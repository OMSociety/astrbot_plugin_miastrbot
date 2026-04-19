# -*- coding: utf-8 -*-
"""
配置缓存模块
"""

from typing import Any, Optional
from datetime import datetime, timedelta


class ConfigCache:
    """
    配置缓存
    
    特性:
    - 内存缓存
    - TTL过期
    - 手动刷新
    """
    
    def __init__(self, ttl_seconds: int = 300):
        """
        初始化缓存
        
        Args:
            ttl_seconds: 缓存过期时间（秒），默认5分钟
        """
        self.ttl = ttl_seconds
        self._cache: dict = {}
        self._timestamps: dict = {}
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存
        
        Args:
            key: 缓存键
        
        Returns:
            缓存值，过期返回None
        """
        if key not in self._cache:
            return None
        
        # 检查是否过期
        timestamp = self._timestamps.get(key)
        if timestamp:
            if datetime.now() - timestamp > timedelta(seconds=self.ttl):
                # 已过期，删除
                self.delete(key)
                return None
        
        return self._cache.get(key)
    
    def set(self, key: str, value: Any):
        """
        设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        self._cache[key] = value
        self._timestamps[key] = datetime.now()
    
    def delete(self, key: str):
        """
        删除缓存
        
        Args:
            key: 缓存键
        """
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)
    
    def clear(self):
        """清空所有缓存"""
        self._cache.clear()
        self._timestamps.clear()
    
    def invalidate(self, key: str = None):
        """
        使缓存失效
        
        Args:
            key: 指定键，不传则清空所有
        """
        if key:
            self.delete(key)
        else:
            self.clear()
