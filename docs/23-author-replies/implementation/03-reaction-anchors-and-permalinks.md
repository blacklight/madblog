# Phase 3: Reaction Anchors and Permalinks

This document summarizes the implementation of Phase 3 of the Author Replies feature.

## Overview

Phase 3 adds stable anchor IDs to all reactions (webmentions, AP interactions,
author replies) and in-page navigation links for threaded replies.

## Implementation Approach

The plan recommended upstream changes to `webmentions` and `pubby` libraries.
However, since Madblog now renders reactions through its own `reactions.html`
template (implemented in Phase 2), all anchor ID functionality is implemented
directly in Madblog without requiring upstream changes.

## Files Changed

### Modified Files

- **`madblog/templates/reactions.html`**:
  - Added `parent_anchor` parameter to `render_thread_node()` macro
  - Added `get_anchor_id()` helper macro
  - Updated `render_webmention()`, `render_ap_interaction()`, and
    `render_author_reply()` to accept `parent_anchor`
  - Added "↩" reply-to links when `parent_anchor` is set

### Test Files

- **`tests/test_replies.py`**:
  - Added `PermalinkNavigationTest` class with 3 tests

## Anchor ID Format

Anchor IDs are generated using MD5 hashes for stability:

| Reaction Type | Format | Example |
|---|---|---|
| Webmention | `wm-<hash12>` | `wm-abc123def456` |
| AP Interaction | `ap-<hash12>` | `ap-789xyz012abc` |
| Author Reply | `reply-<hash12>` | `reply-def456789xyz` |

The 12-character hex suffix is derived from the reaction's identity URL.

## In-Page Navigation

When a reaction is nested under a parent:
- A "↩" link appears in the reaction header
- Clicking the link scrolls to the parent reaction
- This enables quick navigation in deep threads

## Tests Added

In `tests/test_replies.py`:

- **`PermalinkNavigationTest`** (3 tests):
  - `test_anchor_id_format`: Verifies prefix and length
  - `test_anchor_ids_are_deterministic`: Same URL → same ID
  - `test_different_urls_produce_different_anchors`: Uniqueness

## Template Changes

The `render_thread_node()` macro now:
1. Computes the current node's anchor ID
2. Passes this as `parent_anchor` to child nodes
3. Each render macro shows "↩" link when `parent_anchor` is set

```html
{% if parent_anchor %}
  <a href="#{{ parent_anchor }}" class="reaction-reply-to" title="In reply to">↩</a>
{% endif %}
```

## Follow-up Notes

- **CSS styling**: The `.reaction-reply-to` class can be styled for better visibility
- **URL fragments**: Browser navigation to `#anchor-id` URLs works automatically
- **Phase 4**: Will add federation support for publishing replies to the Fediverse
