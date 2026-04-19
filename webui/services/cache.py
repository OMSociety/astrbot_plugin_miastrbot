# -*- coding: utf-8 -*-
"""
缓存服务
"""
from typing import Any, Optional
from datetime import datetime, timedelta

class CacheService:
    """简单的内存缓存"""
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._cache = {}
        self._timestamps = {}
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key not in self._cache:
            return None
        if datetime.now() - self._timestamps.get(key, datetime.min) > timedelta(seconds=self.ttl):
            self.delete(key)
            return None
        return self._cache.get(key)
    
    def set(self, key: str, value: Any):
        """设置缓存"""
        self._cache[key] = value
        self._timestamps[key] = datetime.now()
    
    def delete(self, key: str):
        """删除缓存"""
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._timestamps.clear()
