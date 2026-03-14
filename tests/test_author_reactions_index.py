"""
Tests for the AuthorReactionsIndex (JSON-persisted reverse index)
and template rendering of author reactions.
"""

import json
import tempfile
import unittest
from pathlib import Path

from madblog.monitor import ChangeType
from madblog.reactions import AuthorReactionsIndex


class AuthorReactionsIndexTest(unittest.TestCase):
    """Core tests for the AuthorReactionsIndex."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.state_dir = root / "state"
        self.state_dir.mkdir()
        self.replies_dir = root / "replies"
        self.replies_dir.mkdir()
        self.base_url = "https://example.com"

        self.index = AuthorReactionsIndex(
            state_dir=self.state_dir,
            replies_dir=self.replies_dir,
            base_url=self.base_url,
        )

    def _write_reply(self, subdir: str, slug: str, like_of: str) -> Path:
        """Helper: write a reply file with like-of metadata."""
        reply_dir = self.replies_dir / subdir
        reply_dir.mkdir(parents=True, exist_ok=True)
        path = reply_dir / f"{slug}.md"
        path.write_text(
            f"[//]: # (like-of: {like_of})\n"
            f"[//]: # (published: 2025-07-10)\n"
            f"\n"
            f"# I liked this\n",
            encoding="utf-8",
        )
        return path

    def test_empty_index_initially(self):
        """Index starts empty before load or scan."""
        self.assertEqual(self.index.get_reactions("https://example.com/article/x"), [])

    def test_scan_populates_index(self):
        """Adding a file with like-of targeting a local URL populates the index."""
        self._write_reply("my-post", "liked-it", "https://example.com/article/my-post")

        self.index.load()

        reactions = self.index.get_reactions("https://example.com/article/my-post")
        self.assertEqual(len(reactions), 1)
        self.assertEqual(reactions[0]["type"], "like")
        self.assertEqual(reactions[0]["source_url"], "/reply/my-post/liked-it")

    def test_persists_to_json(self):
        """The index is persisted to a JSON file after load/scan."""
        self._write_reply("my-post", "liked-it", "https://example.com/article/my-post")

        self.index.load()

        index_file = self.state_dir / "author_reactions_index.json"
        self.assertTrue(index_file.exists())

        with open(index_file, "r") as f:
            data = json.load(f)
        self.assertIn("https://example.com/article/my-post", data)

    def test_reload_from_json_restores_index(self):
        """Reloading from the persisted JSON restores the index."""
        self._write_reply("my-post", "liked-it", "https://example.com/article/my-post")
        self.index.load()

        # Create a new index instance pointing at the same state
        index2 = AuthorReactionsIndex(
            state_dir=self.state_dir,
            replies_dir=self.replies_dir,
            base_url=self.base_url,
        )
        index2.load()

        reactions = index2.get_reactions("https://example.com/article/my-post")
        self.assertEqual(len(reactions), 1)
        self.assertEqual(reactions[0]["source_url"], "/reply/my-post/liked-it")

    def test_external_url_not_indexed(self):
        """A like-of pointing at an external URL is NOT in the index."""
        self._write_reply(
            "my-post", "external-like", "https://remote.social/statuses/42"
        )

        self.index.load()

        self.assertEqual(
            self.index.get_reactions("https://remote.social/statuses/42"), []
        )
        # No entries at all
        self.assertEqual(
            self.index.get_reactions("https://example.com/article/my-post"), []
        )

    def test_on_reply_change_add(self):
        """on_reply_change with ADDED indexes the new file."""
        path = self._write_reply(
            "my-post", "new-like", "https://example.com/article/my-post"
        )
        self.index.load()  # Start with empty (no files existed before scan)

        # Simulate adding the file via monitor callback
        self.index.on_reply_change(ChangeType.ADDED, str(path))

        reactions = self.index.get_reactions("https://example.com/article/my-post")
        self.assertEqual(len(reactions), 1)

    def test_on_reply_change_edit(self):
        """on_reply_change with EDITED re-indexes the file."""
        path = self._write_reply(
            "my-post", "liked-it", "https://example.com/article/my-post"
        )
        self.index.load()

        # Edit the file to point at a different target
        path.write_text(
            "[//]: # (like-of: https://example.com/article/other-post)\n"
            "[//]: # (published: 2025-07-10)\n"
            "\n"
            "# Changed my mind\n",
            encoding="utf-8",
        )
        self.index.on_reply_change(ChangeType.EDITED, str(path))

        # Old target should be empty
        self.assertEqual(
            self.index.get_reactions("https://example.com/article/my-post"), []
        )
        # New target should have the entry
        reactions = self.index.get_reactions("https://example.com/article/other-post")
        self.assertEqual(len(reactions), 1)

    def test_on_reply_change_delete(self):
        """on_reply_change with DELETED removes entries."""
        path = self._write_reply(
            "my-post", "liked-it", "https://example.com/article/my-post"
        )
        self.index.load()
        self.assertEqual(
            len(self.index.get_reactions("https://example.com/article/my-post")), 1
        )

        self.index.on_reply_change(ChangeType.DELETED, str(path))

        self.assertEqual(
            self.index.get_reactions("https://example.com/article/my-post"), []
        )

    def test_on_reply_change_flushes_to_disk(self):
        """on_reply_change persists changes to JSON."""
        path = self._write_reply(
            "my-post", "liked-it", "https://example.com/article/my-post"
        )
        self.index.load()

        # Delete and verify JSON is updated
        self.index.on_reply_change(ChangeType.DELETED, str(path))

        with open(self.state_dir / "author_reactions_index.json", "r") as f:
            data = json.load(f)
        self.assertEqual(data, {})

    def test_multiple_likes_same_target(self):
        """Multiple files liking the same target all appear in the index."""
        self._write_reply("my-post", "like-1", "https://example.com/article/my-post")
        self._write_reply("my-post", "like-2", "https://example.com/article/my-post")

        self.index.load()

        reactions = self.index.get_reactions("https://example.com/article/my-post")
        self.assertEqual(len(reactions), 2)
        sources = {r["source_url"] for r in reactions}
        self.assertEqual(sources, {"/reply/my-post/like-1", "/reply/my-post/like-2"})

    def test_no_duplicate_on_rescan(self):
        """Re-indexing the same file does not create duplicates."""
        path = self._write_reply(
            "my-post", "liked-it", "https://example.com/article/my-post"
        )
        self.index.load()

        # Simulate edit (re-index same content)
        self.index.on_reply_change(ChangeType.EDITED, str(path))

        reactions = self.index.get_reactions("https://example.com/article/my-post")
        self.assertEqual(len(reactions), 1)

    def test_replies_dir_missing(self):
        """load() handles a non-existent replies directory gracefully."""
        import shutil

        shutil.rmtree(self.replies_dir)

        self.index.load()
        self.assertEqual(self.index.get_reactions("https://example.com/anything"), [])

    def test_file_without_like_of_not_indexed(self):
        """A reply file without like-of metadata is not indexed."""
        reply_dir = self.replies_dir / "my-post"
        reply_dir.mkdir(parents=True, exist_ok=True)
        (reply_dir / "plain-reply.md").write_text(
            "[//]: # (reply-to: https://example.com/article/my-post)\n"
            "[//]: # (published: 2025-07-10)\n"
            "\n"
            "# Just a reply\n"
            "No like-of here.\n",
            encoding="utf-8",
        )

        self.index.load()

        self.assertEqual(
            self.index.get_reactions("https://example.com/article/my-post"), []
        )


class AuthorReactionsTemplateTest(unittest.TestCase):
    """Template rendering tests for author-reaction footers."""

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
        replies_dir = root / "replies"
        replies_dir.mkdir(parents=True, exist_ok=True)

        # Article that is the SOURCE of a like (has like-of metadata)
        (markdown_dir / "like-source.md").write_text(
            "[//]: # (title: Like Source)\n"
            "[//]: # (published: 2025-07-10)\n"
            "[//]: # (like-of: https://remote.social/statuses/42)\n"
            "\n"
            "# Like Source\n"
            "I liked a remote post.\n",
            encoding="utf-8",
        )

        # Article that is the TARGET of an author like
        (markdown_dir / "like-target.md").write_text(
            "[//]: # (title: Like Target)\n"
            "[//]: # (published: 2025-07-10)\n"
            "\n"
            "# Like Target\n"
            "This article is liked by the author.\n",
            encoding="utf-8",
        )

        # Article that is both source and target
        (markdown_dir / "like-both.md").write_text(
            "[//]: # (title: Both)\n"
            "[//]: # (published: 2025-07-10)\n"
            "[//]: # (like-of: https://remote.social/statuses/99)\n"
            "\n"
            "# Both\n"
            "Source and target.\n",
            encoding="utf-8",
        )

        # Plain article with no likes
        (markdown_dir / "plain.md").write_text(
            "[//]: # (title: Plain Article)\n"
            "[//]: # (published: 2025-07-10)\n"
            "\n"
            "# Plain Article\n"
            "No likes here.\n",
            encoding="utf-8",
        )

        # Reply that likes a local article (like-target)
        like_reply_dir = replies_dir / "like-target"
        like_reply_dir.mkdir(parents=True, exist_ok=True)
        (like_reply_dir / "liked-it.md").write_text(
            "[//]: # (like-of: https://example.com/article/like-target)\n"
            "[//]: # (published: 2025-07-10)\n"
            "\n"
            "# Liked\n",
            encoding="utf-8",
        )

        # Reply that likes the "both" article
        like_both_dir = replies_dir / "like-both"
        like_both_dir.mkdir(parents=True, exist_ok=True)
        (like_both_dir / "liked-both.md").write_text(
            "[//]: # (like-of: https://example.com/article/like-both)\n"
            "[//]: # (published: 2025-07-10)\n"
            "\n"
            "# Liked both\n",
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link

        config.content_dir = str(root)
        config.link = "https://example.com"

        self.app.pages_dir = markdown_dir
        self.app.replies_dir = replies_dir

        # Rebuild the author reactions index for the new content
        self.app.author_reactions_index = AuthorReactionsIndex(
            state_dir=config.resolved_state_dir,
            replies_dir=replies_dir,
            base_url=config.link,
        )
        self.app.author_reactions_index.load()

        self.client = self.app.test_client()

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link

    def test_outgoing_like_footer_rendered(self):
        """A page with like-of metadata renders the outgoing-reactions footer."""
        rsp = self.client.get("/article/like-source")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.get_data(as_text=True)
        self.assertIn("author-reactions", html)
        self.assertIn("u-like-of", html)
        self.assertIn("https://remote.social/statuses/42", html)

    def test_author_liked_indicator_rendered(self):
        """A page that is the target of an author like renders the indicator."""
        rsp = self.client.get("/article/like-target")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.get_data(as_text=True)
        self.assertIn("author-liked-by", html)

    def test_both_outgoing_and_incoming(self):
        """A page that is both source and target renders both footers."""
        rsp = self.client.get("/article/like-both")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.get_data(as_text=True)
        self.assertIn("u-like-of", html)
        self.assertIn("https://remote.social/statuses/99", html)
        self.assertIn("author-liked-by", html)

    def test_no_likes_renders_neither(self):
        """A page with no likes renders neither footer."""
        rsp = self.client.get("/article/plain")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.get_data(as_text=True)
        self.assertNotIn("author-reactions", html)
        self.assertNotIn("u-like-of", html)
        self.assertNotIn("author-liked-by", html)
