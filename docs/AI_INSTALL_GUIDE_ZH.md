# Vibe Remote AI 辅助安装指南

本文档包含结构化的安装指令，专为 AI 编码助手（Claude Code、OpenAI Codex 等）设计，用于自动化 vibe-remote 的安装和配置。

**目标**：用户只需对 AI 说"安装这个项目"，即可完成整个安装流程。

---

## AI 指令概要

当用户要求安装 vibe-remote 时，按顺序执行以下自动化步骤：

1. **环境检测与准备**
2. **依赖安装**
3. **配置向导**（需要用户交互）
4. **验证与启动**

---

## 详细 AI 指令

### 第一阶段：环境检测

**需要执行：**
- 检查 Python 版本（要求 3.9+）
- 检查虚拟环境是否存在
- 如不存在则创建虚拟环境
- 检查 Node.js 和 npm（Claude Code CLI 需要）
- 检测操作系统（macOS/Linux/Windows）

**不要执行：**
- 如果 Python < 3.9，不要继续 - 提示用户升级
- 除非明确要求，否则不要使用 sudo

**运行命令：**
```bash
# 检查 Python 版本
python3 --version

# 检查现有虚拟环境
ls -la venv 2>/dev/null || echo "未找到虚拟环境"

# 检查 Node.js
node --version
npm --version

# 检查 Claude Code CLI
claude --version 2>/dev/null || echo "未安装 Claude CLI"
```

**输出格式：**
用清晰的表格报告结果：
```
环境检测结果:
✅ Python 3.11.0
✅ Node.js 20.10.0
✅ npm 10.2.0
❌ Claude Code CLI (未安装)
```

### 第二阶段：依赖安装

**需要执行：**
- 创建并激活虚拟环境
- 从 requirements.txt 安装 Python 依赖
- 如缺失则安装 Claude Code CLI
- 验证所有安装

**运行命令：**

```bash
# 创建虚拟环境（如果不存在）
python3 -m venv venv

# 激活（根据平台）
source venv/bin/activate          # macOS/Linux
# 或
venv\Scripts\activate             # Windows

# 安装 Python 依赖
pip install --upgrade pip
pip install -r requirements.txt

# 如果缺失则安装 Claude Code CLI
if ! command -v claude &> /dev/null; then
    npm install -g @anthropic-ai/claude-code
fi

# 验证安装
python -c "import claude_code_sdk; print('claude-code-sdk 正常')"
python -c "import telegram; print('telegram 正常')"
python -c "import slack_sdk; print('slack_sdk 正常')"
```

**预计耗时：** 2-5 分钟（取决于网络速度）

### 第三阶段：配置 - 需要用户输入

**此阶段无法完全自动化**，用户必须从外部平台获取凭证。

**需要执行：**
- 引导用户选择平台
- 为每个平台提供清晰的分步说明
- 使用用户提供的凭证生成 .env 文件
- 尽可能通过 API 调试验证凭证

**不要执行：**
- 不要跳过凭证验证
- 不要硬编码任何 token 或密钥
- 在没有有效凭证的情况下不要继续

#### 配置决策树

```
询问用户："您想使用哪个 IM 平台？"

├── Slack
│   ├── 指引：在 https://api.slack.com/apps 创建应用
│   ├── 必需：SLACK_BOT_TOKEN (xoxb-...)
│   ├── 必需：SLACK_APP_TOKEN (xapp-...)
│   └── 可选：SLACK_TARGET_CHANNEL, SLACK_REQUIRE_MENTION
│
├── Telegram
│   ├── 指引：通过 @BotFather 创建机器人
│   ├── 必需：TELEGRAM_BOT_TOKEN
│   └── 可选：TELEGRAM_TARGET_CHAT_ID
│
└── 钉钉
    ├── 指引：在 https://open.dingtalk.com/ 创建应用
    ├── 必需：DINGTALK_APP_KEY
    ├── 必需：DINGTALK_APP_SECRET
    └── 可选：DINGTALK_TARGET_CONVERSATION, DINGTALK_REQUIRE_MENTION
```

#### 各平台设置指引

**Slack 设置指引（展示给用户）：**

