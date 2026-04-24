# -*- coding: utf-8 -*-
"""
小爱音箱服务 (XiaomiSpeakerService)

基于 Cookie 认证的小爱音箱控制服务。

工作原理:
1. 轮询小爱音箱状态，获取用户语音命令
2. 将语音命令发送给 AI 处理
3. AI 回答通过 TTS 播报回小爱音箱

用户需要提供 Cookie 信息（从 account.xiaomi.com 登录后 F12 获取）。

参考: https://github.com/yihong0618/xiaogpt
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import aiohttp

from astrbot.api import logger

try:
    from miservice import MiAccount, MiNAService
    MISERVICE_AVAILABLE = True
except ImportError:
    MISERVICE_AVAILABLE = False

# API 端点
MINA_API_HOST = "api2.mina.mi.com"
LATEST_ASK_API = "https://userprofile.mina.mi.com/device_profile/v2/conversation?limit=2&timestamp={timestamp}&requestId={requestId}&source=dialogu&hardware={hardware}"

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
        device_id: 设备 DID（可留空自动选择）
        user_id: 小米账号 userId（从 Cookie 中提取）
        service_token: micoapi serviceToken（从 Cookie 中提取）
    
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
        
        # Cookie 配置（从 account.xiaomi.com F12 获取）
        self.user_id = config.get("user_id", "")
        self.service_token = config.get("service_token", "")
        self.account = config.get("account", "")
        self.password = config.get("password", "")
        
        # Token 文件路径
        self.token_path = os.path.join(self.data_dir, "speaker_token.json")
        
        # aiohttp session
        self._session: Optional[aiohttp.ClientSession] = None
        
        # 轮询状态
        self._last_timestamp = 0
        self._running = False
        self._last_poll_status = None
        self._last_poll_error = None
        self._last_query = ""
        self._last_poll_url = None
        self._auth_invalid_count = 0

        # AI 回调（用于处理语音命令）
        self.ai_handler = None
        
        logger.info(f"[miastrbot] 小爱音箱服务初始化，型号: {self.hardware}")
    
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
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; 000; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/119.0.6045.193 Mobile Safari/537.36 /XiaoMi/HybridView/ micoSoundboxApp/i appVersion/A_2.4.40",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
    
    def _get_cookies(self) -> Dict[str, str]:
        """获取 Cookie"""
        cookies = {
            "userId": self.user_id,
            "serviceToken": self.service_token,
        }
        if self.device_id:
            cookies["deviceId"] = self.device_id
        return cookies
    
    async def login(self) -> bool:
        """
        验证 Cookie 是否有效，或通过账号密码登录获取 token
        
        Returns:
            是否登录成功
        
        Raises:
            XiaomiSpeakerAuthError: 认证失败
        """
        if self.account and self.password and MISERVICE_AVAILABLE:
            # 方式一：账号密码登录（自动获取有效 token）
            logger.info("[miastrbot] 使用账号密码登录小爱音箱...")
            try:
                session_for_login = aiohttp.ClientSession()
                mi_account = MiAccount(
                    session_for_login,
                    self.account,
                    self.password,
                    self.token_path,
                )
                await mi_account.login("micoapi")
                self.mi_account = mi_account
                self.mi_naservice = MiNAService(mi_account)
                
                # 从 token 文件读取 userId 和 serviceToken
                if os.path.exists(self.token_path):
                    with open(self.token_path) as f:
                        user_data = json.load(f)
                    self.user_id = user_data.get("userId", "")
                    micoapi_token = user_data.get("micoapi", [])
                    if isinstance(micoapi_token, list) and len(micoapi_token) >= 2:
                        self.service_token = micoapi_token[1]
                
                await session_for_login.close()
                
                if self.user_id and self.service_token:
                    logger.info(f"[miastrbot] 账号密码登录成功，userId: {self.user_id}")
                    self._auth_invalid_count = 0
                    self._save_token()
                    return True
                else:
                    raise XiaomiSpeakerAuthError("账号密码登录成功但无法解析 token")
                    
            except Exception as e:
                logger.error(f"[miastrbot] 账号密码登录失败: {e}")
                raise XiaomiSpeakerAuthError(f"账号密码登录失败: {e}")
        
        if not (self.user_id and self.service_token):
            raise XiaomiSpeakerAuthError(
                "未配置 user_id 和 service_token，请从 Cookie 中提取这两个值，或配置账号密码自动登录"
            )
        
        # 方式二：手动 Cookie 登录（直接测试 API）
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
                    detail = await resp.text()
                    raise XiaomiSpeakerAuthError(
                        f"Cookie 已过期或无权限，请重新获取: {detail[:120]}"
                    )
                elif resp.status != 200:
                    text = await resp.text()
                    raise XiaomiSpeakerAuthError(f"API 请求失败: {resp.status}, 响应: {text[:120]}")
                
                data = await resp.json()
                devices = data.get("data", [])
                
                # 保存 token
                self._save_token()
                
                self._auth_invalid_count = 0
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
    
    def get_debug_status(self) -> Dict[str, Any]:
        """获取最近一次轮询的调试状态"""
        return {
            "last_poll_status": self._last_poll_status,
            "last_poll_error": self._last_poll_error,
            "last_query": self._last_query,
            "last_poll_url": self._last_poll_url,
            "auth_invalid_count": self._auth_invalid_count,
        }

    async def _build_conversation_urls(self, timestamp: str, request_id: str) -> list[str]:
        """构造对话接口候选 URL（兼容不同服务端参数差异）"""
        return [
            LATEST_ASK_API.format(hardware=self.hardware, timestamp=timestamp, requestId=request_id),
            f"https://userprofile.mina.mi.com/device_profile/v2/conversation?source=dialogue&hardware={self.hardware}&timestamp={timestamp}&limit=2",
            f"https://userprofile.mina.mi.com/device_profile/v2/conversation?source=dialogu&hardware={self.hardware}&timestamp={timestamp}&requestId={request_id}&limit=2",
        ]

    async def get_latest_command(self) -> Optional[Dict[str, Any]]:
        """
        获取最新的语音命令
        
        Returns:
            语音命令字典，包含 query（命令文本）等字段。如果没有新命令返回 None。
        """
        session = await self._get_session()
        if not self.device_id:
            try:
                await self.get_device_id()
            except Exception:
                logger.debug("[miastrbot] 获取设备ID失败，继续尝试请求对话记录")

        timestamp = str(int(time.time() * 1000))
        request_id = uuid.uuid4().hex[:12]
        urls = await self._build_conversation_urls(timestamp=timestamp, request_id=request_id)

        for url in urls:
            self._last_poll_url = url
            try:
                async with session.get(
                    url,
                    cookies=self._get_cookies(),
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    self._last_poll_status = resp.status
                    if resp.status == 200:
                        data = await resp.json()
                        records = data.get("data", {}).get("records", [])

                        if not records:
                            logger.debug("[miastrbot] 对话记录为空")
                            return None

                        record = records[0]
                        record_time = record.get("time", 0)

                        # 检查是否是新记录
                        if record_time > self._last_timestamp:
                            self._last_timestamp = record_time
                            self._last_query = record.get("query", "")
                            self._last_poll_error = None
                            return {
                                "query": record.get("query", ""),
                                "time": record_time,
                                "request_id": record.get("requestId", ""),
                                "answers": record.get("answers", []),
                            }

                        self._last_poll_error = None
                        return None

                    body = None
                    try:
                        body = (await resp.text())[:200]
                    except Exception:
                        body = None

                    if resp.status == 401:
                        self._auth_invalid_count += 1
                        self._last_poll_error = f"HTTP 401 未授权: {body}"
                        logger.warning(
                            "[miastrbot] 获取对话记录返回401（Cookie/Token 无效或过期），请重新执行 /小爱 登录 并更新 Cookie，响应: %s",
                            body,
                        )
                    elif resp.status == 400:
                        self._last_poll_error = f"HTTP 400 参数错误: {body}"
                        logger.warning(
                            "[miastrbot] 获取对话记录返回400，请检查URL参数（source/headers/设备ID），响应: %s",
                            body,
                        )
                    else:
                        self._last_poll_error = f"HTTP {resp.status}: {body}"
                        logger.warning(f"[miastrbot] 获取对话记录失败 HTTP {resp.status}, 响应: {body}")
            except Exception as e:
                self._last_poll_error = str(e)
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
            keywords: 触发关键词列表，如 ["小爱同学", "小爱"]
            poll_interval: 轮询间隔（秒）
        
        Yields:
            语音命令字典
        """
        if keywords is None:
            keywords = ["请", "帮我"]
        keywords = [kw.strip() for kw in keywords if kw and kw.strip()]
        
        self._running = True
        logger.info(f"[miastrbot] 开始轮询语音命令，关键词: {keywords}")
        
        while self._running:
            try:
                command = await self.get_latest_command()
                
                if command:
                    query = (command.get("query", "") or "").strip()
                    logger.info(f"[miastrbot] 轮询收到命令: {query!r}  关键词: {keywords}")
                    
                    # 没配置关键词时，默认放行全部语音
                    matched = not keywords
                    if not matched:
                        matched = any(query.startswith(kw) or kw in query for kw in keywords)
                    
                    if matched:
                        command["query"] = query
                        logger.info(f"[miastrbot] 命令命中关键词，进入 Agent 处理")
                        yield command
                    else:
                        logger.debug(f"[miastrbot] 命令未命中关键词，跳过")
                else:
                    logger.debug("[miastrbot] 本次轮询无新命令")
                
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
