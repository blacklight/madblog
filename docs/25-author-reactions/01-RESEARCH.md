# Author Reactions — Research

## 1. Goal

Allow the blog author to express **reactions** (likes for now; boosts and
quotes later) on arbitrary URLs. Reactions must federate via **ActivityPub**
and **Webmentions**, following the same file-driven authoring model used by
replies.

## 2. Existing patterns in the codebase

### 2.1 Author replies

Replies live under `<content_dir>/replies/<article-slug>/<reply-slug>.md`.
Key infrastructure:

| Component | Role |
|---|---|
| `RepliesMixin` (`madblog/replies/_mixin.py`) | Loads reply files, builds interaction trees, renders reply pages |
| `ActivityPubRepliesMixin` (`madblog/activitypub/_replies.py`) | Builds AP `Note` objects, publishes Create/Update/Delete |
| `FileWebmentionsStorage.on_reply_change` | Sends outgoing Webmentions for reply content |
| `ContentMonitor` (`replies_monitor`) | Watches `replies_dir` for filesystem changes |
| `_get_pages_from_files` | Excludes `replies_dir` from the home page listing |

The replies flow is: **file change → ContentMonitor → AP publish + WM
send**. Startup sync re-publishes any files whose mtime changed while the
server was down.

### 2.2 Markdown metadata

All content files use `[//]: # (key: value)` comment headers. Replies use
`reply-to: <url>` to specify the target. The same pattern maps naturally to
`like-of: <url>`.

### 2.3 ActivityPub (pubby)

- `publish_object(obj, activity_type)` supports `Create`, `Update`,
  `Delete` — but **not** `Like` or `Undo`.
- The outbox `OutboxProcessor` has `build_create_activity`,
  `build_update_activity`, `build_delete_activity` — no `build_like_activity`.
- The inbox **does** handle incoming `Like` and `Undo Like` activities,
  storing them as `InteractionType.LIKE`.

**Implication:** pubby needs a new `build_like_activity` method (and a
corresponding `build_undo_activity` for deletions/unlike). This is a small,
self-contained change in pubby's `OutboxProcessor` and `ActivityPubHandler`.

### 2.4 Webmentions

The outgoing processor (`OutgoingWebmentionsProcessor`) extracts all URLs
from a source page's content and sends a Webmention to each target's
endpoint. It does **not** inspect metadata or microformat properties — it
only discovers link targets in the text.

For a like to be recognised by the receiver as a `like-of`, the **rendered
HTML** of the like page must contain a Microformats2 `h-entry` with a
`u-like-of` property pointing at the target URL. The webmentions library's
**incoming** parser already recognises `like-of` from mf2 properties
(`_infer_mention_type_from_entry`), so receivers running compatible software
will correctly classify the mention.

**Implication:** the outgoing side already works (it discovers the target URL
in the rendered HTML). What's needed is that the **rendered page** emits the
correct mf2 markup (`<a class="u-like-of" href="…">`). No changes to the
webmentions library itself are required.

## 3. Storage design — unified metadata approach

### 3.1 Core idea

Instead of introducing a separate `reactions/` directory, reactions are
**metadata headers** on Markdown files that already live in the existing
directory structure. Every content type the blog supports is a Markdown
file with metadata — reactions are no different.

### 3.2 How reactions map to existing content types

| Reaction | Metadata header | Content body | Location |
|---|---|---|---|
| **Like** | `like-of: <url>` | empty | `replies/<slug>.md` or `replies/<article>/<slug>.md` |
| **Boost** | `boost-of: <url>` | empty | `replies/<slug>.md` or `replies/<article>/<slug>.md` |
| **Quote** | `quote-of: <url>` | author commentary | `replies/<slug>.md` or `replies/<article>/<slug>.md` |
| **Like on article** | `like-of: <url>` | article content | `<pages_dir>/<article>.md` |
| **Like on reply** | `like-of: <url>` | reply content | `replies/<article>/<reply>.md` |

A standalone like is just a Markdown file under `replies/` with a
`like-of:` header and no body content:

```markdown
[//]: # (like-of: https://example.com/post/123)
```

A reply that also likes its target is a normal reply file with both
`reply-to:` and `like-of:` headers:

```markdown
[//]: # (reply-to: https://example.com/post/123)
[//]: # (like-of: https://example.com/post/123)

Great post! I really enjoyed this.
```

An article that likes an external URL is a normal article with a `like-of:`
header alongside its content.

### 3.3 Why this is better than a separate directory

- **No new `ContentMonitor`** — the existing `replies_monitor` already
  watches all files under `replies/`.
- **No new startup sync** — the existing replies startup sync already
  processes all `.md` files under `replies/`.
