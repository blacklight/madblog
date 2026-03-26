# 01 — Research: Reply Metadata Index

## Goal

Replace per-request full-directory scans of `replies/` with a single,
general-purpose, JSON-persisted metadata index keyed by slug. The index
should be usable for any current or future lookup that depends on reply
file metadata, and should subsume existing purpose-built indices that
duplicate the same work.

---

## 1. Existing indices

### 1.1 `AuthorReactionsIndex` (`madblog/reactions.py:575-748`)

- **Purpose:** reverse index `target_url → [reaction_info]` so article
  pages can show "author liked this" without scanning all reply files.
- **Storage:** `<state_dir>/author_reactions_index.json`
- **Key stored per entry:** `type` ("like"), `source_url` ("/reply/…"),
  `source_file` (relative path).
- **Full scan:** `replies_dir.rglob("*.md")` — reads only the metadata
  block of each file (`_extract_like_of` stops at the first `# ` heading).
- **Incremental update:** `on_reply_change()` callback registered on
  `replies_monitor` (`ContentMonitor`).
- **Query API:** `get_reactions(target_url) -> list[dict]`.
- **Observation:** this index reads only one metadata field (`like-of`).
  A general-purpose index that stores *all* metadata fields per slug
  can derive the same reverse mapping at query time.

### 1.2 `TagIndex` (`madblog/tags/_index.py`)

- **Purpose:** `tag → [post_info]` mapping for the `/tags` page.
- **Scope:** `pages_dir` only (articles), not `replies/`.
- **Storage:** `<state_dir>/cache/tags-index.json`
- **Key stored per entry:** path, title, description, published,
  per-source tag counts.
- **Full scan:** `os.walk(pages_dir)` at startup. Uses mtime-based
  skip for unchanged files.
- **Incremental update:** `reindex_file()` called from
  `content_monitor` callback.
- **Observation:** operates on a different directory (`pages_dir`),
  different monitor (`content_monitor`), and stores tag-specific data.
  Not a candidate for migration into the reply metadata index.

---

## 2. Full-scan patterns in `replies/`

All of these are in `madblog/replies/_mixin.py` and scan `replies/`
root-level `*.md` files on every invocation:

### 2.1 `get_unlisted_posts()` (line 194–257)

- **When called:** every request to `/unlisted` (default "Posts" tab).
- **What it does per file:**
  1. `_parse_reply_metadata(None, slug)` — opens file, reads metadata
     block, derives `reply-to` from directory structure.
  2. `_parse_markdown_content(f)` — reads full file content.
  3. Filters: skip if `reply-to` or `like-of` present, skip if empty,
     skip if visibility ≠ UNLISTED.
  4. `_build_unlisted_post_dict()` → calls `render_html()` (CPU-heavy
     Markdown→HTML rendering).
- **Cost:** O(N) file reads + O(K) markdown renders per request.

### 2.2 `get_ap_replies()` (line 259–325)

- **When called:** every request to `/unlisted?tab=posts_and_replies`.
- **What it does per file:**
  1. `_parse_reply_metadata(None, slug)` — same as above.
  2. `_parse_markdown_content(f)` — full content read.
  3. Filters: skip if no `reply-to`, skip standalone likes, skip if
     empty, skip if visibility ∉ {PUBLIC, UNLISTED}.
  4. `_build_unlisted_post_dict()` → `render_html()`.
- **Cost:** O(N) file reads + O(K) markdown renders per request.

### 2.3 `_get_article_replies(article_slug)` (line 71–154)

- **When called:** for every article page render and every reply page
  render (via `_get_page_interactions` and `_get_reply_interactions`).
- **Scope:** when `article_slug` is None, scans `replies/` root
  (same as 2.1/2.2). When non-None, scans `replies/<article_slug>/`.
- **What it does per file:**
  1. `_parse_reply_metadata()` — metadata read.
  2. `_parse_markdown_content(f)` — full content read.
  3. Filters: visibility, standalone likes.
  4. `render_html()` on content.
- **Cost:** same as above. Called with `article_slug=None` in
  `_get_reply_interactions` when rendering individual reply pages
  for root-level replies.

### 2.4 `_get_unlisted_articles()` (line 327–376)

- **When called:** from `get_unlisted_posts()`.
- **Scope:** `pages_dir.rglob("*.md")` — scans all articles.
- **What it does per file:**
  1. `_parse_page_metadata(rel_path)` — full metadata parse.
  2. Filters: visibility ≠ UNLISTED → skip.
  3. `_parse_markdown_content(f)` + `_build_unlisted_post_dict()`.
