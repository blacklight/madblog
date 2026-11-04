"""
Metadata header parser for Markdown files.

Two syntaxes are supported:

- YAML front matter — a ``---`` block at the very top of the file,
  closed by another ``---`` line::

      ---
      title: My post
      published: 2022-01-01
      ---

- Comment headers — ``[//]: # (key: value)`` lines at the top of the
  file (legacy syntax, still fully supported).
"""

import datetime
import re
from typing import Iterable

import yaml

from madblog.constants import REGEX_MARKDOWN_METADATA

_FRONT_MATTER_DELIMITER = re.compile(r"^---\s*$")
_FRONT_MATTER_FALLBACK_LINE = re.compile(r"^([\w.\-]+):\s*(.*)$")


def _parse_front_matter_block(block: Iterable[str]) -> dict:
    """
    Parse the lines inside a ``---`` block.

    Tries ``yaml.safe_load`` first; on failure (or when the block does
    not evaluate to a mapping) falls back to line-by-line parsing of
    both ``[//]: # (key: value)`` comments and plain ``key: value``
    lines.
    """
    lines = list(block)
    try:
        data = yaml.safe_load("".join(lines))
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass

    metadata: dict = {}
    for line in lines:
        m = REGEX_MARKDOWN_METADATA.match(line) or _FRONT_MATTER_FALLBACK_LINE.match(
            line
        )
        if m:
            metadata[m.group(1)] = m.group(2)

    return metadata


def split_front_matter(lines: list) -> tuple:
    """
    Split a leading YAML front matter block from a list of lines.

    Returns ``(metadata, remaining_lines)``. The block is only consumed
    when the first line is ``---``, a closing ``---`` exists, and the
    block either is empty or yields some metadata — otherwise the lines
    are returned unchanged.
    """
    if not lines or not _FRONT_MATTER_DELIMITER.match(lines[0]):
        return {}, lines

    for i in range(1, len(lines)):
        if _FRONT_MATTER_DELIMITER.match(lines[i]):
            block = lines[1:i]
            metadata = _parse_front_matter_block(block)
            if metadata or not any(line.strip() for line in block):
                return metadata, lines[i + 1 :]
            return {}, lines

    return {}, lines


def normalize_metadata(metadata: dict) -> dict:
    """
    Normalize metadata values parsed from YAML to plain strings, so
    they can be consumed the same way as values parsed from comment
    headers. Dates are converted to ISO format, lists are joined with
    ``,`` — the same separator used by list-like metadata keys such as
    ``tags``, ``links`` and ``org``.
    """
    normalized = {}
    for key, value in metadata.items():
        key = str(key)
        if isinstance(value, datetime.datetime):
            normalized[key] = value.isoformat()
        elif isinstance(value, datetime.date):
            normalized[key] = value.isoformat()
        elif isinstance(value, (list, tuple)):
            normalized[key] = ", ".join(str(v) for v in value)
        elif value is None:
            normalized[key] = ""
        else:
            normalized[key] = str(value)

    return normalized


def parse_metadata_header(filepath: str) -> dict:
    """
    Read only the metadata header from a Markdown file (no full parse).

    Returns a ``dict`` of raw string key → string value pairs.
    Silently returns an empty dict on ``OSError``.
    """
    metadata: dict = {}
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            front_matter, lines = split_front_matter(fh.readlines())
    except OSError:
        return metadata

    metadata.update(normalize_metadata(front_matter))

    for line in lines:
        if not line.strip() or re.match(r"(^---\s*$)|(^#\s+.*)", line):
            continue
        m = REGEX_MARKDOWN_METADATA.match(line)
        if not m:
            break
        metadata[m.group(1)] = m.group(2)

    return metadata
