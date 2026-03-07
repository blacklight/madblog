"""
ActivityPub integration for Madblog.

Wraps pubby's file-based storage and provides a content-change callback
that publishes Article objects to followers.
"""

import logging
import os
import re
import json

from datetime import datetime, timezone
from pathlib import Path

from markdown import markdown
from pubby import ActivityPubHandler, Object, extract_mentions

from ...config import config
from ...activitypub import MarkdownActivityPubMentions
from ...autolink import MarkdownAutolink
from ...latex import MarkdownLatex
from ...mermaid import MarkdownMermaid
from ...monitor import ChangeType
from .._sync import StartupSyncMixin
from ...tasklist import MarkdownTaskList
from ...toc import MarkdownTocMarkers
from ...tags import MarkdownTags

logger = logging.getLogger(__name__)


class ActivityPubIntegration(StartupSyncMixin):
    """
    Bridges Madblog's content monitor to the pubby ActivityPub handler.

    :param handler: The pubby ``ActivityPubHandler``.
    :param pages_dir: Absolute path to the markdown pages directory.
    :param base_url: Public base URL (e.g. ``https://example.com``).
    """

    _metadata_regex = re.compile(r"^\[//]: # \(([^:]+):\s*(.*)\)\s*$")

    _MARKDOWN_EXTENSIONS = [
        "fenced_code",
        "codehilite",
        "tables",
        "toc",
        "attr_list",
        "sane_lists",
    ]

    def __init__(
        self,
        handler: ActivityPubHandler,
        pages_dir: str | Path,
        base_url: str,
    ):
        self.handler = handler
        self.pages_dir = str(Path(pages_dir).resolve())
        self.base_url = base_url.rstrip("/")
        self.workdir = Path(config.content_dir) / ".madblog" / "activitypub"
        self.workdir.mkdir(parents=True, exist_ok=True)

        self.deleted_urls_file = self.workdir / "deleted_urls.json"
        self.file_urls_file = self.workdir / "file_urls.json"

        # StartupSyncMixin configuration
        self._sync_cache_file = self.workdir / "published_objects.json"
        self._sync_pages_dir = self.pages_dir

    # -----------------------------------------------------------------
    # StartupSyncMixin hooks
    # -----------------------------------------------------------------

    def _sync_file_to_url(self, filepath: str) -> str:
        return self._file_to_url(filepath)

    def _sync_notify(self, filepath: str, is_new: bool) -> None:
        change = ChangeType.ADDED if is_new else ChangeType.EDITED
        self.on_content_change(change, filepath)

    # -----------------------------------------------------------------
    # Published-objects helpers (delegate to mixin)
    # -----------------------------------------------------------------

    def _is_published(self, url: str) -> bool:
        return self._sync_is_tracked(url)

    def _mark_as_published(self, url: str, mtime: float = 0) -> None:
        self._sync_mark(url, mtime)

    def debug_published_cache(self) -> dict:
        return {
            "cache_file": str(self._sync_cache_file),
            "cache_exists": self._sync_cache_file.exists(),
            "published_urls": self._load_sync_cache(),
        }

    def reset_published_cache(self) -> None:
        self._sync_reset()

    # -----------------------------------------------------------------
    # Deleted-URL tracking (collision avoidance)
    # -----------------------------------------------------------------

    def _load_recently_deleted_urls(self) -> dict:
        """Load recently deleted URLs with timestamps."""
        try:
            if self.deleted_urls_file.exists():
                with open(self.deleted_urls_file, "r") as f:
                    return json.load(f)
        except Exception:
            logger.warning("Failed to load deleted URLs cache")
        return {}

    def _save_recently_deleted_urls(self, deleted: dict) -> None:
        """Save recently deleted URLs with timestamps."""
        try:
            with open(self.deleted_urls_file, "w") as f:
                json.dump(deleted, f, indent=2)
        except Exception:
            logger.warning("Failed to save deleted URLs cache")

    def _mark_as_deleted(self, url: str) -> None:
        """Mark a URL as recently deleted."""
        deleted = self._load_recently_deleted_urls()
        deleted[url] = int(datetime.now(timezone.utc).timestamp())
        self._save_recently_deleted_urls(deleted)

    def _get_recently_deleted_urls(self, max_age_hours: int = 24) -> set:
        """Get URLs deleted within the last N hours (default 24)."""
        deleted = self._load_recently_deleted_urls()
        cutoff = int(datetime.now(timezone.utc).timestamp()) - (max_age_hours * 3600)
        recent = {url for url, ts in deleted.items() if ts > cutoff}
        if len(recent) != len(deleted):
            self._save_recently_deleted_urls(
                {url: ts for url, ts in deleted.items() if ts > cutoff}
            )
        return recent

    # -----------------------------------------------------------------
    # File ↔ URL mapping (persistent across edits)
    # -----------------------------------------------------------------

    def _load_file_urls(self) -> dict:
        """Load file path -> URL mappings."""
        try:
            if self.file_urls_file.exists():
                with open(self.file_urls_file, "r") as f:
                    return json.load(f)
        except Exception:
            logger.warning("Failed to load file URLs cache")
        return {}

    def _save_file_urls(self, file_urls: dict) -> None:
        """Save file path -> URL mappings."""
        try:
            with open(self.file_urls_file, "w") as f:
                json.dump(file_urls, f, indent=2)
        except Exception:
            logger.warning("Failed to save file URLs cache")

    def _set_file_url(self, filepath: str, url: str) -> None:
        """Set the URL for a specific file path."""
        file_urls = self._load_file_urls()
        file_urls[os.path.relpath(filepath, self.pages_dir)] = url
        self._save_file_urls(file_urls)

    def _get_file_url(self, filepath: str) -> str | None:
        """Get the URL for a specific file path."""
        return self._load_file_urls().get(os.path.relpath(filepath, self.pages_dir))

    def _remove_file_url(self, filepath: str) -> None:
        """Remove the URL mapping for a deleted file."""
        file_urls = self._load_file_urls()
        file_urls.pop(os.path.relpath(filepath, self.pages_dir), None)
        self._save_file_urls(file_urls)

    def _file_to_url(self, filepath: str) -> str:
        stored = self._get_file_url(filepath)
        if stored:
            return stored

        # Generate the base URL
        rel = os.path.relpath(filepath, self.pages_dir).rsplit(".", 1)[0]
        base_url = f"{self.base_url}/article/{rel}"

        # If this URL was recently deleted, append timestamp to avoid collisions
        if base_url in self._get_recently_deleted_urls():
            ts = int(datetime.now(timezone.utc).timestamp())
            collision_url = f"{base_url}?v={ts}"
            # Store this collision-avoiding URL to prevent future edits from
            # being treated as different posts
            self._set_file_url(filepath, collision_url)
            logger.info("Collision-avoiding URL: %s", collision_url)
            return collision_url

        self._set_file_url(filepath, base_url)
        return base_url

    # -----------------------------------------------------------------
    # Markdown / metadata helpers
    # -----------------------------------------------------------------

    def _parse_metadata(self, filepath: str) -> dict:
        """Extract metadata headers from a Markdown file."""
        metadata: dict = {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip() or re.match(r"(^---\s*$)|(^#\s+.*)", line):
                        continue

                    m = self._metadata_regex.match(line)
                    if not m:
                        break

                    key, value = m.group(1), m.group(2)
                    if key == "published":
                        try:
                            metadata[key] = datetime.fromisoformat(
                                value.replace("Z", "+00:00")
                            )
                        except ValueError:
                            metadata[key] = value
                    else:
                        metadata[key] = value
        except OSError:
            pass

        return metadata

    def _extract_title(self, filepath: str) -> str:
        """Extract the first H1 title from a Markdown file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^#\s+\[?([^\]]+)\]?", line)
                    if m:
                        return m.group(1).strip()
        except OSError:
            pass

        return os.path.splitext(os.path.basename(filepath))[0]

    def _clean_content(self, filepath: str) -> str:
        """Read markdown, strip metadata headers and the top-level heading."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return ""

        cleaned: list[str] = []
        for line in lines:
            if (
                line.startswith("[//]: #")
                or line.startswith("---")
                or (line.strip().startswith("---") and line.strip().endswith("---"))
            ):
                continue
            if re.match(r"^#\s+", line) and not cleaned:
                continue
            cleaned.append(line)
        return "".join(cleaned).strip()

    def _render_html(self, md_text: str) -> str:
        """Convert markdown to HTML using Madblog's full extension pipeline."""
        try:
            return markdown(
                md_text,
                extensions=[
                    *self._MARKDOWN_EXTENSIONS,
                    MarkdownAutolink(),
                    MarkdownTaskList(),
                    MarkdownTocMarkers(),
                    MarkdownLatex(),
                    MarkdownMermaid(),
                    MarkdownTags(),
                    MarkdownActivityPubMentions(),
                ],
            )
        except Exception as e:
            logger.warning("Markdown → HTML failed: %s", e)
            return md_text

    # -----------------------------------------------------------------
    # Object builders
    # -----------------------------------------------------------------

    def _build_post_content(
        self,
        filepath: str,
        url: str,
        title: str,
        description: str,
    ) -> tuple[str, str | None]:
        """
        Build the HTML content and optional summary for a post.

        Returns ``(html_content, summary_or_none)``.
        """
        cleaned = self._clean_content(filepath)
        summary: str | None = None

        if config.activitypub_description_only:
            cleaned = description or cleaned[:500] + "..."
        else:
            if description:
                cleaned = f"**{description}**\n\n{cleaned}"

        html = self._render_html(cleaned)

        if (
            config.activitypub_posts_content_wrapped
            and not config.activitypub_description_only
        ):
            # CW mode: title as spoiler, description+body in content
            summary = title
        else:
            # Default: linked title prepended to body
            html = f'<p><strong><a href="{url}">{title}</a></strong></p>\n{html}'

        return html, summary

    def _build_object(
        self,
        filepath: str,
        url: str,
        actor_url: str,
    ) -> tuple[Object, str]:
        """
        Parse a markdown file and return a fully-populated
        ``(Object, activity_type)`` pair ready for publishing.
        """
        metadata = self._parse_metadata(filepath)
        title = metadata.get("title") or self._extract_title(filepath)
        description = metadata.get("description", "")

        published = metadata.get("published")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None

        content, summary = self._build_post_content(
            filepath,
            url,
            title,
            description,
        )

        # Resolve @user@domain mentions via WebFinger (Pubby utility)
        raw_text = self._clean_content(filepath)
        mentions = extract_mentions(raw_text)
        mention_tags = [m.to_tag() for m in mentions]
        mention_cc = [m.actor_url for m in mentions]

        activity_type = "Update" if self._is_published(url) else "Create"

        obj = Object(
            id=url,
            type=config.activitypub_object_type,
            name=title,
            content=content,
            url=url,
            attributed_to=actor_url,
            published=published or datetime.now(timezone.utc),
            updated=datetime.now(timezone.utc),
            summary=summary,
            to=["https://www.w3.org/ns/activitystreams#Public"],
            cc=[self.handler.followers_url] + mention_cc,
            tag=mention_tags,
        )

        if not config.activitypub_description_only:
            obj.media_type = "text/html"

        return obj, activity_type

    # -----------------------------------------------------------------
    # Content-change handlers
    # -----------------------------------------------------------------

    def _handle_delete(self, filepath: str, url: str, actor_url: str) -> None:
        """Publish a Delete activity and clean up caches."""
        base_rel = os.path.relpath(filepath, self.pages_dir).rsplit(".", 1)[0]
        self._mark_as_deleted(f"{self.base_url}/article/{base_rel}")
        self._remove_file_url(filepath)
        self._sync_unmark(url)

        obj = Object(
            id=url,
            type=config.activitypub_object_type,
            attributed_to=actor_url,
            to=["https://www.w3.org/ns/activitystreams#Public"],
            cc=[self.handler.followers_url],
        )

        try:
            self.handler.publish_object(obj, activity_type="Delete")
            logger.info("Published Delete for %s", url)
        except Exception:
            logger.exception("Failed to publish Delete for %s", url)

    def _handle_publish(self, filepath: str, url: str, actor_url: str) -> None:
        """Build and publish a Create or Update activity."""
        obj, activity_type = self._build_object(filepath, url, actor_url)

        try:
            self.handler.publish_object(obj, activity_type=activity_type)
            try:
                mtime = os.path.getmtime(filepath)
            except OSError:
                mtime = 0
            self._mark_as_published(url, mtime)
            logger.info("Published %s for %s", activity_type, url)
        except Exception:
            logger.exception("Failed to publish %s for %s", activity_type, url)

    def on_content_change(self, change_type: ChangeType, filepath: str) -> None:
        """
        Callback for :class:`ContentMonitor`.

        On create/edit: publish a Note/Article to followers.
        On delete: send a Delete activity.
        """
        url = self._file_to_url(filepath)
        actor_url = f"{self.base_url}{self.handler.actor_path}"

        if change_type.value == "deleted":
            self._handle_delete(filepath, url, actor_url)
        else:
            self._handle_publish(filepath, url, actor_url)
