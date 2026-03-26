"""Tests for visibility filtering on the /unlisted page."""

import os
import tempfile
from pathlib import Path

import pytest

from madblog.app import BlogApp
from madblog.config import config


@pytest.fixture
def temp_blog_dir():
    """Create a temporary blog directory with test content."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create replies directory
        replies_dir = os.path.join(temp_dir, "replies")
        os.makedirs(replies_dir)
        yield temp_dir


@pytest.fixture
def blog_app(temp_blog_dir):
    """Create a BlogApp instance for testing."""
    original_content_dir = config.content_dir
    original_title = config.title
    original_link = config.link
    original_default_visibility = config.default_visibility

    config.content_dir = temp_blog_dir
    config.title = "Test Blog"
    config.link = "http://localhost:5000"
    config.default_visibility = "public"

    app = BlogApp(__name__)
    app.config["TESTING"] = True

    yield app

    config.content_dir = original_content_dir
    config.title = original_title
    config.link = original_link
    config.default_visibility = original_default_visibility


def create_article(temp_dir: str, filename: str, visibility: str | None = None) -> str:
    """Create a test article with optional visibility metadata."""
    filepath = os.path.join(temp_dir, filename)
    content = f"# Test Article: {filename}\n\n"
    if visibility:
        content = f"[//]: # (visibility: {visibility})\n\n" + content
    content += "This is test content.\n"

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


def create_reply(
    replies_dir: str,
    filename: str,
    *,
    reply_to: str | None = None,
    visibility: str | None = None,
) -> str:
    """Create a test reply with optional metadata."""
    filepath = os.path.join(replies_dir, filename)
    content = ""
    if visibility:
        content += f"[//]: # (visibility: {visibility})\n"
    if reply_to:
        content += f"[//]: # (reply-to: {reply_to})\n"
    content += f"\n# Reply: {filename}\n\nThis is reply content.\n"

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


class TestUnlistedPageVisibility:
    """Tests for visibility filtering on the /unlisted page."""

    def test_unlisted_article_appears_on_unlisted_page(self, temp_blog_dir, blog_app):
        """Articles with visibility: unlisted appear on /unlisted page."""
        create_article(temp_blog_dir, "unlisted-article.md", visibility="unlisted")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 1
        assert posts[0]["slug"] == "unlisted-article"
        assert posts[0]["is_article"] is True

    def test_public_article_excluded_from_unlisted_page(self, temp_blog_dir, blog_app):
        """Articles with visibility: public don't appear on /unlisted page."""
        create_article(temp_blog_dir, "public-article.md", visibility="public")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 0

    def test_draft_article_excluded_from_unlisted_page(self, temp_blog_dir, blog_app):
        """Articles with visibility: draft don't appear on /unlisted page."""
        create_article(temp_blog_dir, "draft-article.md", visibility="draft")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 0

    def test_unlisted_reply_appears_on_unlisted_page(self, temp_blog_dir, blog_app):
        """Root replies without reply-to appear on /unlisted page."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(replies_dir, "unlisted-reply.md")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 1
        assert posts[0]["slug"] == "unlisted-reply"
        assert posts[0]["is_article"] is False

    def test_reply_with_reply_to_excluded_from_unlisted(self, temp_blog_dir, blog_app):
        """Replies with reply-to don't appear on /unlisted page."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            "actual-reply.md",
            reply_to="https://example.com/post/123",
        )

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 0

    def test_unlisted_reply_with_public_visibility_excluded(
        self, temp_blog_dir, blog_app
    ):
        """Root replies with explicit visibility: public are excluded."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(replies_dir, "public-reply.md", visibility="public")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 0

    def test_unlisted_reply_with_draft_visibility_excluded(
        self, temp_blog_dir, blog_app
    ):
        """Root replies with visibility: draft are excluded from /unlisted."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(replies_dir, "draft-reply.md", visibility="draft")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 0

    def test_mixed_unlisted_content(self, temp_blog_dir, blog_app):
        """Both unlisted articles and replies appear together on /unlisted."""
        replies_dir = os.path.join(temp_blog_dir, "replies")

        create_article(temp_blog_dir, "unlisted-article.md", visibility="unlisted")
        create_reply(replies_dir, "unlisted-reply.md")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 2
        slugs = {p["slug"] for p in posts}
        assert slugs == {"unlisted-article", "unlisted-reply"}

    def test_unlisted_articles_in_subfolders(self, temp_blog_dir, blog_app):
        """Unlisted articles in subfolders appear on /unlisted page."""
        subfolder = os.path.join(temp_blog_dir, "subfolder")
        os.makedirs(subfolder)

        create_article(subfolder, "deep-unlisted.md", visibility="unlisted")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 1
        assert posts[0]["slug"] == "subfolder/deep-unlisted"
        assert posts[0]["is_article"] is True

    def test_index_md_excluded_from_unlisted(self, temp_blog_dir, blog_app):
        """index.md files are excluded even with unlisted visibility."""
        # Create an index.md with unlisted visibility
        index_path = os.path.join(temp_blog_dir, "index.md")
        with open(index_path, "w") as f:
            f.write("[//]: # (visibility: unlisted)\n\n# Index\n\nContent.\n")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_unlisted_posts()

        assert len(posts) == 0


