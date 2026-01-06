#!/usr/bin/env python3
"""
vibe-remote Interactive Setup Script

This script helps users configure vibe-remote by guiding them through
the setup process for their chosen IM platform.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

try:
    import aiohttp
except ImportError:
    print("Error: aiohttp is required. Run: pip install aiohttp")
    sys.exit(1)


# Colors for terminal output
class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.END}\n")


def print_success(text: str):
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_error(text: str):
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_info(text: str):
    print(f"{Colors.CYAN}ℹ {text}{Colors.END}")


def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")


def get_input(prompt: str, default: Optional[str] = None, password: bool = False) -> str:
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "

    if password:
        import getpass
        value = getpass.getpass(prompt)
    else:
        value = input(prompt).strip()

    if not value and default:
        return default
    return value


def check_python_version() -> bool:
    """Check if Python version is compatible."""
    version = sys.version_info
    if version < (3, 9):
        print_error(f"Python 3.9+ required, you have {version.major}.{version.minor}.{version.micro}")
        return False
    print_success(f"Python version: {version.major}.{version.minor}.{version.micro}")
    return True


def check_working_directory() -> Path:
    """Check and return the project directory."""
    cwd = Path.cwd()
    if not (cwd / "main.py").exists():
        print_error("Please run this script from the vibe-remote project directory")
        sys.exit(1)
    print_success(f"Project directory: {cwd}")
    return cwd


def check_dependencies() -> dict:
    """Check which optional dependencies are installed."""
    result = {"claude": False, "qoder": False, "codex": False}

    # Check Claude Code CLI
    try:
        import shutil
        claude_path = shutil.which("claude")
        if claude_path:
            result["claude"] = True
            print_success(f"Claude Code CLI found: {claude_path}")
        else:
            print_warning("Claude Code CLI not found")
    except Exception:
        print_warning("Could not check for Claude Code CLI")

    # Check Qoder CLI
    try:
        import shutil
        qoder_path = shutil.which("qodercli")
        if qoder_path:
            result["qoder"] = True
            print_success(f"Qoder CLI found: {qoder_path}")
        else:
            print_info("Qoder CLI not found (optional)")
    except Exception:
        pass

    # Check Codex CLI
    try:
        import shutil
        codex_path = shutil.which("codex")
        if codex_path:
            result["codex"] = True
            print_success(f"Codex CLI found: {codex_path}")
        else:
            print_info("Codex CLI not found (optional)")
    except Exception:
        pass

    return result


async def validate_slack_token(bot_token: str, app_token: str) -> bool:
    """Validate Slack tokens by making a test API call."""
    try:
        async with aiohttp.ClientSession() as session:
            # Validate bot token
            async with session.get(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"}
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                if not data.get("ok"):
                    return False

            # Validate app token format (xapp-*)
            if not app_token.startswith("xapp-"):
                return False

        return True
    except Exception:
        return False


async def validate_telegram_token(bot_token: str) -> bool:
    """Validate Telegram bot token by making a test API call."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.telegram.org/bot{bot_token}/getMe"
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                return data.get("ok", False)
    except Exception:
        return False


