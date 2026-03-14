# Author Reactions — Implementation Plan (Likes)

This plan focuses on **likes only**. Boosts and quotes are documented in
the research but deferred to a follow-up.

## Phase 1: pubby upstream — Like / Undo support

Add outbound Like and Undo activity support to pubby.

### 1.1 `OutboxProcessor`

All existing builders (`build_create_activity`, `build_update_activity`,
`build_delete_activity`) return `dict` (JSON-LD activity dicts). New
builders follow the same pattern:

- Add `build_like_activity(object_url: str, published: datetime | None = None) -> dict`
  — returns a `Like` activity dict with `actor`, `object`, `published`,
  `to`, `cc`.
- Add `build_undo_activity(inner_activity: dict) -> dict` — wraps any
  activity in an `Undo` envelope. This is intentionally generic: it works
  for `Undo Like`, `Undo Announce`, `Undo Follow`, etc.

For future reaction types, the same pattern applies: add
`build_announce_activity` (boosts), `build_follow_activity` (follows),
each returning `dict`. `build_undo_activity` already covers all of them.

### 1.2 `ActivityPubHandler`

- Add `publish_activity(activity: dict) -> dict` — thin pass-through to
  `outbox.publish(activity)`. This bypasses the Object-wrapping logic of
  `publish_object` (which builds Create/Update around an `Object`).
  Needed for activities like `Like` and `Undo` that are not Object
  wrappers.

### 1.3 Tests

- Unit tests for `build_like_activity` and `build_undo_activity` output
  shape (correct `type`, `actor`, `object`, addressing).
- Unit test for `publish_activity` delivery flow (delegates to
  `outbox.publish`).

---

## Phase 2: Markdown metadata — parse `like-of`

### 2.1 `_parse_metadata_from_markdown`

In `madblog/markdown/_mixin.py`, the metadata parser already extracts
arbitrary `[//]: # (key: value)` headers. Ensure `like-of` is surfaced in
the metadata dict returned by `_parse_reply_metadata` (and
`_parse_page_metadata` for articles with likes).

### 2.2 Pass `like_of` through to templates

Ensure `get_reply` and `get_page` pass `like_of` to the template context
so that templates can render the author-reactions footer.

### 2.3 Tests

- Unit test: a Markdown file with `[//]: # (like-of: https://example.com)`
  produces `metadata["like-of"] == "https://example.com"`.
- Unit test: a file with both `reply-to` and `like-of` returns both.

---

## Phase 3: Author-reaction index

Maintain a **JSON-persisted** reverse index under `state_dir` so that
target pages can display an "author liked this" indicator without scanning
all files on every render. Follows the same pattern as `StartupSyncMixin`.

### 3.1 Data structure and storage

A JSON file at `state_dir/author_reactions_index.json` stores the mapping
`target_url → [reaction_info]`:

```json
{
  "https://blog.example.com/some-article": [
    {
      "type": "like",
      "source_url": "/reply/my-like",
      "source_file": "replies/my-like.md"
    }
  ]
}
```

At runtime, the JSON is loaded into a `dict[str, list[dict]]` for O(1)
lookups. The dict is kept in sync with the file on disk.

### 3.2 Loading on startup

Read the JSON file into memory. If it doesn't exist (first run or
migration), do a one-time scan of all `.md` files under `replies/` to
build the index, then persist it.

### 3.3 Incremental updates via monitor callback

The `replies_monitor` callback already fires on file changes. On
create/edit: parse `like-of`, upsert the in-memory dict, flush to disk.
On delete: remove the entry, flush to disk. Flushing can be debounced to
avoid excessive I/O (same pattern as other state files).

### 3.4 Query on render

When rendering any article or reply page, look up the current page's
full URL in the in-memory dict. If entries exist, pass `author_likes` to
the template context.

### 3.5 Tests

- Unit test: index is empty initially; adding a file with `like-of`
  pointing at a local URL populates the index and persists it to JSON.
- Unit test: reloading from JSON on startup restores the index.
- Unit test: deleting the file removes the entry from both memory and
  JSON.
- Unit test: a `like-of` pointing at an external URL does **not** appear
  in the index (only local targets are tracked).

---

## Phase 4: Template rendering

Both `article.html` and `reply.html` get two new conditional blocks in
the footer area (below content, above the incoming-reactions thread).
A page can have both if it is simultaneously a source and a target.

### 4.1 Outgoing-reactions footer (source pages)

If `like_of` is set in the page's own metadata, render a footer showing
the author's outgoing like(s). Applied to both `article.html` and
`reply.html` (a reply with content + `like-of` renders the reply content,
then the likes footer, then the incoming-reactions thread):

