"""
Shared publish utilities for ActivityPub integration.

Provides common threading, content processing, and publish patterns
used by both article and reply publishing.
"""

import logging
import os
import threading
from collections.abc import Iterable
from typing import Callable

from pubby import ActivityPubHandler, Mention, Object
from pubby.webfinger import _MENTION_RE

logger = logging.getLogger(__name__)


class ActivityPubPublishMixin:  # pylint: disable=too-few-public-methods
    """
    Mixin providing common publish utilities for ActivityPub content.

    Subclasses must provide the threading primitives and handler.
    Expects sync methods from StartupSyncMixin.
    """

    _active_publishes_lock: threading.Lock
    _active_publishes: set[str]
    _publish_semaphore: threading.Semaphore
    base_url: str
    content_base_url: str
    handler: ActivityPubHandler

    # Cache for resolved WebFinger mention lookups.
    _mention_cache: dict[tuple[str, str], str]
    _mention_cache_lock: threading.Lock

    # Expected from StartupSyncMixin
    _load_sync_cache: Callable[[], dict]
    _sync_unmark: Callable[[str], None]
    _is_published: Callable[[str], bool]
    _mark_as_published: Callable[[str, float], None]

    # Expected from the concrete class
    _extract_media_attachments: Callable[[str, str], tuple[str, list[dict]]]
    _parse_metadata: Callable[[str], dict]
    _clean_content: Callable[[str], str]

    # -----------------------------------------------------------------
    # Guarded publish threading
    # -----------------------------------------------------------------

    def _spawn_guarded_publish(
        self,
        url: str,
        publish_fn: Callable[[], None],
        thread_name: str,
    ) -> bool:
        """
        Spawn a background thread to run a publish function with guards.

        Returns True if a thread was spawned, False if publish was skipped
        (already in progress for this URL).

        The publish function is wrapped with:
        - Duplicate detection (skip if URL already being published)
        - Semaphore limiting concurrent publishes
        - Cleanup of active_publishes set on completion
        """
        with self._active_publishes_lock:
            if url in self._active_publishes:
                logger.debug("Publish already in progress for %s, skipping", url)
                return False
            self._active_publishes.add(url)

        def _guarded():
            with self._publish_semaphore:
                publish_fn()
            with self._active_publishes_lock:
                self._active_publishes.discard(url)

        threading.Thread(
            target=_guarded,
            daemon=True,
            name=thread_name,
        ).start()
        return True

    # -----------------------------------------------------------------
    # Mention resolution
    # -----------------------------------------------------------------

    def _resolve_mentions(
        self, text: str, *, allow_network: bool = False
    ) -> list[Mention]:
        """
        Extract ``@user@domain`` mentions from *text* and resolve them.

        Results are cached so that subsequent calls for the same handle
        never repeat the HTTP lookup.

        :param allow_network: When ``True`` (background publish path),
            perform a real WebFinger HTTP request for uncached handles
            and store the result.  When ``False`` (default / request
            path), return a fallback URL for uncached handles without
            making any network call.
        """
        from pubby import resolve_actor_url

        seen: set[tuple[str, str]] = set()
        mentions: list[Mention] = []
        for username, domain in _MENTION_RE.findall(text):
            key = (username.lower(), domain.lower())
            if key in seen:
                continue
            seen.add(key)

            with self._mention_cache_lock:
                cached = self._mention_cache.get(key)

            if cached is not None:
                actor_url = cached
            elif allow_network:
                actor_url = resolve_actor_url(username, domain)
                with self._mention_cache_lock:
                    self._mention_cache[key] = actor_url
                self._save_mention_cache()
            else:
                # Request path: never block on HTTP
                actor_url = f"https://{domain}/@{username}"

            mentions.append(
                Mention(username=username, domain=domain, actor_url=actor_url)
            )
        return mentions

    def _save_mention_cache(self) -> None:
        """Save the mention cache. Override in concrete class for persistence."""
        pass

    # -----------------------------------------------------------------
    # Tag building helpers
    # -----------------------------------------------------------------

    def _build_hashtag_tags(self, hashtags: Iterable[str]) -> list[dict]:
        """Build ActivityPub Hashtag tag objects from a list of hashtag strings."""
        return [
            {
                "type": "Hashtag",
                "href": f"{self.content_base_url}/tags/{tag}",
                "name": f"#{tag}",
            }
            for tag in hashtags
        ]

    def _make_hashtag_links_absolute(self, html: str) -> str:
        """Convert relative hashtag links to absolute URLs."""
        return html.replace(
            'href="/tags/',
            f'href="{self.content_base_url}/tags/',
        )

    # -----------------------------------------------------------------
    # Common publish helpers
    # -----------------------------------------------------------------

    def _publish_delete(
        self,
        url: str,
        actor_url: str,
        object_type: str,
        *,
        extra_cleanup: Callable[[], None] | None = None,
    ) -> None:
        """
        Publish a Delete activity for an object.

        :param url: The object ID being deleted
        :param actor_url: The actor performing the delete
        :param object_type: AP object type (e.g., "Article", "Note")
        :param extra_cleanup: Optional callback for additional cleanup
        """
        self._sync_unmark(url)
        if extra_cleanup:
            extra_cleanup()

        obj = Object(
            id=url,
            type=object_type,
            attributed_to=actor_url,
            to=["https://www.w3.org/ns/activitystreams#Public"],
            cc=[self.handler.followers_url],
        )

        try:
            self.handler.publish_object(obj, activity_type="Delete")
            logger.info("Published Delete for %s", url)
        except Exception:
            logger.exception("Failed to publish Delete for %s", url)

    def _build_and_publish(
        self,
        filepath: str,
        url: str,
        build_fn: Callable[[], tuple],
        *,
        label: str = "",
    ) -> None:
        """
        Shared build → mark → deliver cycle for articles and replies.

        :param filepath: Filesystem path of the source Markdown file.
        :param url: Canonical AP object ``id``.
        :param build_fn: Zero-arg callable returning ``(Object, activity_type)``.
        :param label: Human-readable label for log messages (e.g. "reply").
        """
        tag = f"{label} " if label else ""

        try:
            obj, activity_type = build_fn()
        except Exception:
            logger.exception("Failed to build AP %sobject for %s", tag, url)
            self._mark_as_published(url, self._get_file_mtime(filepath))
            return

        self._mark_as_published(url, self._get_file_mtime(filepath))

        try:
            self.handler.publish_object(obj, activity_type=activity_type)
            logger.info("Published %s%s for %s", tag, activity_type, url)
        except Exception:
            logger.exception("Failed to deliver %s%s for %s", tag, activity_type, url)

    def _get_file_mtime(self, filepath: str) -> float:
        """Get file modification time, returning 0 on error."""
        try:
            return os.path.getmtime(filepath)
        except OSError:
            return 0
