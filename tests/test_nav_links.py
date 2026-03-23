"""
Tests for the nav_links configuration and rendering.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from madblog.config import config


class TestNavLinksRendering(unittest.TestCase):
    """Tests for nav_links rendering in the navigation panel."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_content_dir = config.content_dir
        self.original_nav_links = config.nav_links
        self.original_header = config.header
        config.content_dir = self.temp_dir
        config.header = True

        # Create markdown directory
        self.pages_dir = Path(os.path.join(self.temp_dir, "markdown"))
        os.makedirs(self.pages_dir, exist_ok=True)

    def tearDown(self):
        config.content_dir = self.original_content_dir
        config.nav_links = self.original_nav_links
        config.header = self.original_header
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _get_html(self):
        from madblog.app import app

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/blog")
            return response.data.decode()

    def test_simple_url_nav_link_no_new_tab(self):
        """Simple URL nav links should not open in a new tab by default."""
        config.nav_links = ["https://example.com"]
        html = self._get_html()
        self.assertIn('href="https://example.com"', html)
        self.assertNotIn(
            'href="https://example.com" target="_blank"',
            html,
        )

    def test_dict_nav_link_no_new_tab_by_default(self):
        """Dict nav links without new_tab should not open in a new tab."""
        config.nav_links = [{"url": "https://example.com", "display_name": "Example"}]
        html = self._get_html()
        self.assertIn('href="https://example.com"', html)
        self.assertNotIn(
            'href="https://example.com" target="_blank"',
            html,
        )

    def test_dict_nav_link_new_tab_false(self):
        """Dict nav links with new_tab=False should not open in a new tab."""
        config.nav_links = [
            {"url": "https://example.com", "display_name": "Example", "new_tab": False}
        ]
        html = self._get_html()
        self.assertIn('href="https://example.com"', html)
        self.assertNotIn(
            'href="https://example.com" target="_blank"',
            html,
        )

    def test_dict_nav_link_new_tab_true(self):
        """Dict nav links with new_tab=True should open in a new tab."""
        config.nav_links = [
            {"url": "https://example.com", "display_name": "Example", "new_tab": True}
        ]
        html = self._get_html()
        self.assertIn(
            'href="https://example.com" target="_blank" rel="noopener"',
            html,
        )

    def test_mixed_nav_links(self):
        """Mix of nav links with and without new_tab."""
        config.nav_links = [
            {"url": "https://a.com", "display_name": "A", "new_tab": True},
            {"url": "https://b.com", "display_name": "B"},
            "https://c.com",
        ]
        html = self._get_html()
        self.assertIn('href="https://a.com" target="_blank" rel="noopener"', html)
        self.assertNotIn('href="https://b.com" target="_blank"', html)
        self.assertNotIn('href="https://c.com" target="_blank"', html)


if __name__ == "__main__":
    unittest.main()
