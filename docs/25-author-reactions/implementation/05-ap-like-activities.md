# Phase 5: ActivityPub — Publish Like Activities

## Summary

Extended both ActivityPub callbacks (`on_reply_change` and
`on_content_change`) to publish `Like` and `Undo Like` activities when
files contain `like-of` metadata.

## Files changed

### `madblog/activitypub/_publish.py`

Added two shared helpers to `ActivityPubPublishMixin`:

- **`_publish_like(like_of_url)`** — builds a `Like` activity via
  `handler.outbox.build_like_activity` and publishes it. Returns the
  activity dict (caller stores its `id` for later `Undo`).
- **`_publish_undo_like(like_id, actor_url)`** — reconstructs a minimal
  `Like` stub from the stored ID, wraps it in `build_undo_activity`,
  and publishes the `Undo`.

### `madblog/activitypub/_replies.py`

- **Like ID tracking**: `_set_reply_like_id`, `_get_reply_like_id`,
  `_remove_reply_like_id` — store/retrieve/remove Like activity IDs in
  the existing `file_urls` JSON, keyed by
  `reply/<relpath>#like`.
- **`_handle_reply_like_publish`** — on create/edit, undo any previous
  Like for the same file, then publish a new Like and store its ID.
- **`_handle_reply_like_delete`** — on delete, publish Undo Like and
  remove the stored ID.
- **`on_reply_change`** — now branches on metadata:
  - `like-of` present → spawn guarded Like publish.
  - `reply-to` present or non-empty content → spawn guarded Note publish.
  - Both → both threads spawned.
  - On delete → Undo Like + Delete Note.

### `madblog/activitypub/_integration.py`

- **Like ID tracking**: `_set_like_id`, `_get_like_id`,
  `_remove_like_id` — same pattern as replies but keyed by
  `<relpath>#like` (relative to `pages_dir`).
- **`_handle_like_publish`** / **`_handle_like_delete`** — article
  equivalents of the reply handlers.
- **`on_content_change`** — on create/edit, always publishes the
  Article; also spawns a Like publish if `like-of` is present. On
  delete, publishes Undo Like before Delete Article.

### `tests/test_activitypub.py`

- Updated `_join_ap_publish_threads` to also wait for `ap-like-*`
  threads.
- **`ReplyLikeActivityTest`** (3 tests):
  - Standalone like (only `like-of`) publishes Like, not Note.
  - Delete publishes Undo Like.
  - Both `reply-to` + `like-of` publishes Note + Like.
- **`ArticleLikeActivityTest`** (2 tests):
  - Article with `like-of` publishes Article + Like.
  - Delete publishes Delete Article + Undo Like.

## Design decisions

- Like activity IDs reuse the existing `file_urls` JSON with a `#like`
  fragment suffix, avoiding a separate persistence file.
- Startup sync is automatic: both `sync_on_startup` and
  `sync_replies_on_startup` call `on_content_change` / `on_reply_change`
  which now includes the Like branching logic.
