"""Regression tests for stale HTTP cache invalidation."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from madblog.config import config


def _touch(path: Path, mtime: float | None = None) -> None:
    """Create an empty file and optionally set its mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _article_content(title: str, published: str = "2026-01-01T00:00:00") -> str:
    return f"""[//]: # (title: {title})
[//]: # (published: {published})

# {title}

Content.
"""


class CacheHelperTest(unittest.TestCase):
    """Unit tests for new cache helper primitives."""

    def test_get_recursive_max_mtime_nested_tree(self):
        """Recursive mtime reflects the most recent nested entry."""
        from madblog.cache import get_recursive_max_mtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "b").mkdir(parents=True)
            (root / "a" / "b" / "deep.txt").write_text("deep")
            (root / "c.txt").write_text("top")

            base = root.stat().st_mtime
            os.utime(root / "a", (base - 100, base - 100))
            os.utime(root / "a" / "b", (base - 100, base - 100))
            os.utime(root / "a" / "b" / "deep.txt", (base - 100, base - 100))
            os.utime(root / "c.txt", (base - 100, base - 100))
            os.utime(root, (base + 100, base + 100))

            self.assertEqual(get_recursive_max_mtime(root), base + 100)
            self.assertEqual(get_recursive_max_mtime(root / "a" / "b"), base - 100)
            self.assertEqual(get_recursive_max_mtime(root / "missing"), 0.0)
            self.assertEqual(get_recursive_max_mtime(None), 0.0)

    def test_compute_pages_mtime_folder_and_followers(self):
        """compute_pages_mtime honours folder-scoped trees and follower mtimes."""
        from madblog.cache import compute_pages_mtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "folder" / "sub").mkdir(parents=True)
            (root / "folder" / "sub" / "article.md").write_text("x")
            (root / "folder" / "top.md").write_text("y")

            t1 = 1000.0
            t2 = 2000.0
            t3 = 3000.0
            t4 = 4000.0
            os.utime(root / "folder", (t1, t1))
            os.utime(root / "folder" / "sub", (t2, t2))
            os.utime(root / "folder" / "top.md", (t3, t3))
            os.utime(root / "folder" / "sub" / "article.md", (t4, t4))

            pages = [(0, {"file_mtime": t3})]
            self.assertEqual(
                compute_pages_mtime(pages, root, folder="folder"),
                t4,
            )
            self.assertEqual(
                compute_pages_mtime(
                    pages, root, folder="folder", followers_mtime=t4 + 100
                ),
                t4 + 100,
            )
            self.assertEqual(
                compute_pages_mtime([], root, folder="folder"),
                t4,
            )


