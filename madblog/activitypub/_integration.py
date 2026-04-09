"""
ActivityPub integration for Madblog.

Wraps pubby's file-based storage and provides a content-change callback
that publishes Article objects to followers.
"""

import base64
import hashlib
import logging
import os
import re
import json
import shutil
import subprocess
import tempfile
import threading
import mimetypes

from datetime import datetime, timezone
from pathlib import Path

from pubby import ActivityPubHandler, Object

from madblog.config import config
from madblog.constants import (
    REGEX_MERMAID_BLOCK,
    REGEX_TOC_MARKER,
)
from madblog.markdown import parse_metadata_header, render_html, resolve_relative_urls
from madblog.monitor import ChangeType
from madblog.sync import StartupSyncMixin
from madblog.tags import extract_hashtags
from madblog.visibility import resolve_visibility

from ._replies import ActivityPubRepliesMixin

logger = logging.getLogger(__name__)

_MAX_CONCURRENT_PUBLISHES = 4


class ActivityPubIntegration(ActivityPubRepliesMixin, StartupSyncMixin):
    """
    Bridges Madblog's content monitor to the pubby ActivityPub handler.

    :param handler: The pubby ``ActivityPubHandler``.
    :param pages_dir: Absolute path to the markdown pages directory.
    :param base_url: Public base URL (e.g. ``https://example.com``).
    """

    def __init__(
        self,
        handler: ActivityPubHandler,
        pages_dir: str | Path,
        base_url: str,
        *,
        content_base_url: str | None = None,
        replies_dir: str | Path | None = None,
    ):
        super().__init__()

        self.handler = handler
        self.pages_dir = str(Path(pages_dir).resolve())
        self.base_url = base_url.rstrip("/")
        self.replies_dir = str(Path(replies_dir).resolve()) if replies_dir else None

        # URL where images/assets are actually served (may differ from AP base_url)
        self.content_base_url = (content_base_url or base_url).rstrip("/")
        self.workdir = config.resolved_state_dir / "activitypub"
        self.workdir.mkdir(parents=True, exist_ok=True)

        self.deleted_urls_file = self.workdir / "deleted_urls.json"
        self.file_urls_file = self.workdir / "file_urls.json"
        self._mention_cache_file = self.workdir / "mention_cache.json"

        # StartupSyncMixin configuration
        self._sync_cache_file = self.workdir / "published_objects.json"
        self._sync_pages_dir = self.pages_dir

        # Concurrency controls for background publish threads
        self._publish_semaphore = threading.Semaphore(_MAX_CONCURRENT_PUBLISHES)
        self._active_publishes: set[str] = set()
        self._active_publishes_lock = threading.Lock()

        # Cache for resolved WebFinger mention lookups (from mixin)
        self._mention_cache: dict[tuple[str, str], str] = self._load_mention_cache()
        self._mention_cache_lock = threading.Lock()

    # -----------------------------------------------------------------
    # StartupSyncMixin hooks
    # -----------------------------------------------------------------

    def _sync_file_to_url(self, filepath: str) -> str:
        return self.file_to_url(filepath)

    def _sync_notify(self, filepath: str, is_new: bool) -> None:
        change = ChangeType.ADDED if is_new else ChangeType.EDITED
        self.on_content_change(change, filepath)

    # -----------------------------------------------------------------
    # Published-objects helpers (delegate to mixin)
    # -----------------------------------------------------------------

    def _is_published(self, url: str) -> bool:  # type: ignore
        return self._sync_is_tracked(url)

    def _mark_as_published(self, url: str, mtime: float = 0) -> None:  # type: ignore
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
    # Mention cache persistence
    # -----------------------------------------------------------------

    def _load_mention_cache(self) -> dict[tuple[str, str], str]:
        """Load the mention cache from disk."""
        try:
            if self._mention_cache_file.exists():
                with open(self._mention_cache_file, "r") as f:
                    data = json.load(f)
                # Convert string keys back to tuples
                return {tuple(k.split("|")): v for k, v in data.items()}
        except Exception:
            logger.warning("Failed to load mention cache")
        return {}

    def _save_mention_cache(self) -> None:
        """Save the mention cache to disk."""
        try:
            with self._mention_cache_lock:
                # Convert tuple keys to strings for JSON serialization
                data = {f"{k[0]}|{k[1]}": v for k, v in self._mention_cache.items()}
            with open(self._mention_cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            logger.warning("Failed to save mention cache")

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

    def file_to_url(self, filepath: str) -> str:
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

    @staticmethod
    def _parse_metadata(filepath: str) -> dict:  # type: ignore
        """Extract metadata headers from a Markdown file."""
        metadata = parse_metadata_header(filepath)
        # Post-process: parse ``published`` into a datetime when possible.
        pub = metadata.get("published")
        if isinstance(pub, str):
            try:
                metadata["published"] = datetime.fromisoformat(
                    pub.replace("Z", "+00:00")
                )
            except ValueError:
                pass  # keep as raw string
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

    @staticmethod
    def _clean_content(filepath: str) -> str:  # type: ignore
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
            if REGEX_TOC_MARKER.match(line):
                continue
            cleaned.append(line)
        return "".join(cleaned).strip()

    # -----------------------------------------------------------------
    # Rendered media extraction (LaTeX / Mermaid → PNG attachments)
    # -----------------------------------------------------------------

    # base64 LaTeX images (block and inline variants)
    _LATEX_IMG_RE = re.compile(
        r'(?:<div class="latex-block">)?'
        r'<img\s+class="latex[^"]*"\s+'
        r'id="([^"]*)"\s+src="data:image/png;base64,([^"]+)"'
        r"\s*/?>(?:</div>)?",
    )

    # Mermaid SVG wrappers: <div class="mermaid-wrapper">...</div> (outermost)
    _MERMAID_WRAPPER_RE = re.compile(
        r'<div class="mermaid-wrapper">(.+?)\n</div>',
        re.DOTALL,
    )

    # Generic inline images coming from Markdown (e.g. ![alt](url) -> <img ...>)
    _INLINE_IMG_RE = re.compile(
        r"<img\s+[^>]*?>",
        re.IGNORECASE | re.DOTALL,
    )

    _INLINE_IMG_SRC_RE = re.compile(r'\bsrc="([^"]+)"', re.IGNORECASE)
    _INLINE_IMG_ALT_RE = re.compile(r'\balt="([^"]*)"', re.IGNORECASE)

    @staticmethod
    def _guess_image_media_type(url: str) -> str | None:
        # Prefer mimetypes based on URL path extension.
        # Strip query string so mimetypes can match.
        path = url.split("?", 1)[0]
        mt, _ = mimetypes.guess_type(path)
        if mt and mt.startswith("image/"):
            return mt
        return None

    def _ensure_img_dir(self) -> Path:
        """Ensure the img directory exists and return its path."""
        img_dir = Path(config.content_dir) / "img"
        img_dir.mkdir(parents=True, exist_ok=True)
        return img_dir

    def _mermaid_to_png(self, mermaid_source: str) -> bytes | None:
        """Render Mermaid source directly to PNG via mmdc."""
        mmdc = shutil.which("mmdc")
        npx = shutil.which("npx")

        if not mmdc and not npx:
            logger.warning("Neither mmdc nor npx found; cannot render Mermaid to PNG")
            return None

        cmd = [mmdc] if mmdc else [npx, "-y", "@mermaid-js/mermaid-cli"]
        mmd_path = png_path = None

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".mmd", mode="w", delete=False
            ) as f:
                f.write(mermaid_source)
                mmd_path = f.name

            png_path = mmd_path.replace(".mmd", ".png")

            subprocess.run(
                [
                    *cmd,
                    "-i",
                    mmd_path,
                    "-o",
                    png_path,
                    "-t",
                    "default",
                    "-b",
                    "transparent",
                    "--scale",
                    "2",
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )

            with open(png_path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.warning("Mermaid → PNG rendering failed: %s", e)
            return None
        finally:
            for p in (mmd_path, png_path):
                try:
                    if p:
                        os.unlink(p)
                except OSError:
                    pass

    def _extract_media_attachments(  # type: ignore
        self, html: str, md_text: str
    ) -> tuple[str, list[dict]]:
        """
        Extract rendered LaTeX/Mermaid from HTML, save as PNGs, and return
        ``(cleaned_html, attachments)`` where attachments is a list of AP
        attachment dicts.
        """
        img_dir = self._ensure_img_dir()
        attachments: list[dict] = []
        attachment_urls: set[str] = set()
        counter = {"latex": 0, "mermaid": 0}

        def _save_png(data: bytes, prefix: str) -> str | None:
            """Save PNG bytes, return public URL."""
            content_hash = hashlib.sha256(data).hexdigest()[:16]
            filename = f"ap-{prefix}-{content_hash}.png"
            dest = img_dir / filename
            if not dest.exists():
                dest.write_bytes(data)
            # Use content_base_url for assets (where Madblog actually serves them)
            return f"{self.content_base_url}/img/{filename}"

        # --- LaTeX base64 images ---
        def _replace_latex(m: re.Match) -> str:
            b64_data = m.group(2)
            try:
                png_bytes = base64.b64decode(b64_data)
            except Exception:
                return m.group(0)

            counter["latex"] += 1
            url = _save_png(png_bytes, "latex")
            if url:
                attachments.append(
                    {
                        "type": "Image",
                        "mediaType": "image/png",
                        "url": url,
                        "name": f"LaTeX formula {counter['latex']}",
                    }
                )
                return f'<p>[<a href="{url}">formula {counter["latex"]}</a>]</p>'
            return m.group(0)

        html = self._LATEX_IMG_RE.sub(_replace_latex, html)

        # --- Mermaid diagrams (render from source via mmdc) ---
        mermaid_sources = REGEX_MERMAID_BLOCK.findall(md_text)
        mermaid_idx = 0

        def _replace_mermaid(m: re.Match) -> str:
            nonlocal mermaid_idx
            if mermaid_idx >= len(mermaid_sources):
                return m.group(0)

            source = mermaid_sources[mermaid_idx]
            mermaid_idx += 1

            png_bytes = self._mermaid_to_png(source)
            if not png_bytes:
                return m.group(0)

            counter["mermaid"] += 1
            url = _save_png(png_bytes, "mermaid")
            if url:
                attachments.append(
                    {
                        "type": "Image",
                        "mediaType": "image/png",
                        "url": url,
                        "name": f"Mermaid diagram {counter['mermaid']}",
                    }
                )
                return f'<p>[<a href="{url}">diagram {counter["mermaid"]}</a>]</p>'
            return m.group(0)

        html = self._MERMAID_WRAPPER_RE.sub(_replace_mermaid, html)

        # --- Inline images (Markdown ![alt](url) and raw <img>) ---
        img_counter = 0

        def _replace_inline_img(m: re.Match) -> str:
            nonlocal img_counter
            tag = m.group(0)

            # Skip LaTeX-rendered images (handled above)
            if 'class="latex' in tag or "class='latex" in tag:
                return tag

            src_m = self._INLINE_IMG_SRC_RE.search(tag)
            if not src_m:
                return tag

            src = src_m.group(1).strip()
            if not src or src.startswith("data:"):
                return tag

            # Avoid duplicates (keep first occurrence in content)
            if src in attachment_urls:
                return ""

            alt_m = self._INLINE_IMG_ALT_RE.search(tag)
            alt = alt_m.group(1).strip() if alt_m else ""

            img_counter += 1
            attachment_urls.add(src)

            att: dict = {
                "type": "Image",
                "url": src,
                "name": alt or f"Image {img_counter}",
            }
            mt = self._guess_image_media_type(src)
            if mt:
                att["mediaType"] = mt

            attachments.append(att)
            label = alt or f"image {img_counter}"
            return f'<p>[<a href="{src}">{label}</a>]</p>'

        html = self._INLINE_IMG_RE.sub(_replace_inline_img, html)

        return html, attachments

    # -----------------------------------------------------------------
    # Object builders
    # -----------------------------------------------------------------

    def _build_post_content(
        self,
        filepath: str,
        url: str,
        title: str,
        description: str,
        *,
        uri: str = "",
    ) -> tuple[str, str | None, list[dict]]:
        """
        Build the HTML content and optional summary for a post.

        Returns ``(html_content, summary_or_none, attachments)``.
        """
        cleaned = self._clean_content(filepath)
        summary: str | None = None

        if config.activitypub_description_only:
            cleaned = description or cleaned[:500] + "..."
        else:
            if description:
                cleaned = f"**{description}**\n\n{cleaned}"

        # Resolve relative URLs to absolute before rendering to HTML
        cleaned = resolve_relative_urls(cleaned, self.content_base_url, uri)
        html = render_html(cleaned)

        # Extract LaTeX/Mermaid rendered media → PNG attachments
        html, attachments = self._extract_media_attachments(html, cleaned)

        if (
            config.activitypub_posts_content_wrapped
            and not config.activitypub_description_only
        ):
            # CW mode: title as spoiler, description+body in content
            summary = title
        else:
            # Default: linked title prepended to body
            html = f'<p><strong><a href="{url}">{title}</a></strong></p>\n{html}'

        return html, summary, attachments

    def build_object(
        self,
        filepath: str,
        url: str,
        actor_url: str,
        public_url: str | None = None,
        *,
        allow_network: bool = False,
    ) -> tuple["Object", str] | tuple[None, None]:
        """
        Parse a markdown file and return a fully-populated
        ``(Object, activity_type)`` pair ready for publishing.

        :param url: Canonical AP object ``id`` (must share origin with actor).
        :param public_url: Human-facing URL stored in the ``url`` field of the
            AP object.  Defaults to *url* when the AP domain and blog domain
            are the same.
        :param allow_network: When ``True``, WebFinger HTTP lookups are
            permitted for uncached mentions.  Pass ``True`` only from
            background threads; the request-serving path must use the
            default (``False``) so it never blocks.
        :return: Tuple of ``(Object, activity_type)`` or ``(None, None)`` if
            the post should not be federated (draft visibility).
        """
        public_url = public_url or url
        metadata = self._parse_metadata(filepath)
        title = metadata.get("title") or self._extract_title(filepath)
        description = metadata.get("description", "")

        published = metadata.get("published")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None

        content, summary, attachments = self._build_post_content(
            filepath,
            public_url,
            title,
            description,
            uri=metadata.get("uri", ""),
        )

        # Resolve @user@domain mentions
        raw_text = self._clean_content(filepath)
        mentions = self._resolve_mentions(raw_text, allow_network=allow_network)
        mention_tags = [m.to_tag() for m in mentions]
        mention_cc = [m.actor_url for m in mentions]

        # Extract #hashtags and build Hashtag tags
        hashtags = extract_hashtags(raw_text)
        hashtag_tags = self._build_hashtag_tags(hashtags)

        # Make hashtag links absolute in HTML content
        content = self._make_hashtag_links_absolute(content)

        # Resolve visibility and build addressing
        visibility = resolve_visibility(metadata)
        addressing = self._build_addressing(visibility, mention_cc)
        if addressing is None:
            # Draft visibility - do not federate
            logger.info("Skipping federation for draft: %s", url)
            return None, None

        to_field, cc_field = addressing

        activity_type = "Update" if self._is_published(url) else "Create"
        quote_control, quote_policy, interaction_policy = self._build_quote_policy()

        obj = Object(
            id=url,
            type=config.activitypub_object_type,
            name=title,
            content=content,
            url=public_url,
            attributed_to=actor_url,
            published=published or datetime.now(timezone.utc),
            updated=datetime.now(timezone.utc),
            summary=summary,
            to=to_field,
            cc=cc_field,
            tag=mention_tags + hashtag_tags,
            attachment=attachments,
            quote_control=quote_control,
            quote_policy=quote_policy,
            interaction_policy=interaction_policy,
        )

        if not config.activitypub_description_only:
            obj.media_type = "text/html"

        # Language: per-post metadata overrides global config
        obj.language = metadata.get("language", config.language)

        return obj, activity_type

    # -----------------------------------------------------------------
    # Like activity ID tracking for articles (file_urls with #like suffix)
    # -----------------------------------------------------------------

    def _set_like_id(self, filepath: str, activity_id: str, object_url: str) -> None:
        """Store the Like activity ID and object URL for an article file."""
        file_urls = self._load_file_urls()
        key = os.path.relpath(filepath, self.pages_dir) + "#like"
        file_urls[key] = activity_id
        file_urls[key + "-object"] = object_url
        self._save_file_urls(file_urls)

    def _get_like_id(self, filepath: str) -> str | None:
        """Get the stored Like activity ID for an article file."""
        key = os.path.relpath(filepath, self.pages_dir) + "#like"
        return self._load_file_urls().get(key)

    def _get_like_object(self, filepath: str) -> str | None:
        """Get the stored like-of object URL for an article file."""
        key = os.path.relpath(filepath, self.pages_dir) + "#like-object"
        return self._load_file_urls().get(key)

    def _remove_like_id(self, filepath: str) -> None:
        """Remove the stored Like activity ID and object URL for an article file."""
        file_urls = self._load_file_urls()
        key = os.path.relpath(filepath, self.pages_dir) + "#like"
        file_urls.pop(key, None)
        file_urls.pop(key + "-object", None)
        self._save_file_urls(file_urls)

    # -----------------------------------------------------------------
    # Like publish / delete handlers for articles
    # -----------------------------------------------------------------

    def _handle_like_publish(self, filepath: str, actor_url: str) -> None:
        """Build and publish a Like activity for an article with like-of."""
        metadata = self._parse_metadata(filepath)
        like_of = metadata.get("like-of")
        if not like_of:
            return

        old_like_id = self._get_like_id(filepath)
        old_object = self._get_like_object(filepath) if old_like_id else None

        # Skip if we already have a Like for the same target URL
        if old_like_id and old_object == like_of:
            logger.debug("Like already published for %s, skipping", like_of)
            return

        # Undo any previously published Like for this file (target changed)
        if old_like_id:
            self._publish_undo_like(old_like_id, actor_url, object_url=old_object)

        like_activity = self._publish_like(like_of)
        self._set_like_id(filepath, like_activity["id"], like_of)

    def _handle_like_delete(self, filepath: str, actor_url: str) -> None:
        """Publish an Undo Like for a deleted article file."""
        like_id = self._get_like_id(filepath)
        if not like_id:
            return

        object_url = self._get_like_object(filepath)
        self._publish_undo_like(like_id, actor_url, object_url=object_url)
        self._remove_like_id(filepath)

    # -----------------------------------------------------------------
    # Content-change handlers
    # -----------------------------------------------------------------

    def _handle_delete(self, filepath: str, url: str, actor_url: str) -> None:
        """Publish a Delete activity and clean up caches."""
        base_rel = os.path.relpath(filepath, self.pages_dir).rsplit(".", 1)[0]

        def _cleanup():
            # Use base_url (AP domain) for collision tracking, matching file_to_url()
            self._mark_as_deleted(f"{self.base_url}/article/{base_rel}")
            self._remove_file_url(filepath)

        self._publish_delete(
            url,
            actor_url,
            config.activitypub_object_type,
            extra_cleanup=_cleanup,
        )

    def _handle_publish(self, filepath: str, url: str, actor_url: str) -> None:
        """
        Build and publish a Create or Update activity.

        WebFinger mention resolution happens here (``allow_network=True``)
        inside a background thread — never on the request-serving path.
        The file is marked as processed **before** delivery so that a
        crash or restart will not re-queue it.

        Delivery retries are handled internally by pubby's
        ``OutboxProcessor`` (exponential back-off per inbox), so this
        method does **not** add its own retry loop.
        """
        base_rel = os.path.relpath(filepath, self.pages_dir).rsplit(".", 1)[0]
        public_url = f"{self.content_base_url}/article/{base_rel}"

        self._build_and_publish(
            filepath,
            url,
            lambda: self.build_object(
                filepath, url, actor_url, public_url=public_url, allow_network=True
            ),
        )

    def on_content_change(self, change_type: ChangeType, filepath: str) -> None:
        """
        Callback for :class:`ContentMonitor`.

        On create/edit: publish a Note/Article to followers in a
        background thread so that slow WebFinger look-ups or delivery
        failures do not block the content-monitor loop.  If the article
        contains ``like-of`` metadata, a Like activity is also published.

        At most :data:`_MAX_CONCURRENT_PUBLISHES` threads run in
        parallel, and duplicate requests for the same URL are dropped.

        On delete: send a Delete activity (synchronous — no mentions
        involved).  If a Like was published, also send Undo Like.
        """
        # Skip files under replies/ - handled by on_reply_change
        if self.replies_dir and filepath.startswith(self.replies_dir + os.sep):
            return

        # Skip ABOUT.md - it's the About page, not a regular article
        if os.path.basename(filepath) == "ABOUT.md":
            return

        url = self.file_to_url(filepath)
        actor_url = f"{self.base_url}{self.handler.actor_path}"

        if change_type.value == "deleted":
            self._handle_like_delete(filepath, actor_url)
            self._handle_delete(filepath, url, actor_url)
        else:
            # Always publish the Article
            self._spawn_guarded_publish(
                url,
                lambda: self._handle_publish(filepath, url, actor_url),
                f"ap-publish-{os.path.basename(filepath)}",
            )

            # Also publish a Like if like-of is present
            metadata = self._parse_metadata(filepath)
            if metadata.get("like-of"):
                self._spawn_guarded_publish(
                    url + "#like",
                    lambda: self._handle_like_publish(filepath, actor_url),
                    f"ap-like-{os.path.basename(filepath)}",
                )
