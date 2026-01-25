import logging
from typing import Any

from ..exceptions import WebmentionException
from ._model import Webmention, WebmentionDirection
from ._parser import WebmentionsParser
from ._storage import WebmentionsStorage

logger = logging.getLogger(__name__)


class WebmentionsHandler:
    """
    Webmentions handler.
    """

    def __init__(self):
        self.storage = WebmentionsStorage.build()
        self.parser = WebmentionsParser()

    def process_webmention_request(
        self, source: str | None, target: str | None, data: dict | None = None
    ) -> Any:
        """
        Process a Webmention.

        :param source: The source URL of the webmention
        :param target: The target URL of the webmention
        :param data: Optional dictionary with verified data from the source
        """
        logger.info("Received Webmention from '%s' to '%s'", source, target)

        try:
            mention = self.parser.parse(source, target)
            assert source and target  # for mypy
        except ValueError as e:
            raise WebmentionException(source, target, str(e)) from e

        parsed_data = data.copy() if data else {}
        parsed_data.setdefault("title", mention.title)
        parsed_data.setdefault("excerpt", mention.excerpt)
        parsed_data.setdefault("content", mention.content)
        parsed_data.setdefault("author_name", mention.author_name)
        parsed_data.setdefault("author_url", mention.author_url)
        parsed_data.setdefault("author_photo", mention.author_photo)
        parsed_data.setdefault("published", mention.published)
        parsed_data.setdefault("mention_type", mention.mention_type.value)
        parsed_data.setdefault("mention_type_raw", mention.mention_type_raw)

        ret = self.storage.store_webmention(
            source, target, direction=WebmentionDirection.IN, data=parsed_data
        )

        logger.info("Processed Webmention from '%s' to '%s'", source, target)
        return ret

    def retrieve_webmentions(self, target: str) -> list[Webmention]:
        """
        Retrieve webmentions for a given target URL.

        :param target: The target URL to retrieve webmentions for
        :return: A list of webmention data dictionaries
        """
        return self.storage.retrieve_webmentions(target)
