# Implementation Summary: Reply Metadata Index

## Overview

Implemented a general-purpose `ReplyMetadataIndex` class that provides O(1)
metadata lookups for reply files, eliminating per-request full directory scans.

## Files Changed

### New Files

- `madblog/replies/_index.py` — Core `ReplyMetadataIndex` class
  - `ReplyMetadata` dataclass for per-file metadata
  - JSON persistence with schema versioning
  - `ContentMonitor` callback integration
  - Query methods for unlisted posts, AP replies, article replies, and likes

- `tests/test_reply_metadata_index.py` — 22 tests covering:
  - Metadata extraction (8 tests)
  - Persistence and loading (3 tests)
  - Incremental updates (4 tests)
  - Direct access methods (2 tests)
  - Query methods (5 tests)

### Modified Files

- `madblog/replies/__init__.py` — Export `ReplyMetadata`, `ReplyMetadataIndex`
- `madblog/app.py` — Instantiate and wire `ReplyMetadataIndex`:
  - Added import
  - Created instance in `__init__`
  - Load index in `start()`
  - Register callback with `replies_monitor`
- `madblog/markdown/_mixin.py` — Migrate `author_likes` lookup to use
  `reply_metadata_index.get_likes_for_target()` instead of
  `author_reactions_index.get_reactions()`
- `madblog/replies/_mixin.py` — Same migration for reply pages
- `tests/test_author_reactions_index.py` — Add `reply_metadata_index` setup
  to template tests
- `docs/ARCHITECTURE.md` — Document `ReplyMetadataIndex` in Author Replies section
- `CHANGELOG.md` — Add Unreleased section with feature entry

## Index Storage

Location: `<state_dir>/reply_metadata_index.json`

```json
{
  "schema_version": 1,
  "entries": {
    "my-post.md": {
      "rel_path": "my-post.md",
      "reply_to": null,
      "like_of": null,
      "visibility": "unlisted",
      "published": "2025-03-26T10:00:00+00:00",
      "has_content": true,
      "title": "My Post"
    }
  }
}
```

## Query Methods

| Method | Purpose |
|--------|---------|
| `get_unlisted_slugs()` | Root-level files: no reply_to/like_of, has_content, visibility=unlisted |
| `get_ap_reply_slugs()` | Root-level files: reply_to set, has_content, visibility public/unlisted |
| `get_article_reply_slugs(slug)` | Replies under `replies/<slug>/` |
| `get_likes_for_target(url)` | Reverse lookup for author likes |
| `get_like_of_map()` | Full reverse mapping of like targets |

## Test Results

- 576 tests pass (22 new for ReplyMetadataIndex)
- pre-commit clean (black, flake8)

## Follow-ups

Documented in `99-FOLLOW-UP.md`.
