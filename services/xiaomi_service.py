# -*- coding: utf-8 -*-
"""
小爱音箱服务 (XiaomiService) - OAuth 方案

支持多型号：小爱音箱Play增强版(L05C)、小爱音箱Pro(LX06)等

基于 Home Assistant Xiaomi Home 集成的 OAuth 2.0 实现
参考: https://github.com/XiaoMi/ha_xiaomi_home
"""

import asyncio
import json
import logging
import os
import secrets
import hashlib
from typing import Any, Dict, List, Optional

import aiohttp

from astrbot.api import logger

# 小米 OAuth 和 API 配置
OAUTH2_CLIENT_ID = "2882303761520251711"
OAUTH2_AUTH_URL = "https://account.xiaomi.com/oauth2/authorize"
OAUTH2_API_HOST = "ha.api.io.mi.com"
MIHOME_HTTP_API_TIMEOUT = 30


class XiaomiServiceError(Exception):
    """小爱服务异常基类"""
    pass


class XiaomiAuthError(XiaomiServiceError):
    """认证异常"""
    pass


class XiaomiCommandError(XiaomiServiceError):
    """命令执行异常"""
    pass


class XiaomiService:
    """
    小爱音箱服务（OAuth 版本）
    
    支持型号:
    - L05C (小爱音箱Play增强版): 必须使用 command 模式
    - LX06 (小爱音箱Pro): 支持 ubus/command 模式
    - LX04, X10A, L05B: 使用 command 模式
    
    使用方式:
    1. 登录: login() - 使用 OAuth token
    2. 获取设备: get_devices()
    3. 发送TTS: send_tts(text)
    """
    
    # 需要使用 command 模式的型号
    COMMAND_ONLY_MODELS = ["L05C", "LX04", "X10A", "L05B"]
    
    def __init__(self, config: Dict[str, Any], data_dir: str = None):
        """
        初始化小爱服务
        
        Args:
            config: 配置字典
            data_dir: 数据目录（用于存储 token）
        """
        self.config = config
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data"
        )
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.hardware = config.get("hardware", "L05C")
        self.device_id = config.get("device_id", "") or os.getenv("MI_DID", "")
        
        # 根据型号自动选择通信模式
        self.use_command = self.hardware in self.COMMAND_ONLY_MODELS
        
        # OAuth 配置
        self.client_id = OAUTH2_CLIENT_ID
        self.redirect_uri = "http://homeassistant.local:8123"  # 使用 HA 预注册的 URI
        
        # Token 相关
        self.token_path = os.path.join(self.data_dir, "oauth_token.json")
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expires_in: int = 0
        self.token_expires_ts: int = 0
        
        # aiohttp session
        self._session: Optional[aiohttp.ClientSession] = None
        
        # 缓存的设备列表
        self._devices: List[Dict] = []
        
        # 是否已登录
        self._logged_in = False
        
        logger.info(f"[miastrbot] 小爱服务初始化(OAuth)，型号: {self.hardware}")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def _get_headers(self) -> Dict[str, str]:
        """获取 API 请求头（注意：Bearer 后不带空格）"""
        return {
            "Host": OAUTH2_API_HOST,
            "X-Client-BizId": "haapi",
            "Content-Type": "application/json",
            "Authorization": f"Bearer{self.access_token}",  # 小米要求不带空格！
            "X-Client-AppId": self.client_id,
        }
    
    def gen_auth_url(self) -> str:
        """
        生成 OAuth 授权 URL
        
        Returns:
            授权 URL
        """
        device_id = f"ha.{secrets.token_hex(16)}"
        state = hashlib.sha1(f"d={device_id}".encode()).hexdigest()
        
        params = {
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "response_type": "code",
            "device_id": device_id,
            "state": state,
            "skip_confirm": "true",
        }
        
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{OAUTH2_AUTH_URL}?{query}"
    
    async def authorize(self, callback_url: str) -> bool:
        """
        使用回调 URL 完成授权
        
        Args:
            callback_url: OAuth 回调 URL（包含 code 参数）
        
        Returns:
            是否成功
        """
        # 从回调 URL 提取 code
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(callback_url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        
        if not code:
            raise XiaomiAuthError("无法从回调 URL 提取 code")
        
        return await self._get_token(code)
    
    async def _get_token(self, code: str) -> bool:
        """
        用授权码换取 token
        
        Args:
            code: 授权码
        
        Returns:
            是否成功
        """
        # 从回调 URL 提取 device_id
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.redirect_uri)
        device_id = f"ha.{secrets.token_hex(16)}"  # 生成新的 device_id
        
        url = f"https://{OAUTH2_API_HOST}/app/v2/ha/oauth/get_token"
        data = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code": code,
            "device_id": device_id,
        }
        
        session = await self._get_session()
        
        try:
            async with session.post(
                url,
                data={"data": json.dumps(data)},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=MIHOME_HTTP_API_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise XiaomiAuthError(f"Token 请求失败: HTTP {resp.status}")
                
                res_str = await resp.text()
                res_obj = json.loads(res_str)
                
                if res_obj.get("code") != 0:
                    raise XiaomiAuthError(f"Token 获取失败: {res_obj.get('message')}")
                
                result = res_obj.get("result", {})
                
                # 保存 token
                self.access_token = result.get("access_token", "")
                self.refresh_token = result.get("refresh_token", "")
                self.token_expires_in = result.get("expires_in", 0)
                self.token_expires_ts = int(__import__("time").time()) + self.token_expires_in
                
                # 持久化
                with open(self.token_path, "w") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                
                self._logged_in = True
                logger.info("[miastrbot] OAuth token 获取成功")
                return True
                
        except aiohttp.ClientError as e:
            logger.error(f"[miastrbot] Token 请求异常: {e}")
            raise XiaomiAuthError(f"Token 请求失败: {e}")
    
    async def load_token(self) -> bool:
        """
        从文件加载 token
        
        Returns:
            是否成功加载
        """
        if not os.path.exists(self.token_path):
            return False
        
        try:
            with open(self.token_path) as f:
                data = json.load(f)
            
            self.access_token = data.get("access_token", "")
            self.refresh_token = data.get("refresh_token", "")
            self.token_expires_in = data.get("expires_in", 0)
            self.token_expires_ts = data.get("expires_ts", 0)
            
            if not self.access_token:
                return False
            
            self._logged_in = True
            logger.info("[miastrbot] OAuth token 加载成功")
            return True
            
        except Exception as e:
            logger.error(f"[miastrbot] Token 加载失败: {e}")
            return False
    
    async def login(self) -> bool:
        """
        登录（使用已保存的 token）
        
        Returns:
            是否成功
        """
        # 尝试加载已有 token
        if await self.load_token():
            return True
        
        # 需要授权
        auth_url = self.gen_auth_url()
        logger.info(f"[miastrbot] 请访问以下链接授权: {auth_url}")
        raise XiaomiAuthError(f"请先授权，访问: {auth_url}")
    
    async def get_devices(self) -> List[Dict[str, Any]]:
        """
        获取设备列表
        
        Returns:
            设备列表
        """
        if not self._logged_in:
            raise XiaomiAuthError("请先登录")
        
        session = await self._get_session()
        headers = self._get_headers()
        
        # 获取所有设备
        url = f"https://{OAUTH2_API_HOST}/app/v2/home/device_list_page"
        data = {
            "limit": 200,
            "get_split_device": True,
            "get_third_device": True,
            "dids": []  # 空列表获取所有设备
        }
        
        try:
            async with session.post(
                url, json=data, headers=headers,
                timeout=aiohttp.ClientTimeout(total=MIHOME_HTTP_API_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise XiaomiAuthError("Token 已过期，需要重新授权")
                
                result = json.loads(await resp.text())
                
                if result.get("code") != 0:
                    raise XiaomiServiceError(f"获取设备失败: {result.get('message')}")
                
                devices = result.get("result", {}).get("list", [])
                self._devices = [
                    {
                        "did": d.get("did"),
                        "name": d.get("name"),
                        "model": d.get("model"),
                        "online": d.get("isOnline", False),
                    }
                    for d in devices
                ]
                
                logger.info(f"[miastrbot] 获取到 {len(self._devices)} 个设备")
                return self._devices
                
        except aiohttp.ClientError as e:
            logger.error(f"[miastrbot] 获取设备异常: {e}")
            raise XiaomiServiceError(f"获取设备失败: {e}")
    
    async def get_speakers(self) -> List[Dict[str, Any]]:
        """获取小爱音箱设备列表"""
        devices = await self.get_devices()
        return [
            d for d in devices
            if "speaker" in d.get("model", "").lower() or "音箱" in d.get("name", "")
        ]
    
    async def get_device_id(self) -> str:
        """
        获取当前配置的设备 DID
        
        如果未配置，自动从设备列表中选择第一个音箱
        
        Returns:
            设备 DID
        """
        if self.device_id:
            return self.device_id
        
        speakers = await self.get_speakers()
        if not speakers:
            raise XiaomiServiceError("未找到可用的小爱音箱设备")
        
        self.device_id = speakers[0]["did"]
        logger.info(f"[miastrbot] 自动选择设备: {speakers[0]['name']} (DID: {self.device_id})")
        return self.device_id
    
    async def send_tts(self, text: str, did: str = None) -> bool:
        """
        发送 TTS 播报
        
        Args:
            text: 要播放的文字
            did: 设备 DID（可选，默认使用配置的设备）
        
        Returns:
            是否成功
        """
        if not self._logged_in:
            raise XiaomiAuthError("请先登录")
        
        if not did:
            did = await self.get_device_id()
        
        session = await self._get_session()
        headers = self._get_headers()
        
        # TTS 服务: siid=5, aiid=1
        url = f"https://{OAUTH2_API_HOST}/app/v2/miotspec/action"
        data = {
            "params": {
                "did": did,
                "siid": 5,  # 语音播报服务
                "aiid": 1,  # text_to_speech 动作
                "in": [text]
            }
        }
        
        try:
            async with session.post(
                url, json=data, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = json.loads(await resp.text())
                
                if result.get("code") == 0:
                    logger.info(f"[miastrbot] TTS 发送成功: {text[:20]}...")
                    return True
                else:
                    logger.error(f"[miastrbot] TTS 失败: {result}")
                    return False
                    
        except aiohttp.ClientError as e:
            logger.error(f"[miastrbot] TTS 异常: {e}")
            return False
    
    async def send_command(self, command: str, did: str = None) -> Dict[str, Any]:
        """
        发送命令到小爱音箱
        
        Args:
            command: 命令内容
            did: 设备 DID（可选）
        
        Returns:
            执行结果
        """
        # 对于 L05C 等型号，使用 TTS 代替命令
        return {"code": 0, "message": "success"} if await self.send_tts(command, did) else {"code": -1, "message": "failed"}
    
    @property
    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        return self._logged_in
