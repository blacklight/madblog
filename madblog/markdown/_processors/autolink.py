"""
Markdown extension: auto-links bare URLs that aren't already inside
code blocks, inline code, or explicit Markdown links.
"""

import re

import markdown
import markdown.preprocessors

from madblog.constants import REGEX_BARE_URL, REGEX_FENCED_OPEN


class AutolinkPreprocessor(  # pylint: disable=too-few-public-methods
    markdown.preprocessors.Preprocessor
):
    """Replace bare URLs with <URL> so Markdown renders them as links."""

    def run(self, lines):
        out = []
        fence = None  # tracks the fence delimiter when inside a fenced block

        for line in lines:
            # Track fenced code blocks
            m = REGEX_FENCED_OPEN.match(line)
            if m:
                if fence is None:
                    fence = m.group(1)[0]  # '`' or '~'
                    out.append(line)
                    continue
                if line.strip().startswith(fence):
                    fence = None
                    out.append(line)
                    continue

            if fence is not None:
                # Inside a fenced code block — pass through
                out.append(line)
                continue

            # Protect inline code spans from replacement
            # Split by backtick-delimited code spans, only transform non-code parts
            parts = re.split(r"(`[^`]+`)", line)
            new_parts = []
            for part in parts:
                if part.startswith("`") and part.endswith("`"):
                    new_parts.append(part)
                else:
                    new_parts.append(REGEX_BARE_URL.sub(r"<\1>", part))
            out.append("".join(new_parts))

        return out


class MarkdownAutolink(markdown.Extension):
    """Wrapper for AutolinkPreprocessor."""

    def extendMarkdown(self, md):
        # Priority 50 — run before all other custom preprocessors
        md.preprocessors.register(
            AutolinkPreprocessor(md),
            "autolink",
            50,
        )
