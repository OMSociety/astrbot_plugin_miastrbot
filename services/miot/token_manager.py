# -*- coding: utf-8 -*-
"""
Token 管理器 - 负责 Token 的存储和自动刷新

基于 Home Assistant Xiaomi Home 集成的实现
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any

from astrbot.api import logger

# Token 过期时间比例（提前刷新）
TOKEN_EXPIRES_TS_RATIO = 0.7


class TokenInfo:
    """Token 信息"""
    
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        expires_ts: Optional[int] = None,
        user_id: Optional[str] = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in
        self.expires_ts = expires_ts or int(time.time() + expires_in * TOKEN_EXPIRES_TS_RATIO)
        self.user_id = user_id
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "expires_ts": self.expires_ts,
            "user_id": self.user_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenInfo":
        return cls(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_in=data.get("expires_in", 0),
            expires_ts=data.get("expires_ts"),
            user_id=data.get("user_id"),
        )
    
    def is_expired(self, margin: int = 300) -> bool:
        """检查 token 是否即将过期（提前 margin 秒）"""
        return time.time() >= (self.expires_ts - margin)
    
    def needs_refresh(self) -> bool:
        """是否需要刷新"""
        return self.is_expired(margin=0)


class TokenManager:
    """
    Token 管理器
    
    负责：
    - Token 的持久化存储
    - Token 的自动刷新
    - 多账户 Token 管理
    """
    
    def __init__(self, storage_path: str):
        """
        初始化 Token 管理器
        
        Args:
            storage_path: Token 存储文件路径
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._tokens: Dict[str, TokenInfo] = {}  # user_id -> TokenInfo
        self._refresh_locks: Dict[str, asyncio.Lock] = {}  # user_id -> 刷新锁
        self._oauth_client = None  # OAuth 客户端引用
    
    def set_oauth_client(self, oauth_client):
        """设置 OAuth 客户端（用于刷新 token）"""
        self._oauth_client = oauth_client
    
    async def load(self, user_id: str = "default") -> Optional[TokenInfo]:
        """
        从存储加载 Token
        
        Args:
            user_id: 用户 ID
        
        Returns:
            TokenInfo 或 None
        """
        try:
            if not self.storage_path.exists():
                return None
            
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            
            # 兼容旧格式（直接存储 TokenInfo）
            if "access_token" in data:
                token = TokenInfo.from_dict(data)
                self._tokens[user_id] = token
                return token
            
            # 新格式（多账户）
            if user_id in data:
                token = TokenInfo.from_dict(data[user_id])
                self._tokens[user_id] = token
                return token
            
            return None
            
        except Exception as e:
            logger.warning(f"[miastrbot] 加载 Token 失败: {e}")
            return None
    
    async def save(self, token_info: TokenInfo, user_id: str = "default"):
        """
        保存 Token 到存储
        
        Args:
            token_info: Token 信息
            user_id: 用户 ID
        """
        try:
            self._tokens[user_id] = token_info
            
            # 读取现有数据
            data = {}
            if self.storage_path.exists():
                try:
                    data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            
            # 更新对应用户的 token
            data[user_id] = token_info.to_dict()
            
            # 写入文件
            self.storage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            
            logger.debug(f"[miastrbot] Token 已保存: user_id={user_id}")
            
        except Exception as e:
            logger.error(f"[miastrbot] 保存 Token 失败: {e}")
    
    async def get_valid_token(self, user_id: str = "default") -> Optional[str]:
        """
        获取有效的 Token（自动刷新过期 token）
        
        Args:
            user_id: 用户 ID
        
        Returns:
            有效的 access_token 或 None
        """
        # 加载 token（如果还没加载）
        if user_id not in self._tokens:
            await self.load(user_id)
        
        token = self._tokens.get(user_id)
        if not token:
            return None
        
        # 检查是否需要刷新
        if token.needs_refresh():
            # 检查是否有刷新锁
            if user_id not in self._refresh_locks:
                self._refresh_locks[user_id] = asyncio.Lock()
            
            async with self._refresh_locks[user_id]:
                # 双重检查（可能在锁内已经被其他协程刷新）
                if self._tokens.get(user_id) and not self._tokens[user_id].needs_refresh():
                    return self._tokens[user_id].access_token
                
                # 执行刷新
                if self._oauth_client:
                    try:
                        new_token = await self._oauth_client.refresh_token(token.refresh_token)
                        if new_token:
                            new_token.user_id = user_id
                            await self.save(new_token, user_id)
                            return new_token.access_token
                    except Exception as e:
                        logger.error(f"[miastrbot] Token 刷新失败: {e}")
                        return None
        
        return token.access_token
    
    def set_token(self, token_info: TokenInfo, user_id: str = "default"):
        """
        设置 Token（不持久化，需要调用 save）
        
        Args:
            token_info: Token 信息
            user_id: 用户 ID
        """
        self._tokens[user_id] = token_info
    
    def get_token_info(self, user_id: str = "default") -> Optional[TokenInfo]:
        """获取 Token 信息"""
        return self._tokens.get(user_id)
    
    async def clear(self, user_id: str = "default"):
        """
        清除 Token
        
        Args:
            user_id: 用户 ID
        """
        if user_id in self._tokens:
            del self._tokens[user_id]
        
        try:
            if self.storage_path.exists():
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                if user_id in data:
                    del data[user_id]
                    self.storage_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
        except Exception as e:
            logger.warning(f"[miastrbot] 清除 Token 失败: {e}")
