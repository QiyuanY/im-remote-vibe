# Vibe Remote AI-Assisted Installation Guide

This document contains structured instructions for AI coding assistants (Claude Code, OpenAI Codex, etc.) to automate the installation and setup of vibe-remote.

**Purpose**: Enable users to install vibe-remote by simply saying "install this project" to an AI coding assistant.

---

## AI Instruction Summary

When a user asks to install vibe-remote, execute the following automated steps in order:

1. **Environment Detection & Setup**
2. **Dependency Installation**
3. **Configuration Guide** (user interaction required)
4. **Validation & Start**

---

## Detailed AI Instructions

### Phase 1: Environment Detection

**DO:**
- Check Python version (require 3.9+)
- Check if virtual environment exists
- Create virtual environment if missing
- Check for Node.js and npm (required for Claude Code CLI)
- Detect operating system (macOS/Linux/Windows)

**DON'T:**
- Don't proceed if Python < 3.9 - inform user to upgrade
- Don't use sudo unless explicitly requested

**Commands to run:**
```bash
# Check Python version
python3 --version

# Check for existing venv
ls -la venv 2>/dev/null || echo "No venv found"

# Check Node.js
node --version
npm --version

# Check Claude Code CLI
claude --version 2>/dev/null || echo "Claude CLI not found"
```

**Output format:**
Report findings in a clean table:
```
Environment Check:
✅ Python 3.11.0
✅ Node.js 20.10.0
✅ npm 10.2.0
❌ Claude Code CLI (not installed)
```

### Phase 2: Dependency Installation

**DO:**
- Create and activate virtual environment
- Install Python dependencies from requirements.txt
- Install Claude Code CLI if missing
- Verify all installations

**Commands to run:**

```bash
# Create virtual environment (if not exists)
python3 -m venv venv

# Activate (platform-specific)
source venv/bin/activate          # macOS/Linux
# OR
venv\Scripts\activate             # Windows

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Claude Code CLI if missing
if ! command -v claude &> /dev/null; then
    npm install -g @anthropic-ai/claude-code
fi

# Verify installations
python -c "import claude_code_sdk; print('claude-code-sdk OK')"
python -c "import telegram; print('telegram OK')"
python -c "import slack_sdk; print('slack_sdk OK')"
```

**Expected runtime:** 2-5 minutes depending on network

### Phase 3: Configuration - CRITICAL USER INPUT REQUIRED

**This phase CANNOT be fully automated.** The user MUST obtain credentials from external platforms.

**DO:**
- Guide user through platform selection
- Provide clear, step-by-step instructions for each platform
- Generate .env file with user-provided credentials
- Validate credentials via API calls where possible

**DON'T:**
- Don't skip credential validation
- Don't hardcode any tokens or secrets
- Don't proceed without valid credentials

#### Configuration Decision Tree

```
Ask user: "Which IM platform do you want to use?"

├── Slack
│   ├── Guide: Create Slack App at https://api.slack.com/apps
│   ├── Required: SLACK_BOT_TOKEN (xoxb-...)
│   ├── Required: SLACK_APP_TOKEN (xapp-...)
│   └── Optional: SLACK_TARGET_CHANNEL, SLACK_REQUIRE_MENTION
│
├── Telegram
│   ├── Guide: Create bot via @BotFather
│   ├── Required: TELEGRAM_BOT_TOKEN
│   └── Optional: TELEGRAM_TARGET_CHAT_ID
│
└── DingTalk (钉钉)
    ├── Guide: Create app at https://open.dingtalk.com/
    ├── Required: DINGTALK_APP_KEY
    ├── Required: DINGTALK_APP_SECRET
    └── Optional: DINGTALK_TARGET_CONVERSATION, DINGTALK_REQUIRE_MENTION
```

#### Platform-Specific Setup Instructions

**Slack Setup Instructions to Display:**

