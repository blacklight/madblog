import logging
import re
from urllib.parse import urlparse
from typing import Any
from datetime import datetime

from bs4 import BeautifulSoup
import mf2py
import requests

from .._exceptions import WebmentionGone
from .._model import Webmention, WebmentionDirection, WebmentionType
from ._constants import DEFAULT_HTTP_TIMEOUT, DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)


class WebmentionsRequestParser:  # pylint: disable=too-few-public-methods
    """
    Parses a Webmention request.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        **_,
    ) -> None:
        self._base_url = base_url
        self._http_timeout = http_timeout
        self._user_agent = user_agent

    def parse(self, source: str | None, target: str | None) -> Webmention:
        """
        Parse a Webmention.

        :param source: The source URL of the webmention
        :param target: The target URL of the webmention
        """
        # Check that both source and target are provided
        if not (source and target):
            raise ValueError(source, target, "Missing source or target URL")

        # Check that the target domain is the same as this server's domain
        if self._base_url:
            target_domain = urlparse(target).netloc
            server_domain = urlparse(self._base_url).netloc
            if target_domain != server_domain:
                raise ValueError("Target URL domain does not match server domain")

        # Check that the source URL is reachable
        resp = requests.get(
            source,
            timeout=self._http_timeout,
            headers={"User-Agent": self._user_agent},
        )

        if resp.status_code in (404, 410):
            raise WebmentionGone(source, target, "Source URL not found")

        resp.raise_for_status()

        # Check that the target URL is included in the source content
        if target not in resp.text:
            raise WebmentionGone(
                source, target, "Target URL not found in source content"
            )

        mention = Webmention(
            source=source,
            target=target,
            direction=WebmentionDirection.IN,
        )

        self._parse_source_payload(mention, resp.text, source, target)
        return mention

    @classmethod
    def _parse_source_payload(
        cls, mention: Webmention, html: str, source_url: str, target_url: str
    ) -> None:
        entry = cls._extract_h_entry(html, source_url)
        if entry:
            cls._fill_from_h_entry(mention, entry, target_url)

        cls._fill_from_html_fallbacks(mention, html)

        if not mention.excerpt and mention.content:
            excerpt = re.sub(r"\s+", " ", mention.content).strip()
            mention.excerpt = excerpt[:240] if excerpt else None

    @staticmethod
    def _extract_h_entry(html: str, source_url: str) -> dict | None:
        try:
            parsed: dict = mf2py.parse(doc=html, url=source_url)  # type: ignore
        except Exception:
            return None

        items = parsed.get("items") or []
        for item in items:
            if "h-entry" in (item.get("type") or []):
                return item

        for item in items:
            for child in item.get("children") or []:
                if "h-entry" in (child.get("type") or []):
                    return child

        return None

    @staticmethod
    def _first_str(  # pylint: disable=too-many-return-statements
        value: Any,
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value

        if isinstance(value, dict):
            for key in ("value", "url"):
                v = value.get(key)
                if isinstance(v, str) and v:
                    return v
            return None

        if isinstance(value, list) and value:
            v0 = value[0]
            if isinstance(v0, str):
                return v0
            if isinstance(v0, dict):
                for key in ("value", "url"):
                    v = v0.get(key)
                    if isinstance(v, str) and v:
                        return v
            return None

        return None

    @classmethod
    def _extract_author(
        cls, properties: dict
    ) -> tuple[str | None, str | None, str | None]:
        """
        Extract the author of a Webmention.

        :param properties: The properties of the Webmention
        :return: A tuple of (name, url, photo)
        """

        author = properties.get("author")
        if not author:
            return None, None, None

        if isinstance(author, list) and author:
            author = author[0]

        if isinstance(author, str):
            return None, author, None

        if isinstance(author, dict):
            props = author.get("properties") or {}
            name = cls._first_str(props.get("name"))
            url = cls._first_str(props.get("url"))
            photo = cls._first_str(props.get("photo"))
            return name, url, photo

        return None, None, None

    @classmethod
    def _fill_from_h_entry(  # pylint: disable=too-many-branches
        cls, mention: Webmention, entry: dict, target_url: str
    ) -> None:
        """
        Fill a Webmention from an h-entry.

        :param mention: The Webmention to fill
        :param entry: The h-entry to fill the Webmention from
        :param target_url: The target URL of the Webmention
        """
        props = entry.get("properties") or {}
        mention.title = mention.title or cls._first_str(props.get("name"))
        if not mention.published:
            published = cls._first_str(props.get("published"))
            if published:
                mention.published = datetime.fromisoformat(published)
        summary = cls._first_str(props.get("summary"))

        if summary and not mention.excerpt:
            mention.excerpt = summary

        content = props.get("content")
        if not mention.content and isinstance(content, list) and content:
            c0 = content[0]
            if isinstance(c0, dict):
                mention.content = c0.get("value") or c0.get("html")
            elif isinstance(c0, str):
                mention.content = c0

        if not mention.content:
            mention.content = cls._first_str(props.get("content"))

        if (
            not mention.author_name
            and not mention.author_url
            and not mention.author_photo
        ):
            name, url, photo = cls._extract_author(props)
            mention.author_name = name
            mention.author_url = url
            mention.author_photo = photo

        if mention.mention_type == WebmentionType.UNKNOWN:
            like_of = props.get("like-of") or []
            repost_of = props.get("repost-of") or []
            in_reply_to = props.get("in-reply-to") or []
            if any(target_url == x for x in like_of if isinstance(x, str)):
                mention.mention_type_raw = "like-of"
                mention.mention_type = WebmentionType.from_raw(mention.mention_type_raw)
            elif any(target_url == x for x in repost_of if isinstance(x, str)):
                mention.mention_type_raw = "repost-of"
                mention.mention_type = WebmentionType.from_raw(mention.mention_type_raw)
            elif any(target_url == x for x in in_reply_to if isinstance(x, str)):
                mention.mention_type_raw = "in-reply-to"
                mention.mention_type = WebmentionType.from_raw(mention.mention_type_raw)
            else:
                mention.mention_type_raw = "mention"
                mention.mention_type = WebmentionType.from_raw(mention.mention_type_raw)

    @staticmethod
    def _fill_from_html_fallbacks(mention: Webmention, html: str) -> None:
        """
        Fill a Webmention from HTML.

        :param mention: The Webmention to fill
        :param html: The HTML to fill the Webmention from
        """
        soup = BeautifulSoup(html, "html.parser")

        if not mention.title:
            og_title: dict = soup.find("meta", attrs={"property": "og:title"})  # type: ignore
            tw_title: dict = soup.find("meta", attrs={"name": "twitter:title"})  # type: ignore
            if og_title and og_title.get("content"):
                mention.title = og_title.get("content")
            elif tw_title and tw_title.get("content"):
                mention.title = tw_title.get("content")
            elif soup.title and soup.title.string:
                mention.title = soup.title.string.strip()

        if not mention.author_name:
            meta_author: dict = soup.find("meta", attrs={"name": "author"})  # type: ignore
            if meta_author and meta_author.get("content"):
                mention.author_name = meta_author.get("content")

        if not mention.published:
            meta_pub: dict = soup.find("meta", attrs={"property": "article:published_time"})  # type: ignore
            if meta_pub and meta_pub.get("content"):
                mention.published = datetime.fromisoformat(meta_pub["content"])

        if not mention.content:
            desc: dict = soup.find("meta", attrs={"property": "og:description"})  # type: ignore
            if desc and desc.get("content"):
                mention.content = desc.get("content")

        if mention.content and not mention.excerpt:
            excerpt = re.sub(r"\s+", " ", mention.content).strip()
            mention.excerpt = excerpt[:250] if excerpt else None
