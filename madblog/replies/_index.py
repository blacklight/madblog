"""
Reply metadata index: JSON-persisted metadata for reply files.

Stores per-file metadata extracted from the Markdown header block,
enabling O(1) lookups without filesystem scans. Incrementally updated
via ContentMonitor callbacks.
"""

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from madblog.constants import REGEX_MARKDOWN_METADATA
from madblog.monitor import ChangeType
from madblog.reactions import _fediverse_url_aliases

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


@dataclass
class ReplyMetadata:
    """Metadata stored per reply file."""

    rel_path: str
    reply_to: str | None
    like_of: str | None
    visibility: str | None  # raw string, not resolved
    published: str | None  # ISO format string
    has_content: bool
    title: str | None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ReplyMetadata":
        return cls(**d)


class ReplyMetadataIndex:
    """
    JSON-persisted metadata index for reply files.

    Stores per-file metadata extracted from the Markdown header block,
    enabling O(1) lookups without filesystem scans.

    The index is keyed by relative path (e.g. ``"my-post.md"`` or
    ``"article/reply.md"``) to handle sub-directories unambiguously.

    Thread-safe: all mutations go through ``_lock``.
    """

    def __init__(self, replies_dir: Path, state_dir: Path):
        self._replies_dir = Path(replies_dir)
        self._state_dir = Path(state_dir)
        self._index_file = self._state_dir / "reply_metadata_index.json"
        self._entries: dict[str, ReplyMetadata] = {}
        self._lock = threading.RLock()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._loaded

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Load the index from JSON on disk.

        If the file does not exist or has a schema mismatch, perform a
        one-time full scan of all ``.md`` files under ``replies_dir``
        to build the index, then persist it.
        """
        with self._lock:
            if self._index_file.exists():
                try:
                    with open(self._index_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    if data.get("schema_version") == _SCHEMA_VERSION:
                        self._entries = {
                            rel_path: ReplyMetadata.from_dict(entry)
                            for rel_path, entry in data.get("entries", {}).items()
                        }
                        self._loaded = True
                        logger.debug(
                            "Loaded reply metadata index: %d entries",
                            len(self._entries),
                        )
                        return
                    else:
                        logger.info(
                            "Reply metadata index schema mismatch (v%s != v%s); rebuilding",
                            data.get("schema_version"),
                            _SCHEMA_VERSION,
                        )
                except Exception:
                    logger.warning("Failed to load reply metadata index; rebuilding")

            self._full_scan()
            self._save()
            self._loaded = True

    def _save(self) -> None:
        """Persist the in-memory index to JSON."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": _SCHEMA_VERSION,
            "entries": {
                rel_path: entry.to_dict() for rel_path, entry in self._entries.items()
            },
        }
        tmp = self._index_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._index_file)
        except OSError as exc:
            logger.warning("Failed to write reply metadata index: %s", exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Full scan (first run or schema mismatch)
    # ------------------------------------------------------------------

    def _full_scan(self) -> None:
        """Scan all ``.md`` files under ``replies_dir`` to build the index."""
        self._entries = {}
        if not self._replies_dir.is_dir():
            return

        count = 0
        for md_file in self._replies_dir.rglob("*.md"):
            entry = self._extract_metadata(str(md_file))
            if entry:
                self._entries[entry.rel_path] = entry
                count += 1

        logger.info("Reply metadata index full scan: %d files indexed", count)

    # ------------------------------------------------------------------
    # Single-file metadata extraction
    # ------------------------------------------------------------------

    def _extract_metadata(self, filepath: str) -> ReplyMetadata | None:
        """
        Extract metadata from a reply Markdown file.

        Reads only the metadata block (stops at first ``# `` heading or
        non-metadata line). Determines ``has_content`` by checking if
        there are non-blank, non-metadata lines after the block.

        :param filepath: Absolute path to the Markdown file.
        :return: ReplyMetadata instance, or None if file cannot be read.
        """
        try:
            rel_path = os.path.relpath(filepath, self._replies_dir)
        except ValueError:
            return None

        metadata: dict[str, Any] = {}
        has_content = False
        title_from_heading: str | None = None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                in_metadata = True
                for line in f:
                    stripped = line.strip()

                    # Skip empty lines and YAML delimiters in metadata block
                    if in_metadata and (not stripped or stripped == "---"):
                        continue

                    # Check for first heading (ends metadata block)
                    if line.startswith("# "):
                        in_metadata = False
                        title_from_heading = line[2:].strip()
                        # Check for link in heading: # [Title](url)
                        link_match = re.match(
                            r"\[([^\]]+)\]\([^)]+\)", title_from_heading
                        )
                        if link_match:
                            title_from_heading = link_match.group(1)
                        continue

                    if in_metadata:
                        m = REGEX_MARKDOWN_METADATA.match(line)
                        if m:
                            key, value = m.group(1), m.group(2).strip()
                            metadata[key] = value
                        else:
                            # Non-metadata line encountered
                            in_metadata = False
                            # This line is content
                            if stripped and not stripped.startswith("[//]: # ("):
                                has_content = True
                    else:
                        # After metadata block, check for content
                        if stripped and not stripped.startswith("[//]: # ("):
                            has_content = True
                            # Once we find content, no need to read more
                            break

        except OSError:
            return None

        # Parse published date if present
        published_str: str | None = None
        if "published" in metadata:
            published_str = metadata["published"]

        # Determine title: explicit > from heading > None
        title = metadata.get("title") or title_from_heading

        return ReplyMetadata(
            rel_path=rel_path,
            reply_to=metadata.get("reply-to"),
            like_of=metadata.get("like-of"),
            visibility=metadata.get("visibility"),
            published=published_str,
            has_content=has_content,
            title=title,
        )

    # ------------------------------------------------------------------
    # Monitor callback
    # ------------------------------------------------------------------

    def on_reply_change(self, change_type: ChangeType, filepath: str) -> None:
        """
        Callback for the replies ``ContentMonitor``.

        On create/edit: re-index the file. On delete: remove its entry.
        Always flushes to disk.

        :param change_type: Type of change (ADDED, EDITED, DELETED).
        :param filepath: Absolute path to the changed file.
        """
        try:
            rel_path = os.path.relpath(filepath, self._replies_dir)
        except ValueError:
            return

        with self._lock:
            if change_type == ChangeType.DELETED:
                self._entries.pop(rel_path, None)
            else:
                entry = self._extract_metadata(filepath)
                if entry:
                    self._entries[entry.rel_path] = entry
                else:
                    # File couldn't be read, remove stale entry
                    self._entries.pop(rel_path, None)

            self._save()

    # ------------------------------------------------------------------
    # Direct access
    # ------------------------------------------------------------------

    def get_entry(self, rel_path: str) -> ReplyMetadata | None:
        """
        Get metadata for a specific file by relative path.

        :param rel_path: Path relative to replies_dir (e.g. "my-post.md").
        :return: ReplyMetadata or None if not found.
        """
        with self._lock:
            return self._entries.get(rel_path)

    def get_all_entries(self) -> dict[str, ReplyMetadata]:
        """
        Get a copy of all entries.

        :return: Dict mapping rel_path to ReplyMetadata.
        """
        with self._lock:
            return dict(self._entries)

    @property
    def entry_count(self) -> int:
        """Number of indexed entries."""
        with self._lock:
            return len(self._entries)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def _is_root_level(self, rel_path: str) -> bool:
        """Check if a path is at the root level (no subdirectory)."""
        return "/" not in rel_path and "\\" not in rel_path

    def get_unlisted_slugs(self) -> list[str]:
        """
        Get slugs for unlisted posts (root-level files).

        Matches files with:
        - No reply_to
        - No like_of
        - has_content = True
        - visibility = "unlisted" (explicit or default for root replies)

        :return: List of slugs (filename stems without .md).
        """
        slugs = []
        with self._lock:
            for rel_path, entry in self._entries.items():
                if not self._is_root_level(rel_path):
                    continue
                if entry.reply_to or entry.like_of:
                    continue
                if not entry.has_content:
                    continue
                # For root-level replies without reply-to/like-of,
                # default visibility is UNLISTED
                vis = (entry.visibility or "unlisted").lower()
                if vis != "unlisted":
                    continue
                # Slug is the filename stem
                slug = rel_path.rsplit(".", 1)[0]
                slugs.append(slug)
        return slugs

    def get_ap_reply_slugs(self) -> list[str]:
        """
        Get slugs for AP replies (root-level files with reply-to).

        Matches files with:
        - reply_to is set
        - has_content = True
        - visibility in ("public", "unlisted")

        :return: List of slugs (filename stems without .md).
        """
        slugs = []
        with self._lock:
            for rel_path, entry in self._entries.items():
                if not self._is_root_level(rel_path):
                    continue
                if not entry.reply_to:
                    continue
                if not entry.has_content:
                    continue
                vis = (entry.visibility or "public").lower()
                if vis not in ("public", "unlisted"):
                    continue
                slug = rel_path.rsplit(".", 1)[0]
                slugs.append(slug)
        return slugs

    def get_article_reply_slugs(self, article_slug: str) -> list[str]:
        """
        Get slugs for replies under a specific article directory.

        Matches files under replies/<article_slug>/ with:
        - visibility not in ("followers", "direct", "draft")

        :param article_slug: The article slug (subdirectory name).
        :return: List of reply slugs (filename stems without .md).
        """
        prefix = f"{article_slug}/"
        slugs = []
        with self._lock:
            for rel_path, entry in self._entries.items():
                if not rel_path.startswith(prefix):
                    continue
                # Check visibility
                vis = (entry.visibility or "public").lower()
                if vis in ("followers", "direct", "draft"):
                    continue
                # Slug is just the filename part
                filename = rel_path[len(prefix) :]
                if "/" in filename:
                    # Nested deeper, skip
                    continue
                slug = filename.rsplit(".", 1)[0]
                slugs.append(slug)
        return slugs

    def get_like_of_map(self) -> dict[str, list[dict]]:
        """
        Get reverse mapping of like-of targets to source files.

        Returns a dict mapping target_url to a list of dicts with:
        - slug: The reply slug
        - rel_path: Relative path to the file
        - source_url: The /reply/... URL

        :return: Dict mapping target URLs to lists of source info.
        """
        result: dict[str, list[dict]] = {}
        with self._lock:
            for rel_path, entry in self._entries.items():
                if not entry.like_of:
                    continue
                # Build source URL
                stem = rel_path.rsplit(".", 1)[0]
                source_url = f"/reply/{stem}"
                info = {
                    "slug": stem.split("/")[-1],
                    "rel_path": rel_path,
                    "source_url": source_url,
                    "type": "like",
                }
                if entry.like_of not in result:
                    result[entry.like_of] = []
                result[entry.like_of].append(info)
        return result

    def get_likes_for_target(self, target_url: str) -> list[dict]:
        """
        Get author likes targeting a specific URL.

        :param target_url: The URL to look up.
        :return: List of like info dicts.
        """
        target_urls = {target_url} | set(_fediverse_url_aliases(target_url))
        result = []
        with self._lock:
            for rel_path, entry in self._entries.items():
                if entry.like_of not in target_urls:
                    continue
                stem = rel_path.rsplit(".", 1)[0]
                result.append(
                    {
                        "slug": stem.split("/")[-1],
                        "rel_path": rel_path,
                        "source_url": f"/reply/{stem}",
                        "type": "like",
                    }
                )
        return result
