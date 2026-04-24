# -*- coding: utf-8 -*-
"""
miastrbot - AstrBot 小爱音箱+米家设备集成插件

小爱音箱作为语音入口， AstrBot 作为大脑，米家设备作为执行终端

作者: Slandre & Flandre
版本: 0.1.0
"""

import os
import asyncio
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.core.message.components import Plain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger as astrbot_logger

from .config_manager import MiASTRBotConfigManager
from .services.xiaomi_speaker_service import XiaomiSpeakerService, XiaomiSpeakerError, XiaomiSpeakerAuthError
from .services.mihome_service import MiHomeService, MiHomeAuthError, MiHomeControlError
from .services.tts_service import TTSServer, TTSServerError
from .agent.handler import AgentHandler, IntentType
from .webui import init_container, Server
from .webui.config import WebUIConfig
from .utils.logging import init_logging
from .utils.exceptions import (
    MiASTRBotError,
    MiASTRBotConfigError,
    MiASTRBotServiceError,
)

PLUGIN_NAME = "astrbot_plugin_miastrbot"


@register(PLUGIN_NAME, "Slandre & Flandre", "小爱Agent", "0.1.0")
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
        
        # 服务实例
        self.speaker_service: Optional[XiaomiSpeakerService] = None
        self.mihome_service: Optional[MiHomeService] = None
        self.tts_server: Optional[TTSServer] = None
        self.agent_handler: Optional[AgentHandler] = None
        
        # 生命周期任务
        self._webui_server = None
        self._running = False
        self._initialized = False
        self._init_lock = asyncio.Lock()
        
        self.log.info("插件初始化完成")
    


    async def initialize(self):
        await super().initialize()
        
        # 初始化服务
        try:
            await self._init_services()
            self._initialized = True
            self._running = True
        except Exception as e:
            self.log.error(f"❌ 服务初始化失败: {e}")
            import traceback
            self.log.error(traceback.format_exc())
            self._initialized = False
        
        # 服务未初始化完成则不启动 WebUI
        if not self._initialized:
            self.log.warning("服务未初始化完成，WebUI 不启动")
            return
        
        # 检查是否启用 WebUI
        enable_webui = self.config_manager.get("webui.enable", True)
        if not enable_webui:
            self.log.info("WebUI 已禁用")
            return
        
        # 初始化 WebUI 配置
        webui_config = WebUIConfig(
            host=self.config_manager.get("webui.host", "0.0.0.0"),
            port=self.config_manager.get("webui.port", 9528),
            password=self.config_manager.get("webui.password", "")
        )
        
        # 确保服务都已初始化后再注入容器
        init_container(
            config_manager=self.config_manager,
            speaker_service=self.speaker_service,
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
        """插件被禁用时调用"""
        self._running = False
        
        # 停止小爱音箱轮询
        if self.speaker_service:
            self.speaker_service.stop_polling()
            await self.speaker_service.close()
        
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
        
        # 初始化小爱音箱服务
        try:
            speaker_config = self.config_manager.get_section("speaker")
            self.speaker_service = XiaomiSpeakerService(config=speaker_config)
            
            # 如果有 Cookie/Token，尝试登录
            if self.speaker_service.is_logged_in:
                await self._login_speaker()
            else:
                self.log.info("小爱音箱未配置 Cookie，请参考 README 获取")
        except Exception as e:
            self.log.error(f"小爱音箱服务初始化失败: {e}")
        
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
                speaker_service=self.speaker_service,
                mihome_service=self.mihome_service,
                tts_server=self.tts_server,
                config=agent_config,
                context=self.context,
            )
            self.log.info("Agent Handler 初始化完成")
        except Exception as e:
            self.log.error(f"Agent Handler 初始化失败: {e}")
        
        # 启动小爱音箱语音轮询
        if self.speaker_service and self.speaker_service.is_logged_in and self.config_manager.get("speaker.ai_mode", True):
            asyncio.create_task(self._run_speaker_polling())

    async def _run_speaker_polling(self):
        """运行小爱音箱语音轮询（支持等待模式）"""
        self.log.info(f"启动小爱音箱语音轮询，唤醒词: {self.config_manager.get('speaker.wake_words', '')}")
        
        try:
            wake_words = [w.strip() for w in self.config_manager.get("speaker.wake_words", "").split(",") if w.strip()]
            poll_keywords = wake_words or ["请", "帮我"]
            self.log.info(f"小爱语音触发词: {poll_keywords}")
            async for command in self.speaker_service.poll_voice(keywords=poll_keywords):
                query = command.get("query", "")
                self.log.info(f"收到语音命令: {query}")
                
                # 处理语音命令
                if self.agent_handler:
                    try:
                        response = await self.agent_handler.process(query)
                        if response:
                            intent = response.get("intent", "")
                            tts_text = response.get("tts_text", "")
                            
                            # 等待模式下，只回复"我在呢"，继续监听
                            if intent == IntentType.WAITING:
                                await self.speaker_service.speak(tts_text)
                                self.log.info("进入等待模式，继续监听...")
                                # 继续下一次循环，等待用户继续说话
                                continue
                            
                            # 正常回复
                            if tts_text:
                                await self.speaker_service.speak(tts_text)
                    except Exception as e:
                        self.log.error(f"处理语音命令失败: {e}")
                        await self.speaker_service.speak("处理命令失败，请稍后重试")
                        
        except asyncio.CancelledError:
            self.log.info("小爱音箱语音轮询已停止")
        except Exception as e:
            self.log.error(f"语音轮询异常: {e}")
    
    async def _login_speaker(self) -> bool:
        """登录小爱音箱"""
        if not self.speaker_service:
            return False
        
        try:
            success = await self.speaker_service.login()
            if success:
                self.log.info("小爱音箱登录成功")
            return success
        except XiaomiSpeakerAuthError as e:
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
                if status == "success":
                    self.log.info("米家登录成功")
                    return True
                elif status == "started":
                    self.log.info("米家登录流程已启动，请扫码完成登录")
                    return True
                elif status == "in_progress":
                    self.log.info("米家登录进行中，请等待")
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
        if not self.speaker_service:
            return "小爱音箱服务未初始化"
        
        try:
            success = await self.speaker_service.speak(text)
            return "✅ 播报成功" if success else "❌ 播报失败"
        except Exception as e:
            return f"❌ 播报失败: {e}"
    
    @filter.command("小爱", alias={"help"})
    async def xiaoai_command(self, event: AstrMessageEvent):
        """
小爱音箱控制中心。

用法：
/小爱 帮助    - 查看所有命令
/小爱 状态    - 查看服务连接状态
/小爱 登录    - 重新登录小爱音箱和米家
/小爱 设备    - 列出已绑定的米家设备
/小爱 控制 <设备> <动作> - 控制设备，如 /小爱 控制 客厅灯 开
/小爱 播报 <内容>     - 让小爱音箱播报文字
        """
        if not event.message_str:
            return

        message_text = event.message_str.strip()
        command = message_text
        if command.startswith("/小爱"):
            command = command[len("/小爱"):].strip()
        elif command.startswith("小爱"):
            command = command[len("小爱"):].strip()

        if not command:
            await self._send_help(event, "")
            return

        await self._handle_command(event, command)

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_message(self, event: AstrMessageEvent):
        """
        处理接收到的消息
        仅处理私聊消息
        """
        if not event.message_str:
            return
        
        # 延迟初始化服务（带锁防止重复初始化）
        if not self._initialized:
            async with self._init_lock:
                if not self._initialized:  # 双重检查锁定模式
                    try:
                        await self._init_services()
                        self._initialized = True
                        self._running = True
                    except Exception as e:
                        self._initialized = False
                        self._running = False
                        self.log.error(f"延迟初始化失败: {e}")
                        return
        
        message_text = event.message_str.strip()
        return
    
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
小爱 Astrbot 命令列表：