- **Observation:** this scans `pages_dir`, not `replies/`. The number
  of articles is typically small, but it still does full content reads
  for all articles just to find the unlisted ones. Could benefit from
  the same indexing approach, but on a different directory/monitor.

### 2.5 `AuthorReactionsIndex._full_scan()` (reactions.py:635–642)

- **When called:** first startup (no index file on disk).
- **Scope:** `replies_dir.rglob("*.md")` — all reply files recursively.
- **What it does:** reads only the metadata block of each file to
  extract `like-of`. Lightweight.

### 2.6 `sync_replies_on_startup()` (activitypub/_replies.py:480–497)

- **When called:** app startup.
- **Scope:** `replies_dir.rglob("*.md")` via `_sync_directory`.
- **What it does:** checks mtime against cached values, calls
  `on_reply_change()` for new/modified files (which triggers AP
  publishing). This is a startup-only path and doesn't benefit from
  the metadata index (it needs to check mtime, not metadata).

---

## 3. What metadata fields are needed?

Combining the filter criteria from all scan patterns:

| Field | Used by | Extraction cost |
|-------|---------|-----------------|
| `reply-to` | 2.1, 2.2, 2.3 | metadata block only |
| `like-of` | 2.1, 2.2, 2.3, `AuthorReactionsIndex` | metadata block only |
| `visibility` | 2.1, 2.2, 2.3 | metadata block only |
| `published` | 2.1, 2.2, 2.3 (sorting) | metadata block only |
| `title` | 2.1, 2.2 (display) | metadata block or first `# ` heading |
| `has_content` | 2.1, 2.2, 2.3 | requires reading past metadata block |

All fields except `has_content` can be extracted from just the metadata
block (first few lines of the file, stopping at the first `# ` heading
or non-metadata line). The `has_content` flag requires checking whether
there are non-empty, non-metadata lines after the metadata block — but
this does **not** require full parsing or rendering. A simple scan for
the first non-blank, non-comment line after the metadata block suffices.

---

## 4. Proposed design: `ReplyMetadataIndex`

### 4.1 Scope

**Root-level `replies/*.md` files only** (not recursive). This covers:
- Unlisted posts (2.1)
- AP replies (2.2)
- Root-level article replies when `article_slug=None` (2.3)

Sub-directory replies (`replies/<article_slug>/*.md`) are bounded per
article and loaded on-demand per article page. These don't need
indexing — the set is small per directory.

**`pages_dir` articles** (2.4) can optionally be covered by a second
index instance or a shared base class. The scan pattern is the same
(metadata extraction + visibility filter), but the directory and monitor
are different. We address this in the plan.

### 4.2 On-disk format

```json
{
  "schema_version": 1,
  "entries": {
    "my-unlisted-post": {
      "reply_to": null,
      "like_of": null,
      "visibility": "unlisted",
      "published": "2025-03-26T10:00:00+00:00",
      "has_content": true,
      "title": "My unlisted post"
    },
    "fedi-reply-42": {
      "reply_to": "https://mastodon.social/@user/123",
      "like_of": null,
      "visibility": "public",
      "published": "2025-03-25T08:30:00+00:00",
      "has_content": true,
      "title": "fedi-reply-42"
    },
    "standalone-like": {
      "reply_to": null,
      "like_of": "https://example.com/article/cool-post",
      "visibility": "public",
      "published": "2025-03-24T12:00:00+00:00",
      "has_content": false,
      "title": null
    }
  }
}
```

### 4.3 Lifecycle

1. **Startup:** load from JSON. If missing or schema mismatch, full
   scan of `replies/*.md` root-level files, persist.
2. **Runtime:** `on_reply_change(change_type, filepath)` callback
   registered on `replies_monitor`. On create/edit: re-extract metadata
   for that file. On delete: remove entry. Always persist.
3. **Query:** in-memory dict filter — O(1) per slug, no filesystem I/O.

### 4.4 Query methods

```python
def get_unlisted_slugs(self) -> list[str]:
    """Slugs matching: no reply_to, no like_of, has_content, visibility=UNLISTED."""

def get_ap_reply_slugs(self) -> list[str]:
    """Slugs matching: reply_to set, has_content, visibility in (PUBLIC, UNLISTED)."""

def get_like_of_targets(self) -> dict[str, list[dict]]:
    """Reverse mapping: target_url → [{source_slug, source_url}].
    Replaces AuthorReactionsIndex."""
```

### 4.5 Subsumption of `AuthorReactionsIndex`