async def validate_dingtalk_credentials(app_key: str, app_secret: str) -> bool:
    """Validate DingTalk credentials by getting access token."""
    try:
        async with aiohttp.ClientSession() as session:
            # Get access token
            async with session.post(
                "https://api.dingtalk.com/v1.0/oauth2/accessToken",
                json={"appKey": app_key, "appSecret": app_secret}
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                return "accessToken" in data
    except Exception:
        return False


def setup_platform(project_dir: Path, dependencies: dict) -> str:
    """Guide user through platform selection and configuration."""
    print_header("选择 IM 平台 / Select IM Platform")

    print("可用的 IM 平台 / Available platforms:")
    print("  [1] Slack")
    print("  [2] Telegram")
    print("  [3] DingTalk (钉钉)")
    print()

    choice = get_input("请选择平台 / Enter platform number", default="1")

    platforms = {
        "1": "slack",
        "2": "telegram",
        "3": "dingtalk"
    }

    platform = platforms.get(choice, "slack")
    print_info(f"已选择: {platform.upper()} / Selected: {platform.upper()}")

    env_vars = {}

    if platform == "slack":
        env_vars = setup_slack(dependencies)
    elif platform == "telegram":
        env_vars = setup_telegram(dependencies)
    elif platform == "dingtalk":
        env_vars = setup_dingtalk(dependencies)

    return platform, env_vars


def setup_slack(dependencies: dict) -> dict:
    """Setup Slack configuration."""
    print_header("Slack 配置 / Slack Configuration")

    print("\n请按以下步骤获取 Slack 凭证:")
    print("1. 访问 https://api.slack.com/apps")
    print("2. 创建新应用 或选择已有应用")
    print("3. 在 'OAuth & Permissions' 中:")
    print("   - 添加 Bot Token Scope (chat:write, channels:history, groups:history, im:history, mpim:history)")
    print("   - 滚动到顶部，点击 'Bot User OAuth Token' → 'Install to Workspace'")
    print("4. 在 'Basic Information' 中启用 Socket Mode")
    print("   - 并获取 App-Level Token")
    print()

    bot_token = get_input("输入 Bot Token (xoxb-...)")
    app_token = get_input("输入 App Token (xapp-...)")

    # Optional settings
    print()
    print_info("可选配置 / Optional settings:")
    target_channel = get_input("限制频道 ID (可选，多个用逗号分隔)", default="")
    require_mention = get_input("频道中需要 @提及才响应? (y/n)", default="n")

    env_vars = {
        "IM_PLATFORM": "slack",
        "SLACK_BOT_TOKEN": bot_token,
        "SLACK_APP_TOKEN": app_token,
    }

    if target_channel:
        env_vars["SLACK_TARGET_CHANNEL"] = f"[{target_channel}]"
    else:
        env_vars["SLACK_TARGET_CHANNEL"] = "[]"

    env_vars["SLACK_REQUIRE_MENTION"] = "true" if require_mention.lower() == "y" else "false"

    # Validate
    print()
    print_info("正在验证配置...")

    async def validate():
        valid = await validate_slack_token(bot_token, app_token)
        if valid:
            print_success("Slack 配置有效!")
        else:
            print_warning("无法验证 Slack Token，但会继续配置")

    asyncio.run(validate())

    return env_vars


def setup_telegram(dependencies: dict) -> dict:
    """Setup Telegram configuration."""
    print_header("Telegram 配置 / Telegram Configuration")

    print("\n请按以下步骤获取 Telegram Bot Token:")
    print("1. 在 Telegram 中搜索 @BotFather")
    print("2. 发送 /newbot 创建新机器人")
    print("3. 按提示设置机器人名称")
    print("4. 获得类似这样的 Token: 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
    print()

    bot_token = get_input("输入 Bot Token")

    # Optional settings
    print()
    print_info("可选配置 / Optional settings:")
    target_chat = get_input("限制聊天 ID (可选，多个用逗号分隔)", default="")

    env_vars = {
        "IM_PLATFORM": "telegram",
        "TELEGRAM_BOT_TOKEN": bot_token,
    }

    if target_chat:
        env_vars["TELEGRAM_TARGET_CHAT_ID"] = f"[{target_chat}]"
    else:
        env_vars["TELEGRAM_TARGET_CHAT_ID"] = "[]"

    # Validate
    print()
    print_info("正在验证配置...")

    async def validate():
        valid = await validate_telegram_token(bot_token)
        if valid:
            print_success("Telegram 配置有效!")
        else:
            print_warning("无法验证 Telegram Token，请检查是否正确")

    asyncio.run(validate())

    return env_vars


def setup_dingtalk(dependencies: dict) -> dict:
    """Setup DingTalk configuration."""
    print_header("DingTalk 配置 / DingTalk 配置")

    print("\n请按以下步骤获取钉钉应用凭证:")
    print("1. 访问 https://open.dingtalk.com/")
    print("2. 创建企业内部应用")
    print("3. 在应用详情页获取:")
    print("   - AppKey (Client ID)")
    print("   - AppSecret (Client Secret)")
    print()

    app_key = get_input("输入 AppKey")
    app_secret = get_input("输入 AppSecret", password=True)

    # Optional settings
    print()
    print_info("可选配置 / Optional settings:")
    target_conversation = get_input("限制会话 ID (可选，多个用逗号分隔)", default="")
    require_mention = get_input("群聊中需要 @提及才响应? (y/n)", default="n")

    env_vars = {
        "IM_PLATFORM": "dingtalk",
        "DINGTALK_APP_KEY": app_key,
        "DINGTALK_APP_SECRET": app_secret,
    }

    if target_conversation:
        env_vars["DINGTALK_TARGET_CONVERSATION"] = f"[{target_conversation}]"
    else:
        env_vars["DINGTALK_TARGET_CONVERSATION"] = "[]"

    env_vars["DINGTALK_REQUIRE_MENTION"] = "true" if require_mention.lower() == "y" else "false"

    # Validate
    print()
    print_info("正在验证配置...")

    async def validate():
        valid = await validate_dingtalk_credentials(app_key, app_secret)
        if valid:
            print_success("DingTalk 配置有效!")
        else:
            print_warning("无法验证 DingTalk 凭证，请检查是否正确")

    asyncio.run(validate())

    return env_vars


def setup_agent(dependencies: dict) -> dict:
    """Setup agent selection."""
    print_header("Agent 配置 / Agent Configuration")

    print("可用的 AI Agents:")
    print("  [1] Claude (默认，推荐)")
    if dependencies.get("qoder"):
        print("  [2] Qoder (轻量级)")
    if dependencies.get("codex"):
        print("  [3] Codex")
    print()

    choice = get_input("选择默认 Agent (可选)", default="1")

    env_vars = {}

    if choice == "1":
        print_info("使用 Claude Agent")
        env_vars["CLAUDE_DEFAULT_CWD"] = get_input("工作目录 (默认: ./_tmp)", default="./_tmp")
        env_vars["CLAUDE_PERMISSION_MODE"] = "bypassPermissions"
        env_vars["CLAUDE_SYSTEM_PROMPT"] = ""

    elif choice == "2" and dependencies.get("qoder"):
        print_info("使用 Qoder Agent")
        # Qoder-specific settings could go here

    elif choice == "3" and dependencies.get("codex"):
        print_info("使用 Codex Agent")

    return env_vars


def write_env_file(project_dir: Path, platform_vars: dict, agent_vars: dict):
    """Write the .env file."""
    env_file = project_dir / ".env"

    print_header("生成配置文件 / Generating Configuration")

    # Check if .env already exists
    if env_file.exists():
        print_warning(".env 文件已存在")
        overwrite = get_input("是否覆盖? (y/n)", default="n")
        if overwrite.lower() != "y":
            print_info("保留现有配置，跳过文件生成")
            return

    # Combine all env vars
    all_vars = {**platform_vars, **agent_vars}

    # Write to .env
    with open(env_file, "w") as f:
        f.write("# IM Platform Selection\n")
        f.write(f"IM_PLATFORM={platform_vars['IM_PLATFORM']}\n\n")

        if platform_vars['IM_PLATFORM'] == "slack":
            f.write("# ============== Slack Configuration ==============\n")
            f.write(f"SLACK_BOT_TOKEN={platform_vars['SLACK_BOT_TOKEN']}\n")
            f.write(f"SLACK_APP_TOKEN={platform_vars['SLACK_APP_TOKEN']}\n")
            f.write(f"SLACK_TARGET_CHANNEL={platform_vars.get('SLACK_TARGET_CHANNEL', '[]')}\n")
            f.write(f"SLACK_REQUIRE_MENTION={platform_vars.get('SLACK_REQUIRE_MENTION', 'false')}\n\n")

        elif platform_vars['IM_PLATFORM'] == "telegram":
            f.write("# ============== Telegram Configuration ==============\n")
            f.write(f"TELEGRAM_BOT_TOKEN={platform_vars['TELEGRAM_BOT_TOKEN']}\n")
            f.write(f"TELEGRAM_TARGET_CHAT_ID={platform_vars.get('TELEGRAM_TARGET_CHAT_ID', '[]')}\n\n")

        elif platform_vars['IM_PLATFORM'] == "dingtalk":
            f.write("# ============== DingTalk Configuration ==============\n")
            f.write(f"DINGTALK_APP_KEY={platform_vars['DINGTALK_APP_KEY']}\n")
            f.write(f"DINGTALK_APP_SECRET={platform_vars['DINGTALK_APP_SECRET']}\n")
            f.write(f"DINGTALK_TARGET_CONVERSATION={platform_vars.get('DINGTALK_TARGET_CONVERSATION', '[]')}\n")
            f.write(f"DINGTALK_REQUIRE_MENTION={platform_vars.get('DINGTALK_REQUIRE_MENTION', 'false')}\n\n")

        # Claude configuration
        if "CLAUDE_DEFAULT_CWD" in agent_vars:
            f.write("# Claude Configuration\n")
            f.write(f"CLAUDE_PERMISSION_MODE={agent_vars.get('CLAUDE_PERMISSION_MODE', 'bypassPermissions')}\n")
            f.write(f"CLAUDE_DEFAULT_CWD={agent_vars.get('CLAUDE_DEFAULT_CWD', './_tmp')}\n")
            if agent_vars.get('CLAUDE_SYSTEM_PROMPT'):
                f.write(f"CLAUDE_SYSTEM_PROMPT={agent_vars['CLAUDE_SYSTEM_PROMPT']}\n")
            f.write("\n")

        f.write("# Application Configuration\n")
        f.write("LOG_LEVEL=INFO\n")

    print_success(f"配置文件已生成: {env_file}")


def show_next_steps(project_dir: Path, platform: str):
    """Show next steps to the user."""
    print_header("下一步 / Next Steps")

    print(f"\n配置已完成！现在可以启动服务:\n")
    print(f"  启动 / Start:")
    print(f"    {Colors.YELLOW}./start.sh{Colors.END}\n")
    print(f"  停止 / Stop:")
    print(f"    {Colors.YELLOW}./stop.sh{Colors.END}\n")
    print(f"  查看状态 / Status:")
    print(f"    {Colors.YELLOW}./status.sh{Colors.END}\n")

    # Show platform-specific info
    if platform == "slack":
        print(f"\n{Colors.CYAN}Slack 使用提示:{Colors.END}")
        print("  - 将机器人邀请到频道后即可开始对话")
        print("  - 使用 /start 命令查看所有可用命令")

    elif platform == "telegram":
        print(f"\n{Colors.CYAN}Telegram 使用提示:{Colors.END}")
        print("  - 在 Telegram 中搜索你的机器人并开始对话")
        print("  - 使用 /start 命令查看所有可用命令")

    elif platform == "dingtalk":
        print(f"\n{Colors.CYAN}DingTalk 使用提示:{Colors.END}")
        print("  - 在钉钉中将机器人添加到群聊或单聊")
        print("  - 直接发送消息即可开始对话")

    print()


def main():
    """Main setup function."""
    print_header("vibe-remote 配置向导 / vibe-remote Setup Wizard")

    # Check Python version
    if not check_python_version():
        sys.exit(1)

    # Check working directory
    project_dir = check_working_directory()

    # Check dependencies
    print_header("检查依赖 / Checking Dependencies")
    dependencies = check_dependencies()

    # Select and configure platform
    platform, platform_vars = setup_platform(project_dir, dependencies)

    # Configure agent
    agent_vars = setup_agent(dependencies)

    # Write .env file
    write_env_file(project_dir, platform_vars, agent_vars)

    # Show next steps
    show_next_steps(project_dir, platform)

    print_success("配置完成！运行 ./start.sh 启动服务 / Setup complete! Run ./start.sh to start the service")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}配置已取消 / Setup cancelled{Colors.END}")
        sys.exit(0)
    except Exception as e:
        print_error(f"配置过程中出错: {e}")
        sys.exit(1)
