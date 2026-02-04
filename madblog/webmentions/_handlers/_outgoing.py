import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

# noinspection PyPackageRequirements
from bs4 import BeautifulSoup
import requests

from .._model import ContentTextFormat, WebmentionDirection
from .._storage import WebmentionsStorage
from ._constants import DEFAULT_HTTP_TIMEOUT, DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)


class OutgoingWebmentionsProcessor:  # pylint: disable=too-few-public-methods
    """
    Process outgoing Webmentions.

    :param storage: Webmentions storage
    :param user_agent: User agent to use
    :param exclude_netlocs: List of netlocs that should not be processed
    :param http_timeout: HTTP timeout
    """

    def __init__(
        self,
        storage: WebmentionsStorage,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        exclude_netlocs: set[str] | None = None,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
        **_,
    ):
        self._storage = storage
        self._http_timeout = http_timeout
        self._user_agent = user_agent
        self._exclude_netlocs = exclude_netlocs or set()

    def process_outgoing_webmentions(
        self,
        source_url: str,
        *,
        text: str | None = None,
        text_format: ContentTextFormat | None = None,
    ) -> None:
        """
        Process an outgoing Webmention.

        :param source_url: The source URL of the Webmention. Ignored if text is
            provided.
        :param text: The text of the Webmention. If not provided, the source URL
            will be fetched.
        :param text_format: The text format of the Webmention. If not provided,
            it will be inferred from the source URL or text.
        """
        if text is None:
            resp = requests.get(
                source_url,
                timeout=self._http_timeout,
                headers={"User-Agent": self._user_agent},
                allow_redirects=True,
            )
            resp.raise_for_status()
            text = resp.text or ""
            text_format = ContentTextFormat.HTML

        text_format = text_format or ContentTextFormat.TEXT
        new_targets = self._extract_targets(text, text_format)

        try:
            old_targets = {
                webmention.target
                for webmention in self._storage.retrieve_webmentions(
                    source_url, direction=WebmentionDirection.OUT
                )
            }
        except Exception:
            old_targets = set()

        removed = old_targets - new_targets
        added_pool = ThreadPoolExecutor(max_workers=10)
        removed_pool = ThreadPoolExecutor(max_workers=10)

        for target_url in sorted(new_targets):
            added_pool.submit(self._notify_added, source_url, target_url)

        for target_url in sorted(removed):
            removed_pool.submit(self._notify_removed, source_url, target_url)

        added_pool.shutdown(wait=True)
        removed_pool.shutdown(wait=True)

    def _notify_added(self, source_url: str, target_url: str):
        """
        Notify a target of an outgoing Webmention.
        """
        try:
            self._notify_target(source_url, target_url)
            self._storage.mark_sent(source_url, target_url)
        except Exception as e:
            logger.info(
                "Outgoing Webmention failed (source=%s target=%s): %s",
                source_url,
                target_url,
                str(e),
            )

    def _notify_removed(self, source_url: str, target_url: str):
        """
        Notify a target of a removed outgoing Webmention.
        """
        try:
            self._notify_target(source_url, target_url)
            self._storage.delete_webmention(
                source_url, target_url, direction=WebmentionDirection.OUT
            )
        except Exception as e:
            logger.info(
                "Outgoing Webmention deletion failed (source=%s target=%s): %s",
                source_url,
                target_url,
                str(e),
            )

    def _extract_targets(self, text: str, text_format: ContentTextFormat) -> set[str]:
        """
        Given a text and a text format, extract the target URLs from the text.
        """
        if text_format == ContentTextFormat.HTML:
            return self._extract_urls_from_html(text)
        return self._extract_urls_from_markdown_or_text(text)

    def _extract_urls_from_html(self, html: str) -> set[str]:
        """
        Extract URLs from HTML.
        """
        urls: set[str] = set()
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["a", "link"]):
            href = tag.get("href")
            if not href:
                continue
            href = str(href).strip()
            if href.lower().startswith("http://") or href.lower().startswith(
                "https://"
            ):
                urls.add(href)
        return self._clean_and_filter_targets(urls)

    def _extract_urls_from_markdown_or_text(self, md: str) -> set[str]:
        """
        Extract URLs from Markdown or text.
        """
        urls: set[str] = set()

        for m in re.finditer(r"]\((https?://[^\s)]+)\)", md, flags=re.IGNORECASE):
            urls.add(m.group(1))

        for m in re.finditer(r"<(https?://[^>\s]+)>", md, flags=re.IGNORECASE):
            urls.add(m.group(1))

        for m in re.finditer(r"(https?://[^\s)\]}>\"']+)", md, flags=re.IGNORECASE):
            urls.add(m.group(1))

        return self._clean_and_filter_targets(urls)

    def _clean_and_filter_targets(self, urls: set[str]) -> set[str]:
        """
        Clean and filter URLs.
        """
        cleaned: set[str] = set()
        for u in urls:
            u2 = u.strip().rstrip('.,;:!?)"]\'"')
            if not u2:
                continue
            cleaned.add(u2)

        return {
            u
            for u in cleaned
            if urlparse(u).scheme in ("http", "https")
            and urlparse(u).netloc
            and urlparse(u).netloc not in self._exclude_netlocs
        }

    def _notify_target(self, source_url: str, target_url: str) -> None:
        """
        Notify a target of an outgoing Webmention.
        """
        endpoint = self._discover_webmention_endpoint(target_url)
        if not endpoint:
            return

        resp = requests.post(
            endpoint,
            data={"source": source_url, "target": target_url},
            timeout=self._http_timeout,
            headers={"User-Agent": self._user_agent},
            allow_redirects=True,
        )

        if resp.status_code >= 400:
            resp.raise_for_status()

    def _discover_webmention_endpoint(self, target_url: str) -> str | None:
        """
        Discover a Webmention endpoint for a target URL.
        """
        resp = requests.get(
            target_url,
            timeout=self._http_timeout,
            headers={"User-Agent": self._user_agent},
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Check if there is a Link header
        link_header = resp.headers.get("Link")
        if link_header:
            for part in link_header.split(","):
                if "rel=" not in part.lower():
                    continue
                if "webmention" not in part.lower():
                    continue
                m = re.search(r"<([^>]+)>", part)
                if m:
                    return urljoin(resp.url, m.group(1))

        # Check if there is a <link> or <a> tag
        soup = BeautifulSoup(resp.text or "", "html.parser")
        for tag in soup.find_all(["link", "a"]):
            rel = tag.get("rel")
            href: str = tag.get("href")  # type: ignore
            if not href:
                continue

            rel_str = " ".join(rel) if isinstance(rel, list) else (rel or "")
            if "webmention" in rel_str.lower():
                return urljoin(resp.url, href)

        return None
