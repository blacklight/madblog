import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from madblog.config import config
from madblog.webmentions._storage import FileWebmentionsStorage


class TestWebmentionsStateDirPlacement(unittest.TestCase):
    """
    Regression test: the ``.madblog`` state directory must live under
    ``root_dir`` (the content root), **not** under ``content_dir``
    (the pages directory).
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        self.root = Path(self._tmpdir.name)
        self.pages_dir = self.root / "markdown"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = self.root / "mentions"

        # Set config.content_dir so resolved_state_dir points to the temp dir
        self._old_content_dir = config.content_dir
        config.content_dir = str(self.root)
        self.addCleanup(self._restore_config)

    def _restore_config(self):
        config.content_dir = self._old_content_dir

    def test_state_dir_under_root_dir(self):
        """When root_dir is given, .madblog must be under root_dir."""
        storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
            root_dir=self.root,
        )

        expected = self.root / ".madblog" / "webmentions_sync.json"
        self.assertEqual(storage._sync_cache_file, expected)
        self.assertTrue(expected.parent.is_dir())
        # Must NOT be under pages_dir
        self.assertFalse(str(storage._sync_cache_file).startswith(str(self.pages_dir)))

    def test_state_dir_defaults_to_content_dir_when_no_root(self):
        """When root_dir is omitted, .madblog falls back to config.resolved_state_dir."""
        storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
        )

        # Now uses config.resolved_state_dir (self.root / ".madblog")
        expected = self.root / ".madblog" / "webmentions_sync.json"
        self.assertEqual(storage._sync_cache_file, expected)

    def test_file_to_url_uses_content_dir(self):
        """URL generation must use content_dir (pages dir), not root_dir."""
        (self.pages_dir / "hello.md").write_text("# Hello\n", encoding="utf-8")

        storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
            root_dir=self.root,
        )

        url = storage.file_to_url(str(self.pages_dir / "hello.md"))
        self.assertEqual(url, "https://example.com/article/hello")


class TestOnContentChangeMalformedUrl(unittest.TestCase):
    """
    Regression test: a malformed URL (e.g. invalid IPv6) inside a
    markdown file must not crash the worker via ``ValueError`` from
    ``urlparse``.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        self.root = Path(self._tmpdir.name)
        self.pages_dir = self.root / "markdown"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = self.root / "mentions"

        self.storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
            root_dir=self.root,
        )

        self.handler = MagicMock()
        self.storage.set_handler(self.handler)

    def test_malformed_ipv6_url_does_not_crash(self):
        """ValueError from urlparse on malformed IPv6 must be caught."""
        md_file = self.pages_dir / "bad-link.md"
        md_file.write_text(
            "Check [this](http://[invalid-ipv6]:8080/path)\n",
            encoding="utf-8",
        )

        self.handler.process_outgoing_webmentions.side_effect = ValueError(
            "Invalid IPv6 URL"
        )

        from madblog.monitor import ChangeType

        # Must not raise
        self.storage.on_content_change(ChangeType.ADDED, str(md_file))

    def test_deleted_content_with_malformed_url_does_not_crash(self):
        """ValueError during deletion must also be caught."""
        md_file = self.pages_dir / "bad-link.md"
        md_file.write_text("placeholder", encoding="utf-8")

        self.handler.process_outgoing_webmentions.side_effect = ValueError(
            "Invalid IPv6 URL"
        )

        from madblog.monitor import ChangeType

        # Must not raise
        self.storage.on_content_change(ChangeType.DELETED, str(md_file))


class TestNormalizeAuthor(unittest.TestCase):
    """Tests for _normalize_author which fixes legacy author_url data."""

    def test_plain_name_in_author_url_moves_to_author_name(self):
        """A non-URL author_url should be moved to author_name."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            author_url="Alice",
            author_name=None,
        )

        FileWebmentionsStorage._normalize_author(mention)

        self.assertEqual(mention.author_name, "Alice")
        self.assertIsNone(mention.author_url)

    def test_plain_name_in_author_url_does_not_overwrite_existing_name(self):
        """If author_name is already set, don't overwrite it."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            author_url="Bob",
            author_name="Alice",
        )

        FileWebmentionsStorage._normalize_author(mention)

        self.assertEqual(mention.author_name, "Alice")
        self.assertIsNone(mention.author_url)

    def test_valid_url_not_modified(self):
        """A proper URL in author_url should be left as-is."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            author_url="https://alice.example.com",
            author_name="Alice",
        )

        FileWebmentionsStorage._normalize_author(mention)

        self.assertEqual(mention.author_url, "https://alice.example.com")
        self.assertEqual(mention.author_name, "Alice")

    def test_mailto_url_not_modified(self):
        """A mailto: author_url should be left as-is."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            author_url="mailto:alice@example.com",
        )

        FileWebmentionsStorage._normalize_author(mention)

        self.assertEqual(mention.author_url, "mailto:alice@example.com")


