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

    def test_is_article_thread_url(self):
        from madblog.guestbook._mixin import GuestbookMixin

        class MockApp(GuestbookMixin):
            mentions_dir = Path("/tmp")

            @property
            def _app(self):
                return MagicMock()

        app = MockApp()

        # Should match articles
        self.assertTrue(app._is_article_thread_url("https://example.com/article/test"))

        # Should match author reply URLs
        self.assertTrue(
            app._is_article_thread_url("https://example.com/reply/my-post/reply-1")
        )

        # Should not match non-article/non-reply URLs
        self.assertFalse(app._is_article_thread_url("https://example.com"))
        self.assertFalse(app._is_article_thread_url("https://example.com/tags/python"))
        self.assertFalse(
            app._is_article_thread_url("https://remote.social/users/alice/statuses/123")
        )
        self.assertFalse(app._is_article_thread_url(""))


class GuestbookAPInteractionsTest(unittest.TestCase):
    """Test that get_guestbook_ap_interactions filters interaction types correctly."""

    def setUp(self):
        from madblog.config import config

        self.config = config
        self._orig_link = config.link
        self._orig_activitypub_link = config.activitypub_link
        self._orig_blocked = config.blocked_actors
        self._orig_allowed = config.allowed_actors
        config.link = "https://example.com"
        config.activitypub_link = None
        config.blocked_actors = []
        config.allowed_actors = []

    def tearDown(self):
        self.config.link = self._orig_link
        self.config.activitypub_link = self._orig_activitypub_link
        self.config.blocked_actors = self._orig_blocked
        self.config.allowed_actors = self._orig_allowed

    def _make_mixin(self, interactions, mentioning_interactions=None):
        from madblog.guestbook._mixin import GuestbookMixin

        storage = MagicMock()
        storage.get_interactions.return_value = interactions
        storage.get_interactions_mentioning.return_value = mentioning_interactions or []
        storage.get_interaction_by_object_id.return_value = None

        handler = MagicMock()
        handler.actor_id = "https://example.com/ap/actor"
        handler.storage = storage

        class MockApp(GuestbookMixin):
            mentions_dir = Path("/tmp")
            activitypub_handler = handler

            @property
            def _app(self):
                return MagicMock()

        return MockApp()

    def _make_interaction(self, interaction_type, target_resource, object_id):
        return MagicMock(
            interaction_type=MagicMock(value=interaction_type),
            target_resource=target_resource,
            source_actor_id="https://remote.social/users/alice",
            activity_id=f"https://remote.social/activity/{object_id}",
            object_id=f"https://remote.social/objects/{object_id}",
            published=None,
            created_at=None,
        )

    def test_mention_included(self):
        mention = self._make_interaction("mention", "https://example.com/ap/actor", "1")
        app = self._make_mixin([mention])
        result = app.get_guestbook_ap_interactions()
        self.assertEqual(len(result), 1)

    def test_reply_to_guestbook_entry_included(self):
        """Replies to guestbook entries (non-article targets) should appear."""
        reply = self._make_interaction(
            "reply", "https://remote.social/users/alice/statuses/123", "2"
        )
        app = self._make_mixin([], mentioning_interactions=[reply])
        result = app.get_guestbook_ap_interactions()
        self.assertEqual(len(result), 1)

    def test_reply_to_article_excluded(self):
        """Replies to articles should NOT appear in the guestbook."""
        reply = self._make_interaction(
            "reply", "https://example.com/article/my-post", "3"
        )
        app = self._make_mixin([], mentioning_interactions=[reply])
        result = app.get_guestbook_ap_interactions()
        self.assertEqual(len(result), 0)

    def test_reply_to_author_reply_excluded(self):
        """Replies to author reply URLs should NOT appear in the guestbook."""
        reply = self._make_interaction(
            "reply", "https://example.com/reply/my-post/reply-1", "r1"
        )
        app = self._make_mixin([], mentioning_interactions=[reply])
        result = app.get_guestbook_ap_interactions()
        self.assertEqual(len(result), 0)

    def test_reply_to_fediverse_reply_in_article_thread_excluded(self):
        """Replies to fediverse replies that are part of an article thread
        should NOT appear in the guestbook."""
        # The parent interaction targets an author reply URL
        parent_interaction = MagicMock(
            target_resource="https://example.com/reply/my-post/reply-1",
            object_id="https://remote.social/users/alice/statuses/100",
        )

        # The child reply targets the parent's Mastodon URL
        child_reply = self._make_interaction(
            "reply", "https://remote.social/users/alice/statuses/100", "child1"
        )

        # Set up storage to return the parent when looking up by object_id
        from madblog.guestbook._mixin import GuestbookMixin

        storage = MagicMock()
        storage.get_interactions.return_value = []
        storage.get_interactions_mentioning.return_value = [child_reply]
        storage.get_interaction_by_object_id.return_value = parent_interaction

        handler = MagicMock()
        handler.actor_id = "https://example.com/ap/actor"
        handler.storage = storage

        class MockApp(GuestbookMixin):
            mentions_dir = Path("/tmp")
            activitypub_handler = handler

            @property
            def _app(self):
                return MagicMock()

        app = MockApp()
        result = app.get_guestbook_ap_interactions()
        self.assertEqual(len(result), 0)

    def test_like_excluded(self):
        like = self._make_interaction("like", "https://example.com/ap/actor", "4")
        app = self._make_mixin([like])
        result = app.get_guestbook_ap_interactions()
        self.assertEqual(len(result), 0)

    def test_boost_excluded(self):
        boost = self._make_interaction("boost", "https://example.com/ap/actor", "5")
        app = self._make_mixin([boost])
        result = app.get_guestbook_ap_interactions()
        self.assertEqual(len(result), 0)


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
