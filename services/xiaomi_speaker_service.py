# -*- coding: utf-8 -*-
"""
小爱音箱服务 (XiaomiSpeakerService)

基于 Cookie 认证的小爱音箱控制服务。

工作原理（参考 xiaogpt 项目）:
1. 轮询小爱音箱状态，获取用户语音命令
2. 将语音命令发送给 AI 处理
3. AI 回答通过 TTS 播报回小爱音箱

用户需要提供 Cookie 信息，可通过以下方式获取：
1. 使用 miservice_fork: `micli list` 自动获取
2. 抓包获取: 访问 https://userprofile.mina.mi.com/device_profile/v2/conversation

参考: https://github.com/yihong0618/xiaogpt
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import aiohttp

from astrbot.api import logger

# API 端点
MINA_API_HOST = "api2.mina.mi.com"
LATEST_ASK_API = "https://userprofile.mina.mi.com/device_profile/v2/conversation?source=dialogu&hardware={hardware}&timestamp={timestamp}&limit=2"

# 硬件型号对应的命令
HARDWARE_COMMAND_DICT = {
    "LX06": ("5-1", "5-5"),
    "L05C": ("5-3", "5-4"),
    "LX04": ("5-1", "5-4"),
    "L05B": ("5-3", "5-4"),
    "X10A": ("7-3", "7-4"),
    "L07A": ("5-1", "5-5"),
    "LX5A": ("5-1", "5-5"),
    "X08E": ("7-3", "7-4"),
    "L15A": ("7-3", "7-4"),
    "X6A": ("7-3", "7-4"),
}


class XiaomiSpeakerError(Exception):
    """小爱音箱服务异常基类"""
    pass


class XiaomiSpeakerAuthError(XiaomiSpeakerError):
    """认证异常"""
    pass


class XiaomiSpeakerService:
    """
    小爱音箱服务
    
    使用 Cookie 认证，控制小爱音箱的语音交互。
    
    配置项:
        hardware: 设备型号（小爱音箱屁股上的型号，如 L05C、LX06）
        device_id: 设备 DID（可从 miservice_fork 的 micli list 获取）
        cookie: Cookie 字符串（格式: deviceId=xxx; serviceToken=xxx; userId=xxx）
        user_id: 小米账号 userId
        service_token: micoapi serviceToken
        device_id: 小爱音箱设备 ID
    
    使用方式:
        1. 初始化: service = XiaomiSpeakerService(config)
        2. 登录: await service.login()
        3. 轮询语音: async for query in service.poll_voice():
        4. TTS 播报: await service.speak("你好")
    """
    
    def __init__(self, config: Dict[str, Any], data_dir: str = None):
        self.config = config
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data"
        )
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 硬件配置
        self.hardware = config.get("hardware", "L05C")
        self.device_id = config.get("device_id", "") or os.getenv("MI_DID", "")
        
        # Cookie 配置
        self.user_id = config.get("user_id", "")
        self.service_token = config.get("service_token", "")
        self.cookie = config.get("cookie", "")
        
        # 如果提供了完整 cookie，解析出各个字段
        if self.cookie and not (self.user_id and self.service_token):
            self._parse_cookie(self.cookie)
        
        # Token 文件路径
        self.token_path = os.path.join(self.data_dir, "speaker_token.json")
        
        # aiohttp session
        self._session: Optional[aiohttp.ClientSession] = None
        
        # 轮询状态
        self._last_timestamp = 0
        self._running = False
        
        # AI 回调（用于处理语音命令）
        self.ai_handler = None
        
        logger.info(f"[miastrbot] 小爱音箱服务初始化，型号: {self.hardware}")
    
    def _parse_cookie(self, cookie: str):
        """解析 Cookie 字符串"""
        for part in cookie.split(";"):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip()
                if key == "userId":
                    self.user_id = value.strip()
                elif key == "serviceToken":
                    self.service_token = value.strip()
                elif key == "deviceId":
                    if not self.device_id:
                        self.device_id = value.strip()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """关闭 session"""
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "User-Agent": "MiHome/6.0.103 (com.xiaomi.mihome; build:6.0.103.1; iOS 14.4.0) Alamofire/6.0.103 MICO/iOSApp/appStore/6.0.103",
            "Content-Type": "application/json",
        }
    
    def _get_cookies(self) -> Dict[str, str]:
        """获取 Cookie"""
        return {
            "userId": self.user_id,
            "serviceToken": self.service_token,
        }
    
    async def login(self) -> bool:
        """
        验证 Cookie 是否有效
        
        Returns:
            是否登录成功
        
        Raises:
            XiaomiSpeakerAuthError: 认证失败
        """
        if not (self.user_id and self.service_token):
            raise XiaomiSpeakerAuthError(
                "未配置 Cookie，请提供 user_id、service_token 或完整 cookie"
            )
        
        # 测试 API 调用
        session = await self._get_session()
        try:
            url = f"https://{MINA_API_HOST}/admin/v2/device_list"
            async with session.get(
                url,
                cookies=self._get_cookies(),
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    raise XiaomiSpeakerAuthError(
                        "Cookie 已过期，请重新获取"
                    )
                elif resp.status != 200:
                    text = await resp.text()
                    raise XiaomiSpeakerAuthError(f"API 请求失败: {resp.status}")
                
                data = await resp.json()
                devices = data.get("data", [])
                
                # 保存 token
                self._save_token()
                
                logger.info(f"[miastrbot] 小爱音箱登录成功，获取到 {len(devices)} 个设备")
                return True
                
        except aiohttp.ClientError as e:
            raise XiaomiSpeakerAuthError(f"网络请求失败: {e}")
    
    def _save_token(self):
        """保存 token 到文件"""
        token_data = {
            "user_id": self.user_id,
            "service_token": self.service_token,
            "device_id": self.device_id,
            "hardware": self.hardware,
        }
        with open(self.token_path, "w") as f:
            json.dump(token_data, f, indent=2)
    
    async def load_token(self) -> bool:
        """从文件加载 token"""
        if not os.path.exists(self.token_path):
            return False
        
        try:
            with open(self.token_path) as f:
                data = json.load(f)
            
            self.user_id = data.get("user_id", "")
            self.service_token = data.get("service_token", "")
            self.device_id = data.get("device_id", "") or self.device_id
            self.hardware = data.get("hardware", self.hardware)
            
            if not self.user_id or not self.service_token:
                return False
            
            logger.info("[miastrbot] 小爱音箱 token 加载成功")
            return True
            
        except Exception as e:
            logger.error(f"[miastrbot] token 加载失败: {e}")
            return False
    
    async def get_device_id(self) -> str:
        """获取设备 DID，如果没有配置则从列表选择第一个"""
        if self.device_id:
            return self.device_id
        
        session = await self._get_session()
        url = f"https://{MINA_API_HOST}/admin/v2/device_list"
        
        async with session.get(
            url,
            cookies=self._get_cookies(),
            headers=self._get_headers(),
        ) as resp:
            data = await resp.json()
            devices = data.get("data", [])
            
            # 筛选小爱音箱
            speakers = [
                d for d in devices
                if "speaker" in d.get("name", "").lower() or "音箱" in d.get("name", "")
            ]
            
            if speakers:
                self.device_id = speakers[0].get("deviceID", "")
            elif devices:
                self.device_id = devices[0].get("deviceID", "")
            
            if self.device_id:
                logger.info(f"[miastrbot] 使用设备: {self.device_id}")
                return self.device_id
            
            raise XiaomiSpeakerError("未找到可用的小爱音箱设备")
    
    async def get_latest_command(self) -> Optional[Dict[str, Any]]:
        """
        获取最新的语音命令
        
        Returns:
            语音命令字典，包含 query（命令文本）等字段。如果没有新命令返回 None。
        """
        session = await self._get_session()
        timestamp = str(int(time.time() * 1000))
        
        url = LATEST_ASK_API.format(hardware=self.hardware, timestamp=timestamp)
        
        try:
            async with session.get(
                url,
                cookies=self._get_cookies(),
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                records = data.get("data", {}).get("records", [])
                
                if not records:
                    return None
                
                record = records[0]
                record_time = record.get("time", 0)
                
                # 检查是否是新记录
                if record_time > self._last_timestamp:
                    self._last_timestamp = record_time
                    return {
                        "query": record.get("query", ""),
                        "time": record_time,
                        "request_id": record.get("requestId", ""),
                        "answers": record.get("answers", []),
                    }
                
                return None
                
        except Exception as e:
            logger.debug(f"[miastrbot] 获取语音命令失败: {e}")
            return None
    
    async def speak(self, text: str) -> bool:
        """
        TTS 播报文字
        
        Args:
            text: 要播报的文本
        
        Returns:
            是否成功
        """
        if not self.device_id:
            await self.get_device_id()
        
        session = await self._get_session()
        url = f"https://{MINA_API_HOST}/remote/ubus"
        
        data = {
            "deviceId": self.device_id,
            "method": "text_to_speech",
            "path": "mibrain",
            "message": json.dumps({"text": text}),
        }
        
        try:
            async with session.post(
                url,
                json=data,
                cookies=self._get_cookies(),
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                code = result.get("data", {}).get("code", -1)
                
                if code == 0:
                    logger.info(f"[miastrbot] TTS 播报成功: {text[:30]}...")
                    return True
                else:
                    logger.error(f"[miastrbot] TTS 失败: {result}")
                    return False
                    
        except Exception as e:
            logger.error(f"[miastrbot] TTS 异常: {e}")
            return False
    
    async def stop_playing(self) -> bool:
        """停止当前播放"""
        if not self.device_id:
            await self.get_device_id()
        
        session = await self._get_session()
        url = f"https://{MINA_API_HOST}/remote/ubus"
        
        data = {
            "deviceId": self.device_id,
            "method": "player_play_operation",
            "path": "mediaplayer",
            "message": json.dumps({"action": "pause", "media": "app_ios"}),
        }
        
        try:
            async with session.post(
                url,
                json=data,
                cookies=self._get_cookies(),
                headers=self._get_headers(),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False
    
    async def get_play_status(self) -> Dict[str, Any]:
        """获取播放状态"""
        if not self.device_id:
            await self.get_device_id()
        
        session = await self._get_session()
        url = f"https://{MINA_API_HOST}/remote/ubus"
        
        data = {
            "deviceId": self.device_id,
            "method": "player_get_play_status",
            "path": "mediaplayer",
            "message": json.dumps({"media": "app_ios"}),
        }
        
        try:
            async with session.post(
                url,
                json=data,
                cookies=self._get_cookies(),
                headers=self._get_headers(),
            ) as resp:
                return await resp.json()
        except Exception as e:
            logger.error(f"[miastrbot] 获取播放状态失败: {e}")
            return {}
    
    async def poll_voice(self, keywords: List[str] = None, poll_interval: float = 2.0):
        """
        轮询语音命令（异步生成器）
        
        Args:
            keywords: 触发关键词列表，如 ["请", "帮我"]
            poll_interval: 轮询间隔（秒）
        
        Yields:
            语音命令字典
        """
        if keywords is None:
            keywords = ["请", "帮我"]
        
        self._running = True
        logger.info(f"[miastrbot] 开始轮询语音命令，关键词: {keywords}")
        
        while self._running:
            try:
                command = await self.get_latest_command()
                
                if command:
                    query = command.get("query", "")
                    
                    # 检查是否包含触发关键词
                    if any(kw in query for kw in keywords):
                        # 去除关键词
                        for kw in keywords:
                            if query.startswith(kw):
                                query = query[len(kw):].strip()
                                break
                        command["query"] = query
                        yield command
                
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f"[miastrbot] 轮询异常: {e}")
                await asyncio.sleep(poll_interval * 2)
        
        logger.info("[miastrbot] 停止轮询语音命令")
    
    def stop_polling(self):
        """停止轮询"""
        self._running = False
    
    @property
    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        return bool(self.user_id and self.service_token)
    
    def gen_auth_url(self) -> str:
        """
        生成授权 URL（用于获取 Cookie）
        
        Returns:
            授权页面 URL
        """
        return "https://userprofile.mina.mi.com/device_profile/v2/conversation"
    
    @staticmethod
    def get_cookie_from_miservice() -> Dict[str, str]:
        """
        从 miservice_fork 获取 Cookie（需要在本地运行）
        
        用户需要先安装 miservice_fork，然后运行:
            micli list
        
        Returns:
            包含 userId, serviceToken, deviceId 的字典
        """
        # 这是一个示例，实际需要用户手动操作
        return {
            "userId": "从 micli list 输出中复制",
            "serviceToken": "从 micli list 输出中复制",
            "deviceId": "从 micli list 输出中复制",
        }