```markdown
### Slack Setup Required

Please follow these steps:

1. Visit https://api.slack.com/apps
2. Click "Create New App"
3. Add Bot Token Scopes: `chat:write`, `channels:history`, `groups:history`,
   `im:history`, `mpim:history`
4. Install app to workspace → copy Bot Token (starts with `xoxb-`)
5. Enable Socket Mode in Basic Information
6. Generate App-Level Token (starts with `xapp-`)

Please provide:
1. SLACK_BOT_TOKEN: _
2. SLACK_APP_TOKEN: _
```

**Telegram Setup Instructions to Display:**

```markdown
### Telegram Bot Setup Required

Please follow these steps:

1. Open Telegram and search for @BotFather
2. Send /newbot
3. Follow prompts to name your bot
4. Copy the token (format: 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ)

Please provide:
1. TELEGRAM_BOT_TOKEN: _
```

**DingTalk Setup Instructions to Display:**

```markdown
### 钉钉应用设置

请按以下步骤操作:

1. 访问 https://open.dingtalk.com/
2. 创建企业内部应用
3. 获取 AppKey 和 AppSecret

请提供:
1. DINGTALK_APP_KEY: _
2. DINGTALK_APP_SECRET: _
```

#### .env File Generation

After collecting credentials, generate `.env` file:

```bash
# Template for .env generation
cat > .env << EOF
# IM Platform Selection
IM_PLATFORM={{PLATFORM}}

# Platform Configuration
{{PLATFORM_UPPER}}_TOKEN={{USER_TOKEN}}
{{PLATFORM_UPPER}}_SECRET={{USER_SECRET_IF_APPLICABLE}}

# Claude Configuration
CLAUDE_PERMISSION_MODE=bypassPermissions
CLAUDE_DEFAULT_CWD=./_tmp

# Application
LOG_LEVEL=INFO
EOF
```

**Variables:**
- `{{PLATFORM}}` = slack | telegram | dingtalk
- `{{PLATFORM_UPPER}}` = SLACK | TELEGRAM | DINGTALK
- `{{USER_TOKEN}}` = user-provided token
- `{{USER_SECRET_IF_APPLICABLE}}` = for Slack (APP_TOKEN) or DingTalk (APP_SECRET)

### Phase 4: Validation

**DO:**
- Validate .env file exists and is properly formatted
- Test IM platform connection (optional API call)
- Verify Claude Code CLI can be invoked
- Create working directory if specified

**Validation Commands:**

```bash
# Check .env exists
test -f .env && echo ".env exists" || echo ".env missing"

# Load and validate .env
set -a; source .env; set +a

# Verify required variables
if [ -z "$IM_PLATFORM" ]; then
    echo "ERROR: IM_PLATFORM not set"
    exit 1
fi

# Verify Claude CLI
claude --version

# Create working directory
mkdir -p ./_tmp
```

### Phase 5: First Start

**DO:**
- Start the service
- Verify connection to IM platform
- Provide user with next steps

**Start Commands:**

```bash
# Option 1: Direct start (for testing)
python main.py

# Option 2: Daemon start (for production)
chmod +x start.sh
./start.sh

# Option 3: Background with nohup
nohup python main.py > logs/bot.log 2>&1 &
```

---

## User Interaction Script

When user says "install vibe-remote", follow this conversation flow:

```
AI: I'll help you install vibe-remote. Let me check your environment...

[Phase 1: Environment Detection]
AI: Environment check results:
     ✅ Python 3.11.2
     ✅ Node.js 20.0
     ❌ Claude Code CLI not found

[Phase 2: Install Dependencies]
AI: Installing dependencies...
     - Creating virtual environment
     - Installing Python packages
     - Installing Claude Code CLI via npm
     ✅ All dependencies installed

[Phase 3: Configuration]
AI: Which IM platform do you want to use?
     1. Slack (recommended for team use)
     2. Telegram (simple setup)
     3. DingTalk (for enterprise users)

User: [chooses 1, 2, or 3]

AI: [Displays platform-specific setup instructions]
    Please provide the following credentials:
    1. TOKEN: _

[User provides credentials]

AI: Validating credentials...
    ✅ Credentials valid
    ✅ .env file created

[Phase 4: Validation]
AI: Running validation checks...
    ✅ Configuration valid
    ✅ Working directory created

[Phase 5: Start]
AI: Starting vibe-remote service...
    ✅ Service started successfully

AI: Setup complete! You can now:
     - Send messages to your bot on [PLATFORM]
     - Use /start to see available commands
     - Use /clear to reset conversation
```