```markdown
### 需要配置 Slack

请按以下步骤操作：

1. 访问 https://api.slack.com/apps
2. 点击 "Create New App"
3. 添加 Bot Token 权限：`chat:write`、`channels:history`、`groups:history`、`im:history`、`mpim:history`
4. 安装应用到工作区 → 复制 Bot Token（以 `xoxb-` 开头）
5. 在 Basic Information 中启用 Socket Mode
6. 生成 App-Level Token（以 `xapp-` 开头）

请提供：
1. SLACK_BOT_TOKEN: _
2. SLACK_APP_TOKEN: _
```

**Telegram 设置指引（展示给用户）：**

```markdown
### 需要配置 Telegram 机器人

请按以下步骤操作：

1. 在 Telegram 中搜索 @BotFather
2. 发送 /newbot
3. 按提示命名你的机器人
4. 复制 token（格式：123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ）

请提供：
1. TELEGRAM_BOT_TOKEN: _
```

**钉钉设置指引（展示给用户）：**

```markdown
### 需要配置钉钉应用

请按以下步骤操作：

1. 访问 https://open.dingtalk.com/
2. 创建企业内部应用
3. 获取 AppKey 和 AppSecret

请提供：
1. DINGTALK_APP_KEY: _
2. DINGTALK_APP_SECRET: _
```

#### .env 文件生成

收集凭证后，生成 `.env` 文件：

```bash
# .env 文件生成模板
cat > .env << EOF
# IM 平台选择
IM_PLATFORM={{PLATFORM}}

# 平台配置
{{PLATFORM_UPPER}}_TOKEN={{USER_TOKEN}}
{{PLATFORM_UPPER}}_SECRET={{USER_SECRET_IF_APPLICABLE}}

# Claude 配置
CLAUDE_PERMISSION_MODE=bypassPermissions
CLAUDE_DEFAULT_CWD=./_tmp

# 应用配置
LOG_LEVEL=INFO
EOF
```

**变量说明：**
- `{{PLATFORM}}` = slack | telegram | dingtalk
- `{{PLATFORM_UPPER}}` = SLACK | TELEGRAM | DINGTALK
- `{{USER_TOKEN}}` = 用户提供的 token
- `{{USER_SECRET_IF_APPLICABLE}}` = Slack (APP_TOKEN) 或钉钉 (APP_SECRET)

### 第四阶段：验证

**需要执行：**
- 验证 .env 文件存在且格式正确
- 测试 IM 平台连接（可选 API 调用）
- 验证 Claude Code CLI 可以被调用
- 创建工作目录

**验证命令：**

```bash
# 检查 .env 是否存在
test -f .env && echo ".env 存在" || echo ".env 缺失"

# 加载并验证 .env
set -a; source .env; set +a

# 验证必需变量
if [ -z "$IM_PLATFORM" ]; then
    echo "错误: IM_PLATFORM 未设置"
    exit 1
fi

# 验证 Claude CLI
claude --version

# 创建工作目录
mkdir -p ./_tmp
```

### 第五阶段：首次启动

**需要执行：**
- 启动服务
- 验证与 IM 平台的连接
- 提供用户后续步骤说明

**启动命令：**

```bash
# 方式 1：直接启动（用于测试）
python main.py

# 方式 2：守护进程启动（用于生产环境）
chmod +x start.sh
./start.sh

# 方式 3：后台运行
nohup python main.py > logs/bot.log 2>&1 &
```

---

## 用户交互脚本

当用户说"安装 vibe-remote"时，按此对话流程进行：

```
AI: 我来帮您安装 vibe-remote。让我先检查您的环境...

[第一阶段：环境检测]
AI: 环境检测结果：
     ✅ Python 3.11.2
     ✅ Node.js 20.0
     ❌ 未安装 Claude Code CLI

[第二阶段：安装依赖]
AI: 正在安装依赖...
     - 创建虚拟环境
     - 安装 Python 包
     - 通过 npm 安装 Claude Code CLI
     ✅ 所有依赖已安装

[第三阶段：配置]
AI: 您想使用哪个 IM 平台？
     1. Slack（推荐团队使用）
     2. Telegram（设置简单）
     3. 钉钉（企业用户）

用户: [选择 1、2 或 3]

AI: [显示对应平台的设置指引]
    请提供以下凭证：
    1. TOKEN: _

[用户提供凭证]

AI: 正在验证凭证...
    ✅ 凭证有效
    ✅ .env 文件已创建

[第四阶段：验证]
AI: 运行验证检查...
    ✅ 配置有效
    ✅ 工作目录已创建

[第五阶段：启动]
AI: 正在启动 vibe-remote 服务...
    ✅ 服务启动成功

AI: 安装完成！现在您可以：
     - 向 [平台] 上的机器人发送测试消息
     - 使用 /start 查看所有可用命令
     - 使用 /clear 重置对话
```

