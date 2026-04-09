"""
Lightweight metadata header parser for Markdown files.

Reads ``[//]: # (key: value)`` comment lines from the top of a file,
stopping at the first non-metadata, non-blank, non-delimiter line.
"""

import re

from madblog.constants import REGEX_MARKDOWN_METADATA


def parse_metadata_header(filepath: str) -> dict:
    """
    Read only the metadata header from a Markdown file (no full parse).

    Returns a ``dict`` of raw string key → string value pairs.
    Silently returns an empty dict on ``OSError``.
    """
    metadata: dict = {}
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip() or re.match(r"(^---\s*$)|(^#\s+.*)", line):
                    continue
                m = REGEX_MARKDOWN_METADATA.match(line)
                if not m:
                    break
                metadata[m.group(1)] = m.group(2)
    except OSError:
        pass

    return metadata
