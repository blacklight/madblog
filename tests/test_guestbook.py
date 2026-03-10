"""
Tests for the Guestbook feature in Madblog.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class GuestbookConfigTest(unittest.TestCase):
    """Test that guestbook config options are parsed correctly."""

    def test_defaults(self):
        from madblog.config import Config

        cfg = Config()
        self.assertTrue(cfg.enable_guestbook)

    def test_env_var(self):
        import os
        from madblog.config import config, _init_config_from_env

        with patch.dict(os.environ, {"MADBLOG_ENABLE_GUESTBOOK": "0"}, clear=False):
            _init_config_from_env()

        self.assertFalse(config.enable_guestbook)

        # Reset
        config.enable_guestbook = True


class GuestbookMixinTest(unittest.TestCase):
    """Test the GuestbookMixin helper methods."""

    def setUp(self):
        from madblog.config import config

        self.config = config
        self._orig_link = config.link
        self._orig_activitypub_link = config.activitypub_link
        config.link = "https://example.com"
        config.activitypub_link = None

    def tearDown(self):
        self.config.link = self._orig_link
        self.config.activitypub_link = self._orig_activitypub_link

    def test_is_home_page_url(self):
        from madblog.guestbook._mixin import GuestbookMixin

        # Create a minimal mock that includes the mixin
        class MockApp(GuestbookMixin):
            mentions_dir = Path("/tmp")

            @property
            def _app(self):
                return MagicMock()

        app = MockApp()

        # Should match home page
        self.assertTrue(app._is_home_page_url("https://example.com"))
        self.assertTrue(app._is_home_page_url("https://example.com/"))

        # Should not match articles
        self.assertFalse(app._is_home_page_url("https://example.com/article/test"))
        self.assertFalse(app._is_home_page_url("https://other.com"))
        self.assertFalse(app._is_home_page_url(""))

    def test_is_article_url(self):
        from madblog.guestbook._mixin import GuestbookMixin

        class MockApp(GuestbookMixin):
            mentions_dir = Path("/tmp")

            @property
            def _app(self):
                return MagicMock()

        app = MockApp()

        # Should match articles
        self.assertTrue(app._is_article_url("https://example.com/article/test"))
        self.assertTrue(app._is_article_url("https://example.com/article/nested/post"))

        # Should not match non-articles
        self.assertFalse(app._is_article_url("https://example.com"))
        self.assertFalse(app._is_article_url("https://example.com/tags/python"))
        self.assertFalse(app._is_article_url(""))


class GuestbookRouteTest(unittest.TestCase):
    """Test the /guestbook route."""

    def setUp(self):
        from madblog.config import config

        self.config = config
        self._orig_enable_guestbook = config.enable_guestbook
        self._orig_enable_webmentions = config.enable_webmentions
        self._orig_enable_activitypub = config.enable_activitypub
        self._orig_content_dir = config.content_dir
        self._orig_link = config.link

        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)
        mentions_dir = root / "mentions"
        mentions_dir.mkdir(parents=True, exist_ok=True)

        (markdown_dir / "test-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Test Post)",
                    "[//]: # (published: 2026-01-01)",
                    "",
                    "# Test Post",
                    "",
                    "Hello world.",
                ]
            )
        )

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_guestbook = True
        config.enable_webmentions = True
        config.enable_activitypub = False

    def tearDown(self):
        self.config.enable_guestbook = self._orig_enable_guestbook
        self.config.enable_webmentions = self._orig_enable_webmentions
        self.config.enable_activitypub = self._orig_enable_activitypub
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link

    def test_guestbook_route_returns_200(self):
        from madblog.app import app

        client = app.test_client()
        resp = client.get("/guestbook")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Guestbook", resp.data)

    def test_guestbook_route_disabled(self):
        from madblog.config import config
        from madblog.app import app

        config.enable_guestbook = False
        client = app.test_client()
        resp = client.get("/guestbook")
        self.assertEqual(resp.status_code, 404)

    def test_guestbook_shows_empty_message(self):
        from madblog.app import app

        client = app.test_client()
        resp = client.get("/guestbook")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No messages yet", resp.data)


class GuestbookNavLinkTest(unittest.TestCase):
    """Test that the guestbook link appears in navigation."""

    def setUp(self):
        from madblog.config import config

        self.config = config
        self._orig_enable_guestbook = config.enable_guestbook
        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_header = config.header

        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)
        mentions_dir = root / "mentions"
        mentions_dir.mkdir(parents=True, exist_ok=True)

        (markdown_dir / "test-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Test Post)",
                    "[//]: # (published: 2026-01-01)",
                    "",
                    "# Test Post",
                    "",
                    "Hello world.",
                ]
            )
        )

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_guestbook = True
        config.header = True

    def tearDown(self):
        self.config.enable_guestbook = self._orig_enable_guestbook
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link
        self.config.header = self._orig_header

    def test_guestbook_link_in_nav(self):
        from madblog.app import app

        client = app.test_client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/guestbook", resp.data)
        self.assertIn(b"Guestbook", resp.data)

    def test_guestbook_link_hidden_when_disabled(self):
        from madblog.config import config
        from madblog.app import app

        config.enable_guestbook = False
        client = app.test_client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'href="/guestbook"', resp.data)


if __name__ == "__main__":
    unittest.main()
