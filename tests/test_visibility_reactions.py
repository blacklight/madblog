"""Tests for visibility filtering in reactions (author replies)."""

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


def create_article(temp_dir: str, filename: str) -> str:
    """Create a test article."""
    filepath = os.path.join(temp_dir, filename)
    content = f"# Test Article: {filename}\n\nThis is test content.\n"

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


def create_reply(
    replies_dir: str,
    article_slug: str,
    reply_filename: str,
    *,
    reply_to: str | None = None,
    visibility: str | None = None,
) -> str:
    """Create a test reply in the article's replies subdirectory."""
    article_replies_dir = os.path.join(replies_dir, article_slug)
    os.makedirs(article_replies_dir, exist_ok=True)

    filepath = os.path.join(article_replies_dir, reply_filename)
    content = ""
    if visibility:
        content += f"[//]: # (visibility: {visibility})\n"
    if reply_to:
        content += f"[//]: # (reply-to: {reply_to})\n"
    content += f"\n# Reply: {reply_filename}\n\nThis is reply content.\n"

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


class TestReactionsVisibilityFiltering:
    """Tests for visibility filtering in reactions (author replies)."""

    def test_public_reply_appears_in_reactions(self, temp_blog_dir, blog_app):
        """Public replies appear in reactions."""
        article_slug = "test-article"
        create_article(temp_blog_dir, f"{article_slug}.md")

        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            article_slug,
            "public-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="public",
        )

        with blog_app.test_request_context("/"):
            replies = blog_app._get_article_replies(article_slug)

        assert len(replies) == 1
        assert replies[0]["slug"] == "public-reply"

    def test_unlisted_reply_appears_in_reactions(self, temp_blog_dir, blog_app):
        """Unlisted replies appear in reactions (visible on page, just not in index)."""
        article_slug = "test-article"
        create_article(temp_blog_dir, f"{article_slug}.md")

        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            article_slug,
            "unlisted-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="unlisted",
        )

        with blog_app.test_request_context("/"):
            replies = blog_app._get_article_replies(article_slug)

        assert len(replies) == 1
        assert replies[0]["slug"] == "unlisted-reply"

    def test_followers_reply_excluded_from_reactions(self, temp_blog_dir, blog_app):
        """Followers-only replies are excluded from reactions."""
        article_slug = "test-article"
        create_article(temp_blog_dir, f"{article_slug}.md")

        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            article_slug,
            "followers-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="followers",
        )

        with blog_app.test_request_context("/"):
            replies = blog_app._get_article_replies(article_slug)

        assert len(replies) == 0

    def test_direct_reply_excluded_from_reactions(self, temp_blog_dir, blog_app):
        """Direct replies are excluded from reactions."""
        article_slug = "test-article"
        create_article(temp_blog_dir, f"{article_slug}.md")

        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            article_slug,
            "direct-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="direct",
        )

        with blog_app.test_request_context("/"):
            replies = blog_app._get_article_replies(article_slug)

        assert len(replies) == 0

    def test_draft_reply_excluded_from_reactions(self, temp_blog_dir, blog_app):
        """Draft replies are excluded from reactions."""
        article_slug = "test-article"
        create_article(temp_blog_dir, f"{article_slug}.md")

        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            article_slug,
            "draft-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="draft",
        )

        with blog_app.test_request_context("/"):
            replies = blog_app._get_article_replies(article_slug)

        assert len(replies) == 0

    def test_mixed_visibility_replies(self, temp_blog_dir, blog_app):
        """Only public and unlisted replies appear in reactions."""
        article_slug = "test-article"
        create_article(temp_blog_dir, f"{article_slug}.md")

        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            article_slug,
            "public-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="public",
        )
        create_reply(
            replies_dir,
            article_slug,
            "unlisted-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="unlisted",
        )
        create_reply(
            replies_dir,
            article_slug,
            "followers-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="followers",
        )
        create_reply(
            replies_dir,
            article_slug,
            "direct-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="direct",
        )
        create_reply(
            replies_dir,
            article_slug,
            "draft-reply.md",
            reply_to="http://localhost:5000/article/test-article",
            visibility="draft",
        )

        with blog_app.test_request_context("/"):
            replies = blog_app._get_article_replies(article_slug)

        assert len(replies) == 2
        slugs = {r["slug"] for r in replies}
        assert slugs == {"public-reply", "unlisted-reply"}

    def test_no_visibility_uses_default(self, temp_blog_dir, blog_app):
        """Replies without visibility metadata use the default (public)."""
        article_slug = "test-article"
        create_article(temp_blog_dir, f"{article_slug}.md")

        replies_dir = os.path.join(temp_blog_dir, "replies")
        create_reply(
            replies_dir,
            article_slug,
            "no-visibility-reply.md",
            reply_to="http://localhost:5000/article/test-article",
        )

        with blog_app.test_request_context("/"):
            replies = blog_app._get_article_replies(article_slug)

        # Default is public, so it should appear
        assert len(replies) == 1
        assert replies[0]["slug"] == "no-visibility-reply"
