import json
import tempfile
import time
import unittest
from pathlib import Path

from madblog.tags import TagIndex, extract_hashtags, normalize_tag, parse_metadata_tags


class TagParsingTest(unittest.TestCase):
    """Test the low-level tag extraction and normalization utilities."""

    def test_normalize_tag(self):
        self.assertEqual(normalize_tag("#Foo"), "foo")
        self.assertEqual(normalize_tag("Foo"), "foo")
        self.assertEqual(normalize_tag("#foo_bar"), "foo_bar")
        self.assertEqual(
            normalize_tag("##double"), "double"
        )  # lstrip strips all leading #

    def test_parse_metadata_tags(self):
        self.assertEqual(
            parse_metadata_tags("#tag1, #tag2, tag3"), ["tag1", "tag2", "tag3"]
        )
        self.assertEqual(parse_metadata_tags(""), [])
        self.assertEqual(parse_metadata_tags("#A, ,, #B"), ["a", "b"])

    def test_extract_hashtags_basic(self):
        counts = extract_hashtags("Hello #world, this is #Python and #world again.")
        self.assertEqual(counts["world"], 2)
        self.assertEqual(counts["python"], 1)

    def test_extract_hashtags_skips_fenced_code(self):
        text = (
            "Before #visible\n"
            "```\n"
            "#hidden_in_code\n"
            "```\n"
            "After #also_visible\n"
        )
        counts = extract_hashtags(text)
        self.assertIn("visible", counts)
        self.assertIn("also_visible", counts)
        self.assertNotIn("hidden_in_code", counts)

    def test_extract_hashtags_skips_inline_code(self):
        text = "Use `#not_a_tag` but #real_tag is fine."
        counts = extract_hashtags(text)
        self.assertNotIn("not_a_tag", counts)
        self.assertIn("real_tag", counts)

    def test_extract_hashtags_skips_mermaid_block(self):
        text = (
            "```mermaid\n"
            "graph LR\n"
            "    A --> #mermaid_tag\n"
            "```\n"
            "#outside_tag\n"
        )
        counts = extract_hashtags(text)
        self.assertNotIn("mermaid_tag", counts)
        self.assertIn("outside_tag", counts)

    def test_extract_hashtags_skips_url_fragments(self):
        """Hashtags in URLs should not be parsed as tags."""
        text = (
            "Check out [this link](https://example.com/page#section) for more info.\n"
            "Also see [another page](http://test.com/docs.html#tests) about #testing.\n"
            "* [Hey](https://pluralistic.net/2025/06/28/mamdani/#linkdump): Delights.\n"
            "Regular #hashtag should still work.\n"
        )
        counts = extract_hashtags(text)

        # Should extract legitimate hashtags
        self.assertIn("testing", counts)
        self.assertIn("hashtag", counts)

        # Should NOT extract URL fragments as hashtags
        self.assertNotIn("section", counts)
        self.assertNotIn("tests", counts)
        self.assertNotIn("linkdump", counts)

        self.assertEqual(dict(counts), {"testing": 1, "hashtag": 1})

    def test_extract_hashtags_no_match_mid_word(self):
        text = "foo#bar is not a tag, but #baz is."
        counts = extract_hashtags(text)
        self.assertNotIn("bar", counts)
        self.assertIn("baz", counts)