- **No new routes infrastructure** — standalone likes are served via the
  existing `/reply/…` routes.
- **No new directory to exclude** from the home page listing.
- **Conceptual consistency** — everything the author produces is a
  Markdown file with metadata headers. A like is a degenerate reply (no
  content, no `reply-to`, just `like-of`).
- **One pipeline** — file change → ContentMonitor → AP publish + WM send.
  The same pipeline handles replies, likes, boosts, and quotes.

### 3.4 Discarded alternatives

**Separate `reactions/` directory:** would require a new `ContentMonitor`,
new startup sync, new routes, new WM callback, and new directory exclusion
from the home page. All of these duplicate existing replies infrastructure.

**`touch reactions/likes/<url-encoded>`:** URL encoding in filenames is
fragile (slashes, query strings, length limits). No room for metadata.
Breaks the Markdown-everywhere convention.

### 3.5 Standalone-reaction placement

Flat files directly under `replies/` are already supported by the existing
infrastructure — the author can mention arbitrary AP accounts or respond to
arbitrary posts by dropping files there. Files with no mentions, no parent
article and no `reply-to` behave like "unlisted" posts (accessible via URL
but not displayed on the index nor federated).

Standalone likes follow the same pattern:
`replies/<slug>.md` → `/reply/<slug>`. The file contains only a `like-of:`
header and no body content. No subdirectory needed.

## 4. ActivityPub federation

### 4.1 Branching on metadata

The existing `on_reply_change` callback in `ActivityPubRepliesMixin` builds
a `Note` object and publishes `Create`/`Update`/`Delete`. With the unified
approach, this callback must inspect the file's metadata and branch:

| Metadata present | AP action on create/update | AP action on delete |
|---|---|---|
| `reply-to:` (no reaction headers) | `Create`/`Update` wrapping a `Note` | `Delete` |
| `like-of:` (no content) | `Like` activity | `Undo Like` |
| `boost-of:` (no content) | `Announce` activity | `Undo Announce` |
| `quote-of:` (with content) | `Create` wrapping a `Note` with `quoteUrl` | `Delete` |
| `reply-to:` + `like-of:` | `Create`/`Update` `Note` **and** `Like` | `Delete` + `Undo Like` |

### 4.2 Like activity

```json
{
  "@context": "https://www.w3.org/ns/activitystreams",
  "id": "https://blog.example.com/reply/likes/<slug>#like",
  "type": "Like",
  "actor": "https://blog.example.com/ap/actor",
  "object": "https://target.example.com/post/123",
  "published": "2026-03-14T10:00:00Z"
}
```

Unlike articles/replies (which wrap an Object in a `Create`), a `Like`
activity **directly targets** the remote object URL. Delivery targets:
- The author of the liked object (resolved by fetching the object and
  reading `attributedTo`).
- Followers (so the like appears in timelines — Mastodon does this).

### 4.3 Unlike / delete

Removing a like sends an `Undo` wrapping the original `Like`:

```json
{
  "type": "Undo",
  "actor": "…",
  "object": {
    "type": "Like",
    "id": "…original like activity id…",
    "object": "…target url…"
  }
}
```

### 4.4 Required pubby changes

1. `OutboxProcessor.build_like_activity(object_url)` — build a `Like`
   activity dict.
2. `OutboxProcessor.build_undo_activity(inner_activity)` — build an `Undo`
   wrapper.
3. `ActivityPubHandler` — add a `publish_activity(activity_dict)` method
   that stores and delivers an arbitrary pre-built activity. This is
   simpler than extending `publish_object()`, since `Like` and `Undo`
   don't wrap an `Object` the same way `Create`/`Update` do.

## 5. Webmentions federation

### 5.1 Outgoing

The rendered page must contain mf2 markup for receivers to classify the
mention correctly:

```html
<div class="h-entry">
  <a class="u-like-of" href="https://target.example.com/post/123">
    Liked: https://target.example.com/post/123
  </a>
  <a class="u-author" href="https://blog.example.com">Author Name</a>
  <time class="dt-published" datetime="2026-03-14T10:00:00Z">…</time>
</div>
```

The existing outgoing webmentions processor will:
1. Discover the target URL in the rendered HTML.
2. Send the webmention to the target's endpoint.
3. The receiver parses mf2, sees `u-like-of`, and records it as a like.

No changes to the webmentions library needed.

### 5.2 Deleting a like

When the like file is deleted, `process_outgoing_webmentions` is called
with empty text, which triggers removal of previously sent outgoing
mentions. This already works via the existing `_notify_removed` flow.

## 6. File monitoring

**No new monitor needed.** The existing `replies_monitor` (`ContentMonitor`
watching `replies_dir`) already picks up all file changes under `replies/`,
including standalone likes at `replies/likes/<slug>.md`.

