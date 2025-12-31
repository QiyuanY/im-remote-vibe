"""Qoder CLI integration via qodercli non-interactive mode."""

import asyncio
import hashlib
import json
import logging
import os
import signal
from asyncio.subprocess import Process
from typing import Dict, Optional, Tuple

from markdown_to_mrkdwn import SlackMarkdownConverter

from modules.agents.base import AgentRequest, BaseAgent

logger = logging.getLogger(__name__)

STREAM_BUFFER_LIMIT = 8 * 1024 * 1024  # 8MB cap for Qoder stdout/stderr streams


class QoderAgent(BaseAgent):
    """Qoder CLI integration via qodercli streaming mode.

    Qoder CLI supports:
    - Non-interactive mode: qodercli -p "prompt"
    - Working directory: qodercli -w /path/to/project
    - JSON output: qodercli -f json or -f stream-json
    - Session resume: qodercli -r <session_id>
    """

    name = "qoder"

    def __init__(self, controller, qoder_config):
        super().__init__(controller)
        self.qoder_config = qoder_config
        self.active_processes: Dict[str, Tuple[Process, str]] = {}
        self.base_process_index: Dict[str, str] = {}
        self.composite_to_base: Dict[str, str] = {}
        self._initialized_sessions: set[str] = set()
        self._slack_markdown_converter = (
            SlackMarkdownConverter()
            if getattr(self.controller.config, "platform", None) == "slack"
            else None
        )
        # Track sent messages to avoid duplicates from qoder's repeated events
        self._sent_message_hashes: Dict[str, set] = {}

    async def handle_message(self, request: AgentRequest) -> None:
        # Initialize message hash set for this session
        self._sent_message_hashes[request.composite_session_id] = set()

        # Handle concurrent task for the same base session
        existing = self.base_process_index.get(request.base_session_id)
        if existing and existing in self.active_processes:
            await self.controller.emit_agent_message(
                request.context,
                "notify",
                "⚠️ Qoder is already processing a task in this thread. "
                "Cancelling the previous run...",
            )
            await self._terminate_process(existing)
            await self.controller.emit_agent_message(
                request.context,
                "notify",
                "⏹ Previous Qoder task cancelled. Starting the new request...",
            )

        # Get resume session ID if available
        resume_id = self.settings_manager.get_agent_session_id(
            request.settings_key,
            request.base_session_id,
            request.working_path,
            agent_name=self.name,
        )

        # Ensure working directory exists
        if not os.path.exists(request.working_path):
            os.makedirs(request.working_path, exist_ok=True)

        cmd = self._build_command(request, resume_id)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=request.working_path,
                limit=STREAM_BUFFER_LIMIT,
                **({"preexec_fn": os.setsid} if hasattr(os, "setsid") else {}),
            )
        except FileNotFoundError:
            await self.controller.emit_agent_message(
                request.context,
                "notify",
                "❌ Qoder CLI not found. Please install it or set QODER_CLI_PATH.",
            )
            return
        except Exception as e:
            logger.error(f"Failed to launch Qoder CLI: {e}", exc_info=True)
            await self.controller.emit_agent_message(
                request.context, "notify", f"❌ Failed to start Qoder CLI: {e}"
            )
            return

        await self._delete_ack(request)

        self.active_processes[request.composite_session_id] = (
            process,
            request.settings_key,
        )
        self.base_process_index[request.base_session_id] = request.composite_session_id
        self.composite_to_base[request.composite_session_id] = request.base_session_id
        logger.info(
            f"Qoder session {request.composite_session_id} started (pid={process.pid})"
        )

        stdout_task = asyncio.create_task(
            self._consume_stdout(process, request)
        )
        stderr_task = asyncio.create_task(
            self._consume_stderr(process, request)
        )

        try:
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
        finally:
            self._unregister_process(request.composite_session_id)
            # Clean up message hash set for this session
            self._sent_message_hashes.pop(request.composite_session_id, None)

        if process.returncode != 0:
            await self.controller.emit_agent_message(
                request.context,
                "notify",
                "⚠️ Qoder exited with a non-zero status. Review stderr for details.",
            )

    async def clear_sessions(self, settings_key: str) -> int:
        self.settings_manager.clear_agent_sessions(settings_key, self.name)
        # Terminate any active processes scoped to this settings key
        terminated = 0
        for key, (_, stored_key) in list(self.active_processes.items()):
            if stored_key == settings_key:
                await self._terminate_process(key)
                terminated += 1
        return terminated

    async def handle_stop(self, request: AgentRequest) -> bool:
        key = request.composite_session_id
        if not await self._terminate_process(key):
            key = self.base_process_index.get(request.base_session_id)
            if not key or not await self._terminate_process(key):
                return False
        await self.controller.emit_agent_message(
            request.context, "notify", "🛑 Terminated Qoder execution."
        )
        logger.info(f"Qoder session {key} terminated via /stop")
        return True

    def _unregister_process(self, composite_key: str):
        self.active_processes.pop(composite_key, None)
        base_id = self.composite_to_base.pop(composite_key, None)
        if base_id and self.base_process_index.get(base_id) == composite_key:
            self.base_process_index.pop(base_id, None)

    async def _terminate_process(self, composite_key: str) -> bool:
        entry = self.active_processes.get(composite_key)
        if not entry:
            return False

        proc, _ = entry
        try:
            if hasattr(os, "getpgid"):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass

        self._unregister_process(composite_key)
        return True

    def _build_command(self, request: AgentRequest, resume_id: Optional[str]) -> list:
        """Build qodercli command for the request."""
        cmd = [self.qoder_config.binary]

        # Working directory
        cmd += ["-w", request.working_path]

        # Non-interactive mode with prompt
        cmd += ["-p", request.message]

        # Stream JSON output format
        cmd += ["-f", "stream-json"]

        # Quiet mode (no spinner)
        cmd += ["-q"]

        # Model selection if specified
        if self.qoder_config.default_model:
            cmd += ["--model", self.qoder_config.default_model]

        # Extra args from config
        if self.qoder_config.extra_args:
            cmd += self.qoder_config.extra_args

        # Resume session if available
        # NOTE: Skip resume if working path contains non-ASCII characters due to qoder bug
        # where path sanitization is inconsistent between session creation and resume
        should_resume = resume_id and request.working_path.isascii()
        if should_resume:
            cmd += ["-r", resume_id]
        elif resume_id and not request.working_path.isascii():
            logger.warning(
                f"Skipping session resume due to non-ASCII characters in path: {request.working_path}. "
                "This is a workaround for qoder CLI bug with non-ASCII path handling."
            )

        logger.info(f"Executing Qoder command: {' '.join(cmd)}")
        return cmd

    async def _consume_stdout(self, process: Process, request: AgentRequest):
        """Consume and parse JSON events from Qoder stdout."""
        assert process.stdout is not None
        try:
            while True:
                try:
                    line = await process.stdout.readline()
                except (asyncio.LimitOverrunError, ValueError) as err:
                    await self._notify_stream_error(
                        request, f"Qoder 输出过长导致流解码失败：{err}"
                    )
                    logger.exception("Qoder stdout exceeded buffer limit")
                    break
                if not line:
                    break
                line = line.decode().strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug(f"Qoder emitted non-JSON line: {line}")
                    # Try to handle as plain text
                    await self.controller.emit_agent_message(
                        request.context, "assistant", line, parse_mode="text"
                    )
                    continue
                await self._handle_event(event, request)
        except Exception as err:
            await self._notify_stream_error(
                request, f"Qoder stdout 读取异常：{err}"
            )
            logger.exception("Unexpected Qoder stdout error")

    async def _consume_stderr(self, process: Process, request: AgentRequest):
        """Consume stderr from Qoder process."""
        assert process.stderr is not None
        buffer = []
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            decoded = line.decode(errors="ignore").rstrip()
            buffer.append(decoded)
            logger.debug(f"Qoder stderr: {decoded}")

        if buffer:
            joined = "\n".join(buffer[-10:])
            await self.controller.emit_agent_message(
                request.context,
                "notify",
                f"❗️ Qoder stderr:\n```stderr\n{joined}\n```",
                parse_mode="markdown",
            )

    async def _handle_event(
        self, event: Dict, request: AgentRequest
    ):
        """Handle a JSON event from Qoder stream.

        Qoder JSON format examples:
        {"type":"system","subtype":"init","session_id":"...","tools":[...]}
        {"type":"assistant","subtype":"message","message":{"content":[...]}}
        {"type":"result","subtype":"success",...}
        """
        event_type = event.get("type")
        subtype = event.get("subtype", "")

        # System/Init event - capture session and send system message
        if event_type == "system":
            session_id = event.get("session_id")
            if session_id:
                self.settings_manager.set_agent_session_mapping(
                    request.settings_key,
                    self.name,
                    request.base_session_id,
                    request.working_path,
                    session_id,
                )
            session_key = request.composite_session_id
            if session_key not in self._initialized_sessions:
                self._initialized_sessions.add(session_key)
                # Send system message with tools info if available
                tools = event.get("tools", [])
                tools_text = ""
                if tools:
                    tools_text = f"\n🔧 Available tools: {', '.join(tools[:10])}"
                    if len(tools) > 10:
                        tools_text += f" and {len(tools) - 10} more"
                system_text = self.im_client.formatter.format_system_message(
                    request.working_path, "init", session_id
                )
                if self.config.platform == "slack":
                    system_text = system_text + "\n---"
                parse_mode = None if self._slack_markdown_converter else "markdown"
                await self.controller.emit_agent_message(
                    request.context,
                    "system",
                    system_text + tools_text,
                    parse_mode=parse_mode,
                )
            return

        # User message event (echo of user's message)
        if event_type == "user" and subtype == "message":
            # User message echo - typically contains the user's message text
            # We can choose to display it or ignore it
            message = event.get("message", {})
            if message:
                content_list = message.get("content", [])
                text_parts = []
                for content_item in content_list:
                    if content_item.get("type") == "text":
                        text_parts.append(content_item.get("text", ""))
                text = "\n".join(text_parts) if text_parts else str(message)

                if text:
                    # Optionally send user message echo
                    # For now, we'll skip it to avoid showing the message twice
                    logger.debug(f"Qoder user message echo: {text[:50]}...")
            return

        # Assistant message event
        if event_type == "assistant" and subtype == "message":
            message = event.get("message", {})
            if message:
                # Extract content from message
                content_list = message.get("content", [])
                text_parts = []
                tool_calls = []

                for content_item in content_list:
                    item_type = content_item.get("type")

                    # Text content
                    if item_type == "text":
                        text_parts.append(content_item.get("text", ""))

                    # Function call content
                    elif item_type == "function":
                        func_name = content_item.get("name", "")
                        func_input = content_item.get("input", "{}")
                        finished = content_item.get("finished", False)

                        # Format tool call
                        if func_name:
                            if finished:
                                # Completed tool call - show the input/result
                                try:
                                    input_data = json.loads(func_input) if isinstance(func_input, str) else func_input
                                    if isinstance(input_data, dict):
                                        # Format as tool output
                                        command = input_data.get("command", "")
                                        description = input_data.get("description", "")
                                        if command and description:
                                            tool_calls.append(f"🔧 `{command}` - {description}")
                                        elif command:
                                            tool_calls.append(f"🔧 `{command}`")
                                        else:
                                            tool_calls.append(f"🔧 {func_name}")
                                    else:
                                        tool_calls.append(f"🔧 {func_name}: {func_input}")
                                except json.JSONDecodeError:
                                    tool_calls.append(f"🔧 {func_name}")
                            else:
                                # Tool call in progress
                                tool_calls.append(f"⏳ {func_name}...")

                # Combine text and tool calls
                text = "\n".join(text_parts) if text_parts else ""
                if tool_calls:
                    if text:
                        text = text + "\n\n" + "\n".join(tool_calls)
                    else:
                        text = "\n".join(tool_calls)

                if text:
                    # Use message hash to avoid duplicates (qoder sometimes sends same event twice)
                    text_hash = hashlib.md5(text.encode()).hexdigest()
                    session_id = request.composite_session_id

                    if session_id not in self._sent_message_hashes:
                        self._sent_message_hashes[session_id] = set()

                    if text_hash not in self._sent_message_hashes[session_id]:
                        self._sent_message_hashes[session_id].add(text_hash)
                        parse_mode = None if self._slack_markdown_converter else "markdown"
                        await self.controller.emit_agent_message(
                            request.context, "assistant", text, parse_mode=parse_mode
                        )
                        (
                            request.last_agent_message,
                            request.last_agent_message_parse_mode,
                        ) = self._prepare_last_message_payload(text)
                    else:
                        logger.debug(f"Skipping duplicate message (hash: {text_hash[:8]}...)")
            return

        # Result event - final success/failure
        # Note: Qoder sends duplicate result events, so we only process the first one per session
        if event_type == "result":
            if subtype == "success":
                # Don't re-send the message since it was already sent in assistant event
                # Just clear the cached message to prepare for next turn
                request.last_agent_message = None
                request.last_agent_message_parse_mode = None
            elif subtype == "error":
                error_message = event.get("message", {}).get("error", "Unknown error")
                await self.controller.emit_agent_message(
                    request.context, "notify", f"❌ Qoder error: {error_message}"
                )
                request.last_agent_message = None
                request.last_agent_message_parse_mode = None
            return

        # Generic text content (for debugging unknown events)
        logger.debug(f"Unhandled Qoder event type: {event_type}, subtype: {subtype}")
        return

    async def _delete_ack(self, request: AgentRequest):
        ack_id = request.ack_message_id
        if ack_id and hasattr(self.im_client, "delete_message"):
            try:
                await self.im_client.delete_message(
                    request.context.channel_id, ack_id
                )
            except Exception as err:
                logger.debug(f"Could not delete ack message: {err}")
            finally:
                request.ack_message_id = None

    def _prepare_last_message_payload(
        self, text: str
    ) -> Tuple[str, Optional[str]]:
        """Prepare cached assistant text for reuse in result messages."""
        if self._slack_markdown_converter:
            return self._slack_markdown_converter.convert(text), None
        return text, "markdown"

    async def _notify_stream_error(self, request: AgentRequest, message: str) -> None:
        """Emit a notify message when Qoder stdout handling fails."""
        await self.controller.emit_agent_message(
            request.context,
            "notify",
            f"⚠️ {message}\n请查看 `logs/vibe_remote.log` 获取更多细节。",
        )
