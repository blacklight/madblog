import re


# ActivityPub mention pattern: @username@domain.tld
# Matches: letters, numbers, underscore, hyphen, dot for username and domain
REGEX_ACTIVITYPUB_MENTION = re.compile(
    r"(?<!\w)@([a-zA-Z0-9_.-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
)

# Matches bare URLs (http/https) that are NOT already:
#  - wrapped in <> angle brackets
#  - inside a Markdown link [text](url) or reference
#  - preceded by ( or "
REGEX_BARE_URL = re.compile(
    r'(?<![(<"\[])(?<!\]\()(?<!`)(?<![=\'"])'  # negative lookbehinds
    r"(https?://[^\s\)<>\]\"`]+)"
)

# Fenced code block delimiters
REGEX_FENCED_OPEN = re.compile(r"^(`{3,}|~{3,})")

# Canonical hashtag pattern: ``#`` followed by one or more word chars.
# The negative lookbehind prevents matching inside words (e.g. ``foo#bar``).
REGEX_HASHTAG = re.compile(r"(?<!\w)#([A-Za-z0-9_]+)")

# Markdown metadata header pattern
REGEX_MARKDOWN_METADATA = re.compile(r"^\[//]: # \(([^:]+):\s*(.*)\)\s*$")

# Mermaid fenced code block pattern
REGEX_MERMAID_BLOCK = re.compile(
    r"^```mermaid\s*\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)

# Segments that must be left untouched when scanning for hashtags:
#   - inline code spans: `...`
#   - Markdown link URLs:  [text](url)  — the whole construct
REGEX_PROTECTED = re.compile(r"(`[^`]+`|\[[^\]]*\]\([^)]+\))")


# Markdown table of contents marker
REGEX_TOC_MARKER = re.compile(
    r"^\s*(?:\[\[TOC\]\]|\[TOC\]|\{\{\s*TOC\s*\}\}|<!--\s*TOC\s*-->)\s*$",
    re.IGNORECASE,
)
