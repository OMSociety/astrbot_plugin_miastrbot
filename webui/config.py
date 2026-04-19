# -*- coding: utf-8 -*-
"""
WebUI 配置
"""
from pydantic import BaseModel
from typing import Optional

class WebUIConfig(BaseModel):
    """WebUI 配置模型"""
    host: str = "0.0.0.0"
    port: int = 9528
    password: Optional[str] = ""
    auto_find_port: bool = False
    auto_kill: bool = False  # 是否自动清理占用端口的进程
