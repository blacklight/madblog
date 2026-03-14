# Phase 4: Federation

This document summarizes the implementation of Phase 4 of the Author Replies feature.

## Overview

Phase 4 adds federation support for author replies, allowing them to be published
to the Fediverse (ActivityPub) and send outgoing Webmentions.

## Architecture

### Replies Monitor

A separate `ContentMonitor` instance watches the `replies/` directory:

- **Isolation**: Different callbacks than `content_monitor` (no tag indexing)
- **Auto-creation**: `replies_dir` is created at startup if missing
- **Callbacks**: Registered for both ActivityPub and Webmentions

### Conflict Prevention

When `pages_dir == content_dir` (no `markdown/` subfolder), `replies/` would be
under `pages_dir`. To prevent duplicate processing:

- `on_content_change()` in both `ActivityPubIntegration` and `FileWebmentionsStorage`
  now skips files under `replies_dir`
- Reply files are only processed by `on_reply_change()`

## Files Changed

### `madblog/activitypub/_integration.py`

- Added `replies_dir` parameter to `__init__()`
- Added `reply_file_to_url()`: Converts reply path → public URL
- Added `_parse_reply_metadata()`: Extracts reply-to from metadata
- Added `_resolve_reply_target_actor()`: Looks up original author for CC
- Added `build_reply_object()`: Creates AP Note with `in_reply_to` set
- Added `_handle_reply_publish()` / `_handle_reply_delete()`: Publishing logic
- Added `on_reply_change()`: Callback for replies monitor
- Added `sync_replies_on_startup()`: Syncs existing replies at startup
- Modified `on_content_change()`: Skips files under `replies_dir`

### `madblog/webmentions/_storage.py`

- Added `replies_dir` parameter to `__init__()`
- Added `reply_file_to_url()`: Converts reply path → public URL
- Added `on_reply_change()`: Sends outgoing webmentions for replies
- Modified `on_content_change()`: Skips files under `replies_dir`

### `madblog/webmentions/_mixin.py`

- Pass `replies_dir` to `FileWebmentionsStorage`

### `madblog/activitypub/_mixin.py`

- Pass `replies_dir` to `ActivityPubIntegration`
- Call `sync_replies_on_startup()` in startup tasks

### `madblog/app.py`

- Added `_start_replies_monitor()`: Creates and configures replies monitor
- Modified `start()`: Calls `_start_replies_monitor()`
- Modified `stop()`: Stops `replies_monitor` if present

## AP Object Format for Replies

Replies are published as **Notes** (not Articles):

```json
{
  "type": "Note",
  "name": null,
  "inReplyTo": "https://mastodon.social/status/123",
  "content": "<p>Thank you for your comment!</p>",
  "to": ["https://www.w3.org/ns/activitystreams#Public"],
  "cc": ["https://example.com/followers", "https://mastodon.social/users/alice"]
}
```

Key differences from article publishing:
- `type` is `"Note"` (conversational)
- `name` is `null` (Notes shouldn't have names)
- `inReplyTo` is set from `reply-to` metadata
- Original author is CC'd for notification

## Tests Added

In `tests/test_replies.py`:

- **`ReplyFederationTest`** (4 tests):
  - `test_reply_file_to_url_activitypub`: URL generation for AP
  - `test_reply_file_to_url_webmentions`: URL generation for WM
  - `test_on_content_change_skips_replies`: Conflict prevention
  - `test_build_reply_object_sets_note_type`: Note object creation

## Follow-up Notes

- **Guestbook replies**: `_guestbook` pseudo-slug works the same way
- **Edit/Delete**: Handled automatically via existing `_handle_reply_publish`
  and `_handle_reply_delete` (Update/Delete activities)
- **Testing federated delivery**: Requires integration tests with actual
  ActivityPub instances

## Upstream Changes (pubby)

Added `get_interaction_by_object_id()` to pubby's storage API to support
looking up interactions by their remote object URL. This enables CC'ing the
original author when replying to an AP interaction.

- **Base class** (`ActivityPubStorage`): Added abstract method with default `None`
- **File storage**: Implemented with `_object_ids/` index for O(1) lookups
- **DB storage**: Implemented with SQL query on indexed `object_id` column
