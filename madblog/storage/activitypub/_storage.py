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

import requests
from pubby import ActivityPubHandler, Object
from markdown import markdown

from ...config import config
from ...activitypub import MarkdownActivityPubMentions
from ...autolink import MarkdownAutolink
from ...latex import MarkdownLatex
from ...mermaid import MarkdownMermaid
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

    # -- StartupSyncMixin hooks --

    def _sync_file_to_url(self, filepath: str) -> str:
        return self._file_to_url(filepath)

    def _sync_notify(self, filepath: str, is_new: bool) -> None:
        from madblog.monitor import ChangeType

        change = ChangeType.ADDED if is_new else ChangeType.EDITED
        self.on_content_change(change, filepath)

    # -- Convenience aliases (keep existing call-sites working) --

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
        current_time = int(datetime.now(timezone.utc).timestamp())
        cutoff_time = current_time - (max_age_hours * 3600)

        # Filter out old entries and return recent ones
        recent = {url for url, timestamp in deleted.items() if timestamp > cutoff_time}

        # Clean up old entries
        if len(recent) != len(deleted):
            fresh_deleted = {url: ts for url, ts in deleted.items() if ts > cutoff_time}
            self._save_recently_deleted_urls(fresh_deleted)

        return recent

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
        rel_path = os.path.relpath(filepath, self.pages_dir)
        file_urls[rel_path] = url
        self._save_file_urls(file_urls)

    def _get_file_url(self, filepath: str) -> str | None:
        """Get the stored URL for a file path, if any."""
        file_urls = self._load_file_urls()
        rel_path = os.path.relpath(filepath, self.pages_dir)
        return file_urls.get(rel_path)

    def _remove_file_url(self, filepath: str) -> None:
        """Remove the URL mapping for a deleted file."""
        file_urls = self._load_file_urls()
        rel_path = os.path.relpath(filepath, self.pages_dir)
        file_urls.pop(rel_path, None)
        self._save_file_urls(file_urls)

    def _file_to_url(self, filepath: str) -> str:
        # Check if we already have a stored URL for this file
        stored_url = self._get_file_url(filepath)
        if stored_url:
            return stored_url

        # Generate the base URL
        rel = os.path.relpath(filepath, self.pages_dir).rsplit(".", 1)[0]
        base_url = f"{self.base_url}/article/{rel}"

        # If this URL was recently deleted, append timestamp to avoid collisions
        if base_url in self._get_recently_deleted_urls():
            timestamp = int(datetime.now(timezone.utc).timestamp())
            collision_url = f"{base_url}?v={timestamp}"
            # Store this collision-avoiding URL for future edits
            self._set_file_url(filepath, collision_url)
            logger.info(
                "Generated collision-avoiding URL for restored content: %s",
                collision_url,
            )
            return collision_url

        # Store the normal URL for future edits
        self._set_file_url(filepath, base_url)
        return base_url

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

    def _read_content(self, filepath: str) -> str:
        """Read the raw text content of a file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def _clean_content_for_activitypub(self, filepath: str) -> str:
        """Read and clean content for ActivityPub, removing metadata headers."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            cleaned_lines = []

            for line in lines:
                # Always skip metadata headers, regardless of position
                if (
                    line.startswith("[//]: #")
                    or line.startswith("---")
                    or (line.strip().startswith("---") and line.strip().endswith("---"))
                ):
                    continue

                # Include everything else (including titles, content, etc.)
                cleaned_lines.append(line)

            return "".join(cleaned_lines).strip()
        except OSError:
            return ""

    def _render_markdown_to_html(self, content: str) -> str:
        """Convert markdown content to HTML using Madblog's extensions."""
        try:
            return markdown(
                content,
                extensions=[
                    "fenced_code",
                    "codehilite",
                    "tables",
                    "toc",
                    "attr_list",
                    "sane_lists",
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
            logger.warning(f"Failed to render markdown to HTML: {e}")
            return content  # Return original content as fallback

    def _resolve_actor_url(self, username: str, domain: str) -> str:
        """
        Resolve the ActivityPub actor URL for ``@username@domain`` via
        WebFinger.  Falls back to ``https://domain/@username`` on failure.
        """
        fallback = f"https://{domain}/@{username}"
        try:
            resp = requests.get(
                f"https://{domain}/.well-known/webfinger",
                params={"resource": f"acct:{username}@{domain}"},
                headers={"Accept": "application/jrd+json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            for link in data.get("links", []):
                if (
                    link.get("rel") == "self"
                    and link.get("type", "").startswith("application/")
                ):
                    return link["href"]
        except Exception:
            logger.warning(
                "WebFinger lookup failed for @%s@%s, using fallback",
                username, domain,
            )
        return fallback

    def on_content_change(self, change_type, filepath: str) -> None:
        """
        Callback for :class:`ContentMonitor`.

        On create/edit: publish an Article to followers.
        On delete: send a Delete activity.
        """
        url = self._file_to_url(filepath)
        actor_url = f"{self.base_url}{self.handler.actor_path}"

        if change_type.value == "deleted":
            # Mark base URL as recently deleted to avoid collisions
            base_url = f"{self.base_url}/article/{os.path.relpath(filepath, self.pages_dir).rsplit('.', 1)[0]}"
            self._mark_as_deleted(base_url)

            # Remove the file URL mapping since the file is being deleted
            self._remove_file_url(filepath)

            obj = Object(
                id=url,
                type=config.activitypub_object_type,
                attributed_to=actor_url,
                to=["https://www.w3.org/ns/activitystreams#Public"],  # Public timeline
                cc=[self.handler.followers_url],  # Send to followers
            )

            # Always remove from cache, even if delete fails
            self._sync_unmark(url)

            try:
                self.handler.publish_object(obj, activity_type="Delete")
                logger.info("Published Delete for %s", url)
            except Exception:
                logger.exception("Failed to publish Delete for %s", url)
            return

        metadata = self._parse_metadata(filepath)
        title = metadata.get("title") or self._extract_title(filepath)
        description = metadata.get("description", "")
        published = metadata.get("published")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None

        # Choose content based on config setting
        if config.activitypub_description_only:
            # Use description as main content, with a snippet as summary
            post_content = (
                description
                or self._clean_content_for_activitypub(filepath)[:500] + "..."
            )
            post_summary = (
                description[:200] + "..." if len(description) > 200 else description
            )
        else:
            # Use full article content (default behavior) - render as HTML
            cleaned_content = self._clean_content_for_activitypub(filepath)
            post_content = self._render_markdown_to_html(cleaned_content)
            post_summary = description  # Keep description as summary for previews

        # Extract @user@domain mentions for ActivityPub tags + cc
        mention_pattern = re.compile(
            r"(?<!\w)@([a-zA-Z0-9_.-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
        )
        raw_content = self._clean_content_for_activitypub(filepath)
        mentions = mention_pattern.findall(raw_content)  # [(user, domain), ...]

        mention_tags = []
        mention_actor_urls = []
        for username, domain in mentions:
            actor_href = self._resolve_actor_url(username, domain)
            mention_tags.append(
                {
                    "type": "Mention",
                    "href": actor_href,
                    "name": f"@{username}@{domain}",
                }
            )
            mention_actor_urls.append(actor_href)

        # More efficient update detection using local tracking
        activity_type = "Update" if self._is_published(url) else "Create"

        obj = Object(
            id=url,
            type=config.activitypub_object_type,
            name=title,
            content=post_content,
            url=url,
            attributed_to=actor_url,
            published=published or datetime.now(timezone.utc),
            updated=datetime.now(timezone.utc),  # Required for Update activities
            summary=post_summary,
            to=["https://www.w3.org/ns/activitystreams#Public"],  # Public timeline
            cc=[self.handler.followers_url] + mention_actor_urls,
            tag=mention_tags,
        )

        # Add media type for HTML content (ActivityPub standard)
        if not config.activitypub_description_only:
            obj.media_type = "text/html"

        try:
            self.handler.publish_object(obj, activity_type=activity_type)
            # Mark as published with current file mtime
            try:
                mtime = os.path.getmtime(filepath)
            except OSError:
                mtime = 0
            self._mark_as_published(url, mtime)
            logger.info("Published %s for %s", activity_type, url)
        except Exception:
            logger.exception("Failed to publish %s for %s", activity_type, url)
