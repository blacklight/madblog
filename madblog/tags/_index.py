"""
Tag index: builds, persists and caches a mapping of tags → posts.

The index is stored as JSON at ``<content_dir>/.madblog/cache/tags-index.json``
and kept up-to-date via a watchdog-based filesystem monitor.
"""

import json
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from madblog.constants import REGEX_HASHTAG, REGEX_MARKDOWN_METADATA

from ._parsers import extract_hashtags, normalize_tag, parse_metadata_tags

logger = logging.getLogger(__name__)

_INDEX_VERSION = 1


class _PostTagInfo:
    """Per-post tag data stored in the index."""

    __slots__ = (
        "path",
        "title",
        "description",
        "published",
        "tags_meta",
        "tags_title",
        "tags_desc",
        "tags_body",
        "tags_mentions",
    )

    def __init__(
        self,
        path: str,
        *,
        title: str = "",
        description: str = "",
        published: str = "",
        tags_meta: Optional[List[str]] = None,
        tags_title: Optional[Dict[str, int]] = None,
        tags_desc: Optional[Dict[str, int]] = None,
        tags_body: Optional[Dict[str, int]] = None,
        tags_mentions: Optional[Dict[str, int]] = None,
    ):
        self.path = path
        self.title = title
        self.description = description
        self.published = published
        self.tags_meta = tags_meta or []
        self.tags_title = tags_title or {}
        self.tags_desc = tags_desc or {}
        self.tags_body = tags_body or {}
        self.tags_mentions = tags_mentions or {}

    def all_tags(self) -> set:
        tags = set(self.tags_meta)
        tags.update(self.tags_title)
        tags.update(self.tags_desc)
        tags.update(self.tags_body)
        tags.update(self.tags_mentions)
        return tags

    def score_for(self, tag: str) -> float:
        meta_boost = 5 if tag in self.tags_meta else 0
        return (
            meta_boost
            + 10 * self.tags_title.get(tag, 0)
            + 5 * self.tags_desc.get(tag, 0)
            + 1 * self.tags_body.get(tag, 0)
            + 0.25 * self.tags_mentions.get(tag, 0)
        )

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "description": self.description,
            "published": self.published,
            "tags_meta": self.tags_meta,
            "tags_title": self.tags_title,
            "tags_desc": self.tags_desc,
            "tags_body": self.tags_body,
            "tags_mentions": self.tags_mentions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_PostTagInfo":
        return cls(**d)


def _parse_metadata_fast(filepath: str) -> dict:
    """Read only the metadata header from a Markdown file (no full parse)."""
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


def _read_body(filepath: str) -> str:
    """Read the Markdown body (everything after metadata + first ``# title``)."""
    lines: list = []
    past_header = False
    skipped_title = False
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                if not past_header:
                    if not line.strip() or re.match(r"(^---\s*$)", line):
                        continue
                    if REGEX_MARKDOWN_METADATA.match(line):
                        continue
                    past_header = True

                if not skipped_title and line.startswith("# "):
                    skipped_title = True
                    continue

                lines.append(line)
    except OSError:
        pass
    return "".join(lines)


def _count_hashtags_in(text: str) -> Dict[str, int]:
    """Count hashtag occurrences in a plain string (no fence-awareness needed)."""
    counts: Counter = Counter()
    for hit in REGEX_HASHTAG.finditer(text):
        counts[hit.group(1).lower()] += 1
    return dict(counts)


