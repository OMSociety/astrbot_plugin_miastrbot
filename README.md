# 小爱Astrbot

AstrBot 小爱音箱 + 米家设备集成插件。  
将小爱音箱作为语音入口，通过 AstrBot 对话能力联动米家设备控制与播报。

## 功能概览

- 小米账号登录与小爱音箱设备发现
- 米家账号二维码授权与设备管理
- 设备别名解析与自然语言控制
- TTS 播报（edge/openai/native/volcengine，azure 预留）
- WebUI 管理面板（配置、登录、设备查看）

## 目录结构

```text
astrbot_plugin_miastrbot/
├── main.py
├── metadata.yaml
├── config.yaml.example
├── requirements.txt
├── services/
├── agent/
├── webui/
├── web_res/
└── utils/
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置

复制 `config.yaml.example` 并按需填写：

- `xiaomi`：小爱音箱账号、密码、设备 DID、硬件型号
- `mihome`：米家登录状态与数据目录（账号授权在 WebUI 扫码完成）
- `speaker`：对话模式、模型与命令前缀
- `weather`：天气查询 API key 与默认城市
- `tts`：TTS 引擎、音色、语速（支持火山云 AppID/Token/音色 ID）
- `webui`：WebUI 开关、监听地址、端口、访问密码、端口冲突处理

## 使用说明

1. 在 AstrBot 插件目录安装本插件。
2. 配置插件参数并重载插件。
3. 访问 WebUI（默认 `http://127.0.0.1:9528`）进行登录与设备管理。
4. 在聊天中使用命令前缀（默认 `/小爱,`）触发设备控制。

## 兼容与注意事项

- 小爱音箱常见型号：`L05C`、`LX06`、`LX04`、`X10A`、`L05B`
- 米家控制依赖 `mijiaAPI`
- 小爱能力依赖 `miservice_fork`

## 元信息

- 插件名：`astrbot_plugin_miastrbot`
- 显示名：`小爱Astrbot`
- AstrBot 版本要求：`>=4.0.0`
- 作者：`Slandre & Flandre`
