from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from logging import getLogger
from threading import RLock
from typing import Collection

import feedparser

from ._model import Feed

feeds_lock = RLock()
logger = getLogger(__name__)


class FeedParser:
    """
    A thread-safe concurrent feedparser.

    :param urls: A list of URLs to parse
    :param cache_expiry_secs: The number of seconds to cache parsed feeds
        (default: no caching)
    """

    def __init__(
        self, urls: Collection[str] = tuple(), cache_expiry_secs: int = 0
    ) -> None:
        self.urls = urls
        self._cache_expiry_secs = cache_expiry_secs
        self._feeds_cache: dict[str, Feed] = {}

    def parse_feed(self, url: str) -> Feed | None:
        cached_feed = self._feeds_cache.get(url)
        if cached_feed and (
            not self._cache_expiry_secs
            or (
                cached_feed.last_fetched
                and (
                    datetime.now(timezone.utc) - cached_feed.last_fetched
                ).total_seconds()
                < self._cache_expiry_secs
            )
        ):
            return cached_feed

        try:
            feed = Feed.build(feedparser.parse(url))
            feed.last_fetched = datetime.now(timezone.utc)
            self._feeds_cache[url] = feed
            return feed
        except Exception:
            logger.exception("Failed to parse feed %s", url)
            return None

    def parse_feeds(self) -> dict[str, Feed]:
        """
        Parse all feeds.

        :return: A dictionary of parsed feeds in the form {href: feed}
        """
        with feeds_lock, ThreadPoolExecutor(max_workers=10) as executor:
            return {
                feed.href: feed
                for feed in executor.map(self.parse_feed, self.urls)
                if feed
            }
