# miastrbot 插件开发方案 - 最终版

> 更新时间：2026-04-08
> 插件路径：`/AstrBot/data/plugins/miastrbot/`

---

## 一、项目概述

| 项目 | 内容 |
|------|------|
| 插件名 | `miastrbot` (Mi + AstrBot) |
| 定位 | 小爱音箱 + 米家设备 + AstrBot Agent 集成 |
| 目标 | 语音输入 → AstrBot大脑 → 控制米家设备 |
| 开发路径 | `/AstrBot/data/plugins/miastrbot/` |
| 主题色 | `#19CD90` (米家官方绿) |
| 适配音箱 | L05C (小爱音箱Play增强版) |
| 兼容型号 | LX06 / LX04 / X10A / L05B |

---

## 二、整体架构

```
用户层：QQ/TG/小爱音箱/WebUI
        ↓
AstrBot核心：全局Agent(自带) + 消息路由
        ↓
插件层：AgentHandler | DeviceManager | ConfigCache | WebUI
        ↓
服务层：XiaomiService | MiHomeService | TTSServer
        ↓
硬件层：小爱音箱(L05C等) | 米家设备 | 米家云API
```

---

## 三、核心模块详解

### 3.1 XiaomiService - 小爱服务

| 功能 | 说明 | 适配说明 |
|------|------|----------|
| OAuth登录 | 小米账号授权 | 全型号通用 |
| 设备列表 | 获取绑定的小爱音箱 | 全型号通用 |
| TTS播报 | 文字转语音播放 | edge-tts / openai-tts |
| 命令发送 | 与音箱通信 | 按型号自动选择模式 |
| 事件监听 | 监听音箱状态变化 | 全型号通用 |

**多型号兼容策略**：

| 型号 | 通信模式 | 状态 |
|------|----------|------|
| L05C (Play增强版) | command | ✅ 主测试 |
| LX06 (小爱Pro) | ubus / command | ✅ 官方推荐 |
| LX04 | command | ✅ 已知兼容 |
| X10A | command | ✅ 已知兼容 |
| L05B | command | ✅ 已知兼容 |

**关键代码**：

```python
# xiaomi_service.py
class XiaomiService:
    # 需要使用 command 模式的型号
    COMMAND_ONLY_MODELS = ["L05C", "LX04", "X10A", "L05B"]
    
    def __init__(self, config):
        self.hardware = config.get("hardware", "L05C")
        # L05C 强制使用 command 模式
        self.use_command = self.hardware in self.COMMAND_ONLY_MODELS
    
    async def send_command(self, command):
        if self.use_command:
            # command 模式（L05C等）
            return await self._send_via_command(command)
        else:
            # ubus 模式（LX06等）
            return await self._send_via_ubus(command)
```

### 3.2 MiHomeService - 米家服务（自实现）

| 功能 | 说明 |
|------|------|
| OAuth登录 | 米家账号授权获取Token |
| 设备列表 | 自动获取绑定设备 |
| 设备属性读写 | 开关/亮度/温度等 |
| 设备别名映射 | 自然语言→DID映射 |

### 3.3 AgentHandler - Agent对话

| 功能 | 说明 |
|------|------|
| 音箱专用LLM | 插件内独立配置，与全局隔离 |
| 流畅响应 | 独立开关，避免干扰 |
| 命令解析 | 自然语言→设备+动作 |
| 多轮对话 | 保持上下文 |

**配置项**：

```yaml
speaker:
  model: "gpt-4o-mini"    # 音箱专用模型
  stream: true             # 独立流式开关
```

### 3.4 WebUI - 可视化配置（参考 self_learning 架构）

**设计风格**：
- 主题色：`#19CD90` (米家官方绿)
- 渐变色：`#19CD90` → `#2DE5A8`
- 布局：卡片式设备展示 + 状态指示灯

**架构**（参考 self_learning 单例+守护线程模式）：

```
miastrbot/webui/
├── __init__.py          # 导出
├── server.py            # 单例服务器（守护线程）
├── app.py               # FastAPI 应用工厂
├── config.py            # WebUI 配置
├── dependencies.py     # 依赖注入容器
├── blueprints/          # 路由蓝图
│   ├── __init__.py
│   ├── auth.py          # 登录/登出
│   ├── devices.py       # 设备管理
│   ├── config.py        # 配置管理
│   └── oauth.py         # OAuth 授权
└── services/           # 服务
    └── cache.py         # 缓存服务

miastrbot/web_res/
└── static/             # 静态资源
    ├── css/
    │   └── main.css    # 米家风格 CSS
    ├── js/
    │   └── app.js       # 前端逻辑
    └── index.html       # 主页面
```

**server.py 核心特性**（参考 self_learning）：
- 单例模式防止重复启动
- 守护线程运行 Hypercorn
- SO_REUSEADDR 端口复用
- 自动清理占用进程
- 优雅关闭机制

---

## 四、目录结构

