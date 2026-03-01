"""DingTalk (钉钉) formatter for markdown and message formatting.

DingTalk supports:
- Text messages
- Markdown messages
- ActionCard messages with buttons
- Link messages
- FeedCard messages
"""

import re
from typing import Optional, List, Any
from .base_formatter import BaseMarkdownFormatter


class DingtalkFormatter(BaseMarkdownFormatter):
    """DingTalk formatter that outputs DingTalk-compatible markdown

    DingTalk markdown format:
    - Bold: **text**
    - Italic: *text*
    - Link: [text](url)
    - Image: ![alt](url)
    - Code: `code`
    - Code blocks: ```language\ncode\n```

    Reference: https://open.dingtalk.com/document/robots/custom-robot-send-message-type
    """

    # Tool output emoji prefixes that indicate pre-formatted content
    TOOL_EMOJI_PREFIXES = ("🔧", "💻", "🔍", "📖", "✏️", "📝", "📄", "📓", "🌐", "✅", "❌", "🤖", "📂", "🔎", "🚪")

    def __init__(self):
        super().__init__()

    # ============================================================================
    # Core abstract method implementations - DingTalk Markdown
    # ============================================================================

    def format_bold(self, text: str) -> str:
        """Format bold text in DingTalk markdown"""
        return f"**{text}**"

    def format_italic(self, text: str) -> str:
        """Format italic text in DingTalk markdown"""
        return f"*{text}*"

    def format_strikethrough(self, text: str) -> str:
        """Format strikethrough text - DingTalk doesn't support this natively"""
        # DingTalk doesn't support strikethrough, return as-is
        return text

    def format_link(self, text: str, url: str) -> str:
        """Format hyperlink in DingTalk markdown"""
        return f"[{text}]({url})"

    def escape_special_chars(self, text: str) -> str:
        r"""Escape special characters for DingTalk markdown

        DingTalk requires escaping:
        - Asterisks for bold/italic: * -> \*
        - Underscores: _ -> \_
        - Backticks: ` -> \`
        """
        # Only escape if not already in a code block
        lines = []
        in_code_block = False

        for line in text.split('\n'):
            # Check for code block markers
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                lines.append(line)
                continue

            if in_code_block:
                lines.append(line)
                continue

            # Escape special markdown characters
            line = line.replace('\\', '\\\\')  # Escape backslashes first
            line = line.replace('*', '\\*')
            line = line.replace('_', '\\_')
            line = line.replace('`', '\\`')

            lines.append(line)

        return '\n'.join(lines)

    # ============================================================================
    # DingTalk-specific message formatting
    # ============================================================================

    def format_text_message(self, text: str) -> str:
        """Format a plain text message for DingTalk

        Args:
            text: Message text

        Returns:
            DingTalk formatted message
        """
        return self.format_text(text)

    def format_markdown_message(self, text: str) -> str:
        """Format a markdown message for DingTalk

        Args:
            text: Message text with markdown

        Returns:
            DingTalk formatted message
        """
        return self.format_text(text)

    def format_action_card(self, title: str, text: str,
                           btn_orientation: str = "1",
                           btn_text: str = None,
                           btn_url: str = None) -> dict:
        """Format an ActionCard message for DingTalk

        Args:
            title: Card title
            text: Card content (supports markdown)
            btn_orientation: Button orientation "0"=vertical, "1"=horizontal
            btn_text: Button text (optional)
            btn_url: Button URL (optional)

        Returns:
            DingTalk ActionCard message dict
        """
        card = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "text": text,
                "btnOrientation": btn_orientation
            }
        }

        if btn_text and btn_url:
            card["actionCard"]["btns"] = [
                {
                    "title": btn_text,
                    "actionURL": btn_url
                }
            ]

        return card

    def format_feed_card(self, title: str, text: str,
                         btn_text: str = None,
                         btn_url: str = None) -> dict:
        """Format a FeedCard message for DingTalk

        Args:
            title: Card title
            text: Card content
            btn_text: Button text (optional)
            btn_url: Button URL (optional)

        Returns:
            DingTalk FeedCard message dict
        """
        links = []
        if btn_text and btn_url:
            links.append({
                "title": btn_text,
                "messageURL": btn_url,
                "picURL": ""
            })

        return {
            "msgtype": "feedCard",
            "feedCard": {
                "title": title,
                "text": text,
                "links": links
            }
        }

    def format_link_message(self, title: str, text: str,
                          pic_url: str = "",
                          message_url: str = "") -> dict:
        """Format a link message for DingTalk

        Args:
            title: Link title
            text: Link description
            pic_url: Optional image URL
            message_url: Link target URL

        Returns:
            DingTalk link message dict
        """
        return {
            "msgtype": "link",
            "link": {
                "title": title,
                "text": text,
                "picUrl": pic_url,
                "messageUrl": message_url
            }
        }

    # ============================================================================
    # Assistant message formatting
    # ============================================================================

    def format_assistant_message(self, content_parts: list[str]) -> str:
        """Format assistant message with clean markdown"""
        header = self.format_section_header("Assistant", "🤖")

        # For DingTalk, just join all parts cleanly
        parts = [header] + content_parts
        return "\n\n".join(parts)

    def _is_tool_output(self, text: str) -> bool:
        """Check if text is already formatted tool output"""
        return text.startswith(self.TOOL_EMOJI_PREFIXES)
