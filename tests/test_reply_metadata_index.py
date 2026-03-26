"""
Tests for ReplyMetadataIndex.
"""

import json

import pytest

from madblog.monitor import ChangeType
from madblog.replies import ReplyMetadata, ReplyMetadataIndex


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary replies and state directories."""
    replies_dir = tmp_path / "replies"
    state_dir = tmp_path / ".madblog"
    replies_dir.mkdir()
    state_dir.mkdir()
    return replies_dir, state_dir


@pytest.fixture
def index(temp_dirs):
    """Create a ReplyMetadataIndex instance."""
    replies_dir, state_dir = temp_dirs
    return ReplyMetadataIndex(replies_dir, state_dir)


class TestReplyMetadataExtraction:
    """Tests for metadata extraction from Markdown files."""

    def test_extract_basic_metadata(self, temp_dirs, index):
        """Extract basic metadata fields from a reply file."""
        replies_dir, _ = temp_dirs
        md_file = replies_dir / "test-post.md"
        md_file.write_text(
            """\
[//]: # (reply-to: https://example.com/post/123)
[//]: # (like-of: https://example.com/post/456)
[//]: # (visibility: public)
[//]: # (published: 2025-03-26T10:00:00+00:00)
[//]: # (title: Test Post)

# Heading

This is the content.
"""
        )

        entry = index._extract_metadata(str(md_file))

        assert entry is not None
        assert entry.rel_path == "test-post.md"
        assert entry.reply_to == "https://example.com/post/123"
        assert entry.like_of == "https://example.com/post/456"
        assert entry.visibility == "public"
        assert entry.published == "2025-03-26T10:00:00+00:00"
        assert entry.title == "Test Post"
        assert entry.has_content is True

    def test_extract_title_from_heading(self, temp_dirs, index):
        """Title is inferred from first heading if not in metadata."""
        replies_dir, _ = temp_dirs
        md_file = replies_dir / "no-title.md"
        md_file.write_text(
            """\
[//]: # (visibility: unlisted)

# My Heading Title

Content here.
"""
        )

        entry = index._extract_metadata(str(md_file))

        assert entry is not None
        assert entry.title == "My Heading Title"

    def test_extract_title_from_link_heading(self, temp_dirs, index):
        """Title extracts text from link in heading."""
        replies_dir, _ = temp_dirs
        md_file = replies_dir / "link-title.md"
        md_file.write_text(
            """\
# [Link Title](https://example.com)

Content.
"""
        )

        entry = index._extract_metadata(str(md_file))

        assert entry is not None
        assert entry.title == "Link Title"

    def test_has_content_false_for_empty(self, temp_dirs, index):
        """has_content is False for files with only metadata."""
        replies_dir, _ = temp_dirs
        md_file = replies_dir / "metadata-only.md"
        md_file.write_text(
            """\
[//]: # (like-of: https://example.com/post)
[//]: # (visibility: public)
"""
        )

        entry = index._extract_metadata(str(md_file))

        assert entry is not None
        assert entry.has_content is False

    def test_has_content_ignores_metadata_comments(self, temp_dirs, index):
        """Metadata comments ([//]: # (...)) don't count as content."""
        replies_dir, _ = temp_dirs
        md_file = replies_dir / "comment-only.md"
        md_file.write_text(
            """\
[//]: # (like-of: https://example.com/post)

[//]: # (ap-object-id: https://example.com/objects/123)
"""
        )

        entry = index._extract_metadata(str(md_file))

        assert entry is not None
        assert entry.has_content is False

    def test_has_content_true_with_real_content(self, temp_dirs, index):
        """has_content is True when there's real content after metadata."""
        replies_dir, _ = temp_dirs
        md_file = replies_dir / "with-content.md"
        md_file.write_text(
            """\
[//]: # (reply-to: https://example.com/post)

This is actual content.
"""
        )

        entry = index._extract_metadata(str(md_file))

        assert entry is not None
        assert entry.has_content is True

    def test_extract_from_subdirectory(self, temp_dirs, index):
        """Extract metadata from files in subdirectories."""
        replies_dir, _ = temp_dirs
        subdir = replies_dir / "article-slug"
        subdir.mkdir()
        md_file = subdir / "reply-1.md"
        md_file.write_text(
            """\
[//]: # (visibility: public)

Reply content.
"""
        )

        entry = index._extract_metadata(str(md_file))

        assert entry is not None
        assert entry.rel_path == "article-slug/reply-1.md"

    def test_extract_nonexistent_file(self, temp_dirs, index):
        """Returns None for non-existent files."""
        replies_dir, _ = temp_dirs
        entry = index._extract_metadata(str(replies_dir / "nonexistent.md"))
        assert entry is None


class TestReplyMetadataIndexPersistence:
    """Tests for index persistence and loading."""

    def test_full_scan_and_save(self, temp_dirs, index):
        """Full scan indexes all files and persists to JSON."""
        replies_dir, state_dir = temp_dirs

        # Create some reply files
        (replies_dir / "post1.md").write_text(
            "[//]: # (visibility: unlisted)\n\nContent 1."
        )
        (replies_dir / "post2.md").write_text(
            "[//]: # (reply-to: https://x.com)\n\nReply."
        )
        subdir = replies_dir / "article"
        subdir.mkdir()
        (subdir / "reply.md").write_text("[//]: # (visibility: public)\n\nNested.")

        index.load()

        assert index.entry_count == 3
        assert index.get_entry("post1.md") is not None
        assert index.get_entry("post2.md") is not None
        assert index.get_entry("article/reply.md") is not None

        # Check JSON file was created
        index_file = state_dir / "reply_metadata_index.json"
        assert index_file.exists()

        data = json.loads(index_file.read_text())
        assert data["schema_version"] == 1
        assert len(data["entries"]) == 3

    def test_load_from_existing_json(self, temp_dirs, index):
        """Load index from existing JSON file without re-scanning."""
        _, state_dir = temp_dirs

        # Create index file directly
        index_file = state_dir / "reply_metadata_index.json"
        index_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "entries": {
                        "cached.md": {
                            "rel_path": "cached.md",
                            "reply_to": None,
                            "like_of": None,
                            "visibility": "unlisted",
                            "published": "2025-01-01T00:00:00+00:00",
                            "has_content": True,
                            "title": "Cached Entry",
                        }
                    },
                }
            )
        )

        index.load()

        assert index.entry_count == 1
        entry = index.get_entry("cached.md")
        assert entry is not None
        assert entry.title == "Cached Entry"

    def test_schema_mismatch_triggers_rescan(self, temp_dirs, index):
        """Schema version mismatch triggers full rescan."""
        replies_dir, state_dir = temp_dirs

        # Create a file that should be indexed
        (replies_dir / "new.md").write_text(
            "[//]: # (visibility: public)\n\nNew content."
        )

        # Create index file with old schema version
        index_file = state_dir / "reply_metadata_index.json"
        index_file.write_text(
            json.dumps(
                {
                    "schema_version": 0,  # Old version
                    "entries": {
                        "old.md": {
                            "rel_path": "old.md",
                            "reply_to": None,
                            "like_of": None,
                            "visibility": "unlisted",
                            "published": None,
                            "has_content": True,
                            "title": "Old Entry",
                        }
                    },
                }
            )
        )

        index.load()

        # Should have rescanned and found new.md, not old.md
        assert index.entry_count == 1
        assert index.get_entry("new.md") is not None
        assert index.get_entry("old.md") is None


class TestReplyMetadataIndexIncrementalUpdate:
    """Tests for incremental updates via ContentMonitor callback."""

    def test_on_reply_change_added(self, temp_dirs, index):
        """New files are indexed on ADDED event."""
        replies_dir, _ = temp_dirs
        index.load()  # Start with empty index

        # Create a new file
        md_file = replies_dir / "new-post.md"
        md_file.write_text("[//]: # (visibility: public)\n\nNew post content.")

        # Trigger callback
        index.on_reply_change(ChangeType.ADDED, str(md_file))

        assert index.entry_count == 1
        entry = index.get_entry("new-post.md")
        assert entry is not None
        assert entry.visibility == "public"
        assert entry.has_content is True

    def test_on_reply_change_edited(self, temp_dirs, index):
        """Edited files are re-indexed on EDITED event."""
        replies_dir, _ = temp_dirs

        # Create initial file
        md_file = replies_dir / "editable.md"
        md_file.write_text("[//]: # (visibility: public)\n\nOriginal content.")
        index.load()

        assert index.get_entry("editable.md").visibility == "public"

        # Edit the file
        md_file.write_text("[//]: # (visibility: unlisted)\n\nUpdated content.")

        # Trigger callback
        index.on_reply_change(ChangeType.EDITED, str(md_file))

        entry = index.get_entry("editable.md")
        assert entry.visibility == "unlisted"

    def test_on_reply_change_deleted(self, temp_dirs, index):
        """Deleted files are removed on DELETED event."""
        replies_dir, _ = temp_dirs

        # Create and index a file
        md_file = replies_dir / "deletable.md"
        md_file.write_text("[//]: # (visibility: public)\n\nContent.")
        index.load()

        assert index.entry_count == 1

        # Delete the file
        md_file.unlink()

        # Trigger callback
        index.on_reply_change(ChangeType.DELETED, str(md_file))

        assert index.entry_count == 0
        assert index.get_entry("deletable.md") is None

    def test_incremental_update_persists(self, temp_dirs, index):
        """Incremental updates are persisted to JSON."""
        replies_dir, state_dir = temp_dirs
        index.load()

        # Add a file
        md_file = replies_dir / "persisted.md"
        md_file.write_text("[//]: # (visibility: public)\n\nContent.")
        index.on_reply_change(ChangeType.ADDED, str(md_file))

        # Create a new index instance and load
        index2 = ReplyMetadataIndex(replies_dir, state_dir)
        index2.load()

        assert index2.entry_count == 1
        assert index2.get_entry("persisted.md") is not None


class TestReplyMetadataIndexDirectAccess:
    """Tests for direct access methods."""

    def test_get_all_entries(self, temp_dirs, index):
        """get_all_entries returns a copy of all entries."""
        replies_dir, _ = temp_dirs
        (replies_dir / "a.md").write_text("[//]: # (visibility: public)\n\nA")
        (replies_dir / "b.md").write_text("[//]: # (visibility: unlisted)\n\nB")
        index.load()

        entries = index.get_all_entries()

        assert len(entries) == 2
        assert "a.md" in entries
        assert "b.md" in entries

        # Verify it's a copy (modifying doesn't affect internal state)
        entries["c.md"] = ReplyMetadata(
            rel_path="c.md",
            reply_to=None,
            like_of=None,
            visibility="public",
            published=None,
            has_content=True,
            title="C",
        )
        assert index.entry_count == 2

    def test_entry_count(self, temp_dirs, index):
        """entry_count returns the number of indexed entries."""
        replies_dir, _ = temp_dirs
        index.load()
        assert index.entry_count == 0

        (replies_dir / "one.md").write_text("# Title\n\nContent.")
        index.on_reply_change(ChangeType.ADDED, str(replies_dir / "one.md"))
        assert index.entry_count == 1


class TestReplyMetadataIndexQueryMethods:
    """Tests for query methods."""

    def test_get_unlisted_slugs(self, temp_dirs, index):
        """get_unlisted_slugs returns root-level unlisted posts."""
        replies_dir, _ = temp_dirs

        # Unlisted post (no reply-to, no like-of, has content, visibility unlisted)
        (replies_dir / "unlisted-post.md").write_text(
            "[//]: # (visibility: unlisted)\n\nUnlisted content."
        )
        # Another unlisted post (default visibility for root replies)
        (replies_dir / "default-unlisted.md").write_text("# Title\n\nContent.")
        # AP reply (has reply-to) - should NOT be included
        (replies_dir / "ap-reply.md").write_text(
            "[//]: # (reply-to: https://example.com)\n\nReply content."
        )
        # Standalone like (no content) - should NOT be included
        (replies_dir / "like-only.md").write_text(
            "[//]: # (like-of: https://example.com/post)"
        )
        # Public post - should NOT be included
        (replies_dir / "public-post.md").write_text(
            "[//]: # (visibility: public)\n\nPublic content."
        )
        # Subdirectory reply - should NOT be included
        subdir = replies_dir / "article"
        subdir.mkdir()
        (subdir / "nested.md").write_text(
            "[//]: # (visibility: unlisted)\n\nNested content."
        )

        index.load()
        slugs = index.get_unlisted_slugs()

        assert sorted(slugs) == ["default-unlisted", "unlisted-post"]

    def test_get_ap_reply_slugs(self, temp_dirs, index):
        """get_ap_reply_slugs returns root-level AP replies."""
        replies_dir, _ = temp_dirs

        # AP reply with public visibility
        (replies_dir / "public-reply.md").write_text(
            "[//]: # (reply-to: https://example.com/post/1)\n"
            "[//]: # (visibility: public)\n\n"
            "My reply."
        )
        # AP reply with unlisted visibility
        (replies_dir / "unlisted-reply.md").write_text(
            "[//]: # (reply-to: https://example.com/post/2)\n"
            "[//]: # (visibility: unlisted)\n\n"
            "My unlisted reply."
        )
        # AP reply with default visibility (public)
        (replies_dir / "default-reply.md").write_text(
            "[//]: # (reply-to: https://example.com/post/3)\n\nDefault reply."
        )
        # AP reply with followers visibility - should NOT be included
        (replies_dir / "followers-reply.md").write_text(
            "[//]: # (reply-to: https://example.com/post/4)\n"
            "[//]: # (visibility: followers)\n\n"
            "Private reply."
        )
        # Unlisted post (no reply-to) - should NOT be included
        (replies_dir / "unlisted-post.md").write_text(
            "[//]: # (visibility: unlisted)\n\nPost content."
        )
        # Like-reply combo without content - should NOT be included
        (replies_dir / "like-only.md").write_text(
            "[//]: # (reply-to: https://example.com/post/5)\n"
            "[//]: # (like-of: https://example.com/post/5)"
        )

        index.load()
        slugs = index.get_ap_reply_slugs()

        assert sorted(slugs) == ["default-reply", "public-reply", "unlisted-reply"]

    def test_get_article_reply_slugs(self, temp_dirs, index):
        """get_article_reply_slugs returns replies for a specific article."""
        replies_dir, _ = temp_dirs

        # Create article subdirectory
        article_dir = replies_dir / "my-article"
        article_dir.mkdir()

        # Public reply
        (article_dir / "reply1.md").write_text(
            "[//]: # (visibility: public)\n\nReply 1."
        )
        # Unlisted reply
        (article_dir / "reply2.md").write_text(
            "[//]: # (visibility: unlisted)\n\nReply 2."
        )
        # Draft reply - should NOT be included
        (article_dir / "draft.md").write_text(
            "[//]: # (visibility: draft)\n\nDraft reply."
        )
        # Root-level file - should NOT be included
        (replies_dir / "root.md").write_text(
            "[//]: # (visibility: public)\n\nRoot content."
        )
        # Different article's reply - should NOT be included
        other_dir = replies_dir / "other-article"
        other_dir.mkdir()
        (other_dir / "other.md").write_text(
            "[//]: # (visibility: public)\n\nOther reply."
        )

        index.load()
        slugs = index.get_article_reply_slugs("my-article")

        assert sorted(slugs) == ["reply1", "reply2"]

    def test_get_like_of_map(self, temp_dirs, index):
        """get_like_of_map returns reverse mapping of like-of targets."""
        replies_dir, _ = temp_dirs

        # Like at root level
        (replies_dir / "like1.md").write_text(
            "[//]: # (like-of: https://example.com/post/A)"
        )
        # Another like for the same target
        (replies_dir / "like2.md").write_text(
            "[//]: # (like-of: https://example.com/post/A)"
        )
        # Like for different target
        (replies_dir / "like3.md").write_text(
            "[//]: # (like-of: https://example.com/post/B)"
        )
        # Like in subdirectory
        subdir = replies_dir / "article"
        subdir.mkdir()
        (subdir / "like4.md").write_text(
            "[//]: # (like-of: https://example.com/post/C)"
        )
        # File without like-of - should NOT appear
        (replies_dir / "no-like.md").write_text("# Just content\n\nNo like.")

        index.load()
        like_map = index.get_like_of_map()

        assert len(like_map) == 3
        assert len(like_map["https://example.com/post/A"]) == 2
        assert len(like_map["https://example.com/post/B"]) == 1
        assert len(like_map["https://example.com/post/C"]) == 1

        # Check structure of entries
        entry = like_map["https://example.com/post/B"][0]
        assert entry["slug"] == "like3"
        assert entry["rel_path"] == "like3.md"
        assert entry["source_url"] == "/reply/like3"
        assert entry["type"] == "like"

        # Check subdirectory entry
        entry = like_map["https://example.com/post/C"][0]
        assert entry["slug"] == "like4"
        assert entry["rel_path"] == "article/like4.md"
        assert entry["source_url"] == "/reply/article/like4"

    def test_get_likes_for_target(self, temp_dirs, index):
        """get_likes_for_target returns likes for a specific URL."""
        replies_dir, _ = temp_dirs

        target_url = "https://example.com/post/target"
        other_url = "https://example.com/post/other"

        (replies_dir / "like1.md").write_text(f"[//]: # (like-of: {target_url})")
        (replies_dir / "like2.md").write_text(f"[//]: # (like-of: {target_url})")
        (replies_dir / "like3.md").write_text(f"[//]: # (like-of: {other_url})")

        index.load()
        likes = index.get_likes_for_target(target_url)

        assert len(likes) == 2
        slugs = [like["slug"] for like in likes]
        assert sorted(slugs) == ["like1", "like2"]

        # Check non-existent target
        assert index.get_likes_for_target("https://nowhere.com") == []
