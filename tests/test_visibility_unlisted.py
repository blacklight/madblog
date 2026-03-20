"""Tests for visibility filtering on the /unlisted page."""

import os
import tempfile

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
