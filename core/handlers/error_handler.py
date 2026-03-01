"""
Intelligent Error Handler with user-friendly error messages and solutions.

Provides categorized error handling with actionable suggestions for common issues.
"""

import logging
import os
import subprocess
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Error categories for intelligent handling"""
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    NETWORK = "network"
    TIMEOUT = "timeout"
    SYNTAX = "syntax"
    RESOURCE = "resource"
    AUTH = "auth"
    UNKNOWN = "unknown"


class ErrorSolution:
    """Represents an error with its solution"""

    def __init__(
        self,
        title: str,
        description: str,
        suggestions: list[str],
        category: ErrorCategory = ErrorCategory.UNKNOWN,
    ):
        self.title = title
        self.description = description
        self.suggestions = suggestions
        self.category = category


class IntelligentErrorHandler:
    """
    Intelligent error handler that provides user-friendly error messages
    with actionable solutions.
    """

    # Error patterns and their solutions
    ERROR_PATTERNS: Dict[str, ErrorSolution] = {
        # Permission errors
        "Permission denied": ErrorSolution(
            title="Permission Denied",
            description="You don't have permission to access this resource.",
            suggestions=[
                "• Check if you have read/write permissions for the file/directory",
                "• Try using `sudo` if you need elevated privileges (use with caution)",
                "• Check file ownership with `ls -la <path>`",
                "• Contact your administrator if you need access",
            ],
            category=ErrorCategory.PERMISSION,
        ),
        "Access denied": ErrorSolution(
            title="Access Denied",
            description="Access to this resource is restricted.",
            suggestions=[
                "• Verify you have the necessary credentials",
                "• Check if you're authorized to access this resource",
                "• Try re-authenticating if your session may have expired",
            ],
            category=ErrorCategory.PERMISSION,
        ),
        # Not found errors
        "No such file": ErrorSolution(
            title="File Not Found",
            description="The specified file or directory doesn't exist.",
            suggestions=[
                "• Check the path is correct with `/ls` to see available files",
                "• Use `@@` to switch to project root directory",
                "• Try `/set_cwd <path>` to change to a valid directory",
                "• Use tab completion or wildcards for partial matches",
            ],
            category=ErrorCategory.NOT_FOUND,
        ),
        "does not exist": ErrorSolution(
            title="Path Not Found",
            description="The specified path doesn't exist.",
            suggestions=[
                "• Verify the path is spelled correctly",
                "• Use `/ls` to browse the current directory",
                "• Check if you're in the right directory with `/cwd`",
                "• Use absolute paths if relative paths aren't working",
            ],
            category=ErrorCategory.NOT_FOUND,
        ),
        "command not found": ErrorSolution(
            title="Command Not Found",
            description="The shell command you're trying to run isn't available.",
            suggestions=[
                "• Check if the command is installed with `which <command>`",
                "• Install the missing package (e.g., `brew install <package>` on macOS)",
                "• Check your PATH variable with `echo $PATH`",
                "• Try using the full path to the executable",
            ],
            category=ErrorCategory.NOT_FOUND,
        ),
        # Network errors
        "Connection refused": ErrorSolution(
            title="Connection Refused",
            description="Cannot connect to the remote service.",
            suggestions=[
                "• Check if the service is running",
                "• Verify the hostname and port are correct",
                "• Check your firewall settings",
                "• Try again later if the service might be temporarily down",
            ],
            category=ErrorCategory.NETWORK,
        ),
        "Timeout": ErrorSolution(
            title="Request Timeout",
            description="The request took too long to complete.",
            suggestions=[
                "• The operation may be taking longer than expected",
                "• Check your network connection",
                "• Try breaking the operation into smaller chunks",
                "• Current timeout is 30 seconds for /run commands",
            ],
            category=ErrorCategory.TIMEOUT,
        ),
        "timed out": ErrorSolution(
            title="Operation Timeout",
            description="The operation exceeded the time limit.",
            suggestions=[
                "• The command may be processing a large amount of data",
                "• Try running with less data or different parameters",
                "• For long-running tasks, consider running them directly in a terminal",
                "• Use `nohup` or background tasks for long operations",
            ],
            category=ErrorCategory.TIMEOUT,
        ),
        # Syntax errors
        "Invalid syntax": ErrorSolution(
            title="Syntax Error",
            description="The command has invalid syntax.",
            suggestions=[
                "• Check the command format with `/help` or `/start`",
                "• Ensure arguments are properly quoted",
                "• For /run: use `/run <your shell command>`",
                "• For /set_cwd: use `/set_cwd <path>`",
            ],
            category=ErrorCategory.SYNTAX,
        ),
        "usage": ErrorSolution(
            title="Usage Error",
            description="The command was not used correctly.",
            suggestions=[
                "• Check the correct format with `/start` for all commands",
                "• Examples: `/run ls -la`, `/ls /tmp`, `/set_cwd ~/projects`",
                "• Use `/help` to see detailed command documentation",
            ],
            category=ErrorCategory.SYNTAX,
        ),
        # Resource errors
        "Disk full": ErrorSolution(
            title="Disk Full",
            description="Not enough disk space to complete the operation.",
            suggestions=[
                "• Check disk usage with `/run df -h`",
                "• Clean up temporary files with `/run rm -rf /tmp/*`",
                "• Remove unnecessary files or move to another disk",
                "• Check disk space with `/run du -sh ~`",
            ],
            category=ErrorCategory.RESOURCE,
        ),
        "Out of memory": ErrorSolution(
            title="Out of Memory",
            description="The system doesn't have enough memory.",
            suggestions=[
                "• Check memory usage with `/status`",
                "• Close unnecessary applications",
                "• Try processing smaller chunks of data",
                "• Restart the service if memory is leaking",
            ],
            category=ErrorCategory.RESOURCE,
        ),
        # Authentication errors
        "Authentication failed": ErrorSolution(
            title="Authentication Failed",
            description="Invalid credentials or authentication error.",
            suggestions=[
                "• Check your API token or credentials",
                "• Verify the token hasn't expired",
                "• Re-authenticate if needed",
                "• Check your account status",
            ],
            category=ErrorCategory.AUTH,
        ),
        "Unauthorized": ErrorSolution(
            title="Unauthorized Access",
            description="You don't have permission to perform this action.",
            suggestions=[
                "• Check if your account has the required permissions",
                "• Contact your administrator for access",
                "• Verify you're using the correct account",
            ],
            category=ErrorCategory.AUTH,
        ),
    }

    @classmethod
    def classify_error(cls, error_message: str) -> ErrorCategory:
        """Classify an error into a category"""
        error_lower = error_message.lower()

        for pattern, solution in cls.ERROR_PATTERNS.items():
            if pattern.lower() in error_lower:
                return solution.category

        # Additional classification
        if any(word in error_lower for word in ["permission", "denied", "forbidden"]):
            return ErrorCategory.PERMISSION
        if any(word in error_lower for word in ["not found", "no such", "doesn't exist"]):
            return ErrorCategory.NOT_FOUND
        if any(word in error_lower for word in ["timeout", "timed out"]):
            return ErrorCategory.TIMEOUT
        if any(word in error_lower for word in ["connection", "network", "refused"]):
            return ErrorCategory.NETWORK
        if any(word in error_lower for word in ["syntax", "invalid", "usage"]):
            return ErrorCategory.SYNTAX
        if any(word in error_lower for word in ["disk", "memory", "space"]):
            return ErrorCategory.RESOURCE
        if any(word in error_lower for word in ["auth", "unauthorized", "token"]):
            return ErrorCategory.AUTH

        return ErrorCategory.UNKNOWN

    @classmethod
    def get_solution(cls, error_message: str) -> Optional[ErrorSolution]:
        """Get the solution for a given error message"""
        error_lower = error_message.lower()

        # Try exact pattern matches first
        for pattern, solution in cls.ERROR_PATTERNS.items():
            if pattern.lower() in error_lower:
                return solution

        # No specific solution found, return generic one
        return None

    @classmethod
    def format_error(
        cls,
        error_message: str,
        formatter,
        show_suggestions: bool = True
    ) -> str:
        """
        Format an error message with intelligent suggestions.

        Args:
            error_message: The raw error message
            formatter: Platform-specific formatter (e.g., dingtalk_formatter)
            show_suggestions: Whether to include solution suggestions

        Returns:
            Formatted error message with optional solutions
        """
        solution = cls.get_solution(error_message)

        lines = [
            formatter.format_error(error_message)
        ]

        if solution and show_suggestions:
            lines.append("")
            lines.append(formatter.format_bold(f"💡 {solution.title}"))
            lines.append(formatter.format_text(solution.description))
            lines.append("")
            lines.append(formatter.format_bold("Suggestions:"))
            for suggestion in solution.suggestions:
                lines.append(formatter.format_text(suggestion))

        return formatter.format_message(*lines)

    @classmethod
    def handle_command_error(
        cls,
        error: Exception,
        formatter,
        context: str = ""
    ) -> str:
        """
        Handle command execution errors with intelligent messaging.

        Args:
            error: The exception that occurred
            formatter: Platform-specific formatter
            context: Additional context about what operation failed

        Returns:
            Formatted error message with solutions
        """
        error_msg = str(error)
        error_type = type(error).__name__

        # Add context if provided
        if context:
            error_msg = f"{context}: {error_msg}"

        # Special handling for specific exception types
        if isinstance(error, PermissionError):
            return cls.format_error(
                f"Permission denied: {error_msg}",
                formatter
            )
        elif isinstance(error, FileNotFoundError):
            return cls.format_error(
                f"File not found: {error_msg}",
                formatter
            )
        elif isinstance(error, subprocess.TimeoutExpired):
            return cls.format_error(
                "Command timed out after 30 seconds",
                formatter
            )
        else:
            return cls.format_error(error_msg, formatter)

    @classmethod
    def handle_path_error(
        cls,
        path: str,
        operation: str,
        formatter,
        original_error: Optional[Exception] = None
    ) -> str:
        """
        Handle path-related errors with context-aware suggestions.

        Args:
            path: The problematic path
            operation: What operation was being performed
            formatter: Platform-specific formatter
            original_error: The original exception if any

        Returns:
            Formatted error message with path-specific suggestions
        """
        error_msg = f"Failed to {operation}: {path}"

        if original_error:
            error_msg = f"{error_msg} ({str(original_error)})"

        # Check if path exists
        path_exists = os.path.exists(path)

        suggestions = []

        if not path_exists:
            suggestions.append("• The path doesn't exist")
            suggestions.append("• Use `/ls` to see available files and directories")
            suggestions.append("• Check with `/cwd` to see your current directory")
        elif not os.access(path, os.R_OK):
            suggestions.append("• You don't have read permissions for this path")
            suggestions.append("• Check permissions with `ls -la <path>`")
        else:
            suggestions.append("• An unexpected error occurred")
            suggestions.append("• Try running `/status` to check system health")

        lines = [
            formatter.format_error(error_msg),
            "",
            formatter.format_bold("Suggestions:"),
        ]

        for suggestion in suggestions:
            lines.append(formatter.format_text(suggestion))

        return formatter.format_message(*lines)

    @classmethod
    def validate_command_input(
        cls,
        command: str,
        formatter,
        dangerous_commands: Optional[list[str]] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Validate command input for security issues.

        Args:
            command: The command to validate
            formatter: Platform-specific formatter
            dangerous_commands: List of commands that require warnings

        Returns:
            Tuple of (is_safe, warning_message)
        """
        dangerous = dangerous_commands or [
            "rm -rf /",
            "rm -rf /*",
            "mkfs",
            "dd if=/dev/zero",
            ":(){ :|:& };:",  # fork bomb
            "chmod 000",
        ]

        for dangerous_cmd in dangerous_commands:
            if dangerous_cmd in command.lower():
                warning = formatter.format_message(
                    formatter.format_error("⚠️ Dangerous Command Detected!"),
                    "",
                    formatter.format_bold("This command could cause serious damage:"),
                    formatter.format_code_inline(command),
                    "",
                    formatter.format_bold("If you're sure, run it directly in a terminal."),
                )
                return False, warning

        return True, None


def handle_error(
    error: Exception,
    formatter,
    context: str = "",
    show_suggestions: bool = True
) -> str:
    """
    Convenience function to handle errors with intelligent suggestions.

    Args:
        error: The exception that occurred
        formatter: Platform-specific formatter
        context: Additional context about what operation failed
        show_suggestions: Whether to include solution suggestions

    Returns:
        Formatted error message
    """
    return IntelligentErrorHandler.handle_command_error(
        error, formatter, context
    )


def format_user_error(
    error_message: str,
    formatter,
    show_suggestions: bool = True
) -> str:
    """
    Convenience function to format user-facing error messages.

    Args:
        error_message: The error message to format
        formatter: Platform-specific formatter
        show_suggestions: Whether to include solution suggestions

    Returns:
        Formatted error message
    """
    return IntelligentErrorHandler.format_error(
        error_message, formatter, show_suggestions
    )
