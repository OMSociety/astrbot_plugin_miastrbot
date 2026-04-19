# -*- coding: utf-8 -*-
"""
WebUI 单例服务器 - 参考 self_learning 架构
"""
import os
import sys
import asyncio
import socket
import threading
from typing import Optional
import hypercorn.asyncio
from hypercorn.config import Config as HypercornConfig

try:
    from hypercorn.config import Sockets
except ImportError:
    class Sockets:
        def __init__(self, secure_sockets, insecure_sockets, quic_sockets):
            self.secure_sockets = secure_sockets
            self.insecure_sockets = insecure_sockets
            self.quic_sockets = quic_sockets

from astrbot.api import logger
from .app import create_app
from .dependencies import get_container


class SecureConfig(HypercornConfig):
    """安全的 Hypercorn 配置"""
    
    def create_sockets(self):
        insecure_sockets = []
        secure_sockets = []
        quic_sockets = []
        
        for bind in self.bind:
            if ":" in bind:
                host, port = bind.rsplit(":", 1)
                port = int(port)
            else:
                host = bind
                port = 80
            
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if sys.platform != "win32" and hasattr(socket, "SO_REUSEPORT"):
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except (AttributeError, OSError):
                        pass
                sock.set_inheritable(False)
                sock.bind((host, port))
                sock.listen(128)
                insecure_sockets.append(sock)
            except Exception as e:
                logger.error(f"[miastrbot] Socket 创建失败 {bind}: {e}")
                try:
                    sock.close()
                except Exception:
                    pass
                raise
        
        return Sockets(secure_sockets, insecure_sockets, quic_sockets)


class Server:
    """WebUI 单例服务器（守护线程模式）"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Server, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, host: str = "0.0.0.0", port: int = 9528, auto_find_port: bool = False, auto_kill: bool = False):
        if hasattr(self, "_initialized") and self._initialized:
            return
        
        self._initialized = True
        self.host = host
        self.port = port
        self.auto_kill = auto_kill  # 是否自动清理占用端口的进程
        self.server_thread: Optional[threading.Thread] = None
        self._thread_loop = None
        self._shutdown_event = None
        self.app = None
        
        logger.info(f"[miastrbot] WebUI 服务初始化 (端口: {port}, 自动清理: {auto_kill})")
    
    def _run_thread(self):
        """在独立线程中运行 Hypercorn 服务器"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._thread_loop = loop
            self._shutdown_event = asyncio.Event()
            
            config = SecureConfig()
            config.bind = [f"{self.host}:{self.port}"]
            config.accesslog = None
            config.errorlog = None
            config.loglevel = "WARNING"
            config.workers = 1
            config.worker_class = "asyncio"
            
            loop.run_until_complete(
                hypercorn.asyncio.serve(
                    self.app,
                    config,
                    shutdown_trigger=self._shutdown_event.wait
                )
            )
            loop.close()
            logger.debug("[miastrbot] WebUI 服务线程已退出")
        except Exception as e:
            logger.error(f"[miastrbot] WebUI 服务线程异常: {e}")
    
    async def start(self):
        """启动服务"""
        try:
            if self.server_thread and self.server_thread.is_alive():
                logger.info("[miastrbot] WebUI 服务已在运行中")
                return
            
            # 检查端口是否可用
            if not self._is_port_available(self.port):
                if self.auto_kill:
                    logger.warning(f"[miastrbot] 端口 {self.port} 被占用，尝试清理...")
                    await self._kill_port_holder(self.port)
                else:
                    logger.error(f"[miastrbot] 端口 {self.port} 被占用，auto_kill 已禁用，请手动清理或更换端口")
                    raise RuntimeError(f"端口 {self.port} 被占用")
            
            # 获取配置并创建应用
            container = get_container()
            self.app = create_app(container.webui_config)
            
            # 在守护线程中启动服务
            logger.info(f"[miastrbot] 启动 WebUI: http://{self.host}:{self.port}")
            
            self.server_thread = threading.Thread(
                target=self._run_thread,
                daemon=True,
                name="MiASTRBot_WebUI"
            )
            self.server_thread.start()
            
            # 验证服务是否成功启动
            for _ in range(5):
                await asyncio.sleep(1.0)
                if await self._verify_tcp():
                    logger.info(f"[miastrbot] WebUI 服务启动成功!")
                    logger.info(f"[miastrbot] 本地访问: http://127.0.0.1:{self.port}")
                    return
            
            logger.warning("[miastrbot] WebUI 服务线程已启动但端口无响应")
            
        except Exception as e:
            logger.error(f"[miastrbot] WebUI 服务启动失败: {e}", exc_info=True)
            raise
    
    async def stop(self):
        """停止服务"""
        try:
            logger.info("[miastrbot] 停止 WebUI 服务...")
            
            if self._thread_loop and self._shutdown_event:
                try:
                    self._thread_loop.call_soon_threadsafe(self._shutdown_event.set)
                except Exception:
                    pass
            
            if self.server_thread:
                loop = asyncio.get_event_loop()
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, self.server_thread.join, 5.0),
                        timeout=6.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("[miastrbot] WebUI 服务线程退出超时")
                self.server_thread = None
            
            self._thread_loop = None
            self._shutdown_event = None
            
            # 重置单例状态
            Server._instance = None
            self._initialized = False
            
            logger.info("[miastrbot] WebUI 服务已停止")
            
        except Exception as e:
            logger.error(f"[miastrbot] 停止 WebUI 服务失败: {e}", exc_info=True)
    
    def _is_port_available(self, port: int) -> bool:
        """检查端口是否可用"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self.host, port))
                return True
        except Exception:
            return False
    
    async def _kill_port_holder(self, port: int):
        """清理占用端口的进程"""
        try:
            if sys.platform == "win32":
                cmd_find = f"netstat -ano | findstr :{port}"
                process = await asyncio.create_subprocess_shell(
                    cmd_find,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await process.communicate()
                if stdout:
                    lines = stdout.decode("gbk", errors="ignore").strip().split("\n")
                    for line in lines:
                        parts = line.strip().split()
                        if len(parts) > 4 and "LISTENING" in line:
                            pid = parts[-1]
                            if pid and pid != str(os.getpid()):
                                logger.warning(f"[miastrbot] 清理占用进程 PID={pid}")
                                await asyncio.create_subprocess_shell(
                                    f"taskkill /F /PID {pid}",
                                    stdout=asyncio.subprocess.DEVNULL,
                                    stderr=asyncio.subprocess.DEVNULL
                                )
                                await asyncio.sleep(1.0)
            else:
                cmd_find = f"lsof -ti tcp:{port}"
                process = await asyncio.create_subprocess_shell(
                    cmd_find,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await process.communicate()
                if stdout:
                    pids = stdout.decode().strip().split("\n")
                    current_pid = str(os.getpid())
                    for pid in pids:
                        pid = pid.strip()
                        if pid and pid != current_pid:
                            logger.warning(f"[miastrbot] 清理占用进程 PID={pid}")
                            await asyncio.create_subprocess_shell(
                                f"kill -9 {pid}",
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL
                            )
                    await asyncio.sleep(0.5)
        except Exception:
            pass
    
    async def _verify_tcp(self) -> bool:
        """验证服务端口是否已监听"""
        loop = asyncio.get_event_loop()
        
        def check():
            try:
                check_host = "127.0.0.1" if self.host == "0.0.0.0" else self.host
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    return s.connect_ex((check_host, self.port)) == 0
            except Exception:
                return False
        
        return await loop.run_in_executor(None, check)
