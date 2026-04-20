# -*- coding: utf-8 -*-
"""
Agent指令处理器 (AgentHandler)

负责：
1. 意图识别（基于 LLM）
2. 设备控制指令解析
3. 天气查询（心知天气 API）
4. 闲聊回复（基于 LLM）
5. TTS 格式化
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
    1. 接收用户输入文本
    2. 用 LLM 识别意图类型
    3. 根据意图调用对应处理函数
    4. 返回 {intent, result, tts_text} 统一格式
    """
    
    def __init__(self, xiaomi_service=None, mihome_service=None, tts_server=None, config: Dict[str, Any] = None, context=None):
        """
        初始化 Agent 处理器
        
        Args:
            xiaomi_service: 小爱服务实例
            mihome_service: 米家服务实例
            tts_server: TTS 服务实例
            config: 配置字典（包含 model, weather_api_key, weather_city）
            context: AstrBot Context，用于调用 LLM
        """
        self.config = config or {}
        self.xiaomi_service = xiaomi_service
        self.mihome_service = mihome_service
        self.tts_server = tts_server
        self.context = context
        
        # LLM 模型
        self.model = self.config.get("model", "gpt-4o-mini")
        
        # 天气配置（与日程插件共用）
        self.weather_api_key = self.config.get("weather_api_key", "")
        self.weather_city = self.config.get("weather_city", "北京")
        
        # 设备列表缓存
        self._devices_cache: List[Dict] = []
        self._devices_cache_time: float = 0
        
        logger.info(f"[miastrbot] Agent处理器初始化，LLM模型: {self.model}")

    async def process(self, text: str) -> Dict[str, Any]:
        """
        处理用户输入（主入口，与 main.py 对齐）
        
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
    
    async def _recognize_intent(self, text: str) -> str:
        """
        用 LLM 识别意图类型
        
        优先用关键词快速判断（节省 LLM 调用），复杂情况走 LLM
        """
        # 关键词快速路径
        if any(kw in text for kw in ["天气", "温度", "下雨", "晴", "下雪", "刮风"]):
            return IntentType.WEATHER_QUERY
        if any(kw in text for kw in ["几点", "时间", "现在", "几点钟", "几点了"]):
            return IntentType.TIME_QUERY
        
        # 设备控制关键词
        control_kws = ["开", "关", "打开", "关闭", "启动", "停止", "调亮", "调暗", "调高", "调低"]
        query_kws = ["多少", "什么", "怎么", "开着吗", "关着吗", "状态", "查询", "看看", "看一下"]
        
        has_control = any(kw in text for kw in control_kws)
        has_query = any(kw in text for kw in query_kws)
        
        if has_control or has_query:
            # 走 LLM 精细判断
            return await self._llm_recognize_intent(text)
        
        # 默认闲聊
        return IntentType.CHAT
    
    async def _llm_recognize_intent(self, text: str) -> str:
        """
        使用 LLM 识别意图
        
        适合关键词难以判断的模糊场景
        """
        try:
            import aiohttp
            
            # 从 mihome_service 获取设备名作为上下文
            devices_context = ""
            if self.mihome_service:
                devices = await self.mihome_service.list_devices()
                if devices:
                    names = [d.get("name", "") for d in devices[:10]]
                    devices_context = "已知设备：" + "、".join(names)
            
            prompt = INTENT_PROMPT.format(
                user_input=text,
                devices_context=devices_context,
            )
            
            if self.context:
                resp = await self.context.llm_generate(prompt=f"你是意图识别器。用户说：{text}\n{devices_context}\n只输出意图类型：DEVICE_CONTROL / DEVICE_QUERY / CHAT / WEATHER_QUERY / TIME_QUERY / UNKNOWN")
                result = (resp.completion_text or resp.text or "").strip().upper()
                for itype in IntentType:
                    if itype.value.upper().replace("_", "") in result.replace("_", ""):
                        return itype
                logger.debug(f"[miastrbot] LLM意图结果: {result}，fallback关键词判断")
            else:
                logger.warning("[miastrbot] 无 context，无法使用 LLM 意图识别")
        
        except Exception as e:
            logger.warning(f"[miastrbot] LLM意图识别失败，使用关键词 fallback: {e}")
            if any(kw in text for kw in ["开", "关", "打开", "启动"]):
                return IntentType.DEVICE_CONTROL
            return IntentType.DEVICE_QUERY
    
    async def _handle_device_control(self, text: str) -> Dict[str, Any]:
        """
        处理设备控制指令
        
        从文本中提取设备名和动作，调用 mihome_service 执行
        """
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
        """
        处理天气查询（心知天气 API）
        
        复用日程插件的天气 API 逻辑
        """
        # 从文本中提取城市名
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
        """
        调用心知天气 API 获取天气
        
        Args:
            city: 城市名
        
        Returns:
            (当前天气描述, 预报描述)
        """
        import aiohttp
        
        current_text = ""
        forecast_text = ""
        
        async with aiohttp.ClientSession() as session:
            # 当前天气
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
            
            # 今日预报
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
        # 常见城市
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
        """
        处理闲聊
        
        目前为简单关键词回复，后续可接入 LLM
        """
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
                return {
                    "intent": IntentType.CHAT,
                    "result": response,
                    "tts_text": response,
                    "success": True,
                }
        
        # 默认回复
        default = "嗯嗯，芙兰听到了~还有什么需要帮忙的吗？"
        return {
            "intent": IntentType.CHAT,
            "result": default,
            "tts_text": default,
            "success": True,
        }
    
    def _parse_control_command(self, text: str) -> tuple:
        """
        解析设备控制命令
        
        Args:
            text: 用户输入
        
        Returns:
            (设备名, 动作, 参数字典)
        """
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
        """
        从文本中提取设备名
        
        优先用 mihome_service 的别名解析，兜底用已知设备名匹配
        """
        if self.mihome_service:
            # 用服务的别名解析
            return self.mihome_service.resolve_alias(text)
        
        return None
    
    def _format_control_result(self, device_name: str, action: str, success: bool) -> str:
        """格式化设备控制结果为 TTS 文本"""
        if success:
            return f"{device_name}已{action}"
        else:
            return f"抱歉，{device_name}控制失败了，请检查设备是否在线"
    
    def _format_query_result(self, device_name: str, status: Dict) -> str:
        """格式化设备查询结果为 TTS 文本"""
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
        """
        通过小爱音箱播放 TTS
        
        Args:
            text: 要播放的文字
        
        Returns:
            是否成功
        """
        if not self.xiaomi_service:
            logger.warning("[miastrbot] 小爱服务未初始化")
            return False
        
        try:
            await self.xiaomi_service.send_tts(text)
            return True
        except Exception as e:
            logger.error(f"[miastrbot] TTS播放失败: {e}")
            return False
