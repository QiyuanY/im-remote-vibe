import asyncio
import logging
import os
from typing import Callable, Optional

from claude_code_sdk import TextBlock

from modules.agents.base import AgentRequest, BaseAgent
from modules.im import MessageContext

logger = logging.getLogger(__name__)


class ClaudeAgent(BaseAgent):
    """Existing Claude Code integration extracted into an agent backend."""

    name = "claude"

    def __init__(self, controller):
        super().__init__(controller)
        self.session_handler = controller.session_handler
        self.session_manager = controller.session_manager
        self.receiver_tasks = controller.receiver_tasks
        self.claude_sessions = controller.claude_sessions
        self.claude_client = controller.claude_client
        self._last_assistant_text: dict[str, str] = {}
        # Message buffer for batching same-type messages
        self._pending_messages: dict[str, list[tuple[str, str]]] = {}  # composite_key -> [(msg_type, text), ...]
        self._flush_tasks: dict[str, Optional[asyncio.Task]] = {}
        # Lock for protecting concurrent access to message buffers
        self._buffer_lock = asyncio.Lock()
        # Max entries to prevent unbounded growth
        self._MAX_BUFFER_ENTRIES = 1000

    async def handle_message(self, request: AgentRequest) -> None:
        context = request.context

        try:
            client = await self.session_handler.get_or_create_claude_session(context)

            await client.query(
                request.message, session_id=request.composite_session_id
            )
            logger.info(
                f"Sent message to Claude for session {request.composite_session_id}"
            )

            await self._delete_ack(context, request)

            if (
                request.composite_session_id not in self.receiver_tasks
                or self.receiver_tasks[request.composite_session_id].done()
            ):
                self.receiver_tasks[request.composite_session_id] = asyncio.create_task(
                    self._receive_messages(
                        client, request.base_session_id, request.working_path, context
                    )
                )
        except Exception as e:
            logger.error(f"Error processing Claude message: {e}", exc_info=True)
            await self.session_handler.handle_session_error(
                request.composite_session_id, context, e
            )
        finally:
            await self._delete_ack(context, request)

    async def clear_sessions(self, settings_key: str) -> int:
        """Clear Claude sessions scoped to the provided settings key."""
        # First, cleanup any stale buffers
        await self._cleanup_stale_buffers()

        settings = self.settings_manager.get_user_settings(settings_key)
        claude_map = settings.session_mappings.get(self.name, {})
        session_bases_to_clear = set(claude_map.keys())

        self.settings_manager.clear_agent_sessions(settings_key, self.name)

        sessions_to_clear = []
        for session_key in list(self.claude_sessions.keys()):
            base_part = session_key.split(":")[0] if ":" in session_key else session_key
            if base_part in session_bases_to_clear:
                sessions_to_clear.append(session_key)

        for session_key in sessions_to_clear:
            try:
                # First, cancel and wait for any associated receiver task
                receiver_task = self.receiver_tasks.get(session_key)
                if receiver_task and not receiver_task.done():
                    receiver_task.cancel()
                    try:
                        await asyncio.wait_for(receiver_task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.debug(f"Receiver task for {session_key} cancelled or timed out")

                client = self.claude_sessions[session_key]
                if hasattr(client, "close"):
                    await client.close()
            except Exception as e:
                logger.warning(f"Error closing Claude session {session_key}: {e}")
            finally:
                self.claude_sessions.pop(session_key, None)
                self.receiver_tasks.pop(session_key, None)

        # Legacy session manager cleanup (best-effort)
        await self.session_manager.clear_session(settings_key)

        # Clear message buffers and flush tasks for cleared sessions (protected by lock)
        async with self._buffer_lock:
            for composite_key in list(self._pending_messages.keys()):
                # composite_key format: base_session_id:working_path
                base_part = composite_key.split(":")[0] if ":" in composite_key else composite_key
                if base_part in session_bases_to_clear:
                    del self._pending_messages[composite_key]
                    logger.debug(f"Cleared pending messages for {composite_key}")

            for composite_key, task in list(self._flush_tasks.items()):
                base_part = composite_key.split(":")[0] if ":" in composite_key else composite_key
                if base_part in session_bases_to_clear:
                    if task and not task.done():
                        task.cancel()
                    del self._flush_tasks[composite_key]
                    logger.debug(f"Cancelled flush task for {composite_key}")

        # Clear assistant text cache
        for composite_key in list(self._last_assistant_text.keys()):
            base_part = composite_key.split(":")[0] if ":" in composite_key else composite_key
            if base_part in session_bases_to_clear:
                del self._last_assistant_text[composite_key]

        return len(sessions_to_clear) or len(session_bases_to_clear)

    async def handle_stop(self, request: AgentRequest) -> bool:
        composite_key = request.composite_session_id
        if composite_key not in self.claude_sessions:
            return False

        client = self.claude_sessions[composite_key]
        await self.controller.emit_agent_message(
            request.context, "notify", "🛑 Interrupting Claude session..."
        )
        try:
            if hasattr(client, "interrupt"):
                await client.interrupt()
                return True
            else:
                await self.controller.emit_agent_message(
                    request.context,
                    "notify",
                    "⚠️ This Claude session cannot be interrupted; consider /clear.",
                )
                return False
        except Exception as err:
            logger.error(f"Failed to interrupt Claude session {composite_key}: {err}")
            await self.controller.emit_agent_message(
                request.context,
                "notify",
                "⚠️ Failed to interrupt Claude session. Please try /clear.",
            )
            return False

    async def _flush_pending_messages(self, composite_key: str, context: MessageContext):
        """Flush and send all pending messages for a session."""
        async with self._buffer_lock:
            if composite_key not in self._pending_messages:
                return

            messages = self._pending_messages.pop(composite_key, [])
            if not messages:
                return

        # Group by message type and combine (outside lock to avoid holding during async send)
        by_type: dict[str, list[str]] = {}
        for msg_type, text in messages:
            if msg_type not in by_type:
                by_type[msg_type] = []
            by_type[msg_type].append(text)

        # Send each combined message
        for msg_type, texts in by_type.items():
            combined = "\n\n".join(texts)
            await self.controller.emit_agent_message(
                context, msg_type, combined, parse_mode="markdown"
            )

    async def _schedule_flush(self, composite_key: str, context: MessageContext, delay: float = 0.2):
        """Schedule a flush after delay. New messages will reset the timer."""

        async with self._buffer_lock:
            # Cancel existing flush task
            existing_task = self._flush_tasks.get(composite_key)
            if existing_task and not existing_task.done():
                existing_task.cancel()

            # Create new flush task
            async def flush_after_delay():
                try:
                    await asyncio.sleep(delay)
                    await self._flush_pending_messages(composite_key, context)
                except asyncio.CancelledError:
                    pass  # Task was cancelled by new message

            loop = asyncio.get_event_loop()
            self._flush_tasks[composite_key] = loop.create_task(flush_after_delay())

    async def _cleanup_stale_buffers(self):
        """Clean up completed/failed flush tasks and empty pending message buffers."""
        async with self._buffer_lock:
            # Clean up completed tasks
            for composite_key in list(self._flush_tasks.keys()):
                task = self._flush_tasks.get(composite_key)
                if task is None or task.done():
                    self._flush_tasks.pop(composite_key, None)

            # Clean up empty buffers
            for composite_key in list(self._pending_messages.keys()):
                if not self._pending_messages.get(composite_key):
                    self._pending_messages.pop(composite_key, None)

            # Prevent unbounded growth
            if len(self._pending_messages) > self._MAX_BUFFER_ENTRIES:
                # Remove oldest entries (first half)
                keys_to_remove = list(self._pending_messages.keys())[:self._MAX_BUFFER_ENTRIES // 2]
                for key in keys_to_remove:
                    self._pending_messages.pop(key, None)
                    # Also cancel any associated flush task
                    task = self._flush_tasks.get(key)
                    if task and not task.done():
                        task.cancel()
                    self._flush_tasks.pop(key, None)
                logger.warning(f"Buffer overflow: removed {len(keys_to_remove)} stale entries")

    async def _receive_messages(
        self,
        client,
        base_session_id: str,
        working_path: str,
        context: MessageContext,
    ):
        """Receive messages from Claude SDK client."""
        try:
            settings_key = self.controller._get_settings_key(context)
            composite_key = f"{base_session_id}:{working_path}"

            async for message in client.receive_messages():
                # Periodically clean up stale buffers (every ~100 messages)
                await self._cleanup_stale_buffers()

                try:
                    claude_session_id = self._maybe_capture_session_id(
                        message, base_session_id, working_path, settings_key
                    )
                    if claude_session_id:
                        logger.info(
                            f"Captured Claude session id {claude_session_id} for {base_session_id}"
                        )

                    if self.claude_client._is_skip_message(message):
                        continue

                    message_type = self._detect_message_type(message)
                    formatted_message = None

                    if message_type == "assistant":
                        formatted_message = self.claude_client.format_message(
                            message,
                            get_relative_path=lambda path: self.get_relative_path(
                                path, context
                            ),
                        )
                        assistant_text = self._extract_text_blocks(message)
                        # Check if assistant is hidden BEFORE saving to last_assistant_text
                        # This prevents result messages from being skipped when assistant was hidden
                        if self.settings_manager.is_message_type_hidden(
                            settings_key, message_type
                        ):
                            # Don't save assistant_text if hidden, so result won't be skipped
                            continue
                        # Only save assistant_text if it was actually shown
                        if assistant_text:
                            self._last_assistant_text[composite_key] = assistant_text
                    elif message_type == "result":
                        # Flush any pending messages before sending result
                        await self._flush_pending_messages(composite_key, context)
                        # Cancel pending flush task
                        existing_task = self._flush_tasks.get(composite_key)
                        if existing_task and not existing_task.done():
                            existing_task.cancel()

                        if self.settings_manager.is_message_type_hidden(
                            settings_key, message_type
                        ):
                            self._last_assistant_text.pop(composite_key, None)
                            continue
                        result_text = getattr(message, "result", None)
                        # Only emit result message if there's actual result content
                        # If result_text is empty and assistant wasn't hidden, the assistant
                        # message was already shown, so skip the duplicate
                        if not result_text:
                            logger.debug(f"Skipping empty result message")
                            self._last_assistant_text.pop(composite_key, None)
                            continue
                        # Skip result if it's identical to the last assistant message (avoid duplicate)
                        last_assistant = self._last_assistant_text.get(composite_key, "")
                        result_trimmed = result_text.strip()
                        last_trimmed = last_assistant.strip()

                        # Check various duplication scenarios:
                        # 1. Exact match
                        if result_trimmed == last_trimmed:
                            logger.debug(f"Skipping result message (exact match with assistant)")
                            self._last_assistant_text.pop(composite_key, None)
                            continue
                        # 2. Result starts with assistant text (result = assistant + extra)
                        if last_trimmed and result_trimmed.startswith(last_trimmed):
                            extra_content = result_trimmed[len(last_trimmed):].strip()
                            if not extra_content or len(extra_content) < 50:
                                logger.debug(f"Skipping result message (assistant is prefix, extra: {len(extra_content)} chars)")
                                self._last_assistant_text.pop(composite_key, None)
                                continue
                        # 3. Assistant ends with result text (assistant = process + result)
                        # This is the common case: assistant shows tool calls + final result,
                        # and result only shows the final result again
                        if last_trimmed and last_trimmed.endswith(result_trimmed):
                            preceding_content = last_trimmed[:-len(result_trimmed)].strip()
                            # Check if the preceding content is substantial (tool calls, etc.)
                            # If assistant is significantly longer than result, it likely contains process info
                            if len(last_trimmed) > len(result_trimmed) * 1.5:  # Assistant is 50%+ longer
                                logger.debug(f"Skipping result message (result is suffix of assistant, assistant has {len(preceding_content)} chars of preceding content)")
                                self._last_assistant_text.pop(composite_key, None)
                                continue
                        suffix = "---" if self.config.platform == "slack" else None
                        await self.emit_result_message(
                            context,
                            result_text,
                            subtype=getattr(message, "subtype", "") or "",
                            duration_ms=getattr(message, "duration_ms", 0),
                            parse_mode="markdown",
                            suffix=suffix,
                        )
                        self._last_assistant_text.pop(composite_key, None)
                        continue
                    else:
                        if message_type and self.settings_manager.is_message_type_hidden(
                            settings_key, message_type
                        ):
                            if message_type == "result":
                                self._last_assistant_text.pop(composite_key, None)
                            continue
                        formatted_message = self.claude_client.format_message(
                            message,
                            get_relative_path=lambda path: self.get_relative_path(
                                path, context
                            ),
                        )
                    if not formatted_message or not formatted_message.strip():
                        continue

                    if self.config.platform == "slack":
                        formatted_message = formatted_message + "\n---"

                    # Buffer the message and schedule delayed send (protected by lock)
                    async with self._buffer_lock:
                        if composite_key not in self._pending_messages:
                            self._pending_messages[composite_key] = []
                        self._pending_messages[composite_key].append(
                            (message_type or "assistant", formatted_message)
                        )

                    # Schedule flush after delay (new messages reset timer)
                    await self._schedule_flush(composite_key, context)

                except Exception as e:
                    logger.error(
                        f"Error processing message from Claude: {e}", exc_info=True
                    )
                    continue

            # Flush any remaining pending messages when stream ends
            await self._flush_pending_messages(composite_key, context)

        except Exception as e:
            composite_key = f"{base_session_id}:{working_path}"
            logger.error(
                f"Error in Claude receiver for session {composite_key}: {e}",
                exc_info=True,
            )
            # Flush pending messages on error
            await self._flush_pending_messages(composite_key, context)
            await self.session_handler.handle_session_error(composite_key, context, e)

    async def _delete_ack(self, context: MessageContext, request: AgentRequest):
        ack_id = request.ack_message_id
        if ack_id and hasattr(self.im_client, "delete_message"):
            try:
                await self.im_client.delete_message(context.channel_id, ack_id)
            except Exception as err:
                logger.debug(f"Could not delete ack message: {err}")
            finally:
                request.ack_message_id = None

    def get_relative_path(
        self, abs_path: str, context: Optional[MessageContext] = None
    ) -> str:
        """Convert absolute path to relative path from working directory."""
        try:
            cwd = self.session_handler.get_working_path(context)
            abs_path = os.path.abspath(os.path.expanduser(abs_path))
            rel_path = os.path.relpath(abs_path, cwd)
            if rel_path.startswith("../.."):
                return abs_path
            return rel_path
        except Exception:
            return abs_path

    def _get_target_context(self, context: MessageContext) -> MessageContext:
        """Return context for sending messages (respect Slack thread replies)."""
        if self.im_client.should_use_thread_for_reply() and context.thread_id:
            return MessageContext(
                user_id=context.user_id,
                channel_id=context.channel_id,
                thread_id=context.thread_id,
                message_id=context.message_id,
                platform_specific=context.platform_specific,
            )
        return context

    def _maybe_capture_session_id(
        self,
        message,
        base_session_id: str,
        working_path: str,
        settings_key: str,
    ) -> Optional[str]:
        """Capture session id from system init messages."""
        if (
            hasattr(message, "__class__")
            and message.__class__.__name__ == "SystemMessage"
            and getattr(message, "subtype", None) == "init"
            and getattr(message, "data", None)
        ):
            session_id = message.data.get("session_id")
            if session_id:
                self.session_handler.capture_session_id(
                    base_session_id, working_path, session_id, settings_key
                )
                return session_id
        return None

    def _extract_text_blocks(self, message) -> str:
        """Extract text-only content blocks for result fallbacks."""
        parts = []
        for block in getattr(message, "content", []) or []:
            if isinstance(block, TextBlock):
                text = block.text.strip() if block.text else ""
                if text:
                    parts.append(self.claude_client.formatter.escape_special_chars(text))
        return "\n\n".join(parts).strip()

    def _detect_message_type(self, message) -> Optional[str]:
        """Infer message type name from Claude SDK class."""
        if not hasattr(message, "__class__"):
            return None
        class_name = message.__class__.__name__
        mapping = {
            "SystemMessage": "system",
            "UserMessage": "user",
            "AssistantMessage": "assistant",
            "ResultMessage": "result",
        }
        return mapping.get(class_name)
