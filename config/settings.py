import logging
import os
import shlex
import shutil
from dataclasses import dataclass, field
from typing import List, Optional, Union
from modules.im.base import BaseIMConfig

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig(BaseIMConfig):
    bot_token: str
    target_chat_id: Optional[Union[List[int], str]] = (
        None  # Whitelist of chat IDs. Empty list = DM only, null/None = accept all
    )

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

        target_chat_id = None
        target_chat_id_str = os.getenv("TELEGRAM_TARGET_CHAT_ID")
        if target_chat_id_str:
            # Handle null string
            if target_chat_id_str.lower() in ["null", "none"]:
                target_chat_id = None
            # Handle empty list
            elif target_chat_id_str.strip() in ["[]", ""]:
                target_chat_id = []
            # Handle comma-separated list
            else:
                try:
                    # Remove brackets if present and split by comma
                    ids_str = target_chat_id_str.strip("[]")
                    if ids_str:
                        target_chat_id = [int(id.strip()) for id in ids_str.split(",")]
                    else:
                        target_chat_id = []
                except ValueError:
                    raise ValueError(
                        f"Invalid TELEGRAM_TARGET_CHAT_ID format: {target_chat_id_str}"
                    )

        return cls(bot_token=bot_token, target_chat_id=target_chat_id)

    def validate(self) -> bool:
        """Validate Telegram configuration"""
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        # Telegram bot token format is typically "<digits>:<token>"
        if ":" not in self.bot_token:
            logger.warning("Telegram bot token format might be invalid: missing colon")
        else:
            prefix = self.bot_token.split(":", 1)[0]
            if not prefix.isdigit():
                logger.warning(
                    "Telegram bot token format might be invalid: non-numeric prefix"
                )
        return True


@dataclass
class ClaudeConfig:
    permission_mode: str
    cwd: str
    system_prompt: Optional[str] = None

    @classmethod
    def from_env(cls) -> "ClaudeConfig":
        permission_mode = os.getenv("CLAUDE_PERMISSION_MODE")
        if not permission_mode:
            raise ValueError("CLAUDE_PERMISSION_MODE environment variable is required")

        cwd = os.getenv("CLAUDE_DEFAULT_CWD")
        if not cwd:
            raise ValueError("CLAUDE_DEFAULT_CWD environment variable is required")

        return cls(
            permission_mode=permission_mode,
            cwd=cwd,
            system_prompt=os.getenv("CLAUDE_SYSTEM_PROMPT"),
        )


@dataclass
class CodexConfig:
    binary: str = "codex"
    extra_args: List[str] = field(default_factory=list)
    default_model: Optional[str] = None

    @classmethod
    def from_env(cls) -> "CodexConfig":
        binary = os.getenv("CODEX_CLI_PATH", "codex")
        if not shutil.which(binary):
            raise ValueError(
                f"Codex CLI binary '{binary}' not found in PATH. "
                "Set CODEX_CLI_PATH or install Codex CLI."
            )

        extra_args_env = os.getenv("CODEX_EXTRA_ARGS", "").strip()
        extra_args = shlex.split(extra_args_env) if extra_args_env else []
        default_model = os.getenv("CODEX_DEFAULT_MODEL")

        return cls(
            binary=binary,
            extra_args=extra_args,
            default_model=default_model,
        )


@dataclass
class QoderConfig:
    binary: str = "qodercli"
    extra_args: List[str] = field(default_factory=list)
    default_model: Optional[str] = None

    @classmethod
    def from_env(cls) -> "QoderConfig":
        binary = os.getenv("QODER_CLI_PATH", "qodercli")
        if not shutil.which(binary):
            raise ValueError(
                f"Qoder CLI binary '{binary}' not found in PATH. "
                "Set QODER_CLI_PATH or install Qoder CLI."
            )

        extra_args_env = os.getenv("QODER_EXTRA_ARGS", "").strip()
        extra_args = shlex.split(extra_args_env) if extra_args_env else []
        default_model = os.getenv("QODER_DEFAULT_MODEL")

        return cls(
            binary=binary,
            extra_args=extra_args,
            default_model=default_model,
        )


@dataclass
class SlackConfig(BaseIMConfig):
    bot_token: str
    app_token: Optional[str] = None  # For Socket Mode
    signing_secret: Optional[str] = None  # For webhook mode
    target_channel: Optional[Union[List[str], str]] = (
        None  # Whitelist of channel IDs. Empty list = DM only, null/None = accept all
    )
    require_mention: bool = False  # Require @mention in channels (ignored in DMs)

    @classmethod
    def from_env(cls) -> "SlackConfig":
        bot_token = os.getenv("SLACK_BOT_TOKEN")
        if not bot_token:
            raise ValueError("SLACK_BOT_TOKEN environment variable is required")

        return cls(
            bot_token=bot_token,
            app_token=os.getenv("SLACK_APP_TOKEN"),
            signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
            target_channel=cls._parse_channel_list(os.getenv("SLACK_TARGET_CHANNEL")),
            require_mention=os.getenv("SLACK_REQUIRE_MENTION", "false").lower()
            == "true",
        )

    def validate(self) -> bool:
        """Validate Slack configuration"""
        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required")
        if not self.bot_token.startswith("xoxb-"):
            raise ValueError("Invalid Slack bot token format (should start with xoxb-)")
        if self.app_token and not self.app_token.startswith("xapp-"):
            raise ValueError("Invalid Slack app token format (should start with xapp-)")
        return True

    @classmethod
    def _parse_channel_list(
        cls, value: Optional[str]
    ) -> Optional[Union[List[str], str]]:
        """Parse channel list from environment variable"""
        if not value:
            return None

        # Handle null string
        if value.lower() in ["null", "none"]:
            return None

        # Handle empty list
        if value.strip() in ["[]", ""]:
            return []

        # Handle comma-separated list
        # Remove brackets if present and split by comma
        ids_str = value.strip("[]")
        if ids_str:
            return [id.strip() for id in ids_str.split(",")]
        else:
            return []


