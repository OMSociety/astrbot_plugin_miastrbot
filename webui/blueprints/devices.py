# -*- coding: utf-8 -*-
"""
设备蓝图 - 设备管理
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from astrbot.api import logger
from ..dependencies import get_container

router = APIRouter()

@router.get("/devices")
async def api_list_devices():
    """获取米家设备列表"""
    container = get_container()
    if not container or not container.mihome_service:
        return {"success": False, "data": [], "message": "米家服务未初始化，请先扫码登录"}
    
    try:
        devices = await container.mihome_service.list_devices()
        
        devices_with_status = []
        for device in (devices or []):
            device_info = {
                "did": device.get("did", ""),
                "name": device.get("name", "未知设备"),
                "model": device.get("model", ""),
                "online": True,
                "status": "正常"
            }
            devices_with_status.append(device_info)
        
        return {
            "success": True, 
            "data": devices_with_status, 
            "count": len(devices_with_status),
            "speaker_connected": container.speaker_service.is_logged_in if container.speaker_service else False,
            "mihome_connected": container.mihome_service.is_authenticated() if container.mihome_service else False
        }
    except Exception as e:
        return {"success": False, "data": [], "message": f"获取设备失败: {str(e)}"}

@router.get("/devices/{did}/status")
async def api_device_status(did: str):
    """获取设备详细状态"""
    container = get_container()
    if not container or not container.mihome_service:
        return {"success": False, "message": "米家服务未初始化"}
    
    try:
        status = await container.mihome_service.get_device_status(did)
        return {"success": True, "data": status or {}}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/devices/{did}/control")
async def api_control_device(did: str, action: str, params: dict = None):
    """控制设备"""
    container = get_container()
    if not container or not container.mihome_service:
        return {"success": False, "message": "米家服务未初始化"}
    
    try:
        result = await container.mihome_service.control_device(did, action, params or {})
        return {"success": True, "message": "控制成功", "result": result}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/tts")
async def api_test_tts(text: str = "你好，我是小爱"):
    """测试 TTS 播报"""
    container = get_container()
    if not container:
        return {"success": False, "message": "服务未初始化"}
    
    try:
        # 优先使用小爱音箱服务
        if container.speaker_service and container.speaker_service.is_logged_in:
            success = await container.speaker_service.speak(text)
            return {"success": success, "message": "TTS 已发送到小爱音箱" if success else "TTS 发送失败"}
        elif container.tts_server:
            audio_data = await container.tts_server.speak(text)
            return {"success": True, "message": "TTS 合成成功", "note": "仅本地合成，未发送到音箱"}
        else:
            return {"success": False, "message": "小爱音箱服务未初始化，请先配置 Cookie"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/sync-devices")
async def api_sync_devices():
    """手动同步设备列表"""
    container = get_container()
    if not container or not container.mihome_service:
        return {"success": False, "message": "米家服务未初始化"}
    
    try:
        devices = await container.mihome_service.list_devices()
        return {
            "success": True, 
            "message": "同步成功", 
            "count": len(devices) if devices else 0,
            "data": devices
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.get("/speaker/status")
async def api_speaker_status():
    """获取小爱音箱状态"""
    container = get_container()
    if not container:
        return {"success": False, "message": "服务未初始化"}
    
    result = {
        "connected": False,
        "device_id": "",
        "hardware": "",
        "model": ""
    }
    
    if container.speaker_service:
        result["connected"] = container.speaker_service.is_logged_in
        result["device_id"] = getattr(container.speaker_service, "device_id", "") or ""
        result["hardware"] = getattr(container.speaker_service, "hardware", "L05C")
        result["model"] = "小爱音箱" if container.speaker_service.is_logged_in else "未连接"
    
    return {"success": True, "data": result}

@router.post("/speaker/play")
async def api_speaker_play(text: str):
    """通过小爱音箱播放语音"""
    container = get_container()
    if not container or not container.speaker_service:
        return {"success": False, "message": "小爱音箱服务未初始化"}
    
    try:
        success = await container.speaker_service.speak(text)
        return {"success": success, "message": "已发送到小爱音箱" if success else "发送失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.get("/speaker/devices")
async def api_speaker_devices():
    """获取小爱音箱设备列表"""
    container = get_container()
    if not container or not container.speaker_service:
        return {"success": False, "data": [], "message": "小爱音箱服务未初始化"}
    
    try:
        if not container.speaker_service.is_logged_in:
            return {"success": False, "data": [], "message": "请先配置 Cookie"}
        
        # 获取设备列表
        import asyncio
        try:
            device_id = await container.speaker_service.get_device_id()
            devices = [{"deviceID": device_id, "name": "小爱音箱"}]
        except:
            devices = []
        
        return {"success": True, "data": devices or [], "count": len(devices) if devices else 0}
    except Exception as e:
        return {"success": False, "data": [], "message": str(e)}

@router.post("/speaker/login")
async def api_speaker_login():
    """手动触发小爱音箱登录"""
    container = get_container()
    if not container or not container.speaker_service:
        return {"success": False, "message": "小爱音箱服务未初始化"}
    
    try:
        service = container.speaker_service
        if service.is_logged_in:
            return {"success": True, "message": "已登录"}
        
        success = await service.login()
        if success:
            return {"success": True, "message": "登录成功"}
        return {"success": False, "message": "登录失败，请检查 Cookie 配置"}
    except Exception as e:
        logger.warning(f"[miastrbot] WebUI 触发小爱登录失败: {e}")
        return {"success": False, "message": str(e)}