The general index stores `like_of` per slug. The reverse mapping
`target_url → [sources]` currently provided by `AuthorReactionsIndex`
can be derived at query time or maintained as a secondary in-memory
dict rebuilt whenever the primary index changes. This eliminates the
separate `author_reactions_index.json` file and the separate scan.

**Important difference:** `AuthorReactionsIndex` scans **recursively**
(`rglob`), covering sub-directory replies too (`replies/<article>/`).
The new index must also cover these for `like_of` lookups. Two options:

1. **Index all reply files recursively** — simpler, one index covers
   everything. The index grows with all reply files, not just root ones.
2. **Index root-level only, keep sub-directory likes separate** — more
   complex, smaller index.

Recommendation: **Option 1** (recursive). The metadata per entry is
tiny (~100 bytes JSON), and the extraction is cheap (metadata block
only). Even with thousands of reply files, the index stays small.
The `like_of` reverse mapping becomes a derived view over the same
data. For non-`like_of` queries (unlisted, AP replies), we filter by
directory depth (root-level = no `/` in the relative path).

### 4.6 Coverage of `_get_unlisted_articles()`

`_get_unlisted_articles()` scans `pages_dir` for articles with
`visibility: unlisted`. This is a different directory with a different
monitor (`content_monitor`). Options:

1. **Separate index instance** — same `ReplyMetadataIndex` class,
   instantiated for `pages_dir`, registered on `content_monitor`.
   Stores visibility + published + title for all articles. Query:
   `get_unlisted_article_slugs()`.
2. **Leave as-is** — the number of articles is typically small and
   bounded by the author's writing rate, not external interactions.

Recommendation: **Option 1** if we want consistency, but the scope
(articles) is architecturally distinct. A better approach: extract
a shared base class (`FileMetadataIndex`) that can be instantiated
for any directory, with configurable metadata extraction. Then:
- `ReplyMetadataIndex` = `FileMetadataIndex(replies_dir, recursive=True)`
- `ArticleMetadataIndex` = `FileMetadataIndex(pages_dir, recursive=True)`

Both use the same code, different directories, different monitors.

### 4.7 What about `_get_article_replies(article_slug)`?

This scans `replies/<article_slug>/*.md` — a single sub-directory.
With a recursive index over all of `replies/`, we can filter entries
by their relative path prefix to get replies for a specific article.
This would eliminate the per-article scan too.

However, `_get_article_replies` also reads full content and renders
HTML. The index only avoids the *scan* — rendering still happens at
request time for matching files. The benefit is smaller: we skip
non-matching files without opening them, but all matching files still
need full reads.

For sub-directory replies, the set is small per article, so the
benefit of indexing is marginal. The main win is for root-level scans
where the total file count is high.

---

## 5. Summary of consumers to migrate

| Consumer | Current pattern | After index |
|----------|----------------|-------------|
| `get_unlisted_posts()` | scan `replies/*.md` | query index → read+render only matching slugs |
| `get_ap_replies()` | scan `replies/*.md` | query index → read+render only matching slugs |
| `_get_article_replies(None)` | scan `replies/*.md` | query index → read+render only matching slugs |
| `AuthorReactionsIndex` | separate JSON index + scan | subsumed by `like_of` field in general index |
| `_get_unlisted_articles()` | scan `pages_dir/**/*.md` | optional: second index instance on `pages_dir` |
| `_get_article_replies(slug)` | scan `replies/<slug>/*.md` | optional: filter recursive index by prefix |

---

## 6. Metadata extraction function

The lightweight metadata reader already exists in two places:

- `_parse_metadata_fast()` in `madblog/tags/_index.py:103-117` — reads
  metadata block, stops at `# ` heading or non-metadata line.
- `ActivityPubIntegration._parse_metadata()` in
  `madblog/activitypub/_integration.py:252-279` — same pattern, also
  parses `published` as datetime.

Both are essentially the same. The new index should use a shared
utility (or reuse one of these) plus a `has_content` check that scans
for the first non-blank, non-comment line after the metadata block.

---

## 7. Risk assessment

- **Stale index:** mitigated by `ContentMonitor` incremental updates.
  Same risk as `AuthorReactionsIndex` (proven pattern).
- **Schema migration:** bump `schema_version` → triggers full rescan.
  Low risk, same pattern as `TagIndex`.
- **Thread safety:** use `threading.Lock`, same as existing indices.
- **Startup cost:** one-time full scan if no index on disk. Same as
  `AuthorReactionsIndex`. Metadata-only extraction is fast.
- **Breaking change for `AuthorReactionsIndex`:** the old
  `author_reactions_index.json` becomes obsolete. Migration: delete
  old file (or ignore it) — the new index rebuilds on first run.
