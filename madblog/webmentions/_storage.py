import hashlib
import json
import logging
import os
import re

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

from webmentions import (
    Webmention,
    WebmentionDirection,
    WebmentionsHandler,
    WebmentionStatus,
    WebmentionsStorage,
)
from webmentions.storage.adapters.file._watcher import ContentTextFormat

from madblog.config import config
from madblog.markdown import resolve_relative_urls
from madblog.monitor import ChangeType
from madblog.sync import StartupSyncMixin

logger = logging.getLogger(__name__)


class FileWebmentionsStorage(StartupSyncMixin, WebmentionsStorage):
    """
    File-based storage for Webmentions.

    Stores each Webmention as a Markdown file with metadata in comments.
    """

    _EXT_FORMAT_MAP = {
        ".md": ContentTextFormat.MARKDOWN,
        ".markdown": ContentTextFormat.MARKDOWN,
        ".html": ContentTextFormat.HTML,
        ".htm": ContentTextFormat.HTML,
        ".txt": ContentTextFormat.TEXT,
    }

    def __init__(
        self,
        content_dir: str | Path,
        mentions_dir: str | Path,
        *,
        base_url: str,
        root_dir: str | Path | None = None,
        webmentions_hard_delete: bool = False,
        replies_dir: str | Path | None = None,
        **_,
    ):
        self.content_dir = Path(content_dir).resolve()
        self.root_dir = Path(root_dir).resolve() if root_dir else self.content_dir
        self.mentions_dir = Path(mentions_dir).resolve()
        self.mentions_dir.mkdir(exist_ok=True, parents=True)
        self.base_url = base_url
        self.replies_dir = Path(replies_dir).resolve() if replies_dir else None
        self._webmentions_hard_delete = webmentions_hard_delete
        self._resource_locks = defaultdict(RLock)
        self._watcher_lock = RLock()
        self._webmentions_handler: WebmentionsHandler | None = None

        # StartupSyncMixin configuration
        self._sync_cache_file = config.resolved_state_dir / "webmentions_sync.json"
        self._sync_cache_file.parent.mkdir(exist_ok=True, parents=True)
        self._sync_pages_dir = str(self.content_dir)

    def set_handler(self, handler: WebmentionsHandler) -> None:
        """Wire the :class:`WebmentionsHandler` used for outgoing mentions."""
        self._webmentions_handler = handler

    # -- StartupSyncMixin hooks --

    def _sync_file_to_url(self, filepath: str) -> str:
        return self.file_to_url(filepath)

    def _sync_notify(self, filepath: str, is_new: bool) -> None:
        change = ChangeType.ADDED if is_new else ChangeType.EDITED
        self.on_content_change(change, filepath)

    def file_to_url(self, filepath: str) -> str:
        """Convert a local file path to its public article URL."""
        rel = os.path.relpath(filepath, self.content_dir).rsplit(".", 1)[0]
        return f"{self.base_url}/article/{rel}"

    def _get_text_format(self, filepath: str) -> ContentTextFormat:
        """Get ContentTextFormat from file extension."""
        ext = os.path.splitext(filepath)[1].lower()
        return self._EXT_FORMAT_MAP.get(ext, ContentTextFormat.MARKDOWN)

    def _process_outgoing_change(
        self,
        source_url: str,
        filepath: str,
        change_type: ChangeType,
        *,
        sync: bool = True,
        label: str = "",
    ) -> None:
        """
        Process outgoing webmentions for a content change.

        :param source_url: The public URL of the source content.
        :param filepath: The local file path.
        :param change_type: The type of change (added, edited, deleted).
        :param sync: Whether to update the sync cache.
        :param label: Label for log messages (e.g. "reply ").
        """
        if self._webmentions_handler is None:
            return

        text_format = self._get_text_format(filepath)

        if change_type.value == "deleted":
            if sync:
                self._sync_unmark(source_url)
            try:
                self._webmentions_handler.process_outgoing_webmentions(
                    source_url,
                    text="",
                    text_format=text_format,
                )
            except ValueError as e:
                logger.warning(
                    "Skipping outgoing webmentions for %s%s: %s", label, source_url, e
                )
        else:
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                return
            # Resolve relative URLs to absolute before processing
            text = resolve_relative_urls(text, self.base_url)
            try:
                self._webmentions_handler.process_outgoing_webmentions(
                    source_url,
                    text=text,
                    text_format=text_format,
                )
            except ValueError as e:
                logger.warning(
                    "Skipping outgoing webmentions for %s%s: %s", label, source_url, e
                )
            if sync:
                try:
                    mtime = os.path.getmtime(filepath)
                except OSError:
                    mtime = 0
                self._sync_mark(source_url, mtime)

    def on_content_change(self, change_type: ChangeType, filepath: str) -> None:
        """
        Callback for :class:`ContentMonitor`

        Forward file changes to the Webmentions handler so that outgoing
        mentions are (re-)processed.
        """
        # Skip files under replies/ - handled by on_reply_change
        if self.replies_dir and filepath.startswith(str(self.replies_dir) + os.sep):
            return

        source_url = self.file_to_url(filepath)
        self._process_outgoing_change(source_url, filepath, change_type, sync=True)

    def _get_mentions_dir(
        self, source: str, target: str, direction: WebmentionDirection
    ) -> Path:
        """
        Get the mentions directory for a webmention based on direction.

        For incoming mentions, use the target URL to determine the post slug.
        For outgoing mentions, use the source URL.
        """
        if direction == WebmentionDirection.IN:
            post_slug = self._extract_post_slug(target)
        else:
            post_slug = self._extract_post_slug(source)
        return self.mentions_dir / direction.value / post_slug

    def store_webmention(self, mention: Webmention):
        """
        Store Webmention as Markdown file
        """
        post_mentions_dir = self._get_mentions_dir(
            mention.source, mention.target, mention.direction
        )
        post_mentions_dir.mkdir(exist_ok=True, parents=True)

        # Generate safe filename
        filename = self._generate_mention_filename(mention.source, "webmention")
        filepath = post_mentions_dir / filename

        # Prepare metadata
        mention.created_at = datetime.now(timezone.utc)
        mention.updated_at = mention.created_at

        with self._resource_locks[filepath]:
            # Parse existing file metadata if file exists
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    existing_content = f.read()

                existing_metadata = self._parse_metadata(existing_content)
                if existing_metadata:
                    mention.created_at = (
                        Webmention.build(existing_metadata).created_at
                        or mention.created_at
                    )

            # Write as Markdown with YAML frontmatter
            content = self._format_webmention_markdown(mention)

            # Atomic write
            self._atomic_write(filepath, content)

        return filepath

    def retrieve_webmentions(
        self, resource: str, direction: WebmentionDirection
    ) -> list[Webmention]:
        """
        Retrieve stored Webmentions for a given resource.
        """

        post_slug = self._extract_post_slug(resource)
        post_mentions_dir = self.mentions_dir / direction.value / post_slug
        webmentions = []

        if not post_mentions_dir.exists():
            return webmentions

        for md_file in post_mentions_dir.glob("webmention-*.md"):
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()

                metadata = self._parse_metadata(content)
                if metadata.get("status") != WebmentionStatus.CONFIRMED.value:
                    continue

                mention = Webmention.build(metadata)
                self._normalize_author(mention)
                self._normalize_content(mention)
                webmentions.append(mention)
            except Exception as e:
                logger.error("Error parsing Webmention in %s: %s", md_file, e)
                continue

        return sorted(
            webmentions, key=lambda x: x.published or x.created_at, reverse=True
        )

    def delete_webmention(
        self,
        source: str,
        target: str,
        direction: WebmentionDirection,
    ):
        """Mark a stored mention as deleted by updating its metadata."""
        post_mentions_dir = self._get_mentions_dir(source, target, direction)

        filename = self._generate_mention_filename(source, "webmention")
        filepath = post_mentions_dir / filename
        if not filepath.exists():
            return None

        if self._webmentions_hard_delete:
            with self._resource_locks[filepath]:
                filepath.unlink(missing_ok=True)
            return filepath

        with self._resource_locks[filepath]:
            with open(filepath, "r", encoding="utf-8") as f:
                existing_content = f.read()

            existing_metadata = self._parse_metadata(existing_content)
            metadata = {
                **existing_metadata,
                "type": existing_metadata.get("type", "webmention"),
                "source": source,
                "target": target,
                "updated_at": datetime.now(timezone.utc),
                "status": "deleted",
            }

            content = self._format_webmention_markdown(Webmention.build(metadata))
            self._atomic_write(filepath, content)

        return filepath

    @staticmethod
    def _parse_metadata(content: str) -> dict:
        """
        Parse metadata from Markdown comments and extract body content.
        """

        metadata = {}
        body_lines = []
        in_body = False

        for line in content.splitlines():
            match = re.match(r"\[//]: # \(([^:]+): (.+)\)", line)
            if match:
                key, value = match.groups()
                metadata[key.strip()] = value.strip()
            elif line.strip() or in_body:
                # After metadata, collect body content
                in_body = True
                body_lines.append(line)

        # Extract body content (full content stored after metadata)
        if body_lines:
            body = "\n".join(body_lines).strip()
            if body:
                metadata["content"] = body

        return metadata

    @staticmethod
    def _format_webmention_markdown(mention: Webmention):
        """
        Format Webmention as Markdown and include metadata as comments.
        """

        md_content = ""

        for key, value in asdict(mention).items():
            if key == "content" or value is None:
                continue
            if isinstance(value, Enum):
                value = value.value
            if isinstance(value, datetime):
                value = value.isoformat()
            if isinstance(value, (list, dict)):
                value = json.dumps(value)

            md_content += f"[//]: # ({key}: {value})\n"

        md_content += f"\n{mention.content or ''}\n"
        return md_content

    @staticmethod
    def _atomic_write(filepath: Path, content: str):
        """Atomic file write to prevent corruption"""
        temp_path = filepath.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
            temp_path.replace(filepath)  # Atomic on most filesystems
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    @classmethod
    def _extract_post_slug(cls, target_url: str):
        """Extract post slug from target URL"""
        # Customize based on your URL structure
        # e.g., https://yourblog.com/post/hello-world -> hello-world
        parts = target_url.rstrip("/").split("/")
        return cls._safe_filename(parts[-1])

    @classmethod
    def _generate_mention_filename(
        cls, source_url: str, mention_type: str = "webmention"
    ):
        """
        Generate unique, safe filename for mentions.
        """
        url_hash = hashlib.md5(source_url.encode()).hexdigest()[:8]

        # Extract domain for readability
        domain = urlparse(source_url).netloc.replace(".", "-")
        domain = cls._safe_filename(domain)

        return f"{mention_type}-{domain}-{url_hash}.md"

    @staticmethod
    def _safe_filename(text: str, max_length: int = 50) -> str:
        """
        Generate safe filenames from Webmention source URLs.
        """
        # Remove/replace unsafe characters
        safe = re.sub(r"[^\w\s-]", "", text)
        safe = re.sub(r"[-\s]+", "-", safe)
        return safe[:max_length].strip("-")

    @staticmethod
    def _normalize_content(mention: Webmention) -> None:
        """
        Fix legacy data where ``None`` content was serialized as the
        literal string ``"None"``.
        """
        if mention.content == "None":
            mention.content = None
        if mention.excerpt == "None":
            mention.excerpt = None
        if mention.title == "None":
            mention.title = None

    @staticmethod
    def _normalize_author(mention: Webmention) -> None:
        """
        Fix legacy data where a plain-text author name was stored in
        ``author_url`` instead of ``author_name``.
        """
        if mention.author_url and not mention.author_url.startswith(
            ("http://", "https://", "mailto:")
        ):
            if not mention.author_name:
                mention.author_name = mention.author_url
            mention.author_url = None

    # -----------------------------------------------------------------
    # Reply outgoing webmentions
    # -----------------------------------------------------------------

    def reply_file_to_url(self, filepath: str) -> str:
        """Convert a reply file path to its public URL."""
        if not self.replies_dir:
            raise ValueError("replies_dir not configured")

        rel = os.path.relpath(filepath, self.replies_dir).rsplit(".", 1)[0]
        return f"{self.base_url}/reply/{rel}"

    def on_reply_change(self, change_type: ChangeType, filepath: str) -> None:
        """
        Callback for replies ContentMonitor.

        Forward reply file changes to the Webmentions handler so that
        outgoing mentions are (re-)processed.
        """
        if not self.replies_dir:
            return

        source_url = self.reply_file_to_url(filepath)
        self._process_outgoing_change(
            source_url, filepath, change_type, sync=False, label="reply "
        )
