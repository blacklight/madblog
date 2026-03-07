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
            "MADBLOG_ACTIVITYPUB_USERNAME": "testuser",
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
        self.assertEqual(config.activitypub_username, "testuser")
        self.assertEqual(config.activitypub_name, "Test Blog")
        self.assertEqual(config.activitypub_summary, "A test blog")
        self.assertEqual(config.activitypub_icon_url, "https://example.com/icon.png")
        self.assertEqual(config.activitypub_private_key_path, "/tmp/key.pem")
        self.assertTrue(config.activitypub_manually_approves_followers)
        self.assertTrue(config.activitypub_description_only)

        # Reset
        config.enable_activitypub = False
        config.activitypub_username = "blog"
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
        self._tmpdir = tempfile.TemporaryDirectory()
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
        config.activitypub_private_key_path = None
        config.author = "Test Author"

        # Create a fresh Flask app to avoid "setup already finished" errors
        from madblog.app import BlogApp

        self.app = BlogApp(__name__)

    def tearDown(self):
        if hasattr(self, "config"):
            self.config.enable_activitypub = False

    @skip_if_no_pubby
    def test_webfinger(self):
        client = self.app.test_client()
        resp = client.get("/.well-known/webfinger" "?resource=acct:blog@example.com")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["subject"], "acct:blog@example.com")

    @skip_if_no_pubby
    def test_actor(self):
        client = self.app.test_client()
        resp = client.get("/ap/actor")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["type"], "Person")
        self.assertEqual(data["preferredUsername"], "blog")

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
        from madblog.storage.activitypub import ActivityPubIntegration

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
        self.assertEqual(obj.name, "Hello")
        self.assertIn("https://example.com/article/hello", obj.id)

    @skip_if_no_pubby
    def test_on_content_change_delete(self):
        from pubby import ActivityPubHandler
        from pubby.crypto import generate_rsa_keypair
        from pubby.storage.adapters.file import FileActivityPubStorage
        from madblog.storage.activitypub import ActivityPubIntegration

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


class ActivityPubNotificationsTest(unittest.TestCase):
    """Test the AP email notifier."""

    @skip_if_no_pubby
    def test_email_sent_on_interaction(self):
        from madblog.notifications import SmtpConfig, build_activitypub_email_notifier
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


if __name__ == "__main__":
    unittest.main()
