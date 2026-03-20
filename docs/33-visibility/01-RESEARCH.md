# Research: Visibility Model for Author Posts

## Current State Analysis

### 1. Blog Index Filtering

**Location:** `madblog/app.py` — `_get_pages_from_files()` and `get_pages()`

Currently, all Markdown files under `pages_dir` are included in the index. The only exclusions are:
- Files under `replies/` directory (excluded via `os.walk` filtering)
- `index.md` files (used for folder metadata)

There is no visibility-based filtering for the blog index.

### 2. Unlisted Posts

**Location:** `madblog/replies/_mixin.py` — `get_unlisted_posts()`

Current definition of "unlisted":
- Files at root level of `replies/` directory
- Have content (not empty)
- No `reply-to` or `like-of` metadata

These are displayed on `/unlisted` page but excluded from the blog index.

### 3. ActivityPub Publishing

**Location:** `madblog/activitypub/_integration.py` — `build_object()`

Current addressing (hardcoded public):
```python
obj = Object(
    ...
    to=["https://www.w3.org/ns/activitystreams#Public"],
    cc=[self.handler.followers_url] + mention_cc,
    ...
)
```

**Location:** `madblog/activitypub/_replies.py` — `build_reply_object()`

Same pattern for replies:
```python
obj = Object(
    ...
    to=["https://www.w3.org/ns/activitystreams#Public"],
    cc=cc_list,  # includes followers_url + mentions
    ...
)
```

### 4. Reactions Display

**Location:** `madblog/templates/reactions.html`

Author replies are displayed in reactions section. The `is_unlisted` flag affects heading visibility but not filtering.

### 5. Configuration System

**Location:** `madblog/config.py`

Config parameters are defined in the `Config` dataclass with:
- Default values
- Loading from YAML file (`_init_config_from_file`)
- Loading from environment (`_init_config_from_env`)

### 6. Metadata Parsing

**Location:** `madblog/markdown/_mixin.py` — `_parse_page_metadata()`

Metadata is extracted from `[//]: # (key: value)` comment format at the top of Markdown files.

---

## ActivityPub Visibility Addressing

Based on ActivityPub spec and common implementations (Mastodon, etc.):

| Visibility | `to` field | `cc` field | Federated? |
|------------|------------|------------|------------|
| **public** | `[AS_PUBLIC]` | `[followers_url] + mentions` | Yes |
| **unlisted** | `[followers_url]` | `[AS_PUBLIC] + mentions` | Yes |
| **followers** | `[followers_url]` | `mentions` | Yes |
| **direct** | `mentions` | `[]` | Yes |
| **draft** | N/A | N/A | No |

Where:
- `AS_PUBLIC = "https://www.w3.org/ns/activitystreams#Public"`
- `followers_url = "{base_url}/ap/actor/followers"`

**Key difference:**
- **public**: Appears in public timelines and federated timelines
- **unlisted**: Visible if you have the link, but not in public/federated timelines
- **followers**: Only delivered to followers' home timelines
- **direct**: Only delivered to mentioned actors' inboxes

---

## Proposed Approach

### 1. Visibility Enum

Create a `Visibility` enum in a new module (`madblog/visibility.py`):

```python
from enum import Enum

class Visibility(str, Enum):
    PUBLIC = "public"
    UNLISTED = "unlisted"
    FOLLOWERS = "followers"
    DIRECT = "direct"
    DRAFT = "draft"
```

### 2. Configuration Parameter

Add `default_visibility` to `Config`:
- Default: `"public"`
- YAML: `default_visibility: public|unlisted|followers|direct|draft`
- Env: `MADBLOG_DEFAULT_VISIBILITY`

### 3. Metadata Parameter

Support `visibility` in Markdown metadata:
```markdown
[//]: # (visibility: unlisted)
```

### 4. Visibility Resolution

