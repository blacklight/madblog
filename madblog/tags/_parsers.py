from collections import Counter
from typing import List

from madblog.constants import (
    REGEX_HASHTAG,
    REGEX_FENCED_OPEN,
    REGEX_PROTECTED,
)


def normalize_tag(tag: str) -> str:
    """Return the canonical (lowercase, no ``#`` prefix) form of *tag*."""
    return tag.lstrip("#").lower()


def parse_metadata_tags(value: str) -> List[str]:
    """
    Parse a ``tags`` metadata value into a list of canonical tag keys.

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
    """
    Extract hashtag counts from *text*, skipping code fences and inline code.

    Returns a :class:`~collections.Counter` mapping canonical tag -> count.
    """
    counts: Counter = Counter()
    fence = None

    for line in text.splitlines():
        # Track fenced code blocks
        m = REGEX_FENCED_OPEN.match(line)
        if m:
            if fence is None:
                fence = m.group(1)[0]  # '`' or '~'
                continue
            if line.strip().startswith(fence):
                fence = None
                continue

        if fence is not None:
            continue

        # Split by protected spans (inline code + Markdown links)
        parts = REGEX_PROTECTED.split(line)
        for part in parts:
            if REGEX_PROTECTED.fullmatch(part):
                continue
            for hit in REGEX_HASHTAG.finditer(part):
                counts[hit.group(1).lower()] += 1

    return counts
