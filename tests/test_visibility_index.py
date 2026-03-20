"""Tests for visibility filtering in the blog index."""

import os
import tempfile

import pytest

from madblog.app import BlogApp
from madblog.config import config
from madblog.visibility import Visibility


@pytest.fixture
def temp_blog_dir():
    """Create a temporary blog directory with test articles."""
    with tempfile.TemporaryDirectory() as temp_dir:
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


class TestBlogIndexVisibilityFiltering:
    """Tests for visibility filtering in the blog index."""

    def test_public_articles_appear_in_index(self, temp_blog_dir, blog_app):
        """Public articles should appear in the index."""
        create_article(temp_blog_dir, "public-article.md", visibility="public")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        assert len(pages) == 1
        assert pages[0][1]["path"] == "public-article.md"
        assert pages[0][1]["resolved_visibility"] == Visibility.PUBLIC

    def test_unlisted_articles_excluded_from_index(self, temp_blog_dir, blog_app):
        """Unlisted articles should be excluded from the index."""
        create_article(temp_blog_dir, "public-article.md", visibility="public")
        create_article(temp_blog_dir, "unlisted-article.md", visibility="unlisted")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        assert len(pages) == 1
        assert pages[0][1]["path"] == "public-article.md"

    def test_followers_articles_excluded_from_index(self, temp_blog_dir, blog_app):
        """Followers-only articles should be excluded from the index."""
        create_article(temp_blog_dir, "public-article.md", visibility="public")
        create_article(temp_blog_dir, "followers-article.md", visibility="followers")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        assert len(pages) == 1
        assert pages[0][1]["path"] == "public-article.md"

    def test_direct_articles_excluded_from_index(self, temp_blog_dir, blog_app):
        """Direct articles should be excluded from the index."""
        create_article(temp_blog_dir, "public-article.md", visibility="public")
        create_article(temp_blog_dir, "direct-article.md", visibility="direct")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        assert len(pages) == 1
        assert pages[0][1]["path"] == "public-article.md"

    def test_draft_articles_excluded_from_index(self, temp_blog_dir, blog_app):
        """Draft articles should be excluded from the index."""
        create_article(temp_blog_dir, "public-article.md", visibility="public")
        create_article(temp_blog_dir, "draft-article.md", visibility="draft")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        assert len(pages) == 1
        assert pages[0][1]["path"] == "public-article.md"

    def test_no_visibility_uses_config_default(self, temp_blog_dir, blog_app):
        """Articles without visibility metadata use config default."""
        create_article(temp_blog_dir, "no-visibility.md", visibility=None)

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        # Default visibility is public, so it should appear
        assert len(pages) == 1
        assert pages[0][1]["path"] == "no-visibility.md"
        assert pages[0][1]["resolved_visibility"] == Visibility.PUBLIC

    def test_config_default_unlisted(self, temp_blog_dir, blog_app, monkeypatch):
        """Articles use config default when no explicit visibility."""
        monkeypatch.setattr(config, "default_visibility", "unlisted")

        create_article(temp_blog_dir, "no-visibility.md", visibility=None)

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        # Default visibility is unlisted, so it should NOT appear in index
        assert len(pages) == 0

    def test_filter_by_visibility_can_be_disabled(self, temp_blog_dir, blog_app):
        """Visibility filtering can be disabled."""
        create_article(temp_blog_dir, "public-article.md", visibility="public")
        create_article(temp_blog_dir, "unlisted-article.md", visibility="unlisted")
        create_article(temp_blog_dir, "draft-article.md", visibility="draft")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages(filter_by_visibility=False)

        # All articles should appear when filtering is disabled
        assert len(pages) == 3

    def test_mixed_visibility_filtering(self, temp_blog_dir, blog_app):
        """Only public articles appear when multiple visibility levels exist."""
        create_article(temp_blog_dir, "public-1.md", visibility="public")
        create_article(temp_blog_dir, "public-2.md", visibility="public")
        create_article(temp_blog_dir, "unlisted.md", visibility="unlisted")
        create_article(temp_blog_dir, "followers.md", visibility="followers")
        create_article(temp_blog_dir, "direct.md", visibility="direct")
        create_article(temp_blog_dir, "draft.md", visibility="draft")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages()

        assert len(pages) == 2
        paths = {p[1]["path"] for p in pages}
        assert paths == {"public-1.md", "public-2.md"}

    def test_visibility_in_subfolders(self, temp_blog_dir, blog_app):
        """Visibility filtering works for articles in subfolders."""
        subfolder = os.path.join(temp_blog_dir, "subfolder")
        os.makedirs(subfolder)

        create_article(temp_blog_dir, "root-public.md", visibility="public")
        create_article(subfolder, "sub-public.md", visibility="public")
        create_article(subfolder, "sub-unlisted.md", visibility="unlisted")

        with blog_app.test_request_context("/"):
            pages = blog_app.get_pages(recursive=True)

        assert len(pages) == 2
        paths = {p[1]["path"] for p in pages}
        assert "root-public.md" in paths
        assert "subfolder/sub-public.md" in paths
