"""Tests for folder support functionality."""

import os
import tempfile
from pathlib import Path
from unittest import TestCase

from madblog.config import config


class FolderTestCase(TestCase):
    """Base test case with folder structure setup."""

    def setUp(self):
        from madblog.app import app

        self.app = app

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.markdown_dir = root / "markdown"
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        config.content_dir = str(root)
        config.link = "http://test.local"
        config.title = "Test Blog"
        config.author = "Test Author"
        config.enable_webmentions = False

        self.app.pages_dir = self.markdown_dir
        self.app.replies_dir = root / "replies"
        self.client = self.app.test_client()

    def _create_article(self, path: str, content: str = "# Test\n\nContent"):
        """Create a markdown file at the given path relative to markdown_dir."""
        full_path = os.path.join(self.markdown_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

    def _create_folder(self, path: str):
        """Create a folder at the given path relative to markdown_dir."""
        full_path = os.path.join(self.markdown_dir, path)
        os.makedirs(full_path, exist_ok=True)


class FolderVisibilityTest(FolderTestCase):
    """Tests for folder visibility rules."""

    def test_hidden_folder_starting_with_dot_not_shown(self):
        self._create_article(".hidden/article.md")
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(folders, [])

    def test_hidden_folder_starting_with_underscore_not_shown(self):
        self._create_article("_private/article.md")
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(folders, [])

    def test_empty_folder_not_shown(self):
        self._create_folder("empty")
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(folders, [])

    def test_folder_with_only_index_md_metadata_is_empty(self):
        self._create_folder("meta-only")
        self._create_article(
            "meta-only/index.md",
            "[//]: # (title: Meta Only)\n[//]: # (description: Just metadata)\n",
        )
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(folders, [])

    def test_folder_with_article_is_shown(self):
        self._create_article("docs/guide.md")
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]["name"], "docs")

    def test_folder_with_subfolder_containing_article_is_shown(self):
        self._create_article("parent/child/article.md")
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]["name"], "parent")


class FolderMetadataTest(FolderTestCase):
    """Tests for folder metadata from index.md."""

    def test_folder_uses_name_when_no_index_md(self):
        self._create_article("docs/article.md")
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(folders[0]["title"], "docs")

    def test_folder_uses_title_from_index_md(self):
        self._create_article("docs/article.md")
        self._create_article(
            "docs/index.md",
            "[//]: # (title: Documentation)\n",
        )
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(folders[0]["title"], "Documentation")

    def test_folder_uses_description_from_index_md(self):
        self._create_article("docs/article.md")
        self._create_article(
            "docs/index.md",
            "[//]: # (description: All documentation)\n",
        )
        folders = self.app._get_folders_in_dir("")
        self.assertEqual(folders[0]["description"], "All documentation")

    def test_parse_folder_metadata_returns_empty_when_no_index(self):
        self._create_folder("docs")
        metadata = self.app._parse_folder_metadata("docs")
        self.assertEqual(metadata, {})

    def test_parse_folder_metadata_detects_content(self):
        self._create_article(
            "docs/index.md",
            "[//]: # (title: Docs)\n\n# Welcome\n\nThis has content.",
        )
        metadata = self.app._parse_folder_metadata("docs")
        self.assertTrue(metadata.get("has_content"))

    def test_parse_folder_metadata_detects_no_content(self):
        self._create_article(
            "docs/index.md",
            "[//]: # (title: Docs)\n[//]: # (description: Just meta)",
        )
        metadata = self.app._parse_folder_metadata("docs")
        self.assertFalse(metadata.get("has_content"))


