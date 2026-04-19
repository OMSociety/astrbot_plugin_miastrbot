# -*- coding: utf-8 -*-
"""
数据管理器 - 管理认证文件和状态
"""
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

AUTH_FILENAME = "mi_auth.json"
STATE_FILENAME = "state.json"


class MiAstrBotDataManager:
    """管理 miastrbot 的数据和状态"""
    
    def __init__(self, plugin_data_dir: str):
        self.data_dir = Path(plugin_data_dir)
        self.auth_path = self.data_dir / AUTH_FILENAME
        self.state_path = self.data_dir / STATE_FILENAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def get_auth_path(self) -> str:
        """获取认证文件路径"""
        return str(self.auth_path)
    
    def auth_exists(self) -> bool:
        """检查认证文件是否存在"""
        return self.auth_path.exists() and self.auth_path.stat().st_size > 0
    
    def clear_auth_file(self) -> bool:
        """清除认证文件"""
        try:
            if self.auth_path.exists():
                self.auth_path.unlink()
            return True
        except Exception:
            return False
    
    def load_state(self) -> Dict[str, Any]:
        """加载状态"""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def save_state(self, state: Dict[str, Any]):
        """保存状态"""
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    
    def update_state(self, **kwargs):
        """更新状态字段"""
        state = self.load_state()
        state.update(kwargs)
        self.save_state(state)
