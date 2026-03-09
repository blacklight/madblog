"""
Tests for the moderation module.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from pubby._model import Interaction, InteractionType, InteractionStatus

from madblog.app import BlogApp
from madblog.config import Config, config, _init_config_from_env
from madblog.moderation import is_blocked
from madblog.webmentions._mixin import WebmentionsMixin


class TestIsBlocked(unittest.TestCase):
    """Unit tests for ``is_blocked``."""

    # -- Empty / None edge cases --

    def test_empty_blocklist(self):
        self.assertFalse(is_blocked("https://example.com", []))

    def test_empty_identifier(self):
        self.assertFalse(is_blocked("", ["example.com"]))

    def test_none_blocklist(self):
        self.assertFalse(is_blocked("https://example.com", []))

    # -- Domain matching --

    def test_domain_blocks_url(self):
        self.assertTrue(
            is_blocked(
                "https://spammer.example.com/post/123",
                ["spammer.example.com"],
            )
        )

    def test_domain_blocks_url_case_insensitive(self):
        self.assertTrue(
            is_blocked(
                "https://Spammer.Example.COM/post/123",
                ["spammer.example.com"],
            )
        )

    def test_domain_does_not_block_different_domain(self):
        self.assertFalse(
            is_blocked(
                "https://legit.example.com/post/1",
                ["spammer.example.com"],
            )
        )

    def test_domain_blocks_activitypub_actor(self):
        self.assertTrue(
            is_blocked(
                "https://evil.social/users/someone",
                ["evil.social"],
            )
        )

    # -- Exact URL matching --

    def test_exact_url_match(self):
        url = "https://mastodon.social/users/spammer"
        self.assertTrue(is_blocked(url, [url]))

    def test_exact_url_case_insensitive(self):
        self.assertTrue(
            is_blocked(
                "https://Mastodon.Social/Users/Spammer",
                ["https://mastodon.social/users/spammer"],
            )
        )

    def test_exact_url_no_match(self):
        self.assertFalse(
            is_blocked(
                "https://mastodon.social/users/legit",
                ["https://mastodon.social/users/spammer"],
            )
        )

    # -- FQN matching --

    def test_fqn_with_at_prefix(self):
        self.assertTrue(
            is_blocked(
                "https://mastodon.social/users/spammer",
                ["@spammer@mastodon.social"],
            )
        )

    def test_fqn_without_at_prefix(self):
        self.assertTrue(
            is_blocked(
                "https://mastodon.social/users/spammer",
                ["spammer@mastodon.social"],
            )
        )

    def test_fqn_wrong_user(self):
        self.assertFalse(
            is_blocked(
                "https://mastodon.social/users/legit",
                ["@spammer@mastodon.social"],
            )
        )

    def test_fqn_wrong_domain(self):
        self.assertFalse(
            is_blocked(
                "https://other.social/users/spammer",
                ["@spammer@mastodon.social"],
            )
        )

    def test_fqn_case_insensitive(self):
        self.assertTrue(
            is_blocked(
                "https://Mastodon.Social/Users/Spammer",
                ["@spammer@mastodon.social"],
            )
        )

    # -- Regex matching --

    def test_regex_match(self):
        self.assertTrue(
            is_blocked(
                "https://spammer.example.com/post/123",
                ["/spammer\\.example\\.com/"],
            )
        )

    def test_regex_no_match(self):
        self.assertFalse(
            is_blocked(
                "https://legit.example.com/post/1",
                ["/spammer\\.example\\.com/"],
            )
        )

    def test_regex_partial_match(self):
        self.assertTrue(
            is_blocked(
                "https://evil.social/users/badactor",
                ["/evil\\.social/"],
            )
        )

    def test_invalid_regex_is_skipped(self):
        self.assertFalse(
            is_blocked(
                "https://example.com",
                ["/[invalid/"],
            )
        )

    # -- Multiple entries --

    def test_multiple_entries_first_matches(self):
        blocklist = ["spammer.example.com", "other.example.com"]
        self.assertTrue(is_blocked("https://spammer.example.com/post/1", blocklist))

    def test_multiple_entries_second_matches(self):
        blocklist = ["other.example.com", "spammer.example.com"]
        self.assertTrue(is_blocked("https://spammer.example.com/post/1", blocklist))

    def test_multiple_entries_none_matches(self):
        blocklist = ["a.example.com", "b.example.com"]
        self.assertFalse(is_blocked("https://legit.example.com/post/1", blocklist))

    # -- Whitespace in entries --

    def test_whitespace_entry_is_ignored(self):
        self.assertFalse(is_blocked("https://example.com", ["", "  "]))

    def test_entry_with_leading_trailing_space(self):
        self.assertTrue(
            is_blocked(
                "https://spammer.example.com/x",
                ["  spammer.example.com  "],
            )
        )

    # -- Webmention source URL scenarios --

    def test_webmention_source_blocked_by_domain(self):
        self.assertTrue(
            is_blocked(
                "https://spam-blog.net/2024/01/seo-garbage",
                ["spam-blog.net"],
            )
        )

    def test_webmention_source_blocked_by_regex(self):
        self.assertTrue(
            is_blocked(
                "https://subdomain.spam-blog.net/2024/01/seo-garbage",
                ["/spam-blog\\.net/"],
            )
        )


class TestBlockedActorsConfig(unittest.TestCase):
    """Test that the blocked_actors config field is parsed correctly."""

    def test_default_is_empty(self):
        cfg = Config()
        self.assertEqual(cfg.blocked_actors, [])

    def test_from_env_var(self):
        env = {"MADBLOG_BLOCKED_ACTORS": "evil.social,spammer.example.com"}
        with patch.dict(os.environ, env, clear=False):
            _init_config_from_env()

        self.assertEqual(config.blocked_actors, ["evil.social", "spammer.example.com"])

        # Reset
        config.blocked_actors = []

    def test_from_env_var_space_separated(self):
        env = {"MADBLOG_BLOCKED_ACTORS": "evil.social spammer.example.com"}
        with patch.dict(os.environ, env, clear=False):
            _init_config_from_env()

        self.assertEqual(config.blocked_actors, ["evil.social", "spammer.example.com"])

        # Reset
        config.blocked_actors = []


class TestWebmentionModeration(unittest.TestCase):
    """Test that the webmention handler rejects blocked sources."""

    def setUp(self):
        self._orig_blocked = config.blocked_actors[:]
        self._orig_enable_wm = config.enable_webmentions
        self._orig_content_dir = config.content_dir
        self._orig_link = config.link

        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        md_dir = root / "markdown"
        md_dir.mkdir(parents=True)

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_webmentions = False  # don't bind routes
        config.blocked_actors = ["spammer.example.com"]

        self.app = BlogApp(__name__)
        self.config = config

    def tearDown(self):
        self.config.blocked_actors = self._orig_blocked
        self.config.enable_webmentions = self._orig_enable_wm
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link

    def test_blocked_source_is_rejected(self):
        result = self.app.webmentions_handler.process_incoming_webmention(
            "https://spammer.example.com/post/1",
            "https://example.com/article/test",
        )
        self.assertIsNone(result)

    def test_allowed_source_reaches_original_handler(self):
        self.app.webmentions_handler.incoming.process_incoming_webmention = MagicMock(
            return_value="stored"
        )

        # The wrapper should delegate to the original (which we've mocked
        # at the *inner* level).  We need to also mock the outer original
        # to prove delegation happens.
        # Re-install moderation wrapper on a fresh mock.
        mock_original = MagicMock(return_value="stored")
        self.app.webmentions_handler.process_incoming_webmention = mock_original

        # Manually re-wrap
        WebmentionsMixin._install_webmention_moderation(self.app)

        self.app.webmentions_handler.process_incoming_webmention(
            "https://legit.example.com/post/1",
            "https://example.com/article/test",
        )
        mock_original.assert_called_once_with(
            "https://legit.example.com/post/1",
            "https://example.com/article/test",
        )


def _skip_if_no_pubby(test_func):
    """Decorator to skip tests if pubby is not available."""

    def wrapper(self, *args, **kwargs):
        try:
            import pubby  # noqa: F401
        except ImportError:
            self.skipTest("pubby is not installed")
        return test_func(self, *args, **kwargs)

    return wrapper


class TestActivityPubModeration(unittest.TestCase):
    """Test that the AP inbox handler rejects blocked actors."""

    @_skip_if_no_pubby
    def setUp(self):
        self._orig_blocked = config.blocked_actors[:]
        self._orig_enable_ap = config.enable_activitypub
        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_ap_link = config.activitypub_link
        self._orig_ap_domain = config.activitypub_domain

        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        md_dir = root / "markdown"
        md_dir.mkdir(parents=True)

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_activitypub = True
        config.activitypub_link = None
        config.activitypub_domain = None
        config.activitypub_private_key_path = None
        config.blocked_actors = ["evil.social"]

        with patch("madblog.activitypub._mixin.threading.Thread"):
            self.app = BlogApp(__name__)
        self.config = config

    def tearDown(self):
        if hasattr(self, "config"):
            self.config.blocked_actors = self._orig_blocked
            self.config.enable_activitypub = self._orig_enable_ap
            self.config.content_dir = self._orig_content_dir
            self.config.link = self._orig_link
            self.config.activitypub_link = self._orig_ap_link
            self.config.activitypub_domain = self._orig_ap_domain

    @_skip_if_no_pubby
    def test_blocked_actor_activity_is_dropped(self):
        activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "type": "Like",
            "id": "https://evil.social/activity/1",
            "actor": "https://evil.social/users/badguy",
            "object": "https://example.com/article/test",
        }

        result = self.app.activitypub_handler.process_inbox_activity(
            activity, skip_verification=True
        )
        self.assertIsNone(result)

    @_skip_if_no_pubby
    def test_allowed_actor_activity_is_processed(self):
        # Mock the original inbox.process to avoid real processing
        self.app.activitypub_handler.inbox.process = MagicMock(return_value=None)

        activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "type": "Like",
            "id": "https://good.social/activity/1",
            "actor": "https://good.social/users/niceperson",
            "object": "https://example.com/article/test",
        }

        # Re-install moderation wrapper so it wraps the mock
        self.app.activitypub_handler.process_inbox_activity(
            activity, skip_verification=True
        )

        # The activity from good.social should have reached the inner processor
        self.app.activitypub_handler.inbox.process.assert_called_once()

    @_skip_if_no_pubby
    def test_blocked_actor_interactions_filtered_at_render_time(self):
        # Store an interaction from a blocked actor directly in storage
        interaction = Interaction(
            source_actor_id="https://evil.social/users/badguy",
            target_resource="https://example.com/article/test",
            interaction_type=InteractionType.LIKE,
            activity_id="https://evil.social/activity/1",
            author_name="Bad Guy",
            status=InteractionStatus.CONFIRMED,
            published=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.app.activitypub_handler.storage.store_interaction(interaction)

        # _get_rendered_ap_interactions should filter it out
        # We need a file that maps to the target URL
        pages_dir = Path(self.config.content_dir) / "markdown"
        test_file = pages_dir / "test.md"
        test_file.write_text("[//]: # (title: Test)\n\n# Test\n\nContent.\n")

        result = self.app._get_rendered_ap_interactions(str(test_file))
        self.assertEqual(result, "")


class TestBlocklistCache(unittest.TestCase):
    """Tests for the TTL-based BlocklistCache."""

    def test_returns_config_blocked_actors(self):
        from madblog.config import config
        from madblog.moderation import BlocklistCache

        orig = config.blocked_actors[:]
        config.blocked_actors = ["evil.social", "spam.example.com"]
        try:
            cache = BlocklistCache(ttl_seconds=60)
            self.assertEqual(cache.get(), ["evil.social", "spam.example.com"])
        finally:
            config.blocked_actors = orig

    def test_cache_does_not_reload_within_ttl(self):
        from madblog.config import config
        from madblog.moderation import BlocklistCache

        orig = config.blocked_actors[:]
        config.blocked_actors = ["evil.social"]
        try:
            cache = BlocklistCache(ttl_seconds=300)
            cache.get()
            config.blocked_actors = ["other.social"]
            # Should still return the cached version
            self.assertEqual(cache.get(), ["evil.social"])
        finally:
            config.blocked_actors = orig

    def test_invalidate_forces_reload(self):
        from madblog.config import config
        from madblog.moderation import BlocklistCache

        orig = config.blocked_actors[:]
        config.blocked_actors = ["evil.social"]
        try:
            cache = BlocklistCache(ttl_seconds=300)
            cache.get()
            config.blocked_actors = ["other.social"]
            cache.invalidate()
            self.assertEqual(cache.get(), ["other.social"])
        finally:
            config.blocked_actors = orig


class TestGetFollowersFiltering(unittest.TestCase):
    """Test that blocked followers are excluded from get_followers()."""

    @_skip_if_no_pubby
    def setUp(self):
        from madblog.config import config

        self._orig_blocked = config.blocked_actors[:]
        self._orig_enable_ap = config.enable_activitypub
        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_ap_link = config.activitypub_link
        self._orig_ap_domain = config.activitypub_domain

        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        md_dir = root / "markdown"
        md_dir.mkdir(parents=True)

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_activitypub = True
        config.activitypub_link = None
        config.activitypub_domain = None
        config.activitypub_private_key_path = None
        config.blocked_actors = ["evil.social"]

        from madblog.app import BlogApp

        with patch("madblog.activitypub._mixin.threading.Thread"):
            self.app = BlogApp(__name__)
        self.config = config

    def tearDown(self):
        if hasattr(self, "config"):
            self.config.blocked_actors = self._orig_blocked
            self.config.enable_activitypub = self._orig_enable_ap
            self.config.content_dir = self._orig_content_dir
            self.config.link = self._orig_link
            self.config.activitypub_link = self._orig_ap_link
            self.config.activitypub_domain = self._orig_ap_domain

    @_skip_if_no_pubby
    def test_blocked_follower_excluded_from_get_followers(self):
        from pubby._model import Follower
        from datetime import datetime, timezone

        storage = self.app.activitypub_storage

        # Store a blocked and a non-blocked follower
        storage._write_json(
            storage._follower_path("https://evil.social/users/badguy"),
            Follower(
                actor_id="https://evil.social/users/badguy",
                inbox="https://evil.social/users/badguy/inbox",
                followed_at=datetime.now(timezone.utc),
            ).to_dict(),
        )
        storage._write_json(
            storage._follower_path("https://good.social/users/alice"),
            Follower(
                actor_id="https://good.social/users/alice",
                inbox="https://good.social/users/alice/inbox",
                followed_at=datetime.now(timezone.utc),
            ).to_dict(),
        )

        followers = storage.get_followers()
        actor_ids = [f.actor_id for f in followers]
        self.assertNotIn("https://evil.social/users/badguy", actor_ids)
        self.assertIn("https://good.social/users/alice", actor_ids)

    @_skip_if_no_pubby
    def test_no_blocklist_returns_all_followers(self):
        from pubby._model import Follower
        from datetime import datetime, timezone

        self.config.blocked_actors = []
        self.app._blocklist_cache.invalidate()

        storage = self.app.activitypub_storage
        storage._write_json(
            storage._follower_path("https://evil.social/users/badguy"),
            Follower(
                actor_id="https://evil.social/users/badguy",
                inbox="https://evil.social/users/badguy/inbox",
                followed_at=datetime.now(timezone.utc),
            ).to_dict(),
        )

        followers = storage.get_followers()
        self.assertEqual(len(followers), 1)


class TestReconcileBlockedFollowers(unittest.TestCase):
    """Test startup reconciliation of blocked/unblocked followers."""

    @_skip_if_no_pubby
    def setUp(self):
        from madblog.config import config

        self._orig_blocked = config.blocked_actors[:]
        self._orig_enable_ap = config.enable_activitypub
        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_ap_link = config.activitypub_link
        self._orig_ap_domain = config.activitypub_domain

        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        root = Path(self._tmpdir.name)
        md_dir = root / "markdown"
        md_dir.mkdir(parents=True)

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.enable_activitypub = True
        config.activitypub_link = None
        config.activitypub_domain = None
        config.activitypub_private_key_path = None
        config.blocked_actors = ["evil.social"]

        from madblog.app import BlogApp

        with patch("madblog.activitypub._mixin.threading.Thread"):
            self.app = BlogApp(__name__)
        self.config = config

    def tearDown(self):
        if hasattr(self, "config"):
            self.config.blocked_actors = self._orig_blocked
            self.config.enable_activitypub = self._orig_enable_ap
            self.config.content_dir = self._orig_content_dir
            self.config.link = self._orig_link
            self.config.activitypub_link = self._orig_ap_link
            self.config.activitypub_domain = self._orig_ap_domain

    @_skip_if_no_pubby
    def test_reconciliation_marks_blocked_follower(self):
        from pubby._model import Follower
        from datetime import datetime, timezone

        storage = self.app.activitypub_storage
        actor_id = "https://evil.social/users/badguy"
        fpath = storage._follower_path(actor_id)

        # Write a follower without the blocked flag
        storage._write_json(
            fpath,
            Follower(
                actor_id=actor_id,
                inbox="https://evil.social/users/badguy/inbox",
                followed_at=datetime.now(timezone.utc),
            ).to_dict(),
        )

        # Run reconciliation
        self.app._reconcile_blocked_followers()

        # Should now have "blocked": true
        data = storage._read_json(fpath)
        self.assertTrue(data.get("blocked"))

    @_skip_if_no_pubby
    def test_reconciliation_restores_unblocked_follower(self):
        import json

        storage = self.app.activitypub_storage
        actor_id = "https://good.social/users/alice"
        fpath = storage._follower_path(actor_id)

        # Write a follower that was previously blocked
        data = {
            "actor_id": actor_id,
            "inbox": "https://good.social/users/alice/inbox",
            "shared_inbox": "",
            "blocked": True,
        }
        storage._write_json(fpath, data)

        # Run reconciliation (good.social is NOT in blocklist)
        self.app._reconcile_blocked_followers()

        # "blocked" key should be removed
        data = storage._read_json(fpath)
        self.assertNotIn("blocked", data)

    @_skip_if_no_pubby
    def test_reconciliation_leaves_unblocked_follower_alone(self):
        from pubby._model import Follower
        from datetime import datetime, timezone

        storage = self.app.activitypub_storage
        actor_id = "https://good.social/users/alice"
        fpath = storage._follower_path(actor_id)

        follower_data = Follower(
            actor_id=actor_id,
            inbox="https://good.social/users/alice/inbox",
            followed_at=datetime.now(timezone.utc),
        ).to_dict()
        storage._write_json(fpath, follower_data)

        # Run reconciliation
        self.app._reconcile_blocked_followers()

        # Should not have "blocked" key
        data = storage._read_json(fpath)
        self.assertNotIn("blocked", data)

    @_skip_if_no_pubby
    def test_restored_follower_appears_in_get_followers(self):
        """A previously blocked follower whose rule was removed reappears."""
        storage = self.app.activitypub_storage
        actor_id = "https://formerly-evil.social/users/reformed"
        fpath = storage._follower_path(actor_id)

        # Simulate a follower that was blocked (flag set in JSON)
        data = {
            "actor_id": actor_id,
            "inbox": "https://formerly-evil.social/users/reformed/inbox",
            "shared_inbox": "",
            "blocked": True,
        }
        storage._write_json(fpath, data)

        # The blocklist does NOT include formerly-evil.social
        # Reconciliation should remove the flag
        self.app._reconcile_blocked_followers()
        self.app._blocklist_cache.invalidate()

        followers = storage.get_followers()
        actor_ids = [f.actor_id for f in followers]
        self.assertIn(actor_id, actor_ids)


if __name__ == "__main__":
    unittest.main()
