# -*- coding: utf-8 -*-
"""
OAuth 客户端 - 小米 OAuth 2.0 授权

基于 Home Assistant Xiaomi Home 集成的实现
参考: https://github.com/XiaoMi/ha_xiaomi_home
"""

import asyncio
import hashlib
import json
import logging
import secrets
import time
from typing import Optional, Dict, Any

import aiohttp

from astrbot.api import logger

from .token_manager import TokenInfo

# 小米 OAuth 配置
OAUTH2_CLIENT_ID = "2882303761520251711"
OAUTH2_AUTH_URL = "https://account.xiaomi.com/oauth2/authorize"
DEFAULT_OAUTH2_API_HOST = "ha.api.io.mi.com"
MIHOME_HTTP_API_TIMEOUT = 30


class MIoTOauthError(Exception):
    """OAuth 错误"""
    pass


class MIoTOauthClient:
    """
    小米 OAuth 2.0 客户端
    
    实现标准的 OAuth 授权码流程：
    1. 生成授权 URL
    2. 用授权码换取 Token
    3. 刷新 Token
    """
    
    def __init__(
        self,
        client_id: str = OAUTH2_CLIENT_ID,
        redirect_url: str = "http://localhost:9528/oauth/callback",
        cloud_server: str = "cn",
        device_id: Optional[str] = None,
    ):
        """
        初始化 OAuth 客户端
        
        Args:
            client_id: OAuth 客户端 ID
            redirect_url: 回调 URL
            cloud_server: 云服务器（cn/de/i2/ru/sg/us）
            device_id: 设备 ID（可选，自动生成）
        """
        self.client_id = client_id
        self.redirect_url = redirect_url
        self.cloud_server = cloud_server
        
        # 生成设备 ID
        if device_id is None:
            device_id = f"ha.{secrets.token_hex(16)}"
        self.device_id = device_id
        
        # 生成 state（用于 CSRF 防护）
        self.state = hashlib.sha1(f"d={self.device_id}".encode()).hexdigest()
        
        # aiohttp session
        self._session: Optional[aiohttp.ClientSession] = None
        
        # OAuth host
        if cloud_server == "cn":
            self.oauth_host = DEFAULT_OAUTH2_API_HOST
        else:
            self.oauth_host = f"{cloud_server}.{DEFAULT_OAUTH2_API_HOST}"
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def gen_auth_url(self, scope: Optional[str] = None, skip_confirm: bool = True) -> str:
        """
        生成授权 URL
        
        Args:
            scope: 权限范围（空格分隔的权限 ID 列表）
            skip_confirm: 是否跳过确认（默认 True）
        
        Returns:
            授权 URL
        """
        params = {
            "redirect_uri": self.redirect_url,
            "client_id": self.client_id,
            "response_type": "code",
            "device_id": self.device_id,
            "state": self.state,
        }
        
        if scope:
            params["scope"] = scope
        
        params["skip_confirm"] = "true" if skip_confirm else "false"
        
        # 构建 URL
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{OAUTH2_AUTH_URL}?{query}"
    
    async def _request_token(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        请求 Token
        
        Args:
            data: 请求数据
        
        Returns:
            Token 响应
        """
        session = await self._get_session()
        
        url = f"https://{self.oauth_host}/app/v2/ha/oauth/get_token"
        
        try:
            async with session.post(
                url,
                data={"data": json.dumps(data)},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=MIHOME_HTTP_API_TIMEOUT),
            ) as resp:
                logger.debug(f"[miastrbot] OAuth token 响应状态: {resp.status}")
                
                if resp.status == 401:
                    raise MIoTOauthError("unauthorized (401)")
                
                if resp.status != 200:
                    text = await resp.text()
                    raise MIoTOauthError(f"HTTP {resp.status}: {text}")
                
                res_str = await resp.text()
                res_obj = json.loads(res_str)
                
                # 验证响应
                if (
                    not res_obj
                    or res_obj.get("code", None) != 0
                    or "result" not in res_obj
                ):
                    raise MIoTOauthError(f"Invalid response: {res_obj}")
                
                result = res_obj["result"]
                
                # 验证必需字段
                required = ["access_token", "refresh_token", "expires_in"]
                for field in required:
                    if field not in result:
                        raise MIoTOauthError(f"Missing field: {field}")
                
                return result
                
        except aiohttp.ClientError as e:
            logger.error(f"[miastrbot] OAuth 请求失败: {e}")
            raise MIoTOauthError(f"Request failed: {e}")
    
    async def get_token(self, code: str) -> TokenInfo:
        """
        用授权码换取 Token
        
        Args:
            code: 授权码（从回调 URL 中获取）
        
        Returns:
            TokenInfo
        """
        logger.info("[miastrbot] 正在获取 Token...")
        
        data = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_url,
            "code": code,
            "device_id": self.device_id,
        }
        
        result = await self._request_token(data)
        
        token = TokenInfo(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            expires_in=result["expires_in"],
            expires_ts=int(time.time() + result["expires_in"] * 0.7),  # 提前刷新
        )
        
        logger.info("[miastrbot] Token 获取成功")
        return token
    
    async def refresh_token(self, refresh_token: str) -> TokenInfo:
        """
        刷新 Access Token
        
        Args:
            refresh_token: 刷新令牌
        
        Returns:
            新的 TokenInfo
        """
        logger.info("[miastrbot] 正在刷新 Token...")
        
        data = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_url,
            "refresh_token": refresh_token,
        }
        
        result = await self._request_token(data)
        
        token = TokenInfo(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            expires_in=result["expires_in"],
            expires_ts=int(time.time() + result["expires_in"] * 0.7),
        )
        
        logger.info("[miastrbot] Token 刷新成功")
        return token
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        获取用户信息
        
        Args:
            access_token: Access Token
        
        Returns:
            用户信息
        """
        session = await self._get_session()
        
        url = "https://open.account.xiaomi.com/user/profile"
        params = {
            "clientId": self.client_id,
            "token": access_token,
        }
        
        try:
            async with session.get(
                url,
                params=params,
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=MIHOME_HTTP_API_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise MIoTOauthError(f"Get user info failed: {resp.status}")
                
                res_str = await resp.text()
                res_obj = json.loads(res_str)
                
                if not res_obj or res_obj.get("code") != 0:
                    raise MIoTOauthError(f"Invalid response: {res_obj}")
                
                return res_obj.get("data", {})
                
        except aiohttp.ClientError as e:
            logger.error(f"[miastrbot] 获取用户信息失败: {e}")
            raise MIoTOauthError(f"Request failed: {e}")
