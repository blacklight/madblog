import os
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree


class FeedRouteTest(unittest.TestCase):
    def setUp(self):
        # Import inside setUp so tests are resilient to execution order.
        from madblog.app import app
        from madblog.config import config

        self.app = app
        self.config = config

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        markdown_dir = root / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)

        # Write a few posts.
        (markdown_dir / "post1.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post 1)",
                    "[//]: # (description: Desc 1)",
                    "[//]: # (image: /img/test.png)",
                    "[//]: # (published: 2025-02-10)",
                    "",
                    "# Hello",
                    "Body 1",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "post2.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post 2)",
                    "[//]: # (description: Desc 2)",
                    "[//]: # (published: 2025-02-11)",
                    "",
                    "# Hello",
                    "Body 2",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "post3.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post 3)",
                    "[//]: # (description: Desc 3)",
                    "[//]: # (published: 2025-02-12)",
                    "",
                    "# Hello",
                    "Body 3",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Point the app at the temp content.
        self.config.content_dir = str(root)
        self.config.link = "https://example.com"
        self.config.title = "Example"
        self.config.description = "Example feed"
        self.config.max_entries_per_feed = 2

        # Ensure app reads from our markdown directory.
        self.app.pages_dir = str(markdown_dir)

        # Tests shouldn't depend on webmentions.
        self.config.enable_webmentions = False

        self.client = self.app.test_client()

    def test_rss_feed_ok_and_limited(self):
        rsp = self.client.get("/feed.rss")
        self.assertEqual(rsp.status_code, 200)
        self.assertIn("application/rss+xml", rsp.content_type)

        root = ElementTree.fromstring(rsp.data)
        self.assertEqual(root.tag, "rss")

        channel = root.find("channel")
        self.assertIsNotNone(channel)
        items = channel.findall("item")
        self.assertEqual(len(items), 2)

    def test_atom_feed_ok_and_limited(self):
        rsp = self.client.get("/feed.atom")
        self.assertEqual(rsp.status_code, 200)
        self.assertIn("application/atom+xml", rsp.content_type)

        root = ElementTree.fromstring(rsp.data)
        self.assertTrue(root.tag.endswith("feed"))

        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        self.assertEqual(len(entries), 2)

    def test_short_feed_does_not_error(self):
        rsp = self.client.get("/feed.rss?short")
        self.assertEqual(rsp.status_code, 200)
        ElementTree.fromstring(rsp.data)


if __name__ == "__main__":
    unittest.main()
