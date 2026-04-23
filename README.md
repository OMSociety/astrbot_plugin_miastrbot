# 小爱Astrbot

[![Version](https://img.shields.io/badge/version-v0.1.0-blue.svg)](https://github.com/OMSociety/astrbot_plugin_miastrbot)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A5v4.0.0-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-AGPL--3.0-orange.svg)](LICENSE)

> 🤖 **AI Generated** — 本插件由 AI 辅助开发

小爱音箱 + 米家设备集成插件。以小爱音箱为语音入口，AstrBot 为大脑，米家设备为执行终端，实现自然语言控制智能家居。

---

## ⚠️ 使用前必读

| 服务 | 认证方式 | 配置项 |
|------|---------|--------|
| 小爱音箱 | Cookie (serviceToken) | `speaker.user_id` + `speaker.service_token` |
| 米家设备 | WebUI 扫码授权 | `mihome` (自动管理) |

---

## 🚀 快速开始

### 1. 小爱音箱配置

#### 获取 Cookie（推荐方式）

```bash
# 安装 miservice_fork
pip install miservice_fork

# 获取 Cookie
export MI_USER="你的小米账号"
export MI_PASS="你的小米密码"
micli cookie
```

复制输出的 `userId`、`serviceToken` 填入配置。

#### 插件配置

```json
{
  "speaker": {
    "user_id": "你的userId",
    "service_token": "你的serviceToken",
    "device_id": "",
    "hardware": "L05C"
  }
}
```

### 2. 米家设备授权

在 WebUI 中扫码授权（访问 `http://127.0.0.1:9527`）。

---

## ✨ 功能总览

### 🎤 小爱音箱能力

| 功能 | 说明 |
|------|------|
| **语音监听** | 轮询小爱音箱状态，接收"请xxx"指令 |
| **TTS 播报** | 将 AI 回答通过小爱音箱播放 |
| **设备控制** | 查询播放状态、停止播放等 |

### 🏠 米家设备控制

| 功能 | 说明 |
|------|------|
| **扫码授权** | WebUI 二维码授权米家账号 |
| **设备发现** | 自动获取账号下所有设备 |
| **别名解析** | 支持中文别名控制设备 |
| **状态查询** | 查询设备当前状态 |

### 🔊 TTS 引擎

| 引擎 | 说明 |
|------|------|
| **Edge TTS** | 免费，推荐使用 |
| **OpenAI TTS** | 需要 API Key |
| **Azure TTS** | 需要语音服务 |
| **火山云 TTS** | 需要 AppID/Token |

---

## 📁 目录结构

```
services/
├── xiaomi_speaker_service.py  # 小爱音箱服务（Cookie 认证）
├── mihome_service.py          # 米家设备服务
└── tts_service.py              # TTS 服务
```

---

## ⚠️ 常见问题

**Q: 小爱音箱登录失败**
> 请确保 Cookie 有效，参考上面的获取步骤。

**Q: 米家扫码失败**
> 确保小米账号开启了"授权登录"权限。

**Q: TTS 无声音**
> 检查 TTS 引擎配置，Edge TTS 需要网络连接。

---

## 🙏 致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — Bot 框架
- [miservice_fork](https://github.com/miaomiaoteam/miservice_fork) — 小爱音箱控制
- [mijiaAPI](https://github.com/yihong0632/python-mijia) — 米家设备控制

---

## 📜 许可证

AGPL-3.0 License

---

**Slandre & Flandre** — [@OMSociety](https://github.com/OMSociety)