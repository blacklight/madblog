"""
Tests for the ActivityPub integration in Madblog.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


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
        if hasattr(self, "config"):
            self.config.enable_activitypub = False
            self.config.activitypub_link = self._orig_activitypub_link
            self.config.activitypub_domain = self._orig_activitypub_domain

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
        resp = client.get("/ap/actor")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["type"], "Person")
        self.assertEqual(data["preferredUsername"], "blog")

    @skip_if_no_pubby
    def test_activitypub_link_override_changes_actor_id(self):
        from madblog.config import config
        from madblog.app import BlogApp

        config.link = "https://example.com"
        config.activitypub_link = "https://ap.example.org"
        config.activitypub_domain = "example.org"

        app = BlogApp(__name__)
        client = app.test_client()

        resp = client.get("/.well-known/webfinger" "?resource=acct:blog@example.org")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["subject"], "acct:blog@example.org")
        self.assertEqual(data["aliases"][0], "https://ap.example.org/ap/actor")

        resp = client.get("/ap/actor")
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

        handler.publish_object.assert_called_once()
        obj = handler.publish_object.call_args[0][0]

        # Article ID should use AP base_url
        self.assertTrue(obj.id.startswith("https://ap.example.org/"))

        # If there are generated image attachments, they should use content_base_url
        for att in obj.attachment or []:
            if att.get("url", "").startswith("https://"):
                # Generated PNGs should point to content_base_url, not AP base_url
                self.assertFalse(
                    att["url"].startswith("https://ap.example.org/"),
                    f"Attachment URL should use content_base_url: {att['url']}",
                )


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


if __name__ == "__main__":
    unittest.main()
