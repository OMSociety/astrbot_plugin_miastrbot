# -*- coding: utf-8 -*-
"""
工具模块

提供：
- events: 事件系统
- logging: 日志系统
- exceptions: 异常定义
"""

from .events import (
    EventType,
    Event,
    EventBus,
    EventManager,
    XiaomiEventListener,
    MiHomeEventListener,
    ScheduledTask,
)

from .logging import (
    LogLevel,
    StructuredLogger,
    ExceptionTracker,
    ErrorHandler,
    init_logging,
    get_logger,
    get_error_handler,
    error_handled,
)

from .exceptions import (
    MiASTRBotError,
    MiASTRBotConfigError,
    MiASTRBotServiceError,
)

__all__ = [
    # 事件
    "EventType",
    "Event",
    "EventBus",
    "EventManager",
    "XiaomiEventListener",
    "MiHomeEventListener",
    "ScheduledTask",
    # 日志
    "LogLevel",
    "StructuredLogger",
    "ExceptionTracker",
    "ErrorHandler",
    "init_logging",
    "get_logger",
    "get_error_handler",
    "error_handled",
    # 异常
    "MiASTRBotError",
    "MiASTRBotConfigError",
    "MiASTRBotServiceError",
]
