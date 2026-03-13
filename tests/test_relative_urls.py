"""
Tests for relative URL resolution in markdown content.
"""

import unittest

from madblog.markdown import resolve_relative_urls


class TestResolveRelativeUrls(unittest.TestCase):
    """Test the resolve_relative_urls function."""

    def test_markdown_link_relative_path(self):
        """Relative markdown links should be resolved to absolute URLs."""
        md = "Check out [this article](/article/a1) for more info."
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(
            result,
            "Check out [this article](https://example.com/article/a1) for more info.",
        )

    def test_markdown_link_nested_path(self):
        """Nested relative paths should be resolved correctly."""
        md = "See [docs](/docs/api/v1/endpoints)."
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(
            result, "See [docs](https://example.com/docs/api/v1/endpoints)."
        )

    def test_markdown_link_absolute_url_unchanged(self):
        """Absolute URLs should not be modified."""
        md = "Visit [Google](https://google.com) for search."
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(result, "Visit [Google](https://google.com) for search.")

    def test_markdown_link_protocol_relative_unchanged(self):
        """Protocol-relative URLs (//...) should not be modified."""
        md = "Use [CDN](//cdn.example.com/file.js)."
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(result, "Use [CDN](//cdn.example.com/file.js).")

    def test_markdown_image_relative_path(self):
        """Relative markdown images should be resolved to absolute URLs."""
        md = "Here is an image: ![alt](/img/photo.png)"
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(
            result, "Here is an image: ![alt](https://example.com/img/photo.png)"
        )

    def test_markdown_image_absolute_url_unchanged(self):
        """Absolute image URLs should not be modified."""
        md = "![logo](https://other.com/logo.png)"
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(result, "![logo](https://other.com/logo.png)")

    def test_html_href_relative_path(self):
        """Relative HTML href attributes should be resolved."""
        md = '<a href="/about">About</a>'
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(result, '<a href="https://example.com/about">About</a>')

    def test_html_src_relative_path(self):
        """Relative HTML src attributes should be resolved."""
        md = '<img src="/img/banner.jpg">'
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(result, '<img src="https://example.com/img/banner.jpg">')

    def test_html_href_absolute_unchanged(self):
        """Absolute HTML href should not be modified."""
        md = '<a href="https://other.com/page">Link</a>'
        result = resolve_relative_urls(md, "https://example.com")
        self.assertEqual(result, '<a href="https://other.com/page">Link</a>')

    def test_multiple_links_mixed(self):
        """Multiple links with mixed relative and absolute URLs."""
        md = (
            "See [local](/local) and [external](https://ext.com/page), "
            "plus ![img](/img/a.png) and ![ext](https://ext.com/b.png)."
        )
        result = resolve_relative_urls(md, "https://example.com")
        expected = (
            "See [local](https://example.com/local) and [external](https://ext.com/page), "
            "plus ![img](https://example.com/img/a.png) and ![ext](https://ext.com/b.png)."
        )
        self.assertEqual(result, expected)

    def test_base_url_with_trailing_slash(self):
        """Base URL with trailing slash should work correctly."""
        md = "Link to [page](/page)."
        result = resolve_relative_urls(md, "https://example.com/")
        self.assertEqual(result, "Link to [page](https://example.com/page).")

    def test_empty_base_url(self):
        """Empty base URL should return content unchanged."""
        md = "Link to [page](/page)."
        result = resolve_relative_urls(md, "")
        self.assertEqual(result, "Link to [page](/page).")

    def test_none_like_base_url(self):
        """None-like base URL should return content unchanged."""
        md = "Link to [page](/page)."
        result = resolve_relative_urls(md, None)  # type: ignore
        self.assertEqual(result, "Link to [page](/page).")

    def test_link_with_title(self):
        """Markdown links with titles should be handled (title may be stripped)."""
        md = '[link](/path "Title")'
        result = resolve_relative_urls(md, "https://example.com")
        # The function extracts just the URL part, title handling is best-effort
        self.assertIn("https://example.com/path", result)

    def test_complex_document(self):
        """Test a complex markdown document with various URL types."""
        md = """# Article

This is a [local link](/article/a1) and here is an [external link](https://ext.com).

![Local image](/img/photo.png)

<a href="/about">About page</a>

Some code: `[not a link](/fake)`
"""
        result = resolve_relative_urls(md, "https://example.com")

        self.assertIn("[local link](https://example.com/article/a1)", result)
        self.assertIn("[external link](https://ext.com)", result)
        self.assertIn("![Local image](https://example.com/img/photo.png)", result)
        self.assertIn('href="https://example.com/about"', result)


