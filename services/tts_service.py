# -*- coding: utf-8 -*-
"""
TTS服务 (TTSServer)

支持多种TTS引擎: edge-tts, openai-tts, native
参考: https://github.com/yihong0618/xiaogpt
"""

import asyncio
import tempfile
import os
import base64
import json
import uuid
from typing import Optional
from abc import ABC, abstractmethod
from astrbot.api import logger
import aiohttp

# 尝试导入各TTS库
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class TTSServerError(Exception):
    """TTS服务异常"""
    pass


class BaseTTSProvider(ABC):
    """TTS提供者基类"""
    
    def __init__(self, config: dict):
        self.config = config
        self.voice = config.get("voice", "zh-CN-XiaoxiaoNeural")
        self.output_file = config.get("output_file")
    
    @abstractmethod
    async def speak(self, text: str) -> bytes:
        """文字转语音"""
        pass
    
    async def speak_to_file(self, text: str, file_path: str = None) -> str:
        """文字转语音并保存为文件"""
        audio_data = await self.speak(text)
        
        if file_path is None:
            fd, file_path = tempfile.mkstemp(suffix=".mp3")
            os.write(fd, audio_data)
            os.close(fd)
        else:
            with open(file_path, "wb") as f:
                f.write(audio_data)
        
        return file_path


class EdgeTTSProvider(BaseTTSProvider):
    """
    微软Edge TTS提供者（推荐，免费）
    
    支持多种中文语音:
    - zh-CN-XiaoxiaoNeural (晓晓 - 女声)
    - zh-CN-YunxiNeural (云希 - 男声)
    - zh-CN-YunyangNeural (云扬 - 新闻女声)
    - zh-CN-XiaoyiNeural (小艺 - 女声)
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.voice = config.get("voice", "zh-CN-XiaoxiaoNeural")
        self.rate = config.get("rate", "+0%")
        self.pitch = config.get("pitch", "+0Hz")
        self.volume = config.get("volume", "+0%")
    
    async def speak(self, text: str) -> bytes:
        """使用edge-tts进行语音合成"""
        if not EDGE_TTS_AVAILABLE:
            raise TTSServerError("edge-tts 库未安装，请运行: pip install edge-tts")
        
        try:
            communicate = edge_tts.Communicate(
                text,
                self.voice,
                rate=self.rate,
                pitch=self.pitch,
                volume=self.volume
            )
            
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            
            logger.debug(f"[miastrbot] Edge TTS 生成成功，文本长度: {len(text)}")
            return audio_data
            
        except Exception as e:
            logger.error(f"[miastrbot] Edge TTS 合成失败: {e}")
            raise TTSServerError(f"Edge TTS 合成失败: {e}")
    
    @staticmethod
    async def list_voices() -> list:
        """列出所有可用的语音"""
        if not EDGE_TTS_AVAILABLE:
            return []
        
        voices = await edge_tts.list_voices()
        zh_voices = [v for v in voices if v["Locale"].startswith("zh-")]
        return zh_voices


class OpenAITTSProvider(BaseTTSProvider):
    """OpenAI TTS提供者"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
        self.api_base = config.get("openai_api_base", "https://api.openai.com/v1")
        self.model = config.get("model", "tts-1")
        self.voice = config.get("voice", "alloy")
        
        if not OPENAI_AVAILABLE:
            raise TTSServerError("openai 库未安装，请运行: pip install openai")
    
    async def speak(self, text: str) -> bytes:
        """使用OpenAI TTS进行语音合成"""
        if not self.api_key:
            raise TTSServerError("未配置 OpenAI API Key")
        
        try:
            client = OpenAI(api_key=self.api_key, base_url=self.api_base)
            
            response = client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text
            )
            
            audio_data = response.content
            logger.debug(f"[miastrbot] OpenAI TTS 生成成功，文本长度: {len(text)}")
            return audio_data
            
        except Exception as e:
            logger.error(f"[miastrbot] OpenAI TTS 合成失败: {e}")
            raise TTSServerError(f"OpenAI TTS 合成失败: {e}")


