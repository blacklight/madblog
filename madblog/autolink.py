"""
Markdown extension: auto-links bare URLs that aren't already inside
code blocks, inline code, or explicit Markdown links.
"""

import re

import markdown
import markdown.preprocessors


# Matches bare URLs (http/https) that are NOT already:
#  - wrapped in <> angle brackets
#  - inside a Markdown link [text](url) or reference
#  - preceded by ( or "
_BARE_URL_RE = re.compile(
    r'(?<![(<"\[])(?<!\]\()(?<!`)(?<![=\'"])'  # negative lookbehinds
    r"(https?://[^\s\)<>\]\"`]+)"
)

# Fenced code block delimiters
_FENCED_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")


class AutolinkPreprocessor(markdown.preprocessors.Preprocessor):
    """Replace bare URLs with <URL> so Markdown renders them as links."""

    def run(self, lines):
        out = []
        fence = None  # tracks the fence delimiter when inside a fenced block

        for line in lines:
            # Track fenced code blocks
            m = _FENCED_OPEN_RE.match(line)
            if m:
                if fence is None:
                    fence = m.group(1)[0]  # '`' or '~'
                    out.append(line)
                    continue
                elif line.strip().startswith(fence):
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
                    new_parts.append(_BARE_URL_RE.sub(r"<\1>", part))
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