class TagPreprocessorTest(unittest.TestCase):
    """Test the Markdown preprocessor that linkifies body hashtags."""

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

        self.config.content_dir = str(root)
        self.config.link = "https://example.com"
        self.config.title = "Example"
        self.config.description = "Example blog"
        self.app.pages_dir = markdown_dir
        self.config.enable_webmentions = False
        self.client = self.app.test_client()

    def test_body_tag_linkified(self):
        md_dir = Path(self.app.pages_dir)
        (md_dir / "tag-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Tag Post)",
                    "[//]: # (published: 2025-03-01)",
                    "",
                    "# Tag Post",
                    "",
                    "This is a #python post.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rsp = self.client.get("/article/tag-post")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")
        self.assertIn('href="/tags/python"', html)
        self.assertIn("#python", html)

    def test_code_block_tag_not_linkified(self):
        md_dir = Path(self.app.pages_dir)
        (md_dir / "code-tag-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Code Tag Post)",
                    "[//]: # (published: 2025-03-01)",
                    "",
                    "# Code Tag Post",
                    "",
                    "```",
                    "#not_a_tag",
                    "```",
                    "",
                    "But #real_tag is.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rsp = self.client.get("/article/code-tag-post")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")
        self.assertNotIn('href="/tags/not_a_tag"', html)
        self.assertIn('href="/tags/real_tag"', html)

    def test_inline_code_tag_not_linkified(self):
        md_dir = Path(self.app.pages_dir)
        (md_dir / "inline-code-tag.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Inline Code Tag)",
                    "[//]: # (published: 2025-03-01)",
                    "",
                    "# Inline Code Tag",
                    "",
                    "Use `#hidden` but #shown is fine.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rsp = self.client.get("/article/inline-code-tag")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")
        self.assertNotIn('href="/tags/hidden"', html)
        self.assertIn('href="/tags/shown"', html)

    def test_url_fragments_not_linkified(self):
        """Hashtags in URLs should not be linkified as tags."""
        md_dir = Path(self.app.pages_dir)
        (md_dir / "url-fragment-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: URL Fragment Test)",
                    "[//]: # (published: 2025-03-01)",
                    "",
                    "# URL Fragment Test",
                    "",
                    "Check out [this link](https://example.com/page#section) for more info.",
                    "Also see [another page](http://test.com/docs.html#tests) about #testing.",
                    "* [Hey](https://pluralistic.net/2025/06/28/mamdani/#linkdump): Delights.",
                    "Regular #hashtag should still work.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rsp = self.client.get("/article/url-fragment-post")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")

        # Should linkify legitimate hashtags
        self.assertIn('href="/tags/testing"', html)
        self.assertIn('href="/tags/hashtag"', html)

        # Should NOT linkify URL fragments
        self.assertNotIn('href="/tags/section"', html)
        self.assertNotIn('href="/tags/tests"', html)
        self.assertNotIn('href="/tags/linkdump"', html)

        # URLs should remain intact
        self.assertIn('href="https://example.com/page#section"', html)
        self.assertIn('href="http://test.com/docs.html#tests"', html)

    def test_metadata_tags_in_header(self):
        md_dir = Path(self.app.pages_dir)
        (md_dir / "meta-tags-post.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Meta Tags Post)",
                    "[//]: # (tags: #alpha, #beta)",
                    "[//]: # (published: 2025-03-01)",
                    "",
                    "# Meta Tags Post",
                    "",
                    "Content here.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        rsp = self.client.get("/article/meta-tags-post")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")
        self.assertIn('href="/tags/alpha"', html)
        self.assertIn('href="/tags/beta"', html)


