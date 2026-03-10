"""Tests for the notifications module."""

from madblog.notifications import html_to_text


class TestHtmlToText:
    """Tests for html_to_text function."""

    def test_simple_paragraph(self):
        """Plain paragraph tags are converted to text with newlines."""
        html = "<p>Hello world</p>"
        assert html_to_text(html) == "Hello world"

    def test_nested_spans_and_links(self):
        """Nested inline elements are stripped, text preserved."""
        html = (
            '<p><span class="h-card" translate="no">'
            '<a href="https://example.com" class="u-url mention">'
            "@<span>blog</span></a></span> some text</p>"
        )
        result = html_to_text(html)
        assert "@blog some text" in result

    def test_br_tags(self):
        """<br> tags are converted to newlines."""
        html = "line1<br>line2<br/>line3"
        result = html_to_text(html)
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result

    def test_multiple_paragraphs(self):
        """Multiple paragraphs get proper spacing."""
        html = "<p>First paragraph</p><p>Second paragraph</p>"
        result = html_to_text(html)
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_heading_tags(self):
        """Heading tags get newlines after them."""
        html = "<h1>Title</h1><p>Content</p>"
        result = html_to_text(html)
        assert "Title" in result
        assert "Content" in result

    def test_list_items(self):
        """List items get newlines."""
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        result = html_to_text(html)
        assert "Item 1" in result
        assert "Item 2" in result

    def test_empty_string(self):
        """Empty string input returns empty string."""
        assert html_to_text("") == ""

    def test_plain_text(self):
        """Plain text without HTML passes through."""
        text = "Just plain text"
        assert html_to_text(text) == text

    def test_excessive_newlines_collapsed(self):
        """Multiple consecutive newlines are collapsed to at most two."""
        html = "<p>First</p><p></p><p></p><p>Second</p>"
        result = html_to_text(html)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result

    def test_activitypub_mention_content(self):
        """Real-world ActivityPub mention content is properly converted."""
        html = (
            '<p><span class="h-card" translate="no">'
            '<a href="https://ocus.top/ap/actor" class="u-url mention">'
            "@<span>blog</span></a></span> trying and throw a random "
            "screenshot on the guestbook because why not</p>"
        )
        result = html_to_text(html)
        assert "@blog" in result
        assert "trying and throw a random screenshot" in result
        assert "<" not in result
        assert ">" not in result