```html
<footer class="author-reactions">
  <div class="author-reaction">
    <span class="author-reaction-icon" title="Liked">⭐</span>
    <a class="u-like-of" href="{{ like_of }}"
       rel="nofollow noopener" target="_blank">
      {{ like_of }}
    </a>
  </div>
</footer>
```

The `u-like-of` class provides mf2 markup for Webmention receivers.

### 4.2 Author-liked indicator (target pages)

When the current page is the **target** of an author like (looked up via
the author-reaction index from Phase 3), render an indicator in the same
footer zone. Shows the reaction type icon + author/blog photo. Applied to
both `article.html` and `reply.html`:

```html
{% if author_likes %}
<div class="author-liked-by" title="Liked by the author">
  {% if author_photo %}
    <img class="author-liked-avatar" src="{{ author_photo }}"
         alt="" loading="lazy">
  {% endif %}
  ⭐
</div>
{% endif %}
```

This is purely decorative — no mf2 semantics (that’s the job of the
source page).

### 4.3 CSS

Add minimal styles for `.author-reactions`, `.author-reaction`,
`.author-liked-by`, and `.author-liked-avatar` to the existing
`reactions.css`.

### 4.4 Tests

- Template test: a page with `like-of` metadata renders the
  outgoing-reactions footer with `u-like-of`.
- Template test: a page that is the target of an author like renders the
  `author-liked-by` indicator.
- Template test: a page with both outgoing and incoming author likes
  renders both footers.
- Template test: a page with no likes renders neither.

---

## Phase 5: ActivityPub — publish Like activities

Both `on_reply_change` and `on_content_change` need branching logic,
since likes can appear in reply files (standalone likes, replies that
also like a post) and in article files (an article that likes another
post).

### 5.1 Extend `on_reply_change` in `ActivityPubRepliesMixin`

The callback currently builds a `Note` and publishes `Create`/`Update`/
`Delete`. Add a branch:

- If `like-of` is present in the file’s metadata:
  - On create/edit: call `publish_activity(build_like_activity(like_of_url))`.
  - On delete: call `publish_activity(build_undo_activity(like_activity))`.
- If `reply-to` is also present, publish both a `Create Note` (existing
  logic) **and** a `Like` activity.
- If only `like-of` (no `reply-to`, no content): publish **only** the
  `Like` activity (no `Create Note`).

### 5.2 Extend `on_content_change` in `ActivityPubIntegration`

The callback currently builds an `Article` and publishes
`Create`/`Update`/`Delete`. Add a branch:

- If `like-of` is present in the article's metadata:
  - On create/edit: publish the `Create Article` (existing logic) **and**
    a `Like` activity.
  - On delete: publish `Delete Article` **and** `Undo Like`.

### 5.3 Activity ID tracking

Store the Like activity ID (keyed by file path or reply URL) so that
`Undo` can reference the original activity. Use the existing file-to-URL
mapping infrastructure in `_integration.py`, extended with a
`#like` fragment suffix.

### 5.4 Startup sync

The existing `sync_replies_on_startup` already walks all `.md` files under
`replies/`. The `on_reply_change` callback will now branch on metadata, so
startup sync automatically covers reply-based likes. Similarly,
`sync_on_startup` for articles already covers articles with `like-of`.

### 5.5 Tests

- Unit test: creating a reply file with `like-of` triggers a `Like`
  activity (not `Create Note`).
- Unit test: deleting a like file triggers an `Undo Like`.
- Unit test: a reply with both `reply-to` and `like-of` triggers both
  `Create Note` and `Like`.
- Unit test: an article with `like-of` triggers both `Create Article`
  and `Like`.

---

## Phase 6: AP content negotiation for standalone likes

### 6.1 `_get_activitypub_reply_response`

When the reply file has `like-of` and no content / no `reply-to`, return
the `Like` activity JSON instead of a `Note` object.

### 6.2 Tests

- Unit test: requesting a standalone like URL with
  `Accept: application/activity+json` returns a `Like` activity.

---

## Phase 7: Empty-file guard

### 7.1 `get_reply` in `app.py`

Before rendering, check: if the file has no trimmed content **and** no
`like-of` **and** no `reply-to`, return 404.

### 7.2 Tests

- Unit test: a file under `replies/` with no content, no `like-of`, no
  `reply-to` → 404.
- Unit test: a file with only `like-of` → 200.

---

## Phase 8: Documentation and wrap-up

### 8.1 `ARCHITECTURE.md`

Document the `like-of` metadata header, how standalone likes work under
`replies/`, the author-reaction index, and the AP Like activity flow.

### 8.2 `README.md`

Add a section on author reactions (likes) under the existing content
authoring documentation.

### 8.3 `CHANGELOG.md`

Add entry under _Unreleased_.
