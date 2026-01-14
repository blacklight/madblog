import logging
import os
import re
from urllib.parse import urlparse
from typing import Any

import requests

from ..config import config
from ..exceptions import WebmentionException
from ._storage import WebmentionsStorage

logger = logging.getLogger(__name__)


class WebmentionsHandler:
    """
    Webmentions handler.
    """

    def __init__(self):
        self.storage = WebmentionsStorage.build()

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
            self.verify_webmention(source, target)
            assert source and target  # for mypy
        except ValueError as e:
            raise WebmentionException(source, target, str(e)) from e

        ret = self.storage.store_webmention(source, target, data)
        logger.info("Processed Webmention from '%s' to '%s'", source, target)
        return ret

    @staticmethod
    def parse_metadata(content: str) -> dict:
        """
        Parse metadata from Markdown comments.
        """
        return WebmentionsStorage.parse_metadata(content)

    @staticmethod
    def verify_webmention(source: str | None, target: str | None):
        """
        Verify that the source URL is reachable and that it actually includes the
        target URL.
        """
        # Check that both source and target are provided
        if not (source and target):
            raise ValueError(source, target, "Missing source or target URL")

        # Check that the source URL is reachable
        resp = requests.get(
            source,
            timeout=10,
            headers={"User-Agent": "Madblog Webmention Listener"},
        )

        resp.raise_for_status()

        # Check that the target URL is included in the source content
        if target not in resp.text:
            raise ValueError("Target URL not found in source content")

        # Check that the target domain is the same as this server's domain
        target_domain = urlparse(target).netloc
        server_domain = urlparse(config.link).netloc
        if target_domain != server_domain:
            raise ValueError("Target URL domain does not match server domain")

        # Check that the target path is an actual path on this server
        filename = os.path.join(
            config.content_dir,
            "markdown",
            re.sub(r"^/article", "", urlparse(target).path).strip("/") + ".md",
        )

        if not os.path.isfile(filename):
            raise ValueError("Target URL does not correspond to any known content")