/小爱 帮助      查看本帮助
/小爱 状态      查看小爱音箱、米家、TTS、Agent 的连接状态
/小爱 登录      重新登录小爱音箱和米家
/小爱 设备      列出已绑定的米家设备
/小爱 控制 <设备> <动作>  控制设备，例：/小爱 控制 客厅灯 开
/小爱 播报 <内容>         让小爱音箱播报文字

说明：
- 小爱语音对话由 speaker.ai_mode + speaker.wake_words 控制
- 对小爱说出唤醒词（如"芙兰"）后，才会尝试转给 AstrBot
        """.strip()
        await event.send(MessageChain([Plain(help_text)]))
    
    async def _send_status(self, event: AstrMessageEvent, _args: str):
        """发送状态信息"""
        speaker_logged_in = False
        if self.speaker_service:
            is_logged_in = getattr(self.speaker_service, "is_logged_in", False)
            speaker_logged_in = is_logged_in() if callable(is_logged_in) else bool(is_logged_in)
        mihome_ok = self.mihome_service and self.mihome_service.is_authenticated()

        status_lines = [
            "小爱 Astrbot 服务状态：",
            f"  小爱音箱  {'✅ 已登录' if speaker_logged_in else '❌ 未登录'}",
            f"  米家      {'✅ 已授权' if mihome_ok else '❌ 未授权'}",
            f"  TTS      {'✅ 就绪' if self.tts_server else '❌ 未就绪'}",
            f"  Agent    {'✅ 就绪' if self.agent_handler else '❌ 未就绪'}",
            f"  AI模式   {'✅ 启用' if self.config_manager.get('speaker.ai_mode', True) else '❌ 停用'}",
        ]
        if self.speaker_service:
            hw = getattr(self.speaker_service, 'hardware', '?')
            did = getattr(self.speaker_service, 'device_id', '')
            status_lines.append(f"  型号: {hw}  设备ID: {did or '自动选择'}")

            dbg = self.speaker_service.get_debug_status() if hasattr(self.speaker_service, 'get_debug_status') else None
            if dbg:
                status_lines.append(f"  最近轮询: {dbg.get('last_poll_status') if dbg.get('last_poll_status') is not None else '无请求'}")
                if dbg.get('last_poll_error'):
                    status_lines.append(f"  最近错误: {dbg.get('last_poll_error')}")
                if dbg.get('last_query'):
                    status_lines.append(f"  最近命令: {dbg.get('last_query')}")
                if dbg.get('auth_invalid_count'):
                    status_lines.append(f"  401计数: {dbg.get('auth_invalid_count')}")
                if dbg.get('last_poll_url'):
                    status_lines.append(f"  最后URL: {dbg.get('last_poll_url')}")

        status_text = "\n".join(status_lines)
        await event.send(MessageChain([Plain(status_text)]))
    
    async def _handle_login(self, event: AstrMessageEvent, _args: str):
        """处理登录"""
        await event.send(MessageChain([Plain("正在登录...")]))
        
        tasks = []
        if self.speaker_service:
            tasks.append(self._login_speaker())
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
