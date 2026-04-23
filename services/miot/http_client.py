# -*- coding: utf-8 -*-
"""
MIoT HTTP 客户端 - 设备控制 API

基于 Home Assistant Xiaomi Home 集成的实现
参考: https://github.com/XiaoMi/ha_xiaomi_home
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from astrbot.api import logger

# API 配置
DEFAULT_OAUTH2_API_HOST = "ha.api.io.mi.com"
MIHOME_HTTP_API_TIMEOUT = 30


class MIoTHttpError(Exception):
    """HTTP API 错误"""
    pass


class MIoTHttpClient:
    """
    MIoT HTTP API 客户端
    
    用于：
    - 获取设备列表
    - 读取设备属性
    - 设置设备属性
    - 执行设备动作
    """
    
    def __init__(
        self,
        token_manager,
        cloud_server: str = "cn",
        client_id: str = "2882303761520251711",
    ):
        """
        初始化 HTTP 客户端
        
        Args:
            token_manager: Token 管理器
            cloud_server: 云服务器
            client_id: OAuth 客户端 ID
        """
        self.token_manager = token_manager
        self.cloud_server = cloud_server
        self.client_id = client_id
        
        # API Host
        if cloud_server == "cn":
            self.host = DEFAULT_OAUTH2_API_HOST
        else:
            self.host = f"{cloud_server}.{DEFAULT_OAUTH2_API_HOST}"
        
        self.base_url = f"https://{self.host}"
        
        # aiohttp session
        self._session: Optional[aiohttp.ClientSession] = None
    
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
    
    async def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        access_token = await self.token_manager.get_valid_token()
        if not access_token:
            raise MIoTHttpError("No valid access token")
        
        return {
            "Host": self.host,
            "X-Client-BizId": "haapi",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "X-Client-AppId": self.client_id,
        }
    
    async def _api_get(self, url_path: str, params: Dict = None) -> Dict:
        """GET 请求"""
        session = await self._get_session()
        headers = await self._get_headers()
        url = f"{self.base_url}{url_path}"
        
        try:
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=MIHOME_HTTP_API_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise MIoTHttpError("Unauthorized (401)", code="INVALID_TOKEN")
                
                if resp.status != 200:
                    text = await resp.text()
                    raise MIoTHttpError(f"HTTP {resp.status}: {text}")
                
                res_str = await resp.text()
                res_obj = json.loads(res_str)
                
                if res_obj.get("code") != 0:
                    raise MIoTHttpError(
                        f"API error: {res_obj.get('code')}: {res_obj.get('message')}",
                        code=res_obj.get("code"),
                    )
                
                logger.debug(f"[miastrbot] API GET {url_path}: {res_obj.get('code')}")
                return res_obj
                
        except aiohttp.ClientError as e:
            logger.error(f"[miastrbot] API 请求失败: {e}")
            raise MIoTHttpError(f"Request failed: {e}")
    
    async def _api_post(self, url_path: str, data: Dict = None) -> Dict:
        """POST 请求"""
        session = await self._get_session()
        headers = await self._get_headers()
        url = f"{self.base_url}{url_path}"
        
        try:
            async with session.post(
                url,
                json=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=MIHOME_HTTP_API_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise MIoTHttpError("Unauthorized (401)", code="INVALID_TOKEN")
                
                if resp.status != 200:
                    text = await resp.text()
                    raise MIoTHttpError(f"HTTP {resp.status}: {text}")
                
                res_str = await resp.text()
                res_obj = json.loads(res_str)
                
                if res_obj.get("code") != 0:
                    raise MIoTHttpError(
                        f"API error: {res_obj.get('code')}: {res_obj.get('message')}",
                        code=res_obj.get("code"),
                    )
                
                logger.debug(f"[miastrbot] API POST {url_path}: {res_obj.get('code')}")
                return res_obj
                
        except aiohttp.ClientError as e:
            logger.error(f"[miastrbot] API 请求失败: {e}")
            raise MIoTHttpError(f"Request failed: {e}")
    
    async def get_homeinfos(self) -> Dict[str, Any]:
        """
        获取家庭列表
        
        Returns:
            包含 uid 和 home_list 的字典
        """
        res = await self._api_post(
            "/app/v2/homeroom/gethome",
            data={
                "limit": 150,
                "fetch_share": True,
                "fetch_share_dev": True,
                "plat_form": 0,
                "app_ver": 9,
            },
        )
        
        if "result" not in res:
            raise MIoTHttpError("Invalid response: no result")
        
        result = res["result"]
        uid = None
        home_list = {}
        
        for device_source in ["homelist", "share_home_list"]:
            for home in result.get(device_source, []):
                if "id" not in home or "name" not in home:
                    continue
                
                if uid is None and device_source == "homelist":
                    uid = str(home.get("uid"))
                
                home_list[home["id"]] = {
                    "home_id": home["id"],
                    "home_name": home["name"],
                    "uid": str(home.get("uid")),
                    "dids": home.get("dids", []),
                }
        
        return {"uid": uid, "home_list": home_list}
    
    async def get_device_list(self, dids: List[str]) -> Dict[str, Dict]:
        """
        获取设备列表
        
        Args:
            dids: 设备 ID 列表
        
        Returns:
            设备信息字典 {did: device_info}
        """
        res = await self._api_post(
            "/app/v2/home/device_list_page",
            data={
                "limit": 200,
                "get_split_device": True,
                "get_third_device": True,
                "dids": dids,
            },
        )
        
        if "result" not in res:
            raise MIoTHttpError("Invalid response: no result")
        
        devices = {}
        for device in res["result"].get("list", []):
            did = device.get("did")
            if not did or not device.get("name"):
                continue
            
            devices[did] = {
                "did": did,
                "name": device.get("name"),
                "model": device.get("model"),
                "online": device.get("isOnline", False),
                "local_ip": device.get("local_ip"),
                "token": device.get("token"),
                "parent_id": device.get("parent_id"),
            }
        
        return devices
    
    async def get_devices(self, home_ids: List[str] = None) -> Dict[str, Any]:
        """
        获取所有设备
        
        Args:
            home_ids: 家庭 ID 列表（可选）
        
        Returns:
            包含 uid, homes, devices 的字典
        """
        # 获取家庭信息
        homeinfos = await self.get_homeinfos()
        
        homes = homeinfos.get("home_list", {})
        devices = {}
        
        # 收集所有设备的 DID
        all_dids = []
        for home_id, home_info in homes.items():
            if home_ids and home_id not in home_ids:
                continue
            all_dids.extend(home_info.get("dids", []))
        
        if not all_dids:
            return {"uid": homeinfos.get("uid"), "homes": homes, "devices": {}}
        
        # 批量获取设备信息
        device_infos = await self.get_device_list(all_dids)
        
        # 合并信息
        for home_id, home_info in homes.items():
            for did in home_info.get("dids", []):
                if did in device_infos:
                    devices[did] = {
                        **home_info,
                        **device_infos.get(did, {}),
                    }
        
        return {
            "uid": homeinfos.get("uid"),
            "homes": homes,
            "devices": devices,
        }
    
    async def get_prop(
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
        res = await self._api_post(
            "/app/v2/miotspec/prop/get",
            data={
                "datasource": 1,
                "params": [{"did": did, "siid": siid, "piid": piid}],
            },
        )
        
        result = res.get("result", [])
        if not result:
            return None
        
        value = result[0].get("value")
        return value
    
    async def set_prop(
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
        res = await self._api_post(
            "/app/v2/miotspec/prop/set",
            data={
                "params": [{"did": did, "siid": siid, "piid": piid, "value": value}],
            },
        )
        
        # 返回成功（MIoT 的 set 接口通常不返回详细错误）
        logger.info(f"[miastrbot] 设置属性成功: {did}/{siid}/{piid} = {value}")
        return True
    
    async def do_action(
        self,
        did: str,
        siid: int,
        aiid: int,
        in_list: List[Any],
    ) -> Dict:
        """
        执行设备动作
        
        Args:
            did: 设备 ID
            siid: 服务 ID
            aiid: 动作 ID
            in_list: 输入参数列表
        
        Returns:
            执行结果
        """
        res = await self._api_post(
            "/app/v2/miotspec/action",
            data={
                "params": {
                    "did": did,
                    "siid": siid,
                    "aiid": aiid,
                    "in": in_list,
                },
            },
        )
        
        logger.info(f"[miastrbot] 执行动作成功: {did}/{siid}/{aiid}")
        return res.get("result", {})
