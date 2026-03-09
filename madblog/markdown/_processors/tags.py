"""
Markdown extension: linkifies #hashtags in body text and provides
a shared extraction utility for the tag indexer.

Hashtags are matched by the pattern ``#[A-Za-z0-9_]+`` at word
boundaries.  The preprocessor intentionally skips:

- fenced code blocks (``` / ~~~)
- inline code spans (backtick-delimited)
- LaTeX expressions (already rewritten by the LaTeX preprocessor)
- Mermaid blocks (already consumed by the Mermaid preprocessor)
"""

from typing import List

import markdown
import markdown.preprocessors

from madblog.constants import (
    REGEX_HASHTAG,
    REGEX_FENCED_OPEN,
    REGEX_PROTECTED,
)


class TagPreprocessor(  # pylint: disable=too-few-public-methods
    markdown.preprocessors.Preprocessor
):
    """Replace ``#hashtag`` tokens with anchor links to ``/tags/<tag>``."""

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
                        REGEX_HASHTAG.sub(
                            lambda hit: (
                                '<a class="tag" href="/tags/{tag}">#{tag}</a>'.format(
                                    tag=hit.group(1).lower()
                                )
                            ),
                            part,
                        )
                    )
            out.append("".join(new_parts))

        return out


class MarkdownTags(markdown.Extension):
    """Wrapper that registers :class:`TagPreprocessor`."""

    def extendMarkdown(self, md):
        # Priority 0 — run after LaTeX (1) and Mermaid (30) preprocessors
        # so their source has already been consumed / rewritten.
        md.preprocessors.register(
            TagPreprocessor(md),
            "tags",
            0,
        )