Create a helper function to resolve effective visibility:
1. Check post metadata for `visibility`
2. Fall back to `config.default_visibility`
3. For unlisted replies (root of `replies/` without `reply-to`/`like-of`), default to `unlisted`

### 5. Blog Index Filtering

Modify `_get_pages_from_files()` to:
- Parse visibility from metadata
- Exclude non-`public` posts from index
- Note: This requires parsing metadata during listing (currently done)

### 6. Unlisted Page Changes

Modify `get_unlisted_posts()` to:
- Include articles with `visibility: unlisted`
- Include replies with `visibility: unlisted`
- Current unlisted behavior becomes the default for root replies

### 7. Reactions Filtering

Modify reaction rendering to:
- Exclude `followers`, `direct`, and `draft` visibility replies from `reactions.html`

### 8. ActivityPub Addressing

Modify `build_object()` and `build_reply_object()` to:
- Accept visibility parameter
- Build `to`/`cc` fields based on visibility level
- For `direct` visibility, only include mentioned actors in `to`

### 9. Feed Filtering

Modify feed generation to:
- Exclude non-`public` posts from RSS/Atom feeds

---

## Files to Modify

| File | Changes |
|------|---------|
| `madblog/visibility.py` | **New** — Visibility enum and helpers |
| `madblog/config.py` | Add `default_visibility` parameter |
| `madblog/markdown/_mixin.py` | Parse `visibility` metadata |
| `madblog/app.py` | Filter index by visibility |
| `madblog/replies/_mixin.py` | Update unlisted logic, filter reactions |
| `madblog/activitypub/_integration.py` | Visibility-based addressing |
| `madblog/activitypub/_replies.py` | Visibility-based addressing for replies |
| `madblog/routes.py` | Update unlisted route, feed filtering |
| `tests/` | New tests for visibility behavior |

---

## Edge Cases and Considerations

### 1. Existing Unlisted Replies

Current unlisted replies (root of `replies/` without `reply-to`/`like-of`) should maintain their behavior. The new visibility model should treat them as `visibility: unlisted` by default.

### 2. Direct Messages Without Mentions

A `visibility: direct` post without any `@mentions` would have an empty `to` field. This should either:
- Warn the user / log an error
- Fall back to `followers` visibility
- Or simply be a "self-only" post (delivered nowhere)

**Recommendation:** Log a warning but allow it (posts to nobody).

### 3. Draft Posts

Draft posts (`visibility: draft`) are:
- **Not listed** on the blog index
- **Not shown** on `/unlisted` page
- **Not rendered** in `reactions.html`
- **Not federated** via ActivityPub
- **Accessible** via direct URL (e.g., `/article/my-draft` or `/reply/my-draft`)

This allows authors to preview content before publishing. Changing from `draft` to any other visibility will trigger normal ActivityPub publishing.

### 4. Followers-Only Articles

These are accessible via direct URL but not listed. Need to ensure:
- No HTTP caching that would expose content
- Consider adding access control (but this is out of scope — visibility is about federation/listing, not access control)

### 5. Re-publishing on Visibility Change

If a post's visibility changes, should we send Update activities? Yes — the normal content change flow handles this.

### 6. Interactions on Non-Public Posts

Incoming interactions (replies, likes) on `followers`/`direct` posts should still be stored and displayed to the author. The visibility affects outbound publishing, not inbound interaction handling.

---

## Questions for User Review

1. **Default for existing unlisted replies:** Should they explicitly get `visibility: unlisted` semantics (hidden from index, shown on `/unlisted`), or should this only apply to posts with explicit `visibility` metadata?
   
   **Current assumption:** Maintain backward compatibility — root replies without `reply-to`/`like-of` default to `unlisted`.

2. **RSS/Atom feeds:** Should we expose `unlisted` posts in feeds, or only `public`?
   
   **Current assumption:** Only `public` posts in feeds.

3. **Direct without mentions:** What behavior is expected?
   
   **Current assumption:** Log warning, publish to nobody (valid use case: drafts visible on blog but not federated).
