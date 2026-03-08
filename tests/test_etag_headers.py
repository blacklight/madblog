#!/usr/bin/env python3
"""
Test script to verify ETag headers are working correctly.
This script tests that ETag headers are set based on file modification times and If-None-Match validation works.
"""

import os
import sys
import tempfile
import time
from unittest.mock import patch

# Add the madblog module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_etag_headers():
    """Test that ETag headers are correctly set and validated."""

    # Create temporary markdown files
    temp_dir = tempfile.mkdtemp()

    # File 1: Regular article
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", dir=temp_dir, delete=False
    ) as f:
        content = """# Test Article for ETag

This is a test article for ETag testing.

[//]: # (published: 2024-01-01T00:00:00)
[//]: # (title: Test ETag Headers)
[//]: # (language: en-US)
"""
        f.write(content)
        test_file = f.name

    # File 2: Additional file for pages list testing
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", dir=temp_dir, delete=False
    ) as f:
        content2 = """# Second Article

This is another article for ETag testing.

[//]: # (published: 2024-01-02T00:00:00)
[//]: # (title: Second Article)
"""
        f.write(content2)
        test_file2 = f.name

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
        config.language = "en-US"

        # Create app
        app = BlogApp(__name__)
        app.config["TESTING"] = True
        app.pages_dir = temp_dir

        page_name = os.path.basename(test_file)

        with app.app_context():
            # Test 1: Individual article ETag generation
            print("Test 1: Individual article ETag generation...")
            response = app.get_page(page_name)

            assert (
                "ETag" in response.headers
            ), "ETag header not found in article response"
            assert (
                "Last-Modified" in response.headers
            ), "Last-Modified header not found in article response"

            etag = response.headers["ETag"]
            last_modified = response.headers["Last-Modified"]

            # ETag should be a quoted string
            assert etag.startswith('"') and etag.endswith(
                '"'
            ), f"ETag not properly quoted: {etag}"
            print(f"✓ Article ETag: {etag}")
            print(f"✓ Article Last-Modified: {last_modified}")

            # Test 2: ETag consistency - same file should generate same ETag
            print("\nTest 2: ETag consistency...")
            response2 = app.get_page(page_name)
            etag2 = response2.headers["ETag"]

            assert etag == etag2, f"ETag should be consistent: {etag} != {etag2}"
            print(f"✓ ETag consistency verified: {etag}")

            # Test 3: If-None-Match validation (should return 304)
            print("\nTest 3: If-None-Match validation (304 response)...")

            with app.test_request_context(
                f"/article/{os.path.splitext(page_name)[0]}",
                headers={"If-None-Match": etag},
            ):
                response_304 = app.get_page(page_name)

                assert (
                    response_304.status_code == 304
                ), f"Expected 304, got {response_304.status_code}"
                assert (
                    response_304.headers.get("ETag") == etag
                ), "ETag missing from 304 response"
                print(f"✓ 304 response with matching ETag: {etag}")

            # Test 4: If-None-Match with wildcard (should return 304)
            print("\nTest 4: If-None-Match with wildcard...")

            with app.test_request_context(
                f"/article/{os.path.splitext(page_name)[0]}",
                headers={"If-None-Match": "*"},
            ):
                response_304_wildcard = app.get_page(page_name)

                assert (
                    response_304_wildcard.status_code == 304
                ), f"Expected 304 with wildcard, got {response_304_wildcard.status_code}"
                print(f"✓ 304 response with wildcard ETag")

            # Test 5: Multiple ETags in If-None-Match
            print("\nTest 5: Multiple ETags in If-None-Match...")

            dummy_etag = '"dummy123456"'

            with app.test_request_context(
                f"/article/{os.path.splitext(page_name)[0]}",
                headers={"If-None-Match": f"{dummy_etag}, {etag}"},
            ):
                response_304_multi = app.get_page(page_name)

                assert (
                    response_304_multi.status_code == 304
                ), f"Expected 304 with multiple ETags, got {response_304_multi.status_code}"
                print(f"✓ 304 response with multiple ETags")

            # Test 6: File modification changes ETag
            print("\nTest 6: File modification changes ETag...")

            # Wait to ensure different mtime
            time.sleep(1)

            # Modify the file
            with open(test_file, "a") as f:
                f.write("\nAdditional content for ETag change test.")

            # Get new response
            new_response = app.get_page(page_name)
            new_etag = new_response.headers["ETag"]

            assert (
                new_etag != etag
            ), f"ETag should change after file modification: {etag} == {new_etag}"
            print(f"✓ ETag changed after modification: {etag} → {new_etag}")

            # Test 7: Pages list ETag generation
            print("\nTest 7: Pages list ETag generation...")

            pages_response = app.get_pages_response()

            assert (
                "ETag" in pages_response.headers
            ), "ETag header not found in pages response"
            assert (
                "Last-Modified" in pages_response.headers
            ), "Last-Modified header not found in pages response"

            pages_etag = pages_response.headers["ETag"]
            print(f"✓ Pages list ETag: {pages_etag}")

            # Test 8: Pages list If-None-Match validation
            print("\nTest 8: Pages list If-None-Match validation...")

            with app.test_request_context(
                "/",
                headers={"If-None-Match": pages_etag},
            ):
                pages_response_304 = app.get_pages_response()

                assert (
                    pages_response_304.status_code == 304
                ), f"Expected 304 for pages, got {pages_response_304.status_code}"
                print(f"✓ 304 response for pages list with matching ETag")

            # Test 9: ETag helper function
            print("\nTest 9: ETag helper function...")

            test_mtime = 1672531200.0  # Fixed timestamp for testing
            generated_etag = app._generate_etag(test_mtime)

            assert generated_etag.startswith('"') and generated_etag.endswith(
                '"'
            ), "Generated ETag not properly quoted"

            # Should be consistent
            generated_etag2 = app._generate_etag(test_mtime)
            assert (
                generated_etag == generated_etag2
            ), "ETag generation should be deterministic"
            print(f"✓ ETag generation helper works: {generated_etag}")

            print("\n✅ All ETag header tests completed successfully!")
            print("✅ ETag validation works alongside Last-Modified headers!")

    finally:
        # Clean up
        try:
            os.unlink(test_file)
            os.unlink(test_file2)
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
    test_etag_headers()
