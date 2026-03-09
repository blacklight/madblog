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

from typing import List

import markdown
import markdown.preprocessors

from madblog.constants import (
    REGEX_ACTIVITYPUB_MENTION,
    REGEX_FENCED_OPEN,
    REGEX_PROTECTED,
)


class MarkdownActivityPubMention(  # pylint: disable=too-few-public-methods
    markdown.preprocessors.Preprocessor
):
    """Replace ``@user@domain.tld`` tokens with anchor links to ActivityPub profiles."""

    def run(self, lines):
        out: List[str] = []
        fence = None

        for line in lines:
            # Track fenced code blocks
            m = REGEX_FENCED_OPEN.match(line)
            if m:
                if fence is None:
                    fence = m.group(1)[0]
                    out.append(line)
                    continue
                if line.strip().startswith(fence):
                    fence = None
                    out.append(line)
                    continue

            if fence is not None:
                out.append(line)
                continue

            # Split by protected spans (inline code + Markdown links)
            parts = REGEX_PROTECTED.split(line)
            new_parts: List[str] = []
            for part in parts:
                if REGEX_PROTECTED.fullmatch(part):
                    new_parts.append(part)
                else:
                    new_parts.append(
                        REGEX_ACTIVITYPUB_MENTION.sub(
                            lambda hit: (
                                (
                                    '<a class="activitypub-mention" href="https://{domain}/@{username}">'
                                    "@{username}@{domain}</a>"
                                ).format(username=hit.group(1), domain=hit.group(2))
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
            MarkdownActivityPubMention(md),
            "activitypub_mentions",
            0,
        )
