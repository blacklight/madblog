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


if __name__ == "__main__":
    unittest.main()