class TestGetApReplies:
    """Tests for the get_ap_replies() method."""

    def test_ap_reply_with_public_visibility(self, temp_blog_dir, blog_app):
        """AP replies with public visibility are returned."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            "public-ap-reply.md",
            reply_to="https://remote.social/statuses/123",
            visibility="public",
        )

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_ap_replies()

        assert len(posts) == 1
        assert posts[0]["slug"] == "public-ap-reply"
        assert posts[0]["reply_to"] == "https://remote.social/statuses/123"

    def test_ap_reply_with_unlisted_visibility(self, temp_blog_dir, blog_app):
        """AP replies with unlisted visibility are returned."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            "unlisted-ap-reply.md",
            reply_to="https://remote.social/statuses/456",
            visibility="unlisted",
        )

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_ap_replies()

        assert len(posts) == 1
        assert posts[0]["slug"] == "unlisted-ap-reply"

    def test_ap_reply_with_draft_visibility_excluded(self, temp_blog_dir, blog_app):
        """AP replies with draft visibility are excluded."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            "draft-ap-reply.md",
            reply_to="https://remote.social/statuses/789",
            visibility="draft",
        )

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_ap_replies()

        assert len(posts) == 0

    def test_ap_reply_with_followers_visibility_excluded(self, temp_blog_dir, blog_app):
        """AP replies with followers visibility are excluded."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            "followers-ap-reply.md",
            reply_to="https://remote.social/statuses/101",
            visibility="followers",
        )

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_ap_replies()

        assert len(posts) == 0

    def test_unlisted_post_without_reply_to_excluded(self, temp_blog_dir, blog_app):
        """Posts without reply-to are not returned by get_ap_replies."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(replies_dir, "plain-post.md")

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_ap_replies()

        assert len(posts) == 0

    def test_ap_reply_no_content_excluded(self, temp_blog_dir, blog_app):
        """AP replies with no body content are excluded."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        filepath = os.path.join(replies_dir, "empty-reply.md")
        with open(filepath, "w") as f:
            f.write(
                "[//]: # (reply-to: https://remote.social/statuses/999)\n"
                "[//]: # (visibility: public)\n"
            )

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_ap_replies()

        assert len(posts) == 0

    def test_ap_reply_default_visibility_included(self, temp_blog_dir, blog_app):
        """AP replies with default (public) visibility are included."""
        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            "default-vis-reply.md",
            reply_to="https://remote.social/statuses/202",
        )

        with blog_app.test_request_context("/unlisted"):
            posts = blog_app.get_ap_replies()

        # Default visibility is public (set in fixture), so it should be included
        assert len(posts) == 1

    def test_get_ap_replies_disjoint_from_get_unlisted_posts(
        self, temp_blog_dir, blog_app
    ):
        """get_ap_replies and get_unlisted_posts return disjoint sets."""
        replies_dir = os.path.join(temp_blog_dir, "replies")

        # Unlisted post (no reply-to)
        create_reply(replies_dir, "unlisted-post.md")
        # AP reply (has reply-to)
        create_reply(
            replies_dir,
            "ap-reply.md",
            reply_to="https://remote.social/statuses/303",
            visibility="public",
        )

        with blog_app.test_request_context("/unlisted"):
            unlisted = blog_app.get_unlisted_posts()
            ap_replies = blog_app.get_ap_replies()

        unlisted_slugs = {p["slug"] for p in unlisted}
        ap_reply_slugs = {p["slug"] for p in ap_replies}

        assert unlisted_slugs == {"unlisted-post"}
        assert ap_reply_slugs == {"ap-reply"}
        assert unlisted_slugs.isdisjoint(ap_reply_slugs)