class TestNormalizeContent(unittest.TestCase):
    """Tests for _normalize_content which fixes legacy 'None' string content."""

    def test_none_string_content_cleared(self):
        """Content stored as literal 'None' should become None."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            content="None",
        )

        FileWebmentionsStorage._normalize_content(mention)

        self.assertIsNone(mention.content)

    def test_none_string_excerpt_cleared(self):
        """Excerpt stored as literal 'None' should become None."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            excerpt="None",
        )

        FileWebmentionsStorage._normalize_content(mention)

        self.assertIsNone(mention.excerpt)

    def test_none_string_title_cleared(self):
        """Title stored as literal 'None' should become None."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            title="None",
        )

        FileWebmentionsStorage._normalize_content(mention)

        self.assertIsNone(mention.title)

    def test_real_content_not_modified(self):
        """Actual content should be left as-is."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            content="<p>Hello world</p>",
            excerpt="Hello world",
            title="My Post",
        )

        FileWebmentionsStorage._normalize_content(mention)

        self.assertEqual(mention.content, "<p>Hello world</p>")
        self.assertEqual(mention.excerpt, "Hello world")
        self.assertEqual(mention.title, "My Post")

    def test_format_webmention_none_content_not_written(self):
        """Serializing a webmention with None content must not write 'None'."""
        from webmentions import Webmention, WebmentionDirection

        mention = Webmention(
            source="https://example.com/a",
            target="https://example.com/b",
            direction=WebmentionDirection.IN,
            content=None,
        )

        md = FileWebmentionsStorage._format_webmention_markdown(mention)
        self.assertNotIn("\nNone\n", md)


class TestOutgoingWebmentionVisibility(unittest.TestCase):
    """
    Outgoing webmentions must be suppressed for posts with
    ``visibility: direct``, ``visibility: followers``, or
    ``visibility: draft``.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        self.root = Path(self._tmpdir.name)
        self.pages_dir = self.root / "markdown"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = self.root / "mentions"
        self.replies_dir = self.root / "replies"
        self.replies_dir.mkdir(parents=True, exist_ok=True)

        self._old_content_dir = config.content_dir
        config.content_dir = str(self.root)
        self.addCleanup(self._restore_config)

        self.storage = FileWebmentionsStorage(
            content_dir=self.pages_dir,
            mentions_dir=self.mentions_dir,
            base_url="https://example.com",
            root_dir=self.root,
            replies_dir=self.replies_dir,
        )

        self.handler = MagicMock()
        self.storage.set_handler(self.handler)

    def _restore_config(self):
        config.content_dir = self._old_content_dir

    def _write_md(self, path, visibility=None, body="Check https://other.blog/post\n"):
        lines = []
        if visibility:
            lines.append(f"[//]: # (visibility: {visibility})\n")
        lines.append(body)
        path.write_text("".join(lines), encoding="utf-8")

    # -- articles --

    def test_public_article_sends_webmentions(self):
        md = self.pages_dir / "pub.md"
        self._write_md(md, visibility="public")

        from madblog.monitor import ChangeType

        self.storage.on_content_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_called_once()

    def test_unlisted_article_sends_webmentions(self):
        md = self.pages_dir / "unl.md"
        self._write_md(md, visibility="unlisted")

        from madblog.monitor import ChangeType

        self.storage.on_content_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_called_once()

    def test_direct_article_skips_webmentions(self):
        md = self.pages_dir / "dm.md"
        self._write_md(md, visibility="direct")

        from madblog.monitor import ChangeType

        self.storage.on_content_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_not_called()

    def test_followers_article_skips_webmentions(self):
        md = self.pages_dir / "fol.md"
        self._write_md(md, visibility="followers")

        from madblog.monitor import ChangeType

        self.storage.on_content_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_not_called()

    def test_draft_article_skips_webmentions(self):
        md = self.pages_dir / "draft.md"
        self._write_md(md, visibility="draft")

        from madblog.monitor import ChangeType

        self.storage.on_content_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_not_called()

    def test_no_visibility_defaults_to_public(self):
        md = self.pages_dir / "default.md"
        self._write_md(md)

        from madblog.monitor import ChangeType

        self.storage.on_content_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_called_once()

    # -- replies --

    def test_direct_reply_skips_webmentions(self):
        sub = self.replies_dir / "some-article"
        sub.mkdir(parents=True, exist_ok=True)
        md = sub / "dm-reply.md"
        self._write_md(md, visibility="direct")

        from madblog.monitor import ChangeType

        self.storage.on_reply_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_not_called()

    def test_followers_reply_skips_webmentions(self):
        sub = self.replies_dir / "some-article"
        sub.mkdir(parents=True, exist_ok=True)
        md = sub / "fol-reply.md"
        self._write_md(md, visibility="followers")

        from madblog.monitor import ChangeType

        self.storage.on_reply_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_not_called()

    def test_public_reply_sends_webmentions(self):
        sub = self.replies_dir / "some-article"
        sub.mkdir(parents=True, exist_ok=True)
        md = sub / "pub-reply.md"
        self._write_md(md, visibility="public")

        from madblog.monitor import ChangeType

        self.storage.on_reply_change(ChangeType.ADDED, str(md))
        self.handler.process_outgoing_webmentions.assert_called_once()

    # -- deleted files should still be processed (retraction) --

    def test_deleted_direct_still_processes(self):
        """Deletion must still send retraction even for previously-direct posts."""
        md = self.pages_dir / "dm-del.md"
        self._write_md(md, visibility="direct")

        from madblog.monitor import ChangeType

        self.storage.on_content_change(ChangeType.DELETED, str(md))
        self.handler.process_outgoing_webmentions.assert_called_once()


if __name__ == "__main__":
    unittest.main()
