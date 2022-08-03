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
"""

import base64
import hashlib
import json
import os
import re
import tempfile
from subprocess import call as rawcall, PIPE

import markdown


def call(*args, **kwargs):
    """
    Proxy to subprocess.call(), removes timeout argument in case of
    Python2 because that was only implemented in Python3.
    """
    return rawcall(*args, **kwargs)


# Defines our basic inline image
img_expr = '<img class="latex inline math-%s" alt="%s" id="%s" src="data:image/png;base64,%s">'

# Defines multiline expression image
multiline_img_expr = '''<div class="multiline-wrapper">
<img class="latex multiline math-%s" alt="%s" id="%s" src="data:image/png;base64,%s"></div>'''

# Base CSS template
img_css = """<style scoped>
.multiline-wrapper {
    width: 100%;
    text-align: center;
}

img.latex.multiline {
    height: 65%;
}

img.latex.inline {
    height: .9em;
    vertical-align: middle;
}
</style>"""

# Cache and temp file paths
tmpdir = tempfile.gettempdir() + '/markdown-latex'
cache_file = tmpdir + '/latex.cache'


class LaTeXPreprocessor(markdown.preprocessors.Preprocessor):
    # These are our cached expressions that are stored in latex.cache
    cached = {}

    # Basic LaTex Setup as well as our list of expressions to parse
    tex_preamble = r"""\documentclass[14pt]{article}
\usepackage{amsmath}
\usepackage{amsthm}
\usepackage{amssymb}
\usepackage{bm}
\usepackage{graphicx}
\usepackage[usenames,dvipsnames]{color}
\pagestyle{empty}
"""

    # Math TeX extraction regex
    math_extract_regex = re.compile(r'(.+?)((\\\(.+?\\\))|(\$\$\n.+?\n\$\$\n))(.*)', re.MULTILINE | re.DOTALL)

    # Math TeX matching regex
    math_match_regex = re.compile(r'\s*(\\\(.+?\\\))|(\$\$\n.+?\n\$\$\n)\s*', re.MULTILINE | re.DOTALL)

    def __init__(self, *_, **__):
        if not os.path.isdir(tmpdir):
            os.makedirs(tmpdir)
        try:
            with open(cache_file, 'r') as f:
                self.cached = json.load(f)
        except (IOError, json.JSONDecodeError):
            self.cached = {}

        self.config = {
            ("general", "preamble"): "",
            ("dvipng", "args"): "-q -T tight -bg Transparent -z 9 -D 200",
            ("delimiters", "text"): "%",
            ("delimiters", "math"): "$",
            ("delimiters", "preamble"): "%%"}

    def _latex_to_base64(self, tex):
        """Generates a base64 representation of TeX string"""

        # Generate the temporary file
        tmp_file_fd, path = tempfile.mkstemp(dir=tmpdir)
        with os.fdopen(tmp_file_fd, "w") as tmp_file:
            tmp_file.write(self.tex_preamble)
            tmp_file.write(tex)
            tmp_file.write('\n\\end{document}')

        # compile LaTeX document. A DVI file is created
        status = call(('latex -halt-on-error -output-directory={:s} {:s}'
                       .format(tmpdir, path)).split(),
                      stdout=PIPE, timeout=10)

        # clean up if the above failed
        if status:
            self._cleanup(path, err=True)
            raise Exception("Couldn't compile LaTeX document." +
                            "Please read '%s.log' for more detail." % path)

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
            raise Exception("Couldn't convert LaTeX to image." +
                            "Please read '%s.log' for more detail." % path)

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
        # Checks for the LaTeX header
        use_latex = any(line == '[//]: # (latex: 1)' for line in lines)
        if not use_latex:
            return lines

        # Re-creates the entire page so we can parse in a multiline env.
        page = "\n".join(lines)

        # Adds a preamble mode
        self.tex_preamble += self.config[("general", "preamble")] + "\n\\begin{document}\n"

        # Figure out our text strings and math-mode strings
        tex_expr = self.math_extract_regex.findall(page)

        # No sense in doing the extra work
        if not len(tex_expr):
            return page.split("\n")

        # Parse the expressions
        new_cache = {}
        new_page = ''
        n_multiline_expressions = 0

        while page:
            m = self.math_extract_regex.match(page)
            if not m:
                new_page += page
                break

            new_page += m.group(1)
            math_match = self.math_match_regex.match(m.group(2))
            if not math_match:
                new_page += m.group(2)
            else:
                expr = m.group(2)
                is_multiline = math_match.group(2) is not None
                tex_hash = self.hash(expr)
                if tex_hash in self.cached:
                    data = self.cached[tex_hash]
                else:
                    data = self._latex_to_base64(expr).decode()
                    new_cache[tex_hash] = data

                if is_multiline and n_multiline_expressions > 0:
                    new_page += '</p>'
                new_page += (multiline_img_expr if is_multiline else img_expr) % ('true', expr, tex_hash, data)

                if is_multiline:
                    new_page += '<p>'
                    n_multiline_expressions += 1

            page = m.group(5)

        if n_multiline_expressions > 0:
            new_page += '</p>'

        # Cache our data
        self.cached.update(new_cache)
        with open(cache_file, 'w') as f:
            json.dump(self.cached, f)

        # Make sure to re-split the lines
        return new_page.split("\n")

    @staticmethod
    def hash(tex: str) -> str:
        return hashlib.sha1(tex.encode()).hexdigest()


class MarkdownLatex(markdown.Extension):
    """Wrapper for LaTeXPreprocessor"""

    def extendMarkdown(self, md):
        md.preprocessors.register(
             LaTeXPreprocessor(self),
            'latex',
            1,
        )
