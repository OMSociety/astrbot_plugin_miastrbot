# -*- coding: utf-8 -*-
"""
米家设备服务 (MiHomeService)

使用 mijiaAPI 实现米家设备管理，支持：
- 二维码授权登录
- 设备列表查询
- 设备别名 → DID 解析（模糊匹配）
- 设备控制（开/关/调亮度等）
- 设备状态查询
"""

import sys
import os as _os
_plugin_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_astrbotsite = _os.path.join(_plugin_root, "..", "..", "data", "site-packages")
_astrbotsite2 = "/usr/local/lib/python3.12/site-packages"
for _p in [_astrbotsite, _astrbotsite2]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import asyncio
import time
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from astrbot.api import logger

try:
    from mijiaAPI import mijiaAPI, mijiaDevice
    MIJIA_API_AVAILABLE = True
except ImportError:
    MIJIA_API_AVAILABLE = False
    logger.warning("[miastrbot] mijiaAPI 未安装，米家设备控制功能将不可用")

from .._data_manager import MiAstrBotDataManager

LOGIN_IDLE = "idle"
LOGIN_RUNNING = "running"


class MiHomeServiceError(Exception):
    """米家服务异常基类"""
    pass


class MiHomeAuthError(MiHomeServiceError):
    """认证异常"""
    pass


class MiHomeControlError(MiHomeServiceError):
    """设备控制异常"""
    pass


