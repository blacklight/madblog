import hashlib
import re

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse


class WebmentionsStorage(ABC):
    """
    Abstract base class for Webmention storage backends.
    """

    @abstractmethod
    def store_webmention(
        self, source: str, target: str, data: dict | None = None
    ) -> Any:
        """
        Store a webmention.

        :param source: The source URL of the webmention
        :param target: The target URL of the webmention
        :param data: Optional dictionary with verified data from the source
        """

    @staticmethod
    def parse_metadata(content: str) -> dict:
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

    def __init__(self, reactions_dir: str = "reactions"):
        from ..config import config

        self.reactions_dir = Path(config.content_dir) / reactions_dir
        self.reactions_dir.mkdir(exist_ok=True, parents=True)
        self._resource_locks = defaultdict(RLock)

    def store_webmention(self, source: str, target: str, data: dict | None = None):
        """
        Store Webmention as Markdown file
        """

        # Extract post slug from target URL
        post_slug = self._extract_post_slug(target)

        # Create post reaction directory
        post_reactions_dir = self.reactions_dir / post_slug
        post_reactions_dir.mkdir(exist_ok=True)

        # Generate safe filename
        filename = self._generate_reaction_filename(source, "webmention")
        filepath = post_reactions_dir / filename

        # Prepare metadata
        metadata = {
            "type": "webmention",
            "source": source,
            "target": target,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "verified": bool(data),
            "status": "pending",  # pending, approved, spam
        }

        # Add parsed data if available
        if data:
            metadata.update(
                {
                    "author_name": data.get("author_name", ""),
                    "author_url": data.get("author_url", ""),
                    "content": data.get("content", ""),
                    "mention_type": data.get(
                        "mention_type", "mention"
                    ),  # mention, reply, like, repost
                    "published": data.get("published", ""),
                }
            )

        with self._resource_locks[filepath]:
            # Parse existing file metadata if file exists
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    existing_content = f.read()

                existing_metadata = self.parse_metadata(existing_content)
                if existing_metadata:
                    metadata["created_at"] = existing_metadata.get(
                        "created_at", metadata["created_at"]
                    )

            # Write as Markdown with YAML frontmatter
            content = self._format_webmention_markdown(metadata, data)

            # Atomic write
            self._atomic_write(filepath, content)

        return filepath

    @staticmethod
    def _format_webmention_markdown(metadata: dict, verified_data: dict | None = None):
        """
        Format Webmention as Markdown and include metadata as comments.
        """

        md_content = ""

        for key, value in metadata.items():
            if key == "content" or value is None:
                continue

            md_content += f"[//]: # ({key}: {value})\n"

        if verified_data and verified_data.get("content"):
            md_content += f"\n{verified_data['content']}\n"

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
    def _generate_reaction_filename(
        cls, source_url: str, reaction_type: str = "webmention"
    ):
        """
        Generate unique, safe filename for reactions.
        """
        url_hash = hashlib.md5(source_url.encode()).hexdigest()[:8]

        # Extract domain for readability
        domain = urlparse(source_url).netloc.replace(".", "-")
        domain = cls._safe_filename(domain)

        return f"{reaction_type}-{domain}-{url_hash}.md"

    @staticmethod
    def _safe_filename(text: str, max_length: int = 50) -> str:
        """
        Generate safe filenames from Webmention source URLs.
        """
        # Remove/replace unsafe characters
        safe = re.sub(r"[^\w\s-]", "", text)
        safe = re.sub(r"[-\s]+", "-", safe)
        return safe[:max_length].strip("-")
