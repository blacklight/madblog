"""
Tests for state directory management and migration.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from madblog.config import config
from madblog.state import ensure_state_directory
from madblog.state._migrations import (
    detect_legacy_layout,
    migrate_legacy_state,
)


class TestDetectLegacyLayout(unittest.TestCase):
    """Test detection of legacy directory layouts."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)
        self.state_dir = self.root / ".madblog"

    def test_no_legacy_layout(self):
        """Empty content directory should not detect any legacy layout."""
        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertEqual(legacy, {})

    def test_detect_legacy_activitypub_with_followers(self):
        """Detect activitypub/ with followers/ subdirectory."""
        ap_dir = self.root / "activitypub"
        (ap_dir / "followers").mkdir(parents=True)

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertIn("activitypub", legacy)
        self.assertEqual(legacy["activitypub"], ap_dir)

    def test_detect_legacy_activitypub_with_objects(self):
        """Detect activitypub/ with objects/ subdirectory."""
        ap_dir = self.root / "activitypub"
        (ap_dir / "objects").mkdir(parents=True)

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertIn("activitypub", legacy)

    def test_detect_legacy_activitypub_with_private_key(self):
        """Detect activitypub/ with private_key.pem."""
        ap_dir = self.root / "activitypub"
        ap_dir.mkdir(parents=True)
        (ap_dir / "private_key.pem").write_text("KEY DATA")

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertIn("activitypub", legacy)

    def test_detect_legacy_mentions_with_incoming(self):
        """Detect mentions/ with incoming/ subdirectory."""
        mentions_dir = self.root / "mentions"
        (mentions_dir / "incoming").mkdir(parents=True)

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertIn("mentions", legacy)
        self.assertEqual(legacy["mentions"], mentions_dir)

    def test_detect_legacy_mentions_with_outgoing(self):
        """Detect mentions/ with outgoing/ subdirectory."""
        mentions_dir = self.root / "mentions"
        (mentions_dir / "outgoing").mkdir(parents=True)

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertIn("mentions", legacy)

    def test_skip_if_new_layout_exists_activitypub(self):
        """Don't detect activitypub/ if new layout already exists."""
        # Create legacy layout
        ap_dir = self.root / "activitypub"
        (ap_dir / "followers").mkdir(parents=True)

        # Create new layout
        (self.state_dir / "activitypub" / "state").mkdir(parents=True)

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertNotIn("activitypub", legacy)

    def test_skip_if_new_layout_exists_mentions(self):
        """Don't detect mentions/ if new layout already exists."""
        # Create legacy layout
        mentions_dir = self.root / "mentions"
        (mentions_dir / "incoming").mkdir(parents=True)

        # Create new layout
        (self.state_dir / "mentions").mkdir(parents=True)

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertNotIn("mentions", legacy)

    def test_ignore_unrelated_activitypub_dir(self):
        """Ignore activitypub/ without pubby storage markers."""
        ap_dir = self.root / "activitypub"
        ap_dir.mkdir(parents=True)
        (ap_dir / "random_file.txt").write_text("not pubby storage")

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertNotIn("activitypub", legacy)

    def test_ignore_unrelated_mentions_dir(self):
        """Ignore mentions/ without webmentions storage markers."""
        mentions_dir = self.root / "mentions"
        mentions_dir.mkdir(parents=True)
        (mentions_dir / "random_file.txt").write_text("not webmentions storage")

        legacy = detect_legacy_layout(self.root, self.state_dir)
        self.assertNotIn("mentions", legacy)