@dataclass
class DingtalkConfig(BaseIMConfig):
    """DingTalk (钉钉) IM platform configuration"""
    app_key: str
    app_secret: str
    target_conversation: Optional[Union[List[str], str]] = (
        None  # Whitelist of conversation IDs. Empty list = specific only, null/None = accept all
    )
    require_mention: bool = False  # Require @mention in group chats (ignored in DMs)

    @classmethod
    def from_env(cls) -> "DingtalkConfig":
        app_key = os.getenv("DINGTALK_APP_KEY")
        if not app_key:
            raise ValueError("DINGTALK_APP_KEY environment variable is required")

        app_secret = os.getenv("DINGTALK_APP_SECRET")
        if not app_secret:
            raise ValueError("DINGTALK_APP_SECRET environment variable is required")

        return cls(
            app_key=app_key,
            app_secret=app_secret,
            target_conversation=SlackConfig._parse_channel_list(os.getenv("DINGTALK_TARGET_CONVERSATION")),
            require_mention=os.getenv("DINGTALK_REQUIRE_MENTION", "false").lower() == "true",
        )

    def validate(self) -> bool:
        """Validate DingTalk configuration"""
        self.validate_required_string(self.app_key, "DINGTALK_APP_KEY")
        self.validate_required_string(self.app_secret, "DINGTALK_APP_SECRET")
        # DingTalk app_key is typically 64 characters
        if len(self.app_key) != 64:
            logger.warning("DingTalk app_key length might be invalid (expected 64 characters)")
        return True


@dataclass
class AppConfig:
    platform: str  # 'telegram', 'slack', or 'dingtalk'
    telegram: Optional[TelegramConfig] = None
    slack: Optional[SlackConfig] = None
    dingtalk: Optional[DingtalkConfig] = None
    claude: ClaudeConfig = None
    codex: Optional[CodexConfig] = None
    qoder: Optional["QoderConfig"] = None
    log_level: str = "INFO"
    cleanup_enabled: bool = False
    agent_route_file: Optional[str] = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        platform = os.getenv("IM_PLATFORM")
        if not platform:
            raise ValueError("IM_PLATFORM environment variable is required")

        platform = platform.lower()
        if platform not in ["telegram", "slack", "dingtalk"]:
            raise ValueError(
                f"Invalid IM_PLATFORM: {platform}. Must be 'telegram', 'slack', or 'dingtalk'"
            )

        log_level = os.getenv(
            "LOG_LEVEL", "INFO"
        )  # Keep default for log level as it's optional

        # Cleanup toggle (safe cleanup of completed tasks only)
        cleanup_enabled_env = os.getenv("CLEANUP_ENABLED", "false").lower()
        cleanup_enabled = cleanup_enabled_env in ["1", "true", "yes", "on"]

        agent_route_env = os.getenv("AGENT_ROUTE_FILE")
        agent_route_file = agent_route_env
        if not agent_route_file:
            candidate = os.path.join(os.getcwd(), "agent_routes.yaml")
            if os.path.exists(candidate):
                agent_route_file = candidate

        codex_config = None
        codex_enabled = os.getenv("CODEX_ENABLED", "true").lower() in [
            "1",
            "true",
            "yes",
            "on",
        ]
        if codex_enabled:
            try:
                codex_config = CodexConfig.from_env()
            except ValueError as exc:
                logger.warning(f"Codex support disabled: {exc}")
                codex_config = None

        qoder_config = None
        qoder_enabled = os.getenv("QODER_ENABLED", "true").lower() in [
            "1",
            "true",
            "yes",
            "on",
        ]
        if qoder_enabled:
            try:
                qoder_config = QoderConfig.from_env()
            except ValueError as exc:
                logger.warning(f"Qoder support disabled: {exc}")
                qoder_config = None

        config = cls(
            platform=platform,
            claude=ClaudeConfig.from_env(),
            log_level=log_level,
            cleanup_enabled=cleanup_enabled,
            codex=codex_config,
            qoder=qoder_config,
            agent_route_file=agent_route_file,
        )

        # Load platform-specific config
        if platform == "telegram":
            config.telegram = TelegramConfig.from_env()
            config.telegram.validate()
        elif platform == "slack":
            config.slack = SlackConfig.from_env()
            config.slack.validate()
        elif platform == "dingtalk":
            config.dingtalk = DingtalkConfig.from_env()
            config.dingtalk.validate()

        return config
