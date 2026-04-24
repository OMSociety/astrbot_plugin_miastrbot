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

> ⚠️ **两种方式获取 token：优先使用「方式一（账号密码）」，自动获取有效 token；「方式二（手动 Cookie）」仅在方式一失败时使用。**

#### 方式一：账号密码登录（推荐，自动获取有效 token）

1. 在插件配置中填写 `account`（手机号/邮箱/小米ID）和 `password`（密码）
2. 执行 `/小爱 登录`，插件会自动调用小米 API 登录并获取有效 token
3. 无需手动抓 Cookie，token 过期后重新 `/小爱 登录` 即可

```json
{
  "speaker": {
    "account": "你的小米账号",
    "password": "你的密码",
    "hardware": "L05C"
  }
}
```

#### 方式二：手动 Cookie 登录（备选）

> ⚠️ **Cookie 必须从小爱音箱相关域名获取，不能从 `account.xiaomi.com` 获取！**
>
> 小爱音箱 API（`userprofile.mina.mi.com` / `api2.mina.mi.com`）使用的 `serviceToken` 和账号登录（`account.xiaomi.com`）的 token 是**不同的**！如果抓错域名会持续 401。

**正确抓取步骤：**

1. 浏览器打开 `https://micommand.mina.mi.com/` 或 `https://api.mina.mi.com/`
2. 登录你的小米账号（若需要）
3. 按 **F12** 打开开发者工具 → **Network（网络）** 标签
4. 刷新页面，找到任意一个请求（URL 包含 `mina.mi.com` 或 `mi.com` 的请求）
5. 点击请求 → **Headers** → 找到 **Request Headers** 里的 `Cookie`
6. 复制完整 Cookie 字符串

#### 解析 Cookie

从 Cookie 字符串中提取两个值：

| 字段 | 来源 | 示例 |
|------|------|------|
| **user_id** | Cookie 中 `userId=xxx` | `2758463163` |
| **service_token** | Cookie 中 `serviceToken=xxx` | `V1:xxx...`（很长，以 V1: 开头） |

#### 插件配置

```json
{
  "speaker": {
    "user_id": "2758463163",
    "service_token": "你的serviceToken（以V1:开头）",
    "hardware": "L05C"
  }
}
```

> 💡 **如何区分 userId 和 serviceToken？**
> - userId 为 Cookie 中的 `userId=...`，是纯数字 ID（你这个 2758463163 是正常的）
> - serviceToken 以 `V1:` 开头，很长（100+ 字符）
> - **如果填了却仍然 401，大概率是 Cookie 抓错了域名**
> - **推荐使用方式一（账号密码）自动登录，无需手动抓 Cookie**

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
> 请确保 Cookie 有效，参考上面的获取步骤。Cookie 过期后需重新获取。

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

## 🔴 开发进度与已知问题

> ⚠️ **语音唤醒功能（"小爱同学"触发 AstrBot）因认证问题暂时无法使用**，详见下方说明。

### 已实现功能 ✅

| 功能 | 状态 | 说明 |
|------|------|------|
| 米家设备授权（扫码） | ✅ 正常 | WebUI 扫码即可控制设备 |
| 米家设备控制 | ✅ 正常 | `/小爱 控制 灯 开` 等指令 |
| TTS 播报 | ✅ 正常 | `/小爱 播报 文字` 通过小爱音箱发声 |
| `/小爱 状态` 调试 | ✅ 正常 | 查看连接状态和错误信息 |

### 卡住的功能 ❌

| 功能 | 状态 | 说明 |
|------|------|------|
| 语音唤醒（"小爱同学"触发 AI） | ❌ 卡住 | 需要 micoapi 认证 |

### 问题根因

**小爱音箱 API（`api2.mina.mi.com` / `userprofile.mina.mi.com`）使用 `micoapi` 认证体系，与以下方式不同：**

| 尝试的方式 | 结果 | 原因 |
|---|---|---|
| 账号密码登录（miservice） | ❌ 失败 | 小米返回 `securityStatus=128`，触发设备风控验证，无法自动获取 token |
| 手动 Cookie（account.xiaomi.com） | ❌ 失败 | 拿到的是 passport 体系的 token，不是 micoapi 的 |
| 米家授权 token | ❌ 失败 | 米家使用 miot 协议体系，token 不通用 |
| 本地 miio 协议 | ❌ 失败 | 需要和音箱在同一局域网，服务器无法访问音箱本地端口 |

**根本原因：你的小米账号触发了小米服务器的安全风控（securityStatus=128），服务器拒绝发放 micoapi serviceToken，客户端代码无法绕过此限制。**

### 可行的替代方向（未测试）

| 方案 | 思路 | 前提条件 |
|---|---|---|
| 关闭账号安全验证 | 在 mi.com 安全设置中移除设备验证 | 需要在网页端操作 |
| 更换音箱型号 | 不同型号可能认证策略不同 | 需要更换硬件 |
| 同局域网 miio | 将 AstrBot 部署到音箱同一局域网 | 需要网络改造 |
| 绕过 MINA API | 监听音箱本地 UDP/TCP 端口 | 需要抓包研究 |

---

**Slandre & Flandre** — [@OMSociety](https://github.com/OMSociety)