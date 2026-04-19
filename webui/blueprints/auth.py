# -*- coding: utf-8 -*-
"""
认证蓝图 - 登录/登出
"""
import os
import secrets
from fastapi import APIRouter, Form, Cookie, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from typing import Optional

router = APIRouter()

# Session 管理从 dependencies 导入（统一存储）
from ..dependencies import is_authenticated, add_session, remove_session


def get_container():
    """延迟导入避免循环依赖"""
    try:
        from ..dependencies import get_container as gc
        return gc()
    except Exception:
        return None


@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    """处理登录"""
    container = get_container()
    
    # 无密码配置或密码匹配即可登录
    expected_pwd = ""
    if container and container.webui_config:
        expected_pwd = container.webui_config.password or ""
    
    # 如果没设置密码，或者密码匹配
    if not expected_pwd or password == expected_pwd:
        # 生成 session
        session_id = secrets.token_hex(16)
        add_session(session_id)
        
        response = JSONResponse({
            "success": True, 
            "message": "登录成功",
            "redirect": "/miastrbot/"
        })
        response.set_cookie(
            key="miastrbot_session",
            value=session_id,
            httponly=True,
            max_age=86400,  # 1天
            samesite="lax",
            path="/"  # 确保 cookie 覆盖整个站点
        )
        return response
    
    return JSONResponse({
        "success": False, 
        "message": "密码错误"
    }, status_code=401)


@router.get("/login")
async def login_page():
    """登录页面"""
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    login_path = os.path.join(plugin_dir, "web_res", "static", "login.html")
    
    if os.path.exists(login_path):
        with open(login_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    
    # 内联登录页面
    return HTMLResponse(content=LOGIN_PAGE_HTML)


@router.post("/logout")
async def logout(session_id: Optional[str] = Cookie(default=None, alias="miastrbot_session")):
    """登出"""
    if session_id:
        remove_session(session_id)
    
    response = JSONResponse({"success": True, "message": "已退出"})
    response.delete_cookie("miastrbot_session", path="/")
    return response


@router.get("/logout")
async def logout_get(session_id: Optional[str] = Cookie(default=None, alias="miastrbot_session")):
    """兼容浏览器 GET 登出"""
    if session_id:
        remove_session(session_id)
    response = RedirectResponse(url="/miastrbot/api/login", status_code=302)
    response.delete_cookie("miastrbot_session", path="/")
    return response


@router.get("/status")
async def status(session_id: Optional[str] = Cookie(default=None, alias="miastrbot_session")):
    """获取登录状态"""
    is_auth = is_authenticated(session_id)
    print(f"[Auth Status] session_id: {session_id[:8] if session_id else None}, authenticated: {is_auth}")
    return {
        "authenticated": is_auth,
    }


# 内联登录页面 HTML
LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小爱Astrbot - 登录</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #19CD90 0%, #2DE5A8 100%);
        }
        .login-container { width: 100%; max-width: 400px; padding: 20px; }
        .login-card {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.2);
        }
        .logo { text-align: center; margin-bottom: 30px; }
        .logo-icon {
            width: 80px; height: 80px;
            background: linear-gradient(135deg, #19CD90, #2DE5A8);
            border-radius: 20px;
            display: flex; align-items: center; justify-content: center;
            margin: 0 auto 16px; font-size: 40px;
        }
        h1 { color: #333; margin-bottom: 8px; }
        .subtitle { color: #666; font-size: 14px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; color: #666; margin-bottom: 8px; font-size: 14px; }
        input {
            width: 100%; padding: 14px 16px;
            border: 1px solid #E5E5E7;
            border-radius: 12px; font-size: 16px;
            transition: border-color 0.2s;
        }
        input:focus { outline: none; border-color: #19CD90; }
        .btn {
            width: 100%; padding: 14px;
            background: linear-gradient(135deg, #19CD90, #2DE5A8);
            color: white; border: none;
            border-radius: 12px; font-size: 16px;
            font-weight: 600; cursor: pointer;
            transition: transform 0.2s;
        }
        .btn:hover { transform: scale(1.02); }
        .btn:active { transform: scale(0.98); }
        .error {
            color: #FF3B30; font-size: 14px;
            margin-top: 12px; text-align: center;
            display: none;
        }
        .footer { text-align: center; margin-top: 24px; color: #999; font-size: 12px; }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-card">
            <div class="logo">
                <div class="logo-icon">🏠</div>
                <h1>小爱Astrbot</h1>
                <p class="subtitle">小爱音箱 + 米家控制中心</p>
            </div>
            <form id="loginForm">
                <div class="form-group">
                    <label>访问密码</label>
                    <input type="password" id="password" placeholder="请输入访问密码" required>
                </div>
                <button type="submit" class="btn">登 录</button>
                <p class="error" id="errorMsg"></p>
            </form>
            <p class="footer">小爱Astrbot v2.0</p>
        </div>
    </div>
    <script>
        document.getElementById("loginForm").addEventListener("submit", async (e) => {
            e.preventDefault();
            const password = document.getElementById("password").value;
            const errorMsg = document.getElementById("errorMsg");
            
            try {
                const formData = new FormData();
                formData.append("password", password);
                
                const res = await fetch("/miastrbot/api/login", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                
                if (data.success) {
                    window.location.href = data.redirect || "/miastrbot/";
                } else {
                    errorMsg.textContent = data.message || "密码错误";
                    errorMsg.style.display = "block";
                }
            } catch (e) {
                errorMsg.textContent = "登录失败，请检查服务器连接";
                errorMsg.style.display = "block";
            }
        });
    </script>
</body>
</html>
"""
