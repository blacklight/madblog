"""
Tests for the Mastodon-compatible API endpoints in Madblog.

Covers:
- Pubby-provided endpoints wired via bind_mastodon_api
- Madblog-specific endpoints: GET /api/v1/tags/:tag, GET /api/v2/search
"""

import tempfile
import unittest
from pathlib import Path

from madblog.app import app
from madblog.config import config
from madblog.tags import TagIndex


class MastodonAPITestBase(unittest.TestCase):
    """Shared setup for Mastodon API tests."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)
        mentions_dir = root / "mentions"
        mentions_dir.mkdir(parents=True, exist_ok=True)

        config.content_dir = str(root)
        config.link = "https://example.com"
        config.title = "Test Blog"
        config.description = "A test blog"
        config.enable_webmentions = False
        app.pages_dir = markdown_dir
        app.mentions_dir = mentions_dir

        # Create sample posts with tags
        (markdown_dir / "post1.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post One)",
                    "[//]: # (description: A post about python)",
                    "[//]: # (tags: #python, #coding)",
                    "[//]: # (published: 2025-03-01)",
                    "",
                    "# Post One",
                    "",
                    "This is about #python and #coding.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "post2.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post Two)",
                    "[//]: # (tags: #python)",
                    "[//]: # (published: 2025-03-02)",
                    "",
                    "# Post Two",
                    "",
                    "More #python content here.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "post3.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post Three)",
                    "[//]: # (tags: #rust)",
                    "[//]: # (published: 2025-03-03)",
                    "",
                    "# Post Three",
                    "",
                    "Some #rust content.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Build tag index
        app.tag_index = TagIndex(
            content_dir=str(root),
            pages_dir=str(markdown_dir),
            mentions_dir=str(mentions_dir),
        )
        app.tag_index.build()

        self.client = app.test_client()


class TestMastodonTagEndpoint(MastodonAPITestBase):
    """Tests for GET /api/v1/tags/:tag."""

    def test_existing_tag_returns_200(self):
        rsp = self.client.get("/api/v1/tags/python")
        self.assertEqual(rsp.status_code, 200)

    def test_existing_tag_json_shape(self):
        rsp = self.client.get("/api/v1/tags/python")
        data = rsp.get_json()
        self.assertEqual(data["name"], "python")
        self.assertIn("/tags/python", data["url"])
        self.assertIsInstance(data["history"], list)
        self.assertEqual(len(data["history"]), 7)
        self.assertFalse(data["following"])

    def test_tag_history_entries_shape(self):
        rsp = self.client.get("/api/v1/tags/python")
        data = rsp.get_json()
        entry = data["history"][0]
        self.assertIn("day", entry)
        self.assertIn("uses", entry)
        self.assertIn("accounts", entry)
        # day is a unix timestamp string
        self.assertTrue(entry["day"].isdigit())

    def test_nonexistent_tag_returns_404(self):
        rsp = self.client.get("/api/v1/tags/nonexistent")
        self.assertEqual(rsp.status_code, 404)

    def test_tag_case_insensitive(self):
        rsp = self.client.get("/api/v1/tags/Python")
        self.assertEqual(rsp.status_code, 200)
        data = rsp.get_json()
        self.assertEqual(data["name"], "python")

    def test_tag_with_hash_prefix(self):
        rsp = self.client.get("/api/v1/tags/%23python")
        self.assertEqual(rsp.status_code, 200)
        data = rsp.get_json()
        self.assertEqual(data["name"], "python")


class TestMastodonSearchEndpoint(MastodonAPITestBase):
    """Tests for GET /api/v2/search."""

    def test_empty_query_returns_empty(self):
        rsp = self.client.get("/api/v2/search")
        self.assertEqual(rsp.status_code, 200)
        data = rsp.get_json()
        self.assertEqual(data["accounts"], [])
        self.assertEqual(data["statuses"], [])
        self.assertEqual(data["hashtags"], [])

    def test_search_hashtags(self):
        rsp = self.client.get("/api/v2/search?q=python&type=hashtags")
        self.assertEqual(rsp.status_code, 200)
        data = rsp.get_json()
        self.assertTrue(len(data["hashtags"]) >= 1)
        names = [h["name"] for h in data["hashtags"]]
        self.assertIn("python", names)

    def test_search_hashtags_prefix(self):
        rsp = self.client.get("/api/v2/search?q=py&type=hashtags")
        self.assertEqual(rsp.status_code, 200)
        data = rsp.get_json()
        names = [h["name"] for h in data["hashtags"]]
        self.assertIn("python", names)

    def test_search_hashtags_no_match(self):
        rsp = self.client.get("/api/v2/search?q=zzzzz&type=hashtags")
        self.assertEqual(rsp.status_code, 200)
        data = rsp.get_json()
        self.assertEqual(data["hashtags"], [])

    def test_search_hashtag_shape(self):
        rsp = self.client.get("/api/v2/search?q=python&type=hashtags")
        data = rsp.get_json()
        tag = data["hashtags"][0]
        self.assertIn("name", tag)
        self.assertIn("url", tag)
        self.assertIn("history", tag)

    def test_search_all_types(self):
        """Without type param, all three result types are present."""
        rsp = self.client.get("/api/v2/search?q=python")
        self.assertEqual(rsp.status_code, 200)
        data = rsp.get_json()
        self.assertIn("accounts", data)
        self.assertIn("statuses", data)
        self.assertIn("hashtags", data)

    def test_search_limit(self):
        rsp = self.client.get("/api/v2/search?q=p&type=hashtags&limit=1")
        data = rsp.get_json()
        self.assertTrue(len(data["hashtags"]) <= 1)


if __name__ == "__main__":
    unittest.main()
