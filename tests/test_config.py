"""
Tests for config utilities.
"""

import unittest

from madblog.config import _normalize_url


class NormalizeUrlTest(unittest.TestCase):
    """Tests for _normalize_url helper."""

    def test_already_has_https(self):
        """URLs with https:// should be returned unchanged."""
        self.assertEqual(
            _normalize_url("https://example.com"),
            "https://example.com",
        )

    def test_already_has_http(self):
        """URLs with http:// should be returned unchanged."""
        self.assertEqual(
            _normalize_url("http://example.com"),
            "http://example.com",
        )

    def test_bare_hostname_gets_https(self):
        """Bare hostnames should get https:// prepended."""
        self.assertEqual(
            _normalize_url("example.com"),
            "https://example.com",
        )

    def test_bare_hostname_with_path(self):
        """Bare hostnames with path should get https:// prepended."""
        self.assertEqual(
            _normalize_url("blog.example.com/path"),
            "https://blog.example.com/path",
        )

    def test_empty_string(self):
        """Empty string should be returned unchanged."""
        self.assertEqual(_normalize_url(""), "")

    def test_slash_only(self):
        """Single slash should be returned unchanged."""
        self.assertEqual(_normalize_url("/"), "/")


if __name__ == "__main__":
    unittest.main()
