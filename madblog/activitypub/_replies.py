import logging
import os

from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

from pubby import Object

from madblog.config import config
from madblog.markdown import render_html, resolve_relative_urls
from madblog.monitor import ChangeType
from madblog.tags import extract_hashtags

from madblog.visibility import resolve_visibility
from ._publish import ActivityPubPublishMixin

logger = logging.getLogger(__name__)


class ActivityPubRepliesMixin(ActivityPubPublishMixin):
    """
    Mixin for ActivityPub integration for replies.

    Inherits common publish utilities from ActivityPubPublishMixin.
    """

    replies_dir: str | None
    _get_recently_deleted_urls: Callable[..., set]
    _load_file_urls: Callable[..., dict]
    _mark_as_deleted: Callable[..., None]
    _save_file_urls: Callable[..., None]
    _sync_directory: Callable[..., None]

    # -----------------------------------------------------------------
    # Reply file ↔ URL mapping (persistent across edits)
    # -----------------------------------------------------------------

    def _set_reply_file_url(self, filepath: str, url: str) -> None:
        """Set the URL for a specific reply file path."""
        file_urls = self._load_file_urls()
        key = "reply/" + os.path.relpath(filepath, self.replies_dir)
        file_urls[key] = url
        self._save_file_urls(file_urls)

    def _get_reply_file_url(self, filepath: str) -> str | None:
        """Get the URL for a specific reply file path."""
        key = "reply/" + os.path.relpath(filepath, self.replies_dir)
        return self._load_file_urls().get(key)

    def _remove_reply_file_url(self, filepath: str) -> None:
        """Remove the URL mapping for a deleted reply file."""
        file_urls = self._load_file_urls()
        key = "reply/" + os.path.relpath(filepath, self.replies_dir)
        file_urls.pop(key, None)
        self._save_file_urls(file_urls)

    def reply_file_to_url(self, filepath: str) -> str:
        """
        Convert a reply file path to its public URL.

        If this URL was recently deleted, appends ``?v=<timestamp>`` to avoid
        collisions with AP implementations that cache deleted object IDs.

        :param filepath: Path like ``replies/<article-slug>/<reply-slug>.md``
            or ``replies/<reply-slug>.md`` for top-level unlisted posts.
        :return: URL like ``https://example.com/reply/<article-slug>/<reply-slug>``
            or ``https://example.com/reply/<reply-slug>`` for top-level posts.
        """
        if not self.replies_dir:
            raise ValueError("replies_dir not configured")

        rel = os.path.relpath(filepath, self.replies_dir).rsplit(".", 1)[0]
        base_url = f"{self.base_url}/reply/{rel}"

        stored = self._get_reply_file_url(filepath)
        if stored:
            # Detect stale URLs with "None" from before top-level support
            if "/None/" in stored or stored.endswith("/None"):
                logger.info("Clearing stale URL mapping with None: %s", stored)
                self._remove_reply_file_url(filepath)
            else:
                return stored

        if base_url in self._get_recently_deleted_urls():
            ts = int(datetime.now(timezone.utc).timestamp())
            collision_url = f"{base_url}?v={ts}"
            self._set_reply_file_url(filepath, collision_url)
            logger.info("Collision-avoiding URL for reply: %s", collision_url)
            return collision_url

        self._set_reply_file_url(filepath, base_url)
        return base_url

    def _article_slug_from_reply_path(self, filepath: str) -> str | None:
        """
        Extract the article slug from a reply file path.

        :param filepath: Path like ``<replies_dir>/<article-slug>/<reply>.md``
        :return: The article slug, or ``None`` if the path has no parent dir.
        """
        if not self.replies_dir:
            return None

        rel = os.path.relpath(filepath, self.replies_dir)
        parts = rel.split(os.sep)
        return parts[0] if len(parts) > 1 else None

    def _parse_reply_metadata(self, filepath: str) -> dict:
        """
        Extract metadata from a reply Markdown file.

        If ``reply-to`` is not set explicitly, it is derived from the
        directory structure: ``replies/<article-slug>/…`` maps to the
        AP object URL ``{base_url}/article/<article-slug>``.

        Top-level files (unlisted posts) intentionally have no reply-to.
        """
        metadata = self._parse_metadata(filepath)
        if "reply-to" not in metadata:
            article_slug = self._article_slug_from_reply_path(filepath)
            if article_slug:
                metadata["reply-to"] = f"{self.base_url}/article/{article_slug}"
                logger.debug(
                    "Derived reply-to %s from directory structure",
                    metadata["reply-to"],
                )
            # Top-level files (unlisted posts) are valid without reply-to
        return metadata

    def _resolve_reply_target_actor(self, reply_to_url: str) -> str | None:
        """
        Look up the actor URL for a reply-to URL.

        If the reply-to points to a stored AP interaction, return the
        source_actor_id so the reply can be CC'd to them.
        """
        try:
            interaction = self.handler.storage.get_interaction_by_object_id(
                reply_to_url
            )
            if interaction:
                return interaction.source_actor_id
        except Exception:
            logger.debug("Could not resolve actor for reply-to %s", reply_to_url)
        return None

    def _resolve_reply_target_mention(
        self, reply_to_url: str
    ) -> tuple[str, str, str] | None:
        """
        Resolve the FQN mention for a reply-to target.

        :param reply_to_url: The URL being replied to.
        :return: Tuple of ``(username, domain, actor_url)`` or ``None`` if
            the target is not an AP interaction or cannot be resolved.
        """
        try:
            interaction = self.handler.storage.get_interaction_by_object_id(
                reply_to_url
            )
            if not interaction:
                return None

            actor_url = interaction.source_actor_id
            if not actor_url:
                return None

            # Extract domain from actor URL
            parsed = urlparse(actor_url)
            domain = parsed.netloc
            if not domain:
                return None

            # Try to get username from cached actor data
            actor_data = self.handler.storage.get_cached_actor(actor_url)
            if actor_data:
                username = actor_data.get("preferredUsername", "")
                if username:
                    return username, domain, actor_url

            # Fallback: extract username from URL path
            # Common patterns: /users/alice, /@alice, /u/alice
            path = parsed.path.rstrip("/")
            if path:
                last_segment = path.split("/")[-1]
                # Remove @ prefix if present
                username = last_segment.lstrip("@")
                if username:
                    return username, domain, actor_url

        except Exception:
            logger.debug("Could not resolve mention for reply-to %s", reply_to_url)
        return None

    def _build_reply_content(
        self,
        filepath: str,
        metadata: dict,
        public_url: str,
        reply_to: str,
    ) -> tuple[str, str, list[dict]]:
        """
        Build HTML content for a reply.

        :return: Tuple of ``(html, cleaned_markdown, attachments)``.
        """
        cleaned = self._clean_content(filepath)
        cleaned = resolve_relative_urls(
            cleaned, self.content_base_url, metadata.get("uri", ""), "/reply"
        )
        html = render_html(cleaned)
        html, attachments = self._extract_media_attachments(html, cleaned)

        # For unlisted posts (no reply-to), add URL link
        if not reply_to:
            title = metadata.get("title", "")
            has_real_title = (
                title and title != os.path.basename(filepath).rsplit(".", 1)[0]
            )
            if has_real_title:
                html = (
                    f'<p><strong><a href="{public_url}">{title}</a></strong></p>' + html
                )
            else:
                html = f'<p><a href="{public_url}">{public_url}</a></p>' + html

        return html, cleaned, attachments

    def _build_reply_mentions(
        self,
        cleaned: str,
        reply_to: str,
        *,
        allow_network: bool = False,
    ) -> tuple[str, list[dict], list[str]]:
        """
        Build mentions for a reply, including auto-mention of reply target.

        :return: Tuple of ``(html_prefix, mention_tags, mention_cc)``.
        """
        mentions = self._resolve_mentions(cleaned, allow_network=allow_network)
        mention_tags = [m.to_tag() for m in mentions]
        mention_cc = [m.actor_url for m in mentions]
        html_prefix = ""

        if reply_to:
            target = self._resolve_reply_target_mention(reply_to)
            if target and target[2] not in mention_cc:
                username, domain, actor_url = target
                fqn = f"@{username}@{domain}"
                html_prefix = (
                    f'<p><span class="h-card">'
                    f'<a href="{actor_url}" class="u-url mention">{fqn}</a>'
                    f"</span></p>"
                )
                mention_tags.append({"type": "Mention", "href": actor_url, "name": fqn})
                mention_cc.append(actor_url)
                logger.debug("Auto-added mention %s to reply", fqn)

        return html_prefix, mention_tags, mention_cc

    def build_reply_object(
        self,
        filepath: str,
        url: str,
        actor_url: str,
        public_url: str | None = None,
        *,
        allow_network: bool = False,
    ) -> tuple["Object", str] | tuple[None, None]:
        """
        Build an AP Note object for an author reply.

        :return: Tuple of ``(Object, activity_type)`` or ``(None, None)`` if
            the post should not be federated (draft visibility).
        """
        public_url = public_url or url
        metadata = self._parse_reply_metadata(filepath)
        reply_to = metadata.get("reply-to", "")

        # Parse published date
        published = metadata.get("published")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None

        # Build content and mentions
        html, cleaned, attachments = self._build_reply_content(
            filepath, metadata, public_url, reply_to
        )
        mention_prefix, mention_tags, mention_cc = self._build_reply_mentions(
            cleaned, reply_to, allow_network=allow_network
        )
        html = mention_prefix + html

        # Hashtags
        hashtags = extract_hashtags(cleaned)
        hashtag_tags = self._build_hashtag_tags(hashtags)
        html = self._make_hashtag_links_absolute(html)

        # Visibility and addressing
        is_unlisted_reply = not reply_to and not metadata.get("like-of")
        visibility = resolve_visibility(metadata, is_unlisted_reply=is_unlisted_reply)
        addressing = self._build_addressing(visibility, mention_cc)
        if addressing is None:
            logger.info("Skipping federation for draft reply: %s", url)
            return None, None

        to_field, cc_field = addressing
        activity_type = "Update" if self._is_published(url) else "Create"
        quote_control, quote_policy, interaction_policy = self._build_quote_policy()

        obj = Object(
            id=url,
            type="Note",
            name=None,
            content=html,
            url=public_url,
            attributed_to=actor_url,
            in_reply_to=reply_to or None,
            published=published or datetime.now(timezone.utc),
            updated=datetime.now(timezone.utc),
            to=to_field,
            cc=cc_field,
            tag=mention_tags + hashtag_tags,
            attachment=attachments,
            quote_control=quote_control,
            quote_policy=quote_policy,
            interaction_policy=interaction_policy,
        )

        obj.media_type = "text/html"
        obj.language = metadata.get("language", config.language)

        return obj, activity_type

    # -----------------------------------------------------------------
    # Like activity ID tracking (file_urls with #like suffix)
    # -----------------------------------------------------------------

    def _set_reply_like_id(
        self, filepath: str, activity_id: str, object_url: str
    ) -> None:
        """Store the Like activity ID and object URL for a reply file."""
        file_urls = self._load_file_urls()
        key = "reply/" + os.path.relpath(filepath, self.replies_dir) + "#like"
        file_urls[key] = activity_id
        file_urls[key + "-object"] = object_url
        self._save_file_urls(file_urls)

    def _get_reply_like_id(self, filepath: str) -> str | None:
        """Get the stored Like activity ID for a reply file."""
        key = "reply/" + os.path.relpath(filepath, self.replies_dir) + "#like"
        return self._load_file_urls().get(key)

    def _get_reply_like_object(self, filepath: str) -> str | None:
        """Get the stored like-of object URL for a reply file."""
        key = "reply/" + os.path.relpath(filepath, self.replies_dir) + "#like-object"
        return self._load_file_urls().get(key)

    def _remove_reply_like_id(self, filepath: str) -> None:
        """Remove the stored Like activity ID and object URL for a reply file."""
        file_urls = self._load_file_urls()
        key = "reply/" + os.path.relpath(filepath, self.replies_dir) + "#like"
        file_urls.pop(key, None)
        file_urls.pop(key + "-object", None)
        self._save_file_urls(file_urls)

    # -----------------------------------------------------------------
    # Like publish / delete handlers
    # -----------------------------------------------------------------

    def _handle_reply_like_publish(self, filepath: str, actor_url: str) -> None:
        """Build and publish a Like activity for a reply with like-of."""
        metadata = self._parse_metadata(filepath)
        like_of = metadata.get("like-of")
        if not like_of:
            return

        old_like_id = self._get_reply_like_id(filepath)
        old_object = self._get_reply_like_object(filepath) if old_like_id else None

        # Skip if we already have a Like for the same target URL
        if old_like_id and old_object == like_of:
            logger.debug("Like already published for %s, skipping", like_of)
            return

        # Undo any previously published Like for this file (target changed)
        if old_like_id:
            self._publish_undo_like(old_like_id, actor_url, object_url=old_object)

        like_activity = self._publish_like(like_of)
        self._set_reply_like_id(filepath, like_activity["id"], like_of)

    def _handle_reply_like_delete(self, filepath: str, actor_url: str) -> None:
        """Publish an Undo Like for a deleted reply file."""
        like_id = self._get_reply_like_id(filepath)
        if not like_id:
            return

        object_url = self._get_reply_like_object(filepath)
        self._publish_undo_like(like_id, actor_url, object_url=object_url)
        self._remove_reply_like_id(filepath)

    # -----------------------------------------------------------------
    # Note publish / delete handlers
    # -----------------------------------------------------------------

    def _handle_reply_publish(self, filepath: str, url: str, actor_url: str) -> None:
        """Build and publish a Create or Update activity for a reply."""
        # Compute the public URL using the content domain, not the AP domain
        rel = os.path.relpath(filepath, self.replies_dir).rsplit(".", 1)[0]
        public_url = f"{self.content_base_url}/reply/{rel}"

        self._build_and_publish(
            filepath,
            url,
            lambda: self.build_reply_object(
                filepath, url, actor_url, public_url=public_url, allow_network=True
            ),
            label="reply",
        )

    def _handle_reply_delete(self, filepath: str, url: str, actor_url: str) -> None:
        """Publish a Delete activity for a reply."""
        base_rel = os.path.relpath(filepath, self.replies_dir).rsplit(".", 1)[0]

        def _cleanup():
            self._mark_as_deleted(f"{self.base_url}/reply/{base_rel}")
            self._remove_reply_file_url(filepath)

        self._publish_delete(url, actor_url, "Note", extra_cleanup=_cleanup)

    def on_reply_change(self, change_type: ChangeType, filepath: str) -> None:
        """
        Callback for replies ContentMonitor.

        Publishes author replies as AP Notes with in_reply_to set.
        If the file contains ``like-of`` metadata, a Like activity is
        also published.  Standalone likes (no ``reply-to``, no content)
        produce only a Like — no Note.
        """
        if not self.replies_dir:
            return

        url = self.reply_file_to_url(filepath)
        actor_url = f"{self.base_url}{self.handler.actor_path}"

        if change_type.value == "deleted":
            self._handle_reply_like_delete(filepath, actor_url)
            self._handle_reply_delete(filepath, url, actor_url)
        else:
            # Read raw metadata (without reply-to derivation) for branching
            metadata = self._parse_metadata(filepath)
            like_of = metadata.get("like-of")
            has_explicit_reply_to = "reply-to" in metadata
            has_content = bool(self._clean_content(filepath).strip())

            if like_of:
                self._spawn_guarded_publish(
                    url + "#like",
                    lambda: self._handle_reply_like_publish(filepath, actor_url),
                    f"ap-like-{os.path.basename(filepath)}",
                )

            if has_explicit_reply_to or has_content:
                self._spawn_guarded_publish(
                    url,
                    lambda: self._handle_reply_publish(filepath, url, actor_url),
                    f"ap-reply-{os.path.basename(filepath)}",
                )
            elif like_of:
                # Standalone like (no Note published) — mark mtime so startup
                # sync won't re-process the file on every restart.
                self._mark_as_published(url, self._get_file_mtime(filepath))

    def sync_replies_on_startup(self) -> None:
        """
        Sync reply files on startup, similar to sync_on_startup() for articles.
        """
        if not self.replies_dir:
            return

        def _notify(filepath: str, is_new: bool) -> None:
            change = ChangeType.ADDED if is_new else ChangeType.EDITED
            self.on_reply_change(change, filepath)

        self._sync_directory(
            self.replies_dir,
            self.reply_file_to_url,
            _notify,
            label="replies",
        )
