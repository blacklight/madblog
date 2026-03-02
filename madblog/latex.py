"""
Licensed under Public Domain Mark 1.0.
See https://creativecommons.org/publicdomain/mark/1.0/
Author: Justin Bruce Van Horne <justinvh@gmail.com>

Python-Markdown LaTeX Extension
Adds support for $math mode$ and %text mode%. This plugin supports
multiline equations/text.
The actual image generation is done via LaTeX/DVI output.
It encodes data as base64 so there is no need for images directly.
All the work is done in the preprocessor.

Adapted by Fabio Manganiello <info@fabiomanganiello.com>
"""

import base64
import logging
import os
import re
import shutil
import tempfile
from subprocess import call as rawcall, PIPE

import markdown
import markdown.preprocessors

from .cache import RenderCache

logger = logging.getLogger(__name__)


def call(*args, **kwargs):
    """
    Proxy to subprocess.call(), removes timeout argument in case of
    Python2 because that was only implemented in Python3.
    """
    return rawcall(*args, **kwargs)


def _latex_available():
    """Check whether both latex and dvipng are on PATH."""
    return shutil.which("latex") is not None and shutil.which("dvipng") is not None


# Defines our basic inline image
img_expr = '<img class="latex inline" id="%s" src="data:image/png;base64,%s">'

# Defines block/display expression image
block_img_expr = '<div class="latex-block"><img class="latex block" id="%s" src="data:image/png;base64,%s"></div>'


class LaTeXPreprocessor(markdown.preprocessors.Preprocessor):
    # Basic LaTex Setup as well as our list of expressions to parse
    tex_preamble = r"""\documentclass[10pt]{article}
\usepackage{amsmath}
\usepackage{amsthm}
\usepackage{amssymb}
\usepackage{bm}
\usepackage{graphicx}
\usepackage[usenames,dvipsnames]{color}
\pagestyle{empty}
"""

    # Matches all common LaTeX delimiters:
    #   Block/display: $$...$$ or \[...\] or $...$ alone on a line
    #   Inline: $...$ (within other text) or \(...\)
    _latex_re = re.compile(
        r"(\$\$.+?\$\$)"  # $$...$$ (block)
        r"|(\\\[.+?\\\])"  # \[...\] (block)
        r"|(\\\(.+?\\\))",  # \(...\) (inline)
        # r"|(^\s*\$.+?\$\s*$)"  # $...$ alone on a line (block)
        # r"|(?<!\$)(\$.+?\$)(?!\$)",  # $...$ with surrounding text (inline)
        re.DOTALL | re.MULTILINE,
    )

    def __init__(self, *_, **__):
        self.cache = RenderCache("latex")

        self.config = {
            ("general", "preamble"): "",
            ("dvipng", "args"): "-q -T tight -bg Transparent -z 9 -D 150",
            ("delimiters", "text"): "%",
            ("delimiters", "math"): "$",
            ("delimiters", "preamble"): "%%",
        }

    def _latex_to_base64(self, tex):
        """Generates a base64 representation of TeX string"""
        tmpdir = str(self.cache.tmpdir)

        # Generate the temporary file
        tmp_file_fd, path = tempfile.mkstemp(dir=tmpdir)
        with os.fdopen(tmp_file_fd, "w") as tmp_file:
            tmp_file.write(self.tex_preamble)
            tmp_file.write(tex)
            tmp_file.write("\n\\end{document}")

        # compile LaTeX document. A DVI file is created
        status = call(
            (
                "latex -halt-on-error -output-directory={:s} {:s}".format(tmpdir, path)
            ).split(),
            stdout=PIPE,
            timeout=10,
        )

        # clean up if the above failed
        if status:
            self._cleanup(path, err=True)
            logger.warning(
                "Couldn't compile LaTeX document. See '%s.log' for detail.", path
            )
            return None

        # Run dvipng on the generated DVI file. Use tight bounding box.
        # Magnification is set to 1200
        dvi = "%s.dvi" % path
        png = "%s.png" % path

        # Extract the image
        cmd = "dvipng %s %s -o %s" % (self.config[("dvipng", "args")], dvi, png)
        status = call(cmd.split(), stdout=PIPE)

        # clean up if we couldn't make the above work
        if status:
            self._cleanup(path, err=True)
            logger.warning(
                "Couldn't convert DVI to PNG. See '%s.log' for detail.", path
            )
            return None

        # Read the png and encode the data
        try:
            with open(png, "rb") as png:
                data = png.read()
                return base64.b64encode(data)
        finally:
            self._cleanup(path)

    @staticmethod
    def _cleanup(path, err=False):
        # don't clean up the log if there's an error
        extensions = ["", ".aux", ".dvi", ".png", ".log"]
        if err:
            extensions.pop()

        # now do the actual cleanup, passing on non-existent files
        for extension in extensions:
            try:
                os.remove("%s%s" % (path, extension))
            except (IOError, OSError):
                pass

    def run(self, lines):
        """Parses the actual page"""
        page = "\n".join(lines)

        # Auto-detect: only proceed if the page contains LaTeX delimiters
        if not self._latex_re.search(page):
            return lines

        # Skip rendering entirely if latex/dvipng aren't installed
        if not _latex_available():
            logger.debug("latex or dvipng not found on PATH; skipping LaTeX rendering")
            return lines

        # Adds a preamble mode
        self.tex_preamble += (
            self.config[("general", "preamble")] + "\n\\begin{document}\n"
        )

        def _replace(m):
            # Groups: 1=$$..$$, 2=\[..\], 3=\(..\), 4=$..$ alone on line, 5=$..$ inline
            num_groups = len(m.groups())
            is_block = (
                m.group(1) is not None
                or m.group(2) is not None
                or (num_groups >= 4 and m.group(4) is not None)
            )
            expr = m.group(0)

            tex_hash = self.cache.hash(expr)
            cached = self.cache.get(tex_hash)
            if cached is not None:
                data = cached
            else:
                try:
                    result = self._latex_to_base64(expr)
                except Exception as e:
                    logger.warning("LaTeX rendering failed for expression: %s", e)
                    return expr

                if result is None:
                    return expr

                data = result.decode()
                self.cache.put(tex_hash, data)

            if is_block:
                return block_img_expr % (tex_hash, data)
            return img_expr % (tex_hash, data)

        new_page = self._latex_re.sub(_replace, page)
        return new_page.split("\n")


class MarkdownLatex(markdown.Extension):
    """Wrapper for LaTeXPreprocessor"""

    def extendMarkdown(self, md):
        md.preprocessors.register(
            LaTeXPreprocessor(self),
            "latex",
            1,
        )
