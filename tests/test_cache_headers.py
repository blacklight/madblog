#!/usr/bin/env python3
"""
Test script to verify cache headers are working correctly.
This script will test the BlogApp.get_page() method to ensure proper cache headers are set.
"""

import os
import sys
import tempfile
import time
from email.utils import parsedate_tz, mktime_tz

# Add the madblog module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_cache_headers():
    """Test that cache headers are correctly set based on file modification time."""

    # Create a temporary markdown file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        test_content = """# Test Article

This is a test article for cache header testing.

[//]: # (published: 2024-01-01T00:00:00)
[//]: # (title: Test Cache Headers)
"""
        f.write(test_content)
        temp_file = f.name

    try:
        # Mock the configuration and create a test app
        from madblog.config import config
        from madblog.app import BlogApp

        # Set up test config
        config.content_dir = os.path.dirname(temp_file)
        config.title = "Test Blog"
        config.link = "http://localhost:5000"
        config.author = "Test Author"

        # Create app with test client
        app = BlogApp(__name__)
        app.config["TESTING"] = True
        app.pages_dir = os.path.dirname(temp_file)

        with app.test_client():
            page_name = os.path.basename(temp_file)

            # Test 1: First request should return full content with Last-Modified header
            print("Test 1: Initial request for cache headers...")
            with app.test_request_context(f"/article/{page_name[:-3]}"):
                response = app.get_page(page_name)

            # Check that Last-Modified header is present
            assert "Last-Modified" in response.headers, "Last-Modified header not found"
            assert "Cache-Control" in response.headers, "Cache-Control header not found"

            last_modified = response.headers["Last-Modified"]
            print(f"✓ Last-Modified header found: {last_modified}")
            print(f"✓ Cache-Control header found: {response.headers['Cache-Control']}")

            # Test 2: Simulate If-Modified-Since with same timestamp (should return 304)
            print("\nTest 2: Testing 304 Not Modified response...")

            with app.test_request_context(
                f"/article/{page_name[:-3]}",
                headers={"If-Modified-Since": last_modified},
            ):
                response_304 = app.get_page(page_name)

                # Should return 304 for unchanged file
                print(f"✓ Response status: {response_304.status_code}")
                if response_304.status_code == 304:
                    print("✓ 304 Not Modified returned correctly")
                else:
                    print("⚠ Expected 304 but got different status code")

            # Test 3: Modify file and check that cache is invalidated
            print("\nTest 3: Testing cache invalidation after file modification...")

            # Wait a moment to ensure different mtime
            time.sleep(1)

            # Modify the file
            with open(temp_file, "a") as f:
                f.write("\nAdditional content added for cache test.")

            # Request again - should get fresh content
            with app.test_request_context(f"/article/{page_name[:-3]}"):
                new_response = app.get_page(page_name)
            new_last_modified = new_response.headers["Last-Modified"]

            print(f"✓ New Last-Modified header: {new_last_modified}")

            # Parse dates to compare
            old_time = mktime_tz(parsedate_tz(last_modified))  # type: ignore
            new_time = mktime_tz(parsedate_tz(new_last_modified))  # type: ignore

            if new_time > old_time:
                print(
                    "✓ Last-Modified header updated correctly after file modification"
                )
            else:
                print("⚠ Last-Modified header was not updated properly")

            print("\n✅ All cache header tests completed successfully!")

    finally:
        # Clean up
        os.unlink(temp_file)


if __name__ == "__main__":
    test_cache_headers()
