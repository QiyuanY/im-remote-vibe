"""DingTalk (钉钉) IM client implementation.

This module implements the DingTalk platform client using the dingtalk-stream SDK.
DingTalk Stream mode uses WebSocket for real-time bidirectional communication,
similar to Slack's Socket Mode.

Reference: https://open.dingtalk.com/document/development/introduction-to-stream-mode
"""

import asyncio
import json
import logging
import hmac
import hashlib
import time
import threading
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime

from dingtalk_stream import DingTalkStreamClient, Credential, ChatbotHandler, ChatbotMessage, CallbackMessage
from dingtalk_stream.card_replier import CardReplier

from .base import BaseIMClient, MessageContext, InlineKeyboard, InlineButton
from config.settings import DingtalkConfig
from .formatters import DingtalkFormatter

logger = logging.getLogger(__name__)


class ChatbotMessageHandler(ChatbotHandler):
    """Handler for DingTalk chatbot messages"""

    def __init__(self, bot_instance):
        super().__init__()
        self.bot = bot_instance

    async def process(self, callback_message: CallbackMessage):
        """Process incoming chatbot message

        Args:
            callback_message: CallbackMessage from dingtalk-stream SDK
        """
        # Run message processing in a new thread to avoid blocking
        import threading
        thread = threading.Thread(target=self._process_message, args=(callback_message,))
        thread.daemon = True
        thread.start()
        # Return OK immediately - this is the ACK for DingTalk
        return 200, "OK"

    def _process_message(self, callback_message: CallbackMessage):
        """Process message in a separate thread

        Args:
            callback_message: CallbackMessage from dingtalk-stream SDK
        """
        try:
            # Convert CallbackMessage to ChatbotMessage
            chatbot_message = ChatbotMessage.from_dict(callback_message.data)

            # Get message content
            text_content = chatbot_message.get_text_list()
            content = "\n".join(text_content) if text_content else ""

            # Get message metadata from ChatbotMessage attributes
            conversation_id = chatbot_message.conversation_id or ""
            sender_id = chatbot_message.sender_id or ""
            msg_id = chatbot_message.message_id or ""
            session_webhook = chatbot_message.session_webhook or ""

            logger.info(f"Received DingTalk message from {sender_id} in {conversation_id}: {content[:50]}...")

            # Check if message is authorized
            if not self.bot._is_conversation_allowed(conversation_id):
                logger.info(f"Conversation {conversation_id} is not in target list, ignoring")
                return

            # Create message context
            context = MessageContext(
                user_id=sender_id,
                channel_id=conversation_id,
                message_id=msg_id,
                platform_specific={}
            )

            # Store session_webhook for reply
            if session_webhook:
                self.bot.session_webhook = session_webhook
                context.platform_specific["session_webhook"] = session_webhook

            # Check for commands (start with /)
            if content.strip().startswith("/"):
                parts = content.strip().split(maxsplit=1)
                command = parts[0].lstrip("/")
                args = parts[1] if len(parts) > 1 else ""

                handler = self.bot.on_command_callbacks.get(command)
                if handler:
                    # Run async handler in new event loop
                    self._run_async_handler(handler, context, args)
                    return

            # Handle as regular message
            if self.bot.on_message_callback:
                self._run_async_handler(self.bot.on_message_callback, context, content)

        except Exception as e:
            logger.error(f"Error processing stream message: {e}", exc_info=True)

    def _run_async_handler(self, handler, *args):
        """Run an async handler in a new event loop

        Args:
            handler: Async function to run
            *args: Arguments to pass to the handler
        """
        def run_in_loop():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(handler(*args))
                loop.close()
            except Exception as e:
                logger.error(f"Error running async handler: {e}", exc_info=True)

        thread = threading.Thread(target=run_in_loop)
        thread.daemon = True
        thread.start()


