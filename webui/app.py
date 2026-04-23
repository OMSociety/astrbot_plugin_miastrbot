# -*- coding: utf-8 -*-
"""
FastAPI 应用工厂
"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from astrbot.api import logger
from .blueprints import auth, devices, config, oauth

# Session 管理从 dependencies 导入
from .dependencies import is_authenticated


class AuthMiddleware(BaseHTTPMiddleware):
    """登录验证中间件"""
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # 放行：登录相关 API
        if path in ["/miastrbot/api/login", "/miastrbot/api/logout", "/miastrbot/api/status"]:
            return await call_next(request)
        
        # 放行：小米账号授权 API（不需要 WebUI session）
        if path.startswith("/miastrbot/api/auth/"):
            return await call_next(request)
        
        # 放行：静态资源
        if path.startswith("/miastrbot/static"):
            return await call_next(request)
        
        # 放行：健康检查
        if path in ["/health", "/miastrbot/health"]:
            return await call_next(request)
        
        # 根路径和首页也需要检查认证（除了登录页本身）
        if path in ["/", "/miastrbot", "/miastrbot/"]:
            session_id = request.cookies.get("miastrbot_session")
            if not session_id or not is_authenticated(session_id):
                # 未登录，重定向到登录页
                logger.debug("[miastrbot] 未认证或无效 session（首页访问）")
                return RedirectResponse(url="/miastrbot/api/login", status_code=302)
            return await call_next(request)
        
        # 检查 /miastrbot/ 下的页面请求
        if path.startswith("/miastrbot/"):
            session_id = request.cookies.get("miastrbot_session")
            
            if not session_id or not is_authenticated(session_id):
                # 未登录，重定向到登录页
                logger.debug("[miastrbot] 未认证或无效 session（页面访问）")
                return RedirectResponse(url="/miastrbot/api/login", status_code=302)
        
        response = await call_next(request)
        return response


def create_app(webui_config=None):
    """创建 FastAPI 应用"""
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_dir = os.path.join(plugin_dir, "web_res", "static")
    
    app = FastAPI(
        title="小爱Astrbot",
        description="小爱 + 米家 + AstrBot"
    )
    
    # 添加登录验证中间件
    app.add_middleware(AuthMiddleware)
    
    # 注册蓝图
    app.include_router(auth.router, prefix="/miastrbot/api")
    app.include_router(devices.router, prefix="/miastrbot/api")
    app.include_router(config.router, prefix="/miastrbot/api")
    app.include_router(oauth.router, prefix="/miastrbot/api")
    
    # 根路径重定向
    @app.get("/")
    async def root():
        return RedirectResponse(url="/miastrbot/")
    
    @app.get("/miastrbot")
    async def miastrbot_root():
        return RedirectResponse(url="/miastrbot/")
    
    @app.get("/miastrbot/")
    async def index():
        """主页面"""
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return HTMLResponse(content="<h1>小爱Astrbot WebUI</h1>")
    
    @app.get("/miastrbot/static/{path:path}")
    async def static_files(path: str):
        """静态文件服务（路径穿越防护）"""
        # 路径规范化，防止 ../ 穿越
        resolved = os.path.normpath(os.path.join(static_dir, path))
        # 确保路径在 static_dir 内
        if not resolved.startswith(os.path.normpath(static_dir) + os.sep) and resolved != os.path.normpath(static_dir):
            return HTMLResponse(content="Forbidden", status_code=403)
        if os.path.isfile(resolved):
            return FileResponse(resolved)
        return HTMLResponse(content="File not found", status_code=404)
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    @app.get("/miastrbot/health")
    async def health2():
        return {"status": "ok"}
    
    return app