---

## 错误处理

### Python 版本过低

```
错误: 需要 Python 3.9+，当前版本：3.8.10
解决方案: 安装更新的 Python 版本：
  - macOS: brew install python@3.11
  - Ubuntu: sudo apt install python3.11
  - Windows: 从 python.org 下载
```

### 缺少 Node.js

```
错误: 未找到 Node.js。Claude Code CLI 需要 Node.js。
解决方案: 安装 Node.js：
  - macOS: brew install node
  - Ubuntu: sudo apt install nodejs npm
  - Windows: 从 nodejs.org 下载
```

### 凭证无效

```
错误: [平台] Token 验证失败
解决方案: 请检查：
  1. Token 复制是否正确（无多余空格）
  2. 机器人/应用是否已创建并激活
  3. 是否已授予所需权限
  4. Token 是否未过期或被撤销
```

### 端口被占用

```
错误: 端口 8080 已被占用
解决方案: 停止现有服务：
  - ./stop.sh
  - 或终止进程: lsof -ti:8080 | xargs kill
```

---

## 安装后步骤

成功安装后，告知用户：

```
✅ vibe-remote 现已运行！

下一步：
1. 将机器人邀请到频道/聊天
2. 发送测试消息，如"你好"
3. 使用 /start 查看所有命令

管理命令：
  ./start.sh  - 启动服务
  ./stop.sh   - 停止服务
  ./status.sh - 检查服务状态

日志保存在：logs/bot_*.log
配置文件：.env
设置持久化：user_settings.json
```

---

## 故障排除命令

如用户遇到问题，提供这些命令：

```bash
# 检查服务是否运行
./status.sh

# 实时查看日志
tail -f logs/bot_*.log

# 测试配置
python -c "from config.settings import AppConfig; print('配置正常')"

# 重启服务
./stop.sh && ./start.sh

# 重置所有设置（清除会话和偏好）
rm user_settings.json
./start.sh
```

---

## 高级：完全卸载

如果用户想完全移除 vibe-remote：

```bash
# 停止服务
./stop.sh

# 移除虚拟环境
rm -rf venv

# 移除配置
rm .env
rm user_settings.json

# 移除日志
rm -rf logs/

# 可选：移除 Claude Code CLI
npm uninstall -g @anthropic-ai/claude-code
```

---

## 给 AI 助手的注意事项

1. **继续前始终验证** - 不要假设环境已准备就绪
2. **提供进度反馈** - 用户应该看到正在发生什么
3. **优雅处理错误** - 提供解决方案，而不仅仅是错误信息
4. **尊重用户权限** - 使用 sudo 或修改系统文件前先询问
5. **特定平台的命令** - 根据 macOS/Linux/Windows 调整命令
6. **保留备份** - 不要在未询问的情况下覆盖现有 .env

---

## 版本兼容性

| 组件 | 最低版本 | 推荐版本 |
|------|----------|----------|
| Python | 3.9 | 3.11+ |
| Node.js | 18.x | 20.x LTS |
| npm | 9.x | 10.x |
| Claude Code CLI | 最新 | 最新 |

---

## AI 快速参考

```bash
# 完整安装序列
python3 -m venv venv && \
source venv/bin/activate && \
pip install -r requirements.txt && \
npm install -g @anthropic-ai/claude-code && \
python3 setup.py && \
./start.sh
```

```python
# Python API 安装检查
import sys
import subprocess
from pathlib import Path

def check_installation():
    """验证 vibe-remote 安装"""
    checks = {
        "Python": sys.version_info >= (3, 9),
        "venv": Path("venv").exists(),
        ".env": Path(".env").exists(),
        "Claude CLI": shutil.which("claude") is not None,
    }
    return checks
```

---

## Claude Code CLI 使用示例

用户可以通过以下对话让 Claude Code 执行安装：

```
用户: 帮我安装这个 vibe-remote 项目

Claude: 我来帮您安装 vibe-remote。让我先检查环境...
[执行上述安装流程]
```

或使用 claude CLI:
```bash
cd /path/to/vibe-remote
claude "帮我完整安装这个项目，包括所有依赖"
```

Claude 会：
1. 自动检测环境
2. 安装所有依赖
3. 引导完成配置
4. 启动服务
5. 验证运行状态
