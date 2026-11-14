"""Tests for custom CSS/JS assets under <content_dir>/{css,js}."""

import tempfile
from pathlib import Path
from unittest import TestCase

from madblog.app import app
from madblog.config import config


class CustomAssetsTestCase(TestCase):
    """Base test case with a temporary content directory."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.markdown_dir = root / "markdown"
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        config.content_dir = str(root)
        config.link = "http://test.local"
        config.title = "Test Blog"
        config.author = "Test Author"
        config.enable_webmentions = False

        app.pages_dir = self.markdown_dir
        app.replies_dir = root / "replies"
        app.css_dir = str(root / "css")
        app.js_dir = str(root / "js")
        self.client = app.test_client()

    def _write(self, rel_path: str, content: str = "") -> Path:
        """Write a file relative to the content dir."""
        path = Path(config.content_dir) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def _create_article(self, filename: str = "post.md") -> None:
        self._write(f"markdown/{filename}", "# Test Article\n\nThis is test content.\n")


class CustomAssetsInjectionTest(CustomAssetsTestCase):
    """Custom assets are injected into rendered pages."""

    def test_custom_css_and_js_injected(self):
        """Custom assets appear as link/script tags on the index page."""
        self._create_article()
        self._write("css/custom.css", "body { color: red; }")
        self._write("js/custom.js", "console.log('hi');")

        response = self.client.get("/")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert '<link rel="stylesheet" type="text/css" href="/css/custom.css">' in html
        assert '<script src="/js/custom.js"></script>' in html
        # Custom CSS must come after the built-in stylesheets
        assert html.index("/css/common.css") < html.index("/css/custom.css")
        assert html.index("/css/home.css") < html.index("/css/custom.css")

    def test_custom_assets_served(self):
        """Files under content_dir/css and content_dir/js are served."""
        self._write("css/custom.css", "body { color: blue; }")
        self._write("js/custom.js", "console.log('served');")

        css_response = self.client.get("/css/custom.css")
        assert css_response.status_code == 200
        assert b"color: blue" in css_response.data

        js_response = self.client.get("/js/custom.js")
        assert js_response.status_code == 200
        assert b"console.log" in js_response.data

    def test_no_custom_assets_no_tags(self):
        """Pages render without custom asset tags when dirs are absent."""
        self._create_article()

        response = self.client.get("/")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "/css/custom.css" not in html
        assert "/js/custom.js" not in html

    def test_builtin_shadowing_files_not_duplicated(self):
        """Files matching built-in names override but are not re-injected."""
        self._write("css/common.css", "/* user override */")
        self._write("js/article.js", "/* user override */")

        response = self.client.get("/")
        html = response.get_data(as_text=True)

        # common.css is already linked once; it must not appear twice
        assert html.count('href="/css/common.css"') == 1

        # The user-provided file is served at the built-in URL
        css_response = self.client.get("/css/common.css")
        assert b"user override" in css_response.data

    def test_non_matching_files_ignored(self):
        """Non-css/js files and subdirectories are not injected."""
        self._write("css/notes.txt", "text")
        self._write("css/style.CSS", "x")
        self._write("js/data.json", "{}")
        self._write("css/sub/nested.css", "x")

        assets = app._custom_asset_urls()

        assert "/css/notes.txt" not in assets["css"]
        assert "/css/style.CSS" in assets["css"]
        assert "/js/data.json" not in assets["js"]
        assert not any("nested" in u for u in assets["css"])

    def test_custom_assets_on_article_page(self):
        """Custom assets are injected on article pages too."""
        self._create_article()
        self._write("css/custom.css", "body {}")
        self._write("js/custom.js", "// x")

        response = self.client.get("/article/post")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert 'href="/css/custom.css"' in html
        assert 'src="/js/custom.js"' in html
