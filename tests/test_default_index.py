"""
Tests for the customizable default index page functionality.
"""

import os
import tempfile
import unittest
import shutil
from pathlib import Path

from madblog.config import config


class TestDefaultIndexConfig(unittest.TestCase):
    """Tests for the default_index configuration option."""

    def test_default_index_default_is_blog(self):
        from madblog.config import Config

        cfg = Config()
        self.assertEqual(cfg.default_index, "blog")


class TestDefaultIndexRoute(unittest.TestCase):
    """Tests for the default index routing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_content_dir = config.content_dir
        self.original_default_index = config.default_index
        self.original_enable_guestbook = config.enable_guestbook
        config.content_dir = self.temp_dir

        # Create markdown directory
        self.pages_dir = Path(os.path.join(self.temp_dir, "markdown"))
        os.makedirs(self.pages_dir, exist_ok=True)

    def tearDown(self):
        config.content_dir = self.original_content_dir
        config.default_index = self.original_default_index
        config.enable_guestbook = self.original_enable_guestbook
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_home_route_defaults_to_blog(self):
        from madblog.app import app

        config.default_index = "blog"
        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/")
            # Should render the blog index directly (not redirect)
            self.assertEqual(response.status_code, 200)

    def test_home_route_redirects_to_about(self):
        from madblog.app import app

        config.default_index = "about"
        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, "/about")

    def test_home_route_redirects_to_tags(self):
        from madblog.app import app

        config.default_index = "tags"
        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, "/tags")

    def test_home_route_redirects_to_guestbook(self):
        from madblog.app import app

        config.default_index = "guestbook"
        config.enable_guestbook = True
        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, "/guestbook")

    def test_blog_route_returns_blog_index(self):
        from madblog.app import app

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/blog")
            self.assertEqual(response.status_code, 200)

    def test_blog_route_with_trailing_slash(self):
        from madblog.app import app

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/blog/")
            self.assertEqual(response.status_code, 200)

    def test_blog_route_always_returns_blog_regardless_of_default_index(self):
        from madblog.app import app

        # Even when default_index is set to something else,
        # /blog should always return the blog index
        config.default_index = "about"
        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/blog")
            self.assertEqual(response.status_code, 200)


class TestNavigationIncludesBlogLink(unittest.TestCase):
    """Tests that the navigation includes a Blog link."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_content_dir = config.content_dir
        config.content_dir = self.temp_dir

        # Create markdown directory
        self.pages_dir = Path(os.path.join(self.temp_dir, "markdown"))
        os.makedirs(self.pages_dir, exist_ok=True)

    def tearDown(self):
        config.content_dir = self.original_content_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_nav_shows_blog_link(self):
        from madblog.app import app

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/blog")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'href="/blog"', response.data)
            self.assertIn(b"Blog", response.data)


if __name__ == "__main__":
    unittest.main()
