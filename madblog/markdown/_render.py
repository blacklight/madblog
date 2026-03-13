import os
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

# Pattern for raw HTML href/src attributes (matches both absolute and relative)
_HTML_ATTR_RE = re.compile(
    r'((?:href|src)\s*=\s*["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)

# Protocols that should not be treated as relative paths
_NON_RELATIVE_PROTOCOLS = frozenset(
    {"mailto:", "tel:", "javascript:", "data:", "blob:", "file:"}
)


def _is_relative_url(url: str) -> bool:
    """
    Check if a URL is a relative path that should be resolved.

    Returns True for:
    - Root-relative: /path, /article/foo
    - Current-relative: ./path, article, ../path

    Returns False for:
    - Absolute URLs: http://..., https://...
    - Protocol-relative: //example.com
    - Anchors: #section
    - Query strings: ?foo=bar
    - Special protocols: mailto:, tel:, javascript:, data:, etc.
    """
    if not url:
        return False

    # Absolute URL with protocol
    if "://" in url:
        return False

    # Protocol-relative URL
    if url.startswith("//"):
        return False

    # Anchor or query string only
    if url.startswith("#") or url.startswith("?"):
        return False

    # Special protocols without ://
    url_lower = url.lower()
    for proto in _NON_RELATIVE_PROTOCOLS:
        if url_lower.startswith(proto):
            return False

    return True


def _resolve_path(url: str, base_url: str, current_uri: str, base_path: str) -> str:
    """
    Resolve a relative URL to an absolute URL.

    :param url: The URL to resolve (may be /path, ./path, ../path, or bare path)
    :param base_url: The site base URL (e.g., "https://example.com")
    :param current_uri: The current page URI (e.g., "/article/2025/my-post")
    :param base_path: The minimum path prefix to enforce (e.g., "/article")
    :return: Absolute URL
    """
    if url.startswith("/") and not url.startswith("//"):
        # Root-relative: /path → https://example.com/path
        return urljoin(base_url + "/", url.lstrip("/"))

    if not current_uri:
        # No current URI context, can't resolve relative paths
        return url

    # Get the directory of the current URI (e.g., /article/2025/my-post → /article/2025)
    current_dir = os.path.dirname(current_uri)

    # Resolve the relative path
    if url.startswith("./"):
        # Explicit current-directory relative: ./other → /article/2025/other
        resolved = os.path.normpath(os.path.join(current_dir, url[2:]))
    elif url.startswith("../"):
        # Parent-directory relative: ../other → /article/other
        resolved = os.path.normpath(os.path.join(current_dir, url))
    else:
        # Bare relative path: other → /article/2025/other
        resolved = os.path.normpath(os.path.join(current_dir, url))

    # Prevent directory traversal above base_path
    if base_path and not resolved.startswith(base_path):
        resolved = base_path + "/" + os.path.basename(resolved)

    # Ensure path starts with /
    if not resolved.startswith("/"):
        resolved = "/" + resolved

    return base_url + resolved


def resolve_relative_urls(
    md_text: str,
    base_url: str,
    current_uri: str = "",
    base_path: str = "/article",
) -> str:
    """
    Resolve relative URLs in Markdown content to absolute URLs.

    Handles:
    - Root-relative: [text](/path) → [text](https://example.com/path)
    - Current-relative: [text](./path) → [text](https://example.com/article/dir/path)
    - Parent-relative: [text](../path) → [text](https://example.com/article/path)
    - Bare relative: [text](path) → [text](https://example.com/article/dir/path)
    - Same patterns for images and raw HTML href/src attributes

    Directory traversal via ../ is prevented from going above base_path.

    :param md_text: Markdown text with potentially relative URLs.
    :param base_url: Base URL to resolve against (e.g., "https://example.com").
    :param current_uri: Current page URI for resolving relative paths
        (e.g., "/article/2025/my-post").
    :param base_path: Minimum path prefix to enforce for traversal prevention
        (default: "/article").
    :return: Markdown text with relative URLs resolved to absolute.
    """
    if not base_url:
        return md_text

    # Normalize base URL (remove trailing slash for consistent urljoin behavior)
    base_url = base_url.rstrip("/")

    def _resolve_md_link(m: re.Match) -> str:
        text = m.group(1)
        url = m.group(2)
        if _is_relative_url(url):
            url = _resolve_path(url, base_url, current_uri, base_path)
        return f"[{text}]({url})"

    def _resolve_md_image(m: re.Match) -> str:
        alt = m.group(1)
        url = m.group(2)
        if _is_relative_url(url):
            url = _resolve_path(url, base_url, current_uri, base_path)
        return f"![{alt}]({url})"

    def _resolve_html_attr(m: re.Match) -> str:
        prefix = m.group(1)
        url = m.group(2)
        suffix = m.group(3)
        if _is_relative_url(url):
            url = _resolve_path(url, base_url, current_uri, base_path)
        return f"{prefix}{url}{suffix}"

    # Process in order: images first (to avoid partial matches), then links, then HTML
    result = _MARKDOWN_IMAGE_RE.sub(_resolve_md_image, md_text)
    result = _MARKDOWN_LINK_RE.sub(_resolve_md_link, result)
    result = _HTML_ATTR_RE.sub(_resolve_html_attr, result)

    return result
