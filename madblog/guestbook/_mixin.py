"""
Guestbook mixin for Madblog.

Provides methods to retrieve and render guestbook entries from:
- Webmentions targeting the home page
- ActivityPub public mentions not in reply to articles
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from flask import Flask
from markupsafe import Markup
from pubby import ActivityPubHandler
from webmentions import WebmentionDirection, WebmentionsHandler

from madblog.config import config
from madblog.moderation import is_allowed, is_blocked, is_actor_permitted

logger = logging.getLogger(__name__)

# Special slug used for guestbook entries
GUESTBOOK_SLUG = "_guestbook"


class GuestbookMixin(ABC):
    """
    Mixin that provides guestbook functionality.

    Guestbook entries are:
    - Webmentions where the target is the home page
    - ActivityPub public mentions that are not replies to articles
    """

    activitypub_handler: ActivityPubHandler
    mentions_dir: Path
    webmentions_handler: WebmentionsHandler

    @property
    @abstractmethod
    def _app(self) -> Flask: ...

    def _is_home_page_url(self, url: str) -> bool:
        """
        Check if a URL points to the home page.
        """
        if not url:
            return False

        base_url = (config.link or "").rstrip("/")
        url_normalized = url.rstrip("/")

        # Direct match with base URL
        if url_normalized == base_url:
            return True

        # Check if it's the root path
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path in ("", "/"):
            # Check if the host matches
            base_parsed = urlparse(base_url)
            if parsed.netloc == base_parsed.netloc:
                return True

        return False

    def _is_article_url(self, url: str) -> bool:
        """
        Check if a URL points to an article.
        """
        if not url:
            return False

        base_url = (config.link or "").rstrip("/")
        ap_base_url = (config.activitypub_link or base_url).rstrip("/")

        # Check common article URL patterns
        for base in (base_url, ap_base_url):
            if url.startswith(f"{base}/article/"):
                return True

        return False

    def get_guestbook_webmentions(self) -> List:
        """
        Retrieve webmentions that target the home page.
        """
        if not hasattr(self, "webmentions_handler"):
            return []

        base_url = (config.link or "").rstrip("/")
        mentions = self.webmentions_handler.retrieve_stored_webmentions(
            base_url,
            direction=WebmentionDirection.IN,
        )

        # Also try with trailing slash
        mentions_slash = self.webmentions_handler.retrieve_stored_webmentions(
            base_url + "/",
            direction=WebmentionDirection.IN,
        )

        all_mentions = list(mentions) + list(mentions_slash)

        # Filter out non-permitted actors
        if config.blocked_actors:
            all_mentions = [
                m
                for m in all_mentions
                if not is_blocked(m.source, config.blocked_actors)
            ]
        elif config.allowed_actors:
            all_mentions = [
                m for m in all_mentions if is_allowed(m.source, config.allowed_actors)
            ]

        # Deduplicate by source URL
        seen = set()
        unique_mentions = []
        for m in all_mentions:
            if m.source not in seen:
                seen.add(m.source)
                unique_mentions.append(m)

        return sorted(
            unique_mentions,
            key=lambda x: x.published or x.created_at,
            reverse=True,
        )

    def get_guestbook_ap_interactions(self) -> List:
        """
        Retrieve ActivityPub mentions targeting the actor (guestbook entries).

        These are Create activities that mention the actor but are not replies
        to articles.
        """
        if not hasattr(self, "activitypub_handler"):
            return []

        storage = self.activitypub_handler.storage

        # Get interactions targeting the actor URL (direct mentions)
        try:
            actor_url = self.activitypub_handler.actor_id
            interactions = list(storage.get_interactions(target_resource=actor_url))
        except Exception:
            logger.debug("Failed to get AP interactions for guestbook", exc_info=True)
            return []

        # Filter to only MENTION type interactions and apply blocklist
        guestbook_interactions = []
        for interaction in interactions:
            # Only include mentions (not replies, likes, boosts targeting actor)
            interaction_type = getattr(interaction, "interaction_type", None)
            if interaction_type is not None:
                # Handle both enum and string values
                type_value = (
                    interaction_type.value
                    if hasattr(interaction_type, "value")
                    else str(interaction_type)
                )
                if type_value != "mention":
                    continue

            # Check if actor is permitted
            actor_id = getattr(interaction, "source_actor_id", "")
            if actor_id and not is_actor_permitted(actor_id):
                continue

            guestbook_interactions.append(interaction)

        # Deduplicate by activity_id or object_id
        seen = set()
        unique_interactions = []
        for i in guestbook_interactions:
            iid = getattr(i, "activity_id", None) or getattr(i, "object_id", None)
            if iid and iid not in seen:
                seen.add(iid)
                unique_interactions.append(i)

        return sorted(
            unique_interactions,
            key=lambda x: getattr(x, "published", None)
            or getattr(x, "created_at", None)
            or "",
            reverse=True,
        )

    def get_rendered_guestbook_webmentions(self) -> Markup:
        """
        Retrieve rendered HTML for guestbook webmentions.
        """
        mentions = self.get_guestbook_webmentions()
        if not mentions:
            return Markup("")

        return self.webmentions_handler.render_webmentions(mentions)

    def get_rendered_guestbook_ap_interactions(self) -> str:
        """
        Retrieve rendered HTML for guestbook ActivityPub interactions.
        """
        interactions = self.get_guestbook_ap_interactions()
        if not interactions:
            return ""

        return self.activitypub_handler.render_interactions(interactions)

    def get_guestbook_count(self) -> int:
        """
        Get the total number of guestbook entries.
        """
        wm_count = len(self.get_guestbook_webmentions())
        ap_count = len(self.get_guestbook_ap_interactions())
        return wm_count + ap_count
