# -*- coding: utf-8 -*-
"""
自定义异常类

定义插件专用的异常类型
"""


class MiASTRBotError(Exception):
    """插件基础异常类"""
    
    def __init__(self, message: str = None, code: int = None):
        """
        初始化异常
        
        Args:
            message: 错误消息
            code: 错误代码
        """
        self.message = message or "未知错误"
        self.code = code
        super().__init__(self.message)
    
    def __str__(self):
        if self.code is not None:
            return f"[{self.code}] {self.message}"
        return self.message


class MiASTRBotConfigError(MiASTRBotError):
    """
    配置错误
    
    当配置文件格式错误或缺少必需字段时抛出
    """
    
    def __init__(self, message: str = None, field: str = None):
        """
        初始化配置错误
        
        Args:
            message: 错误消息
            field: 出错的配置字段
        """
        self.field = field
        msg = message or "配置错误"
        if field:
            msg = f"配置字段 '{field}' {msg}"
        super().__init__(message=msg, code=1001)


class MiASTRBotServiceError(MiASTRBotError):
    """
    服务错误
    
    当服务初始化或运行出错时抛出
    """
    
    def __init__(self, message: str = None, service: str = None):
        """
        初始化服务错误
        
        Args:
            message: 错误消息
            service: 服务名称
        """
        self.service = service
        msg = message or "服务错误"
        if service:
            msg = f"服务 '{service}' {msg}"
        super().__init__(message=msg, code=2001)


class MiASTRBotAuthError(MiASTRBotServiceError):
    """
    认证错误
    
    当登录或权限验证失败时抛出
    """
    
    def __init__(self, message: str = None, service: str = None):
        """
        初始化认证错误
        
        Args:
            message: 错误消息
            service: 服务名称
        """
        msg = message or "认证失败"
        super().__init__(message=msg, service=service)
        self.code = 2002


class MiASTRBotNetworkError(MiASTRBotServiceError):
    """
    网络错误
    
    当网络请求失败时抛出
    """
    
    def __init__(self, message: str = None, url: str = None):
        """
        初始化网络错误
        
        Args:
            message: 错误消息
            url: 请求URL
        """
        self.url = url
        msg = message or "网络请求失败"
        if url:
            msg = f"请求 {url} {msg}"
        super().__init__(message=msg, service="network")
        self.code = 2003


class MiASTRBotDeviceError(MiASTRBotServiceError):
    """
    设备错误
    
    当设备操作失败时抛出
    """
    
    def __init__(self, message: str = None, device: str = None):
        """
        初始化设备错误
        
        Args:
            message: 错误消息
            device: 设备名称或ID
        """
        self.device = device
        msg = message or "设备操作失败"
        if device:
            msg = f"设备 '{device}' {msg}"
        super().__init__(message=msg, service="device")
        self.code = 2004


class MiASTRBotTimeoutError(MiASTRBotServiceError):
    """
    超时错误
    
    当操作超时时抛出
    """
    
    def __init__(self, message: str = None, timeout: float = None):
        """
        初始化超时错误
        
        Args:
            message: 错误消息
            timeout: 超时时间（秒）
        """
        self.timeout = timeout
        msg = message or "操作超时"
        if timeout:
            msg = f"{msg} ({timeout}秒)"
        super().__init__(message=msg, service="timeout")
        self.code = 2005


class MiASTRBotEventError(MiASTRBotError):
    """
    事件错误
    
    当事件处理出错时抛出
    """
    
    def __init__(self, message: str = None, event_type: str = None):
        """
        初始化事件错误
        
        Args:
            message: 错误消息
            event_type: 事件类型
        """
        self.event_type = event_type
        msg = message or "事件处理失败"
        if event_type:
            msg = f"事件 '{event_type}' {msg}"
        super().__init__(message=msg, code=3001)
