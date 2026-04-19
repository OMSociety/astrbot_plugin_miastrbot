# -*- coding: utf-8 -*-
"""
小爱音箱服务 (XiaomiService)

支持多型号：小爱音箱Play增强版(L05C)、小爱音箱Pro(LX06)等
参考: https://github.com/yihong0618/xiaogpt
"""

import os
import asyncio
from typing import Optional, List, Dict, Any, Callable
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
        小米账号OAuth登录
        
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
        
        # 优先使用传入的参数，其次使用配置，最后尝试环境变量
        account = account or self.config.get("account") or os.getenv("MI_USER", "")
        password = password or self.config.get("password") or os.getenv("MI_PASS", "")
        
        if not account or not password:
            raise XiaomiAuthError("未提供小米账号密码，请配置或设置环境变量 MI_USER/MI_PASS")
        
        try:
            # 创建账号实例
            self._account = MiAccount(
                account,
                password,
                os.path.join(os.path.expanduser("~"), ".mi.token")
            )
            
            # 登录获取token
            await self._account.login()
            
            # 初始化服务
            self._ios_service = MiIOService(self._account)
            # 适配 miservice_fork: 使用 MiNAService 替代 MiOTService
            self._na_service = MiNAService(self._account)
            
            self._logged_in = True
            logger.info("[miastrbot] 小爱账号登录成功")
            
            return True
            
        except Exception as e:
            logger.error(f"[miastrbot] 小爱账号登录失败: {e}")
            raise XiaomiAuthError(f"登录失败: {e}")
    
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
        
        try:
            # 使用 MiNAService 获取设备列表 (适配 miservice_fork)
            device_list_raw = await self._na_service.device_list()
            
            # 筛选小爱音箱类型
            devices = []
            for device in device_list_raw:
                # 查找有 audio 能力的设备
                if device.get("extra", {}).get("audio"):
                    devices.append({
                        "id": device.get("id"),
                        "did": device.get("did"),
                        "name": device.get("name"),
                        "hardware": device.get("hardware"),
                        "token": device.get("token"),
                    })
            
            logger.info(f"[miastrbot] 获取到 {len(devices)} 个小爱音箱设备")
            return devices
            
        except Exception as e:
            logger.error(f"[miastrbot] 获取设备列表失败: {e}")
            raise XiaomiAuthError(f"获取设备失败: {e}")
    
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
        
        Args:
            text: 要播放的文字
        
        Returns:
            是否成功
        """
        try:
            # 适配 miservice_fork: 同样使用 text_to_speech()
            await self._na_service.text_to_speech(self.device_id, text)
            logger.info(f"[miastrbot] Ubus TTS 发送成功")
            return True
        except Exception as e:
            logger.error(f"[miastrbot] Ubus TTS 失败: {e}")
            return False
    
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
