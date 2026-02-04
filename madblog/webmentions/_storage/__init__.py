from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from .._model import Webmention, WebmentionDirection


class WebmentionsStorage(ABC):
    """
    Base class for Webmention storage backends.
    """

    @abstractmethod
    def store_webmention(self, mention: Webmention) -> Any:
        """
        Store a Webmention.

        :param mention: The Webmention to store
        """

    @abstractmethod
    def delete_webmention(
        self,
        source: str,
        target: str,
        direction: WebmentionDirection,
    ) -> Any | None:
        """
        Mark a Webmention as deleted.

        :param source: The source URL of the Webmention
        :param target: The target URL of the Webmention
        :param direction: The direction of the Webmention (inbound or outbound)
        """

    @abstractmethod
    def retrieve_webmentions(
        self, resource: str, direction: WebmentionDirection
    ) -> list[Webmention]:
        """
        Retrieve the stored Webmentions for a given URL.

        :param resource: The URL of the resource associated to the Webmentions
        :param direction: The direction of the Webmentions (inbound or outbound)
        :return: A list of webmention data dictionaries
        """
        return []

    def mark_sent(self, source: str, target: str) -> None:
        """
        Mark a Webmention as sent.

        :param source: The source URL of the Webmention
        :param target: The target URL of the Webmention
        """
        mention = Webmention(
            source=source,
            target=target,
            direction=WebmentionDirection.OUT,
        )
        mention.updated_at = datetime.now(timezone.utc)
        self.store_webmention(mention)
