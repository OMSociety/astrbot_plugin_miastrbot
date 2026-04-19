# -*- coding: utf-8 -*-
"""
事件系统

处理：
1. 小爱音箱语音输入事件
2. 米家设备状态变更事件
3. 定时任务事件
"""

import asyncio
from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from astrbot.api import logger


class EventType(Enum):
    """事件类型"""
    # 小爱相关
    XIAOMI_WAKE = "xiaomi_wake"           # 音箱被唤醒
    XIAOMI_VOICE_INPUT = "xiaomi_voice_input"  # 语音输入
    XIAOMI_TTS_START = "xiaomi_tts_start"     # TTS开始播放
    XIAOMI_TTS_END = "xiaomi_tts_end"         # TTS播放结束
    
    # 米家相关
    MIHOME_DEVICE_ONLINE = "mihome_device_online"     # 设备上线
    MIHOME_DEVICE_OFFLINE = "mihome_device_offline"   # 设备离线
    MIHOME_DEVICE_STATE_CHANGE = "mihome_device_state_change"  # 设备状态变化
    MIHOME_SCENE_TRIGGERED = "mihome_scene_triggered"  # 场景被触发
    
    # 系统相关
    SYSTEM_ERROR = "system_error"         # 系统错误
    SYSTEM_LOGIN_SUCCESS = "system_login_success"  # 登录成功
    SYSTEM_LOGIN_FAILED = "system_login_failed"    # 登录失败


@dataclass
class Event:
    """事件数据类"""
    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "miastrbot"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "source": self.source
        }


class EventBus:
    """
    事件总线
    
    提供事件订阅、发布、退订功能
    """
    
    def __init__(self):
        """初始化事件总线"""
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._default_handlers: List[Callable] = []
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info("[miastrbot] 事件总线初始化")
    
    def subscribe(self, event_type: EventType, handler: Callable):
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            handler: 处理函数，接收 Event 对象
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        self._subscribers[event_type].append(handler)
        logger.debug(f"[miastrbot] 订阅事件: {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """
        退订事件
        
        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
                logger.debug(f"[miastrbot] 退订事件: {event_type.value}")
            except ValueError:
                pass
    
    def subscribe_any(self, handler: Callable):
        """
        订阅所有事件
        
        Args:
            handler: 处理函数，接收 Event 对象
        """
        self._default_handlers.append(handler)
        logger.debug("[miastrbot] 订阅所有事件")
    
    def publish(self, event: Event):
        """
        发布事件
        
        Args:
            event: 事件对象
        """
        # 放入事件队列
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("[miastrbot] 事件队列已满，丢弃事件")
    
    def _create_event(self, event_type: EventType, **kwargs) -> Event:
        """创建事件"""
        return Event(type=event_type, data=kwargs)
    
    async def _process_events(self):
        """异步处理事件队列"""
        while self._running:
            try:
                # 从队列获取事件（带超时）
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0
                )
                
                # 调用对应的处理器
                await self._dispatch_event(event)
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[miastrbot] 事件处理异常: {e}")
    
    async def _dispatch_event(self, event: Event):
        """
        分发事件到处理器
        
        Args:
            event: 事件对象
        """
        # 先调用特定类型处理器
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"[miastrbot] 事件处理器执行异常: {e}")
        
        # 再调用默认处理器
        for handler in self._default_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"[miastrbot] 默认事件处理器执行异常: {e}")
    
    async def start(self):
        """启动事件循环"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._process_events())
        logger.info("[miastrbot] 事件循环已启动")
    
    async def stop(self):
        """停止事件循环"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # 清空队列
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        logger.info("[miastrbot] 事件循环已停止")
    
    @property
    def queue_size(self) -> int:
        """获取队列大小"""
        return self._event_queue.qsize()


