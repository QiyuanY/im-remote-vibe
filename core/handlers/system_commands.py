"""
System commands - handle system status and information operations.

Commands included:
- /status - Show system running status
- /history [n] - View conversation history from settings
"""

import logging
from datetime import datetime
import psutil
from modules.im import MessageContext
from modules.agents import get_agent_display_name
from .error_handler import handle_error

logger = logging.getLogger(__name__)

# Bot start time for uptime tracking
BOT_START_TIME = datetime.now()


class SystemCommands:
    """Handles system status and information commands"""

    def __init__(self, controller):
        """Initialize with reference to main controller"""
        self.controller = controller
        self.config = controller.config
        self.im_client = controller.im_client
        self.settings_manager = controller.settings_manager

    def _get_channel_context(self, context: MessageContext) -> MessageContext:
        """Get context for channel messages (no thread)"""
        if self.config.platform == "slack":
            return MessageContext(
                user_id=context.user_id,
                channel_id=context.channel_id,
                thread_id=None,
                platform_specific=context.platform_specific,
            )
        return context

    async def handle_status(self, context: MessageContext, args: str = ""):
        """Handle /status command - show service running status"""
        try:
            formatter = self.im_client.formatter

            # Calculate uptime
            uptime = datetime.now() - BOT_START_TIME
            hours, remainder = divmod(int(uptime.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {seconds}s"

            # Get system info with error handling
            try:
                cpu_percent = psutil.cpu_percent(interval=0.5)
            except Exception as e:
                logger.warning(f"Failed to get CPU info: {e}")
                cpu_percent = 0

            try:
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                memory_used = f"{memory.used / (1024**3):.2f} GB"
                memory_total = f"{memory.total / (1024**3):.2f} GB"
            except Exception as e:
                logger.warning(f"Failed to get memory info: {e}")
                memory_percent = 0
                memory_used = "N/A"
                memory_total = "N/A"

            # Count active sessions
            active_sessions = 0
            try:
                for session_id, client in list(self.controller.claude_sessions.items()):
                    if hasattr(client, 'session') and client.session:
                        active_sessions += 1
            except Exception as e:
                logger.warning(f"Failed to count sessions: {e}")

            # Count active receiver tasks
            active_tasks = 0
            try:
                active_tasks = sum(
                    1 for t in self.controller.receiver_tasks.values()
                    if not t.done()
                )
            except Exception as e:
                logger.warning(f"Failed to count tasks: {e}")

            # Get current working directory
            cwd = self.controller.get_cwd(context)

            # Build status message
            lines = [
                formatter.format_bold("System Status"),
                "",
                f"Uptime: {formatter.format_code_inline(uptime_str)}",
                "",
                formatter.format_bold("Resources:"),
                f"CPU: {formatter.format_code_inline(f'{cpu_percent}%')}",
                f"Memory: {formatter.format_code_inline(f'{memory_used} / {memory_total} ({memory_percent}%')}",
                f"Active Sessions: {formatter.format_code_inline(str(active_sessions))}",
                f"Active Tasks: {formatter.format_code_inline(str(active_tasks))}",
                "",
                formatter.format_bold("Configuration:"),
                f"Platform: {formatter.format_code_inline(self.config.platform)}",
                f"Working Dir: {formatter.format_code_inline(cwd)}",
            ]

            message_text = formatter.format_message(*lines)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, message_text)

        except Exception as e:
            logger.error(f"Error getting status: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            error_msg = handle_error(e, self.im_client.formatter, "Getting system status")
            await self.im_client.send_message(channel_context, error_msg)

    async def handle_history(self, context: MessageContext, args: str = ""):
        """Handle /history command - view conversation history from settings"""
        try:
            formatter = self.im_client.formatter

            # Parse argument for number of entries
            n = 10
            if args and args.strip().isdigit():
                n = min(int(args.strip()), 50)

            settings_key = self.controller._get_settings_key(context)
            user_settings = self.settings_manager.get_user_settings(settings_key)

            lines = [
                formatter.format_bold("Conversation History"),
                f"Session Key: {formatter.format_code_inline(settings_key)}",
                "",
            ]

            # Show session mappings
            if user_settings.session_mappings:
                lines.append(formatter.format_bold("Active Sessions:"))
                for agent_name, agent_sessions in user_settings.session_mappings.items():
                    agent_display = get_agent_display_name(agent_name)
                    lines.append(f"\n{formatter.format_code_inline(agent_display)}:")
                    for base_id, path_map in agent_sessions.items():
                        for working_path, session_id in path_map.items():
                            path_display = working_path
                            if len(path_display) > 40:
                                path_display = "..." + path_display[-37:]
                            lines.append(
                                f"  • {formatter.format_text(path_display, safe=True)}: "
                                f"{formatter.format_code_inline(session_id[:12] + '...')}"
                            )
            else:
                lines.append(formatter.format_text("No active sessions found."))

            # Show other settings info
            lines.append("")
            lines.append(formatter.format_bold("Settings:"))

            if user_settings.custom_cwd:
                cwd_display = user_settings.custom_cwd
                if len(cwd_display) > 40:
                    cwd_display = "..." + cwd_display[-37:]
                lines.append(f"Custom CWD: {formatter.format_code_inline(cwd_display)}")
            else:
                lines.append("Custom CWD: (using default)")

            if user_settings.preferred_agent:
                agent_display = get_agent_display_name(user_settings.preferred_agent)
                lines.append(f"Preferred Agent: {formatter.format_code_inline(agent_display)}")
            else:
                lines.append("Preferred Agent: (using platform default)")

            if user_settings.hidden_message_types:
                hidden_list = ", ".join(user_settings.hidden_message_types)
                lines.append(f"Hidden Types: {formatter.format_code_inline(hidden_list)}")
            else:
                lines.append("Hidden Types: (none)")

            # Show total count
            total_sessions = sum(
                len(path_map)
                for agent_map in user_settings.session_mappings.values()
                for path_map in agent_map.values()
            )
            lines.append("")
            lines.append(f"Total Sessions: {formatter.format_code_inline(str(total_sessions))}")

            message_text = formatter.format_message(*lines)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, message_text)

        except Exception as e:
            logger.error(f"Error in handle_history: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            error_msg = handle_error(e, self.im_client.formatter, "Getting history")
            await self.im_client.send_message(channel_context, error_msg)
