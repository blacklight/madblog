import re
from abc import ABC
from urllib.parse import quote, urlparse

from ..config import config
from ._model import FeedAuthor
from ._parser import FeedParser


def _strip_html(text: str | None) -> str:
    """Strip HTML tags from text and decode entities."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


class FeedsMixin(ABC):  # pylint: disable=too-few-public-methods
    """
    Blog app feeds helpers.
    """

    def __init__(self, *_, **__):
        self._feed_parser = FeedParser(config.external_feeds)

    def _get_pages_from_feeds(self, *, with_content: bool = False):
        return [
            {
                "uri": entry.link,
                "external_url": entry.link,
                "folder": "",
                "source": urlparse(entry.link).netloc,
                "source_logo": feed.logo,
                "content": entry.content if with_content else "",
                "title": entry.title,
                "description": entry.description,
                "image": entry.enclosure,
                "published": entry.published,
                "author": next(
                    (
                        author
                        for author in (
                            entry.authors
                            or feed.authors
                            or (
                                [
                                    FeedAuthor(
                                        name=config.author,
                                        uri=config.author_url or "",
                                        email="",
                                    )
                                ]
                                if config.author
                                else []
                            )
                        )
                    ),
                    None,
                ),
            }
            for feed in self._feed_parser.parse_feeds().values()
            for entry in feed.entries
        ]

    def _get_external_feed_folders(self) -> list:
        """
        Get external feeds as virtual folder entries.

        Returns a list of folder-like dicts for each external feed source.
        """
        feeds = self._feed_parser.parse_feeds()
        folders = []

        for url, feed in feeds.items():
            domain = urlparse(url).netloc
            # Use internal URI with /+ prefix, URL-encoding the feed URL
            internal_uri = f"/+{quote(url, safe='')}/"
            folders.append(
                {
                    "name": domain,
                    "path": f"_external/{domain}",
                    "uri": internal_uri,
                    "feed_url": url,
                    "title": _strip_html(feed.title) or domain,
                    "description": _strip_html(feed.description),
                    "image": feed.logo,
                    "is_external": True,
                    "entry_count": len(feed.entries),
                }
            )

        return sorted(folders, key=lambda f: f["title"].lower())

    def _find_feed_by_url(self, feed_url: str):
        """
        Find a feed by URL, handling slight variations (trailing slashes, etc).

        Returns tuple of (canonical_url, feed) or (None, None) if not found.
        """
        import logging

        logger = logging.getLogger(__name__)
        feeds = self._feed_parser.parse_feeds()
        logger.debug(
            "Looking for feed_url=%s in feeds=%s", feed_url, list(feeds.keys())
        )
        # Try exact match first
        if feed_url in feeds:
            return feed_url, feeds[feed_url]
        # Try with/without trailing slash
        url_stripped = feed_url.rstrip("/")
        url_with_slash = url_stripped + "/"
        for candidate in (url_stripped, url_with_slash):
            if candidate in feeds:
                logger.debug("Found feed with candidate=%s", candidate)
                return candidate, feeds[candidate]
        logger.debug("Feed not found for feed_url=%s", feed_url)
        return None, None

    def _get_pages_from_single_feed(self, feed_url: str, *, with_content: bool = False):
        """
        Get pages from a specific external feed URL.

        Returns a list of page dicts for entries in the specified feed.
        """
        _, feed = self._find_feed_by_url(feed_url)
        if not feed:
            return []

        return [
            {
                "uri": entry.link,
                "external_url": entry.link,
                "folder": "",
                "source": urlparse(entry.link).netloc,
                "source_logo": feed.logo,
                "content": entry.content if with_content else "",
                "title": entry.title,
                "description": entry.description,
                "image": entry.enclosure,
                "published": entry.published,
                "author": next(
                    (
                        author
                        for author in (
                            entry.authors
                            or feed.authors
                            or (
                                [
                                    FeedAuthor(
                                        name=config.author,
                                        uri=config.author_url or "",
                                        email="",
                                    )
                                ]
                                if config.author
                                else []
                            )
                        )
                    ),
                    None,
                ),
            }
            for entry in feed.entries
        ]

    def _get_feed_metadata(self, feed_url: str) -> dict:
        """
        Get metadata for a specific external feed.

        Returns a dict with title, description, image, and feed_url.
        """
        canonical_url, feed = self._find_feed_by_url(feed_url)
        if not feed:
            return {}

        domain = urlparse(canonical_url).netloc
        return {
            "title": _strip_html(feed.title) or domain,
            "description": _strip_html(feed.description),
            "image": feed.logo,
            "feed_url": canonical_url,
        }


# vim:sw=4:ts=4:et:
