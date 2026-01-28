import hashlib
import re

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from ..config import config
from ._model import Webmention, WebmentionDirection


class WebmentionsStorage(ABC):
    """
    Abstract base class for Webmention storage backends.
    """

    @abstractmethod
    def store_webmention(self, mention: Webmention) -> Any:
        """
        Store a webmention.

        :param mention: The webmention to store
        """

    @abstractmethod
    def delete_webmention(
        self,
        source: str,
        target: str,
        direction: WebmentionDirection,
    ) -> Any:
        """
        Mark a webmention as deleted.

        :param source: The source URL of the webmention
        :param target: The target URL of the webmention
        :param direction: The direction of the webmention (inbound or outbound)
        """

    @abstractmethod
    def retrieve_webmentions(self, target: str) -> list[Webmention]:
        """
        Retrieve webmentions for a given target URL.

        :param target: The target URL to retrieve webmentions for
        :return: A list of webmention data dictionaries
        """

    @staticmethod
    def _parse_metadata(content: str) -> dict:
        """
        Parse metadata from Markdown comments.
        """

        metadata = {}
        for line in content.splitlines():
            match = re.match(r"\[//]: # \(([^:]+): (.+)\)", line)
            if match:
                key, value = match.groups()
                metadata[key.strip()] = value.strip()

        return metadata

    @classmethod
    def build(cls) -> "WebmentionsStorage":
        """
        Factory method to create a WebmentionsStorage instance.

        Only FileWebmentionsStorage is supported currently.
        """
        return FileWebmentionsStorage()


class FileWebmentionsStorage(WebmentionsStorage):
    """
    File-based storage for Webmentions.

    Stores each Webmention as a Markdown file with metadata in comments
    """

    def __init__(self, mentions_dir: str = "mentions"):
        self.mentions_dir = Path(config.content_dir) / mentions_dir
        self.mentions_dir.mkdir(exist_ok=True, parents=True)
        self._resource_locks = defaultdict(RLock)

    def store_webmention(self, mention: Webmention):
        """
        Store Webmention as Markdown file
        """

        if mention.direction == WebmentionDirection.IN:
            # Extract post slug from target URL
            post_slug = self._extract_post_slug(mention.target)
            post_mentions_dir = (
                self.mentions_dir / WebmentionDirection.IN.value / post_slug
            )
        else:
            # Extract post slug from source URL
            post_slug = self._extract_post_slug(mention.source)
            post_mentions_dir = (
                self.mentions_dir / WebmentionDirection.OUT.value / post_slug
            )

        post_mentions_dir.mkdir(exist_ok=True)

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

    def retrieve_webmentions(self, target: str) -> list[Webmention]:
        """
        Retrieve Webmentions for a given target URL
        """

        post_slug = self._extract_post_slug(target)
        post_mentions_dir = self.mentions_dir / WebmentionDirection.IN.value / post_slug
        webmentions = []

        if not post_mentions_dir.exists():
            return webmentions

        for md_file in post_mentions_dir.glob("webmention-*.md"):
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()

            metadata = self._parse_metadata(content)
            if metadata.get("status") == "deleted":
                continue

            webmentions.append(Webmention.build(metadata))

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

        if direction == WebmentionDirection.IN:
            post_slug = self._extract_post_slug(target)
            post_mentions_dir = (
                self.mentions_dir / WebmentionDirection.IN.value / post_slug
            )
        else:
            post_slug = self._extract_post_slug(source)
            post_mentions_dir = (
                self.mentions_dir / WebmentionDirection.OUT.value / post_slug
            )

        filename = self._generate_mention_filename(source, "webmention")
        filepath = post_mentions_dir / filename
        if not filepath.exists():
            return None

        if config.webmentions_hard_delete:
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

            md_content += f"[//]: # ({key}: {value})\n"

        md_content += f"\n{mention.content}\n"
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
