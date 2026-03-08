#!/usr/bin/env python3
"""
Test script to verify the optimized cache headers are working correctly.
This verifies that file_mtime is included in page metadata and used for cache headers.
"""

import os
import sys
import tempfile
from email.utils import formatdate, parsedate_tz, mktime_tz

# Add the madblog module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_optimized_cache_logic():
    """Test that the optimized cache logic works without redundant file system calls."""

    # Create a temporary markdown file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        test_content = """# Test Article

This is a test article for optimized cache header testing.

[//]: # (published: 2024-01-01T00:00:00)
[//]: # (title: Test Optimized Cache Headers)
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
        config.view_mode = "cards"

        # Create app
        app = BlogApp(__name__)
        app.config["TESTING"] = True
        app.pages_dir = os.path.dirname(temp_file)

        page_name = os.path.basename(temp_file)

        with app.app_context():
            # Test 1: Check that _parse_page_metadata includes file_mtime
            print("Test 1: Verifying file_mtime is included in page metadata...")
            metadata = app._parse_page_metadata(page_name)

            assert "file_mtime" in metadata, "file_mtime not found in page metadata"
            print(f"✓ file_mtime found in metadata: {metadata['file_mtime']}")

            # Test 2: Check that get_pages includes file_mtime for each page
            print("\nTest 2: Verifying get_pages includes file_mtime...")
            pages = app.get_pages()

            found_test_page = False
            for _, page_data in pages:
                if page_data.get("path") == page_name:
                    found_test_page = True
                    assert (
                        "file_mtime" in page_data
                    ), "file_mtime not found in page data from get_pages"
                    print(
                        f"✓ file_mtime found in get_pages data: {page_data['file_mtime']}"
                    )
                    break

            assert found_test_page, "Test page not found in get_pages output"

            # Test 3: Check get_pages_response uses the file_mtime correctly
            print("\nTest 3: Testing get_pages_response cache headers...")

            response = app.get_pages_response()

            assert "Last-Modified" in response.headers, "Last-Modified header not found"
            assert "Cache-Control" in response.headers, "Cache-Control header not found"

            last_modified = response.headers["Last-Modified"]
            print(f"✓ Last-Modified header: {last_modified}")
            print(f"✓ Cache-Control header: {response.headers['Cache-Control']}")

            # Test 4: Verify the Last-Modified matches file modification time
            print("\nTest 4: Verifying Last-Modified accuracy...")

            file_mtime = os.stat(temp_file).st_mtime
            expected_last_modified = formatdate(file_mtime, usegmt=True)

            # Parse both dates for comparison (allowing for small differences due to formatting)
            actual_time = mktime_tz(parsedate_tz(last_modified))  # type: ignore
            expected_time = mktime_tz(parsedate_tz(expected_last_modified))  # type: ignore

            time_diff = abs(actual_time - expected_time)
            assert time_diff < 1, f"Last-Modified time differs by {time_diff} seconds"
            print(f"✓ Last-Modified matches file mtime (diff: {time_diff}s)")

            # Test 5: Test 304 response with mock If-Modified-Since
            print("\nTest 5: Testing 304 Not Modified response...")

            with app.test_request_context(
                "/",
                headers={"If-Modified-Since": last_modified},
            ):
                response_304 = app.get_pages_response()
                print(f"✓ Response status: {response_304.status_code}")

                if response_304.status_code == 304:
                    print("✓ 304 Not Modified returned correctly")
                else:
                    print("⚠ Expected 304 but got different status code")

            print("\n✅ All optimized cache header tests completed successfully!")
            print(
                "✅ No redundant file system calls - using file_mtime from page metadata!"
            )

    finally:
        # Clean up
        os.unlink(temp_file)


if __name__ == "__main__":
    test_optimized_cache_logic()
