"""
Tests for the About page functionality.
"""

import os
import tempfile
import unittest

from madblog.about._mixin import (
    HCard,
    _parse_org_list,
    _parse_key_field,
    _parse_links_list,
)
from madblog.config import config


class TestHCardHelpers(unittest.TestCase):
    """Tests for h-card helper functions."""

    def test_parse_org_list_with_urls(self):
        result = _parse_org_list(
            "ACME|https://example.com, Platypush|https://platypush.tech"
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "ACME")
        self.assertEqual(result[0]["url"], "https://example.com")
        self.assertEqual(result[1]["name"], "Platypush")
        self.assertEqual(result[1]["url"], "https://platypush.tech")

    def test_parse_org_list_without_urls(self):
        result = _parse_org_list("ACME Corp, Widgets Inc")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "ACME Corp")
        self.assertIsNone(result[0]["url"])
        self.assertEqual(result[1]["name"], "Widgets Inc")
        self.assertIsNone(result[1]["url"])

    def test_parse_org_list_empty(self):
        self.assertEqual(_parse_org_list(""), [])
        self.assertEqual(_parse_org_list(None), [])

    def test_parse_key_field_with_fingerprint(self):
        url, fingerprint = _parse_key_field("/key.txt|ABCDEF")
        self.assertEqual(url, "/key.txt")
        self.assertEqual(fingerprint, "ABCDEF")

    def test_parse_key_field_url_only(self):
        url, fingerprint = _parse_key_field("/key.txt")
        self.assertEqual(url, "/key.txt")
        self.assertIsNone(fingerprint)

    def test_parse_key_field_empty(self):
        url, fingerprint = _parse_key_field("")
        self.assertIsNone(url)
        self.assertIsNone(fingerprint)

    def test_parse_links_list_urls_only(self):
        result = _parse_links_list(
            "https://mastodon.social/@user, https://github.com/user"
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["url"], "https://mastodon.social/@user")
        self.assertIsNone(result[0]["label"])
        self.assertEqual(result[0]["domain"], "mastodon.social")
        self.assertEqual(result[1]["url"], "https://github.com/user")
        self.assertIsNone(result[1]["label"])
        self.assertEqual(result[1]["domain"], "github.com")

    def test_parse_links_list_with_labels(self):
        result = _parse_links_list(
            "Mastodon|https://mastodon.social/@user, GitHub|https://github.com/user"
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["label"], "Mastodon")
        self.assertEqual(result[0]["url"], "https://mastodon.social/@user")
        self.assertEqual(result[0]["domain"], "mastodon.social")
        self.assertEqual(result[1]["label"], "GitHub")
        self.assertEqual(result[1]["url"], "https://github.com/user")
        self.assertEqual(result[1]["domain"], "github.com")

    def test_parse_links_list_empty(self):
        self.assertEqual(_parse_links_list(""), [])


class TestHCard(unittest.TestCase):
    """Tests for the HCard dataclass."""

    def test_has_data_with_name(self):
        hcard = HCard(name="John Doe")
        self.assertTrue(hcard.has_data())

    def test_has_data_with_email(self):
        hcard = HCard(email="john@example.com")
        self.assertTrue(hcard.has_data())

    def test_has_data_empty(self):
        hcard = HCard()
        self.assertFalse(hcard.has_data())


class TestAboutPage(unittest.TestCase):
    """Tests for the About page rendering."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_content_dir = config.content_dir
        config.content_dir = self.temp_dir

        # Create markdown directory
        self.pages_dir = os.path.join(self.temp_dir, "markdown")
        os.makedirs(self.pages_dir, exist_ok=True)

    def tearDown(self):
        config.content_dir = self.original_content_dir
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_about_route_returns_404_when_no_about_file(self):
        from madblog.app import app

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/about")
            self.assertEqual(response.status_code, 404)

    def test_about_route_returns_200_when_about_file_exists(self):
        from madblog.app import app

        # Create ABOUT.md
        about_file = os.path.join(self.pages_dir, "ABOUT.md")
        with open(about_file, "w") as f:
            f.write("[//]: # (title: About Me)\n\n# About\n\nThis is the about page.")

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/about")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"About Me", response.data)
            self.assertIn(b"This is the about page", response.data)

    def test_about_page_renders_hcard_from_metadata(self):
        from madblog.app import app

        # Create ABOUT.md with h-card metadata
        about_file = os.path.join(self.pages_dir, "ABOUT.md")
        with open(about_file, "w") as f:
            f.write(
                """[//]: # (title: About)
[//]: # (name: Jane Doe)
[//]: # (job-title: Software Engineer)
[//]: # (email: jane@example.com)

# About Me

Hello, I'm Jane.
"""
            )

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/about")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Jane Doe", response.data)
            self.assertIn(b"Software Engineer", response.data)
            self.assertIn(b"jane@example.com", response.data)
            # Check h-card class is present
            self.assertIn(b"h-card", response.data)

    def test_about_page_respects_hide_email(self):
        from madblog.app import app

        # Set up config
        original_hide_email = config.hide_email
        original_author_email = config.author_email
        config.hide_email = True
        config.author_email = "secret@example.com"

        try:
            # Create ABOUT.md without explicit email
            about_file = os.path.join(self.pages_dir, "ABOUT.md")
            with open(about_file, "w") as f:
                f.write(
                    """[//]: # (title: About)
[//]: # (name: Jane Doe)

# About Me
"""
                )

            app.pages_dir = self.pages_dir
            with app.test_client() as client:
                response = client.get("/about")
                self.assertEqual(response.status_code, 200)
                # Email should NOT be in response when hide_email is True
                self.assertNotIn(b"secret@example.com", response.data)
        finally:
            config.hide_email = original_hide_email
            config.author_email = original_author_email

    def test_nav_shows_about_link_when_file_exists(self):
        from madblog.app import app

        # Create ABOUT.md
        about_file = os.path.join(self.pages_dir, "ABOUT.md")
        with open(about_file, "w") as f:
            f.write("# About\n\nContent here.")

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'href="/about"', response.data)
            self.assertIn(b"About", response.data)

    def test_nav_hides_about_link_when_no_file(self):
        from madblog.app import app

        app.pages_dir = self.pages_dir
        with app.test_client() as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            # Should not have the about link
            self.assertNotIn(b'href="/about"', response.data)


class TestHideEmailConfig(unittest.TestCase):
    """Tests for the hide_email configuration option."""

    def test_hide_email_default_is_false(self):
        from madblog.config import Config

        cfg = Config()
        self.assertFalse(cfg.hide_email)


if __name__ == "__main__":
    unittest.main()
