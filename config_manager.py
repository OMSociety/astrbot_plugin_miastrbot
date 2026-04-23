# -*- coding: utf-8 -*-
"""
miastrbot 配置管理器

支持内存缓存、热更新、环境变量读取、schema 默认值注入
"""

import copy
from typing import Any, Dict, Optional

from astrbot.api import logger


class MiASTRBotConfigManager:
    """插件配置管理器"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化配置管理器
        
        Args:
            config: AstrBot 传入的插件配置
        """
        self._raw_config = config or {}
        self._cache: Dict[str, Any] = {}
        self._cache_valid = False
        self._load_schema_defaults()
        self._apply_env_overrides()
    
    def _load_schema_defaults(self):
        """从 schema 注入默认值"""
        try:
            import json, os
            schema_path = os.path.join(
                os.path.dirname(__file__), "_conf_schema.json"
            )
            if os.path.exists(schema_path):
                schema = json.load(open(schema_path, encoding="utf-8"))
                self._inject_defaults(self._raw_config, schema)
        except Exception as e:
            logger.warning(f"[miastrbot] 加载 schema 默认值失败: {e}")
    
    def _inject_defaults(self, target: dict, schema: dict):
        """递归注入 schema 默认值"""
        for key, value in schema.items():
            if isinstance(value, dict) and "items" in value:
                # 有 items 说明是 section（如 xiaomi、mihome）
                if key not in target:
                    target[key] = {}
                if isinstance(target[key], dict) and "items" in value:
                    self._inject_defaults(target[key], value["items"])
            elif isinstance(value, dict) and "default" in value:
                target.setdefault(key, value["default"])

    def _apply_env_overrides(self):
        """环境变量覆盖（最高优先级）"""
        env_mappings = {
            "MIASTRBOT_SPEAKER_USER_ID": "speaker.user_id",
            "MIASTRBOT_SPEAKER_SERVICE_TOKEN": "speaker.service_token",
            "MIASTRBOT_SPEAKER_DEVICE_ID": "speaker.device_id",
            "MIASTRBOT_SPEAKER_HARDWARE": "speaker.hardware",
            "MIASTRBOT_SPEAKER_MODEL": "speaker.model",
            "MIASTRBOT_WEATHER_API_KEY": "weather.weather_api_key",
            "MIASTRBOT_WEATHER_CITY": "weather.weather_city",
            "MIASTRBOT_TTS_TYPE": "tts.engine",
            "MIASTRBOT_TTS_VOICE": "tts.voice",
            "MIASTRBOT_VOLCENGINE_APPID": "tts.volcengine_appid",
            "MIASTRBOT_VOLCENGINE_ACCESS_TOKEN": "tts.volcengine_access_token",
            "MIASTRBOT_VOLCENGINE_VOICE_TYPE": "tts.volcengine_voice_type",
        }
        import os
        for env_key, config_key in env_mappings.items():
            val = os.getenv(env_key)
            if val:
                self.set(config_key, val)
                logger.debug(f"[miastrbot] 环境变量覆盖: {env_key} -> {config_key}")
    
    def _ensure_cache(self):
        """确保缓存已填充"""
        if not self._cache_valid:
            try:
                self._cache = copy.deepcopy(self._raw_config)
            except Exception:
                import json
                self._cache = json.loads(
                    json.dumps(self._raw_config, default=str)
                )
            self._cache_valid = True
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项（支持点号路径）
        
        Args:
            key: 配置键，支持 "section.key" 格式
            default: 默认值
        
        Returns:
            配置值
        """
        self._ensure_cache()
        
        keys = key.split(".")
        value = self._cache
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value if value is not None else default
    
    def set(self, key: str, value: Any):
        """
        设置配置项（仅影响内存，不写入文件）
        
        Args:
            key: 配置键，支持 "section.key" 格式
            value: 配置值
        """
        self._ensure_cache()
        
        keys = key.split(".")
        target = self._cache
        raw_target = self._raw_config
        
        # 同步更新 _raw_config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
                raw_target[k] = {}
            target = target[k]
            raw_target = raw_target[k]
        
        target[keys[-1]] = value
        raw_target[keys[-1]] = value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """
        获取整个配置节
        
        Args:
            section: 节名称，如 "xiaomi", "speaker"
        
        Returns:
            配置节字典
        """
        return self.get(section, {})
    
    def reload(self):
        """重新加载配置（热更新）"""
        self._cache_valid = False
        logger.info("[miastrbot] 配置已重新加载")
    
    @property
    def raw(self) -> Dict[str, Any]:
        """获取原始配置"""
        return self._raw_config
