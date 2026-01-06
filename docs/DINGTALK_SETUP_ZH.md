# DingTalk (钉钉) 集成指南

本文档介绍如何配置和使用 vibe-remote 的 DingTalk (钉钉) 集成。

## 目录

- [概述](#概述)
- [前提条件](#前提条件)
- [配置步骤](#配置步骤)
- [使用方法](#使用方法)
- [可用命令](#可用命令)
- [Agent 选择](#agent-选择)
- [故障排除](#故障排除)

## 概述

vibe-remote 支持通过 DingTalk (钉钉) 远程控制 AI 编程助手。支持两种 Agent：

- **Claude** - Anthropic 官方 Claude Code SDK
- **Qoder** - 轻量级 CLI 工具，响应更快

## 前提条件

1. DingTalk 企业内部应用
2. Python 3.9+ 环境
3. 已安装 vibe-remote

## 配置步骤

### 1. 创建 DingTalk 应用

1. 登录 [阿里云钉钉开放平台](https://open.dingtalk.com/)
2. 创建企业内部应用
3. 获取以下信息：
   - `AppKey` (也称为 `ClientID`)
   - `AppSecret` (也称为 `ClientSecret`)

### 2. 配置环境变量

编辑 `.env` 文件：

```bash
# 选择钉钉平台
IM_PLATFORM=dingtalk

# DingTalk 应用凭证
DINGTALK_APP_KEY=your_app_key_here
DINGTALK_APP_SECRET=your_app_secret_here

# (可选) 限制接收消息的会话 ID，null 表示接收所有
DINGTALK_TARGET_CONVERSATION=null

# (可选) 是否需要 @mention 才响应（群聊中）
DINGTALK_REQUIRE_MENTION=false
```

### 3. 启动机器人

```bash
./start.sh
```

### 4. 在钉钉中添加机器人

1. 进入你的 DingTalk 应用
2. 找到"应用首页" → "机器人"
3. 添加机器人到需要使用的群聊或单聊

## 使用方法

### 发送消息

直接在钉钉中向机器人发送消息即可开始对话。

### 命令列表

| 命令 | 说明 |
|------|------|
| `/start` | 显示主菜单 |
| `/clear` | 清除对话上下文，开始新会话 |
| `/cwd` | 显示当前工作目录 |
| `/set_cwd <路径>` | 修改工作目录 |
| `/settings` | 打开设置菜单 |

### Agent 选择

默认使用 Claude。如需切换到 Qoder，编辑 `agent_routes.yaml`：

```yaml
default: qoder

dingtalk:
  default: qoder
```

## 两种 Agent 对比

| 特性 | Claude | Qoder |
|------|--------|-------|
| 首次响应时间 | ~30-40 秒 (初始化) | ~5 秒 |
| 后续响应时间 | 快速 | 快速 |
| 功能完整性 | 官方支持，功能完整 | 轻量级，核心功能 |
| 会话恢复 | 支持 | 支持 (非 ASCII 路径有已知问题) |

## 故障排除

### 机器人无响应

1. 检查机器人是否正在运行：
   ```bash
   ./status.sh
   ```

2. 查看日志：
   ```bash
   tail -f logs/bot_*.log
   ```

### 首次消息响应慢

- Claude 首次创建会话需要 ~30-40 秒（初始化和连接）
- 这是正常行为，后续消息会快速响应

### 会话上下文丢失

- 使用 `/clear` 可以清除上下文并开始新会话
- 检查工作目录路径是否包含非 ASCII 字符（中文等）

## 技术架构

DingTalk 使用 Stream 模式 (WebSocket) 进行双向通信：

```
钉钉服务器 ←→ WebSocket ←→ vibe-remote ←→ Agent (Claude/Qoder)
```

- **Stream 模式**：实时双向通信，无需公网 IP
- **共享事件循环**：支持 Claude SDK 的长期运行接收任务