class TestUnlistedTabRoute:
    """Tests for the /unlisted tab query parameter.

    Uses the singleton ``app`` from :mod:`madblog.app` so that the
    routes registered in :mod:`madblog.routes` are available.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, temp_blog_dir):
        from madblog.app import app

        self.app = app
        self._orig_content_dir = config.content_dir
        self._orig_link = config.link
        self._orig_title = config.title
        self._orig_default_visibility = config.default_visibility

        config.content_dir = temp_blog_dir
        config.link = "http://localhost:5000"
        config.title = "Test Blog"
        config.default_visibility = "public"

        self.app.pages_dir = Path(temp_blog_dir)
        self.app.replies_dir = Path(temp_blog_dir) / "replies"

        self.replies_dir = os.path.join(temp_blog_dir, "replies")
        yield

        config.content_dir = self._orig_content_dir
        config.link = self._orig_link
        config.title = self._orig_title
        config.default_visibility = self._orig_default_visibility

    def test_default_tab_is_posts(self):
        """Default tab is 'posts' showing only unlisted posts."""
        create_reply(self.replies_dir, "unlisted-post.md")
        create_reply(
            self.replies_dir,
            "ap-reply.md",
            reply_to="https://remote.social/statuses/1",
            visibility="public",
        )

        with self.app.test_client() as client:
            resp = client.get("/unlisted")

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "unlisted-post" in html
        assert "ap-reply" not in html

    def test_posts_and_replies_tab_includes_both(self):
        """Posts and Replies tab shows both unlisted posts and AP replies."""
        create_reply(self.replies_dir, "unlisted-post.md")
        create_reply(
            self.replies_dir,
            "ap-reply.md",
            reply_to="https://remote.social/statuses/1",
            visibility="public",
        )

        with self.app.test_client() as client:
            resp = client.get("/unlisted?tab=posts_and_replies")

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "unlisted-post" in html
        assert "ap-reply" in html

    def test_invalid_tab_falls_back_to_posts(self):
        """Invalid tab values fall back to 'posts'."""
        create_reply(self.replies_dir, "unlisted-post.md")
        create_reply(
            self.replies_dir,
            "ap-reply.md",
            reply_to="https://remote.social/statuses/1",
            visibility="public",
        )

        with self.app.test_client() as client:
            resp = client.get("/unlisted?tab=invalid")

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "unlisted-post" in html
        assert "ap-reply" not in html

    def test_tabs_rendered_in_html(self):
        """Tab navigation links are rendered in the HTML."""
        create_reply(self.replies_dir, "unlisted-post.md")

        with self.app.test_client() as client:
            resp = client.get("/unlisted")

        html = resp.data.decode()
        assert 'role="tablist"' in html
        assert ">Posts</a>" in html
        assert ">Posts and Replies</a>" in html

    def test_active_tab_posts_highlighted(self):
        """Posts tab is highlighted when active."""
        create_reply(self.replies_dir, "unlisted-post.md")

        with self.app.test_client() as client:
            resp = client.get("/unlisted")

        html = resp.data.decode()
        assert 'aria-selected="true">Posts</a>' in html
        assert 'aria-selected="false">Posts and Replies</a>' in html

    def test_active_tab_posts_and_replies_highlighted(self):
        """Posts and Replies tab is highlighted when active."""
        create_reply(self.replies_dir, "unlisted-post.md")

        with self.app.test_client() as client:
            resp = client.get("/unlisted?tab=posts_and_replies")

        html = resp.data.decode()
        assert 'aria-selected="false">Posts</a>' in html
        assert 'aria-selected="true">Posts and Replies</a>' in html

    def test_posts_and_replies_shows_reply_to_context(self):
        """AP replies in the Posts and Replies tab show the reply-to URL."""
        create_reply(
            self.replies_dir,
            "ap-reply.md",
            reply_to="https://remote.social/statuses/42",
            visibility="public",
        )

        with self.app.test_client() as client:
            resp = client.get("/unlisted?tab=posts_and_replies")

        html = resp.data.decode()
        assert "https://remote.social/statuses/42" in html
        assert "In reply to" in html

    def test_404_when_no_posts(self):
        """Returns 404 when there are no posts at all."""
        with self.app.test_client() as client:
            resp = client.get("/unlisted")

        assert resp.status_code == 404

    def test_posts_and_replies_tab_only_ap_replies(self):
        """Posts and Replies tab works with only AP replies (no unlisted posts)."""
        create_reply(
            self.replies_dir,
            "ap-reply.md",
            reply_to="https://remote.social/statuses/1",
            visibility="public",
        )

        with self.app.test_client() as client:
            resp = client.get("/unlisted?tab=posts_and_replies")

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "ap-reply" in html
