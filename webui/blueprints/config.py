# -*- coding: utf-8 -*-
"""
配置蓝图 - 配置管理
"""
from fastapi import APIRouter
from typing import Optional, Dict, Any
from ..dependencies import get_container

router = APIRouter()

SENSITIVE_KEYWORDS = {
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "key",
    "account",
    "cookie",
    "credential",
    "access_token",
}


def _is_sensitive_key(key: str) -> bool:
    key_l = (key or "").lower()
    return any(word in key_l for word in SENSITIVE_KEYWORDS)


def _sanitize_config(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, sub_value in value.items():
            if _is_sensitive_key(key):
                sanitized[key] = "***" if sub_value else ""
            else:
                sanitized[key] = _sanitize_config(sub_value, key)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_config(item, parent_key) for item in value]
    if _is_sensitive_key(parent_key):
        return "***" if value else ""
    return value


@router.get("/config")
async def get_config():
    """获取当前配置（脱敏）"""
    container = get_container()
    if not container or not container.config_manager:
        return {"success": False, "message": "配置管理器未初始化"}
    
    try:
        raw_config = container.config_manager.raw
        safe_config = _sanitize_config(raw_config)
        return {"success": True, "data": safe_config}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/config/tts")
async def update_tts_config(tts_type: str, voice: Optional[str] = None):
    """更新 TTS 配置"""
    container = get_container()
    if not container or not container.config_manager:
        return {"success": False, "message": "配置管理器未初始化"}
    
    try:
        container.config_manager.set("tts.engine", tts_type)
        container.config_manager.set("tts.type", tts_type)  # 兼容旧键 tts.type
        if voice:
            container.config_manager.set("tts.voice", voice)
        
        return {"success": True, "message": "TTS 配置已更新，重启插件后生效"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/config/speaker")
async def update_speaker_config(model: str, stream: bool = True):
    """更新音箱对话配置"""
    container = get_container()
    if not container or not container.config_manager:
        return {"success": False, "message": "配置管理器未初始化"}
    
    try:
        container.config_manager.set("speaker.model", model)
        container.config_manager.set("speaker.stream", stream)
        
        return {"success": True, "message": "音箱配置已更新，重启插件后生效"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.get("/config/supported-models")
async def get_supported_models():
    """获取支持的 LLM 模型列表"""
    # 参考 xiaogpt 支持的模型
    models = [
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "OpenAI"},
        {"id": "gpt-4o", "name": "GPT-4o", "provider": "OpenAI"},
        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "provider": "OpenAI"},
        {"id": "claude-3-haiku", "name": "Claude 3 Haiku", "provider": "Anthropic"},
        {"id": "gemini-pro", "name": "Gemini Pro", "provider": "Google"},
        {"id": "moonshot-v1-8k", "name": "Moonshot (Kimi)", "provider": "Moonshot"},
        {"id": "qwen-turbo", "name": "通义千问", "provider": "阿里云"},
        {"id": "doubao-pro", "name": "豆包", "provider": "字节跳动"},
    ]
    return {"success": True, "data": models}

@router.get("/config/supported-tts")
async def get_supported_tts():
    """获取支持的 TTS 引擎列表"""
    tts_engines = [
        {"id": "edge", "name": "Edge TTS", "description": "免费，推荐使用"},
        {"id": "openai", "name": "OpenAI TTS", "description": "需 API Key"},
        {"id": "azure", "name": "Azure TTS", "description": "预留占位，当前版本暂未实现"},
        {"id": "native", "name": "Native TTS", "description": "系统原生 TTS（本地语音合成）"},
        {"id": "volcengine", "name": "火山云 TTS", "description": "需 AppID/AccessToken/VoiceType"},
    ]
    return {"success": True, "data": tts_engines}
