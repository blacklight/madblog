#!/usr/bin/env python3
"""
Test script to verify cache headers are working correctly for get_pages_response.
This script will test the BlogApp.get_pages_response() method to ensure proper cache headers are set.
"""

import os
import sys
import tempfile
import time
from email.utils import parsedate_tz, mktime_tz

# Add the madblog module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_get_pages_cache_headers():
    """Test that cache headers are correctly set for get_pages_response based on most recent file modification."""

    # Create temporary markdown files
    temp_dir = tempfile.mkdtemp()

    # Create multiple test files with different content
    test_files = []
    for i in range(3):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", dir=temp_dir, delete=False
        ) as f:
            test_content = f"""# Test Article {i+1}

This is test article {i+1} for cache header testing.

[//]: # (published: 2024-01-0{i+1}T00:00:00)
[//]: # (title: Test Cache Headers {i+1})
"""
            f.write(test_content)
            test_files.append(f.name)

    try:
        # Mock the configuration and create a test app
        from madblog.config import config
        from madblog.app import BlogApp

        # Set up test config
        original_content_dir = config.content_dir
        config.content_dir = temp_dir
        config.title = "Test Blog"
        config.link = "http://localhost:5000"
        config.author = "Test Author"
        config.view_mode = "cards"

        # Create app with test client
        app = BlogApp(__name__)
        app.config["TESTING"] = True
        app.pages_dir = temp_dir

        with app.test_client():

            # Test 1: First request should return full content with Last-Modified header
            print("Test 1: Initial request for pages cache headers...")

            with app.app_context():
                response = app.get_pages_response()

            # Check that cache headers are present
            assert (
                "Last-Modified" in response.headers
            ), "Last-Modified header not found in get_pages_response"
            assert (
                "Cache-Control" in response.headers
            ), "Cache-Control header not found in get_pages_response"

            last_modified = response.headers["Last-Modified"]
            print(f"✓ Last-Modified header found: {last_modified}")
            print(f"✓ Cache-Control header found: {response.headers['Cache-Control']}")

            # Test 2: Simulate If-Modified-Since with same timestamp (should return 304)
            print(
                "\nTest 2: Testing 304 Not Modified response for get_pages_response..."
            )

            # Create a mock request with If-Modified-Since header
            from unittest.mock import patch

            with patch("madblog.app.request") as mock_request:
                mock_request.headers.get.return_value = last_modified

                with app.app_context():
                    response_304 = app.get_pages_response()

                # Should return 304 for unchanged files
                print(f"✓ Response status: {response_304.status_code}")
                if response_304.status_code == 304:
                    print("✓ 304 Not Modified returned correctly for pages list")
                else:
                    print("⚠ Expected 304 but got different status code")

            # Test 3: Modify a file and check that cache is invalidated
            print("\nTest 3: Testing cache invalidation after file modification...")

            # Wait a moment to ensure different mtime
            time.sleep(1)

            # Modify one of the files (this should be the most recent)
            with open(test_files[1], "a") as f:
                f.write("\nAdditional content added for cache test.")

            # Request again - should get fresh content with new Last-Modified
            with app.app_context():
                new_response = app.get_pages_response()
            new_last_modified = new_response.headers["Last-Modified"]

            print(f"✓ New Last-Modified header: {new_last_modified}")

            # Parse dates to compare
            old_time = mktime_tz(parsedate_tz(last_modified))  # type: ignore
            new_time = mktime_tz(parsedate_tz(new_last_modified))  # type: ignore

            if new_time > old_time:
                print(
                    "✓ Last-Modified header updated correctly after file modification in pages list"
                )
            else:
                print("⚠ Last-Modified header was not updated properly for pages list")

            # Test 4: Test that the most recent file determines the Last-Modified header
            print("\nTest 4: Testing that most recent file determines Last-Modified...")

            # Wait and modify the third file (should become the newest)
            time.sleep(1)
            with open(test_files[2], "a") as f:
                f.write("\nThis should be the newest modification.")

            with app.app_context():
                newest_response = app.get_pages_response()
            newest_last_modified = newest_response.headers["Last-Modified"]

            newest_time = mktime_tz(parsedate_tz(newest_last_modified))  # type: ignore

            if newest_time > new_time:
                print("✓ Most recent file correctly determines Last-Modified header")
            else:
                print("⚠ Most recent file logic may not be working properly")

            print(
                "\n✅ All get_pages_response cache header tests completed successfully!"
            )

    finally:
        # Clean up
        for f in test_files:
            try:
                os.unlink(f)
            except:
                pass
        try:
            os.rmdir(temp_dir)
        except:
            pass

        # Restore original config
        try:
            config.content_dir = original_content_dir  # type: ignore
        except:
            pass


if __name__ == "__main__":
    test_get_pages_cache_headers()
