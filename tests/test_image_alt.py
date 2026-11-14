"""
Tests for image alt text support: ``image_alt`` metadata, ``<figure>`` /
``<figcaption>`` rendering for body images.
"""

import tempfile
import unittest
from pathlib import Path

from madblog.markdown import meaningful_alt, render_html


class MeaningfulAltTest(unittest.TestCase):
    """Test the alt-text normalization helper."""

    def test_meaningful_values(self):
        self.assertEqual(meaningful_alt("a cat"), "a cat")
        self.assertEqual(meaningful_alt("  a cat  "), "a cat")

    def test_decorative_values(self):
        self.assertEqual(meaningful_alt(""), "")
        self.assertEqual(meaningful_alt(None), "")
        self.assertEqual(meaningful_alt("   "), "")
        self.assertEqual(meaningful_alt("."), "")
        self.assertEqual(meaningful_alt(" . "), "")


class ImageCaptionsRenderTest(unittest.TestCase):
    """Test figure/figcaption generation for Markdown body images."""

    def test_standalone_image_gets_caption(self):
        html = render_html("![A cat](cat.png)\n")
        self.assertIn("<figure", html)
        self.assertIn('class="image-figure"', html)
        self.assertIn("<figcaption", html)
        self.assertIn("A cat", html)
        self.assertIn('alt="A cat"', html)

    def test_image_without_alt_has_no_caption(self):
        html = render_html("![](cat.png)\n")
        self.assertNotIn("<figure", html)
        self.assertNotIn("<figcaption", html)

    def test_dot_alt_is_decorative(self):
        html = render_html("![.](cat.png)\n")
        self.assertNotIn("<figure", html)
        self.assertNotIn("<figcaption", html)

    def test_inline_image_not_wrapped(self):
        html = render_html("Some text ![A cat](cat.png) more text\n")
        self.assertNotIn("<figure", html)
        self.assertIn('alt="A cat"', html)

    def test_image_title_attribute_preserved(self):
        html = render_html('![A cat](cat.png "Tooltip")\n')
        self.assertIn("<figure", html)
        self.assertIn('title="Tooltip"', html)


class ImageAltRouteTest(unittest.TestCase):
    """Test banner image alt text on rendered article pages."""

    def setUp(self):
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)

        (markdown_dir / "with-alt.md").write_text(
            "\n".join(
                [
                    "---",
                    "title: Post With Alt",
                    "image: /img/banner.png",
                    "image_alt: A nice banner",
                    "---",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "with-caption.md").write_text(
            "\n".join(
                [
                    "---",
                    "title: Post With Caption",
                    "image: /img/banner.png",
                    "image_alt: A nice banner",
                    "image_caption: Banner caption text",
                    "---",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "caption-only.md").write_text(
            "\n".join(
                [
                    "---",
                    "title: Post With Caption Only",
                    "image: /img/banner.png",
                    "image_caption: Banner caption text",
                    "---",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "no-alt.md").write_text(
            "\n".join(
                [
                    "---",
                    "title: Post Without Alt",
                    "image: /img/banner.png",
                    "---",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "dot-alt.md").write_text(
            "\n".join(
                [
                    "---",
                    "title: Post With Decorative Banner",
                    "image: /img/banner.png",
                    'image_alt: "."',
                    "---",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_title = config.title

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.title = "Test Blog"

        self.app.pages_dir = markdown_dir
        self.app.replies_dir = root / "replies"

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link
        self.config.title = self._orig_title

    def test_banner_alt_without_caption(self):
        with self.app.test_client() as client:
            resp = client.get("/article/with-alt")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('alt="A nice banner"', html)
            self.assertNotIn("<figcaption", html)

    def test_banner_alt_and_caption_rendered(self):
        with self.app.test_client() as client:
            resp = client.get("/article/with-caption")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('alt="A nice banner"', html)
            self.assertIn("<figcaption", html)
            self.assertIn("Banner caption text", html)
            self.assertNotIn(">A nice banner</figcaption>", html)

    def test_banner_caption_only_reused_as_alt(self):
        with self.app.test_client() as client:
            resp = client.get("/article/caption-only")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('alt="Banner caption text"', html)
            self.assertIn("<figcaption", html)
            self.assertIn("Banner caption text", html)

    def test_banner_without_alt_is_decorative(self):
        with self.app.test_client() as client:
            resp = client.get("/article/no-alt")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('alt="."', html)
            self.assertNotIn("<figcaption", html)

    def test_dot_alt_is_decorative(self):
        with self.app.test_client() as client:
            resp = client.get("/article/dot-alt")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertNotIn("<figcaption", html)
