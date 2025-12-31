"""Factory for creating IM platform clients"""

import logging
from typing import Union, TYPE_CHECKING

from .base import BaseIMClient

# Use delayed imports to avoid circular import issues
if TYPE_CHECKING:
    from config.settings import AppConfig, TelegramConfig, SlackConfig, DingtalkConfig

logger = logging.getLogger(__name__)


class IMFactory:
    """Factory class to create the appropriate IM client based on platform"""
    
    @staticmethod
    def create_client(config) -> BaseIMClient:
        """Create and return the appropriate IM client based on configuration
        
        Args:
            config: Application configuration
            
        Returns:
            Instance of platform-specific IM client
            
        Raises:
            ValueError: If platform is not supported
        """
        # Dynamic imports to avoid circular dependency
        from .telegram import TelegramBot
        from .slack import SlackBot
        from .dingtalk import DingtalkBot

        platform = config.platform.lower()

        if platform == "telegram":
            if not config.telegram:
                raise ValueError("Telegram configuration not found")
            logger.info("Creating Telegram client")
            return TelegramBot(config.telegram)

        elif platform == "slack":
            if not config.slack:
                raise ValueError("Slack configuration not found")
            logger.info("Creating Slack client")
            return SlackBot(config.slack)

        elif platform == "dingtalk":
            if not config.dingtalk:
                raise ValueError("DingTalk configuration not found")
            logger.info("Creating DingTalk client")
            return DingtalkBot(config.dingtalk)

        else:
            raise ValueError(f"Unsupported IM platform: {platform}")
    
    @staticmethod
    def get_supported_platforms() -> list[str]:
        """Get list of supported platforms

        Returns:
            List of supported platform names
        """
        return ["telegram", "slack", "dingtalk"]
    
    @staticmethod
    def validate_platform_config(config) -> None:
        """Validate platform configuration before creating client
        
        Args:
            config: Application configuration
            
        Raises:
            ValueError: If configuration is invalid
        """
        platform = config.platform.lower()
        
        if platform not in IMFactory.get_supported_platforms():
            raise ValueError(f"Unsupported platform: {platform}")
        
        # Validate platform-specific configuration
        if platform == "telegram" and config.telegram:
            config.telegram.validate()
        elif platform == "slack" and config.slack:
            config.slack.validate()
        elif platform == "dingtalk" and config.dingtalk:
            config.dingtalk.validate()
        else:
            raise ValueError(f"Missing configuration for platform: {platform}")