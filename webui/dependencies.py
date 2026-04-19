# -*- coding: utf-8 -*-
"""
依赖注入容器
"""
from typing import Optional, Set
from dataclasses import dataclass, field
from ..config_manager import MiASTRBotConfigManager
from ..services.mihome_service import MiHomeService
from ..agent.handler import AgentHandler
from .config import WebUIConfig

# 全局 Session 存储（替代原来的 _sessions 集合）
_sessions: Set[str] = set()

def is_authenticated(session_id: str = None) -> bool:
    """检查 session 是否有效"""
    return session_id in _sessions and session_id is not None

def add_session(session_id: str):
    """添加 session"""
    _sessions.add(session_id)

def remove_session(session_id: str):
    """移除 session"""
    _sessions.discard(session_id)


@dataclass
class Container:
    """
    依赖注入容器
    """
    config_manager: Optional[MiASTRBotConfigManager] = None
    xiaomi_service: Optional[object] = None
    mihome_service: Optional[MiHomeService] = None
    agent_handler: Optional[AgentHandler] = None
    webui_config: WebUIConfig = field(default_factory=WebUIConfig)

_container: Optional[Container] = None

def init_container(
    config_manager=None,
    xiaomi_service=None,
    mihome_service=None,
    agent_handler=None,
    webui_config=None
) -> Container:
    """
    初始化容器
    """
    global _container
    _container = Container(
        config_manager=config_manager,
        xiaomi_service=xiaomi_service,
        mihome_service=mihome_service,
        agent_handler=agent_handler,
        webui_config=webui_config or WebUIConfig()
    )
    return _container

def get_container() -> Container:
    """
    获取容器（单例）
    如果容器未初始化，返回 None 而不是自动创建空容器
    """
    global _container
    return _container
