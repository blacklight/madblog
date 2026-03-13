import logging
import os

from datetime import datetime, timezone
from typing import Callable

from pubby import Object

from madblog.config import config
from madblog.markdown import render_html, resolve_relative_urls
from madblog.monitor import ChangeType
from madblog.tags import extract_hashtags

from ._publish import ActivityPubPublishMixin

logger = logging.getLogger(__name__)


class ActivityPubRepliesMixin(ActivityPubPublishMixin):
    """
    Mixin for ActivityPub integration for replies.

    Inherits common publish utilities from ActivityPubPublishMixin.
    """

    replies_dir: str | None
    _sync_directory: Callable[..., None]

    def reply_file_to_url(self, filepath: str) -> str:
        """
        Convert a reply file path to its public URL.

        :param filepath: Path like ``replies/<article-slug>/<reply-slug>.md``
        :return: URL like ``https://example.com/reply/<article-slug>/<reply-slug>``
        """
        if not self.replies_dir:
            raise ValueError("replies_dir not configured")

        rel = os.path.relpath(filepath, self.replies_dir).rsplit(".", 1)[0]
        return f"{self.base_url}/reply/{rel}"

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
            else:
                logger.warning("Reply %s has no reply-to and no article slug", filepath)
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

    def build_reply_object(
        self,
        filepath: str,
        url: str,
        actor_url: str,
        public_url: str | None = None,
        *,
        allow_network: bool = False,
    ) -> tuple["Object", str]:
        """
        Build an AP Note object for an author reply.

        Similar to build_object() but:
        - Sets type to "Note" (conversational)
        - Sets in_reply_to from metadata
        - Does not set name (Notes shouldn't have names)
        - CCs the original author if replying to an AP interaction
        """
        public_url = public_url or url
        metadata = self._parse_reply_metadata(filepath)
        reply_to = metadata.get("reply-to", "")

        published = metadata.get("published")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published = None

        # Build content (no title header for Notes)
        cleaned = self._clean_content(filepath)
        # Resolve relative URLs to absolute before rendering to HTML
        cleaned = resolve_relative_urls(cleaned, self.content_base_url)
        html = render_html(cleaned)
        html, attachments = self._extract_media_attachments(html, cleaned)

        # Resolve @user@domain mentions
        mentions = self._resolve_mentions(cleaned, allow_network=allow_network)
        mention_tags = [m.to_tag() for m in mentions]
        mention_cc = [m.actor_url for m in mentions]

        # Extract #hashtags
        hashtags = extract_hashtags(cleaned)
        hashtag_tags = self._build_hashtag_tags(hashtags)

        # Make hashtag links absolute
        html = self._make_hashtag_links_absolute(html)

        # Build CC list: followers + mentions + original author (if AP)
        cc_list = [self.handler.followers_url] + mention_cc
        if reply_to:
            target_actor = self._resolve_reply_target_actor(reply_to)
            if target_actor and target_actor not in cc_list:
                cc_list.append(target_actor)

        activity_type = "Update" if self._is_published(url) else "Create"

        obj = Object(
            id=url,
            type="Note",  # Replies are Notes, not Articles
            name=None,  # Notes should not have a name
            content=html,
            url=public_url,
            attributed_to=actor_url,
            in_reply_to=reply_to or None,
            published=published or datetime.now(timezone.utc),
            updated=datetime.now(timezone.utc),
            to=["https://www.w3.org/ns/activitystreams#Public"],
            cc=cc_list,
            tag=mention_tags + hashtag_tags,
            attachment=attachments,
        )

        obj.media_type = "text/html"
        obj.language = metadata.get("language", config.language)

        return obj, activity_type

    def _handle_reply_publish(self, filepath: str, url: str, actor_url: str) -> None:
        """Build and publish a Create or Update activity for a reply."""
        self._build_and_publish(
            filepath,
            url,
            lambda: self.build_reply_object(
                filepath, url, actor_url, public_url=url, allow_network=True
            ),
            label="reply",
        )

    def _handle_reply_delete(self, url: str, actor_url: str) -> None:
        """Publish a Delete activity for a reply."""
        self._publish_delete(url, actor_url, "Note")

    def on_reply_change(self, change_type: ChangeType, filepath: str) -> None:
        """
        Callback for replies ContentMonitor.

        Publishes author replies as AP Notes with in_reply_to set.
        """
        if not self.replies_dir:
            return

        url = self.reply_file_to_url(filepath)
        actor_url = f"{self.base_url}{self.handler.actor_path}"

        if change_type.value == "deleted":
            self._handle_reply_delete(url, actor_url)
        else:
            self._spawn_guarded_publish(
                url,
                lambda: self._handle_reply_publish(filepath, url, actor_url),
                f"ap-reply-{os.path.basename(filepath)}",
            )

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