class MiHomeService:
    """
    米家设备服务
    
    使用二维码授权方式管理米家设备。
    支持设备别名解析（模糊匹配）和设备缓存。
    """
    
    def __init__(self, config: Dict[str, Any], data_manager: MiAstrBotDataManager = None):
        self.config = config
        self.data_dir = config.get(
            "data_dir", "/AstrBot/data/plugins/astrbot_plugin_miastrbot/data"
        )
        self.data_manager = data_manager or MiAstrBotDataManager(self.data_dir)
        
        # API 实例
        self.api = None
        if MIJIA_API_AVAILABLE and self.data_manager.auth_exists():
            try:
                self.api = mijiaAPI(self.data_manager.get_auth_path())
            except Exception as e:
                logger.error(f"[miastrbot] 初始化米家API失败: {e}")
        
        self._api_lock = asyncio.Lock()
        self._login_status = LOGIN_IDLE
        self._login_process: Optional[asyncio.subprocess.Process] = None
        self._worker_script = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)), "_login_worker.py"
        )
        
        # 设备缓存（避免每次查询都调 API）
        self._devices_cache: List[Dict[str, Any]] = []
        self._devices_cache_time: float = 0
        self._devices_cache_ttl: float = 300  # 缓存 5 分钟
        
        # 设备别名 → DID 映射（从设备名提取）
        self._device_alias_map: Dict[str, str] = {}
    
    def is_authenticated(self) -> bool:
        """检查是否已认证"""
        return self.api is not None and self.data_manager.auth_exists()
    
    def _check_api(self):
        """检查 API 是否可用"""
        if not self.api:
            raise MiHomeServiceError("米家服务未初始化，请先登录")
    
    def _refresh_alias_map(self, devices: List[Dict[str, Any]]):
        """从设备列表构建别名映射表"""
        self._device_alias_map.clear()
        for d in devices:
            name = d.get("name", "")
            did = d.get("did", "")
            if name and did:
                # 全名
                self._device_alias_map[name] = did
                # 无符号名
                clean = name.replace("的", "").replace(" ", "")
                self._device_alias_map[clean] = did
                # 单字前缀（如「客厅灯」「卧室灯」）
                if len(name) >= 2:
                    for i in range(len(name)):
                        prefix = name[:i + 1]
                        if prefix not in self._device_alias_map:
                            self._device_alias_map[prefix] = did
    
    def resolve_alias(self, name: str) -> Optional[str]:
        """
        将设备名/别名解析为 DID
        
        支持模糊匹配：
        - 精确匹配
        - 去除「的」后匹配
        - 前缀匹配（取最短匹配）
        
        Args:
            name: 设备名称或别名
        
        Returns:
            DID，未找到返回 None
        """
        if not name:
            return None
        
        name = name.strip()
        
        # 1. 精确匹配
        if name in self._device_alias_map:
            return self._device_alias_map[name]
        
        # 2. 去除「的」后匹配
        clean = name.replace("的", "").replace(" ", "")
        if clean in self._device_alias_map:
            return self._device_alias_map[clean]
        
        # 3. 前缀匹配（最短优先）
        candidates = [
            k for k in self._device_alias_map
            if k in name or name in k
        ]
        if candidates:
            # 选最短的（最精确的）
            return self._device_alias_map[sorted(candidates, key=len)[0]]
        
        return None
    
    @property
    def device_aliases(self) -> Dict[str, str]:
        """返回设备别名映射（供外部使用）"""
        return self._device_alias_map
    
    async def get_login_status(self) -> Dict[str, Any]:
        """获取登录状态"""
        state = self.data_manager.load_state()
        return {
            "auth_exists": self.data_manager.auth_exists(),
            "login_in_progress": self._login_status != LOGIN_IDLE,
            "last_login_at": state.get("last_login_at", ""),
            "last_login_error": state.get("last_login_error", ""),
        }
    
    async def logout(self) -> bool:
        """退出登录，清理认证和缓存"""
        async with self._api_lock:
            if self._login_process and self._login_process.returncode is None:
                try:
                    self._login_process.kill()
                    await self._login_process.wait()
                except ProcessLookupError:
                    pass
                except Exception as e:
                    logger.warning(f"[miastrbot] 强制终止登录进程失败: {e}")
                finally:
                    self._login_process = None
            
            self._login_status = LOGIN_IDLE
            ok = self.data_manager.clear_auth_file()
            
            if MIJIA_API_AVAILABLE:
                self.api = mijiaAPI(self.data_manager.get_auth_path())
            
            self.data_manager.update_state(
                last_login_at="", last_login_error="",
            )
            
            # 清理缓存
            self._devices_cache.clear()
            self._device_alias_map.clear()
            
            return ok
    
    async def login(self, qr_callback: Callable[[str], Any] = None) -> Dict[str, Any]:
        """
        启动二维码登录流程（异步非阻塞）
        
        Args:
            qr_callback: 回调函数，获取到二维码URL时调用
        
        Returns:
            登录状态信息（立即返回，不等待扫码完成）
        """
        if self._login_status != LOGIN_IDLE:
            return {"status": "in_progress"}
        
        if not MIJIA_API_AVAILABLE:
            return {"status": "error", "message": "mijiaAPI 未安装"}
        
        logger.info("[miastrbot] 启动米家登录流程")
        asyncio.create_task(self._run_login_background(qr_callback))
        return {"status": "started", "message": "登录流程已启动，请等待二维码"}
    
    async def _run_login_background(self, qr_callback: Callable[[str], Any] = None):
        """后台运行登录流程（内部方法）"""
        self._login_status = LOGIN_RUNNING
        full_buffer = ""
        proc = None
        qr_found = False
        
        try:
            async with self._api_lock:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-u", self._worker_script,
                    self.data_manager.get_auth_path(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                self._login_process = proc
                if proc.stdout is None:
                    raise MiHomeServiceError("Stdout 管道损坏")
            
            while True:
                chunk = await proc.stdout.read(256)
                if not chunk:
                    break
                
                text = chunk.decode("utf-8", errors="replace")
                full_buffer = (full_buffer + text)[-16384:]
                
                if not qr_found and qr_callback:
                    url = self._extract_qr_url(full_buffer)
                    if url and self._is_likely_qr_login_url(url):
                        qr_found = True
                        await qr_callback(url)
                        logger.info("[miastrbot] 二维码 URL 已推送")
                
                for line in text.split("\n"):
                    if line.strip():
                        logger.debug(f"[Sandbox] {line.strip()}")
            
            returncode = await proc.wait()
            
            if returncode != 0:
                error_msg = full_buffer.split("\n")[-5] if full_buffer else "未知错误"
                self.data_manager.update_state(
                    last_login_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_login_error=f"登录失败: {error_msg}",
                )
                logger.error(f"[miastrbot] 登录失败: {error_msg}")
            else:
                self.data_manager.update_state(
                    last_login_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_login_error="",
                )
                self.api = mijiaAPI(self.data_manager.get_auth_path())
                logger.info("[miastrbot] 登录成功")
                # 登录成功后刷新缓存
                await self._refresh_devices_cache()
            
        except asyncio.CancelledError:
            logger.info("[miastrbot] 登录流程被取消")
            if proc:
                proc.terminate()
        except Exception as e:
            logger.error(f"[miastrbot] 登录异常: {e}")
            self.data_manager.update_state(
                last_login_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_login_error=f"登录异常: {e}",
            )
        finally:
            self._login_status = LOGIN_IDLE
            self._login_process = None
    
    def _extract_qr_url(self, buffer_text: str) -> str:
        """从输出缓冲区提取二维码登录链接"""
        import re
        patterns = [
            r'(https://account\.xiaomi\.com/[^\s\'"]*/qr(?:/[^\s\'"]*)?(?:\?[^\s\'"]*)?)',
            r'(https://api\.io\.micloud\.xiaomi\.com/[^\s\'"]*/qr(?:/[^\s\'"]*)?(?:\?[^\s\'"]*)?)',
            r'二维码[：:]\s*(https://[^\s]+)',
            r'URL[：:]\s*(https://[^\s]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, buffer_text)
            if match:
                return match.group(1).replace("&amp;", "&")
        return ""

    def _is_likely_qr_login_url(self, url: str) -> bool:
        """判断 URL 是否像小米扫码登录链接"""
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            path = (parsed.path or "").lower()
            if host not in {"account.xiaomi.com", "api.io.micloud.xiaomi.com"}:
                return False
            path_segments = [seg for seg in path.split("/") if seg]
            query_keys = {k.lower() for k in parse_qs(parsed.query or "").keys()}
            return (
                "qr" in path_segments
                or "qr" in query_keys
                or "ticket" in query_keys
            )
        except Exception as e:
            logger.debug(f"[miastrbot] 二维码链接校验失败: {type(e).__name__}")
            return False
    
    async def _refresh_devices_cache(self):
        """刷新设备缓存并重建别名映射"""
        try:
            self._check_api()
            async with self._api_lock:
                self.api.login()
                devices = self.api.get_devices_list()
                self._devices_cache = [
                    {
                        "did": d.get("did", ""),
                        "name": d.get("name", ""),
                        "model": d.get("model", ""),
                        "token": d.get("token", ""),
                    }
                    for d in devices
                ]
                self._devices_cache_time = time.time()
                self._refresh_alias_map(self._devices_cache)
                logger.info(f"[miastrbot] 设备缓存已刷新，共 {len(self._devices_cache)} 个设备")
        except Exception as e:
            logger.error(f"[miastrbot] 刷新设备缓存失败: {e}")
    
    async def list_devices(self) -> List[Dict[str, Any]]:
        """
        获取米家设备列表（带缓存）
        
        Returns:
            设备列表
        """
        # 缓存未过期直接返回
        if self._devices_cache and (time.time() - self._devices_cache_time) < self._devices_cache_ttl:
            return self._devices_cache
        
        await self._refresh_devices_cache()
        return self._devices_cache
    
    # 别名，供 WebUI 调用
    get_devices = list_devices
    
    async def control_device(self, name_or_did: str, action: str, params: Dict = None) -> Dict[str, Any]:
        """
        控制米家设备
        
        支持两种调用方式：
        1. control_device("客厅灯", "开") — 通过设备名/别名
        2. control_device("123456789", "开") — 通过 DID
        
        Args:
            name_or_did: 设备名称、别名或 DID
            action: 动作名称（开/关/on/off/调亮/调暗 等）
            params: 额外参数（亮度百分比、温度等）
        
        Returns:
            执行结果字典 {"success": bool, "message": str}
        """
        self._check_api()
        
        # 解析 DID
        did = self.resolve_alias(name_or_did) or name_or_did
        
        # 规范化动作
        action_map = {
            "开": "on", "打开": "on", "启动": "on",
            "关": "off", "关闭": "off", "停止": "off",
        }
        normalized_action = action_map.get(action, action)
        
        async with self._api_lock:
            try:
                device = mijiaDevice(self.api, did=did, sleep_time=1.0)
                result = device.execute_action(normalized_action, params or {})
                
                if result:
                    logger.info(f"[miastrbot] 设备 {name_or_did} 执行 {action} 成功")
                    return {"success": True, "message": f"{name_or_did} 已{action}"}
                else:
                    return {"success": False, "message": f"{name_or_did} 执行{action}失败"}
            
            except Exception as e:
                logger.error(f"[miastrbot] 控制设备 {name_or_did} 失败: {e}")
                raise MiHomeControlError(f"控制设备 {name_or_did} 失败: {e}")
    
    async def get_device_status(self, name_or_did: str) -> Dict[str, Any]:
        """
        获取米家设备当前状态
        
        Args:
            name_or_did: 设备名称、别名或 DID
        
        Returns:
            设备状态字典 {"online": bool, "properties": dict}
        """
        self._check_api()
        
        did = self.resolve_alias(name_or_did) or name_or_did
        
        async with self._api_lock:
            try:
                device = mijiaDevice(self.api, did=did, sleep_time=1.0)
                props = device.get_prop(
                    ["power", "brightness", "temperature", "mode"]
                )
                return {"online": True, "properties": props or {}}
            except Exception as e:
                logger.error(f"[miastrbot] 查询设备 {name_or_did} 状态失败: {e}")
                return {"online": False, "error": str(e)}
