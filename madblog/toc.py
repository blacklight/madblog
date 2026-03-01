import re

import markdown


_TOC_MARKER_RE = re.compile(
    r"^\s*(?:\[\[TOC\]\]|\[TOC\]|\{\{\s*TOC\s*\}\}|<!--\s*TOC\s*-->)\s*$",
    re.IGNORECASE,
)


class TocMarkerPreprocessor(markdown.preprocessors.Preprocessor):
    def run(self, lines):
        replaced = False
        out = []
        for line in lines:
            if _TOC_MARKER_RE.match(line):
                out.append("[TOC]")
                replaced = True
            else:
                out.append(line)

        return out if replaced else lines


class MarkdownTocMarkers(markdown.Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(
            TocMarkerPreprocessor(md),
            "toc_markers",
            40,
        )
