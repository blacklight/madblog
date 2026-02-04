import logging
from typing import Any

from .._model import ContentTextFormat, Webmention, WebmentionDirection
from .._storage import WebmentionsStorage
from ._constants import DEFAULT_HTTP_TIMEOUT, DEFAULT_USER_AGENT
from ._incoming import IncomingWebmentionsProcessor
from ._outgoing import OutgoingWebmentionsProcessor

logger = logging.getLogger(__name__)


class WebmentionsHandler:
    """
    Webmentions handler.
    """

    def __init__(
        self,
        storage: WebmentionsStorage,
        *,
        base_url: str | None = None,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        exclude_netlocs: set[str] | None = None,
        **kwargs,
    ):
        self.storage = storage
        self.incoming = IncomingWebmentionsProcessor(
            storage=storage,
            base_url=base_url,
            http_timeout=http_timeout,
            user_agent=user_agent,
            **kwargs,
        )
        self.outgoing = OutgoingWebmentionsProcessor(
            storage=storage,
            user_agent=user_agent,
            exclude_netlocs=exclude_netlocs,
            http_timeout=http_timeout,
            **kwargs,
        )

    def process_incoming_webmention(
        self, source_url: str | None, target_url: str | None
    ) -> Any:
        """
        Process an incoming Webmention.

        :param source_url: The source URL of the Webmention
        :param target_url: The target URL of the Webmention
        """
        return self.incoming.process_incoming_webmention(source_url, target_url)

    def process_outgoing_webmentions(
        self,
        source_url: str,
        *,
        text: str | None = None,
        text_format: ContentTextFormat | None = None,
    ) -> Any:
        """
        Process an outgoing Webmention.

        :param source_url: The source URL of the Webmention. Ignored if text is
            provided.
        :param text: The text of the Webmention. If not provided, the source URL
            will be fetched.
        :param text_format: The text format of the Webmention. If not provided,
            it will be inferred from the source URL or text.
        """
        return self.outgoing.process_outgoing_webmentions(
            source_url, text=text, text_format=text_format
        )

    def retrieve_stored_webmentions(
        self, resource: str, direction: WebmentionDirection
    ) -> list[Webmention]:
        """
        Retrieve stored Webmentions for a given URL.

        :param resource: The resource URL
        :param direction: The direction of the Webmentions (inbound or outbound)
        :return: A list of Webmentions
        """
        return self.storage.retrieve_webmentions(resource, direction=direction)
