import re
from logging import getLogger
from urllib.parse import urljoin

from markdown import markdown

from ._processors import (
    MarkdownActivityPubMentions,
    MarkdownAutolink,
    MarkdownLatex,
    MarkdownMermaid,
    MarkdownTags,
    MarkdownTaskList,
    MarkdownTocMarkers,
)

logger = getLogger(__name__)


_md_extensions = [
    "fenced_code",
    "codehilite",
    "tables",
    "toc",
    "attr_list",
    "sane_lists",
    MarkdownAutolink(),
    MarkdownTaskList(),
    MarkdownTocMarkers(),
    MarkdownLatex(),
    MarkdownMermaid(),
    MarkdownTags(),
    MarkdownActivityPubMentions(),
]


def render_html(md_text: str) -> str:
    """
    Convert Markdown to HTML using Madblog's full extension pipeline.
    """
    try:
        return markdown(
            md_text,
            extensions=_md_extensions,
        )
    except Exception as e:
        logger.warning("Markdown → HTML failed: %s", e)
        return md_text


# Pattern for Markdown links: [text](url) or [text](url "title")
_MARKDOWN_LINK_RE = re.compile(
    r'\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)',
)

# Pattern for Markdown image: ![alt](url) or ![alt](url "title")
_MARKDOWN_IMAGE_RE = re.compile(
    r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)',
)

# Pattern for raw HTML href/src attributes
_HTML_ATTR_RE = re.compile(
    r'((?:href|src)\s*=\s*["\'])(/[^"\']*?)(["\'])',
    re.IGNORECASE,
)


def resolve_relative_urls(md_text: str, base_url: str) -> str:
    """
    Resolve relative URLs in Markdown content to absolute URLs.

    Handles:
    - Markdown links: [text](/path) → [text](https://example.com/path)
    - Markdown images: ![alt](/path) → ![alt](https://example.com/path)
    - Raw HTML href/src: href="/path" → href="https://example.com/path"

    :param md_text: Markdown text with potentially relative URLs.
    :param base_url: Base URL to resolve against (e.g., "https://example.com").
    :return: Markdown text with relative URLs resolved to absolute.
    """
    if not base_url:
        return md_text

    # Normalize base URL (remove trailing slash for consistent urljoin behavior)
    base_url = base_url.rstrip("/")

    def _resolve_md_link(m: re.Match) -> str:
        text = m.group(1)
        url = m.group(2)
        # Check if URL is relative (starts with / but not //)
        if url.startswith("/") and not url.startswith("//"):
            url = urljoin(base_url + "/", url.lstrip("/"))
        return f"[{text}]({url})"

    def _resolve_md_image(m: re.Match) -> str:
        alt = m.group(1)
        url = m.group(2)
        if url.startswith("/") and not url.startswith("//"):
            url = urljoin(base_url + "/", url.lstrip("/"))
        return f"![{alt}]({url})"

    def _resolve_html_attr(m: re.Match) -> str:
        prefix = m.group(1)
        url = m.group(2)
        suffix = m.group(3)
        if url.startswith("/") and not url.startswith("//"):
            url = urljoin(base_url + "/", url.lstrip("/"))
        return f"{prefix}{url}{suffix}"

    # Process in order: images first (to avoid partial matches), then links, then HTML
    result = _MARKDOWN_IMAGE_RE.sub(_resolve_md_image, md_text)
    result = _MARKDOWN_LINK_RE.sub(_resolve_md_link, result)
    result = _HTML_ATTR_RE.sub(_resolve_html_attr, result)

    return result
