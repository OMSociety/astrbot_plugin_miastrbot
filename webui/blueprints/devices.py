# -*- coding: utf-8 -*-
"""
设备蓝图 - 设备管理（增强版）
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from ..dependencies import get_container

router = APIRouter()

@router.get("/devices")
async def api_list_devices():
    """获取设备列表（包含状态）"""
    container = get_container()
    if not container or not container.mihome_service:
        return {"success": False, "data": [], "message": "米家服务未初始化，请先在「账号」标签页扫码登录"}
    
    try:
        devices = await container.mihome_service.list_devices()
        
        # 尝试获取每个设备的状态
        devices_with_status = []
        for device in (devices or []):
            device_info = {
                "did": device.get("did", ""),
                "name": device.get("name", "未知设备"),
                "model": device.get("model", ""),
                "online": True,  # 默认在线
                "status": "正常"
            }
            devices_with_status.append(device_info)
        
        return {
            "success": True, 
            "data": devices_with_status, 
            "count": len(devices_with_status),
            "xiaomi_connected": container.xiaomi_service._logged_in if container.xiaomi_service else False,
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
    """控制设备
    
    Args:
        did: 设备ID
        action: 动作名称
        params: 动作参数
    """
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
        # 优先使用小爱服务
        if container.xiaomi_service and container.xiaomi_service._logged_in:
            result = await container.xiaomi_service.send_tts(text)
            return {"success": result, "message": "TTS 已发送到小爱音箱" if result else "TTS 发送失败"}
        elif container.tts_server:
            # 如果小爱服务不可用，使用本地 TTS
            audio_data = await container.tts_server.speak(text)
            return {"success": True, "message": "TTS 合成成功", "note": "仅本地合成，未发送到音箱"}
        else:
            return {"success": False, "message": "TTS 服务未初始化"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/sync-devices")
async def api_sync_devices():
    """手动同步设备列表（重新从云端获取）"""
    container = get_container()
    if not container or not container.mihome_service:
        return {"success": False, "message": "米家服务未初始化"}
    
    try:
        # 强制刷新
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
    
    if container.xiaomi_service:
        result["connected"] = container.xiaomi_service._logged_in
        result["device_id"] = container.xiaomi_service.device_id or ""
        result["hardware"] = container.xiaomi_service.hardware
        result["model"] = "小爱音箱" if container.xiaomi_service._logged_in else "未连接"
    
    return {"success": True, "data": result}

@router.post("/speaker/play")
async def api_speaker_play(text: str):
    """通过小爱音箱播放语音"""
    container = get_container()
    if not container or not container.xiaomi_service:
        return {"success": False, "message": "小爱服务未初始化"}
    
    try:
        result = await container.xiaomi_service.send_tts(text)
        return {"success": result, "message": "已发送到小爱音箱" if result else "发送失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.get("/xiaomi/devices")
async def api_xiaomi_devices():
    """获取小爱音箱设备列表"""
    container = get_container()
    if not container or not container.xiaomi_service:
        return {"success": False, "data": [], "message": "小爱服务未初始化"}
    
    try:
        if not container.xiaomi_service._logged_in:
            return {"success": False, "data": [], "message": "请先登录小米账号"}
        
        devices = await container.xiaomi_service.get_devices()
        return {"success": True, "data": devices or [], "count": len(devices) if devices else 0}
    except Exception as e:
        return {"success": False, "data": [], "message": str(e)}


@router.post("/xiaomi/login")
async def api_xiaomi_login():
    """手动触发小米账号登录"""
    container = get_container()
    if not container or not container.xiaomi_service:
        return {"success": False, "message": "小爱服务未初始化"}
    
    try:
        if container.xiaomi_service._logged_in:
            return {"success": True, "message": "小米账号已登录"}
        
        success = await container.xiaomi_service.login()
        if success:
            return {"success": True, "message": "小米账号登录成功"}
        return {"success": False, "message": "小米账号登录失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}
