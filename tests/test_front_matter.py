"""
Tests for YAML front matter support in Markdown metadata headers.
"""

import datetime
import tempfile
import unittest
from pathlib import Path

from madblog.markdown import (
    normalize_metadata,
    parse_metadata_header,
    split_front_matter,
)


class SplitFrontMatterTest(unittest.TestCase):
    """Test the low-level front matter block splitter."""

    def test_parses_yaml_block(self):
        metadata, lines = split_front_matter(
            ["---\n", 'title: "test"\n', "published: 2021-04-20\n", "---\n", "# T\n"]
        )
        self.assertEqual(metadata["title"], "test")
        self.assertEqual(metadata["published"], datetime.date(2021, 4, 20))
        self.assertEqual(lines, ["# T\n"])

    def test_returns_lines_unchanged_without_leading_delimiter(self):
        lines = ["# T\n", "---\n", "title: x\n", "---\n"]
        metadata, remaining = split_front_matter(lines)
        self.assertEqual(metadata, {})
        self.assertEqual(remaining, lines)

    def test_returns_lines_unchanged_without_closing_delimiter(self):
        lines = ["---\n", "title: x\n", "body\n"]
        metadata, remaining = split_front_matter(lines)
        self.assertEqual(metadata, {})
        self.assertEqual(remaining, lines)

    def test_non_metadata_block_is_not_consumed(self):
        """A ``---`` block that yields no metadata is left alone."""
        lines = ["---\n", "some random text\n", "---\n", "# T\n"]
        metadata, remaining = split_front_matter(lines)
        self.assertEqual(metadata, {})
        self.assertEqual(remaining, lines)

    def test_comment_metadata_inside_delimiters(self):
        """Comment headers wrapped in ``---`` still parse as front matter."""
        metadata, lines = split_front_matter(
            ["---\n", "[//]: # (title: Wrapped)\n", "---\n", "body\n"]
        )
        self.assertEqual(metadata, {"title": "Wrapped"})
        self.assertEqual(lines, ["body\n"])

    def test_empty_block_is_consumed(self):
        metadata, lines = split_front_matter(["---\n", "---\n", "body\n"])
        self.assertEqual(metadata, {})
        self.assertEqual(lines, ["body\n"])

    def test_invalid_yaml_falls_back_to_key_value(self):
        metadata, _ = split_front_matter(
            ["---\n", "title: foo: bar\n", "{invalid\n", "---\n", "body\n"]
        )
        self.assertEqual(metadata.get("title"), "foo: bar")


class NormalizeMetadataTest(unittest.TestCase):
    """Test normalization of YAML-parsed values to metadata strings."""

    def test_scalars(self):
        self.assertEqual(
            normalize_metadata({"title": "Hi", "draft": False, "n": 3}),
            {"title": "Hi", "draft": "False", "n": "3"},
        )

    def test_dates(self):
        normalized = normalize_metadata(
            {
                "published": datetime.datetime(
                    2021, 4, 20, 12, 21, tzinfo=datetime.timezone.utc
                ),
                "date": datetime.date(2021, 4, 20),
            }
        )
        self.assertEqual(normalized["published"], "2021-04-20T12:21:00+00:00")
        self.assertEqual(normalized["date"], "2021-04-20")

    def test_lists_joined_with_commas(self):
        self.assertEqual(
            normalize_metadata({"tags": ["python", "webdev"]}),
            {"tags": "python, webdev"},
        )

    def test_none_becomes_empty_string(self):
        self.assertEqual(normalize_metadata({"key": None}), {"key": ""})


