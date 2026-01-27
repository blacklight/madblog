import logging
from datetime import datetime, timezone
from typing import Any

from ..exceptions import WebmentionException
from ._model import Webmention, WebmentionDirection
from ._parser import WebmentionsParser, WebmentionGone
from ._storage import WebmentionsStorage

logger = logging.getLogger(__name__)


class Webmentions:
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
        except WebmentionGone:
            assert source and target  # for mypy
            self.storage.delete_webmention(
                source, target, direction=WebmentionDirection.IN
            )

            logger.info("Deleted Webmention from '%s' to '%s'", source, target)
            return None
        except ValueError as e:
            raise WebmentionException(source, target, str(e)) from e

        now = datetime.now(timezone.utc)
        mention.created_at = mention.created_at or mention.published or now
        mention.updated_at = mention.updated_at or now
        ret = self.storage.store_webmention(mention)
        logger.info("Processed Webmention from '%s' to '%s'", source, target)
        return ret

    def retrieve_webmentions(self, target: str) -> list[Webmention]:
        """
        Retrieve webmentions for a given target URL.

        :param target: The target URL to retrieve webmentions for
        :return: A list of webmention data dictionaries
        """
        return self.storage.retrieve_webmentions(target)
