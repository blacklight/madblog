"""
Tests for the ActivityPub integration in Madblog.
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _join_ap_publish_threads(timeout: float = 1) -> None:
    """Wait for any background ``ap-publish-*`` threads to finish."""
    for t in threading.enumerate():
        if t.name.startswith("ap-publish-") and t.is_alive():
            t.join(timeout=timeout)


def skip_if_no_pubby(test_func):
    """Decorator to skip tests if pubby is not available."""

    def wrapper(self, *args, **kwargs):
        try:
            import pubby
        except ImportError:
            self.skipTest("pubby is not installed")
        return test_func(self, *args, **kwargs)

    return wrapper


class ActivityPubConfigTest(unittest.TestCase):
    """Test that AP config options are parsed correctly."""

    def test_defaults(self):
        from madblog.config import Config

        cfg = Config()
        self.assertFalse(cfg.enable_activitypub)
        self.assertEqual(cfg.activitypub_username, "blog")
        self.assertIsNone(cfg.activitypub_name)
        self.assertIsNone(cfg.activitypub_private_key_path)
        self.assertFalse(cfg.activitypub_manually_approves_followers)
        self.assertFalse(cfg.activitypub_description_only)

    def test_actor_url_single_domain(self):
        from madblog.config import Config

        cfg = Config(
            enable_activitypub=True,
            link="https://example.com",
            activitypub_username="blog",
        )
        self.assertEqual(cfg.activitypub_actor_url, "https://example.com/ap/actor")

    def test_actor_url_split_domain(self):
        from madblog.config import Config

        cfg = Config(
            enable_activitypub=True,
            link="https://blog.example.com",
            activitypub_link="https://ap.example.org",
            activitypub_username="blog",
        )
        self.assertEqual(cfg.activitypub_actor_url, "https://ap.example.org/ap/actor")

    def test_actor_url_none_when_disabled(self):
        from madblog.config import Config

        cfg = Config(enable_activitypub=False)
        self.assertIsNone(cfg.activitypub_actor_url)

    def test_env_vars(self):
        from madblog.config import config, _init_config_from_env

        env = {
            "MADBLOG_ENABLE_ACTIVITYPUB": "1",
            "MADBLOG_ACTIVITYPUB_LINK": "https://ap.example.org",
            "MADBLOG_ACTIVITYPUB_USERNAME": "testuser",
            "MADBLOG_ACTIVITYPUB_DOMAIN": "example.org",
            "MADBLOG_ACTIVITYPUB_NAME": "Test Blog",
            "MADBLOG_ACTIVITYPUB_SUMMARY": "A test blog",
            "MADBLOG_ACTIVITYPUB_ICON_URL": "https://example.com/icon.png",
            "MADBLOG_ACTIVITYPUB_PRIVATE_KEY_PATH": "/tmp/key.pem",
            "MADBLOG_ACTIVITYPUB_MANUALLY_APPROVES_FOLLOWERS": "1",
            "MADBLOG_ACTIVITYPUB_DESCRIPTION_ONLY": "1",
        }

        with patch.dict(os.environ, env, clear=False):
            _init_config_from_env()

        self.assertTrue(config.enable_activitypub)
        self.assertEqual(config.activitypub_link, "https://ap.example.org")
        self.assertEqual(config.activitypub_username, "testuser")
        self.assertEqual(config.activitypub_domain, "example.org")
        self.assertEqual(config.activitypub_name, "Test Blog")
        self.assertEqual(config.activitypub_summary, "A test blog")
        self.assertEqual(config.activitypub_icon_url, "https://example.com/icon.png")
        self.assertEqual(config.activitypub_private_key_path, "/tmp/key.pem")
        self.assertTrue(config.activitypub_manually_approves_followers)
        self.assertTrue(config.activitypub_description_only)

        # Reset
        config.enable_activitypub = False
        config.activitypub_link = None
        config.activitypub_username = "blog"
        config.activitypub_domain = None
        config.activitypub_name = None
        config.activitypub_summary = None
        config.activitypub_icon_url = None
        config.activitypub_private_key_path = None
        config.activitypub_manually_approves_followers = False
        config.activitypub_description_only = False


class ActivityPubDisabledTest(unittest.TestCase):
    """When AP is disabled (default), no AP endpoints should be registered."""

    def setUp(self):
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config
        self._orig = config.enable_activitypub
        config.enable_activitypub = False

    def tearDown(self):
        self.config.enable_activitypub = self._orig

    def test_no_ap_endpoints_by_default(self):
        """AP endpoints should not exist when disabled."""
        client = self.app.test_client()
        resp = client.get("/.well-known/webfinger?resource=acct:blog@example.com")
        # Should be 404 since AP is not enabled
        # (webfinger is only registered by pubby)
        self.assertIn(resp.status_code, (404, 405))


class ActivityPubEnabledTest(unittest.TestCase):
    """When AP is enabled, endpoints should work."""

    @skip_if_no_pubby
    def setUp(self):
        from madblog.config import config

        self.config = config
        self._orig_activitypub_domain = config.activitypub_domain
        self._orig_activitypub_link = config.activitypub_link
        self._orig_activitypub_profile_field_name = getattr(
            config, "activitypub_profile_field_name", "Blog"
        )
        self._orig_activitypub_profile_fields = getattr(
            config, "activitypub_profile_fields", {}
        )
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)

        # Write a test post
        (markdown_dir / "test-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Test Post)",
                    "[//]: # (description: A test post)",
                    "[//]: # (published: 2026-01-01T00:00:00+00:00)",
                    "",
                    "# Test Post",
                    "",
                    "Hello world.",
                ]
            )
        )

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_activitypub = True
        config.activitypub_link = None
        config.activitypub_domain = None
        config.activitypub_private_key_path = None
        config.author = "Test Author"

        # Create a fresh Flask app to avoid "setup already finished" errors
        from madblog.app import BlogApp

        self.app = BlogApp(__name__)

    def tearDown(self):
        # Wait for the background startup thread to finish before cleaning up
        # the temp directory, otherwise it may try to write to a deleted path.
        if hasattr(self, "app") and hasattr(self.app, "_ap_startup_thread"):
            self.app._ap_startup_thread.join(timeout=5)

        if hasattr(self, "config"):
            self.config.enable_activitypub = False
            self.config.activitypub_link = self._orig_activitypub_link
            self.config.activitypub_domain = self._orig_activitypub_domain
            self.config.activitypub_profile_field_name = (
                self._orig_activitypub_profile_field_name
            )
            self.config.activitypub_profile_fields = (
                self._orig_activitypub_profile_fields
            )

    @skip_if_no_pubby
    def test_webfinger(self):
        client = self.app.test_client()
        resp = client.get("/.well-known/webfinger" "?resource=acct:blog@example.com")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["subject"], "acct:blog@example.com")

    @skip_if_no_pubby
    def test_webfinger_domain_override(self):
        from madblog.config import config
        from madblog.app import BlogApp

        config.activitypub_domain = "example.org"
        # Create a new app after setting the domain override
        app = BlogApp(__name__)
        self.addCleanup(lambda: app._ap_startup_thread.join(timeout=5))
        client = app.test_client()

        resp = client.get("/.well-known/webfinger" "?resource=acct:blog@example.org")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["subject"], "acct:blog@example.org")

        # Actor IDs are still based on config.link
        self.assertTrue(data["aliases"])
        self.assertEqual(data["aliases"][0], "https://example.com/ap/actor")

    @skip_if_no_pubby
    def test_actor(self):
        client = self.app.test_client()
        resp = client.get("/ap/actor", headers={"Accept": "application/activity+json"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["type"], "Person")
        self.assertEqual(data["preferredUsername"], "blog")

    @skip_if_no_pubby
    def test_actor_redirects_to_profile_for_html_clients(self):
        """When a browser requests /ap/actor, redirect to the profile page."""
        client = self.app.test_client()
        # No Accept header or HTML Accept header should redirect
        resp = client.get("/ap/actor")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "https://example.com/@blog")

        # Explicitly requesting HTML should also redirect
        resp = client.get("/ap/actor", headers={"Accept": "text/html"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "https://example.com/@blog")

    @skip_if_no_pubby
    def test_actor_profile_fields_are_configurable(self):
        from madblog.config import config
        from madblog.app import BlogApp

        config.activitypub_profile_field_name = "Website"
        config.activitypub_profile_fields = {
            "Git repository": "https://git.example.com/myblog",
            "About": "A personal blog",
        }

        app = BlogApp(__name__)
        self.addCleanup(lambda: app._ap_startup_thread.join(timeout=5))
        client = app.test_client()

        resp = client.get("/ap/actor", headers={"Accept": "application/activity+json"})
        self.assertEqual(resp.status_code, 200)
        actor = resp.get_json()

        self.assertIn("attachment", actor)
        attachments = actor.get("attachment") or []
        self.assertTrue(attachments)

        # Primary blog link field
        primary = next((a for a in attachments if a.get("name") == "Website"), None)
        self.assertIsNotNone(primary, attachments)
        assert primary  # For mypy
        self.assertEqual(primary.get("type"), "PropertyValue")
        self.assertIn('href="https://example.com"', primary.get("value", ""))
        self.assertIn('rel="me"', primary.get("value", ""))

        # Additional URL field rendered as rel="me" anchor
        repo = next(
            (a for a in attachments if a.get("name") == "Git repository"),
            None,
        )
        self.assertIsNotNone(repo, attachments)
        assert repo  # For mypy
        self.assertIn('href="https://git.example.com/myblog"', repo.get("value", ""))
        self.assertIn('rel="me"', repo.get("value", ""))

        # Additional non-URL field rendered as string
        about = next((a for a in attachments if a.get("name") == "About"), None)
        self.assertIsNotNone(about, attachments)
        assert about  # For mypy
        self.assertEqual(about.get("value"), "A personal blog")

    @skip_if_no_pubby
    def test_activitypub_link_override_changes_actor_id(self):
        from madblog.config import config
        from madblog.app import BlogApp

        config.link = "https://example.com"
        config.activitypub_link = "https://ap.example.org"
        config.activitypub_domain = "example.org"

        app = BlogApp(__name__)
        self.addCleanup(lambda: app._ap_startup_thread.join(timeout=5))
        client = app.test_client()

        resp = client.get("/.well-known/webfinger" "?resource=acct:blog@example.org")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["subject"], "acct:blog@example.org")
        self.assertEqual(data["aliases"][0], "https://ap.example.org/ap/actor")

        resp = client.get("/ap/actor", headers={"Accept": "application/activity+json"})
        self.assertEqual(resp.status_code, 200)
        actor = resp.get_json()
        self.assertEqual(actor["id"], "https://ap.example.org/ap/actor")

        # Website/profile URL remains based on config.link
        self.assertEqual(actor["url"], "https://example.com/@blog")

    @skip_if_no_pubby
    def test_outbox(self):
        client = self.app.test_client()
        resp = client.get("/ap/outbox")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["type"], "OrderedCollection")

    @skip_if_no_pubby
    def test_followers(self):
        client = self.app.test_client()
        resp = client.get("/ap/followers")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["type"], "OrderedCollection")

    @skip_if_no_pubby
    def test_nodeinfo(self):
        client = self.app.test_client()
        resp = client.get("/.well-known/nodeinfo")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("links", data)

    @skip_if_no_pubby
    def test_article_advertises_ap_alternate_link(self):
        with self.app.test_request_context("/article/test-post"):
            resp = self.app.get_page("test-post")

        self.assertEqual(resp.status_code, 200)
        links = resp.headers.getlist("Link")
        self.assertTrue(
            any(
                'rel="alternate"' in link
                and 'type="application/activity+json"' in link
                and "https://example.com/article/test-post" in link
                for link in links
            ),
            links,
        )

    @skip_if_no_pubby
    def test_article_can_be_fetched_as_activitypub_json(self):
        with self.app.test_request_context(
            "/article/test-post",
            headers={"Accept": "application/activity+json"},
        ):
            resp = self.app.get_page("test-post")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/activity+json")
        data = resp.get_json()
        self.assertEqual(data["id"], "https://example.com/article/test-post")
        self.assertEqual(data.get("url"), "https://example.com/article/test-post")

    @skip_if_no_pubby
    def test_article_fetched_with_ld_json_accept_returns_ap(self):
        """Accept: application/ld+json should also return AP JSON, not HTML."""
        with self.app.test_request_context(
            "/article/test-post",
            headers={"Accept": "application/ld+json"},
        ):
            resp = self.app.get_page("test-post")

        assert resp  # For mypy
        self.assertEqual(resp.status_code, 200)
        self.assertIn("json", resp.mimetype or "")
        data = resp.get_json()
        self.assertEqual(data["id"], "https://example.com/article/test-post")

    @skip_if_no_pubby
    def test_article_fetched_with_parameterised_ld_json_accept_returns_ap(self):
        """Accept with mimetype parameters (e.g. profile=) must still return AP JSON."""
        with self.app.test_request_context(
            "/article/test-post",
            headers={
                "Accept": 'application/ld+json; profile="https://www.w3.org/ns/activitystreams"',
            },
        ):
            resp = self.app.get_page("test-post")

        assert resp  # For mypy
        self.assertEqual(resp.status_code, 200)
        self.assertIn("json", resp.mimetype or "")
        data = resp.get_json()
        self.assertEqual(data["id"], "https://example.com/article/test-post")

    def _make_cross_domain_app(self):
        """Create a BlogApp with split AP / blog domains and a test post."""
        from madblog.config import config
        from madblog.app import BlogApp

        tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)

        (markdown_dir / "test-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Test Post)",
                    "[//]: # (description: A test post)",
                    "[//]: # (published: 2026-01-01T00:00:00+00:00)",
                    "",
                    "# Test Post",
                    "",
                    "Hello world.",
                ]
            )
        )

        config.content_dir = str(root)
        config.link = "https://blog.example.com"
        config.activitypub_link = "https://ap.example.org"
        config.activitypub_domain = "example.org"

        app = BlogApp(__name__)
        self.addCleanup(lambda: app._ap_startup_thread.join(timeout=5))
        return app

    @skip_if_no_pubby
    def test_article_ap_json_via_ap_domain_proxy(self):
        """When the request arrives via the AP domain proxy, serve AP JSON."""
        app = self._make_cross_domain_app()

        # Simulate a proxied request with Host: ap.example.org
        with app.test_request_context(
            "/article/test-post",
            headers={
                "Accept": "application/activity+json",
                "Host": "ap.example.org",
            },
        ):
            resp = app.get_page("test-post")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/activity+json")
        data = resp.get_json()
        # Object id must be on the AP domain (same origin as actor,
        # required by Mastodon's origin check during inbox delivery).
        self.assertEqual(data["id"], "https://ap.example.org/article/test-post")
        # The human-facing url points to the blog domain.
        self.assertEqual(data.get("url"), "https://blog.example.com/article/test-post")
        # The actor (attributedTo) remains on the AP domain
        self.assertEqual(data.get("attributedTo"), "https://ap.example.org/ap/actor")

    @skip_if_no_pubby
    def test_article_ap_request_at_blog_domain_redirects_to_ap_domain(self):
        """When an AP client hits the blog domain, redirect to the AP domain."""
        app = self._make_cross_domain_app()

        # Request arrives at the blog domain (no proxy)
        with app.test_request_context(
            "/article/test-post",
            headers={
                "Accept": "application/activity+json",
                "Host": "blog.example.com",
            },
        ):
            resp = app.get_page("test-post")

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.headers["Location"],
            "https://ap.example.org/article/test-post",
        )

    @skip_if_no_pubby
    def test_rel_me_links_include_ap_domain_when_split(self):
        """When activitypub_link != link, rel='me' links for both domains."""
        from flask import render_template
        from madblog.config import config

        app = self._make_cross_domain_app()

        with app.test_request_context("/"):
            html = render_template(
                "common-head.html",
                config=config,
                title="Test",
                description="",
                image="",
                url=config.link,
                type="website",
                tags=[],
                styles=[],
                view_mode="cards",
            )

        # AP actor URL (the URL Mastodon caches and checks for verification)
        self.assertIn(
            '<link rel="me" href="https://ap.example.org/ap/actor">',
            html,
        )
        # Blog-domain links (always present)
        self.assertIn(
            '<link rel="me" href="https://blog.example.com/@blog">',
            html,
        )
        self.assertIn(
            '<link rel="me" href="https://blog.example.com">',
            html,
        )
        # AP-domain links (only when domains differ)
        self.assertIn(
            '<link rel="me" href="https://ap.example.org/@blog">',
            html,
        )
        self.assertIn(
            '<link rel="me" href="https://ap.example.org">',
            html,
        )


class ActivityPubKeyPermissionsTest(unittest.TestCase):
    """Test that Madblog refuses to start if the key file is world-readable."""

    @skip_if_no_pubby
    def test_world_readable_key_fails(self):
        from madblog.app import app
        from madblog.config import config

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        key_file = root / "bad_key.pem"

        # Write a dummy key
        from pubby.crypto import generate_rsa_keypair, export_private_key_pem

        priv, _ = generate_rsa_keypair()
        key_file.write_text(export_private_key_pem(priv))
        os.chmod(key_file, 0o644)  # world-readable

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_activitypub = True
        config.activitypub_private_key_path = str(key_file)

        with self.assertRaises(RuntimeError) as ctx:
            app._init_activitypub()

        self.assertIn("readable", str(ctx.exception))

        # Reset
        config.enable_activitypub = False
        config.activitypub_private_key_path = None
        for attr in (
            "activitypub_handler",
            "activitypub_storage",
            "_ap_integration",
        ):
            if hasattr(app, attr):
                delattr(app, attr)


class ActivityPubContentChangeTest(unittest.TestCase):
    """Test the on_content_change callback."""

    def setUp(self):
        from madblog.monitor import ChangeType

        self.ChangeType = ChangeType

    @skip_if_no_pubby
    def test_on_content_change_create(self):
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://example.com",
                "username": "blog",
            },
            private_key=priv,
        )

        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://example.com",
        )

        # Write a test file
        test_file = pages_dir / "hello.md"
        test_file.write_text("[//]: # (title: Hello)\n\n# Hello\n\nWorld.\n")

        # Mock publish_object to capture the call
        handler.publish_object = MagicMock()
        integration.on_content_change(self.ChangeType.ADDED, str(test_file))
        _join_ap_publish_threads()

        handler.publish_object.assert_called_once()
        obj = handler.publish_object.call_args[0][0]
        self.assertEqual(obj.type, "Note")
        self.assertIn("Hello", obj.content)  # Title rendered as linked heading
        self.assertIn("https://example.com/article/hello", obj.id)

    @skip_if_no_pubby
    def test_on_content_change_delete(self):
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://example.com",
                "username": "blog",
            },
            private_key=priv,
        )

        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://example.com",
        )

        handler.publish_object = MagicMock()
        integration.on_content_change(
            self.ChangeType.DELETED,
            str(pages_dir / "gone.md"),
        )

        handler.publish_object.assert_called_once()
        kwargs = handler.publish_object.call_args
        self.assertEqual(kwargs[1]["activity_type"], "Delete")

    @skip_if_no_pubby
    def test_delete_then_recreate_uses_collision_avoiding_url(self):
        """
        When an article is deleted and then re-created with the same slug,
        the AP object ID should get a version suffix to avoid Mastodon
        ignoring the Create (since Mastodon tombstones deleted object IDs).
        """
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://ap.example.com",
                "username": "blog",
            },
            private_key=priv,
        )

        # Split-domain setup: AP on ap.example.com, blog on blog.example.com
        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://ap.example.com",
            content_base_url="https://blog.example.com",
        )

        handler.publish_object = MagicMock()

        # Step 1: Create the article
        test_file = pages_dir / "test.md"
        test_file.write_text("# Test Article\n\nContent here.")
        integration.on_content_change(self.ChangeType.ADDED, str(test_file))
        _join_ap_publish_threads()

        # Verify Create was sent with base URL
        self.assertEqual(handler.publish_object.call_count, 1)
        first_obj = handler.publish_object.call_args[0][0]
        self.assertEqual(first_obj.id, "https://ap.example.com/article/test")

        handler.publish_object.reset_mock()

        # Step 2: Delete the article
        integration.on_content_change(self.ChangeType.DELETED, str(test_file))

        # Verify Delete was sent
        self.assertEqual(handler.publish_object.call_count, 1)
        self.assertEqual(handler.publish_object.call_args[1]["activity_type"], "Delete")

        handler.publish_object.reset_mock()

        # Step 3: Re-create the article with the same slug
        test_file.write_text("# Test Article\n\nNew content.")
        integration.on_content_change(self.ChangeType.ADDED, str(test_file))
        _join_ap_publish_threads()

        # Verify Create was sent with collision-avoiding URL (has ?v= suffix)
        self.assertEqual(handler.publish_object.call_count, 1)
        recreated_obj = handler.publish_object.call_args[0][0]
        self.assertIn("?v=", recreated_obj.id)
        self.assertTrue(
            recreated_obj.id.startswith("https://ap.example.com/article/test?v=")
        )

    @skip_if_no_pubby
    def test_inline_markdown_images_become_attachments(self):
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration
        from madblog.config import config

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        # Ensure generated attachments are written into this temp content dir
        config.content_dir = str(root)

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://example.com",
                "username": "blog",
            },
            private_key=priv,
        )

        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://example.com",
        )

        # Inline image: should be added as an attachment for Mastodon
        img_url = "https://s3.example.com/img/stock.jpg"
        test_file = pages_dir / "with-image.md"
        test_file.write_text(
            "\n".join(
                [
                    "[//]: # (title: With Image)",
                    "",
                    "# With Image",
                    "",
                    f"![Stock image]({img_url})",
                    "",
                    "Text after.",
                ]
            )
        )

        handler.publish_object = MagicMock()
        integration.on_content_change(self.ChangeType.ADDED, str(test_file))
        _join_ap_publish_threads()

        handler.publish_object.assert_called_once()
        obj = handler.publish_object.call_args[0][0]
        self.assertTrue(obj.attachment)
        self.assertTrue(any(a.get("url") == img_url for a in obj.attachment))

    @skip_if_no_pubby
    def test_generated_image_attachments_use_content_base_url(self):
        """LaTeX/Mermaid PNGs use content_base_url, not base_url (AP identity)."""
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration
        from madblog.config import config

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        config.content_dir = str(root)

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://ap.example.org",  # AP identity URL
                "username": "blog",
            },
            private_key=priv,
        )

        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://ap.example.org",  # AP identity
            content_base_url="https://blog.example.com",  # Where images served
        )

        # Post with inline LaTeX (base64 image that gets extracted)
        test_file = pages_dir / "latex-post.md"
        test_file.write_text(
            "\n".join(
                [
                    "[//]: # (title: LaTeX Post)",
                    "",
                    "# LaTeX Post",
                    "",
                    "Some math: $E=mc^2$",
                ]
            )
        )

        handler.publish_object = MagicMock()
        integration.on_content_change(self.ChangeType.ADDED, str(test_file))
        _join_ap_publish_threads()

        handler.publish_object.assert_called_once()
        obj = handler.publish_object.call_args[0][0]

        # Article ID should use AP base_url (same origin as actor,
        # required by Mastodon's origin check during inbox delivery).
        self.assertTrue(obj.id.startswith("https://ap.example.org/"))

        # If there are generated image attachments, they should use content_base_url
        for att in obj.attachment or []:
            if att.get("url", "").startswith("https://"):
                # Generated PNGs should point to content_base_url, not AP base_url
                self.assertFalse(
                    att["url"].startswith("https://ap.example.org/"),
                    f"Attachment URL should use content_base_url: {att['url']}",
                )


class ActivityPubTocStrippingTest(unittest.TestCase):
    """TOC markers must be stripped from federated posts."""

    @skip_if_no_pubby
    def test_toc_markers_stripped_from_ap_content(self):
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration
        from madblog.config import config

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        config.content_dir = str(root)

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://example.com",
                "username": "blog",
            },
            private_key=priv,
        )

        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://example.com",
        )

        for marker in ("[[TOC]]", "[TOC]", "{{ TOC }}", "<!-- TOC -->"):
            test_file = pages_dir / "toc-post.md"
            test_file.write_text(
                "\n".join(
                    [
                        "[//]: # (title: TOC Post)",
                        "[//]: # (published: 2025-02-13)",
                        "",
                        "# TOC Post",
                        "",
                        marker,
                        "",
                        "## Section 1",
                        "Text",
                        "",
                        "## Section 2",
                        "More text",
                    ]
                ),
                encoding="utf-8",
            )

            handler.publish_object = MagicMock()
            integration.on_content_change(
                __import__("madblog.monitor", fromlist=["ChangeType"]).ChangeType.ADDED,
                str(test_file),
            )
            _join_ap_publish_threads()

            handler.publish_object.assert_called_once()
            obj = handler.publish_object.call_args[0][0]

            self.assertNotIn(
                'class="toc"',
                obj.content,
                f"Generated TOC HTML found in AP content for marker {marker!r}",
            )
            self.assertNotIn(
                marker,
                obj.content,
                f"Raw TOC marker {marker!r} found in AP content",
            )

            # Reset published state so the next iteration can re-publish
            integration._sync_reset()


class ActivityPubPublishSplitDomainTest(unittest.TestCase):
    """Published objects use AP domain for id and blog domain for url."""

    def setUp(self):
        from madblog.monitor import ChangeType

        self.ChangeType = ChangeType

    @skip_if_no_pubby
    def test_published_object_id_on_ap_domain_url_on_blog_domain(self):
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration
        from madblog.config import config

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        config.content_dir = str(root)

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://ap.example.org",
                "username": "blog",
            },
            private_key=priv,
        )

        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://ap.example.org",
            content_base_url="https://blog.example.com",
        )

        test_file = pages_dir / "hello.md"
        test_file.write_text("[//]: # (title: Hello)\n\n# Hello\n\nWorld.\n")

        handler.publish_object = MagicMock()
        integration.on_content_change(self.ChangeType.ADDED, str(test_file))
        _join_ap_publish_threads()

        handler.publish_object.assert_called_once()
        obj = handler.publish_object.call_args[0][0]

        # id must be on the AP domain (same origin as actor) for delivery
        self.assertEqual(obj.id, "https://ap.example.org/article/hello")
        # url must be on the blog domain (human-facing, StatusFinder lookup)
        self.assertEqual(obj.url, "https://blog.example.com/article/hello")


class ActivityPubNotificationsTest(unittest.TestCase):
    """Test the AP email notifier."""

    @skip_if_no_pubby
    def test_email_sent_on_interaction(self):
        from madblog.activitypub import build_activitypub_email_notifier
        from madblog.notifications import SmtpConfig
        from pubby import Interaction, InteractionType

        send_email = MagicMock()
        notifier = build_activitypub_email_notifier(
            recipient="test@example.com",
            blog_base_url="https://example.com",
            smtp=SmtpConfig(server="smtp.example.com"),
            send_email=send_email,
        )

        interaction = Interaction(
            source_actor_id="https://remote.example/user/alice",
            target_resource="https://example.com/article/test",
            interaction_type=InteractionType.LIKE,
            author_name="Alice",
        )

        notifier(interaction)
        send_email.assert_called_once()
        call_kwargs = send_email.call_args[1]
        self.assertIn("Like", call_kwargs["subject"])
        self.assertIn("Alice", call_kwargs["body"])

    @skip_if_no_pubby
    def test_no_email_for_non_local_target(self):
        from madblog.activitypub import build_activitypub_email_notifier
        from madblog.notifications import SmtpConfig
        from pubby import Interaction, InteractionType

        send_email = MagicMock()
        notifier = build_activitypub_email_notifier(
            recipient="test@example.com",
            blog_base_url="https://example.com",
            smtp=SmtpConfig(server="smtp.example.com"),
            send_email=send_email,
        )

        interaction = Interaction(
            source_actor_id="https://someone.social/user1",
            target_resource="https://someone.else.social/users/user2/statuses/12345",
            interaction_type=InteractionType.REPLY,
            author_name="Joe",
        )

        notifier(interaction)
        send_email.assert_not_called()

    @skip_if_no_pubby
    def test_email_sent_for_ap_base_url_target(self):
        from madblog.activitypub import build_activitypub_email_notifier
        from madblog.notifications import SmtpConfig
        from pubby import Interaction, InteractionType

        send_email = MagicMock()
        notifier = build_activitypub_email_notifier(
            recipient="test@example.com",
            blog_base_url="https://example.com",
            ap_base_url="https://ap.example.com",
            smtp=SmtpConfig(server="smtp.example.com"),
            send_email=send_email,
        )

        interaction = Interaction(
            source_actor_id="https://remote.example/user/bob",
            target_resource="https://ap.example.com/article/test",
            interaction_type=InteractionType.REPLY,
            author_name="Bob",
        )

        notifier(interaction)
        send_email.assert_called_once()

    @skip_if_no_pubby
    def test_email_sent_when_mentioned_actors_includes_actor(self):
        from madblog.activitypub import build_activitypub_email_notifier
        from madblog.notifications import SmtpConfig
        from pubby import Interaction, InteractionType

        send_email = MagicMock()
        notifier = build_activitypub_email_notifier(
            recipient="test@example.com",
            blog_base_url="https://blog.example.com",
            ap_base_url="https://example.com",
            actor_url="https://example.com/ap/actor",
            smtp=SmtpConfig(server="smtp.example.com"),
            send_email=send_email,
        )

        interaction = Interaction(
            source_actor_id="https://remote.social/users/alice",
            target_resource="https://other.instance/objects/some-uuid",
            interaction_type=InteractionType.REPLY,
            author_name="Alice",
            content=(
                '<p><span class="h-card">'
                '<a href="https://example.com/ap/actor" class="u-url mention">'
                "@<span>blog</span></a></span> great post!</p>"
            ),
            mentioned_actors=["https://example.com/ap/actor"],
        )

        notifier(interaction)
        send_email.assert_called_once()

    @skip_if_no_pubby
    def test_no_email_for_non_local_target_without_mention(self):
        from madblog.activitypub import build_activitypub_email_notifier
        from madblog.notifications import SmtpConfig
        from pubby import Interaction, InteractionType

        send_email = MagicMock()
        notifier = build_activitypub_email_notifier(
            recipient="test@example.com",
            blog_base_url="https://blog.example.com",
            ap_base_url="https://example.com",
            actor_url="https://example.com/ap/actor",
            smtp=SmtpConfig(server="smtp.example.com"),
            send_email=send_email,
        )

        interaction = Interaction(
            source_actor_id="https://remote.social/users/alice",
            target_resource="https://other.instance/users/bob/statuses/999",
            interaction_type=InteractionType.REPLY,
            author_name="Alice",
            content="<p>@bob just a random reply in a thread</p>",
        )

        notifier(interaction)
        send_email.assert_not_called()


class FollowersRouteTest(unittest.TestCase):
    """Test /followers HTML route and followers bar on home page."""

    @skip_if_no_pubby
    def setUp(self):
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config
        self._orig_enable_ap = config.enable_activitypub

        self._tmpdir = tempfile.TemporaryDirectory()
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

        self.config.content_dir = str(root)
        self.config.link = "https://example.com"
        self.config.title = "Example"
        self.config.description = "Example blog"
        self.config.enable_activitypub = True
        self.app.pages_dir = markdown_dir
        self.app.mentions_dir = mentions_dir
        self.client = self.app.test_client()

    def tearDown(self):
        if hasattr(self, "config"):
            self.config.enable_activitypub = self._orig_enable_ap

    @skip_if_no_pubby
    def test_followers_html_page_returns_200(self):
        """Test the /followers HTML page renders when AP is enabled."""
        resp = self.client.get("/followers")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Followers", resp.data)

    @skip_if_no_pubby
    def test_followers_html_page_shows_no_followers(self):
        """Test the /followers page shows 'no followers' when empty."""
        resp = self.client.get("/followers")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No followers yet", resp.data)

    @skip_if_no_pubby
    def test_home_page_shows_followers_in_menu(self):
        """Test the home page shows the followers link in hamburger menu when AP is enabled."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"hamburger-menu", resp.data)
        self.assertIn(b"activitypub-handle", resp.data)
        self.assertIn(b"@blog@example.com", resp.data)
        self.assertIn(b'href="/followers"', resp.data)

    @skip_if_no_pubby
    def test_followers_route_404_when_ap_disabled(self):
        """Test /followers returns 404 when ActivityPub is disabled."""
        self.config.enable_activitypub = False
        resp = self.client.get("/followers")
        self.assertEqual(resp.status_code, 404)