The `on_reply_change` callbacks in `ActivityPubRepliesMixin` and
`FileWebmentionsStorage` already fire for every file under `replies/`. The
only change is that these callbacks must inspect the metadata to decide
whether to publish a `Note` (reply) or a `Like`/`Announce` (reaction).

Startup sync also requires no changes — `sync_replies_on_startup` already
walks all `.md` files under `replies/`.

## 7. Rendering

### 7.1 Author-reactions footer on source pages

Any page (`article.html` or `reply.html`) that contains `like-of:`
metadata renders an **outgoing-reactions footer** below the content but
above the incoming-reactions thread. The footer shows each reaction as:

- An **icon** (e.g. ⭐ for like) with a `title` attribute describing the
  reaction type.
- A **link** to the target URL. If the title of the target page is
  available use it as the link text; otherwise use the raw URL. (For the
  initial implementation, fetching remote page titles adds complexity —
  just use the URL as the link text. Title fetching can be a follow-up.)

Example rendered HTML:

```html
<footer class="author-reactions">
  <div class="author-reaction">
    <span class="author-reaction-icon" title="Liked">⭐</span>
    <a class="u-like-of" href="https://example.com/post/123"
       rel="nofollow noopener" target="_blank">
      https://example.com/post/123
    </a>
  </div>
</footer>
```

The `u-like-of` class provides the mf2 markup needed for Webmention
receivers to classify the mention as a like.

This applies to all source pages:
- A **reply with content + `like-of`** renders the reply content, then
  the likes footer, then the incoming-reactions thread.
- A **standalone like** (no body content) renders only this footer (plus
  standard page chrome — author, date, etc.).
- An **article with `like-of`** renders the article content, then the
  likes footer, then the incoming-reactions thread.

### 7.5 Author-reaction indicator on target pages

When a local page is the **target** of an author like, that target page
should display a visual indicator in its footer. This makes it easy to
see which posts have interactions from the author. The indicator shows
the reaction type icon + the blog author's photo/logo.

This applies to both `article.html` and `reply.html` — any page that is
the target of an author reaction gets the indicator.

This requires a **reverse lookup**: given a page URL, find all author
reactions targeting it. Scanning all files under `replies/` on every page
render is O(n) — too expensive. Instead, maintain a **JSON-persisted
index** under `state_dir`.

#### Author-reaction index

A JSON file (e.g. `state_dir/author_reactions_index.json`) stores the
mapping `target_url → [reaction_info]`:

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

This follows the same pattern as `StartupSyncMixin`, which already
persists `{url: mtime}` as JSON under `state_dir`.

**Loaded on startup:** read the JSON file into memory — O(1) file read
instead of scanning+parsing all reaction files. If the file doesn't exist
(first run), do a one-time scan of `replies/` to build it.

**Updated incrementally:** the `replies_monitor` callback already fires on
file changes. On create/edit: parse `like-of` and upsert the index, then
flush to disk. On delete: remove the entry and flush. Flushing can be
debounced (same as other state files) to avoid excessive I/O.

**Queried on render:** the index is kept in memory (loaded from JSON on
startup). When rendering any article or reply page, look up the current
page URL in the dict. If entries exist, pass them to the template context.

**Memory overhead:** the in-memory dict holds only URL strings and small
metadata dicts — negligible even for thousands of reactions. The JSON file
on disk grows proportionally but stays small (a few KB for hundreds of
reactions).

#### Template rendering

In both `article.html` and `reply.html`, if the current page is the
target of author reactions (looked up via the index), render an indicator
in the footer area (below content, same zone as the outgoing-reactions
footer):

```html
{% if author_likes %}
<div class="author-liked-by" title="Liked by the author">
  {% if author_photo %}
    <img class="author-liked-avatar" src="{{ author_photo }}" alt="" loading="lazy">
  {% endif %}
  ⭐
</div>
{% endif %}
```

This is purely decorative — it doesn't carry mf2 semantics (that's the
job of the source page). A page can have **both** footers if it is
simultaneously a source of outgoing reactions (`like-of:` in its own
metadata) and a target of incoming author reactions (another file has
`like-of:` pointing at it).

### 7.2 mf2 markup per reaction type

| Reaction | Icon | mf2 class | `title` attribute |
|---|---|---|---|
| Like | ⭐ | `u-like-of` | "Liked" |
| Boost | 🔁 | `u-repost-of` | "Boosted" |
| Quote | 🗣️ | `u-quotation-of` | "Quoted" |

### 7.3 Empty-file guard

A Markdown file with no trimmed content **and** no reaction metadata
(`like-of`, `boost-of`, `quote-of`) **and** no `reply-to` should not be
rendered (404):