class TagRoutesTest(unittest.TestCase):
    """Test /tags and /tags/<tag> routes."""

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
        mentions_dir = root / "mentions"
        mentions_dir.mkdir(parents=True, exist_ok=True)

        self.config.content_dir = str(root)
        self.config.link = "https://example.com"
        self.config.title = "Example"
        self.config.description = "Example blog"
        self.app.pages_dir = markdown_dir
        self.app.mentions_dir = mentions_dir
        self.config.enable_webmentions = False
        self.client = self.app.test_client()

        # Create posts with tags
        (markdown_dir / "post1.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post One)",
                    "[//]: # (description: A post about #python)",
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

        # Build the tag index
        self.app.tag_index = TagIndex(
            content_dir=str(root),
            pages_dir=str(markdown_dir),
            mentions_dir=str(mentions_dir),
        )
        self.app.tag_index.build()

    def test_tags_route_returns_200(self):
        rsp = self.client.get("/tags")
        self.assertEqual(rsp.status_code, 200)

    def test_tags_route_lists_tags(self):
        rsp = self.client.get("/tags")
        html = rsp.data.decode("utf-8")
        self.assertIn("#python", html)
        self.assertIn("#coding", html)
        self.assertIn("#rust", html)

    def test_tag_posts_route_returns_200(self):
        rsp = self.client.get("/tags/python")
        self.assertEqual(rsp.status_code, 200)

    def test_tag_posts_route_with_hash_prefix(self):
        """Tag matching should work with or without # prefix."""
        rsp = self.client.get("/tags/%23python")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")
        self.assertIn("Post One", html)

    def test_tag_posts_case_insensitive(self):
        rsp = self.client.get("/tags/Python")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")
        self.assertIn("Post One", html)

    def test_tag_posts_route_lists_matching_posts(self):
        rsp = self.client.get("/tags/python")
        html = rsp.data.decode("utf-8")
        self.assertIn("Post One", html)
        self.assertIn("Post Two", html)
        self.assertNotIn("Post Three", html)

    def test_tag_posts_route_nonexistent_tag(self):
        rsp = self.client.get("/tags/nonexistent")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")
        self.assertIn("No posts found", html)

    def test_tags_route_no_cache(self):
        rsp = self.client.get("/tags")
        self.assertEqual(rsp.headers.get("Cache-Control"), "no-store")

    def test_tag_posts_route_no_cache(self):
        rsp = self.client.get("/tags/python")
        self.assertEqual(rsp.headers.get("Cache-Control"), "no-store")

    def test_semantic_tag_links_in_article_head(self):
        """Test that article pages include semantic link rel="tag" elements."""
        # Set up some categories in config
        self.config.categories = ["Technology", "Programming"]

        rsp = self.client.get("/article/post1")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")

        # Should include category links
        self.assertIn('<link rel="tag" href="/tags/technology"', html)
        self.assertIn('<link rel="tag" href="/tags/programming"', html)

        # Should include article tags
        self.assertIn('<link rel="tag" href="/tags/python"', html)
        self.assertIn('<link rel="tag" href="/tags/coding"', html)

    def test_semantic_category_links_on_home_page(self):
        """Test that home page includes semantic link rel="tag" elements for categories."""
        # Set up some categories in config
        self.config.categories = ["Technology", "Programming"]

        rsp = self.client.get("/")
        self.assertEqual(rsp.status_code, 200)
        html = rsp.data.decode("utf-8")

        # Should include category links on home page
        self.assertIn('<link rel="tag" href="/tags/technology"', html)
        self.assertIn('<link rel="tag" href="/tags/programming"', html)


class TagRankingTest(unittest.TestCase):
    """Test that posts are ranked by the scoring formula."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.markdown_dir = root / "markdown"
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = root / "mentions"
        self.mentions_dir.mkdir(parents=True, exist_ok=True)

        # Post A: meta(5) + title(10) + body(1) = 16
        (self.markdown_dir / "post_a.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: #testing is great)",
                    "[//]: # (tags: #testing)",
                    "[//]: # (published: 2025-01-01)",
                    "",
                    "# #testing is great",
                    "",
                    "This is about #testing.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Post B: desc(5) + body(1) = 6
        (self.markdown_dir / "post_b.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post B)",
                    "[//]: # (description: A #testing description)",
                    "[//]: # (published: 2025-01-02)",
                    "",
                    "# Post B",
                    "",
                    "We do #testing here.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Post C: body only (1)
        (self.markdown_dir / "post_c.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post C)",
                    "[//]: # (published: 2025-01-03)",
                    "",
                    "# Post C",
                    "",
                    "Mentions #testing once.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Post D: meta tag only (5), no body/title/desc match
        (self.markdown_dir / "post_d.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Post D)",
                    "[//]: # (tags: #testing)",
                    "[//]: # (published: 2025-01-04)",
                    "",
                    "# Post D",
                    "",
                    "No hashtags in body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self.tag_index = TagIndex(
            content_dir=str(root),
            pages_dir=str(self.markdown_dir),
            mentions_dir=str(self.mentions_dir),
        )
        self.tag_index.build()

    def test_ranking_order(self):
        posts = self.tag_index.get_posts_for_tag("testing")
        self.assertEqual(len(posts), 4)
        # Post A first (meta=5 + title=10 + body=1 = 16)
        self.assertEqual(posts[0]["path"], "post_a.md")
        # Post B second (desc=5 + body=1 = 6)
        self.assertEqual(posts[1]["path"], "post_b.md")
        # Post D third (meta=5 only)
        self.assertEqual(posts[2]["path"], "post_d.md")
        # Post C last (body=1)
        self.assertEqual(posts[3]["path"], "post_c.md")

    def test_scores_are_correct(self):
        posts = self.tag_index.get_posts_for_tag("testing")
        scores = {p["path"]: p["score"] for p in posts}
        self.assertEqual(scores["post_a.md"], 16.0)  # meta(5) + title(10) + body(1)
        self.assertEqual(scores["post_b.md"], 6.0)  # desc(5) + body(1)
        self.assertEqual(scores["post_d.md"], 5.0)  # meta(5) only
        self.assertEqual(scores["post_c.md"], 1.0)  # body(1) only


class TagCacheTest(unittest.TestCase):
    """Test that the tag index persists to disk and reloads correctly."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.markdown_dir = root / "markdown"
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = root / "mentions"
        self.mentions_dir.mkdir(parents=True, exist_ok=True)
        self.root = root

        (self.markdown_dir / "cached.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Cached Post)",
                    "[//]: # (tags: #cached)",
                    "[//]: # (published: 2025-03-01)",
                    "",
                    "# Cached Post",
                    "",
                    "Body with #cached tag.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def test_index_persists_and_reloads(self):
        # Build and save
        idx1 = TagIndex(
            content_dir=str(self.root),
            pages_dir=str(self.markdown_dir),
            mentions_dir=str(self.mentions_dir),
        )
        idx1.build()

        tags1 = idx1.get_all_tags()
        self.assertTrue(any(t[0] == "cached" for t in tags1))

        # Verify the index file exists
        index_path = self.root / ".madblog" / "cache" / "tags-index.json"
        self.assertTrue(index_path.exists())

        # Create a new TagIndex instance (simulating restart) and verify it loads from disk
        idx2 = TagIndex(
            content_dir=str(self.root),
            pages_dir=str(self.markdown_dir),
            mentions_dir=str(self.mentions_dir),
        )
        tags2 = idx2.get_all_tags()
        self.assertTrue(any(t[0] == "cached" for t in tags2))

    def test_reindex_on_file_change(self):
        idx = TagIndex(
            content_dir=str(self.root),
            pages_dir=str(self.markdown_dir),
            mentions_dir=str(self.mentions_dir),
        )
        idx.build()

        # Initially only #cached
        tags = idx.get_all_tags()
        tag_names = [t[0] for t in tags]
        self.assertIn("cached", tag_names)
        self.assertNotIn("newtag", tag_names)

        # Add a new file
        (self.markdown_dir / "new.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: New Post)",
                    "[//]: # (tags: #newtag)",
                    "[//]: # (published: 2025-03-02)",
                    "",
                    "# New Post",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        idx.reindex_file(str(self.markdown_dir / "new.md"))
        tags = idx.get_all_tags()
        tag_names = [t[0] for t in tags]
        self.assertIn("newtag", tag_names)


class TagIncrementalBuildTest(unittest.TestCase):
    """Test that build() skips files older than the last index time."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        root = Path(self._tmpdir.name)
        self.markdown_dir = root / "markdown"
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        self.mentions_dir = root / "mentions"
        self.mentions_dir.mkdir(parents=True, exist_ok=True)
        self.root = root

        (self.markdown_dir / "old.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: Old Post)",
                    "[//]: # (tags: #oldtag)",
                    "[//]: # (published: 2025-01-01)",
                    "",
                    "# Old Post",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def test_build_skips_unchanged_files(self):
        idx = TagIndex(
            content_dir=str(self.root),
            pages_dir=str(self.markdown_dir),
            mentions_dir=str(self.mentions_dir),
        )
        idx.build()

        # Verify the index was written with last_indexed_at
        index_path = self.root / ".madblog" / "cache" / "tags-index.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertIn("last_indexed_at", data)
        self.assertGreater(data["last_indexed_at"], 0)

        old_indexed_at = data["last_indexed_at"]

        # Wait briefly so the new file gets a newer mtime
        time.sleep(0.05)

        # Add a new file
        (self.markdown_dir / "new.md").write_text(
            "\n".join(
                [
                    "[//]: # (title: New Post)",
                    "[//]: # (tags: #newtag)",
                    "[//]: # (published: 2025-02-01)",
                    "",
                    "# New Post",
                    "",
                    "Body.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Rebuild — old.md should be skipped (reused from index),
        # new.md should be re-indexed
        idx2 = TagIndex(
            content_dir=str(self.root),
            pages_dir=str(self.markdown_dir),
            mentions_dir=str(self.mentions_dir),
        )
        idx2.build()

        tags = idx2.get_all_tags()
        tag_names = [t[0] for t in tags]
        self.assertIn("oldtag", tag_names)
        self.assertIn("newtag", tag_names)

        # Verify the new index has a more recent last_indexed_at
        data2 = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertGreater(data2["last_indexed_at"], old_indexed_at)


if __name__ == "__main__":
    unittest.main()