class ParseMetadataHeaderTest(unittest.TestCase):
    """Test ``parse_metadata_header`` with both supported syntaxes."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.dir = Path(self._tmpdir.name)

    def _write(self, text: str) -> str:
        path = self.dir / "post.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_front_matter(self):
        metadata = parse_metadata_header(
            self._write(
                "---\n"
                'title: "My Post"\n'
                "description: A description\n"
                "published: 2021-04-20T12:21:00+09:00\n"
                "---\n"
                "\n"
                "# My Post\n"
            )
        )
        self.assertEqual(metadata["title"], "My Post")
        self.assertEqual(metadata["description"], "A description")
        self.assertEqual(metadata["published"], "2021-04-20T12:21:00+09:00")

    def test_comment_headers(self):
        metadata = parse_metadata_header(
            self._write("[//]: # (title: Hello)\n\n# Hello\n\nBody.\n")
        )
        self.assertEqual(metadata["title"], "Hello")

    def test_front_matter_with_yaml_list(self):
        metadata = parse_metadata_header(
            self._write("---\ntags: [python, webdev]\n---\n\nBody.\n")
        )
        self.assertEqual(metadata["tags"], "python, webdev")

    def test_front_matter_and_comment_headers_merge(self):
        """Comment headers after front matter are merged (and take precedence)."""
        metadata = parse_metadata_header(
            self._write(
                "---\ntitle: FM Title\n---\n[//]: # (description: Desc)\n\nBody.\n"
            )
        )
        self.assertEqual(metadata["title"], "FM Title")
        self.assertEqual(metadata["description"], "Desc")

    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(parse_metadata_header(str(self.dir / "missing.md")), {})


class FrontMatterRouteTest(unittest.TestCase):
    """Test that pages with front matter render correctly."""

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

        (markdown_dir / "fm-post.md").write_text(
            "\n".join(
                [
                    "---",
                    'title: "Front Matter Post"',
                    "description: A post using front matter",
                    "published: 2025-07-01",
                    'tags: "#python, #madblog"',
                    "---",
                    "",
                    "# Front Matter Post",
                    "",
                    "Body content here.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (markdown_dir / "fm-inferred-title.md").write_text(
            "\n".join(
                [
                    "---",
                    "published: 2025-07-02",
                    "---",
                    "",
                    "# Inferred Heading",
                    "",
                    "Body.",
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

    def test_article_renders_with_front_matter(self):
        with self.app.test_client() as client:
            resp = client.get("/article/fm-post")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn("Body content here.", html)
            self.assertIn("Front Matter Post", html)

    def test_front_matter_not_rendered_in_body(self):
        """Front matter keys/delimiters must not leak into the HTML."""
        with self.app.test_client() as client:
            resp = client.get("/article/fm-post")
            html = resp.get_data(as_text=True)
            self.assertNotIn("published: 2025-07-01", html)
            self.assertNotIn("tags:", html)

    def test_title_inferred_from_heading(self):
        metadata = self.app._parse_page_metadata("fm-inferred-title")
        self.assertEqual(metadata["title"], "Inferred Heading")

    def test_published_parsed_as_datetime(self):
        metadata = self.app._parse_page_metadata("fm-post")
        self.assertIsInstance(metadata["published"], datetime.datetime)
        self.assertEqual(metadata["published"].year, 2025)

    def test_tags_from_front_matter(self):
        metadata = self.app._parse_page_metadata("fm-post")
        self.assertEqual(metadata["tags"], "#python, #madblog")


class FrontMatterTagIndexTest(unittest.TestCase):
    """Test that the tag index picks up front matter metadata."""

    def setUp(self):
        from madblog.config import config

        self.config = config
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.markdown_dir = root / "markdown"
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = root / "mentions"
        self.mentions_dir.mkdir(parents=True, exist_ok=True)
        self.root = root

        self._old_content_dir = config.content_dir
        config.content_dir = str(root)
        self.addCleanup(self._restore_config)

    def _restore_config(self):
        self.config.content_dir = self._old_content_dir

    def _build_index(self):
        from madblog.tags import TagIndex

        index = TagIndex(
            content_dir=str(self.root),
            pages_dir=str(self.markdown_dir),
            mentions_dir=str(self.mentions_dir),
        )
        index.build()
        return index

    def test_tags_from_front_matter_list(self):
        (self.markdown_dir / "fm.md").write_text(
            "---\ntitle: FM Post\ntags: [python, fediverse]\n---\n\n# FM\n\nBody.\n",
            encoding="utf-8",
        )
        index = self._build_index()
        tag_names = [t[0] for t in index.get_all_tags()]
        self.assertIn("python", tag_names)
        self.assertIn("fediverse", tag_names)

    def test_front_matter_not_indexed_as_body(self):
        """Front matter content must not leak hashtag-looking keys into the body index."""
        (self.markdown_dir / "fm.md").write_text(
            "---\ntitle: FM Post\ntags: [python]\n---\n\n# FM\n\nBody text.\n",
            encoding="utf-8",
        )
        index = self._build_index()
        post = index.get_posts_for_tag("python")[0]
        self.assertEqual(post["title"], "FM Post")
        # Only the metadata tag — no stray tags from front matter lines
        self.assertEqual(post["score"], 5.0)


class FrontMatterReplyIndexTest(unittest.TestCase):
    """Test that ReplyMetadataIndex extracts front matter metadata."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.replies_dir = root / "replies"
        self.replies_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = root / ".madblog"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _index(self):
        from madblog.replies import ReplyMetadataIndex

        return ReplyMetadataIndex(self.replies_dir, self.state_dir)

    def test_extract_front_matter_metadata(self):
        md_file = self.replies_dir / "reply.md"
        md_file.write_text(
            "---\n"
            "reply-to: https://example.com/post/123\n"
            "visibility: public\n"
            "published: 2025-03-26T10:00:00+00:00\n"
            "---\n"
            "\n"
            "# Heading\n"
            "\n"
            "This is the content.\n",
            encoding="utf-8",
        )

        entry = self._index()._extract_metadata(str(md_file))

        self.assertIsNotNone(entry)
        self.assertEqual(entry.reply_to, "https://example.com/post/123")
        self.assertEqual(entry.visibility, "public")
        self.assertEqual(entry.published, "2025-03-26T10:00:00+00:00")
        self.assertEqual(entry.title, "Heading")
        self.assertTrue(entry.has_content)

    def test_extract_front_matter_only_metadata_no_content(self):
        md_file = self.replies_dir / "like.md"
        md_file.write_text(
            "---\nlike-of: https://example.com/post/456\n---\n",
            encoding="utf-8",
        )

        entry = self._index()._extract_metadata(str(md_file))

        self.assertIsNotNone(entry)
        self.assertEqual(entry.like_of, "https://example.com/post/456")
        self.assertFalse(entry.has_content)


class FrontMatterActivityPubTest(unittest.TestCase):
    """Test that ActivityPub content cleaning strips front matter."""

    def test_clean_content_strips_front_matter(self):
        from madblog.activitypub._integration import ActivityPubIntegration

        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                "---\ntitle: FM Post\npublished: 2025-01-01\n---\n\n# FM Post\n\nBody.\n"
            )
            path = f.name

        self.addCleanup(Path(path).unlink)
        cleaned = ActivityPubIntegration._clean_content(path)
        self.assertNotIn("title:", cleaned)
        self.assertNotIn("---", cleaned)
        self.assertIn("Body.", cleaned)
