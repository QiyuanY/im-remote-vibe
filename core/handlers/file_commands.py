"""
File operation commands - handle file and directory related operations.

Commands included:
- /run <cmd> - Execute shell command
- /ls [path] - List directory contents
- @@ - Switch to project root directory
"""

import os
import logging
import subprocess
from datetime import datetime
from modules.im import MessageContext
from .error_handler import handle_error, format_user_error

logger = logging.getLogger(__name__)


class FileCommands:
    """Handles file and directory operations"""

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

    async def handle_run(self, context: MessageContext, args: str = ""):
        """Handle /run command - execute shell command"""
        try:
            if not args or not args.strip():
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(
                    channel_context, "Usage: /run <command>"
                )
                return

            command = args.strip()
            formatter = self.im_client.formatter

            # Validate command for dangerous patterns
            is_safe, warning = self.controller.error_handler.validate_command_input(
                command, formatter
            )
            if not is_safe:
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, warning)
                return

            # Get working directory for this context
            cwd = self.controller.get_cwd(context)

            # Execute command
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                # Build response
                lines = [
                    formatter.format_bold("Command Result"),
                    f"Command: {formatter.format_code_inline(command)}",
                    f"Exit Code: {formatter.format_code_inline(str(result.returncode))}",
                ]

                # Add stdout if present
                if result.stdout:
                    stdout_lines = result.stdout.strip().split('\n')
                    if len(stdout_lines) > 50:
                        stdout_preview = '\n'.join(stdout_lines[:50])
                        stdout_preview += f"\n... ({len(stdout_lines) - 50} more lines)"
                    else:
                        stdout_preview = result.stdout.strip()
                    lines.append("")
                    lines.append(formatter.format_bold("Output:"))
                    lines.append(formatter.format_code_block(stdout_preview))

                # Add stderr if present
                if result.stderr:
                    lines.append("")
                    lines.append(formatter.format_bold("Errors:"))
                    stderr_preview = result.stderr.strip()
                    if len(stderr_preview) > 1000:
                        stderr_preview = stderr_preview[:1000] + "..."
                    lines.append(formatter.format_code_block(stderr_preview))

                message_text = formatter.format_message(*lines)
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, message_text)

            except subprocess.TimeoutExpired:
                channel_context = self._get_channel_context(context)
                error_msg = format_user_error(
                    "Command timed out after 30 seconds",
                    formatter
                )
                await self.im_client.send_message(channel_context, error_msg)

            except FileNotFoundError as e:
                channel_context = self._get_channel_context(context)
                error_msg = handle_error(e, formatter, "Command execution")
                await self.im_client.send_message(channel_context, error_msg)

            except PermissionError as e:
                channel_context = self._get_channel_context(context)
                error_msg = handle_error(e, formatter, "Command execution")
                await self.im_client.send_message(channel_context, error_msg)

        except Exception as e:
            logger.error(f"Error in handle_run: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            error_msg = format_user_error(str(e), self.im_client.formatter)
            await self.im_client.send_message(channel_context, error_msg)

    async def handle_ls(self, context: MessageContext, args: str = ""):
        """Handle /ls command - list directory contents"""
        try:
            formatter = self.im_client.formatter

            # Get target path
            target_path = args.strip() if args.strip() else None

            # Get working directory for this context
            cwd = self.controller.get_cwd(context)

            if target_path:
                expanded = os.path.expanduser(target_path)
                if not os.path.isabs(expanded):
                    target_path = os.path.join(cwd, expanded)
                else:
                    target_path = expanded
            else:
                target_path = cwd

            target_path = os.path.abspath(target_path)

            # Check if path exists
            if not os.path.exists(target_path):
                channel_context = self._get_channel_context(context)
                error_msg = self.controller.error_handler.handle_path_error(
                    target_path, "list directory", formatter
                )
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Check if it's a directory
            if not os.path.isdir(target_path):
                stat = os.stat(target_path)
                size = stat.st_size
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

                lines = [
                    formatter.format_bold("File Info"),
                    f"Path: {formatter.format_code_inline(target_path)}",
                    f"Size: {formatter.format_code_inline(f'{size} bytes')}",
                    f"Modified: {formatter.format_code_inline(mtime)}",
                ]
                message_text = formatter.format_message(*lines)
                channel_context = self._get_channel_context(context)
                await self.im_client.send_message(channel_context, message_text)
                return

            # List directory contents
            try:
                entries = sorted(os.listdir(target_path))
            except PermissionError:
                channel_context = self._get_channel_context(context)
                error_msg = handle_error(
                    PermissionError(f"Permission denied: {target_path}"),
                    formatter
                )
                await self.im_client.send_message(channel_context, error_msg)
                return

            # Separate directories and files
            dirs = []
            files = []

            for entry in entries:
                entry_path = os.path.join(target_path, entry)
                if os.path.isdir(entry_path):
                    dirs.append(entry + "/")
                else:
                    files.append(entry)

            # Build response
            lines = [
                formatter.format_bold("Directory Listing"),
                f"Path: {formatter.format_code_inline(target_path)}",
            ]

            total_dirs = len(dirs)
            total_files = len(files)

            if dirs:
                lines.append("")
                lines.append(formatter.format_bold(f"Directories ({total_dirs}):"))
                for d in dirs[:20]:
                    lines.append(f"📁 {formatter.format_text(d, safe=True)}")
                if len(dirs) > 20:
                    lines.append(f"... and {len(dirs) - 20} more directories")

            if files:
                lines.append("")
                lines.append(formatter.format_bold(f"Files ({total_files}):"))
                for f in files[:30]:
                    lines.append(f"📄 {formatter.format_text(f, safe=True)}")
                if len(files) > 30:
                    lines.append(f"... and {len(files) - 30} more files")

            message_text = formatter.format_message(*lines)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, message_text)

        except Exception as e:
            logger.error(f"Error in handle_ls: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            error_msg = handle_error(e, self.im_client.formatter, "Listing directory")
            await self.im_client.send_message(channel_context, error_msg)

    async def handle_at_at(self, context: MessageContext, args: str = ""):
        """Handle @@ command - switch to project root directory"""
        try:
            default_cwd = os.path.abspath(os.path.expanduser(self.config.claude.cwd))

            if not os.path.exists(default_cwd):
                formatter = self.im_client.formatter
                channel_context = self._get_channel_context(context)
                error_msg = self.controller.error_handler.handle_path_error(
                    default_cwd, "switch to project root", formatter
                )
                await self.im_client.send_message(channel_context, error_msg)
                return

            settings_key = self.controller._get_settings_key(context)
            self.settings_manager.set_custom_cwd(settings_key, default_cwd)

            formatter = self.im_client.formatter
            lines = [
                formatter.format_bold("Switched to Project Root"),
                "",
                f"Working directory: {formatter.format_code_inline(default_cwd)}",
                "",
                formatter.format_text("All commands will now execute in this directory."),
            ]
            message_text = formatter.format_message(*lines)
            channel_context = self._get_channel_context(context)
            await self.im_client.send_message(channel_context, message_text)

            logger.info(f"User {context.user_id} switched to project root: {default_cwd}")

        except Exception as e:
            logger.error(f"Error in handle_at_at: {e}", exc_info=True)
            channel_context = self._get_channel_context(context)
            error_msg = handle_error(e, self.im_client.formatter, "Switching directory")
            await self.im_client.send_message(channel_context, error_msg)
