from abc import ABC
from urllib.parse import urlparse

from ..config import config
from ._model import FeedAuthor
from ._parser import FeedParser


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


# vim:sw=4:ts=4:et:
