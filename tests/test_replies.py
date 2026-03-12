"""
Tests for the Author Replies feature (Phase 1).
"""

import tempfile
import unittest
from pathlib import Path


class ReplyRouteTest(unittest.TestCase):
    """Test reply routes render correctly and return expected status codes."""

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

        # Create an article
        (markdown_dir / "my-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: My Post)",
                    "[//]: # (published: 2025-07-01)",
                    "",
                    "# My Post",
                    "Article body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Create replies directory and a reply
        replies_dir = root / "replies" / "my-post"
        replies_dir.mkdir(parents=True, exist_ok=True)

        (replies_dir / "thanks-alice.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://mastodon.social/users/alice/statuses/123)",
                    "[//]: # (published: 2025-07-02)",
                    "",
                    "# Re: Thanks Alice",
                    "Thank you for your thoughtful response!",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Create a guestbook reply
        guestbook_replies_dir = root / "replies" / "_guestbook"
        guestbook_replies_dir.mkdir(parents=True, exist_ok=True)

        (guestbook_replies_dir / "welcome.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://mastodon.social/users/bob/statuses/456)",
                    "[//]: # (published: 2025-07-03)",
                    "",
                    "# Welcome",
                    "Welcome to my blog!",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_title = config.title

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.title = "Test Blog"

        self.app.pages_dir = markdown_dir
        self.app.replies_dir = root / "replies"

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link
        self.config.title = self._orig_title

    def test_reply_route_renders(self):
        """Requesting /reply/<article>/<reply> returns 200 with rendered content."""
        with self.app.test_client() as client:
            resp = client.get("/reply/my-post/thanks-alice")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn("Thank you for your thoughtful response!", html)
            self.assertIn("Re: Thanks Alice", html)

    def test_reply_backlink_rendered(self):
        """The reply page should show a back-link to the reply-to URL."""
        with self.app.test_client() as client:
            resp = client.get("/reply/my-post/thanks-alice")
            html = resp.get_data(as_text=True)
            self.assertIn("https://mastodon.social/users/alice/statuses/123", html)

    def test_reply_raw_markdown(self):
        """Requesting /reply/<article>/<reply>.md returns raw Markdown."""
        with self.app.test_client() as client:
            resp = client.get("/reply/my-post/thanks-alice.md")
            self.assertEqual(resp.status_code, 200)
            text = resp.get_data(as_text=True)
            self.assertIn("Thank you for your thoughtful response!", text)
            self.assertEqual(resp.mimetype, "text/markdown")

    def test_reply_404_nonexistent(self):
        """Requesting a non-existent reply returns 404."""
        with self.app.test_client() as client:
            resp = client.get("/reply/my-post/nonexistent")
            self.assertEqual(resp.status_code, 404)

    def test_reply_404_nonexistent_article(self):
        """Requesting a reply under a non-existent article slug returns 404."""
        with self.app.test_client() as client:
            resp = client.get("/reply/no-such-article/thanks-alice")
            self.assertEqual(resp.status_code, 404)

    def test_guestbook_reply_route(self):
        """Guestbook replies under _guestbook pseudo-slug are accessible."""
        with self.app.test_client() as client:
            resp = client.get("/reply/_guestbook/welcome")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn("Welcome to my blog!", html)

    def test_reply_cache_headers(self):
        """Reply responses include standard cache headers."""
        with self.app.test_client() as client:
            resp = client.get("/reply/my-post/thanks-alice")
            self.assertIn("Last-Modified", resp.headers)
            self.assertIn("ETag", resp.headers)
            self.assertIn("Cache-Control", resp.headers)

    def test_reply_published_date(self):
        """The reply page should show the published date."""
        with self.app.test_client() as client:
            resp = client.get("/reply/my-post/thanks-alice")
            html = resp.get_data(as_text=True)
            self.assertIn("Jul 02, 2025", html)


class RepliesExcludedFromHomeTest(unittest.TestCase):
    """Test that replies do not appear in the home page listing."""

    def setUp(self):
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)

        # Use content_dir directly as pages_dir (no markdown/ subdir)
        # This is the case where replies_dir is a subdirectory of pages_dir.
        (root / "article.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: My Article)",
                    "[//]: # (published: 2025-07-01)",
                    "",
                    "# My Article",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        replies_dir = root / "replies" / "article"
        replies_dir.mkdir(parents=True, exist_ok=True)
        (replies_dir / "reply1.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://example.com/article/article)",
                    "[//]: # (published: 2025-07-02)",
                    "",
                    "# Reply 1",
                    "A reply body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_title = config.title

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.title = "Test Blog"

        # Simulate fallback mode: pages_dir == content_dir
        self.app.pages_dir = root
        self.app.replies_dir = root / "replies"

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link
        self.config.title = self._orig_title

    def test_replies_excluded_from_pages_listing(self):
        """Files under replies/ should not appear in _get_pages_from_files()."""
        with self.app.app_context():
            pages = self.app._get_pages_from_files()

        titles = [p.get("title") for p in pages]
        self.assertIn("My Article", titles)
        self.assertNotIn("Reply 1", titles)


class ReplyMetadataParsingTest(unittest.TestCase):
    """Test that reply metadata is parsed correctly."""

    def setUp(self):
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)

        replies_dir = root / "replies" / "my-post"
        replies_dir.mkdir(parents=True, exist_ok=True)

        (replies_dir / "test-reply.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://remote.social/statuses/999)",
                    "[//]: # (published: 2025-07-10)",
                    "[//]: # (title: Test Reply Title)",
                    "",
                    "# Test Reply Title",
                    "Reply content here.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link

        config.content_dir = str(root)
        config.link = "https://example.com"

        self.app.replies_dir = root / "replies"

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link

    def test_reply_to_extracted(self):
        """The reply-to metadata field is correctly parsed."""
        with self.app.app_context():
            metadata = self.app._parse_reply_metadata("my-post", "test-reply")
        self.assertEqual(metadata["reply-to"], "https://remote.social/statuses/999")

    def test_reply_uri_scheme(self):
        """The URI uses the /reply/ scheme."""
        with self.app.app_context():
            metadata = self.app._parse_reply_metadata("my-post", "test-reply")
        self.assertEqual(metadata["uri"], "/reply/my-post/test-reply")

    def test_reply_title_parsed(self):
        """The title is parsed from metadata."""
        with self.app.app_context():
            metadata = self.app._parse_reply_metadata("my-post", "test-reply")
        self.assertEqual(metadata["title"], "Test Reply Title")

    def test_reply_published_date(self):
        """The published date is parsed from metadata."""
        import datetime

        with self.app.app_context():
            metadata = self.app._parse_reply_metadata("my-post", "test-reply")
        self.assertEqual(metadata["published"], datetime.date(2025, 7, 10))


class ReplyTitleInferenceTest(unittest.TestCase):
    """Test title inference for replies with various content layouts."""

    def setUp(self):
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        replies_dir = root / "replies" / "some-post"
        replies_dir.mkdir(parents=True, exist_ok=True)

        # Reply with heading but no title metadata
        (replies_dir / "heading-only.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://example.com/article/some-post)",
                    "[//]: # (published: 2025-07-01)",
                    "",
                    "# My Heading Title",
                    "Some content.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Reply with no heading and no title metadata
        (replies_dir / "no-title.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://example.com/article/some-post)",
                    "[//]: # (published: 2025-07-01)",
                    "",
                    "Just a quick reply with no heading.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        config.content_dir = str(root)
        config.link = "https://example.com"
        self.app.replies_dir = root / "replies"

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link

    def test_title_inferred_from_heading(self):
        """Title is inferred from # heading when no title metadata is present."""
        with self.app.app_context():
            metadata = self.app._parse_reply_metadata("some-post", "heading-only")
        self.assertEqual(metadata["title"], "My Heading Title")

    def test_title_falls_back_to_slug(self):
        """Title falls back to the reply slug when no heading or metadata."""
        with self.app.app_context():
            metadata = self.app._parse_reply_metadata("some-post", "no-title")
        self.assertEqual(metadata["title"], "no-title")


class ThreadingModelTest(unittest.TestCase):
    """Tests for the threading model (Phase 2)."""

    def test_build_thread_tree_empty(self):
        """Empty inputs return empty tree."""
        from madblog.threading import build_thread_tree

        tree = build_thread_tree([], [], [], "https://example.com/article/test")
        self.assertEqual(tree, [])

    def test_author_replies_become_root_nodes(self):
        """Author replies to the article URL become root nodes."""
        from madblog.threading import build_thread_tree, ReactionType

        replies = [
            {
                "slug": "reply-1",
                "title": "Reply 1",
                "reply_to": "https://example.com/article/test",
                "published": None,
                "content_html": "<p>Content</p>",
                "permalink": "/reply/test/reply-1",
                "full_url": "https://example.com/reply/test/reply-1",
            }
        ]

        tree = build_thread_tree([], [], replies, "https://example.com/article/test")

        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].reaction_type, ReactionType.AUTHOR_REPLY)
        self.assertEqual(tree[0].item["slug"], "reply-1")

    def test_nested_replies_become_children(self):
        """A reply to another reply becomes a child node."""
        from madblog.threading import build_thread_tree

        replies = [
            {
                "slug": "reply-1",
                "title": "Reply 1",
                "reply_to": "https://example.com/article/test",
                "published": None,
                "content_html": "<p>First reply</p>",
                "permalink": "/reply/test/reply-1",
                "full_url": "https://example.com/reply/test/reply-1",
            },
            {
                "slug": "reply-2",
                "title": "Reply 2",
                "reply_to": "https://example.com/reply/test/reply-1",
                "published": None,
                "content_html": "<p>Nested reply</p>",
                "permalink": "/reply/test/reply-2",
                "full_url": "https://example.com/reply/test/reply-2",
            },
        ]

        tree = build_thread_tree([], [], replies, "https://example.com/article/test")

        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].item["slug"], "reply-1")
        self.assertEqual(len(tree[0].children), 1)
        self.assertEqual(tree[0].children[0].item["slug"], "reply-2")

    def test_reaction_anchor_id_stable(self):
        """Anchor IDs are stable and deterministic."""
        from madblog.threading import reaction_anchor_id

        id1 = reaction_anchor_id("wm", "https://example.com/post/123")
        id2 = reaction_anchor_id("wm", "https://example.com/post/123")
        self.assertEqual(id1, id2)
        self.assertTrue(id1.startswith("wm-"))


class ArticleRepliesCollectionTest(unittest.TestCase):
    """Tests for _get_article_replies() (Phase 2)."""

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

        # Create an article
        (markdown_dir / "test-article.md").write_text(
            "[//]: # (title: Test Article)\n\n# Test Article\nContent.",
            encoding="utf-8",
        )

        # Create replies
        replies_dir = root / "replies" / "test-article"
        replies_dir.mkdir(parents=True, exist_ok=True)

        (replies_dir / "first-reply.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://example.com/article/test-article)",
                    "[//]: # (published: 2025-07-01)",
                    "",
                    "# First Reply",
                    "First reply content.",
                ]
            ),
            encoding="utf-8",
        )

        (replies_dir / "second-reply.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://example.com/article/test-article)",
                    "[//]: # (published: 2025-07-02)",
                    "",
                    "# Second Reply",
                    "Second reply content.",
                ]
            ),
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        config.content_dir = str(root)
        config.link = "https://example.com"
        self.app.pages_dir = markdown_dir
        self.app.replies_dir = root / "replies"

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link

    def test_get_article_replies_returns_list(self):
        """_get_article_replies returns a list of reply dicts."""
        with self.app.app_context():
            replies = self.app._get_article_replies("test-article")

        self.assertIsInstance(replies, list)
        self.assertEqual(len(replies), 2)

    def test_get_article_replies_sorted_by_date(self):
        """Replies are sorted by published date ascending."""
        with self.app.app_context():
            replies = self.app._get_article_replies("test-article")

        self.assertEqual(replies[0]["slug"], "first-reply")
        self.assertEqual(replies[1]["slug"], "second-reply")

    def test_get_article_replies_contains_expected_keys(self):
        """Each reply dict contains expected keys."""
        with self.app.app_context():
            replies = self.app._get_article_replies("test-article")

        reply = replies[0]
        self.assertIn("slug", reply)
        self.assertIn("title", reply)
        self.assertIn("reply_to", reply)
        self.assertIn("published", reply)
        self.assertIn("content_html", reply)
        self.assertIn("permalink", reply)
        self.assertIn("full_url", reply)

    def test_get_article_replies_empty_for_nonexistent(self):
        """Returns empty list for articles without replies."""
        with self.app.app_context():
            replies = self.app._get_article_replies("nonexistent-article")

        self.assertEqual(replies, [])


class InlineReactionsRenderingTest(unittest.TestCase):
    """Tests for inline reactions rendering on article pages (Phase 2)."""

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

        # Create an article
        (markdown_dir / "article-with-reply.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Article With Reply)",
                    "[//]: # (published: 2025-07-01)",
                    "",
                    "# Article With Reply",
                    "Article body content.",
                ]
            ),
            encoding="utf-8",
        )

        # Create a reply to this article
        replies_dir = root / "replies" / "article-with-reply"
        replies_dir.mkdir(parents=True, exist_ok=True)

        (replies_dir / "author-reply.md").write_text(
            "\n".join(
                [
                    "[//]: # (reply-to: https://example.com/article/article-with-reply)",
                    "[//]: # (published: 2025-07-02)",
                    "",
                    "# Author Response",
                    "Thanks for reading!",
                ]
            ),
            encoding="utf-8",
        )

        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        config.content_dir = str(root)
        config.link = "https://example.com"
        self.app.pages_dir = markdown_dir
        self.app.replies_dir = root / "replies"

        self.client = self.app.test_client()

    def tearDown(self):
        self.config.content_dir = self._orig_content_dir
        self.config.link = self._orig_link

    def test_article_page_renders_author_reply_inline(self):
        """Article page includes author reply in reactions section."""
        rsp = self.client.get("/article/article-with-reply")
        self.assertEqual(rsp.status_code, 200)

        html = rsp.get_data(as_text=True)
        self.assertIn("reaction-author-reply", html)
        self.assertIn("Thanks for reading!", html)

    def test_reactions_section_has_heading(self):
        """Reactions section includes a heading when reactions exist."""
        rsp = self.client.get("/article/article-with-reply")
        html = rsp.get_data(as_text=True)
        self.assertIn("reactions-section", html)

    def test_author_reply_has_permalink_anchor(self):
        """Author replies have an anchor ID for permalinking."""
        rsp = self.client.get("/article/article-with-reply")
        html = rsp.get_data(as_text=True)
        self.assertIn('id="reply-', html)
