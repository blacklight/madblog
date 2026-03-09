from logging import getLogger

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
