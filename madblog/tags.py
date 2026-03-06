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

import re
from collections import Counter
from typing import List

import markdown
import markdown.preprocessors


# Canonical hashtag pattern: ``#`` followed by one or more word chars.
# The negative lookbehind prevents matching inside words (e.g. ``foo#bar``).
_HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_]+)")

# Fenced code block delimiters
_FENCED_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")

# Segments that must be left untouched when scanning for hashtags:
#   - inline code spans: `...`
#   - Markdown link URLs:  [text](url)  — the whole construct
_PROTECTED_RE = re.compile(r"(`[^`]+`|\[[^\]]*\]\([^)]+\))")


def normalize_tag(tag: str) -> str:
    """Return the canonical (lowercase, no ``#`` prefix) form of *tag*."""
    return tag.lstrip("#").lower()


def parse_metadata_tags(value: str) -> List[str]:
    """Parse a ``tags`` metadata value into a list of canonical tag keys.

    Accepts comma-separated tags with or without leading ``#``.
    """
    tags: List[str] = []
    for segment in value.split(","):
        segment = segment.strip()
        if not segment:
            continue
        canonical = normalize_tag(segment)
        if canonical:
            tags.append(canonical)
    return tags


def extract_hashtags(text: str) -> Counter:
    """Extract hashtag counts from *text*, skipping code fences and inline code.

    Returns a :class:`~collections.Counter` mapping canonical tag -> count.
    """
    counts: Counter = Counter()
    fence = None

    for line in text.splitlines():
        # Track fenced code blocks
        m = _FENCED_OPEN_RE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)[0]  # '`' or '~'
                continue
            elif line.strip().startswith(fence):
                fence = None
                continue

        if fence is not None:
            continue

        # Split by protected spans (inline code + Markdown links)
        parts = _PROTECTED_RE.split(line)
        for part in parts:
            if _PROTECTED_RE.fullmatch(part):
                continue
            for hit in _HASHTAG_RE.finditer(part):
                counts[hit.group(1).lower()] += 1

    return counts


class TagPreprocessor(markdown.preprocessors.Preprocessor):
    """Replace ``#hashtag`` tokens with anchor links to ``/tags/<tag>``."""

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
                        _HASHTAG_RE.sub(
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
