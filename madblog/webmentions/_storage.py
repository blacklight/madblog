from abc import ABC, abstractmethod
from typing import Any

from ._model import Webmention, WebmentionDirection


class WebmentionsStorage(ABC):
    """
    Abstract base class for Webmention storage backends.
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
    ) -> Any:
        """
        Mark a Webmention as deleted.

        :param source: The source URL of the webmention
        :param target: The target URL of the webmention
        :param direction: The direction of the webmention (inbound or outbound)
        """

    @abstractmethod
    def retrieve_webmentions(self, target: str) -> list[Webmention]:
        """
        Retrieve webmentions for a given target URL.

        :param target: The target URL to retrieve webmentions for
        :return: A list of webmention data dictionaries
        """