class XiaomiEventListener:
    """
    小爱音箱事件监听器
    
    监听小爱音箱的语音输入和状态变化
    """
    
    def __init__(self, xiaomi_service, event_bus: EventBus):
        """
        初始化监听器
        
        Args:
            xiaomi_service: 小爱服务实例
            event_bus: 事件总线
        """
        self.xiaomi_service = xiaomi_service
        self.event_bus = event_bus
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # 轮询间隔（秒）
        self.poll_interval = 2.0
        
        logger.info("[miastrbot] 小爱事件监听器初始化")
    
    async def start(self):
        """启动监听"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[miastrbot] 小爱事件监听已启动")
    
    async def stop(self):
        """停止监听"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("[miastrbot] 小爱事件监听已停止")
    
    async def _poll_loop(self):
        """轮询循环"""
        last_status = None
        
        while self._running:
            try:
                if not self.xiaomi_service or not self.xiaomi_service.is_logged_in:
                    await asyncio.sleep(self.poll_interval)
                    continue
                
                # 获取音箱状态
                try:
                    status = await self.xiaomi_service._ot_service.player_get_status(
                        self.xiaomi_service.device_id
                    )
                    
                    # 检查唤醒状态
                    is_wake = status.get("asr_state") == 1
                    if is_wake and last_status != "wake":
                        self.event_bus.publish(Event(
                            EventType.XIAOMI_WAKE,
                            data={"device_id": self.xiaomi_service.device_id}
                        ))
                    
                    # 检查语音输入
                    voice_text = status.get("text", "")
                    if voice_text and voice_text != last_status.get("text"):
                        self.event_bus.publish(Event(
                            EventType.XIAOMI_VOICE_INPUT,
                            data={
                                "device_id": self.xiaomi_service.device_id,
                                "text": voice_text
                            }
                        ))
                    
                    # 检查播放状态
                    is_playing = status.get("is_playing", False)
                    if is_playing and not last_status.get("is_playing"):
                        self.event_bus.publish(Event(
                            EventType.XIAOMI_TTS_START,
                            data={"device_id": self.xiaomi_service.device_id}
                        ))
                    elif not is_playing and last_status.get("is_playing"):
                        self.event_bus.publish(Event(
                            EventType.XIAOMI_TTS_END,
                            data={"device_id": self.xiaomi_service.device_id}
                        ))
                    
                    last_status = status
                    
                except Exception as e:
                    logger.debug(f"[miastrbot] 获取音箱状态失败: {e}")
                
                await asyncio.sleep(self.poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[miastrbot] 事件轮询异常: {e}")
                await asyncio.sleep(self.poll_interval)


class MiHomeEventListener:
    """
    米家设备事件监听器
    
    监听设备的上下线和状态变化
    """
    
    def __init__(self, mihome_service, event_bus: EventBus):
        """
        初始化监听器
        
        Args:
            mihome_service: 米家服务实例
            event_bus: 事件总线
        """
        self.mihome_service = mihome_service
        self.event_bus = event_bus
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # 设备状态缓存
        self._device_states: Dict[str, Dict] = {}
        
        # 轮询间隔（秒）
        self.poll_interval = 10.0
        
        logger.info("[miastrbot] 米家事件监听器初始化")
    
    async def start(self):
        """启动监听"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[miastrbot] 米家事件监听已启动")
    
    async def stop(self):
        """停止监听"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("[miastrbot] 米家事件监听已停止")
    
    async def _poll_loop(self):
        """轮询循环"""
        while self._running:
            try:
                if not self.mihome_service or not self.mihome_service.is_logged_in:
                    await asyncio.sleep(self.poll_interval)
                    continue
                
                # 获取设备列表
                try:
                    devices = await self.mihome_service.get_devices()
                    
                    for device in devices:
                        did = device.get("did")
                        if not did:
                            continue
                        
                        # 检查上下线状态
                        online = device.get("online", True)
                        last_state = self._device_states.get(did, {})
                        last_online = last_state.get("online", None)
                        
                        if last_online is not None:
                            if online and not last_online:
                                self.event_bus.publish(Event(
                                    EventType.MIHOME_DEVICE_ONLINE,
                                    data={"device": device}
                                ))
                            elif not online and last_online:
                                self.event_bus.publish(Event(
                                    EventType.MIHOME_DEVICE_OFFLINE,
                                    data={"device": device}
                                ))
                        
                        # 更新缓存
                        self._device_states[did] = device.copy()
                    
                except Exception as e:
                    logger.debug(f"[miastrbot] 获取米家设备状态失败: {e}")
                
                await asyncio.sleep(self.poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[miastrbot] 米家事件轮询异常: {e}")
                await asyncio.sleep(self.poll_interval)


class ScheduledTask:
    """
    定时任务
    
    支持 Cron 表达式或固定间隔
    """
    
    def __init__(
        self,
        name: str,
        handler: Callable,
        interval: float = None,
        cron: str = None
    ):
        """
        初始化定时任务
        
        Args:
            name: 任务名称
            handler: 处理函数
            interval: 间隔秒数（与cron二选一）
            cron: Cron表达式
        """
        self.name = name
        self.handler = handler
        self.interval = interval
        self.cron = cron
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(f"[miastrbot] 定时任务初始化: {name}")
    
    async def start(self):
        """启动任务"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"[miastrbot] 定时任务已启动: {self.name}")
    
    async def stop(self):
        """停止任务"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"[miastrbot] 定时任务已停止: {self.name}")
    
    async def _run_loop(self):
        """任务循环"""
        while self._running:
            try:
                # 执行任务
                if asyncio.iscoroutinefunction(self.handler):
                    await self.handler()
                else:
                    self.handler()
                
                # 等待下次执行
                if self.interval:
                    await asyncio.sleep(self.interval)
                # TODO: 支持 Cron 表达式解析
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[miastrbot] 定时任务执行异常: {e}")
                if self.interval:
                    await asyncio.sleep(self.interval)


class EventManager:
    """
    事件管理器
    
    统一管理所有事件相关的组件
    """
    
    def __init__(self):
        """初始化事件管理器"""
        self.event_bus = EventBus()
        self._xiaomi_listener: Optional[XiaomiEventListener] = None
        self._mihome_listener: Optional[MiHomeEventListener] = None
        self._scheduled_tasks: List[ScheduledTask] = []
        
        logger.info("[miastrbot] 事件管理器初始化")
    
    def setup_listeners(
        self,
        xiaomi_service=None,
        mihome_service=None
    ):
        """
        设置监听器
        
        Args:
            xiaomi_service: 小爱服务实例
            mihome_service: 米家服务实例
        """
        if xiaomi_service:
            self._xiaomi_listener = XiaomiEventListener(
                xiaomi_service,
                self.event_bus
            )
        
        if mihome_service:
            self._mihome_listener = MiHomeEventListener(
                mihome_service,
                self.event_bus
            )
    
    def add_scheduled_task(
        self,
        name: str,
        handler: Callable,
        interval: float = None,
        cron: str = None
    ) -> ScheduledTask:
        """
        添加定时任务
        
        Args:
            name: 任务名称
            handler: 处理函数
            interval: 间隔秒数
            cron: Cron表达式
        
        Returns:
            创建的任务对象
        """
        task = ScheduledTask(name, handler, interval, cron)
        self._scheduled_tasks.append(task)
        return task
    
    async def start_all(self):
        """启动所有事件组件"""
        await self.event_bus.start()
        
        if self._xiaomi_listener:
            await self._xiaomi_listener.start()
        
        if self._mihome_listener:
            await self._mihome_listener.start()
        
        for task in self._scheduled_tasks:
            await task.start()
        
        logger.info("[miastrbot] 所有事件组件已启动")
    
    async def stop_all(self):
        """停止所有事件组件"""
        if self._xiaomi_listener:
            await self._xiaomi_listener.stop()
        
        if self._mihome_listener:
            await self._mihome_listener.stop()
        
        for task in self._scheduled_tasks:
            await task.stop()
        
        await self.event_bus.stop()
        
        logger.info("[miastrbot] 所有事件组件已停止")
    
    def subscribe(self, event_type: EventType, handler: Callable):
        """订阅事件"""
        self.event_bus.subscribe(event_type, handler)
    
    def subscribe_any(self, handler: Callable):
        """订阅所有事件"""
        self.event_bus.subscribe_any(handler)
    
    def publish(self, event: Event):
        """发布事件"""
        self.event_bus.publish(event)
