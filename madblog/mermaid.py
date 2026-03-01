"""
Markdown extension: renders ```mermaid``` fenced code blocks to inline SVG
via mmdc (Mermaid CLI). Requires Node.js and @mermaid-js/mermaid-cli.
"""

import json
import logging
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import markdown

from .cache import RenderCache

logger = logging.getLogger(__name__)

# Match ```mermaid ... ``` blocks in raw Markdown.
# Runs as a preprocessor so fenced_code never sees these blocks.
_MERMAID_BLOCK_RE = re.compile(
    r"^```mermaid\s*\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)

# Mermaid themes mapped to our light/dark keys.
_THEMES = {
    "light": "default",
    "dark": "dark",
}

# Mermaid JSON config: render at natural size so text is never truncated,
# generous node padding, and readable edge labels.
_MERMAID_CONFIG = {
    "flowchart": {
        "htmlLabels": True,
        "padding": 15,
        "nodeSpacing": 30,
        "rankSpacing": 50,
        "useMaxWidth": False,
    },
}


class MermaidPreprocessor(markdown.preprocessors.Preprocessor):
    def __init__(self, *_, **__):
        super().__init__()
        self.cache = RenderCache("mermaid")
        self._cmd = self._resolve_cmd()
        if not self._cmd:
            logger.warning(
                "Neither mmdc nor npx found in PATH — Mermaid blocks will be "
                "rendered as plain code. Install with: pip install madblog[mermaid]"
            )

        # Write a shared mermaid config file for mmdc.
        self._config_file = self.cache.tmpdir / "mermaid-config.json"
        self._config_file.write_text(json.dumps(_MERMAID_CONFIG))

    @staticmethod
    def _resolve_cmd() -> Optional[list]:
        """Return the base command to invoke mmdc, or None if unavailable."""
        if shutil.which("mmdc"):
            return ["mmdc"]
        if shutil.which("npx"):
            logger.info(
                "mmdc not found in PATH — will use npx to run "
                "@mermaid-js/mermaid-cli. First render may be slow while "
                "dependencies are fetched."
            )
            return ["npx", "-y", "@mermaid-js/mermaid-cli"]
        return None

    def _render_svg(self, source: str, theme_key: str) -> str:
        """Render Mermaid source to SVG string for a given theme."""
        mmdc_theme = _THEMES[theme_key]
        cache_key = self.cache.hash(source, theme_key)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        in_file = self.cache.tmpdir / f"{cache_key}.mmd"
        out_file = self.cache.tmpdir / f"{cache_key}.svg"

        try:
            in_file.write_text(source)
            logger.info("Rendering Mermaid diagram (%s theme)...", theme_key)

            if not self._cmd:
                return source

            result = subprocess.run(
                [
                    *self._cmd,
                    "-i",
                    str(in_file),
                    "-o",
                    str(out_file),
                    "-t",
                    mmdc_theme,
                    "-b",
                    "transparent",
                    "-c",
                    str(self._config_file),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.error("mmdc failed: %s", result.stderr)
                return ""

            svg = out_file.read_text()
            # Give each SVG a unique ID so scoped <style> rules
            # don't collide when multiple diagrams are on one page.
            # Replace all occurrences of the default "my-svg" id —
            # this covers the root id, CSS selectors (#my-svg),
            # and marker id/url references (my-svg_flowchart-...).
            svg_id = f"mermaid-{cache_key}"
            svg = svg.replace("my-svg", svg_id)
            # Strip mermaid's inline max-width on the root SVG so CSS
            # controls scaling.
            svg = re.sub(
                r'(<svg[^>]*style="[^"]*?)max-width:\s*[^;"]+;?\s*',
                r"\1",
                svg,
            )
            # Remove max-width on node/edge label divs that causes
            # text clipping.
            svg = re.sub(
                r'(style="[^"]*?)max-width:\s*200px;?\s*',
                r"\1",
                svg,
            )
            # Add overflow:visible to non-empty foreignObjects so
            # text is never clipped by sizing mismatches.
            svg = re.sub(
                r'<foreignObject width="(?!0")',
                r'<foreignObject style="overflow:visible" width="',
                svg,
            )
            # Remove edge label backgrounds — they cause visual
            # artifacts and alignment issues.
            svg = re.sub(
                r"(\.edgeLabel\s*\{)[^}]*(})",
                r"\1background-color:transparent;text-align:center;\2",
                svg,
            )
            svg = re.sub(
                r"(\.edgeLabel p\s*\{)[^}]*(})",
                r"\1background-color:transparent;\2",
                svg,
            )
            svg = re.sub(
                r"(\.edgeLabel rect\s*\{)[^}]*(})",
                r"\1opacity:0;fill:none;\2",
                svg,
            )
            # Strip labelBkg backgrounds (both CSS rules and inline).
            svg = re.sub(
                r"(\.labelBkg\s*\{)[^}]*(})",
                r"\1background-color:transparent;\2",
                svg,
            )
            self.cache.put(cache_key, svg)
            return svg
        finally:
            in_file.unlink(missing_ok=True)
            out_file.unlink(missing_ok=True)

    @staticmethod
    def _build_html(light_svg: str, dark_svg: str) -> str:
        """Wrap light/dark SVG variants in a togglable container."""
        parts = ['<div class="mermaid-wrapper">']
        if light_svg:
            parts.append(f'<div class="mermaid-light">{light_svg}</div>')
        if dark_svg:
            parts.append(f'<div class="mermaid-dark">{dark_svg}</div>')
        parts.append("</div>")
        return "\n".join(parts)

    def run(self, lines):
        if not self._cmd:
            return lines

        page = "\n".join(lines)
        blocks = list(_MERMAID_BLOCK_RE.finditer(page))
        if not blocks:
            return lines

        # Collect all (source, theme) render jobs.
        sources = [m.group(1) for m in blocks]
        jobs = []
        for src in sources:
            for theme_key in _THEMES:
                jobs.append((src, theme_key))

        # Render all variants in parallel.
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda j: self._render_svg(*j), jobs))

        # Map results back: 2 results per block (light, dark).
        rendered = {}
        for i, src in enumerate(sources):
            rendered[src] = {
                "light": results[i * 2],
                "dark": results[i * 2 + 1],
            }

        # Substitute blocks in reverse order to preserve offsets.
        for m in reversed(blocks):
            src = m.group(1)
            light_svg = rendered[src]["light"]
            dark_svg = rendered[src]["dark"]
            if not light_svg and not dark_svg:
                continue
            html = self._build_html(light_svg, dark_svg)
            page = page[: m.start()] + html + page[m.end() :]

        return page.split("\n")


class MarkdownMermaid(markdown.Extension):
    """Wrapper for MermaidPreprocessor"""

    def extendMarkdown(self, md):
        # Priority 30 > fenced_code (25) so we consume ```mermaid``` first.
        md.preprocessors.register(
            MermaidPreprocessor(self),
            "mermaid",
            30,
        )