```python
if (
    not content.strip()
    and not metadata.get("like-of")
    and not metadata.get("boost-of")
    and not metadata.get("quote-of")
    and not metadata.get("reply-to")
):
    abort(404)
```

### 7.4 AP content negotiation

For standalone likes, when the client sends `Accept: application/activity+json`:
- Return the `Like` activity JSON (not a `Note` object).
- The activity `id` uses the reply URL with a `#like` fragment.

## 8. Routing

No new routes needed. Standalone likes live under `replies/` and are
served via the existing `/reply/…` routes:

| File path | URL |
|---|---|
| `replies/likes/<slug>.md` | `/reply/likes/<slug>` |
| `replies/<article>/<slug>.md` | `/reply/<article>/<slug>` |

The reply route handler branches on metadata to decide how to render
(reaction-only vs. full reply).

## 9. Corner cases

### 9.1 Articles with likes

A normal article with `like-of: <url>` in its metadata should:
- Render normally (with content).
- Also emit the `u-like-of` mf2 link.
- Trigger a `Like` activity via AP **in addition to** the normal
  `Create`/`Update` for the article content.
- Send a webmention to the liked URL (already happens via URL extraction).

### 9.2 Replies with likes

A reply with both `reply-to:` and `like-of:` should:
- Render as a normal reply.
- Also emit the `u-like-of` mf2 link.
- Publish both a `Create Note` (reply) **and** a `Like` activity via AP.
- WM: target URL is already discovered in the rendered HTML.

### 9.3 Multiple likes in one file

For the initial implementation, support a single `like-of` per file.
Multiple likes = multiple files.

### 9.4 Slug derivation

The slug is just the filename. No URL-encoding issues since the target URL
lives in the metadata, not the filename.

### 9.5 ActivityPub activity ID for likes

Unlike articles (`Article`) and replies (`Note`), a `Like` is an
**Activity**, not an Object. Its `id` uses the reply URL with a fragment:

```
https://blog.example.com/reply/<slug>#like
```

The `#like` fragment avoids collision with the reply-page URL at the same
path.

## 10. Future extensibility

### 10.1 Boosts

```markdown
[//]: # (boost-of: https://example.com/post/123)
```

Stored as `replies/<slug>.md` (flat, same as likes).
AP activity: `Announce` targeting the object URL.
Webmention: `u-repost-of` mf2 property.

### 10.2 Quotes

```markdown
[//]: # (quote-of: https://example.com/post/123)

My commentary on this post…
```

Stored as `replies/<slug>.md` (flat, same as likes, but with content).
AP activity: `Create` wrapping a `Note` with `quoteUrl` / FEP-0449
`quote` field.
Webmention: `u-quotation-of` mf2 property.

### 10.3 Homepage rendering of foreign content

Boosts and quotes raise the question of whether (and how) to render
"foreign" content on the homepage. This is out of scope for the initial
likes implementation and should be addressed when boosts/quotes are added.

## 11. Summary of required changes (likes only)

### pubby (upstream)

1. `OutboxProcessor.build_like_activity(object_url)` — build a `Like`
   activity.
2. `OutboxProcessor.build_undo_activity(inner_activity)` — build an `Undo`
   wrapper.
3. `ActivityPubHandler.publish_activity(activity_dict)` — store and deliver
   a pre-built activity.

### madblog

| Area | Change |
|---|---|
| **Storage** | No new directories — likes live under `replies/` |
| **Config** | No changes |
| **Monitoring** | No changes — existing `replies_monitor` covers likes |
| **Author-reaction index** | JSON-persisted under `state_dir`, loaded into memory on startup, updated incrementally by monitor callback |
| **AP mixin** | Extend `on_reply_change` to detect `like-of` metadata and publish `Like` / `Undo Like` activities instead of `Create Note` |
| **WM storage** | No changes — existing `on_reply_change` already sends outgoing WMs for the rendered page |
| **Markdown mixin** | Parse `like-of` metadata header |
| **Templates (source page)** | Outgoing-reactions footer on both `article.html` and `reply.html` — icon (⭐) + link with mf2 `u-like-of` class |
| **Templates (target page)** | Author-liked indicator on both `article.html` and `reply.html` — ⭐ with author icon, looked up via the index |
| **Routes** | No new routes — standalone likes served via `/reply/…` |
| **Empty-file guard** | Check for no-content + no reaction/reply metadata → 404 |
| **AP content negotiation** | Return `Like` activity JSON for standalone like pages |
| **Tests** | Unit tests for `like-of` metadata parsing, author-reaction index, AP Like publishing, template rendering |
| **Docs** | Update ARCHITECTURE.md, README.md |
