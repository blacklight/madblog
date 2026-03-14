# Phase 6: AP Content Negotiation for Standalone Likes

## Overview

When a standalone like reply (has `like-of`, no `reply-to`, no content
beyond heading) is fetched with an ActivityPub `Accept` header, the
response is now a `Like` activity JSON instead of a `Note` object.

## Files Changed

### `madblog/activitypub/_mixin.py`

- **`_get_activitypub_reply_response`**: Added early detection of
  standalone likes. Checks for `like-of` in metadata, absence of
  `reply-to`, and empty content via `_clean_content`. When all three
  conditions are met, delegates to the new
  `_get_activitypub_like_response` helper instead of
  `_get_activitypub_object_response`.

- **`_get_activitypub_like_response`** (new): Builds and returns an
  `application/activity+json` response containing a `Like` activity.
  Handles split-domain redirect logic. If a Like activity ID was
  previously stored (from Phase 5 publishing), reconstructs the activity
  with that ID. Otherwise builds a fresh Like activity via
  `handler.outbox.build_like_activity`. Sets standard AP response
  headers (Last-Modified, ETag, Cache-Control, Language).

### `tests/test_activitypub.py`

- **`StandaloneLikeContentNegotiationTest`** (new class, 3 tests):
  - `test_standalone_like_returns_like_activity_json`: Standalone like
    reply returns `{"type": "Like"}` with correct `object` URL.
  - `test_like_with_reply_to_returns_note`: Reply with both `like-of`
    and `reply-to` still returns a `Note`.
  - `test_like_with_content_returns_note`: Reply with `like-of` and
    body content still returns a `Note`.