class TestMigrateLegacyState(unittest.TestCase):
    """Test migration of legacy state directories."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)
        self.state_dir = self.root / ".madblog"

    def test_no_migration_needed(self):
        """No migration when no legacy layout exists."""
        result = migrate_legacy_state(self.root, self.state_dir)
        self.assertFalse(result)

    def test_migrate_activitypub_directory(self):
        """Migrate activitypub/ to .madblog/activitypub/state/."""
        # Create legacy layout
        ap_dir = self.root / "activitypub"
        (ap_dir / "followers").mkdir(parents=True)
        (ap_dir / "followers" / "actor1.json").write_text('{"actor_id": "test"}')
        (ap_dir / "objects").mkdir(parents=True)
        (ap_dir / "objects" / "obj1.json").write_text('{"id": "test"}')

        result = migrate_legacy_state(self.root, self.state_dir)
        self.assertTrue(result)

        # Legacy dir should be gone
        self.assertFalse(ap_dir.exists())

        # New location should have the content
        new_ap = self.state_dir / "activitypub" / "state"
        self.assertTrue(new_ap.exists())
        self.assertTrue((new_ap / "followers" / "actor1.json").exists())
        self.assertTrue((new_ap / "objects" / "obj1.json").exists())

    def test_migrate_private_key_to_activitypub_level(self):
        """Private key should be at activitypub/ level, not inside state/."""
        # Create legacy layout with private key
        ap_dir = self.root / "activitypub"
        ap_dir.mkdir(parents=True)
        (ap_dir / "private_key.pem").write_text("PRIVATE KEY DATA")
        (ap_dir / "followers").mkdir()

        result = migrate_legacy_state(self.root, self.state_dir)
        self.assertTrue(result)

        # Key should be at activitypub/ level
        new_key = self.state_dir / "activitypub" / "private_key.pem"
        self.assertTrue(new_key.exists())
        self.assertEqual(new_key.read_text(), "PRIVATE KEY DATA")

        # Key should NOT be inside state/
        self.assertFalse(
            (self.state_dir / "activitypub" / "state" / "private_key.pem").exists()
        )

    def test_migrate_mentions_directory(self):
        """Migrate mentions/ to .madblog/mentions/."""
        # Create legacy layout
        mentions_dir = self.root / "mentions"
        (mentions_dir / "incoming" / "post-slug").mkdir(parents=True)
        (mentions_dir / "incoming" / "post-slug" / "webmention-test.md").write_text(
            "content"
        )
        (mentions_dir / "outgoing").mkdir(parents=True)

        result = migrate_legacy_state(self.root, self.state_dir)
        self.assertTrue(result)

        # Legacy dir should be gone
        self.assertFalse(mentions_dir.exists())

        # New location should have the content
        new_mentions = self.state_dir / "mentions"
        self.assertTrue(new_mentions.exists())
        self.assertTrue(
            (new_mentions / "incoming" / "post-slug" / "webmention-test.md").exists()
        )
        self.assertTrue((new_mentions / "outgoing").exists())

    def test_migrate_preserves_mtime(self):
        """Migration should preserve file modification times."""
        # Create legacy layout
        ap_dir = self.root / "activitypub"
        (ap_dir / "followers").mkdir(parents=True)
        test_file = ap_dir / "followers" / "test.json"
        test_file.write_text('{"test": true}')

        # Set a specific mtime in the past
        old_mtime = time.time() - 3600  # 1 hour ago
        os.utime(test_file, (old_mtime, old_mtime))

        result = migrate_legacy_state(self.root, self.state_dir)
        self.assertTrue(result)

        # Check mtime is preserved
        new_file = self.state_dir / "activitypub" / "state" / "followers" / "test.json"
        new_mtime = os.stat(new_file).st_mtime
        self.assertAlmostEqual(new_mtime, old_mtime, delta=1)

    def test_migrate_both_activitypub_and_mentions(self):
        """Both directories can be migrated in one call."""
        # Create both legacy layouts
        ap_dir = self.root / "activitypub"
        (ap_dir / "followers").mkdir(parents=True)

        mentions_dir = self.root / "mentions"
        (mentions_dir / "incoming").mkdir(parents=True)

        result = migrate_legacy_state(self.root, self.state_dir)
        self.assertTrue(result)

        # Both should be migrated
        self.assertFalse(ap_dir.exists())
        self.assertFalse(mentions_dir.exists())
        self.assertTrue((self.state_dir / "activitypub" / "state").exists())
        self.assertTrue((self.state_dir / "mentions").exists())


class TestEnsureStateDirectory(unittest.TestCase):
    """Test the ensure_state_directory function."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)

        # Save and set config
        self._old_content_dir = config.content_dir
        self._old_state_dir = config.state_dir
        config.content_dir = str(self.root)
        config.state_dir = None  # Use default
        self.addCleanup(self._restore_config)

    def _restore_config(self):
        config.content_dir = self._old_content_dir
        config.state_dir = self._old_state_dir

    def test_creates_state_directory(self):
        """ensure_state_directory creates the state dir if it doesn't exist."""
        state_dir = ensure_state_directory()
        self.assertTrue(state_dir.is_dir())
        self.assertEqual(state_dir, self.root / ".madblog")

    def test_runs_migration(self):
        """ensure_state_directory runs migration if legacy layout exists."""
        # Create legacy layout
        ap_dir = self.root / "activitypub"
        (ap_dir / "followers").mkdir(parents=True)
        (ap_dir / "followers" / "test.json").write_text("{}")

        state_dir = ensure_state_directory()

        # Migration should have run
        self.assertFalse(ap_dir.exists())
        self.assertTrue(
            (state_dir / "activitypub" / "state" / "followers" / "test.json").exists()
        )

    def test_custom_state_dir(self):
        """ensure_state_directory uses custom state_dir from config."""
        custom_state = self.root / "custom-state"
        config.state_dir = str(custom_state)

        state_dir = ensure_state_directory()
        self.assertEqual(state_dir, custom_state)
        self.assertTrue(state_dir.is_dir())


class TestResolvedStateDir(unittest.TestCase):
    """Test the config.resolved_state_dir property."""

    def setUp(self):
        self._old_content_dir = config.content_dir
        self._old_state_dir = config.state_dir
        self.addCleanup(self._restore_config)

    def _restore_config(self):
        config.content_dir = self._old_content_dir
        config.state_dir = self._old_state_dir

    def test_default_state_dir(self):
        """Default state_dir is content_dir/.madblog."""
        config.content_dir = "/tmp/test-content"
        config.state_dir = None

        self.assertEqual(config.resolved_state_dir, Path("/tmp/test-content/.madblog"))

    def test_custom_state_dir(self):
        """Custom state_dir overrides default."""
        config.content_dir = "/tmp/test-content"
        config.state_dir = "/custom/state"

        self.assertEqual(config.resolved_state_dir, Path("/custom/state"))

    def test_state_dir_expands_user(self):
        """state_dir expands ~ to home directory."""
        config.state_dir = "~/madblog-state"

        resolved = config.resolved_state_dir
        self.assertNotIn("~", str(resolved))
        self.assertTrue(str(resolved).startswith("/"))


if __name__ == "__main__":
    unittest.main()