class ActivityPubPublishTest(unittest.TestCase):
    """Test non-blocking publish logic, mention caching, and concurrency."""

    def setUp(self):
        from madblog.monitor import ChangeType

        self.ChangeType = ChangeType

    def _make_integration(self):
        """Create an ActivityPubIntegration with a mock handler in a temp dir."""
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.activitypub import ActivityPubIntegration
        from madblog.config import config

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        root = Path(tmpdir.name)
        pages_dir = root / "pages"
        pages_dir.mkdir()
        ap_dir = root / "ap"

        config.content_dir = str(root)

        priv, _ = generate_rsa_keypair()
        storage = FileActivityPubStorage(data_dir=str(ap_dir))
        handler = ActivityPubHandler(
            storage=storage,
            actor_config={
                "base_url": "https://example.com",
                "username": "blog",
            },
            private_key=priv,
        )

        integration = ActivityPubIntegration(
            handler=handler,
            pages_dir=str(pages_dir),
            base_url="https://example.com",
        )

        test_file = pages_dir / "test-post.md"
        test_file.write_text("[//]: # (title: Test Post)\n\n# Test Post\n\nHello.\n")

        return integration, handler, test_file, pages_dir

    # ------------------------------------------------------------------
    # Publish lifecycle
    # ------------------------------------------------------------------

    @skip_if_no_pubby
    def test_publish_calls_handler_once(self):
        """_handle_publish builds and publishes exactly once (no retry loop)."""
        integration, handler, test_file, _ = self._make_integration()
        handler.publish_object = MagicMock()

        url = integration.file_to_url(str(test_file))
        actor_url = f"{integration.base_url}{integration.handler.actor_path}"
        integration._handle_publish(str(test_file), url, actor_url)

        handler.publish_object.assert_called_once()

    @skip_if_no_pubby
    def test_failed_delivery_still_marks_as_published(self):
        """If publish_object raises, the file is still marked as processed."""
        integration, handler, test_file, _ = self._make_integration()
        handler.publish_object = MagicMock(side_effect=RuntimeError("delivery failed"))

        url = integration.file_to_url(str(test_file))
        actor_url = f"{integration.base_url}{integration.handler.actor_path}"
        integration._handle_publish(str(test_file), url, actor_url)

        handler.publish_object.assert_called_once()
        self.assertTrue(integration._is_published(url))

    @skip_if_no_pubby
    def test_failed_publish_not_retried_on_startup_sync(self):
        """A permanently failed publish is not retried by startup sync."""
        integration, handler, test_file, _ = self._make_integration()
        handler.publish_object = MagicMock(side_effect=RuntimeError("delivery failed"))

        url = integration.file_to_url(str(test_file))
        actor_url = f"{integration.base_url}{integration.handler.actor_path}"
        integration._handle_publish(str(test_file), url, actor_url)

        handler.publish_object.reset_mock()
        integration.sync_on_startup()
        handler.publish_object.assert_not_called()

    @skip_if_no_pubby
    def test_build_failure_marks_as_published(self):
        """If build_object itself fails, mark as published to prevent loops."""
        integration, handler, test_file, _ = self._make_integration()
        handler.publish_object = MagicMock()

        url = integration.file_to_url(str(test_file))
        actor_url = f"{integration.base_url}{integration.handler.actor_path}"

        with patch.object(
            integration,
            "build_object",
            side_effect=RuntimeError("parse error"),
        ):
            integration._handle_publish(str(test_file), url, actor_url)

        handler.publish_object.assert_not_called()
        self.assertTrue(integration._is_published(url))

    @skip_if_no_pubby
    def test_marked_as_published_before_delivery(self):
        """File is marked as published before publish_object is called."""
        integration, handler, test_file, _ = self._make_integration()

        url = integration.file_to_url(str(test_file))
        marked_during_publish = []

        def _check_marked(*args, **kwargs):
            marked_during_publish.append(integration._is_published(url))

        handler.publish_object = MagicMock(side_effect=_check_marked)

        actor_url = f"{integration.base_url}{integration.handler.actor_path}"
        integration._handle_publish(str(test_file), url, actor_url)

        self.assertTrue(marked_during_publish[0])

    # ------------------------------------------------------------------
    # Mention caching
    # ------------------------------------------------------------------

    @skip_if_no_pubby
    def test_resolve_mentions_caches_webfinger_results(self):
        """A resolved actor URL is cached and reused without a second HTTP call."""
        integration, _, _, _ = self._make_integration()
        text = "Hello @alice@remote.example"

        with patch(
            "pubby.resolve_actor_url",
            return_value="https://remote.example/users/alice",
        ) as mock_resolve:
            # First call with allow_network=True — does HTTP, caches result
            mentions = integration._resolve_mentions(text, allow_network=True)
            self.assertEqual(mock_resolve.call_count, 1)
            self.assertEqual(
                mentions[0].actor_url, "https://remote.example/users/alice"
            )

            # Second call — should hit cache, no HTTP
            mentions2 = integration._resolve_mentions(text, allow_network=True)
            self.assertEqual(mock_resolve.call_count, 1)  # still 1
            self.assertEqual(
                mentions2[0].actor_url, "https://remote.example/users/alice"
            )

    @skip_if_no_pubby
    def test_resolve_mentions_no_network_uses_fallback(self):
        """With allow_network=False and empty cache, a fallback URL is returned."""
        integration, _, _, _ = self._make_integration()
        text = "Hello @bob@other.example"

        with patch(
            "pubby.resolve_actor_url",
        ) as mock_resolve:
            mentions = integration._resolve_mentions(text, allow_network=False)
            mock_resolve.assert_not_called()
            self.assertEqual(mentions[0].actor_url, "https://other.example/@bob")

    @skip_if_no_pubby
    def test_resolve_mentions_no_network_uses_cache_if_populated(self):
        """With allow_network=False, cached values are returned (no fallback)."""
        integration, _, _, _ = self._make_integration()
        text = "Hello @carol@cached.example"

        # Prepopulate cache
        integration._mention_cache[("carol", "cached.example")] = (
            "https://cached.example/users/carol"
        )

        with patch(
            "pubby.resolve_actor_url",
        ) as mock_resolve:
            mentions = integration._resolve_mentions(text, allow_network=False)
            mock_resolve.assert_not_called()
            self.assertEqual(
                mentions[0].actor_url, "https://cached.example/users/carol"
            )

    @skip_if_no_pubby
    def test_build_object_request_path_never_does_http(self):
        """build_object with allow_network=False never calls resolve_actor_url."""
        integration, _, _, pages_dir = self._make_integration()

        mention_file = pages_dir / "with-mention.md"
        mention_file.write_text(
            "[//]: # (title: With Mention)\n\n" "Hello @dave@unreachable.example\n"
        )

        url = integration.file_to_url(str(mention_file))
        actor_url = f"{integration.base_url}{integration.handler.actor_path}"

        with patch(
            "pubby.resolve_actor_url",
        ) as mock_resolve:
            obj, _ = integration.build_object(
                str(mention_file), url, actor_url, allow_network=False
            )
            mock_resolve.assert_not_called()

        # Mention should use fallback URL
        mention_tags = [t for t in obj.tag if t.get("type") == "Mention"]
        self.assertEqual(len(mention_tags), 1)
        self.assertEqual(mention_tags[0]["href"], "https://unreachable.example/@dave")

    @skip_if_no_pubby
    def test_handle_publish_populates_mention_cache(self):
        """_handle_publish (background) resolves mentions and populates cache."""
        integration, handler, _, pages_dir = self._make_integration()
        handler.publish_object = MagicMock()

        mention_file = pages_dir / "mention-cache.md"
        mention_file.write_text(
            "[//]: # (title: Cache Test)\n\n" "CC @eve@fedi.example\n"
        )

        url = integration.file_to_url(str(mention_file))
        actor_url = f"{integration.base_url}{integration.handler.actor_path}"

        with patch(
            "pubby.resolve_actor_url",
            return_value="https://fedi.example/users/eve",
        ):
            integration._handle_publish(str(mention_file), url, actor_url)

        # Cache should now be populated
        self.assertIn(("eve", "fedi.example"), integration._mention_cache)
        self.assertEqual(
            integration._mention_cache[("eve", "fedi.example")],
            "https://fedi.example/users/eve",
        )

    # ------------------------------------------------------------------
    # Non-blocking / concurrency
    # ------------------------------------------------------------------

    @skip_if_no_pubby
    def test_duplicate_publish_for_same_url_is_dropped(self):
        """A second on_content_change for the same URL while one is in
        progress is silently dropped."""
        integration, handler, test_file, _ = self._make_integration()

        barrier = threading.Event()
        handler.publish_object = MagicMock(
            side_effect=lambda *a, **k: barrier.wait(timeout=5)
        )

        integration.on_content_change(self.ChangeType.ADDED, str(test_file))
        integration.on_content_change(self.ChangeType.EDITED, str(test_file))

        barrier.set()
        _join_ap_publish_threads()

        handler.publish_object.assert_called_once()

    @skip_if_no_pubby
    def test_concurrent_publishes_are_bounded(self):
        """At most _MAX_CONCURRENT_PUBLISHES threads run simultaneously."""
        import time
        from madblog.activitypub._integration import _MAX_CONCURRENT_PUBLISHES

        integration, handler, _, pages_dir = self._make_integration()

        n_files = _MAX_CONCURRENT_PUBLISHES + 3
        files = []
        for i in range(n_files):
            f = pages_dir / f"post-{i}.md"
            f.write_text(f"[//]: # (title: Post {i})\n\n# Post {i}\n\nBody.\n")
            files.append(f)

        barrier = threading.Event()
        concurrent_count = {"current": 0, "peak": 0}
        count_lock = threading.Lock()

        def _track_concurrency(*args, **kwargs):
            with count_lock:
                concurrent_count["current"] += 1
                concurrent_count["peak"] = max(
                    concurrent_count["peak"], concurrent_count["current"]
                )
            barrier.wait(timeout=10)
            with count_lock:
                concurrent_count["current"] -= 1

        handler.publish_object = MagicMock(side_effect=_track_concurrency)

        for f in files:
            integration.on_content_change(self.ChangeType.ADDED, str(f))

        time.sleep(0.1)

        with count_lock:
            self.assertLessEqual(concurrent_count["peak"], _MAX_CONCURRENT_PUBLISHES)

        barrier.set()
        _join_ap_publish_threads(timeout=2)


if __name__ == "__main__":
    unittest.main()
