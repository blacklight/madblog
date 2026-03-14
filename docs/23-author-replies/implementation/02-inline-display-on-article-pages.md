# Phase 2: Inline Display on Article Pages

This document summarizes the implementation of Phase 2 of the Author Replies feature.

## Overview

Phase 2 adds inline display of author replies on article pages, interleaved with
external reactions (Webmentions, ActivityPub interactions) in a threaded tree
structure.

## Files Changed

### New Files

- **`madblog/threading.py`**: Threading model for building reaction trees
  - `ReactionType` enum: `WEBMENTION`, `AP_INTERACTION`, `AUTHOR_REPLY`
  - `ThreadNode` dataclass: Represents a node in the thread tree
  - `build_thread_tree()`: Builds a threaded tree from reactions and replies
  - `reaction_anchor_id()`: Generates stable anchor IDs for permalinking

- **`madblog/templates/reactions.html`**: Jinja2 template for rendering reactions
  - Recursive `render_thread_node()` macro for nested threading
  - `render_webmention()`, `render_ap_interaction()`, `render_author_reply()` macros
  - CSS classes for styling: `.reaction`, `.reaction-author-reply`, `.depth-N`
  - Anchor IDs for each reaction (`wm-*`, `ap-*`, `reply-*`)

### Modified Files

- **`madblog/app.py`**:
  - Added `_article_slug_from_metadata()`: Extracts article slug from URI
  - Added `_get_article_replies()`: Collects and parses replies for an article
  - Added `_register_template_filters()`: Registers `hash_id` Jinja2 filter
  - Updated `_get_page_interactions()`: Now returns thread tree instead of rendered HTML
  - Updated `get_page()`: Passes `reactions_tree` to template

- **`madblog/markdown/_mixin.py`**:
  - Updated `_render_page_html()`: Accepts `reactions_tree` instead of `mentions`/`ap_interactions`

- **`madblog/webmentions/_mixin.py`**:
  - Added `_get_webmentions()`: Returns raw Webmention objects (for threading)
  - Refactored `_get_rendered_webmentions()` to use the new method

- **`madblog/activitypub/_mixin.py`**:
  - Added `_get_ap_interactions()`: Returns raw Interaction objects (for threading)
  - Refactored `_get_rendered_ap_interactions()` to use the new method

- **`madblog/templates/article.html`**:
  - Replaced `mentions`/`ap_interactions` blocks with `{% include 'reactions.html' %}`

### Bug Fixes (Unrelated)

- **`madblog/routes.py`**: Fixed `app._generate_etag()` → `generate_etag()` call
- **`tests/test_etag_headers.py`**: Fixed test to use `generate_etag` from cache module

## Tests Added

In `tests/test_replies.py`:

- **`ThreadingModelTest`** (4 tests):
  - `test_build_thread_tree_empty`: Empty inputs return empty tree
  - `test_author_replies_become_root_nodes`: Root-level reply handling
  - `test_nested_replies_become_children`: Child threading
  - `test_reaction_anchor_id_stable`: Stable anchor ID generation

- **`ArticleRepliesCollectionTest`** (4 tests):
  - `test_get_article_replies_returns_list`: Returns list of dicts
  - `test_get_article_replies_sorted_by_date`: Chronological ordering
  - `test_get_article_replies_contains_expected_keys`: Dict structure
  - `test_get_article_replies_empty_for_nonexistent`: Empty for missing articles

- **`InlineReactionsRenderingTest`** (3 tests):
  - `test_article_page_renders_author_reply_inline`: Reply content appears
  - `test_reactions_section_has_heading`: Section structure
  - `test_author_reply_has_permalink_anchor`: Anchor IDs present

## Threading Model

The threading model builds a tree structure where:

1. **Root nodes**: Reactions directly to the article URL
2. **Child nodes**: Reactions to other reactions (nested replies)
3. **Sorting**: Roots sorted by date DESC (newest first), children by date ASC

Thread depth is visually indicated with CSS classes (`.depth-0` through `.depth-5`)
and indentation via `margin-left`.

## Template Structure

The `reactions.html` template:

1. Checks if `reactions_tree` is non-empty
2. Renders a "Reactions" heading
3. Recursively renders each thread node with appropriate styling
4. Each reaction type has its own rendering macro with:
   - Author info (photo, name, URL)
   - Content
   - Timestamp
   - Source link
   - Permalink anchor

## Follow-up Notes

- **Styling**: Basic CSS classes are in place but may need additional styling
  in the blog's CSS file for proper visual presentation
- **Max depth**: Threading indentation caps at depth 5 to prevent excessive nesting
- **Phase 3**: Will add URL fragment handling for reaction permalinks
