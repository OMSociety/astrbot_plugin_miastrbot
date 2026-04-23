# -*- coding: utf-8 -*-
"""
MIoT 主客户端 - 统一的设备操作接口

整合 OAuth、HTTP 客户端，提供简化的设备控制接口
"""

import logging
from typing import Any, Dict, List, Optional

from astrbot.api import logger

from .oauth_client import MIoTOauthClient, MIoTOauthError
from .http_client import MIoTHttpClient, MIoTHttpError
from .token_manager import TokenManager, TokenInfo


class MIoTClient:
    """
    MIoT 主客户端
    
    提供统一的设备控制接口，整合 OAuth 登录和 HTTP API
    """
    
    def __init__(
        self,
        token_storage_path: str,
        cloud_server: str = "cn",
        client_id: str = "2882303761520251711",
        redirect_url: str = "http://localhost:9528/oauth/callback",
    ):
        """
        初始化 MIoT 客户端
        
        Args:
            token_storage_path: Token 存储路径
            cloud_server: 云服务器（cn/de/i2/ru/sg/us）
            client_id: OAuth 客户端 ID
            redirect_url: OAuth 回调 URL
        """
        self.cloud_server = cloud_server
        
        # 初始化组件
        self.token_manager = TokenManager(token_storage_path)
        self.oauth_client = MIoTOauthClient(
            client_id=client_id,
            redirect_url=redirect_url,
            cloud_server=cloud_server,
        )
        self.http_client = MIoTHttpClient(
            token_manager=self.token_manager,
            cloud_server=cloud_server,
            client_id=client_id,
        )
        
        # Token 管理器需要引用 oauth client（用于刷新）
        self.token_manager.set_oauth_client(self.oauth_client)
    
    def gen_auth_url(self, scope: Optional[str] = None) -> str:
        """
        生成授权 URL
        
        Args:
            scope: 权限范围
        
        Returns:
            授权 URL
        """
        return self.oauth_client.gen_auth_url(scope=scope)
    
    async def authorize(self, code: str) -> bool:
        """
        使用授权码完成授权
        
        Args:
            code: 授权码
        
        Returns:
            是否成功
        """
        try:
            token = await self.oauth_client.get_token(code)
            await self.token_manager.save(token)
            logger.info("[miastrbot] OAuth 授权完成")
            return True
        except MIoTOauthError as e:
            logger.error(f"[miastrbot] OAuth 授权失败: {e}")
            return False
    
    async def is_authorized(self) -> bool:
        """
        检查是否已授权
        
        Returns:
            是否已授权
        """
        token = await self.token_manager.load()
        return token is not None and not token.needs_refresh()
    
    async def get_devices(self, home_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取设备列表
        
        Args:
            home_id: 家庭 ID（可选）
        
        Returns:
            设备信息字典
        """
        try:
            return await self.http_client.get_devices(home_ids=[home_id] if home_id else None)
        except MIoTHttpError as e:
            logger.error(f"[miastrbot] 获取设备失败: {e}")
            raise
    
    async def get_device_prop(
        self, did: str, siid: int, piid: int
    ) -> Optional[Any]:
        """
        读取设备属性
        
        Args:
            did: 设备 ID
            siid: 服务 ID
            piid: 属性 ID
        
        Returns:
            属性值
        """
        try:
            return await self.http_client.get_prop(did, siid, piid)
        except MIoTHttpError as e:
            logger.error(f"[miastrbot] 读取属性失败: {e}")
            raise
    
    async def set_device_prop(
        self, did: str, siid: int, piid: int, value: Any
    ) -> bool:
        """
        设置设备属性
        
        Args:
            did: 设备 ID
            siid: 服务 ID
            piid: 属性 ID
            value: 属性值
        
        Returns:
            是否成功
        """
        try:
            return await self.http_client.set_prop(did, siid, piid, value)
        except MIoTHttpError as e:
            logger.error(f"[miastrbot] 设置属性失败: {e}")
            raise
    
    async def device_action(
        self, did: str, siid: int, aiid: int, in_list: List[Any] = None
    ) -> Dict:
        """
        执行设备动作
        
        Args:
            did: 设备 ID
            siid: 服务 ID
            aiid: 动作 ID
            in_list: 输入参数
        
        Returns:
            执行结果
        """
        try:
            return await self.http_client.do_action(did, siid, aiid, in_list or [])
        except MIoTHttpError as e:
            logger.error(f"[miastrbot] 执行动作失败: {e}")
            raise
    
    async def control_device(
        self,
        did: str,
        action: str,
        params: Dict = None,
    ) -> bool:
        """
        简化的设备控制接口
        
        Args:
            did: 设备 ID
            action: 动作（"on"/"off"/"toggle"）
            params: 额外参数
        
        Returns:
            是否成功
        """
        params = params or {}
        
        # 通用设备控制服务 (siid=2)
        # 开灯: prop set (siid=2, piid=1, value=true)
        # 关灯: prop set (siid=2, piid=1, value=false)
        
        if action in ["on", "off", "open", "close"]:
            value = action in ["on", "open"]
            return await self.set_device_prop(did, siid=2, piid=1, value=value)
        
        elif action == "toggle":
            # 先读取当前状态
            current = await self.get_device_prop(did, siid=2, piid=1)
            if current is not None:
                new_value = not bool(current)
                return await self.set_device_prop(did, siid=2, piid=1, value=new_value)
            return False
        
        return False
    
    async def close(self):
        """关闭客户端，释放资源"""
        await self.oauth_client.close()
        await self.http_client.close()
