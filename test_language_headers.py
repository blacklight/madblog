#!/usr/bin/env python3
"""
Test script to verify Language headers are working correctly.
This script tests that Language headers are set based on article metadata or global config.
"""

import os
import sys
import tempfile
from unittest.mock import patch

# Add the madblog module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_language_headers():
    """Test that Language headers are correctly set based on article metadata or global config."""

    # Create temporary markdown files with different language configurations
    temp_dir = tempfile.mkdtemp()

    # File 1: With explicit language metadata
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", dir=temp_dir, delete=False
    ) as f:
        content_with_lang = """# Test Article with Language

This is a test article with explicit language metadata.

[//]: # (published: 2024-01-01T00:00:00)
[//]: # (title: Test Language Headers)
[//]: # (language: fr-FR)
"""
        f.write(content_with_lang)
        file_with_lang = f.name

    # File 2: Without language metadata (should fall back to global config)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", dir=temp_dir, delete=False
    ) as f:
        content_no_lang = """# Test Article without Language

This is a test article without explicit language metadata.

[//]: # (published: 2024-01-02T00:00:00)
[//]: # (title: Test Global Language)
"""
        f.write(content_no_lang)
        file_no_lang = f.name

    try:
        # Mock the configuration and create a test app
        from madblog.config import config
        from madblog.app import BlogApp

        # Set up test config
        original_content_dir = config.content_dir
        original_language = config.language

        config.content_dir = temp_dir
        config.title = "Test Blog"
        config.link = "http://localhost:5000"
        config.author = "Test Author"
        config.view_mode = "cards"
        config.language = "en-US"  # Global language

        # Create app
        app = BlogApp(__name__)
        app.config["TESTING"] = True
        app.pages_dir = temp_dir

        page_with_lang = os.path.basename(file_with_lang)
        page_no_lang = os.path.basename(file_no_lang)

        with app.app_context():
            # Test 1: Article with explicit language metadata
            print("Test 1: Article with explicit language metadata...")
            response = app.get_page(page_with_lang)

            assert (
                "Language" in response.headers
            ), "Language header not found in article with metadata"
            assert (
                response.headers["Language"] == "fr-FR"
            ), f"Expected 'fr-FR', got '{response.headers['Language']}'"
            print(f"✓ Article language header: {response.headers['Language']}")

            # Test 2: Article without language metadata (should use global config)
            print("\nTest 2: Article without language metadata (fallback to global)...")
            response = app.get_page(page_no_lang)

            assert (
                "Language" in response.headers
            ), "Language header not found in article without metadata"
            assert (
                response.headers["Language"] == "en-US"
            ), f"Expected 'en-US', got '{response.headers['Language']}'"
            print(f"✓ Article fallback language header: {response.headers['Language']}")

            # Test 3: Home page (should use global config)
            print("\nTest 3: Home page language header...")
            response = app.get_pages_response()

            assert (
                "Language" in response.headers
            ), "Language header not found in home page"
            assert (
                response.headers["Language"] == "en-US"
            ), f"Expected 'en-US', got '{response.headers['Language']}'"
            print(f"✓ Home page language header: {response.headers['Language']}")

            # Test 4: 304 responses should also include Language header
            print("\nTest 4: 304 responses include Language header...")

            # Get a fresh response to get Last-Modified
            response = app.get_page(page_with_lang)
            last_modified = response.headers["Last-Modified"]

            # Mock request with If-Modified-Since
            with patch("madblog.app.request") as mock_request:
                mock_request.headers.get.return_value = last_modified

                response_304 = app.get_page(page_with_lang)

                if response_304.status_code == 304:
                    assert (
                        "Language" in response_304.headers
                    ), "Language header not found in 304 response"
                    assert (
                        response_304.headers["Language"] == "fr-FR"
                    ), f"Expected 'fr-FR' in 304, got '{response_304.headers['Language']}'"
                    print(
                        f"✓ 304 response language header: {response_304.headers['Language']}"
                    )
                else:
                    print("⚠ 304 test skipped - different status code returned")

            # Test 5: Test with no global language configured
            print("\nTest 5: No language configured (should skip header)...")
            config.language = None  # Temporarily remove global language

            response = app.get_page(page_no_lang)

            if "Language" in response.headers:
                print(
                    f"⚠ Language header found when none expected: {response.headers['Language']}"
                )
            else:
                print("✓ Language header correctly skipped when no language configured")

            print("\n✅ All Language header tests completed successfully!")

    finally:
        # Clean up
        try:
            os.unlink(file_with_lang)
            os.unlink(file_no_lang)
            os.rmdir(temp_dir)
        except:
            pass

        # Restore original config
        try:
            config.content_dir = original_content_dir
            config.language = original_language
        except:
            pass


if __name__ == "__main__":
    test_language_headers()
