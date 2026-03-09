import markdown
import markdown.preprocessors

from madblog.constants import REGEX_TOC_MARKER


class TocMarkerPreprocessor(  # pylint: disable=too-few-public-methods
    markdown.preprocessors.Preprocessor
):
    """
    Replace ``[[TOC]]`` markers with ``[TOC]``.
    """

    def run(self, lines):
        replaced = False
        out = []
        for line in lines:
            if REGEX_TOC_MARKER.match(line):
                out.append("[TOC]")
                replaced = True
            else:
                out.append(line)

        return out if replaced else lines


class MarkdownTocMarkers(markdown.Extension):
    """
    Replace ``[[TOC]]`` markers with ``[TOC]``.
    """

    def extendMarkdown(self, md):
        md.preprocessors.register(
            TocMarkerPreprocessor(md),
            "toc_markers",
            40,
        )