class FolderRoutingTest(FolderTestCase):
    """Tests for folder routes."""

    def test_folder_index_route_returns_200(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/")
        self.assertEqual(response.status_code, 200)

    def test_folder_index_route_without_trailing_slash(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs")
        self.assertEqual(response.status_code, 200)

    def test_folder_index_route_404_for_nonexistent(self):
        response = self.client.get("/~nonexistent/")
        self.assertEqual(response.status_code, 404)

    def test_folder_index_shows_articles(self):
        self._create_article("docs/guide.md", "# Guide\n\nA guide.")
        response = self.client.get("/~docs/")
        self.assertIn(b"Guide", response.data)

    def test_folder_index_shows_subfolders(self):
        self._create_article("docs/api/reference.md")
        response = self.client.get("/~docs/")
        self.assertIn(b"api", response.data)

    def test_nested_folder_route(self):
        self._create_article("docs/api/reference.md")
        response = self.client.get("/~docs/api/")
        self.assertEqual(response.status_code, 200)

    def test_folder_with_custom_index_renders_as_page(self):
        self._create_article(
            "docs/index.md",
            "# Documentation\n\nWelcome to the docs!",
        )
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/")
        self.assertIn(b"Welcome to the docs!", response.data)

    def test_path_traversal_blocked(self):
        response = self.client.get("/~../../../etc/")
        self.assertEqual(response.status_code, 404)


class FolderFeedTest(FolderTestCase):
    """Tests for per-folder feeds."""

    def test_folder_feed_rss_returns_200(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/feed.rss")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<rss", response.data)

    def test_folder_feed_atom_returns_200(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/feed.atom")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<feed", response.data)

    def test_folder_feed_includes_folder_articles(self):
        self._create_article("docs/guide.md", "# Guide\n\nA guide.")
        response = self.client.get("/~docs/feed.rss")
        self.assertIn(b"Guide", response.data)

    def test_folder_feed_excludes_subfolder_articles(self):
        self._create_article("docs/guide.md", "# Guide\n\nA guide.")
        self._create_article("docs/api/reference.md", "# API Reference\n\nAPI docs.")
        response = self.client.get("/~docs/feed.rss")
        self.assertIn(b"Guide", response.data)
        self.assertNotIn(b"API Reference", response.data)

    def test_folder_feed_404_for_nonexistent(self):
        response = self.client.get("/~nonexistent/feed.rss")
        self.assertEqual(response.status_code, 404)


class HomePageFolderTest(FolderTestCase):
    """Tests for home page folder listing."""

    def test_home_shows_folders(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/")
        self.assertIn(b"docs", response.data)

    def test_home_shows_root_articles_only(self):
        self._create_article("root-article.md", "# Root Article\n\nRoot content.")
        self._create_article("docs/nested.md", "# Nested\n\nNested content.")
        response = self.client.get("/")
        self.assertIn(b"Root Article", response.data)
        self.assertNotIn(b"Nested", response.data)

    def test_home_hides_hidden_folders(self):
        self._create_article(".hidden/secret.md")
        self._create_article("_private/internal.md")
        response = self.client.get("/")
        self.assertNotIn(b".hidden", response.data)
        self.assertNotIn(b"_private", response.data)


class BreadcrumbTest(FolderTestCase):
    """Tests for breadcrumb navigation."""

    def test_breadcrumbs_shown_in_folder(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/")
        self.assertIn(b"breadcrumbs", response.data)

    def test_breadcrumbs_include_home(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/")
        self.assertIn(b'href="/"', response.data)

    def test_nested_breadcrumbs(self):
        self._create_article("docs/api/reference.md")
        response = self.client.get("/~docs/api/")
        self.assertIn(b"/~docs/", response.data)


class ViewModeTest(FolderTestCase):
    """Tests for view mode inheritance in folders."""

    def test_folder_respects_view_mode_param(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/?view=list")
        self.assertIn(b"view-list", response.data)

    def test_folder_cards_view(self):
        self._create_article("docs/guide.md")
        response = self.client.get("/~docs/?view=cards")
        self.assertIn(b"view-cards", response.data)

    def test_folder_full_view(self):
        self._create_article("docs/guide.md", "# Guide\n\nFull content here.")
        response = self.client.get("/~docs/?view=full")
        self.assertIn(b"view-full", response.data)
