# -*- coding: utf-8 -*-
"""
小爱音箱服务 (XiaomiService)

支持多型号：小爱音箱Play增强版(L05C)、小爱音箱Pro(LX06)等
参考: https://github.com/yihong0618/xiaogpt
"""

import base64
import hashlib
import json
import re
import os
import asyncio
from typing import Optional, List, Dict, Any, Callable
from urllib.parse import parse_qs, urlparse

from astrbot.api import logger

# 尝试导入 miservice (适配 miservice_fork)
try:
    from miservice import MiAccount, MiIOService, MiNAService, miio_command
    MI_SERVICE_AVAILABLE = True
except ImportError:
    MI_SERVICE_AVAILABLE = False
    logger.warning("[miastrbot] miservice 未安装，TTS等功能将不可用")


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
    小爱音箱服务
    
    支持型号:
    - L05C (小爱音箱Play增强版): 必须使用 command 模式
    - LX06 (小爱音箱Pro): 支持 ubus/command 模式
    - LX04, X10A, L05B: 使用 command 模式
    
    使用方式:
    1. 登录: login(account, password)
    2. 获取设备: get_devices()
    3. 发送TTS: send_tts(text)
    4. 发送命令: send_command(command)
    """
    
    # 需要使用 command 模式的型号
    COMMAND_ONLY_MODELS = ["L05C", "LX04", "X10A", "L05B"]
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化小爱服务
        
        Args:
            config: 配置字典，包含 account, password, device_id, hardware
        """
        self.config = config
        self.hardware = config.get("hardware", "L05C")
        self.device_id = config.get("device_id", "") or os.getenv("MI_DID", "")
        
        # 根据型号自动选择通信模式
        self.use_command = self.hardware in self.COMMAND_ONLY_MODELS
        
        # 服务实例
        self._account: Optional[MiAccount] = None
        self._session: Optional[Any] = None  # aiohttp session for passtoken login
        self._ios_service: Optional[MiIOService] = None
        self._na_service: Optional[MiNAService] = None  # 适配 miservice_fork: MiNAService
        
        # Token缓存
        self._token: Optional[str] = None
        
        # 事件监听回调
        self._event_callback: Optional[Callable] = None
        
        # 是否已登录
        self._logged_in = False
        
        logger.info(f"[miastrbot] 小爱服务初始化，型号: {self.hardware}, 模式: {'command' if self.use_command else 'ubus'}")
    
    async def login(self, account: str = None, password: str = None) -> bool:
        """
        小米账号OAuth登录，支持两种方式：
        1. passtoken 登录（推荐）：使用预授权的 passtoken，跳过密码验证
        2. 密码登录：传统的 username + password 登录

        Args:
            account: 小米账号（优先使用）
            password: 密码（优先使用）

        Returns:
            登录是否成功

        Raises:
            XiaomiAuthError: 认证失败
        """
        if not MI_SERVICE_AVAILABLE:
            raise XiaomiAuthError("miservice 库未安装，请运行: pip install miservice")

        # 获取配置
        config_account = self.config.get("account", "")
        config_password = self.config.get("password", "")
        config_passtoken = self.config.get("passtoken", "")
        config_xiaomi_id = self.config.get("xiaomi_id", "")
        config_did = self.config.get("device_id", "")

        # 优先级：传入参数 > 配置 > 环境变量
        account = account or config_account or os.getenv("MI_USER", "")
        password = password or config_password or os.getenv("MI_PASS", "")
        passtoken = config_passtoken or os.getenv("MI_PASSTOKEN", "")
        xiaomi_id = config_xiaomi_id or account  # 如果没单独配置，用 account 作为 userId

        if not account and not passtoken:
            raise XiaomiAuthError("未提供小米账号或 passtoken，请配置")

        try:
            # 优先使用 passtoken 登录（参考 migpt-next 的实现）
            if passtoken and xiaomi_id:
                logger.info("[miastrbot] 使用 passtoken 登录...")
                # _passtoken_login 内部创建 session，不再在外部创建
                success = await self._passtoken_login(
                    passtoken=passtoken,
                    user_id=xiaomi_id,
                    sid="micoapi"
                )
                if not success:
                    raise XiaomiAuthError("passtoken 登录失败，请检查是否过期")
                # MiNA 登录成功，继续登录 xiaomiio
                try:
                    await self._passtoken_login(passtoken=passtoken, user_id=xiaomi_id, sid="xiaomiio")
                except Exception as sid_err:
                    logger.warning(f"[miastrbot] xiaomiio sid passtoken 登录失败: {sid_err}")
            elif password:
                # 回退到密码登录
                logger.info("[miastrbot] 使用密码登录...")
                if not password:
                    raise XiaomiAuthError("未提供密码，请配置")
                self._account = MiAccount(
                    account,
                    password,
                    os.path.join(os.path.expanduser("~"), ".mi.token")
                )

                sid_supported = True
                try:
                    await self._account.login("micoapi")
                except TypeError:
                    sid_supported = False
                    await self._account.login()
                if sid_supported:
                    try:
                        await self._account.login("xiaomiio")
                    except Exception as sid_err:
                        logger.warning(f"[miastrbot] xiaomiio sid 登录失败: {sid_err}")
            else:
                raise XiaomiAuthError("未提供密码或 passtoken，请至少配置一项")

            # 初始化服务
            self._ios_service = MiIOService(self._account)
            self._na_service = MiNAService(self._account)

            self._logged_in = True
            logger.info("[miastrbot] 小爱账号登录成功")

            return True

        except Exception as e:
            logger.error(f"[miastrbot] 小爱账号登录失败: {e}")
            self._logged_in = False
            raise XiaomiAuthError(f"登录失败: {e}")

    async def _passtoken_login(self, passtoken: str, user_id: str, sid: str) -> bool:
        """
        使用 passtoken 登录（参考 migpt-next 的实现）
        
        passtoken 直接写入 cookie，跳过 serviceLoginAuth2，
        服务端直接返回 location（含 ssecurity）用于获取 serviceToken
        
        注意：此方法内部创建独立的 aiohttp session，避免外部 session 被提前关闭
        """
        import base64
        import hashlib
        import aiohttp
        from urllib.parse import parse_qs, urlparse, quote as urlquote

        # 内部创建临时 session，确保正确管理生命周期
        session = aiohttp.ClientSession()

        try:
            # 创建/复用 MiAccount
            if not self._account:
                from miservice.miaccount import get_random
                self._account = MiAccount(
                    session, user_id, "",
                    os.path.join(os.path.expanduser("~"), ".mi.token")
                )
                self._account.token = {"deviceId": get_random(16).upper()}
            
            self._account.token["userId"] = user_id
            self._account.token["passToken"] = passtoken

            # 调用 serviceLogin（passtoken 直接写 cookie，响应会直接返回 location）
            # 使用 miservice 官方 User-Agent
            ua = "Mistube/2.0.0 (Android 12; Scale/2.625)"
            cookies = {
                "userId": user_id,
                "passToken": passtoken,
                "deviceId": self._account.token.get("deviceId")
            }
            headers = {"User-Agent": ua}
            url = f"https://account.xiaomi.com/pass/serviceLogin?sid={sid}&_json=true&_locale=zh_CN"

            async with session.get(url, cookies=cookies, headers=headers, ssl=False) as r:
                raw = await r.read()
                resp = json.loads(raw[11:])  # 去掉前缀
                logger.debug(f"[miastrbot] serviceLogin 响应: code={resp.get('code')}, has_location=({'location' in resp})")

            if resp.get("code") != 0:
                logger.error(f"[miastrbot] passtoken serviceLogin 失败: {resp}")
                return False

            # 检查是否需要验证码
            notification_url = resp.get("notificationUrl", "")
            if notification_url and "identity/authStart" in notification_url:
                logger.error(f"[miastrbot] passtoken 需要验证码，请重新获取")
                return False

            # 从响应提取 location + ssecurity
            location = resp.get("location")
            # ssecurity 可能是 psecurity
            ssecurity = resp.get("ssecurity") or resp.get("psecurity")
            
            logger.debug(f"[miastrbot] 提取: location={str(location)[:80]}, ssecurity={'有' if ssecurity else '无'}")

            # 从 location 提取 nonce（所有情况都需要处理）
            nonce = ""
            if location and "nonce=" in location:
                nonce = location.split("nonce=")[1].split("&")[0]
            elif "nonce" in resp:
                nonce = resp.get("nonce", "")
            
            # 如果 location 里嵌入了 ssecurity（base64 编码在 auth 参数中），需要解析
            if location and not ssecurity:
                parsed = urlparse(location)
                params = parse_qs(parsed.query)
                # 从 auth 参数解码 ssecurity（base64）
                auth = params.get("auth", [""])[0]
                if auth:
                    try:
                        ssecurity = base64.b64decode(auth).decode().split("_")[0]
                    except Exception:
                        pass

            if not location or not ssecurity:
                logger.error(f"[miastrbot] passtoken 响应缺少 location/ssecurity: {resp}")
                return False

            # 确保 nonce 已提取
            if not nonce:
                logger.error(f"[miastrbot] passtoken 响应缺少 nonce: {resp}")
                return False
            
            # URL 解码 nonce（如果包含编码字符）
            from urllib.parse import unquote
            if '%' in str(nonce):
                nonce = unquote(str(nonce))

            # 计算 clientSign 并获取 serviceToken（使用官方实现方式）
            nsec = "nonce=" + str(nonce) + "&" + ssecurity
            clientSign = base64.b64encode(hashlib.sha1(nsec.encode()).digest()).decode()
            
            logger.debug(f"[miastrbot] 完整 location: {location}")
            logger.debug(f"[miastrbot] 完整 ssecurity: {ssecurity[:20]}..." if ssecurity else "[miastrbot] ssecurity: 无")
            logger.debug(f"[miastrbot] 计算 clientSign: nsec={nsec[:30]}...")
            
            # 官方方式：不传 cookies，只加 clientSign
            login_url = location + "&clientSign=" + urlquote(clientSign)
            logger.debug(f"[miastrbot] 登录请求 URL: {login_url[:150]}...")
            
            async with session.get(login_url, ssl=False) as r:
                logger.debug(f"[miastrbot] 登录响应状态: {r.status}")
                logger.debug(f"[miastrbot] 登录响应 headers: {dict(r.headers)}")
                serviceToken_cookie = r.cookies.get("serviceToken")
                if serviceToken_cookie:
                    serviceToken = serviceToken_cookie.value
                    logger.debug(f"[miastrbot] 从 cookie 获取 serviceToken 成功")
                else:
                    # 尝试从 set-cookie header 解析
                    set_cookie = str(r.headers.get("Set-Cookie", ""))
                    match = re.search(r'serviceToken=([^;]+)', set_cookie)
                    serviceToken = match.group(1) if match else None

                if not serviceToken:
                    logger.error(f"[miastrbot] passtoken 未获取到 serviceToken")
                    return False

            # 保存 token
            self._account.token[sid] = (ssecurity, serviceToken)
            logger.info(f"[miastrbot] passtoken 登录成功 (sid={sid})")
            return True

        finally:
            # 关闭内部 session
            await session.close()

    def _reinit_services(self):
        """重建所有服务（重登后调用，避免复用旧 session）"""
        if self._account:
            token_preview = getattr(self._account, "token", None) or "N/A"
            if isinstance(token_preview, str) and len(token_preview) > 20:
                token_preview = token_preview[:10] + "..." + token_preview[-5:]
            logger.info(f"[miastrbot] 重登后重建服务，token预览: {token_preview}")
            self._ios_service = MiIOService(self._account)
            self._na_service = MiNAService(self._account)
            logger.info("[miastrbot] IO service 和 NA service 已重建")

    async def _relogin_if_possible(self) -> bool:
        """在凭证可用时尝试重新登录一次，重建 NA service"""
        account = self.config.get("account") or os.getenv("MI_USER", "")
        password = self.config.get("password") or os.getenv("MI_PASS", "")
        if not account or not password:
            logger.warning("[miastrbot] 自动重登失败: 未配置账号密码")
            return False
        try:
            # 清除旧 token 缓存，强制重新认证
            if self._account and hasattr(self._account, 'token'):
                self._account.token = None
            if self._account and hasattr(self._account, 'token_store') and self._account.token_store:
                try:
                    # os 已在文件顶部导入
                    if os.path.exists(self._account.token_store.token_path):
                        os.remove(self._account.token_store.token_path)
                        logger.info(f"[miastrbot] 已删除旧token文件: {self._account.token_store.token_path}")
                except Exception as rm_err:
                    logger.warning(f"[miastrbot] 删除旧token文件失败: {rm_err}")
            
            success = await self.login(account=account, password=password)
            if success:
                # 记录新 token 状态
                token_info = self._account.token if self._account else {}
                token_previews = {
                    k: (v[:8]+"..." if isinstance(v, str) and len(v) > 20 else v)
                    for k, v in (token_info or {}).items()
                }
                logger.info(f"[miastrbot] 自动重登成功，token状态: {token_previews}")
                self._reinit_services()
                logger.info("[miastrbot] IO/NA service 已重建")
            return success
        except Exception as e:
            logger.warning(f"[miastrbot] 自动重登失败: {e}")
            return False

    def _extract_audio_devices(self, device_list_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """筛选并标准化小爱音箱设备列表"""
        devices: List[Dict[str, Any]] = []
        for device in device_list_raw or []:
            if device.get("extra", {}).get("audio"):
                devices.append({
                    "id": device.get("id"),
                    "did": device.get("did"),
                    "name": device.get("name"),
                    "hardware": device.get("hardware"),
                    "token": device.get("token"),
                })
        return devices
    
    async def get_devices(self) -> List[Dict[str, Any]]:
        """
        获取绑定的小爱音箱设备列表
        
        Returns:
            设备列表
        
        Raises:
            XiaomiAuthError: 未登录或Token过期
        """
        if not self._logged_in:
            raise XiaomiAuthError("请先调用 login() 登录")
        
        MAX_RETRIES = 2  # 最多重试2次
        last_error = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                # 首次或重试后需重建服务（避免复用旧session）
                if attempt > 0:
                    self._reinit_services()
                logger.info(f"[miastrbot] 调用 device_list，attempt={attempt+1}")
                device_list_raw = await self._na_service.device_list()
                devices = self._extract_audio_devices(device_list_raw)
                logger.info(f"[miastrbot] 获取到 {len(devices)} 个小爱音箱设备")
                return devices
            except Exception as e:
                last_error = e
                err_str = str(e)
                # 尝试从错误信息提取 HTTP 状态码
                import re
                http_code = re.search(r"HTTP (\d+)", err_str) or re.search(r"status.?(\d{3})", err_str, re.I)
                http_code = http_code.group(1) if http_code else "N/A"
                logger.warning(f"[miastrbot] 获取设备列表失败 (尝试 {attempt+1}/{MAX_RETRIES+1}) HTTP={http_code}: {e}")
                if attempt < MAX_RETRIES:
                    # 检查是否是认证错误（401/403），非认证错误直接退出
                    if http_code not in ("401", "403", "N/A"):
                        logger.warning(f"[miastrbot] 非认证错误 {http_code}，跳过重登")
                        break
                    logger.info(f"[miastrbot] 尝试自动重登...")
                    relogin_ok = await self._relogin_if_possible()
                    if not relogin_ok:
                        logger.warning(f"[miastrbot] 自动重登失败，放弃重试")
                        break
        
        logger.error(f"[miastrbot] 获取设备列表最终失败: {last_error}")
        raise XiaomiAuthError(f"获取设备失败: {last_error}")
    
    async def get_device_id(self) -> str:
        """
        获取当前配置的设备DID
        
        如果未配置，自动从设备列表中选择第一个
        
        Returns:
            设备DID
        
        Raises:
            XiaomiAuthError: 未登录或无设备
        """
        if self.device_id:
            return self.device_id
        
        devices = await self.get_devices()
        if not devices:
            raise XiaomiAuthError("未找到可用的小爱音箱设备")
        
        # 默认选择第一个设备
        self.device_id = devices[0]["did"]
        logger.info(f"[miastrbot] 自动选择设备: {devices[0]['name']} (DID: {self.device_id})")
        return self.device_id
    
    async def send_tts(self, text: str) -> bool:
        """
        发送TTS播报
        
        Args:
            text: 要播放的文字
        
        Returns:
            是否成功
        """
        if not self._logged_in:
            raise XiaomiCommandError("请先调用 login() 登录")
        
        if not self.device_id:
            await self.get_device_id()
        
        try:
            if self.use_command:
                # command模式
                return await self._tts_via_command(text)
            else:
                # ubus模式
                return await self._tts_via_ubus(text)
                
        except Exception as e:
            logger.error(f"[miastrbot] TTS播报失败: {e}")
            raise XiaomiCommandError(f"TTS失败: {e}")
    
    async def _tts_via_command(self, text: str) -> bool:
        """
        通过 command 模式发送TTS
        
        适用型号: L05C, LX04, X10A, L05B
        
        Args:
            text: 要播放的文字
        
        Returns:
            是否成功
        """
        try:
            # 适配 miservice_fork: 使用 MiNAService.text_to_speech()
            await self._na_service.text_to_speech(self.device_id, text)
            logger.info(f"[miastrbot] Command TTS 发送成功")
            return True
        except Exception as e:
            logger.error(f"[miastrbot] Command TTS 失败: {e}")
            return False
    
    async def _tts_via_ubus(self, text: str) -> bool:
        """
        通过 ubus 模式发送TTS
        
        适用型号: LX06 等
        
        注意：当前实现与 _tts_via_command 完全相同，
        因为 miservice_fork 的 MiNAService.text_to_speech() 已统一处理
        保留此方法以保持代码结构清晰，便于未来扩展
        
        Args:
            text: 要播放的文字
        
        Returns:
            是否成功
        """
        # 当前实现与 command 模式相同
        return await self._tts_via_command(text)
    
    async def send_command(self, command: str) -> Dict[str, Any]:
        """
        发送命令到小爱音箱
        
        Args:
            command: 命令内容
        
        Returns:
            执行结果字典，包含 code, message 等
        
        Raises:
            XiaomiCommandError: 命令执行失败
        """
        if not self._logged_in:
            raise XiaomiCommandError("请先调用 login() 登录")
        
        if not self.device_id:
            await self.get_device_id()
        
        try:
            if self.use_command:
                return await self._send_via_command(command)
            else:
                return await self._send_via_ubus(command)
                
        except Exception as e:
            logger.error(f"[miastrbot] 发送命令失败: {e}")
            raise XiaomiCommandError(f"命令执行失败: {e}")
    
    async def _send_via_command(self, command: str) -> Dict[str, Any]:
        """
        通过 command 模式发送命令
        
        适用型号: L05C, LX04, X10A, L05B
        
        Args:
            command: 命令内容
        
        Returns:
            执行结果
        """
        try:
            # 适配 miservice_fork: 使用 miio_command() 函数
            await miio_command(self._ios_service, self.device_id, command)
            return {
                "code": 0,
                "message": "success",
                "data": None
            }
        except Exception as e:
            return {
                "code": -1,
                "message": str(e),
                "data": None
            }
    
    async def _send_via_ubus(self, command: str) -> Dict[str, Any]:
        """
        通过 ubus 模式发送命令
        
        适用型号: LX06 等
        
        Args:
            command: 命令内容
        
        Returns:
            执行结果
        """
        try:
            # 适配 miservice_fork: 使用 MiNAService.ubus_request()
            result = await self._na_service.ubus_request(self.device_id, command, {})
            return {
                "code": 0,
                "message": "success",
                "data": result
            }
        except Exception as e:
            return {
                "code": -1,
                "message": str(e),
                "data": None
            }
    
    async def event_loop(self, callback: Callable[[Dict], None] = None):
        """
        事件循环：监听小爱音箱的唤醒和语音输入
        
        Args:
            callback: 事件回调函数，接收事件字典
        
        注意: 这是一个阻塞循环，需要在独立协程中运行
        """
        if not self._logged_in:
            raise XiaomiCommandError("请先调用 login() 登录")
        
        self._event_callback = callback
        
        logger.info("[miastrbot] 启动事件监听...")
        
        try:
            while True:
                # 轮询方式监听（参考xiaogpt）
                try:
                    # 获取音箱状态 适配 miservice_fork: 使用 MiNAService
                    status = await self._na_service.player_get_status(self.device_id)
                    
                    # 检查是否有新的语音输入
                    if status.get("need_tts"):
                        text = status.get("text", "")
                        if text and self._event_callback:
                            await self._event_callback({
                                "type": "voice_input",
                                "text": text,
                                "device_id": self.device_id
                            })
                    
                    # 检查演奏状态
                    if status.get("is_playing"):
                        pass  # 播放中
                    
                except Exception as e:
                    logger.debug(f"[miastrbot] 事件轮询: {e}")
                
                # 等待下次轮询
                await asyncio.sleep(2)
                
        except asyncio.CancelledError:
            logger.info("[miastrbot] 事件监听已停止")
        except Exception as e:
            logger.error(f"[miastrbot] 事件监听异常: {e}")
    
    async def wake_and_play(self, text: str) -> bool:
        """
        唤醒小爱并播放TTS
        
        这是最常用的功能组合：
        1. 发送唤醒命令
        2. 播放TTS语音
        
        Args:
            text: 要播放的文字
        
        Returns:
            是否成功
        """
        try:
            # 1. 唤醒音箱
            await self.send_command("播放")
            
            # 2. 等待音箱响应
            await asyncio.sleep(1)
            
            # 3. 发送TTS
            return await self.send_tts(text)
            
        except Exception as e:
            logger.error(f"[miastrbot] 唤醒播放失败: {e}")
            return False
    
    async def close(self):
        """关闭服务，释放资源"""
        self._account = None
        self._ios_service = None
        self._na_service = None
        self._logged_in = False
        logger.info("[miastrbot] 小爱服务已关闭")
    
    @property
    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        return self._logged_in