class TagIndex:
    """
    In-memory tag index with on-disk JSON persistence.

    Thread-safe: all mutations go through ``_lock``.
    """

    def __init__(self, content_dir: str, pages_dir: str, mentions_dir: str):
        self._content_dir = Path(content_dir)
        self._pages_dir = Path(pages_dir)
        self._mentions_dir = Path(mentions_dir)
        self._cache_dir = self._content_dir / ".madblog" / "cache"
        self._index_path = self._cache_dir / "tags-index.json"

        self._lock = threading.RLock()
        # path -> _PostTagInfo
        self._posts: Dict[str, _PostTagInfo] = {}
        # tag -> set of paths
        self._tag_to_posts: Dict[str, set] = defaultdict(set)
        self._generation = 0
        self._disk_mtime: float = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> None:
        """
        Rebuild from all ``.md`` files under ``pages_dir``.

        Files whose mtime is older than the last index time are
        skipped — their data is reused from the existing on-disk
        index (if available).
        """
        # Try loading the existing index so we can skip unchanged files
        old_posts: Dict[str, _PostTagInfo] = {}
        last_indexed_at: float = 0
        if self._index_path.is_file():
            try:
                data = json.loads(self._index_path.read_text(encoding="utf-8"))
                if data.get("version") == _INDEX_VERSION:
                    last_indexed_at = data.get("last_indexed_at", 0)
                    for path, d in data.get("posts", {}).items():
                        old_posts[path] = _PostTagInfo.from_dict(d)
            except (OSError, json.JSONDecodeError, TypeError):
                pass

        posts: Dict[str, _PostTagInfo] = {}
        pages_dir = str(self._pages_dir)
        reindexed = 0
        skipped = 0

        for root, _, files in os.walk(pages_dir, followlinks=True):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, pages_dir)

                # Skip files that haven't changed since last index
                try:
                    file_mtime = os.stat(full).st_mtime
                except OSError:
                    continue

                if (
                    last_indexed_at
                    and file_mtime < last_indexed_at
                    and rel in old_posts
                ):
                    posts[rel] = old_posts[rel]
                    skipped += 1
                    continue

                info = self._index_post(full, rel)
                if info:
                    posts[rel] = info
                    reindexed += 1

        with self._lock:
            self._posts = posts
            self._rebuild_tag_map()
            self._generation += 1

        self._save()
        logger.info(
            "Tag index built: %d posts, %d tags (%d reindexed, %d unchanged)",
            len(self._posts),
            len(self._tag_to_posts),
            reindexed,
            skipped,
        )

    def reindex_file(self, filepath: str) -> None:
        """Re-index a single file (called on fs change)."""
        try:
            rel = os.path.relpath(filepath, str(self._pages_dir))
        except ValueError:
            return

        if not filepath.endswith(".md"):
            return

        if os.path.isfile(filepath):
            info = self._index_post(filepath, rel)
            with self._lock:
                if info:
                    self._posts[rel] = info
                elif rel in self._posts:
                    del self._posts[rel]
                self._rebuild_tag_map()
                self._generation += 1
        else:
            # File was deleted
            with self._lock:
                self._posts.pop(rel, None)
                self._rebuild_tag_map()
                self._generation += 1

        self._save()

    def get_all_tags(self) -> List[Tuple[str, int]]:
        """Return ``[(tag, post_count), ...]`` sorted alphabetically."""
        self._ensure_loaded()
        with self._lock:
            return sorted(
                ((tag, len(paths)) for tag, paths in self._tag_to_posts.items()),
                key=lambda t: t[0],
            )

    def get_posts_for_tag(self, tag: str) -> List[dict]:
        """Return post metadata dicts for *tag*, sorted by score then published date."""
        tag = normalize_tag(tag)
        self._ensure_loaded()

        with self._lock:
            paths = self._tag_to_posts.get(tag, set())
            results = []
            for p in paths:
                info = self._posts.get(p)
                if not info:
                    continue
                results.append(
                    {
                        "path": info.path,
                        "title": info.title,
                        "description": info.description,
                        "published": info.published,
                        "score": info.score_for(tag),
                    }
                )

        # Sort by score desc, then published date desc
        results.sort(
            key=lambda r: (-r["score"], r.get("published", "") or ""), reverse=False
        )
        # secondary sort: published desc when scores are equal
        results.sort(key=lambda r: r.get("published", "") or "", reverse=True)
        results.sort(key=lambda r: -r["score"])
        return results

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _index_post(self, filepath: str, rel_path: str) -> Optional[_PostTagInfo]:
        """Parse one Markdown file and return its tag info."""
        metadata = _parse_metadata_fast(filepath)
        body = _read_body(filepath)

        title = metadata.get("title", "")
        description = metadata.get("description", "")
        published = metadata.get("published", "")
        tags_meta = parse_metadata_tags(metadata.get("tags", ""))

        tags_title = _count_hashtags_in(title)
        tags_desc = _count_hashtags_in(description)
        tags_body = dict(extract_hashtags(body))

        # Include metadata tags that may not appear as hashtags in text
        for t in tags_meta:
            if t not in tags_body and t not in tags_title and t not in tags_desc:
                pass  # they're still tracked via tags_meta

        # Mentions
        tags_mentions: Dict[str, int] = {}
        slug = os.path.splitext(os.path.basename(rel_path))[0]
        mentions_in_dir = self._mentions_dir / "incoming" / slug
        if mentions_in_dir.is_dir():
            for md_file in mentions_in_dir.glob("webmention-*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8")
                    for hit in REGEX_HASHTAG.finditer(text):
                        tag = hit.group(1).lower()
                        tags_mentions[tag] = tags_mentions.get(tag, 0) + 1
                except OSError:
                    continue

        return _PostTagInfo(
            path=rel_path,
            title=title,
            description=description,
            published=published,
            tags_meta=tags_meta,
            tags_title=tags_title,
            tags_desc=tags_desc,
            tags_body=tags_body,
            tags_mentions=tags_mentions,
        )

    def _rebuild_tag_map(self) -> None:
        """Rebuild ``_tag_to_posts`` from ``_posts``. Caller must hold ``_lock``."""
        tag_map: Dict[str, set] = defaultdict(set)
        for path, info in self._posts.items():
            for tag in info.all_tags():
                tag_map[tag].add(path)
            for tag in info.tags_meta:
                tag_map[tag].add(path)
        self._tag_to_posts = tag_map

    def _save(self) -> None:
        """Persist the index to disk."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _INDEX_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "last_indexed_at": time.time(),
            "posts": {path: info.to_dict() for path, info in self._posts.items()},
        }
        tmp = self._index_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._index_path)
            self._disk_mtime = os.stat(self._index_path).st_mtime
        except OSError as exc:
            logger.warning("Failed to write tag index: %s", exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _load(self) -> bool:
        """Load the index from disk. Returns True on success."""
        if not self._index_path.is_file():
            return False

        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read tag index: %s", exc)
            return False

        if data.get("version") != _INDEX_VERSION:
            return False

        posts: Dict[str, _PostTagInfo] = {}
        for path, d in data.get("posts", {}).items():
            posts[path] = _PostTagInfo.from_dict(d)

        with self._lock:
            self._posts = posts
            self._rebuild_tag_map()
            self._generation += 1
            self._disk_mtime = os.stat(self._index_path).st_mtime

        return True

    def _ensure_loaded(self) -> None:
        """Make sure the in-memory index is populated."""
        with self._lock:
            if self._posts:
                # Check if disk index is newer
                try:
                    mtime = os.stat(self._index_path).st_mtime
                    if mtime > self._disk_mtime:
                        self._load()
                except OSError:
                    pass
                return

        # Try loading from disk first, fall back to full build
        if not self._load():
            self.build()
