"""
Markdown extension: linkifies ActivityPub mentions (@user@domain.tld) in body text.

ActivityPub mentions are matched by the pattern ``@[username]@[domain.tld]`` at word
boundaries. The preprocessor intentionally skips:

- fenced code blocks (``` / ~~~)
- inline code spans (backtick-delimited)
- existing Markdown links
- LaTeX expressions (already rewritten by the LaTeX preprocessor)
- Mermaid blocks (already consumed by the Mermaid preprocessor)
"""

import re
from typing import List

import markdown
import markdown.preprocessors


# ActivityPub mention pattern: @username@domain.tld
# Matches: letters, numbers, underscore, hyphen, dot for username and domain
_ACTIVITYPUB_MENTION_RE = re.compile(
    r"(?<!\w)@([a-zA-Z0-9_.-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
)

# Fenced code block delimiters
_FENCED_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")

# Segments that must be left untouched when scanning for mentions:
#   - inline code spans: `...`
#   - Markdown link URLs:  [text](url)  — the whole construct
_PROTECTED_RE = re.compile(r"(`[^`]+`|\[[^\]]*\]\([^)]+\))")


class ActivityPubMentionPreprocessor(markdown.preprocessors.Preprocessor):
    """Replace ``@user@domain.tld`` tokens with anchor links to ActivityPub profiles."""

    def run(self, lines):
        out: List[str] = []
        fence = None

        for line in lines:
            # Track fenced code blocks
            m = _FENCED_OPEN_RE.match(line)
            if m:
                if fence is None:
                    fence = m.group(1)[0]
                    out.append(line)
                    continue
                elif line.strip().startswith(fence):
                    fence = None
                    out.append(line)
                    continue

            if fence is not None:
                out.append(line)
                continue

            # Split by protected spans (inline code + Markdown links)
            parts = _PROTECTED_RE.split(line)
            new_parts: List[str] = []
            for part in parts:
                if _PROTECTED_RE.fullmatch(part):
                    new_parts.append(part)
                else:
                    new_parts.append(
                        _ACTIVITYPUB_MENTION_RE.sub(
                            lambda hit: (
                                '<a class="activitypub-mention" href="https://{domain}/@{username}">@{username}@{domain}</a>'.format(
                                    username=hit.group(1), domain=hit.group(2)
                                )
                            ),
                            part,
                        )
                    )
            out.append("".join(new_parts))

        return out


class MarkdownActivityPubMentions(markdown.Extension):
    """Wrapper that registers :class:`ActivityPubMentionPreprocessor`."""

    def extendMarkdown(self, md):
        # Priority 0 — run after LaTeX (1) and Mermaid (30) preprocessors
        # so their source has already been consumed / rewritten.
        md.preprocessors.register(
            ActivityPubMentionPreprocessor(md),
            "activitypub_mentions",
            0,
        )
