# -*- coding: utf-8 -*-
"""
miastrbot - AstrBot 小爱音箱+米家设备集成插件

小爱音箱作为语音入口， AstrBot 作为大脑，米家设备作为执行终端

作者: Slandre & Flandre
版本: 0.0.1
"""

import os
import asyncio
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.core.message.components import Plain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger as astrbot_logger

from .config_manager import MiASTRBotConfigManager
from .services.xiaomi_service import XiaomiService, XiaomiAuthError, XiaomiCommandError
from .services.mihome_service import MiHomeService, MiHomeAuthError, MiHomeControlError
from .services.tts_service import TTSServer, TTSServerError
from .agent.handler import AgentHandler
from .webui import init_container, Server
from .webui.config import WebUIConfig
from .utils.events import EventManager
from .utils.logging import init_logging
from .utils.exceptions import (
    MiASTRBotError,
    MiASTRBotConfigError,
    MiASTRBotServiceError,
)

PLUGIN_NAME = "astrbot_plugin_miastrbot"


@register(PLUGIN_NAME, "Slandre & Flandre & MiniMax", "小爱Astrbot", "0.0.1")
class MiASTRBotPlugin(Star):
    """miastrbot 插件主类"""
    
    def __init__(self, context: Context, config = None):
        super().__init__(context)
        self.context = context
        
        # 初始化日志
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(plugin_dir, "logs")
        self.log = init_logging(log_dir=log_dir)
        self.log.info("插件初始化中...")
        
        # 初始化配置管理器
        self.config_manager = MiASTRBotConfigManager(config)
        
        # 敏感信息优先从环境变量读取
        self._load_from_env()
        
        # 服务实例
        self.xiaomi_service: Optional[XiaomiService] = None
        self.mihome_service: Optional[MiHomeService] = None
        self.tts_server: Optional[TTSServer] = None
        self.agent_handler: Optional[AgentHandler] = None
        
        # 生命周期任务
        self._webui_server = None
        self._running = False
        self._init_lock = asyncio.Lock()
        
        self.log.info("插件初始化完成")
    
    # _load_from_env() 已移至 ConfigManager，保留方法以兼容外部调用
    def _load_from_env(self):
        """从环境变量加载敏感配置（由 ConfigManager 处理）"""
        pass

    async def initialize(self):
        await super().initialize()
        
        # 先初始化服务（包括 mihome_service），再启动 WebUI
        try:
            await self._init_services()
        except Exception as e:
            self.log.error(f"❌ 服务初始化失败: {e}")
            import traceback
            self.log.error(traceback.format_exc())
        
        # 检查是否启用 WebUI
        enable_webui = self.config_manager.get("webui.enable", True)
        if not enable_webui:
            self.log.info("WebUI 已禁用")
            return
        
        # 初始化 WebUI 配置（必须在 init_container 之前定义）
        webui_config = WebUIConfig(
            host=self.config_manager.get("webui.host", "0.0.0.0"),
            port=self.config_manager.get("webui.port", 9528),
            password=self.config_manager.get("webui.password", "")
        )
        
        # 初始化容器（必须在 webui_config 定义之后）
        init_container(
            config_manager=self.config_manager,
            xiaomi_service=self.xiaomi_service,
            mihome_service=self.mihome_service,
            agent_handler=self.agent_handler,
            webui_config=webui_config,
        )
        
        try:
            auto_kill = self.config_manager.get("webui.auto_kill", False)
            self._webui_server = Server(
                host=webui_config.host,
                port=webui_config.port,
                auto_kill=auto_kill
            )
            await self._webui_server.start()
            self.log.info(f"✅ WebUI 服务已启动: http://{webui_config.host}:{webui_config.port}/")
            
        except Exception as e:
            self.log.error(f"❌ WebUI 启动失败: {e}")
            import traceback
            self.log.error(traceback.format_exc())

    async def terminate(self):
        """
        插件被禁用时调用
        """
        self._running = False
        
        # 停止 WebUI 服务器
        if self._webui_server:
            await self._webui_server.stop()
            self._webui_server = None
        
        self.log.info("插件已停止")
    
    async def _init_services(self):
        """初始化各服务"""
        # 初始化 TTS 服务
        try:
            tts_config = self.config_manager.get_section("tts")
            self.tts_server = TTSServer(config=tts_config)
            self.log.info("TTS 服务初始化完成")
        except Exception as e:
            self.log.error(f"TTS 服务初始化失败: {e}")
        
        # 初始化小爱服务
        try:
            xiaomi_config = self.config_manager.get_section("xiaomi")
            self.xiaomi_service = XiaomiService(config=xiaomi_config)
            
            if xiaomi_config.get("account") and xiaomi_config.get("password"):
                await self._login_xiaomi()
        except Exception as e:
            self.log.error(f"小爱服务初始化失败: {e}")
        
        # 初始化米家服务
        try:
            mihome_config = self.config_manager.get_section("mihome")
            self.mihome_service = MiHomeService(config=mihome_config)
            
            self.log.info("米家服务初始化完成")
        except Exception as e:
            self.log.error(f"米家服务初始化失败: {e}")
        
        # 初始化 Agent Handler
        try:
            speaker_config = self.config_manager.get_section("speaker")
            weather_config = self.config_manager.get_section("weather")
            agent_config = {
                **speaker_config,
                "weather_api_key": weather_config.get("weather_api_key", ""),
                "weather_city": weather_config.get("weather_city", "北京"),
            }
            self.agent_handler = AgentHandler(
                xiaomi_service=self.xiaomi_service,
                mihome_service=self.mihome_service,
                tts_server=self.tts_server,
                config=agent_config,
            )
            self.log.info("Agent Handler 初始化完成")
        except Exception as e:
            self.log.error(f"Agent Handler 初始化失败: {e}")
        

    async def _login_xiaomi(self) -> bool:
        """登录小爱音箱"""
        if not self.xiaomi_service:
            return False
        
        try:
            success = await self.xiaomi_service.login()
            if success:
                self.log.info("小爱音箱登录成功")
            return success
        except XiaomiAuthError as e:
            self.log.error(f"小爱音箱登录失败: {e}")
            return False
    
    async def _login_mihome(self) -> bool:
        """登录米家"""
        if not self.mihome_service:
            return False
        
        try:
            result = await self.mihome_service.login()
            if isinstance(result, dict):
                status = result.get("status")
                if status in ("success", "started", "in_progress"):
                    self.log.info(f"米家登录流程状态: {status}")
                    return True
                self.log.error(f"米家登录失败: {result.get('message', '未知错误')}")
                return False
            success = bool(result)
            if success:
                self.log.info("米家登录成功")
            return success
        except MiHomeAuthError as e:
            self.log.error(f"米家登录失败: {e}")
            return False
        except Exception as e:
            self.log.error(f"米家登录异常: {e}")
            return False
    
    async def list_mihome_devices(self) -> str:
        """列出米家设备"""
        if not self.mihome_service:
            return "米家服务未初始化"
        
        try:
            devices = await self.mihome_service.list_devices()
            if not devices:
                return "未发现米家设备"
            
            lines = ["米家设备列表:"]
            for i, device in enumerate(devices, 1):
                lines.append(f"{i}. {device.get('name', '未知')} (DID: {device.get('did', 'N/A')})")
            
            return "\n".join(lines)
        except Exception as e:
            return f"获取设备列表失败: {e}"
    
    async def control_mihome_device(self, device_alias: str, action: str) -> str:
        """控制米家设备"""
        if not self.mihome_service:
            return "米家服务未初始化"
        
        try:
            result = await self.mihome_service.control_device(device_alias, action)
            return result
        except MiHomeControlError as e:
            return f"控制设备失败: {e}"
    
    async def query_mihome_device_status(self, device_alias: str) -> str:
        """查询设备状态"""
        if not self.mihome_service:
            return "米家服务未初始化"
        
        try:
            status = await self.mihome_service.get_device_status(device_alias)
            return f"{device_alias} 状态: {status}"
        except Exception as e:
            return f"查询状态失败: {e}"
    
    async def speak_to_xiaomi(self, text: str) -> str:
        """通过小爱音箱播报"""
        if not self.xiaomi_service:
            return "小爱服务未初始化"
        
        try:
            result = await self.xiaomi_service.send_tts(text)
            return result
        except XiaomiCommandError as e:
            return f"播报失败: {e}"
    
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_message(self, event: AstrMessageEvent):
        """
        处理接收到的消息
        仅处理私聊消息（不监听 QQ 群聊）
        """
        if not event.message_str:
            return
        
        # 延迟初始化服务（带锁防止重复初始化）
        if not self._running:
            async with self._init_lock:
                if not self._running:  # 双重检查锁定模式
                    self._running = True
                    try:
                        await self._init_services()
                    except Exception as e:
                        self._running = False
                        self.log.error(f"延迟初始化失败: {e}")
                        return
        
        message_text = event.message_str.strip()
        
        # 检查是否为命令
        command_prefixes = [p.strip() for p in self.config_manager.get("speaker.command_prefix", "/小爱").split(",") if p.strip()] or ["/小爱"]
        
        for prefix in command_prefixes:
            if message_text.startswith(prefix.strip()):
                command = message_text[len(prefix):].strip()
                # 忽略空命令（只有前缀无内容）
                if not command:
                    return
                await self._handle_command(event, command)
                return
        
        # 如果启用了 AI 模式，将消息发送给 Agent 处理
        if self.config_manager.get("speaker.ai_mode", False) and self.agent_handler:
            try:
                response = await self.agent_handler.process(message_text)
                if response:
                    result = response.get("result") if isinstance(response, dict) else str(response)
                    if result:
                        await event.send(MessageChain([Plain(result)]))
            except Exception as e:
                self.log.error(f"Agent 处理失败: {e}")
    
    async def _handle_command(self, event: AstrMessageEvent, command: str):
        """处理命令"""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        
        handlers = {
            "帮助": self._send_help,
            "help": self._send_help,
            "状态": self._send_status,
            "status": self._send_status,
            "登录": self._handle_login,
            "login": self._handle_login,
            "设备": self._list_devices,
            "devices": self._list_devices,
            "控制": self._handle_control,
            "control": self._handle_control,
            "播报": self._handle_speak,
            "speak": self._handle_speak,
        }
        
        handler = handlers.get(cmd)
        if handler:
            try:
                await handler(event, args)
            except Exception as e:
                await event.send(MessageChain([Plain(f"命令执行失败: {e}")]))
                self.log.error(f"命令 {cmd} 执行失败: {e}")
        else:
            await event.send(MessageChain([Plain(f"未知命令: {cmd}，发送「帮助」查看可用命令")]))
    
    async def _send_help(self, event: AstrMessageEvent, _args: str):
        """发送帮助信息"""
        help_text = """
小爱Astrbot 命令帮助：

「帮助」/「help」 - 显示此帮助信息
「状态」/「status」 - 查看服务连接状态
「登录」/「login」 - 重新登录服务
「设备」/「devices」 - 列出米家设备
「控制 <设备别名> <动作>」 - 控制设备
「播报 <内容>」 - 通过小爱音箱播报

或者直接发送消息与小爱对话（需开启AI模式）
        """.strip()
        await event.send(MessageChain([Plain(help_text)]))
    
    async def _send_status(self, event: AstrMessageEvent, _args: str):
        """发送状态信息"""
        xiaomi_logged_in = False
        if self.xiaomi_service:
            is_logged_in = getattr(self.xiaomi_service, "is_logged_in", False)
            xiaomi_logged_in = is_logged_in() if callable(is_logged_in) else bool(is_logged_in)
        xiaomi_status = "✅ 已连接" if xiaomi_logged_in else "❌ 未连接"
        mihome_status = "✅ 已连接" if self.mihome_service and self.mihome_service.is_authenticated() else "❌ 未连接"
        tts_status = "✅ 就绪" if self.tts_server else "❌ 未就绪"
        agent_status = "✅ 就绪" if self.agent_handler else "❌ 未就绪"
        
        status_text = f"""
服务状态:
├─ 小爱音箱: {xiaomi_status}
├─ 米家: {mihome_status}
├─ TTS: {tts_status}
└─ Agent: {agent_status}
        """.strip()
        
        await event.send(MessageChain([Plain(status_text)]))
    
    async def _handle_login(self, event: AstrMessageEvent, _args: str):
        """处理登录"""
        await event.send(MessageChain([Plain("正在登录...")]))
        
        tasks = []
        if self.xiaomi_service:
            tasks.append(self._login_xiaomi())
        if self.mihome_service:
            tasks.append(self._login_mihome())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        await event.send(MessageChain([Plain(f"登录完成: {success_count}/{len(tasks)} 服务成功")]))
    
    async def _list_devices(self, event: AstrMessageEvent, _args: str):
        """列出设备"""
        device_list = await self.list_mihome_devices()
        await event.send(MessageChain([Plain(device_list)]))
    
    async def _handle_control(self, event: AstrMessageEvent, args: str):
        """处理设备控制"""
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            await event.send(MessageChain([Plain("用法: 「控制 <设备别名> <动作>\n例如: 「控制 客厅灯 开」")]))
            return
        
        device_alias, action = parts
        result = await self.control_mihome_device(device_alias, action)
        await event.send(MessageChain([Plain(result)]))
    
    async def _handle_speak(self, event: AstrMessageEvent, args: str):
        """处理播报"""
        if not args:
            await event.send(MessageChain([Plain("用法: 「播报 <内容>」")]))
            return
        
        result = await self.speak_to_xiaomi(args)
        await event.send(MessageChain([Plain(result)]))
