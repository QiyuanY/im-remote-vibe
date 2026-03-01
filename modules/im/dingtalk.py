"""DingTalk (钉钉) IM client implementation.

This module implements the DingTalk platform client using the dingtalk-stream SDK.
DingTalk Stream mode uses WebSocket for real-time bidirectional communication,
similar to Slack's Socket Mode.

Reference: https://open.dingtalk.com/document/development/introduction-to-stream-mode
"""

import asyncio
import json
import logging
import time
import threading
from typing import Dict, Any, Optional, Callable, List

from dingtalk_stream import DingTalkStreamClient, Credential, ChatbotHandler, ChatbotMessage, CallbackMessage

from .base import BaseIMClient, MessageContext, InlineKeyboard, InlineButton
from config.settings import DingtalkConfig
from .formatters import DingtalkFormatter

logger = logging.getLogger(__name__)

# DingTalk markdown message length limit (conservative to avoid truncation)
_DINGTALK_MARKDOWN_MAX_LEN = 9000


def _chunk_text(text: str, max_len: int = _DINGTALK_MARKDOWN_MAX_LEN) -> List[str]:
    """Split long text into chunks that fit within DingTalk's limits."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunk = text[:max_len]
        # Try to break at a newline to avoid splitting mid-line
        last_nl = chunk.rfind("\n", max_len // 2)
        if last_nl > 0:
            chunk = text[:last_nl]
        chunks.append(chunk)
        text = text[len(chunk):]
    return chunks


class ChatbotMessageHandler(ChatbotHandler):
    """Handler for DingTalk chatbot messages"""

    def __init__(self, bot_instance):
        super().__init__()
        self.bot = bot_instance
        # Shared event loop for Claude's long-running receiver tasks
        self._loop = None
        self._loop_thread = None
        self._init_loop()

    def _init_loop(self):
        """Synchronously initialize the shared event loop for async operations."""
        import queue
        result_queue = queue.Queue()

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            result_queue.put(self._loop)
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()
        # Block until the event loop is successfully created and assigned
        self._loop = result_queue.get(timeout=10)

    async def process(self, callback_message: CallbackMessage):
        """Process incoming chatbot message and ACK immediately."""
        def task_done(fut):
            try:
                fut.result()
            except Exception as e:
                logger.error(f"Error in async task: {e}", exc_info=True)

        future = asyncio.run_coroutine_threadsafe(
            self._process_message(callback_message), self._loop
        )
        future.add_done_callback(task_done)
        return 200, "OK"

    async def _process_message(self, callback_message: CallbackMessage):
        """Process message asynchronously."""
        try:
            chatbot_message = ChatbotMessage.from_dict(callback_message.data)

            text_content = chatbot_message.get_text_list()
            content = "\n".join(text_content) if text_content else ""

            conversation_id = chatbot_message.conversation_id or ""
            sender_id = chatbot_message.sender_id or ""
            sender_staff_id = chatbot_message.sender_staff_id or ""
            msg_id = chatbot_message.message_id or ""
            session_webhook = chatbot_message.session_webhook or ""
            session_webhook_expired_time = chatbot_message.session_webhook_expired_time or 0
            conversation_type = chatbot_message.conversation_type or "1"
            robot_code = chatbot_message.robot_code or self.bot.config.app_key
            is_in_at_list = chatbot_message.is_in_at_list or False

            logger.info(
                f"Received DingTalk message from {sender_id} in {conversation_id} "
                f"(type={conversation_type}): {content[:50]}..."
            )

            if not self.bot._is_conversation_allowed(conversation_id):
                logger.info(f"Conversation {conversation_id} not in target list, ignoring")
                return

            # require_mention: for group chats, only respond when @mentioned
            if self.bot.config.require_mention and conversation_type == "2":
                if not is_in_at_list:
                    logger.debug(
                        f"require_mention=True but bot not in at_list for group {conversation_id}, ignoring"
                    )
                    return

            # Strip @mention text so Claude doesn't see it
            if is_in_at_list and content:
                import re
                content = re.sub(r"@\S+\s*", "", content).strip()

            context = MessageContext(
                user_id=sender_id,
                channel_id=conversation_id,
                message_id=msg_id,
                platform_specific={
                    "session_webhook": session_webhook,
                    "session_webhook_expired_time": session_webhook_expired_time,
                    "conversation_type": conversation_type,
                    "sender_staff_id": sender_staff_id,
                    "robot_code": robot_code,
                },
            )

            # Update bot-level webhook cache as fallback
            if session_webhook:
                self.bot._update_conversation_webhook(
                    conversation_id, session_webhook, session_webhook_expired_time,
                    conversation_type, sender_staff_id, robot_code
                )

            if content.strip().startswith("/"):
                parts = content.strip().split(maxsplit=1)
                command = parts[0].lstrip("/")
                args = parts[1] if len(parts) > 1 else ""
                handler = self.bot.on_command_callbacks.get(command)
                if handler:
                    await handler(context, args)
                    return

            if self.bot.on_message_callback:
                await self.bot.on_message_callback(context, content)

        except Exception as e:
            logger.error(f"Error processing stream message: {e}", exc_info=True)


class DingtalkBot(BaseIMClient):
    """DingTalk implementation of the IM client using Stream mode"""

    def __init__(self, config: DingtalkConfig):
        super().__init__(config)
        self.config = config
        self.stream_client: Optional[DingTalkStreamClient] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        self.formatter = DingtalkFormatter()
        self.command_handlers: Dict[str, Callable] = {}
        self.settings_manager = None
        self._running = False

        # Per-conversation webhook cache:
        # { conversation_id: { webhook, expired_time, type, staff_id, robot_code } }
        self._conversation_cache: Dict[str, Dict[str, Any]] = {}

        self.message_handler = ChatbotMessageHandler(self)

    def set_settings_manager(self, settings_manager):
        self.settings_manager = settings_manager

    def get_default_parse_mode(self) -> str:
        return "markdown"

    def should_use_thread_for_reply(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Conversation metadata cache
    # ------------------------------------------------------------------

    def _update_conversation_webhook(
        self,
        conversation_id: str,
        webhook: str,
        expired_time: int,
        conversation_type: str,
        sender_staff_id: str,
        robot_code: str,
    ):
        """Cache the latest session_webhook and metadata for a conversation."""
        self._conversation_cache[conversation_id] = {
            "webhook": webhook,
            "expired_time": expired_time,
            "conversation_type": conversation_type,
            "sender_staff_id": sender_staff_id,
            "robot_code": robot_code,
        }

    def _get_valid_webhook(self, conversation_id: str) -> Optional[str]:
        """Return the cached webhook URL if still valid (with 60s buffer)."""
        entry = self._conversation_cache.get(conversation_id)
        if not entry:
            return None
        expired_time = entry.get("expired_time", 0)
        # expired_time is in milliseconds
        if expired_time and time.time() * 1000 < expired_time - 60_000:
            return entry.get("webhook")
        return None

    # ------------------------------------------------------------------
    # Access token
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        """Get or refresh the DingTalk v1.0 access token."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        body = {
            "appKey": self.config.app_key,
            "appSecret": self.config.app_secret,
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Failed to get DingTalk access token: HTTP {resp.status} {error_text}")
                    raise RuntimeError(f"Failed to get access token: HTTP {resp.status}")

                data = await resp.json()
                token = data.get("accessToken")
                if not token:
                    raise RuntimeError(f"No accessToken in response: {data}")

                expires_in = data.get("expireIn", 7200)
                self._access_token = token
                self._token_expires_at = time.time() + expires_in
                logger.info(f"DingTalk access token refreshed, expires in {expires_in}s")
                return token

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    async def send_message(
        self,
        context: MessageContext,
        text: str,
        parse_mode: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> str:
        """Send a text message.

        Tries session_webhook first (fast & free), falls back to robot API.
        Long messages are automatically chunked.
        """
        chunks = _chunk_text(text)
        last_msg_id = ""
        for chunk in chunks:
            last_msg_id = await self._send_single(context, chunk)
        return last_msg_id

    async def _send_single(self, context: MessageContext, text: str) -> str:
        """Send a single (already-sized) chunk."""
        platform = context.platform_specific or {}
        conversation_id = context.channel_id

        # 1. Try the webhook from current context
        webhook = platform.get("session_webhook")
        expired_time = platform.get("session_webhook_expired_time", 0)
        if webhook and expired_time:
            if time.time() * 1000 < expired_time - 60_000:
                return await self._send_via_webhook(webhook, text)
            else:
                logger.debug("Context session_webhook expired, checking cache")

        # 2. Try cached webhook for this conversation
        cached_webhook = self._get_valid_webhook(conversation_id)
        if cached_webhook:
            return await self._send_via_webhook(cached_webhook, text)

        # 3. Fall back to robot API
        conversation_type = platform.get("conversation_type") or self._get_cached_field(
            conversation_id, "conversation_type", "1"
        )
        if conversation_type == "2":
            return await self._send_to_group(conversation_id, text, platform)
        else:
            return await self._send_to_user(conversation_id, text, platform)

    def _get_cached_field(self, conversation_id: str, field: str, default: Any = None) -> Any:
        entry = self._conversation_cache.get(conversation_id, {})
        return entry.get(field, default)

    async def _send_via_webhook(self, webhook_url: str, text: str) -> str:
        """Send markdown message via DingTalk session webhook."""
        import aiohttp

        try:
            title = self._extract_title(text)
        except Exception as e:
            logger.warning(f"Failed to extract title, using default: {e}")
            title = "Vibe Remote"

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                result = await resp.json()
                if result.get("errcode") not in (0, None) or (
                    resp.status != 200 and result.get("errcode") != 0
                ):
                    logger.error(f"Webhook send failed: {result}")
                    raise RuntimeError(f"Webhook send failed: {result}")
                return result.get("messageId", "")

    async def _send_to_group(
        self, conversation_id: str, text: str, platform: Dict[str, Any]
    ) -> str:
        """Send message to a group chat via robot API."""
        access_token = await self._get_access_token()
        robot_code = platform.get("robot_code") or self._get_cached_field(
            conversation_id, "robot_code", self.config.app_key
        )
        try:
            title = self._extract_title(text)
        except Exception as e:
            logger.warning(f"Failed to extract title, using default: {e}")
            title = "Vibe Remote"
        msg_param = json.dumps({"title": title, "text": text}, ensure_ascii=False)

        url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
        headers = {"x-acs-dingtalk-access-token": access_token}
        body = {
            "robotCode": robot_code,
            "openConversationId": conversation_id,
            "msgKey": "sampleMarkdown",
            "msgParam": msg_param,
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logger.error(f"Failed to send group message: HTTP {resp.status} {err}")
                    raise RuntimeError(f"Group message failed: HTTP {resp.status}")
                result = await resp.json()
                return result.get("processQueryKey", "")

    async def _send_to_user(
        self, conversation_id: str, text: str, platform: Dict[str, Any]
    ) -> str:
        """Send 1-on-1 message via robot API using staffId."""
        access_token = await self._get_access_token()
        robot_code = platform.get("robot_code") or self._get_cached_field(
            conversation_id, "robot_code", self.config.app_key
        )
        staff_id = platform.get("sender_staff_id") or self._get_cached_field(
            conversation_id, "sender_staff_id"
        )

        if not staff_id:
            logger.warning(
                f"No sender_staff_id for conversation {conversation_id}; cannot send via robot API"
            )
            raise RuntimeError("Cannot send message: no sender staff ID available")

        try:
            title = self._extract_title(text)
        except Exception as e:
            logger.warning(f"Failed to extract title, using default: {e}")
            title = "Vibe Remote"
        msg_param = json.dumps({"title": title, "text": text}, ensure_ascii=False)

        url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
        headers = {"x-acs-dingtalk-access-token": access_token}
        body = {
            "robotCode": robot_code,
            "userIds": [staff_id],
            "msgKey": "sampleMarkdown",
            "msgParam": msg_param,
        }

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    logger.error(f"Failed to send 1-on-1 message: HTTP {resp.status} {err}")
                    raise RuntimeError(f"1-on-1 message failed: HTTP {resp.status}")
                result = await resp.json()
                return result.get("processQueryKey", "")

    @staticmethod
    def _extract_title(text: str) -> str:
        """Extract a short title from message text for DingTalk markdown cards."""
        lines = text.strip().split("\n")
        for line in lines:
            stripped = line.lstrip("#").strip()
            if stripped:
                return stripped[:40] + ("..." if len(stripped) > 40 else "")
        return "Vibe Remote"

    # ------------------------------------------------------------------
    # Message with buttons (ActionCard)
    # ------------------------------------------------------------------

    async def send_message_with_buttons(
        self,
        context: MessageContext,
        text: str,
        keyboard: InlineKeyboard,
        parse_mode: Optional[str] = None,
    ) -> str:
        """Send ActionCard with buttons via webhook or robot API."""
        platform = context.platform_specific or {}
        conversation_id = context.channel_id

        webhook = platform.get("session_webhook")
        expired_time = platform.get("session_webhook_expired_time", 0)
        # Check if webhook is expired (use > to avoid prematurely invalidating at exact boundary)
        if webhook and expired_time and time.time() * 1000 > expired_time - 60_000:
            webhook = None
        if not webhook:
            webhook = self._get_valid_webhook(conversation_id)

        try:
            title = self._extract_title(text)
        except Exception as e:
            logger.warning(f"Failed to extract title, using default: {e}")
            title = "Vibe Remote"
        btns = []
        for row in keyboard.buttons:
            for btn in row:
                # Buttons use deep-link URLs; callback_data becomes the action identifier
                btns.append({"title": btn.text, "actionURL": f"dingtalk://dingtalkclient/action?type=bot_msg&text={btn.callback_data}"})

        card = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "text": text,
                "btnOrientation": "0",
                "btns": btns,
            },
        }

        import aiohttp
        if webhook:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook, json=card) as resp:
                    result = await resp.json()
                    if result.get("errcode") not in (0, None):
                        logger.error(f"ActionCard send failed: {result}")
                        raise RuntimeError(f"ActionCard send failed: {result}")
                    return result.get("messageId", "")

        # Fallback: send plain markdown without buttons
        logger.warning("No valid webhook for ActionCard; falling back to plain markdown")
        return await self.send_message(context, text, parse_mode)

    # ------------------------------------------------------------------
    # Edit / Delete (limited DingTalk support)
    # ------------------------------------------------------------------

    async def edit_message(
        self,
        context: MessageContext,
        message_id: str,
        text: Optional[str] = None,
        keyboard: Optional[InlineKeyboard] = None,
    ) -> bool:
        logger.debug("DingTalk does not support editing messages; skipping")
        return False

    async def answer_callback(
        self, callback_id: str, text: Optional[str] = None, show_alert: bool = False
    ) -> bool:
        return True

    async def delete_message(self, channel_id: str, message_id: str) -> bool:
        logger.debug(f"delete_message called for {message_id}, not supported on DingTalk")
        return True

    # ------------------------------------------------------------------
    # User / channel info
    # ------------------------------------------------------------------

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        try:
            access_token = await self._get_access_token()
        except Exception as e:
            return {"error": str(e)}

        url = f"https://api.dingtalk.com/v1.0/contact/users/{user_id}"
        headers = {"x-acs-dingtalk-access-token": access_token}

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return {"error": f"HTTP {resp.status}"}
                return await resp.json()

    async def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """Return basic info from cache; DingTalk doesn't have a simple channel info API."""
        cached = self._conversation_cache.get(channel_id, {})
        return {
            "id": channel_id,
            "conversation_type": cached.get("conversation_type", "unknown"),
        }

    # ------------------------------------------------------------------
    # Markdown formatting
    # ------------------------------------------------------------------

    def format_markdown(self, text: str) -> str:
        return self.formatter.format_text(text)

    # ------------------------------------------------------------------
    # Allow-list check
    # ------------------------------------------------------------------

    def _is_conversation_allowed(self, conversation_id: str) -> bool:
        target = self.config.target_conversation
        if target is None:
            return True
        if isinstance(target, list):
            if len(target) == 0:
                return True
            return conversation_id in target
        return conversation_id == target

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def register_handlers(self):
        pass

    def run(self):
        logger.info("Starting DingTalk bot in Stream mode...")
        credential = Credential(self.config.app_key, self.config.app_secret)
        self.stream_client = DingTalkStreamClient(credential)
        self.stream_client.register_callback_handler(
            ChatbotMessage.TOPIC, self.message_handler
        )
        self._running = True
        try:
            self.stream_client.start_forever()
        except KeyboardInterrupt:
            logger.info("DingTalk bot received keyboard interrupt")
        except Exception as e:
            logger.error(f"DingTalk stream error: {e}", exc_info=True)
        finally:
            self._running = False

    def stop(self):
        logger.info("Stopping DingTalk bot...")
        self._running = False

    def is_running(self) -> bool:
        return self._running
