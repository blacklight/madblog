import tempfile
import unittest
from pathlib import Path


class TocTest(unittest.TestCase):
    def setUp(self):
        # Import inside setUp so tests are resilient to execution order.
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)

        # Point the app at the temp content.
        self.config.content_dir = str(root)
        self.config.link = "https://example.com"
        self.config.title = "Example"
        self.config.description = "Example feed"

        # Ensure app reads from our markdown directory.
        self.app.pages_dir = str(markdown_dir)

        # Tests shouldn't depend on webmentions.
        self.config.enable_webmentions = False

        self.client = self.app.test_client()

    def test_article_toc_marker_renders(self):
        markdown_dir = Path(self.app.pages_dir)
        (markdown_dir / "toc-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: TOC Post)",
                    "[//]: # (published: 2025-02-13)",
                    "",
                    "# TOC Post",
                    "",
                    "[[TOC]]",
                    "",
                    "## Section 1",
                    "Text",
                    "",
                    "## Section 2",
                    "More text",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rsp = self.client.get("/article/toc-post")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")

        self.assertIn('class="toc"', html)
        self.assertRegex(
            html,
            r'href="#.*section-1.*"|href="#.*section-1"|href="#.*section-1-"',
        )


if __name__ == "__main__":
    unittest.main()
