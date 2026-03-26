# 02 — Plan: Reply Metadata Index

Based on the research in [01-RESEARCH.md](01-RESEARCH.md), this document
outlines the phased implementation plan.

---

## Phase 1: Core `ReplyMetadataIndex` class

**Goal:** Create the index class with JSON persistence and incremental
updates via `ContentMonitor`.

### 1.1 New file: `madblog/replies/_index.py`

```python
class ReplyMetadataIndex:
    """
    JSON-persisted metadata index for reply files.
    
    Stores per-slug metadata extracted from the Markdown header block,
    enabling O(1) lookups without filesystem scans.
    """
    
    def __init__(self, replies_dir: Path, state_dir: Path):
        ...
    
    # Lifecycle
    def load(self) -> None: ...
    def _full_scan(self) -> None: ...
    def _save(self) -> None: ...
    
    # ContentMonitor callback
    def on_reply_change(self, change_type: ChangeType, filepath: str) -> None: ...
    
    # Metadata extraction (metadata block only, no full content read)
    def _extract_metadata(self, filepath: str) -> dict | None: ...
```

### 1.2 Stored fields per entry

```python
@dataclass
class ReplyMetadata:
    slug: str               # filename stem (e.g. "my-post")
    rel_path: str           # relative path from replies_dir (e.g. "my-post.md" or "article/reply.md")
    reply_to: str | None    # explicit reply-to URL, or None
    like_of: str | None     # like-of URL, or None
    visibility: str         # "public", "unlisted", "followers", "direct", "draft"
    published: datetime | None
    has_content: bool       # True if file has non-metadata content
    title: str | None       # from metadata or first # heading
```

### 1.3 On-disk format

```json
{
  "schema_version": 1,
  "entries": {
    "my-post.md": { ... },
    "article/reply.md": { ... }
  }
}
```

Key = relative path (not slug) to handle sub-directories unambiguously.

### 1.4 Tests

- `tests/test_reply_metadata_index.py`
  - Index creation and full scan
  - Incremental update (add, edit, delete)
  - JSON persistence and reload
  - Schema version mismatch triggers rescan

---

## Phase 2: Query methods

**Goal:** Add query methods that replace full-scan patterns.

### 2.1 Methods

```python
def get_unlisted_slugs(self) -> list[str]:
    """
    Root-level files with:
    - No reply_to
    - No like_of
    - has_content = True
    - visibility = "unlisted"
    """

def get_ap_reply_slugs(self) -> list[str]:
    """
    Root-level files with:
    - reply_to is set
    - has_content = True
    - visibility in ("public", "unlisted")
    """

def get_article_reply_slugs(self, article_slug: str) -> list[str]:
    """
    Files under replies/<article_slug>/ matching visibility rules.
    """

def get_like_of_map(self) -> dict[str, list[dict]]:
    """
    Reverse mapping: target_url -> [{slug, source_url, ...}].
    Replaces AuthorReactionsIndex.get_reactions().
    """

def get_entry(self, rel_path: str) -> ReplyMetadata | None:
    """Direct lookup by relative path."""
```

### 2.2 Tests

- Query method correctness
- Edge cases: empty index, no matches, mixed visibility

---

## Phase 3: Integration with `BlogApp`

**Goal:** Wire the index into the application lifecycle.

### 3.1 Changes to `madblog/app.py`

- Instantiate `ReplyMetadataIndex` in `BlogApp.__init__`
- Register `on_reply_change` callback with `replies_monitor`
- Call `load()` in `BlogApp.start()`

### 3.2 Changes to `madblog/replies/_mixin.py`

- Add `reply_metadata_index` property (lazy access to `BlogApp` instance)
- Modify `get_unlisted_posts()`:
  - Query `get_unlisted_slugs()` → get list of slugs
  - Only read/render those files (no scan)
- Modify `get_ap_replies()`:
  - Query `get_ap_reply_slugs()` → get list of slugs
  - Only read/render those files
- Modify `_get_article_replies(article_slug)`:
  - When `article_slug` is None: query `get_unlisted_slugs()` + visibility filter
  - When set: query `get_article_reply_slugs(article_slug)` or keep scan (small set)

### 3.3 Tests

- Integration test: index wired correctly, queries return expected results
- Verify no regression in `/unlisted` route behavior

---

## Phase 4: Subsume `AuthorReactionsIndex`

**Goal:** Replace the separate `author_reactions_index.json` with the
`like_of` field in `ReplyMetadataIndex`.

### 4.1 Changes

- Remove `madblog/reactions.py` class `AuthorReactionsIndex`
- Remove `author_reactions_index.json` file (or ignore it)
- Update `BlogApp` to use `ReplyMetadataIndex.get_like_of_map()` instead
- Update consumers:
  - `_render_reply_html()` → use new method
  - `render_article()` → use new method
  - Template contexts that receive `author_likes`

### 4.2 Migration

- On first run after upgrade: new index rebuilds from scratch
- Old `author_reactions_index.json` can be deleted or left alone (ignored)

### 4.3 Tests

- Verify `author_likes` still works on article and reply pages
- Verify no duplicate data

---

## Phase 5: Optional — Article visibility index

**Goal:** Apply the same pattern to `pages_dir` to optimize
`_get_unlisted_articles()`.

### 5.1 Option A: Shared base class

Extract `FileMetadataIndex` base class, instantiate separately for
`pages_dir` with `content_monitor`.

### 5.2 Option B: Defer

If article count is small and scan cost is acceptable, defer this
optimization to a follow-up.

### 5.3 Decision

Defer to follow-up. The article set is author-bounded (small), while
the reply set grows with external interactions (unbounded). Prioritize
reply index.

---

## Phase 6: Documentation and cleanup

### 6.1 Updates

- `docs/ARCHITECTURE.md` — add `ReplyMetadataIndex` section
- `CHANGELOG.md` — add entry under Unreleased
- Remove or deprecate `AuthorReactionsIndex` references

### 6.2 State schema version

If we add a new index file, no schema version bump is needed (new file).
If we modify an existing file format, bump schema version.

---

## Summary of phases

| Phase | Description | Files changed |
|-------|-------------|---------------|
| 1 | Core index class | `replies/_index.py` (new), tests |
| 2 | Query methods | `replies/_index.py`, tests |
| 3 | Integration with BlogApp | `app.py`, `replies/_mixin.py`, tests |
| 4 | Subsume AuthorReactionsIndex | `reactions.py`, `app.py`, templates, tests |
| 5 | (Deferred) Article visibility index | — |
| 6 | Documentation | `ARCHITECTURE.md`, `CHANGELOG.md` |

---

## Open questions

1. **Derived `reply-to` from directory structure:** Currently
   `_parse_reply_metadata()` derives `reply-to` for sub-directory replies
   if not explicitly set. Should the index store the *derived* value or
   only the *explicit* one?
   
   **Recommendation:** Store explicit only. Derivation is directory-based
   and can be computed at query time from `rel_path`.

2. **Thread safety:** Use `threading.RLock` (same as `TagIndex`).

3. **Index file location:** `<state_dir>/reply_metadata_index.json`
