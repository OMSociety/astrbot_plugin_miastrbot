# -*- coding: utf-8 -*-
"""
OAuth 蓝图 - 二维码授权登录 + WebSocket 实时推送
"""
import os
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any

router = APIRouter()

import logging
logger = logging.getLogger("miastrbot.oauth")


# WebSocket 连接管理器
class ConnectionManager:
    """管理 WebSocket 连接"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.login_waiters: Dict[str, asyncio.Future] = {}
    
    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"[OAuth WS] 客户端连接: {client_id}")
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.login_waiters:
            self.login_waiters[client_id].cancel()
            del self.login_waiters[client_id]
        logger.info(f"[OAuth WS] 客户端断开: {client_id}")
    
    async def send_json(self, client_id: str, data: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(data)
    
    async def broadcast(self, data: dict):
        for ws in self.active_connections.values():
            await ws.send_json(data)


# 全局连接管理器
ws_manager = ConnectionManager()


def get_container():
    """延迟导入避免循环依赖"""
    try:
        from ..dependencies import get_container as _dep_get_container
        return _dep_get_container()
    except Exception as e:
        logger.error(f"获取容器失败: {e}")
        return None


@router.websocket("/ws/login")
async def websocket_login(websocket: WebSocket):
    """
    WebSocket 登录通道
    
    消息格式:
    - 客户端发送: {"action": "start_login"}
    - 服务端推送: {"type": "qr_url", "url": "..."}
    - 服务端推送: {"type": "login_success"}
    - 服务端推送: {"type": "login_error", "error": "..."}
    """
    import uuid
    client_id = str(uuid.uuid4())
    await ws_manager.connect(client_id, websocket)
    
    try:
        # 保持连接，处理消息
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                
                if action == "start_login":
                    await handle_login_start(client_id)
                elif action == "check_status":
                    await handle_check_status(client_id)
                else:
                    await ws_manager.send_json(client_id, {
                        "type": "error",
                        "message": f"未知动作: {action}"
                    })
                    
            except json.JSONDecodeError:
                await ws_manager.send_json(client_id, {
                    "type": "error",
                    "message": "无效的 JSON 格式"
                })
                
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"[OAuth WS] 异常: {e}")
        ws_manager.disconnect(client_id)


async def handle_login_start(client_id: str):
    """处理登录开始请求"""
    container = get_container()
    if not container or not container.mihome_service:
        await ws_manager.send_json(client_id, {
            "type": "login_error",
            "error": "米家服务未初始化，请重启插件"
        })
        return
    
    mihome_service = container.mihome_service
    
    # 检查是否已登录
    try:
        status = await mihome_service.get_login_status()
        if status.get("auth_exists") and not status.get("login_in_progress"):
            await ws_manager.send_json(client_id, {
                "type": "login_success",
                "message": "已登录"
            })
            return
    except Exception as e:
        logger.warning(f"[OAuth] 检查登录状态失败: {e}")
    
    # 启动异步登录任务
    asyncio.create_task(run_async_login(client_id, mihome_service))


async def run_async_login(client_id: str, mihome_service):
    """异步运行登录流程，通过 WebSocket 推送结果"""
    qr_url_holder = {"url": None}
    
    async def qr_callback(url: str):
        qr_url_holder["url"] = url
        await ws_manager.send_json(client_id, {
            "type": "qr_url",
            "url": url
        })
        logger.info(f"[OAuth] 推送二维码 URL: {url[:50]}...")
    
    try:
        result = await mihome_service.login(qr_callback=qr_callback)
        
        if result.get("status") == "success":
            await ws_manager.send_json(client_id, {
                "type": "login_success",
                "message": "登录成功"
            })
        elif result.get("status") == "started":
            await ws_manager.send_json(client_id, {
                "type": "login_started",
                "message": result.get("message", "登录流程已启动，请扫码")
            })
        elif result.get("status") == "in_progress":
            await ws_manager.send_json(client_id, {
                "type": "login_in_progress",
                "message": "已有登录流程在进行中"
            })
            qr_url = qr_url_holder.get("url")
            if qr_url:
                await ws_manager.send_json(client_id, {"type": "qr_url", "url": qr_url})
        else:
            await ws_manager.send_json(client_id, {
                "type": "login_error",
                "error": result.get("message", "登录失败")
            })
            
    except Exception as e:
        logger.error(f"[OAuth] 登录异常: {e}")
        await ws_manager.send_json(client_id, {
            "type": "login_error",
            "error": str(e)
        })


async def handle_check_status(client_id: str):
    """处理状态检查请求"""
    container = get_container()
    if not container or not container.mihome_service:
        await ws_manager.send_json(client_id, {
            "type": "status",
            "logged_in": False,
            "error": "服务未初始化"
        })
        return
    
    try:
        status = await container.mihome_service.get_login_status()
        await ws_manager.send_json(client_id, {
            "type": "status",
            "logged_in": status.get("auth_exists", False),
            "login_in_progress": status.get("login_in_progress", False),
            "last_login_at": status.get("last_login_at", ""),
            "last_error": status.get("last_login_error", "")
        })
    except Exception as e:
        await ws_manager.send_json(client_id, {
            "type": "status",
            "logged_in": False,
            "error": str(e)
        })


# ========== 保留原有的 REST API（兼容性）==========

@router.post("/auth/start_qr")
async def start_qr_login():
    """
    启动二维码登录（REST 模式，已废弃，建议使用 WebSocket）
    """
    return JSONResponse({
        "success": False,
        "message": "此接口已废弃，请使用 WebSocket /ws/login"
    }, status_code=410)


@router.get("/auth/qr_status")
async def get_qr_status():
    """获取登录状态"""
    container = get_container()
    if not container or not container.mihome_service:
        return {
            "status": "error",
            "message": "服务未初始化",
            "qr_url": "",
        }
    
    try:
        login_status = await container.mihome_service.get_login_status()
        return {
            "status": "success" if login_status.get("auth_exists") else "waiting",
            "login_in_progress": login_status.get("login_in_progress", False),
            "auth_exists": login_status.get("auth_exists", False),
            "last_login_at": login_status.get("last_login_at", ""),
            "last_login_error": login_status.get("last_login_error", ""),
            "qr_url": "",
        }
    except Exception as e:
        logger.error(f"获取登录状态失败: {e}")
        return {
            "status": "error",
            "message": str(e),
            "qr_url": "",
        }


@router.get("/auth/status")
async def get_auth_status():
    """获取当前授权状态"""
    container = get_container()
    
    xiaomi_ok = False
    mihome_ok = False
    mihome_status = {}
    
    if container:
        if container.xiaomi_service:
            try:
                xiaomi_ok = container.xiaomi_service._logged_in
            except:
                xiaomi_ok = False
        
        if container.mihome_service:
            try:
                mihome_status = await container.mihome_service.get_login_status()
                mihome_ok = mihome_status.get("auth_exists", False)
            except:
                mihome_ok = False
    
    return {
        "xiaomi": xiaomi_ok,
        "mihome": mihome_ok,
        "mihome_detail": mihome_status,
    }


@router.post("/auth/logout")
async def logout():
    """登出并清除认证"""
    container = get_container()
    
    if container:
        if container.xiaomi_service:
            try:
                container.xiaomi_service._logged_in = False
            except:
                pass
        if container.mihome_service:
            try:
                await container.mihome_service.logout()
            except:
                pass
    
    return {"success": True, "message": "已登出"}


@router.get("/devices")
async def oauth_list_devices():
    """获取设备列表（OAuth 蓝图，已废弃，请使用 /api/devices）"""
    container = get_container()
    if not container or not container.mihome_service:
        return {"success": False, "data": [], "message": "米家服务未初始化"}
    
    try:
        devices = await container.mihome_service.list_devices()
        return {"success": True, "data": devices or [], "count": len(devices) if devices else 0}
    except Exception as e:
        return {"success": False, "data": [], "message": str(e)}