class NativeTTSProvider(BaseTTSProvider):
    """
    原生TTS提供者（系统自带）
    
    支持:
    - Windows: SAPI
    - macOS: say命令
    - Linux: espeak
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        self._engine = None
    
    async def speak(self, text: str) -> bytes:
        """使用系统原生TTS"""
        import platform
        
        system = platform.system()
        
        if system == "Windows":
            return await self._speak_windows(text)
        elif system == "Darwin":
            return await self._speak_macos(text)
        elif system == "Linux":
            return await self._speak_linux(text)
        else:
            raise TTSServerError(f"不支持的系统: {system}")
    
    async def _speak_windows(self, text: str) -> bytes:
        """Windows SAPI TTS"""
        try:
            import pyttsx3
            
            if self._engine is None:
                self._engine = pyttsx3.init()
            
            fd, temp_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            
            self._engine.save_to_file(text, temp_path)
            self._engine.runAndWait()
            
            with open(temp_path, "rb") as f:
                audio_data = f.read()
            
            os.unlink(temp_path)
            return audio_data
            
        except ImportError:
            raise TTSServerError("pyttsx3 库未安装，请运行: pip install pyttsx3")
        except Exception as e:
            raise TTSServerError(f"Windows TTS 失败: {e}")
    
    async def _speak_macos(self, text: str) -> bytes:
        """macOS say命令"""
        import subprocess
        
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".aiff")
            os.close(fd)
            
            subprocess.run(["say", "-o", temp_path, text], check=True)
            
            with open(temp_path, "rb") as f:
                audio_data = f.read()
            
            os.unlink(temp_path)
            return audio_data
            
        except Exception as e:
            raise TTSServerError(f"macOS TTS 失败: {e}")
    
    async def _speak_linux(self, text: str) -> bytes:
        """Linux espeak TTS"""
        try:
            import subprocess
            
            fd, temp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            
            subprocess.run(
                ["espeak", "-w", temp_path, text],
                check=True,
                capture_output=True
            )
            
            with open(temp_path, "rb") as f:
                audio_data = f.read()
            
            os.unlink(temp_path)
            return audio_data
            
        except Exception as e:
            raise TTSServerError(f"Linux TTS 失败: {e}")


class VolcengineTTSProvider(BaseTTSProvider):
    """火山引擎 TTS 提供者"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.appid = config.get("volcengine_appid", "") or os.getenv("VOLCENGINE_APPID", "")
        self.access_token = config.get("volcengine_access_token", "") or os.getenv("VOLCENGINE_ACCESS_TOKEN", "")
        self.voice_type = config.get("volcengine_voice_type", "") or os.getenv("VOLCENGINE_VOICE_TYPE", "")
        self.sample_rate = max(8000, self._safe_int(config.get("volcengine_sample_rate"), 24000))
        self.speed_ratio = self._clamp(self._safe_int(config.get("volcengine_speed_ratio"), 0), -50, 100)
        self.loudness_rate = self._clamp(self._safe_int(config.get("volcengine_loudness_rate"), 0), -50, 100)
        self.resource_id = config.get("volcengine_resource_id", "seed-icl-2.0")

    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: int, min_value: int, max_value: int) -> int:
        return max(min_value, min(max_value, value))

    async def speak(self, text: str) -> bytes:
        if not self.appid or not self.access_token or not self.voice_type:
            raise TTSServerError("火山云 TTS 配置不完整（volcengine_appid/access_token/voice_type）")

        headers = {
            "X-Api-App-Id": self.appid,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }
        payload = {
            "user": {"uid": str(uuid.uuid4())},
            "req_params": {
                "text": text,
                "speaker": self.voice_type,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": self.sample_rate,
                    "enable_timestamp": True,
                    "speech_rate": self.speed_ratio,
                    "loudness_rate": self.loudness_rate,
                },
                "additions": json.dumps(
                    {
                        "explicit_language": "zh-cn",
                        "disable_markdown_filter": True,
                        "enable_latex_tn": True,
                    },
                    ensure_ascii=False,
                ),
            },
        }

        url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
        audio_data = bytearray()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        detail = await response.text()
                        raise TTSServerError(f"火山云 TTS 请求失败: HTTP {response.status} - {detail[:300]}")

                    buffer = ""
                    stream_done = False
                    async for chunk in response.content.iter_any():
                        if not chunk:
                            continue
                        buffer += chunk.decode("utf-8", errors="ignore")
                        lines = buffer.splitlines(keepends=True)
                        if lines and not lines[-1].endswith(("\n", "\r")):
                            buffer = lines.pop()
                        else:
                            buffer = ""

                        for line in lines:
                            line_str = line.strip()
                            if not line_str.startswith("data:"):
                                continue
                            data_str = line_str[len("data:"):].strip()
                            if not data_str:
                                continue
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            if data.get("code") == 0 and data.get("data"):
                                try:
                                    audio_data.extend(base64.b64decode(data["data"]))
                                except Exception:
                                    pass
                            elif data.get("code") == 20000000:
                                stream_done = True
                                break
                        if stream_done:
                            break

            if not audio_data:
                raise TTSServerError("火山云 TTS 未返回音频数据")
            logger.debug(f"[miastrbot] 火山云 TTS 生成成功，文本长度: {len(text)}")
            return bytes(audio_data)
        except TTSServerError:
            raise
        except Exception as e:
            logger.error(f"[miastrbot] 火山云 TTS 合成失败: {e}")
            raise TTSServerError(f"火山云 TTS 合成失败: {e}")


class TTSServer:
    """
    TTS服务统一入口
    
    支持多种引擎自动切换
    """
    
    PROVIDERS = {
        "edge": EdgeTTSProvider,
        "openai": OpenAITTSProvider,
        "native": NativeTTSProvider,
        "volcengine": VolcengineTTSProvider,
    }
    
    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", True)
        self.tts_type = config.get("engine") or config.get("type", "edge")
        
        provider_class = self.PROVIDERS.get(self.tts_type)
        if provider_class:
            try:
                self.provider = provider_class(config)
                logger.info(f"[miastrbot] TTS服务初始化完成，类型: {self.tts_type}, 语音: {self.provider.voice}")
            except TTSServerError as e:
                logger.warning(f"[miastrbot] TTS提供者初始化失败: {e}")
                if self.tts_type != "edge" and EDGE_TTS_AVAILABLE:
                    logger.info("[miastrbot] 回退到 Edge TTS")
                    self.tts_type = "edge"
                    self.provider = EdgeTTSProvider(config)
                else:
                    raise
        else:
            raise TTSServerError(f"未知的TTS类型: {self.tts_type}，可用: {list(self.PROVIDERS.keys())}")
    
    async def speak(self, text: str) -> bytes:
        """文字转语音"""
        if not self.enabled:
            logger.warning("[miastrbot] TTS未启用")
            return b""
        
        return await self.provider.speak(text)
    
    async def speak_to_file(self, text: str, file_path: str = None) -> str:
        """文字转语音并保存为文件"""
        return await self.provider.speak_to_file(text, file_path)
    
    @staticmethod
    async def list_available_voices() -> list:
        """列出所有可用的Edge TTS语音"""
        return await EdgeTTSProvider.list_voices()