```
miastrbot/
├── metadata.yaml              # 插件元信息
├── DESIGN.md                  # 开发方案文档（本文档）
├── config.yaml.example        # 配置示例
├── requirements.txt          # 依赖清单
│
├── main.py                   # 插件主入口 (Star接口)
├── config_manager.py         # 配置管理 (缓存+热更新)
│
├── services/                 # 服务层
│   ├── __init__.py
│   ├── xiaomi_service.py    # 小爱服务 (多型号兼容)
│   ├── mihome_service.py    # 米家服务
│   └── tts_service.py        # TTS服务
│
├── agent/                    # Agent层
│   ├── __init__.py
│   ├── handler.py            # 命令处理
│   └── prompts.py            # Prompt模板
│
├── webui/                    # WebUI（参考 self_learning）
│   ├── __init__.py
│   ├── server.py             # 单例服务器
│   ├── app.py                # FastAPI 应用
│   ├── config.py             # WebUI 配置
│   ├── dependencies.py       # 依赖注入
│   ├── blueprints/          # 模块化路由
│   │   ├── __init__.py
│   │   ├── auth.py          # 登录/登出
│   │   ├── devices.py       # 设备管理
│   │   ├── config.py        # 配置管理
│   │   └── oauth.py         # OAuth 授权
│   └── services/            # WebUI 服务
│       └── cache.py          # 缓存服务
│
├── web_res/                  # 静态资源
│   └── static/
│       ├── css/
│       │   └── main.css     # 米家风格样式
│       ├── js/
│       │   └── app.js       # 前端逻辑
│       └── index.html       # 主页面
│
└── utils/
    ├── __init__.py
    ├── cache.py              # 配置缓存
    ├── exceptions.py         # 自定义异常
    ├── events.py             # 事件系统
    └── logging.py            # 日志系统
```

---

## 五、配置文件

```yaml
# config.yaml.example
xiaomi:
  account: ""              # 小米账号
  password: ""             # 密码
  device_id: ""            # 小爱音箱 DID
  hardware: "L05C"         # 硬件型号 (L05C/LX06/LX04等)

mihome:
  oauth_token: ""           # 米家 OAuth Token
  # 或使用账号密码登录
  account: ""
  password: ""

speaker:
  model: "gpt-4o-mini"    # 音箱专用模型
  stream: true             # 独立流式开关

tts:
  enabled: true
  type: "edge"            # edge/openai/azure
  voice: "zh-CN-XiaoxiaoNeural"

webui:
  host: "0.0.0.0"
  port: 9528
  password: ""            # 访问密码，留空则无需密码
```

---

## 六、开发步骤

### 阶段一：框架搭建 [预计1-2h]

| 步骤 | 任务 | 产出 |
|------|------|------|
| 1.1 | 创建目录骨架 | 插件骨架 |
| 1.2 | 编写 metadata.yaml | 元信息文件 |
| 1.3 | 编写 config.yaml.example | 配置模板 |
| 1.4 | 编写 config_manager.py | 配置管理模块 |
| 1.5 | 创建服务层骨架 | 服务骨架 |

### 阶段二：小爱服务 [预计3-4h]

| 步骤 | 任务 | 参考 |
|------|------|------|
| 2.1 | OAuth登录 | xiaogpt |
| 2.2 | 设备列表获取 | xiaogpt micli list |
| 2.3 | TTS播报 (edge-tts) | xiaogpt --tts edge |
| 2.4 | 命令发送 (多型号兼容) | xiaogpt --use_command |
| 2.5 | 事件监听 | mi-gpt |

### 阶段三：米家服务 [预计2-3h]

| 步骤 | 任务 |
|------|------|
| 3.1 | OAuth登录 |
| 3.2 | 设备列表API |
| 3.3 | 设备属性读写 |
| 3.4 | 设备别名映射 |

### 阶段四：Agent对话 [预计2-3h]

| 步骤 | 任务 |
|------|------|
| 4.1 | AgentHandler主逻辑 |
| 4.2 | 音箱专用LLM调用 |
| 4.3 | 流畅响应实现 |
| 4.4 | Prompt模板编写 |

### 阶段五：WebUI [预计2-3h]

| 步骤 | 任务 |
|------|------|
| 5.1 | server.py 单例服务器 |
| 5.2 | FastAPI路由 |
| 5.3 | 配置页面HTML |
| 5.4 | 设备同步功能 |
| 5.5 | 别名编辑功能 |

### 阶段六：测试调优 [预计2-3h]

| 步骤 | 任务 |
|------|------|
| 6.1 | L05C适配测试 |
| 6.2 | 米家设备控制测试 |
| 6.3 | 流畅响应测试 |
| 6.4 | 多型号兼容性测试 |

---

## 七、依赖清单

```
# requirements.txt

# 小爱服务
aiohttp>=3.9.0
httpx>=0.25.0

# TTS
edge-tts>=6.1.0

# WebUI
fastapi>=0.104.0
uvicorn>=0.24.0
jinja2>=3.1.0
pydantic>=2.5.0
hypercorn>=0.14.0

# 配置
pyyaml>=6.0
```

---

## 八、参考项目

| 项目 | 地址 | 用途 |
|------|------|------|
| xiaogpt | https://github.com/yihong0618/xiaogpt | 小爱SDK、登录、command模式 |
| mi-gpt | https://github.com/idootop/mi-gpt | 事件系统、架构参考 |
| self_learning | 本地 astrbot_plugin_self_learning | WebUI 单例服务器模式 |
| mihome插件 | 本地 astrbot_plugin_mihome | 米家登录参考 |

---

## 九、调试方式

1. **热重载**：AstrBot WebUI → 插件管理 → 重载插件
2. **日志查看**：AstrBot日志输出
3. **断点调试**：VSCode attach到AstrBot进程

---

> 文档版本：v2.0
> 最后更新：2026-04-08