class TestResolveRelativeUrlsWithCurrentUri(unittest.TestCase):
    """Test resolve_relative_urls with current_uri for Obsidian-style links."""

    def test_dot_slash_relative_link(self):
        """./path links should resolve relative to current directory."""
        md = "See [other post](./other-post) for details."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(
            result,
            "See [other post](https://example.com/article/2025/other-post) for details.",
        )

    def test_bare_relative_link(self):
        """Bare relative paths should resolve relative to current directory."""
        md = "See [other post](other-post) for details."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(
            result,
            "See [other post](https://example.com/article/2025/other-post) for details.",
        )

    def test_parent_directory_link(self):
        """../ paths should resolve to parent directory."""
        md = "See [parent dir](../other-dir/post) for details."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(
            result,
            "See [parent dir](https://example.com/article/other-dir/post) for details.",
        )

    def test_multiple_parent_directories(self):
        """Multiple ../ should resolve correctly."""
        md = "See [post](../../other-year/post) for details."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/01/my-post"
        )
        self.assertEqual(
            result,
            "See [post](https://example.com/article/other-year/post) for details.",
        )

    def test_directory_traversal_prevention(self):
        """../ should not go above base_path (/article)."""
        md = "See [escape](../../../../etc/passwd) for details."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        # Should be clamped to /article/passwd, not /etc/passwd
        self.assertTrue(result.startswith("See [escape](https://example.com/article/"))
        self.assertNotIn("/etc/", result)

    def test_directory_traversal_with_custom_base_path(self):
        """../ should respect custom base_path."""
        md = "See [link](../../other) for details."
        result = resolve_relative_urls(
            md, "https://example.com", "/reply/article-slug/reply-id", "/reply"
        )
        # Should be clamped to /reply/other
        self.assertTrue(result.startswith("See [link](https://example.com/reply/"))

    def test_no_current_uri_bare_path_unchanged(self):
        """Bare paths without current_uri should remain unchanged."""
        md = "See [link](other-post) for details."
        result = resolve_relative_urls(md, "https://example.com", "")
        self.assertEqual(result, "See [link](other-post) for details.")

    def test_dot_slash_image(self):
        """./path images should resolve correctly."""
        md = "![photo](./images/photo.png)"
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(
            result, "![photo](https://example.com/article/2025/images/photo.png)"
        )

    def test_bare_relative_image(self):
        """Bare relative image paths should resolve correctly."""
        md = "![photo](photo.png)"
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(result, "![photo](https://example.com/article/2025/photo.png)")

    def test_html_bare_relative_href(self):
        """Bare relative HTML href should resolve correctly."""
        md = '<a href="other-page">Link</a>'
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(
            result, '<a href="https://example.com/article/2025/other-page">Link</a>'
        )

    def test_html_dot_slash_href(self):
        """./path HTML href should resolve correctly."""
        md = '<a href="./other-page">Link</a>'
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(
            result, '<a href="https://example.com/article/2025/other-page">Link</a>'
        )

    def test_special_protocols_unchanged(self):
        """mailto:, tel:, etc. should not be treated as relative paths."""
        md = "Email [us](mailto:test@example.com) or call [us](tel:+1234567890)."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertIn("mailto:test@example.com", result)
        self.assertIn("tel:+1234567890", result)

    def test_anchor_links_unchanged(self):
        """#anchor links should not be treated as relative paths."""
        md = "See [section](#my-section) below."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(result, "See [section](#my-section) below.")

    def test_query_string_unchanged(self):
        """?query links should not be treated as relative paths."""
        md = "See [filtered](?tag=python) results."
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )
        self.assertEqual(result, "See [filtered](?tag=python) results.")

    def test_mixed_relative_formats(self):
        """Test a document with various relative URL formats."""
        md = """# Post

See [absolute](/article/other) and [dot-relative](./sibling).

Also check [bare](another-post) and [parent](../2024/old-post).

External: [Google](https://google.com) and [email](mailto:hi@example.com).
"""
        result = resolve_relative_urls(
            md, "https://example.com", "/article/2025/my-post"
        )

        self.assertIn("[absolute](https://example.com/article/other)", result)
        self.assertIn(
            "[dot-relative](https://example.com/article/2025/sibling)", result
        )
        self.assertIn("[bare](https://example.com/article/2025/another-post)", result)
        self.assertIn("[parent](https://example.com/article/2024/old-post)", result)
        self.assertIn("[Google](https://google.com)", result)
        self.assertIn("[email](mailto:hi@example.com)", result)


if __name__ == "__main__":
    unittest.main()
