# Implementation Plan: Visibility Model for Author Posts

## Overview

This plan implements a visibility model for author posts with five levels: `public`, `unlisted`, `followers`, `direct`, and `draft`. The implementation is split into phases for manageable review cycles.

---

## Phase 1: Core Visibility Infrastructure

**Goal:** Add the `Visibility` enum, configuration parameter, and metadata parsing.

### Tasks

1. **Create `madblog/visibility.py`**
   - Define `Visibility` enum with `PUBLIC`, `UNLISTED`, `FOLLOWERS`, `DIRECT`, `DRAFT`
   - Add `resolve_visibility()` helper that:
     - Takes metadata dict and optional is_unlisted_reply flag
     - Returns effective visibility (metadata → config default → special cases)

2. **Update `madblog/config.py`**
   - Add `default_visibility: str = "public"` to `Config` dataclass
   - Add loading from YAML in `_init_config_from_file()`
   - Add loading from env var `MADBLOG_DEFAULT_VISIBILITY` in `_init_config_from_env()`

3. **Update `madblog/markdown/_mixin.py`**
   - Parse `visibility` from metadata (already extracted via regex, just needs to be kept)
   - Ensure it's included in returned metadata dict

4. **Add tests**
   - `tests/test_visibility.py`: Test `Visibility` enum and `resolve_visibility()`
   - Update config tests for `default_visibility`

---

## Phase 2: Blog Index Filtering

**Goal:** Filter non-public posts from the blog index.

### Tasks

1. **Update `madblog/app.py`**
   - Modify `_build_page_entry()` to include visibility in page dict
   - Modify `_get_pages_from_files()` to filter out non-`public` posts
   - Alternatively, filter in `get_pages()` after collecting all pages

2. **Add tests**
   - Test that `public` articles appear in index
   - Test that `unlisted`/`followers`/`direct` articles are excluded from index

---

## Phase 3: Unlisted Page Enhancement

**Goal:** Include visibility-unlisted articles on the `/unlisted` page.

### Tasks

1. **Update `madblog/replies/_mixin.py`**
   - Modify `get_unlisted_posts()` to also scan `pages_dir` for articles with `visibility: unlisted`
   - Maintain backward compatibility: root replies without `reply-to`/`like-of` still count as unlisted

2. **Update `madblog/routes.py`**
   - No changes needed if `get_unlisted_posts()` returns the combined list

3. **Add tests**
   - Test that articles with `visibility: unlisted` appear on `/unlisted`
   - Test that existing unlisted replies still work

---

## Phase 4: Reactions Filtering

**Goal:** Hide `followers`, `direct`, and `draft` visibility replies from `reactions.html`.

### Tasks

1. **Update `madblog/replies/_mixin.py`**
   - Modify `_get_article_replies()` to filter out `followers`/`direct`/`draft` visibility replies
   - Modify any other reply-fetching methods that feed into reactions

2. **Add tests**
   - Test that `public`/`unlisted` replies appear in reactions
   - Test that `followers`/`direct`/`draft` replies are hidden from reactions

---

## Phase 5: ActivityPub Addressing

**Goal:** Implement visibility-based `to`/`cc` addressing for federation.

### Tasks

1. **Update `madblog/activitypub/_integration.py`**
   - Add `_build_addressing()` method that takes visibility and mentions
   - Modify `build_object()` to:
     - Parse visibility from metadata
     - Call `_build_addressing()` for `to`/`cc` fields

2. **Update `madblog/activitypub/_replies.py`**
   - Modify `build_reply_object()` similarly
   - Special handling: replies inherit parent visibility? Or use their own?
   - **Decision:** Each post has its own visibility; replies use their own metadata

3. **Addressing logic:**
   ```python
   def _build_addressing(self, visibility: Visibility, mention_cc: list[str]) -> tuple[list[str], list[str]] | None:
       AS_PUBLIC = "https://www.w3.org/ns/activitystreams#Public"
       followers_url = self.handler.followers_url
       
       if visibility == Visibility.DRAFT:
           return None  # Do not federate
       elif visibility == Visibility.PUBLIC:
           return [AS_PUBLIC], [followers_url] + mention_cc
       elif visibility == Visibility.UNLISTED:
           return [followers_url], [AS_PUBLIC] + mention_cc
       elif visibility == Visibility.FOLLOWERS:
           return [followers_url], mention_cc
       elif visibility == Visibility.DIRECT:
           return mention_cc, []
   ```

4. **Skip federation for drafts:**
   - `on_content_change()` should check visibility before publishing
   - If visibility is `draft`, skip ActivityPub publishing entirely

5. **Add tests**
   - Test `to`/`cc` fields for each visibility level
   - Test that mentions are correctly included
   - Test that `draft` posts are not federated

---

## Phase 6: Feed Filtering

**Goal:** Exclude non-public posts from RSS/Atom feeds.

### Tasks

1. **Update `madblog/routes.py`**
   - Modify `_get_feed()` to filter pages by visibility
   - Only include `public` visibility posts

2. **Add tests**
   - Test that feed only contains `public` posts

---

## Phase 7: Documentation and Cleanup

**Goal:** Update documentation and ensure consistency.

### Tasks

1. **Update `README.md`**
   - Document `default_visibility` configuration
   - Document `visibility` metadata parameter
   - Explain visibility levels and their effects

2. **Update `docs/ARCHITECTURE.md`**
   - Add section on visibility model
   - Document affected components

3. **Update `CHANGELOG.md`**
   - Add entry under _Unreleased_

---

## Testing Strategy

Each phase includes unit tests. Integration tests should cover:

1. **End-to-end visibility flow:**
   - Create article with `visibility: followers`
   - Verify not in index, not in feeds, not on `/unlisted`
   - Verify AP object has correct addressing

2. **Backward compatibility:**
   - Existing unlisted replies continue to work
   - Posts without visibility metadata use `default_visibility`

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing unlisted behavior | Explicit backward-compat handling in `resolve_visibility()` |
| Performance impact from filtering | Filtering happens in Python, not FS; impact should be minimal |
| Confusing UX for direct messages | Log warning when `direct` has no mentions |

---

## Acceptance Criteria

- [ ] `default_visibility` config parameter works (YAML + env)
- [ ] `visibility` metadata is parsed correctly
- [ ] Blog index only shows `public` posts
- [ ] `/unlisted` shows `unlisted` articles and replies
- [ ] `reactions.html` hides `followers`/`direct`/`draft` replies
- [ ] ActivityPub addressing correct for all visibility levels
- [ ] `draft` posts are not federated
- [ ] RSS/Atom feeds only include `public` posts
- [ ] Existing unlisted replies maintain behavior
- [ ] All tests pass
- [ ] Documentation updated