class DingtalkBot(BaseIMClient):
    """DingTalk implementation of the IM client using Stream mode"""

    def __init__(self, config: DingtalkConfig):
        super().__init__(config)
        self.config = config
        self.stream_client: Optional[DingTalkStreamClient] = None
        self.access_token: Optional[str] = None

        # Initialize DingTalk formatter
        self.formatter = DingtalkFormatter()

        # Store message handlers
        self.command_handlers: Dict[str, Callable] = {}

        # Session webhook for replying to messages
        self.session_webhook: Optional[str] = None

        # Settings manager for user settings
        self.settings_manager = None

        # Active stream connection
        self._running = False
        self._stream_task: Optional[asyncio.Task] = None

        # Message handler
        self.message_handler = ChatbotMessageHandler(self)

    def set_settings_manager(self, settings_manager):
        """Set the settings manager for user settings"""
        self.settings_manager = settings_manager

    def get_default_parse_mode(self) -> str:
        """Get the default parse mode for DingTalk"""
        return "markdown"

    def should_use_thread_for_reply(self) -> bool:
        """DingTalk doesn't use threads like Slack"""
        return False

    async def _get_access_token(self) -> str:
        """Get access token from DingTalk API

        Returns:
            Access token string
        """
        if self.access_token:
            return self.access_token

        # DingTalk get access token API
        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        timestamp = str(int(time.time() * 1000))

        # Build signature
        secret = self.config.app_secret.encode('utf-8')
        string_to_sign = f"{timestamp}\n{self.config.app_secret}".encode('utf-8')
        hmac_code = hmac.new(secret, string_to_sign, digestmod=hashlib.sha256).digest()
        sign = hmac_code.hex()

        params = {
            "appKey": self.config.app_key,
            "appSecret": self.config.app_secret,
            "timestamp": timestamp,
            "sign": sign
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to get access token: {error_text}")
                    raise RuntimeError(f"Failed to get access token: {response.status}")

                data = await response.json()
                # Check for error in response
                if data.get("errcode", 0) != 0:
                    logger.error(f"Failed to get access token: {data}")
                    raise RuntimeError(f"Failed to get access token: {data}")

                self.access_token = data.get("accessToken")
                if not self.access_token:
                    logger.error(f"No access token in response: {data}")
                    raise RuntimeError(f"No access token in response: {data}")
                logger.info("Successfully obtained DingTalk access token")
                return self.access_token

    async def send_message(self, context: MessageContext, text: str,
                          parse_mode: Optional[str] = None,
                          reply_to: Optional[str] = None) -> str:
        """Send a text message via DingTalk API

        Args:
            context: Message context (conversation_id, etc)
            text: Message text
            parse_mode: Optional formatting mode
            reply_to: Optional message ID to reply to

        Returns:
            Message ID of sent message
        """
        # Use session_webhook if available (from received message)
        webhook_url = context.platform_specific.get("session_webhook") if context.platform_specific else None

        if not webhook_url:
            # Fallback to send via API
            webhook_url = await self._get_conversation_webhook(context.channel_id)

        return await self._send_via_webhook(webhook_url, text, parse_mode)

    async def _get_conversation_webhook(self, conversation_id: str) -> str:
        """Get webhook URL for a conversation

        Args:
            conversation_id: DingTalk conversation ID

        Returns:
            Webhook URL for the conversation
        """
        access_token = await self._get_access_token()

        # Get conversation webhook API
        url = f"https://api.dingtalk.com/v1.0/robot/conversation/sendMessages"
        headers = {
            "x-acs-dingtalk-access-token": access_token
        }
        params = {
            "conversationId": conversation_id,
            "msgKey": ""
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to get conversation webhook: {error_text}")
                    raise RuntimeError(f"Failed to get conversation webhook: {response.status}")

                data = await response.json()
                # Extract webhook URL from response
                webhook_url = data.get("webhook", "")
                if not webhook_url:
                    logger.warning(f"No webhook in response: {data}")
                    raise RuntimeError("No webhook URL available for conversation")

                return webhook_url

    async def _send_via_webhook(self, webhook_url: str, text: str,
                              parse_mode: Optional[str] = None) -> str:
        """Send message via DingTalk webhook

        Args:
            webhook_url: DingTalk webhook URL
            text: Message text
            parse_mode: Formatting mode

        Returns:
            Message ID of sent message
        """
        import aiohttp

        # Build message payload for DingTalk markdown
        # DingTalk requires a title for markdown messages
        title = "Vibe Remote"
        # Try to extract a better title from the first line
        lines = text.strip().split('\n')
        if lines and lines[0].startswith('#'):
            title = lines[0].lstrip('#').strip()
            if len(title) > 20:
                title = title[:20] + '...'

        message_data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=message_data) as response:
                result = await response.json()

                if result.get("errcode") != 0:
                    logger.error(f"Failed to send message via webhook: {result}")
                    raise RuntimeError(f"Failed to send message: {result}")

                # Return message ID from response
                return result.get("messageId", "")

    async def send_message_with_buttons(self, context: MessageContext, text: str,
                                      keyboard: InlineKeyboard,
                                      parse_mode: Optional[str] = None) -> str:
        """Send a message with inline buttons using ActionCard

        Args:
            context: Message context
            text: Message text
            keyboard: Inline keyboard configuration
            parse_mode: Optional formatting mode

        Returns:
            Message ID of sent message
        """
        webhook_url = context.platform_specific.get("session_webhook") if context.platform_specific else None

        if not webhook_url:
            webhook_url = await self._get_conversation_webhook(context.channel_id)

        # Convert InlineKeyboard to DingTalk ActionCard button format
        btn_orientation = "1"  # 1 = horizontal
        btn_json = []

        for row in keyboard.buttons:
            for button in row:
                btn_json.append({
                    "title": button.text,
                    "actionURL": button.callback_data
                })

        # Build ActionCard message
        # DingTalk requires a title for ActionCard messages
        title = "Vibe Remote"
        # Try to extract a better title from the first line
        lines = text.strip().split('\n')
        if lines and lines[0].startswith('#'):
            title = lines[0].lstrip('#').strip()
            if len(title) > 20:
                title = title[:20] + '...'

        card = self.formatter.format_action_card(
            title=title,
            text=text,
            btn_orientation=btn_orientation
        )

        if btn_json:
            # Add first button for now (DingTalk ActionCard typically has single button)
            if btn_json:
                card["actionCard"]["btnOrientation"] = "0"
                card["actionCard"]["btns"] = btn_json

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=card) as response:
                result = await response.json()

                if result.get("errcode") != 0:
                    logger.error(f"Failed to send ActionCard message: {result}")
                    raise RuntimeError(f"Failed to send message with buttons: {result}")

                return result.get("messageId", "")

    async def edit_message(self, context: MessageContext, message_id: str,
                          text: Optional[str] = None,
                          keyboard: Optional[InlineKeyboard] = None) -> bool:
        """Edit an existing message

        Note: DingTalk doesn't natively support editing sent messages.
        This is a no-op that returns False.

        Args:
            context: Message context
            message_id: ID of message to edit
            text: New text (if provided)
            keyboard: New keyboard (if provided)

        Returns:
            False (not supported)
        """
        logger.warning("DingTalk doesn't support editing messages")
        return False

    async def answer_callback(self, callback_id: str, text: Optional[str] = None,
                            show_alert: bool = False) -> bool:
        """Answer a callback query from inline button

        Args:
            callback_id: Callback query ID
            text: Optional notification text
            show_alert: Show as alert popup

        Returns:
            Success status
        """
        # DingTalk callbacks are handled via event subscriptions
        # Return True to indicate callback was processed
        return True

    def register_handlers(self):
        """Register platform-specific message and command handlers"""
        # DingTalk uses stream mode handlers
        pass

    def run(self):
        """Start the DingTalk bot using Stream mode"""
        logger.info("Starting DingTalk bot in Stream mode...")

        # Create credential
        credential = Credential(self.config.app_key, self.config.app_secret)

        # Create stream client
        self.stream_client = DingTalkStreamClient(credential)

        # Register chatbot message handler
        self.stream_client.register_callback_handler(ChatbotMessage.TOPIC, self.message_handler)

        # Run the stream client (blocking call)
        self._running = True
        try:
            self.stream_client.start_forever()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"DingTalk stream error: {e}", exc_info=True)
        finally:
            self._running = False

    def _is_conversation_allowed(self, conversation_id: str) -> bool:
        """Check if conversation is allowed based on target_conversation config

        Args:
            conversation_id: DingTalk conversation ID

        Returns:
            True if conversation is allowed
        """
        target = self.config.target_conversation

        # None means accept all
        if target is None:
            return True

        # Empty list means reject all
        if isinstance(target, list) and len(target) == 0:
            return True

        # Check if conversation_id is in the target list
        if isinstance(target, list):
            return conversation_id in target

        # Single string target
        return conversation_id == target

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get information about a user

        Args:
            user_id: DingTalk user ID (union_id)

        Returns:
            User information dict
        """
        access_token = await self._get_access_token()

        url = f"https://api.dingtalk.com/v1.0/contact/users/{user_id}"
        headers = {
            "x-acs-dingtalk-access-token": access_token
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return {"error": f"HTTP {response.status}"}

                data = await response.json()
                if data.get("errcode") != 0:
                    return {"error": data.get("errmsg", "Unknown error")}

                return data.get("result", {})

    async def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """Get information about a conversation

        Args:
            channel_id: DingTalk conversation ID

        Returns:
            Conversation information dict
        """
        access_token = await self._get_access_token()

        url = f"https://api.dingtalk.com/v1.0/robot/conversation/getConversationInfo"
        headers = {
            "x-acs-dingtalk-access-token": access_token
        }
        params = {
            "conversationId": channel_id
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    return {"error": f"HTTP {response.status}"}

                data = await response.json()
                if data.get("errcode") != 0:
                    return {"error": data.get("errmsg", "Unknown error")}

                return data.get("result", {})

    def format_markdown(self, text: str) -> str:
        """Format markdown text for DingTalk

        Args:
            text: Text with common markdown formatting

        Returns:
            DingTalk-specific formatted text
        """
        return self.formatter.format_text(text)

    def stop(self):
        """Stop the DingTalk bot"""
        logger.info("Stopping DingTalk bot...")
        self._running = False
        logger.info("DingTalk bot stopped")

    def is_running(self) -> bool:
        """Check if the bot is running

        Returns:
            True if bot is running
        """
        return self._running