---

## Error Handling

### Python Version Too Old

```
ERROR: Python 3.9+ required. Current version: 3.8.10
SOLUTION: Install a newer Python version:
  - macOS: brew install python@3.11
  - Ubuntu: sudo apt install python3.11
  - Windows: Download from python.org
```

### Missing Node.js

```
ERROR: Node.js not found. Required for Claude Code CLI.
SOLUTION: Install Node.js:
  - macOS: brew install node
  - Ubuntu: sudo apt install nodejs npm
  - Windows: Download from nodejs.org
```

### Invalid Credentials

```
ERROR: Token validation failed for [PLATFORM]
SOLUTION: Please verify:
  1. Token is copied correctly (no extra spaces)
  2. Bot/App is created and activated
  3. Required permissions are granted
  4. Token hasn't expired or been revoked
```

### Port Already in Use

```
ERROR: Port 8080 already in use
SOLUTION: Stop the existing service:
  - ./stop.sh
  - Or kill the process: lsof -ti:8080 | xargs kill
```

---

## Post-Installation Steps

After successful installation, inform the user:

```
✅ vibe-remote is now running!

Next steps:
1. Invite your bot to a channel/chat
2. Send a test message like "hello"
3. Use /start to see all commands

Management commands:
  ./start.sh  - Start the service
  ./stop.sh   - Stop the service
  ./status.sh - Check service status

Logs are saved in: logs/bot_*.log
Configuration: .env
Settings persistence: user_settings.json
```

---

## Troubleshooting Commands

Provide these to users if they encounter issues:

```bash
# Check if service is running
./status.sh

# View real-time logs
tail -f logs/bot_*.log

# Test configuration
python -c "from config.settings import AppConfig; print('Config OK')"

# Restart service
./stop.sh && ./start.sh

# Reset all settings (clears sessions and preferences)
rm user_settings.json
./start.sh
```

---

## Advanced: Uninstallation

If user wants to completely remove vibe-remote:

```bash
# Stop service
./stop.sh

# Remove virtual environment
rm -rf venv

# Remove configuration
rm .env
rm user_settings.json

# Remove logs
rm -rf logs/

# Optionally remove Claude Code CLI
npm uninstall -g @anthropic-ai/claude-code
```

---

## Notes for AI Assistants

1. **Always validate before proceeding** - Don't assume environment is ready
2. **Provide progress feedback** - Users should see what's happening
3. **Handle errors gracefully** - Provide solutions, not just errors
4. **Respect user permissions** - Ask before using sudo or modifying system files
5. **Platform-specific commands** - Adjust commands for macOS/Linux/Windows
6. **Keep backups** - Don't overwrite existing .env without asking

---

## Version Compatibility

| Component | Minimum Version | Recommended Version |
|-----------|----------------|---------------------|
| Python | 3.9 | 3.11+ |
| Node.js | 18.x | 20.x LTS |
| npm | 9.x | 10.x |
| Claude Code CLI | Latest | Latest |

---

## Quick Reference for AI

```bash
# Complete installation sequence
python3 -m venv venv && \
source venv/bin/activate && \
pip install -r requirements.txt && \
npm install -g @anthropic-ai/claude-code && \
python3 setup.py && \
./start.sh
```

```python
# Python API check for installation
import sys
import subprocess
from pathlib import Path

def check_installation():
    """Verify vibe-remote installation"""
    checks = {
        "Python": sys.version_info >= (3, 9),
        "venv": Path("venv").exists(),
        ".env": Path(".env").exists(),
        "Claude CLI": shutil.which("claude") is not None,
    }
    return checks
```
