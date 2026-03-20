import unittest

from madblog.markdown._render import _normalize_list_indentation, render_html


class NestedListIndentationTest(unittest.TestCase):
    """Regression tests for nested list indentation support (2-space and 4-space)."""

    def test_2space_unordered_list(self):
        """2-space indentation should produce nested lists."""
        md = "- item1\n  - item1.1\n  - item1.2"
        html = render_html(md)
        self.assertIn("<ul>", html)
        self.assertIn("<li>item1<ul>", html)
        self.assertIn("<li>item1.1</li>", html)
        self.assertIn("<li>item1.2</li>", html)

    def test_4space_unordered_list(self):
        """4-space indentation should also produce nested lists."""
        md = "- item1\n    - item1.1\n    - item1.2"
        html = render_html(md)
        self.assertIn("<ul>", html)
        self.assertIn("<li>item1<ul>", html)
        self.assertIn("<li>item1.1</li>", html)
        self.assertIn("<li>item1.2</li>", html)

    def test_2space_ordered_list(self):
        """2-space indentation should work for ordered lists."""
        md = "1. item1\n  1. item1.1\n  2. item1.2"
        html = render_html(md)
        self.assertIn("<ol>", html)
        self.assertIn("<li>item1<ol>", html)

    def test_4space_ordered_list(self):
        """4-space indentation should work for ordered lists."""
        md = "1. item1\n    1. item1.1\n    2. item1.2"
        html = render_html(md)
        self.assertIn("<ol>", html)
        self.assertIn("<li>item1<ol>", html)

    def test_deeply_nested_4space(self):
        """Multiple levels of 4-space indentation should nest correctly."""
        md = "- item1\n    - item1.1\n        - item1.1.1"
        html = render_html(md)
        # Should have 3 levels of nesting
        self.assertEqual(html.count("<ul>"), 3)

    def test_fenced_code_block_preserved(self):
        """List-like content inside fenced code blocks should not be altered."""
        md = "```\n    - not a list\n    - just code\n```"
        normalized = _normalize_list_indentation(md)
        # The 4-space indent inside code block should remain unchanged
        self.assertIn("    - not a list", normalized)
        self.assertIn("    - just code", normalized)

    def test_mixed_content_with_code_block(self):
        """Lists outside code blocks normalized, code blocks preserved."""
        md = "- list item\n    - nested\n\n```\n    - code\n```\n\n- another\n    - nested"
        normalized = _normalize_list_indentation(md)
        # Code block content preserved
        self.assertIn("```\n    - code\n```", normalized)
        # List items normalized (4-space -> 2-space)
        lines = normalized.split("\n")
        # First nested item should be normalized
        self.assertEqual(lines[1], "  - nested")
        # Last nested item should be normalized
        self.assertEqual(lines[-1], "  - nested")

    def test_list_markers_star_and_plus(self):
        """All unordered list markers (-, *, +) should be normalized."""
        for marker in ["-", "*", "+"]:
            md = f"{marker} item1\n    {marker} nested"
            html = render_html(md)
            self.assertIn("<ul>", html, f"Failed for marker '{marker}'")
            self.assertIn("<li>item1<ul>", html, f"Failed for marker '{marker}'")

    def test_8space_becomes_2_levels(self):
        """8-space indentation should become 2 levels of nesting."""
        md = "- item1\n        - item1.1.1"
        html = render_html(md)
        # 8 spaces / 4 = 2 levels, but with tab_length=2, that's 4 indent levels
        # After normalization: 8 -> 4 spaces (2 levels in 2-space mode)
        self.assertIn("<ul>", html)
        self.assertIn("<li>item1", html)


if __name__ == "__main__":
    unittest.main()
