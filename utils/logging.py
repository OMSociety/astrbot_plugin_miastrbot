# -*- coding: utf-8 -*-
"""
日志系统

提供：
1. 结构化日志记录
2. 日志分级过滤
3. 日志轮转
4. 异常追踪
"""

import os
import sys
import logging
import traceback
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

from astrbot.api import logger


class LogLevel:
    """日志级别"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class StructuredLogger:
    """
    结构化日志记录器
    
    支持：
    - 标准日志方法
    - 上下文字段
    - JSON格式输出
    """
    
    def __init__(
        self,
        name: str,
        level: int = LogLevel.INFO,
        log_dir: str = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ):
        """
        初始化日志记录器
        
        Args:
            name: 日志记录器名称
            level: 日志级别
            log_dir: 日志目录（None则只输出到控制台）
            max_bytes: 单个日志文件最大字节数
            backup_count: 保留的备份数量
        """
        self.name = f"miastrbot.{name}"
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(level)
        self.logger.handlers = []  # 清空现有处理器
        
        # 格式化器
        self._setup_formatters()
        
        # 添加处理器
        self._add_handlers(log_dir, max_bytes, backup_count)
        
        # 上下文字段
        self._context: Dict[str, Any] = {}
    
    def _setup_formatters(self):
        """设置格式化器"""
        # 控制台格式
        self.console_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        )
        
        # 文件格式（包含更多细节）
        self.file_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s [%(filename)s:%(lineno)d]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    def _add_handlers(
        self,
        log_dir: str,
        max_bytes: int,
        backup_count: int
    ):
        """添加处理器"""
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(LogLevel.INFO)
        console_handler.setFormatter(self.console_formatter)
        self.logger.addHandler(console_handler)
        
        # 文件处理器
        if log_dir:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            
            # 错误日志（单独记录）
            error_handler = RotatingFileHandler(
                log_path / "error.log",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8"
            )
            error_handler.setLevel(LogLevel.ERROR)
            error_handler.setFormatter(self.file_formatter)
            self.logger.addHandler(error_handler)
            
            # 完整日志
            full_handler = RotatingFileHandler(
                log_path / "miastrbot.log",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8"
            )
            full_handler.setLevel(level=LogLevel.DEBUG)
            full_handler.setFormatter(self.file_formatter)
            self.logger.addHandler(full_handler)
    
    def set_context(self, **kwargs):
        """设置上下文字段"""
        self._context.update(kwargs)
    
    def clear_context(self):
        """清除上下文"""
        self._context = {}
    
    def _format_message(self, msg: str) -> str:
        """格式化消息（添加上下文）"""
        if self._context:
            context_str = " ".join(f"{k}={v}" for k, v in self._context.items())
            return f"[{context_str}] {msg}"
        return msg
    
    def debug(self, msg: str, *args, **kwargs):
        """调试日志"""
        self.logger.debug(self._format_message(msg), *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        """信息日志"""
        self.logger.info(self._format_message(msg), *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        """警告日志"""
        self.logger.warning(self._format_message(msg), *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        """错误日志"""
        self.logger.error(self._format_message(msg), *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        """严重错误日志"""
        self.logger.critical(self._format_message(msg), *args, **kwargs)


class ExceptionTracker:
    """
    异常追踪器
    
    记录和统计异常信息
    """
    
    def __init__(self, logger: StructuredLogger):
        """
        初始化追踪器
        
        Args:
            logger: 日志记录器
        """
        self.logger = logger
        self._exception_counts: Dict[str, int] = {}
        self._exception_history: list = []
        self._max_history = 100
    
    def track_exception(
        self,
        exc: Exception,
        context: Dict[str, Any] = None,
        reraise: bool = False
    ):
        """
        追踪异常
        
        Args:
            exc: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出
        """
        # 获取异常类型名
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        
        # 更新计数
        self._exception_counts[exc_type] = self._exception_counts.get(exc_type, 0) + 1
        
        # 记录到历史
        record = {
            "type": exc_type,
            "message": exc_msg,
            "timestamp": datetime.now(),
            "context": context or {},
            "traceback": traceback.format_exc()
        }
        self._exception_history.append(record)
        
        # 限制历史长度
        if len(self._exception_history) > self._max_history:
            self._exception_history = self._exception_history[-self._max_history:]
        
        # 记录日志
        self.logger.error(f"异常: {exc_type} - {exc_msg}")
        self.logger.debug(f"堆栈:\n{record['traceback']}")
        
        if context:
            self.logger.error(f"上下文: {context}")
        
        # 重新抛出
        if reraise:
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """获取异常统计"""
        return {
            "total_count": sum(self._exception_counts.values()),
            "by_type": self._exception_counts.copy(),
            "recent": self._exception_history[-10:]
        }
    
    def get_recent_exceptions(self, count: int = 10) -> list:
        """获取最近的异常"""
        return self._exception_history[-count:]
    
    def clear_history(self):
        """清除历史"""
        self._exception_history = []


class ErrorHandler:
    """
    统一错误处理器
    
    提供：
    - 错误分类
    - 恢复建议
    - 错误报告
    """
    
    # 错误类型到恢复建议的映射
    RECOVERY_SUGGESTIONS = {
        "XiaomiAuthError": {
            "severity": "high",
            "suggestion": "请检查小米账号密码是否正确，或Token是否过期"
        },
        "XiaomiCommandError": {
            "severity": "medium",
            "suggestion": "请检查小爱音箱是否在线，型号是否支持该命令"
        },
        "MiHomeAuthError": {
            "severity": "high",
            "suggestion": "请检查米家OAuth Token或账号密码"
        },
        "MiHomeControlError": {
            "severity": "medium",
            "suggestion": "请检查设备是否在线，设备ID是否正确"
        },
        "TTSServerError": {
            "severity": "low",
            "suggestion": "请检查TTS配置和网络连接"
        },
        "ConnectionError": {
            "severity": "high",
            "suggestion": "请检查网络连接"
        },
        "TimeoutError": {
            "severity": "medium",
            "suggestion": "请求超时，请稍后重试"
        }
    }
    
    def __init__(self, logger: StructuredLogger):
        """
        初始化错误处理器
        
        Args:
            logger: 日志记录器
        """
        self.logger = logger
        self.tracker = ExceptionTracker(logger)
    
    def handle_error(
        self,
        error: Exception,
        operation: str = None,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        处理错误
        
        Args:
            error: 错误对象
            operation: 操作描述
            context: 上下文信息
        
        Returns:
            错误报告字典
        """
        # 追踪异常
        self.tracker.track_exception(error, context)
        
        # 获取错误信息
        error_type = type(error).__name__
        error_message = str(error)
        
        # 获取恢复建议
        suggestion_info = self.RECOVERY_SUGGESTIONS.get(
            error_type,
            {
                "severity": "unknown",
                "suggestion": "请联系开发者报告此问题"
            }
        )
        
        # 构建报告
        report = {
            "error_type": error_type,
            "error_message": error_message,
            "operation": operation,
            "severity": suggestion_info["severity"],
            "suggestion": suggestion_info["suggestion"],
            "timestamp": datetime.now().isoformat(),
            "context": context or {}
        }
        
        # 记录错误
        log_level = {
            "high": self.logger.error,
            "medium": self.logger.warning,
            "low": self.logger.info,
            "unknown": self.logger.error
        }.get(suggestion_info["severity"], self.logger.error)
        
        log_level(
            f"操作失败 [{operation}] - {error_type}: {error_message}"
        )
        self.logger.info(f"恢复建议: {suggestion_info['suggestion']}")
        
        return report
    
    @staticmethod
    def format_error_report(report: Dict[str, Any]) -> str:
        """
        格式化错误报告为可读字符串
        
        Args:
            report: 错误报告
        
        Returns:
            格式化的字符串
        """
        lines = [
            "=== 错误报告 ===",
            f"类型: {report['error_type']}",
            f"消息: {report['error_message']}",
        ]
        
        if report.get("operation"):
            lines.append(f"操作: {report['operation']}")
        
        lines.extend([
            f"严重程度: {report['severity']}",
            f"建议: {report['suggestion']}",
            f"时间: {report['timestamp']}"
        ])
        
        return "\n".join(lines)


# 全局日志实例
_plugin_logger: Optional[StructuredLogger] = None
_error_handler: Optional[ErrorHandler] = None


def init_logging(log_dir: str = None, level: int = LogLevel.INFO):
    """
    初始化全局日志
    
    Args:
        log_dir: 日志目录
        level: 日志级别
    """
    global _plugin_logger, _error_handler
    
    _plugin_logger = StructuredLogger(
        "plugin",
        level=level,
        log_dir=log_dir
    )
    
    _error_handler = ErrorHandler(_plugin_logger)
    
    return _plugin_logger


def get_logger() -> StructuredLogger:
    """获取全局日志实例"""
    global _plugin_logger
    if _plugin_logger is None:
        _plugin_logger = StructuredLogger("plugin")
    return _plugin_logger


def get_error_handler() -> ErrorHandler:
    """获取全局错误处理器"""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler(get_logger())
    return _error_handler


# 便捷装饰器
def error_handled(operation: str = None):
    """
    错误处理装饰器
    
    Args:
        operation: 操作描述
    
    Example:
        @error_handled("获取设备列表")
        async def get_devices():
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            handler = get_error_handler()
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                handler.handle_error(e, operation=operation)
                return None
        return wrapper
    return decorator
