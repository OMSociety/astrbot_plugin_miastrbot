# -*- coding: utf-8 -*-
"""
Agent指令处理器 (AgentHandler)

负责：
1. 唤醒词检测
2. 意图识别（关键词）
3. 设备控制指令解析
4. 天气查询（心知天气 API）
5. LLM 对话（唤醒词触发）
"""

import json
import re
import asyncio
from typing import Dict, Any, Optional, List

from astrbot.api import logger

from .prompts import (
    SYSTEM_PROMPT,
    INTENT_PROMPT,
    DEVICE_CONTROL_PROMPT,
    CHAT_PROMPT,
)


class IntentType:
    """意图类型枚举"""
    WAKE_WORD = "wake_word"  # 唤醒词触发，进入 LLM 对话
    DEVICE_CONTROL = "device_control"
    DEVICE_QUERY = "device_query"
    WEATHER_QUERY = "weather_query"
    TIME_QUERY = "time_query"
    CHAT = "chat"
    UNKNOWN = "unknown"


class AgentHandler:
    """
    Agent 指令处理器
    
    处理流程：
    1. 检查唤醒词（如「芙兰」「小爱同学」）
    2. 如果是唤醒词 → 调用 LLM 对话
    3. 否则进行意图识别 → 设备控制/天气/时间/闲聊
    4. 返回 {intent, result, tts_text} 统一格式
    """
    
    def __init__(self, speaker_service=None, mihome_service=None, tts_server=None, config: Dict[str, Any] = None, context=None):
        """
        初始化 Agent 处理器
        """
        self.config = config or {}
        self.speaker_service = speaker_service
        self.mihome_service = mihome_service
        self.tts_server = tts_server
        self.context = context
        
        # LLM 模型
        self.model = self.config.get("model", "gpt-4o-mini")
        
        # 唤醒词配置（逗号分隔）
        wake_words_str = self.config.get("wake_words", "芙兰,小爱同学")
        self.wake_words = [w.strip() for w in wake_words_str.split(",") if w.strip()]
        
        # 天气配置
        self.weather_api_key = self.config.get("weather_api_key", "")
        self.weather_city = self.config.get("weather_city", "北京")
        
        # 设备列表缓存
        self._devices_cache: List[Dict] = []
        self._devices_cache_time: float = 0
        
        logger.info(f"[miastrbot] Agent处理器初始化，唤醒词: {self.wake_words}，LLM模型: {self.model}")

    def _check_wake_word(self, text: str) -> Optional[str]:
        """
        检查是否包含唤醒词
        
        Args:
            text: 用户输入文本
        
        Returns:
            唤醒词内容（如"芙兰，今天天气怎么样"中的"，今天天气怎么样"）
            如果没有唤醒词返回 None
        """
        text = text.strip()
        for wake_word in self.wake_words:
            if text.startswith(wake_word):
                # 去除唤醒词，保留后续内容
                content = text[len(wake_word):].strip()
                # 如果唤醒词后面还有内容
                if content:
                    return content
                else:
                    # 只有唤醒词，没有后续内容
                    return ""
        return None
    
    async def process(self, text: str) -> Dict[str, Any]:
        """
        处理用户输入（主入口）
        
        Args:
            text: 用户输入文本
        
        Returns:
            处理结果字典：
            {
                "intent": 意图类型,
                "result": 处理结果,
                "tts_text": 语音播报文本,
                "success": 是否成功
            }
        """
        if not text or not text.strip():
            return self._unknown_result("没有听到内容呢，请再说一次")
        
        text = text.strip()
        logger.info(f"[miastrbot] Agent处理输入: {text}")
        
        try:
            # 1. 先检查唤醒词
            wake_content = self._check_wake_word(text)
            if wake_content is not None:
                return await self._handle_wake_word(wake_content)
            
            # 2. 否则进行意图识别
            intent = await self._recognize_intent(text)
            logger.debug(f"[miastrbot] 识别意图: {intent}")
            
            if intent == IntentType.DEVICE_CONTROL:
                return await self._handle_device_control(text)
            elif intent == IntentType.DEVICE_QUERY:
                return await self._handle_device_query(text)
            elif intent == IntentType.WEATHER_QUERY:
                return await self._handle_weather_query(text)
            elif intent == IntentType.TIME_QUERY:
                return await self._handle_time_query(text)
            elif intent == IntentType.CHAT:
                return await self._handle_chat(text)
            else:
                return await self._handle_chat(text)
        
        except Exception as e:
            logger.error(f"[miastrbot] Agent处理异常: {e}")
            return self._unknown_result(f"处理失败：{str(e)}")
    
    async def _handle_wake_word(self, content: str) -> Dict[str, Any]:
        """
        处理唤醒词触发的 LLM 对话
        
        Args:
            content: 唤醒词后面的内容（为空时表示只说了唤醒词）
        
        Returns:
            处理结果
        """
        if not content:
            # 只说了唤醒词，没有后续内容
            return {
                "intent": IntentType.WAKE_WORD,
                "result": None,
                "tts_text": "我在呢，有什么需要帮忙的吗？",
                "success": True,
            }
        
        # 调用 LLM 进行对话
        try:
            response_text = await self._call_llm_chat(content)
            return {
                "intent": IntentType.WAKE_WORD,
                "result": response_text,
                "tts_text": response_text,
                "success": True,
            }
        except Exception as e:
            logger.error(f"[miastrbot] LLM对话失败: {e}")
            return {
                "intent": IntentType.WAKE_WORD,
                "result": None,
                "tts_text": "抱歉，思考出了问题，请稍后重试",
                "success": False,
            }
    
    async def _call_llm_chat(self, user_input: str) -> str:
        """
        调用 LLM 进行对话
        
        Args:
            user_input: 用户输入
        
        Returns:
            LLM 回复文本
        """
        if not self.context:
            # 没有 context，返回默认回复
            return self._get_simple_chat_response(user_input)
        
        # 构建 prompt
        prompt = f"""你是一个智能助手，用户通过语音与你对话。请用简洁、自然的语言回答。

用户说：{user_input}

请直接回答，不需要加"用户说"之类的前缀。"""
        
        try:
            resp = await self.context.llm_generate(prompt=prompt)
            text = resp.completion_text or resp.text or ""
            return text.strip()
        except Exception as e:
            logger.error(f"[miastrbot] LLM 调用失败: {e}")
            return self._get_simple_chat_response(user_input)
    
    def _get_simple_chat_response(self, text: str) -> str:
        """简单的关键词回复（无 LLM 时使用）"""
        simple_responses = {
            "你好": "你好呀~有什么需要帮忙的吗？",
            "在吗": "我在呢，随时为你服务~",
            "在不在": "在的！有什么需要？",
            "晚安": "晚安，做个好梦~明天见！",
            "早上好": "早上好！新的一天要元气满满哦~",
            "中午好": "中午好！记得吃午饭哦~",
            "谢谢": "不客气~有问题随时找我！",
            "辛苦了": "不辛苦，为你服务很开心~",
        }
        
        for keyword, response in simple_responses.items():
            if keyword in text:
                return response
        
        return "嗯嗯，芙兰听到了~还有什么需要帮忙的吗？"
    
    async def _recognize_intent(self, text: str) -> str:
        """用关键词识别意图类型"""
        # 天气关键词
        if any(kw in text for kw in ["天气", "温度", "下雨", "晴", "下雪", "刮风"]):
            return IntentType.WEATHER_QUERY
        # 时间关键词
        if any(kw in text for kw in ["几点", "时间", "现在", "几点钟", "几点了"]):
            return IntentType.TIME_QUERY
        
        # 设备控制关键词
        control_kws = ["开", "关", "打开", "关闭", "启动", "停止", "调亮", "调暗", "调高", "调低"]
        query_kws = ["多少", "什么", "怎么", "开着吗", "关着吗", "状态", "查询", "看看", "看一下"]
        
        has_control = any(kw in text for kw in control_kws)
        has_query = any(kw in text for kw in query_kws)
        
        if has_control:
            return IntentType.DEVICE_CONTROL
        if has_query:
            return IntentType.DEVICE_QUERY
        
        # 默认闲聊
        return IntentType.CHAT
    
    async def _handle_device_control(self, text: str) -> Dict[str, Any]:
        """处理设备控制指令"""
        device_name, action, params = self._parse_control_command(text)
        
        if not device_name:
            return {
                "intent": IntentType.DEVICE_CONTROL,
                "result": None,
                "tts_text": "没有听清要控制哪个设备呢，请再说一次",
                "success": False,
            }
        
        if not self.mihome_service:
            return {
                "intent": IntentType.DEVICE_CONTROL,
                "result": None,
                "tts_text": "米家服务未连接，无法控制设备",
                "success": False,
            }
        
        try:
            result = await self.mihome_service.control_device(device_name, action, params)
            return {
                "intent": IntentType.DEVICE_CONTROL,
                "result": result,
                "tts_text": self._format_control_result(device_name, action, result.get("success")),
                "success": result.get("success", False),
            }
        except Exception as e:
            logger.error(f"[miastrbot] 设备控制异常: {e}")
            return {
                "intent": IntentType.DEVICE_CONTROL,
                "result": None,
                "tts_text": f"抱歉，{device_name}控制失败了",
                "success": False,
            }
    
    async def _handle_device_query(self, text: str) -> Dict[str, Any]:
        """处理设备状态查询"""
        device_name = self._parse_device_name(text)
        
        if not device_name:
            return {
                "intent": IntentType.DEVICE_QUERY,
                "result": None,
                "tts_text": "没有听清要查询哪个设备呢",
                "success": False,
            }
        
        if not self.mihome_service:
            return {
                "intent": IntentType.DEVICE_QUERY,
                "result": None,
                "tts_text": "米家服务未连接",
                "success": False,
            }
        
        try:
            status = await self.mihome_service.get_device_status(device_name)
            return {
                "intent": IntentType.DEVICE_QUERY,
                "result": status,
                "tts_text": self._format_query_result(device_name, status),
                "success": status.get("online", False),
            }
        except Exception as e:
            logger.error(f"[miastrbot] 设备查询异常: {e}")
            return {
                "intent": IntentType.DEVICE_QUERY,
                "result": None,
                "tts_text": f"抱歉，查询{device_name}失败了",
                "success": False,
            }
    
    async def _handle_weather_query(self, text: str) -> Dict[str, Any]:
        """处理天气查询"""
        city = self._extract_city_from_text(text) or self.weather_city
        
        if not self.weather_api_key:
            return {
                "intent": IntentType.WEATHER_QUERY,
                "result": None,
                "tts_text": "未配置天气API，无法查询天气",
                "success": False,
            }
        
        try:
            current, forecast = await self._fetch_weather(city)
            return {
                "intent": IntentType.WEATHER_QUERY,
                "result": {"current": current, "forecast": forecast, "city": city},
                "tts_text": f"{city}现在{current}，{forecast}" if forecast else f"{city}现在{current}",
                "success": True,
            }
        except Exception as e:
            logger.error(f"[miastrbot] 天气查询异常: {e}")
            return {
                "intent": IntentType.WEATHER_QUERY,
                "result": None,
                "tts_text": f"抱歉，查询{city}天气失败了",
                "success": False,
            }
    
    async def _fetch_weather(self, city: str) -> tuple:
        """调用心知天气 API 获取天气"""
        import aiohttp
        
        current_text = ""
        forecast_text = ""
        
        async with aiohttp.ClientSession() as session:
            now_url = "https://api.seniverse.com/v3/weather/now.json"
            params = {
                "key": self.weather_api_key,
                "location": city,
                "language": "zh-Hans",
                "unit": "c",
            }
            async with session.get(now_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        now = results[0].get("now", {})
                        current_text = f"{now.get('text', '未知')}, {now.get('temperature', '?')}度"
            
            daily_url = "https://api.seniverse.com/v3/weather/daily.json"
            async with session.get(daily_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        daily = results[0].get("daily", [])
                        if daily:
                            today = daily[0]
                            high = today.get("high", "?")
                            low = today.get("low", "?")
                            rain = today.get("precip", "0")
                            forecast_text = f"今天{low}~{high}度，降水概率{rain}%"
        
        return current_text, forecast_text
    
    def _extract_city_from_text(self, text: str) -> Optional[str]:
        """从文本中提取城市名"""
        cities = [
            "北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都",
            "重庆", "西安", "苏州", "天津", "长沙", "郑州", "青岛", "济南",
            "大连", "沈阳", "哈尔滨", "长春", "昆明", "福州", "厦门", "合肥",
        ]
        for city in cities:
            if city in text:
                return city
        return None
    
    async def _handle_time_query(self, text: str) -> Dict[str, Any]:
        """处理时间查询"""
        from datetime import datetime
        now = datetime.now()
        
        hour = now.hour
        minute = now.minute
        time_str = f"{hour}点{minute}分" if minute != 0 else f"{hour}点"
        date_str = now.strftime("%m月%d日")
        weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_map[now.weekday()]
        
        return {
            "intent": IntentType.TIME_QUERY,
            "result": {"time": time_str, "date": date_str, "weekday": weekday},
            "tts_text": f"现在是{date_str}{weekday}，{time_str}",
            "success": True,
        }
    
    async def _handle_chat(self, text: str) -> Dict[str, Any]:
        """处理闲聊"""
        response = self._get_simple_chat_response(text)
        return {
            "intent": IntentType.CHAT,
            "result": response,
            "tts_text": response,
            "success": True,
        }
    
    def _parse_control_command(self, text: str) -> tuple:
        """解析设备控制命令"""
        action = None
        if any(kw in text for kw in ["开", "打开", "启动"]):
            action = "开"
        elif any(kw in text for kw in ["关", "关闭", "停止"]):
            action = "关"
        elif any(kw in text for kw in ["调亮", "调高", "加"]):
            action = "调亮"
        elif any(kw in text for kw in ["调暗", "调低", "减"]):
            action = "调暗"
        
        device_name = self._parse_device_name(text)
        
        params = {}
        brightness = re.search(r"(\d+)%", text)
        if brightness:
            params["brightness"] = int(brightness.group(1))
        temperature = re.search(r"(\d+)度", text)
        if temperature:
            params["temperature"] = int(temperature.group(1))
        
        return device_name, action, params
    
    def _parse_device_name(self, text: str) -> Optional[str]:
        """从文本中提取设备名"""
        if self.mihome_service:
            return self.mihome_service.resolve_alias(text)
        return None
    
    def _format_control_result(self, device_name: str, action: str, success: bool) -> str:
        """格式化设备控制结果"""
        if success:
            return f"{device_name}已{action}"
        else:
            return f"抱歉，{device_name}控制失败了，请检查设备是否在线"
    
    def _format_query_result(self, device_name: str, status: Dict) -> str:
        """格式化设备查询结果"""
        if not status.get("online", False):
            return f"{device_name}目前不在线"
        
        props = status.get("properties", {})
        power = props.get("power", "")
        
        if power == "on":
            return f"{device_name}已开启"
        elif power == "off":
            return f"{device_name}已关闭"
        else:
            return f"{device_name}状态未知"
    
    def _unknown_result(self, tts_text: str) -> Dict[str, Any]:
        """构造通用失败结果"""
        return {
            "intent": IntentType.UNKNOWN,
            "result": None,
            "tts_text": tts_text,
            "success": False,
        }
    
    async def speak_tts(self, text: str) -> bool:
        """通过小爱音箱播放 TTS"""
        if not self.speaker_service:
            logger.warning("[miastrbot] 小爱音箱服务未初始化")
            return False
        
        try:
            await self.speaker_service.speak(text)
            return True
        except Exception as e:
            logger.error(f"[miastrbot] TTS播放失败: {e}")
            return False