class StaleCacheRouteTest(unittest.TestCase):
    """Regression tests for the stale-cache bugs."""

    def setUp(self):
        from madblog.app import app

        self.app = app

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_title = config.title
        self._orig_enable_guestbook = config.enable_guestbook
        self._orig_enable_webmentions = config.enable_webmentions
        self._orig_enable_activitypub = config.enable_activitypub

        self._orig_pages_dir = self.app.pages_dir
        self._orig_replies_dir = self.app.replies_dir
        self._orig_mentions_dir = getattr(self.app, "mentions_dir", None)
        self._orig_ap_storage = getattr(self.app, "activitypub_storage", None)
        self._orig_reply_index = getattr(self.app, "reply_metadata_index", None)
        self._orig_state_dir = config.state_dir

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        config.state_dir = None

        root = Path(self._tmpdir.name)
        self.markdown_dir = root / "markdown"
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.replies_dir = root / "replies"
        self.replies_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = root / ".madblog" / "mentions"
        self.mentions_dir.mkdir(parents=True, exist_ok=True)
        self.ap_state_dir = root / ".madblog" / "activitypub" / "state"
        (self.ap_state_dir / "interactions").mkdir(parents=True, exist_ok=True)
        (self.ap_state_dir / "followers").mkdir(parents=True, exist_ok=True)

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.title = "Test Blog"
        config.enable_guestbook = True
        config.enable_webmentions = True
        config.enable_activitypub = True

        self.app.pages_dir = self.markdown_dir
        self.app.replies_dir = self.replies_dir
        self.app.mentions_dir = self.mentions_dir
        self.app.activitypub_storage = MagicMock()
        self.app.activitypub_storage.get_followers.return_value = []
        # Force direct filesystem scanning for unlisted tests.
        self.app.reply_metadata_index = None

        self.client = self.app.test_client()

    def tearDown(self):
        config.content_dir = self._orig_content_dir
        config.link = self._orig_link
        config.title = self._orig_title
        config.enable_guestbook = self._orig_enable_guestbook
        config.enable_webmentions = self._orig_enable_webmentions
        config.enable_activitypub = self._orig_enable_activitypub
        config.state_dir = self._orig_state_dir

        self.app.pages_dir = self._orig_pages_dir
        self.app.replies_dir = self._orig_replies_dir
        if self._orig_mentions_dir is not None:
            self.app.mentions_dir = self._orig_mentions_dir
        if self._orig_ap_storage is not None:
            self.app.activitypub_storage = self._orig_ap_storage
        elif hasattr(self.app, "activitypub_storage"):
            delattr(self.app, "activitypub_storage")
        if self._orig_reply_index is not None:
            self.app.reply_metadata_index = self._orig_reply_index
        else:
            self.app.reply_metadata_index = None

    def _write_article(self, rel_path: str, title: str, mtime: float) -> Path:
        full = self.markdown_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(_article_content(title))
        os.utime(full, (mtime, mtime))
        return full

    def _revalidation_headers(self, response) -> dict:
        return {
            "If-None-Match": response.headers.get("ETag", ""),
            "If-Modified-Since": response.headers.get("Last-Modified", ""),
        }

    def _base_time(self) -> float:
        return time.time()

    def test_article_invalidates_on_second_nested_ap_interaction(self):
        """A second interaction under an existing target tree busts article cache."""
        base = self._base_time()
        self._write_article("test-post.md", "Test Post", base)

        interactions = self.ap_state_dir / "interactions"
        hash_dir = interactions / "abc123"
        hash_dir.mkdir(parents=True, exist_ok=True)
        _touch(hash_dir / "first.json", base)

        first = self.client.get("/article/test-post")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(hash_dir / "second.json", base + 10)

        second = self.client.get(
            "/article/test-post", headers=self._revalidation_headers(first)
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_article_invalidates_on_new_webmention(self):
        """A new webmention for an existing article busts the article cache."""
        base = self._base_time()
        self._write_article("webmention-post.md", "Webmention Post", base)

        wm_dir = self.mentions_dir / "incoming" / "webmention-post"
        _touch(wm_dir / "webmention-1.md", base)

        first = self.client.get("/article/webmention-post")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(wm_dir / "webmention-2.md", base + 10)

        second = self.client.get(
            "/article/webmention-post",
            headers=self._revalidation_headers(first),
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_article_invalidates_on_follower_change(self):
        """A follower addition invalidates a cached article page."""
        base = self._base_time()
        self._write_article("follower-post.md", "Follower Post", base)

        first = self.client.get("/article/follower-post")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(self.ap_state_dir / "followers" / "alice.json", base + 10)

        second = self.client.get(
            "/article/follower-post",
            headers=self._revalidation_headers(first),
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_article_invalidates_on_follower_removal(self):
        """A follower removal invalidates a cached article page."""
        base = self._base_time()
        self._write_article("follower-removal-post.md", "Follower Removal Post", base)

        first = self.client.get("/article/follower-removal-post")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        follower = self.ap_state_dir / "followers" / "remove-me.json"
        _touch(follower)

        second = self.client.get(
            "/article/follower-removal-post",
            headers=self._revalidation_headers(first),
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)
        second_etag = second.headers["ETag"]

        follower.unlink()

        third = self.client.get(
            "/article/follower-removal-post",
            headers=self._revalidation_headers(second),
        )
        self.assertEqual(third.status_code, 200)
        self.assertNotEqual(third.headers["ETag"], second_etag)

    def test_folder_index_invalidates_on_nested_page(self):
        """Adding a page under an existing subfolder busts the folder index cache."""
        base = self._base_time()
        self._write_article("folder/sub/article.md", "Sub Article", base)

        first = self.client.get("/~folder/")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        self._write_article("folder/sub/new-article.md", "New Article", base + 10)

        second = self.client.get("/~folder/", headers=self._revalidation_headers(first))
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_home_index_invalidates_on_follower_change(self):
        """A follower addition invalidates the home/blog index cache."""
        base = self._base_time()
        self._write_article("home-article.md", "Home Article", base)

        first = self.client.get("/blog")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(self.ap_state_dir / "followers" / "bob.json", base + 10)

        second = self.client.get("/blog", headers=self._revalidation_headers(first))
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_home_index_invalidates_on_follower_removal(self):
        """A follower removal invalidates the home/blog index cache."""
        base = self._base_time()
        self._write_article("home-article-removal.md", "Home Article Removal", base)

        # Force page/follower directory mtimes to the base value so the
        # initial response ETag depends only on the article, and later
        # follower changes produce strictly increasing mtimes.
        os.utime(self.markdown_dir, (base, base))
        os.utime(self.ap_state_dir / "followers", (base, base))

        first = self.client.get("/blog")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        follower = self.ap_state_dir / "followers" / "home-remove-me.json"
        _touch(follower, base + 100)

        second = self.client.get("/blog", headers=self._revalidation_headers(first))
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)
        second_etag = second.headers["ETag"]

        follower.unlink()
        # Simulate a directory mtime update caused by the removal with a
        # strictly higher mtime, so the third request sees a newer ETag.
        os.utime(self.ap_state_dir / "followers", (base + 200, base + 200))

        third = self.client.get("/blog", headers=self._revalidation_headers(second))
        self.assertEqual(third.status_code, 200)
        self.assertNotEqual(third.headers["ETag"], second_etag)

    def test_guestbook_invalidates_on_nested_webmention(self):
        """A nested guestbook webmention addition busts the guestbook cache."""
        base = self._base_time()
        _touch(self.mentions_dir / "incoming" / "_homepage" / "first.md", base)

        first = self.client.get("/guestbook")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(self.mentions_dir / "incoming" / "_homepage" / "second.md", base + 10)

        second = self.client.get(
            "/guestbook", headers=self._revalidation_headers(first)
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_guestbook_invalidates_on_follower_change(self):
        """A follower addition invalidates a cached guestbook page."""
        base = self._base_time()
        _touch(self.mentions_dir / "incoming" / "_homepage" / "msg.md", base)

        first = self.client.get("/guestbook")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(self.ap_state_dir / "followers" / "guestbook-follower.json", base + 10)

        second = self.client.get(
            "/guestbook", headers=self._revalidation_headers(first)
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_unlisted_invalidates_on_new_unlisted_post(self):
        """A new unlisted post busts the unlisted timeline cache."""
        base = self._base_time()
        first_post = self.replies_dir / "first-unlisted.md"
        first_post.write_text(_article_content("First Unlisted"))
        os.utime(first_post, (base, base))

        first = self.client.get("/unlisted")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        second_post = self.replies_dir / "second-unlisted.md"
        second_post.write_text(_article_content("Second Unlisted"))
        os.utime(second_post, (base + 10, base + 10))

        second = self.client.get("/unlisted", headers=self._revalidation_headers(first))
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_unlisted_invalidates_on_follower_change(self):
        """A follower addition invalidates the unlisted timeline cache."""
        base = self._base_time()
        first_post = self.replies_dir / "unlisted-for-followers.md"
        first_post.write_text(_article_content("Unlisted For Followers"))
        os.utime(first_post, (base, base))

        first = self.client.get("/unlisted")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(self.ap_state_dir / "followers" / "unlisted-follower.json", base + 10)

        second = self.client.get("/unlisted", headers=self._revalidation_headers(first))
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)

    def test_followers_route_invalidates_on_new_follower(self):
        """Adding a follower updates the /followers cache headers."""
        base = self._base_time()

        first = self.client.get("/followers")
        self.assertEqual(first.status_code, 200)
        first_etag = first.headers["ETag"]

        _touch(self.ap_state_dir / "followers" / "new-follower.json", base + 10)

        second = self.client.get(
            "/followers", headers=self._revalidation_headers(first)
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.headers["ETag"], first_etag)


if __name__ == "__main__":
    unittest.main()
