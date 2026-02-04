import logging
from datetime import datetime, timezone
from typing import Any

from .._exceptions import WebmentionException, WebmentionGone
from .._model import WebmentionDirection
from .._storage import WebmentionsStorage
from ._constants import DEFAULT_HTTP_TIMEOUT, DEFAULT_USER_AGENT
from ._parser import WebmentionsRequestParser

logger = logging.getLogger(__name__)


class IncomingWebmentionsProcessor:  # pylint: disable=too-few-public-methods
    """
    Incoming Webmentions processor.
    """

    def __init__(
        self,
        storage: WebmentionsStorage,
        *,
        base_url: str | None = None,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        **_,
    ):
        self.parser = WebmentionsRequestParser(
            base_url=base_url, http_timeout=http_timeout, user_agent=user_agent
        )
        self._storage = storage

    def process_incoming_webmention(
        self, source: str | None, target: str | None
    ) -> Any:
        """
        Process an incoming Webmention.

        :param source: The source URL of the Webmention
        :param target: The target URL of the Webmention
        """
        logger.info("Received Webmention from '%s' to '%s'", source, target)

        try:
            mention = self.parser.parse(source, target)
            assert source and target  # for mypy
        except WebmentionGone:
            assert source and target  # for mypy
            self._storage.delete_webmention(
                source, target, direction=WebmentionDirection.IN
            )

            logger.info("Deleted Webmention from '%s' to '%s'", source, target)
            return None
        except ValueError as e:
            raise WebmentionException(source, target, str(e)) from e

        now = datetime.now(timezone.utc)
        mention.created_at = mention.created_at or mention.published or now
        mention.updated_at = mention.updated_at or now
        ret = self._storage.store_webmention(mention)
        logger.info("Processed Webmention from '%s' to '%s'", source, target)
        return ret
