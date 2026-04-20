# 小爱Astrbot

[![Version](https://img.shields.io/badge/version-v0.0.9-blue.svg)](https://github.com/OMSociety/astrbot_plugin_miastrbot)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4.0.0-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-AGPL--3.0-orange.svg)](LICENSE)

> 🤖 **AI Generated** — 本插件全是AI写的

小爱音箱 + 米家设备集成插件。以小爱音箱为语音入口，AstrBot 为大脑，米家设备为执行终端，实现自然语言控制智能家居。

[快速开始](#-快速开始) • [功能总览](#-功能总览) • [架构说明](#-架构说明) • [目录结构](#-目录结构) • [更新日志](#-更新日志)

---

## ⚠️ 使用前必读

- 小爱音箱能力依赖 `miservice_fork`，需在小爱音箱所在的局域网内运行
- 米家控制依赖 `mijiaAPI`，首次使用需在 WebUI 中扫码授权
- 支持的音箱型号：`L05C`、`LX06`、`LX04`、`X10A`、`L05B` 等

---

## 🚀 快速开始

### 安装

1. 下载本仓库放入 `/data/plugins` 目录，或在 AstrBot 插件市场搜索安装
2. 安装依赖：`pip install -r requirements.txt`
3. 在插件配置中填写小爱账号密码、米家授权（WebUI 扫码）
4. 重启 AstrBot

### 快速配置

```json
{
  "xiaomi": {
    "account": "你的小米账号",
    "password": "你的小米密码",
    "device_id": "音箱设备 DID（首次登录后自动发现）"
  },
  "mihome": {
    "data_dir": "米家数据目录（授权后自动生成）"
  },
  "speaker": {
    "command_prefix": ["/小爱", "小爱"],
    "ai_mode": true
  }
}
```

---

## ✨ 功能总览

### 🎤 小爱音箱能力

| 功能 | 说明 |
|------|------|
| **账号登录** | 小米账号登录，自动发现音箱设备 |
| **语音唤醒** | 监听音箱唤醒事件，接收语音指令 |
| **TTS 播报** | 小爱音箱播报文字内容（支持多引擎） |
| **设备控制** | 发送命令控制音箱播放、查询状态等 |

### 🏠 米家设备控制

| 功能 | 说明 |
|------|------|
| **扫码授权** | WebUI 二维码授权米家账号 |
| **设备发现** | 自动获取账号下所有米家设备 |
| **别名解析** | 支持中文别名控制设备，如"打开客厅灯" |
| **状态查询** | 查询设备当前开关状态、温度等 |
| **自然语言** | LLM 理解意图 + 关键词双层意图识别 |

### 🔊 TTS 播报引擎

| 引擎 | 说明 |
|------|------|
| **Edge TTS** | 推荐，Edge 浏览器内核，免费稳定 |
| **OpenAI TTS** | OpenAI TTS API |
| **Azure TTS** | Azure 语音服务 |
| **Native TTS** | 系统原生语音（Windows/macOS/Linux） |
| **火山云 TTS** | 字节跳动火山引擎，需要 AppID/Token |

### 📊 WebUI 管理面板

- 小爱账号登录与设备管理
- 米家扫码授权与设备列表
- TTS 配置与音色选择
- 访问地址：`http://127.0.0.1:9528`

---

## 🏗️ 架构说明

```
astrbot_plugin_miastrbot/
├── main.py              # 插件主入口，生命周期管理
├── config_manager.py    # 配置管理器（内存缓存、热更新、环境变量）
├── _data_manager.py     # 数据持久化管理
├── _login_worker.py     # 登录后台任务
├── services/
│   ├── xiaomi_service.py   # 小爱音箱服务（登录、命令、TTS）
│   ├── mihome_service.py    # 米家设备服务（授权、控制、别名）
│   └── tts_service.py       # TTS 服务（多引擎统一入口）
├── agent/
│   ├── handler.py       # Agent 处理器（意图识别 + 任务分发）
│   └── prompts.py        # LLM 提示词模板
├── webui/
│   ├── server.py         # WebUI 主服务
│   ├── app.py            # FastAPI 应用
│   ├── config.py         # WebUI 配置
│   ├── dependencies.py   # 依赖注入
│   └── blueprints/       # 路由蓝图
│       ├── auth.py      # 授权相关
│       ├── config.py     # 配置管理
│       ├── devices.py    # 设备管理
│       └── oauth.py      # OAuth 登录
└── utils/
    ├── cache.py          # 通用缓存工具
    ├── events.py         # 事件系统（预留）
    ├── exceptions.py     # 自定义异常类
    └── logging.py        # 日志初始化
```

**调用链路：**

```
用户语音 → 小爱音箱事件 
    → AstrBot 接收指令 
    → AgentHandler 意图识别（规则 + LLM）
    → 米家设备控制 / 天气查询 / 闲聊 
    → TTS 播报回应
```

---

## 📁 目录结构

| 路径 | 说明 |
|------|------|
| `services/` | 核心服务层，与外部 API 交互 |
| `agent/` | Agent 层，意图识别与任务分发 |
| `webui/` | Web 管理面板（FastAPI + 蓝图分离） |
| `utils/` | 通用工具，不依赖业务逻辑 |
| `_conf_schema.json` | 配置项 Schema（用于前端生成配置表单） |

---

## ⚠️ 常见问题

**Q: 小爱登录失败 `Login failed`**
> 检查小米账号密码是否正确，确保音箱和服务器在同一局域网。

**Q: 米家扫码后提示授权失败**
> 米家账号可能需要开启「账号安全」中的「授权登录」权限。

**Q: TTS 无声音**
> 确认 TTS 引擎已配置，Edge TTS 需要网络连接；Native TTS 需要系统安装语音包。

---

## 🙏 致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — 优秀的 Bot 框架
- [miservice_fork](https://github.com/miaomiaoteam/miservice_fork) — 小爱音箱控制库
- [mijiaAPI](https://github.com/yihong0632/python-mijia) — 米家设备控制库

---

## 📜 许可证

本项目采用 **AGPL-3.0 License** 开源协议。

---

## 👤 作者

**Slandre & Flandre** — [@OMSociety](https://github.com/OMSociety)
