"""
About page mixin for Madblog.

Provides methods to check for and render the About page with h-card support.
"""

import contextlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

from flask import Flask, Response, has_app_context, make_response, render_template

from madblog.config import config
from madblog.markdown import render_html

logger = logging.getLogger(__name__)


@dataclass
class HCard:
    """
    Represents h-card microformat data for the About page.

    All fields are optional. If not provided in the About page metadata,
    they fall back to the blog configuration values where applicable.
    """

    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    url: Optional[str] = None
    photo: Optional[str] = None
    email: Optional[str] = None
    job_title: Optional[str] = None
    note: Optional[str] = None
    key: Optional[str] = None
    key_fingerprint: Optional[str] = None
    links: list[dict] = field(default_factory=list)
    orgs: list[dict] = field(default_factory=list)

    def has_data(self) -> bool:
        """Check if the h-card has any meaningful data."""
        return bool(
            self.name
            or self.given_name
            or self.family_name
            or self.url
            or self.photo
            or self.email
            or self.job_title
            or self.note
            or self.key
            or self.links
            or self.orgs
        )


def _parse_org_list(org_str: str) -> list[dict]:
    """
    Parse an organization list from metadata.

    Format: "Org Name|https://org.url, Another Org|https://another.url"
    or just: "Org Name, Another Org" (without URLs)
    """
    if not org_str:
        return []

    orgs = []
    for item in org_str.split(","):
        item = item.strip()
        if not item:
            continue

        if "|" in item:
            parts = item.split("|", 1)
            orgs.append({"name": parts[0].strip(), "url": parts[1].strip()})
        else:
            orgs.append({"name": item, "url": None})

    return orgs


def _parse_key_field(key_str: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse the key field from metadata.

    Format: "/key.txt|D90FBA7F76362774" (URL|fingerprint)
    or just: "/key.txt" (URL only)
    """
    if not key_str:
        return None, None

    if "|" in key_str:
        parts = key_str.split("|", 1)
        return parts[0].strip(), parts[1].strip()

    return key_str.strip(), None


def _extract_domain(url: str) -> str:
    """Extract the domain from a URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


def _parse_links_list(links_str: str) -> list[dict]:
    """
    Parse a links list from metadata.

    Format: "https://url1, https://url2" (URLs only)
    or: "Label1|https://url1, Label2|https://url2" (with labels)

    Returns list of dicts with keys: label, url, domain
    """
    if not links_str:
        return []

    links = []
    for item in links_str.split(","):
        item = item.strip()
        if not item:
            continue

        if "|" in item:
            parts = item.split("|", 1)
            url = parts[1].strip()
            links.append(
                {
                    "label": parts[0].strip(),
                    "url": url,
                    "domain": _extract_domain(url),
                }
            )
        else:
            links.append(
                {
                    "label": None,
                    "url": item,
                    "domain": _extract_domain(item),
                }
            )

    return links


class AboutMixin(ABC):
    """
    Mixin that provides About page functionality.

    The About page is rendered from ABOUT.md in pages_dir.
    It supports h-card microformat metadata for author information.
    """

    pages_dir: Path

    @property
    @abstractmethod
    def _app(self) -> Flask: ...

    def _register_about_context_processors(self):
        """Register context processors for About page template variables."""

        @self._app.context_processor
        def inject_has_about_page():
            return {"has_about_page": self.has_about_page()}

    def _get_about_file_path(self) -> Optional[Path]:
        """
        Get the path to the About page markdown file.

        Returns None if no About file exists.
        """
        about_file = Path(self.pages_dir) / "ABOUT.md"
        if about_file.is_file():
            return about_file

        return None

    def has_about_page(self) -> bool:
        """Check if an About page exists."""
        return self._get_about_file_path() is not None

    def _parse_about_metadata(self) -> dict:
        """
        Parse metadata from the About page markdown file.

        Returns empty dict if no About file exists.
        """
        about_file = self._get_about_file_path()
        if not about_file:
            return {}

        with open(about_file, "r") as f:
            metadata = self._parse_metadata_from_markdown(f, "ABOUT.md")  # type: ignore

        metadata["md_file"] = str(about_file)
        return metadata

    def _build_hcard(self, metadata: dict) -> HCard:
        """
        Build an h-card from About page metadata with config fallbacks.

        Metadata keys (all optional):
        - name: Full name
        - given-name: First name
        - family-name: Last name
        - url: Personal URL
        - photo: Photo URL
        - email: Email address (respects hide_email config)
        - job-title: Job title
        - note: Short bio/description
        - key: PGP key URL|fingerprint
        - links: Comma-separated list of rel="me" URLs (Label|URL or URL)
        - org: Comma-separated list of organizations (Name|URL format)
        """
        # Parse key field
        key_url, key_fingerprint = _parse_key_field(metadata.get("key", ""))

        # Determine email (respect hide_email)
        email = metadata.get("email")
        if not email and not config.hide_email:
            email = config.author_email

        # Build links list from metadata and config
        links = _parse_links_list(metadata.get("links", ""))
        link_urls = {link["url"] for link in links}
        if config.external_links:
            for ext_link in config.external_links:
                if ext_link not in link_urls:
                    links.append(
                        {
                            "label": None,
                            "url": ext_link,
                            "domain": _extract_domain(ext_link),
                        }
                    )

        return HCard(
            name=metadata.get("name") or config.author,
            given_name=metadata.get("given-name"),
            family_name=metadata.get("family-name"),
            url=metadata.get("url") or config.author_url or config.link,
            photo=metadata.get("photo") or config.author_photo,
            email=email,
            job_title=metadata.get("job-title"),
            note=metadata.get("note") or config.activitypub_summary,
            key=key_url,
            key_fingerprint=key_fingerprint,
            links=links,
            orgs=_parse_org_list(metadata.get("org", "")),
        )

    def get_about_page(self) -> Optional[Response]:
        """
        Render the About page.

        Returns None if no About page exists.
        """
        about_file = self._get_about_file_path()
        if not about_file:
            return None

        metadata = self._parse_about_metadata()
        hcard = self._build_hcard(metadata)

        with open(about_file, "r") as f:
            content = self._parse_markdown_content(f)  # type: ignore

        title = metadata.get("title", "About")

        with contextlib.ExitStack() as stack:
            if not has_app_context():
                stack.enter_context(self._app.app_context())

            html = render_template(
                "about.html",
                config=config,
                title=title,
                content=render_html(content),
                hcard=hcard,
                description=metadata.get("description", config.description),
                image=metadata.get("image", config.logo),
            )

        response = make_response(html)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response
