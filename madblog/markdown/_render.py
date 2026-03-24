import os
import re
from logging import getLogger
from typing import List, Union
from urllib.parse import urljoin

from markdown import Extension, markdown
from markdown.extensions.codehilite import CodeHiliteExtension

from madblog.config import config

from ._processors import (
    MarkdownActivityPubMentions,
    MarkdownAutolink,
    MarkdownTags,
    MarkdownTaskList,
    MarkdownTocMarkers,
)

# Pattern for fenced code block delimiters
_FENCE_PATTERN = re.compile(r"^(`{3,}|~{3,})")

# Pattern for list items: leading spaces + list marker (unordered or ordered)
_LIST_ITEM_PATTERN = re.compile(r"^( *)([*+-]|\d+[.)]) ")


def _normalize_list_indentation(text: str) -> str:
    """
    Normalize 4-space list indentation to 2-space.

    Only affects lines that are clearly list items (unordered or ordered).
    Preserves fenced code blocks and other content unchanged.
    """
    lines = text.split("\n")
    result = []
    in_fenced_block = False

    for line in lines:
        # Check for fenced code block boundaries
        if _FENCE_PATTERN.match(line.lstrip()):
            in_fenced_block = not in_fenced_block
            result.append(line)
            continue

        if in_fenced_block:
            result.append(line)
            continue

        # Check if this is a list item
        match = _LIST_ITEM_PATTERN.match(line)
        if match:
            leading_spaces = match.group(1)
            # Only normalize if indentation is a multiple of 4
            if len(leading_spaces) > 0 and len(leading_spaces) % 4 == 0:
                new_indent = "  " * (len(leading_spaces) // 4)
                line = new_indent + line[len(leading_spaces) :]

        result.append(line)

    return "\n".join(result)


logger = getLogger(__name__)

# Cached extensions list (built lazily on first render)
_md_extensions: List[Union[str, Extension]] | None = None


def _build_extensions() -> List[Union[str, Extension]]:
    """
    Build the list of Markdown extensions based on current config.

    LaTeX and Mermaid extensions are only loaded if their respective
    config flags are enabled, avoiding heavy dependency initialization
    when not needed.
    """
    extensions: List[Union[str, Extension]] = [
        "fenced_code",
        CodeHiliteExtension(guess_lang=False),
        "tables",
        "toc",
        "attr_list",
        "sane_lists",
        MarkdownAutolink(),
        MarkdownTaskList(),
        MarkdownTocMarkers(),
    ]

    if config.enable_latex:
        from ._processors.latex import MarkdownLatex

        extensions.append(MarkdownLatex())
        logger.debug("LaTeX extension enabled")

    if config.enable_mermaid:
        from ._processors.mermaid import MarkdownMermaid

        extensions.append(MarkdownMermaid())
        logger.debug("Mermaid extension enabled")

    extensions.extend(
        [
            MarkdownTags(),
            MarkdownActivityPubMentions(),
        ]
    )

    return extensions


def _get_extensions() -> List[Union[str, Extension]]:
    """Return cached extensions list, building it on first call."""
    global _md_extensions
    if _md_extensions is None:
        _md_extensions = _build_extensions()
    return _md_extensions


def render_html(md_text: str) -> str:
    """
    Convert Markdown to HTML using Madblog's full extension pipeline.
    """
    preprocessors = (_normalize_list_indentation,)

    try:
        for preprocessor in preprocessors:
            md_text = preprocessor(md_text)

        return markdown(
            md_text,
            extensions=_get_extensions(),
            tab_length=2,
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
