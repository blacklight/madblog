# Author Replies — Implementation Plan

This document translates the design in
[`01-RESEARCH.md`](01-RESEARCH.md) into concrete, module-level
implementation changes. Each section maps to a source file (or small
group of files) and describes **what** changes, **why**, and the key
code-level details.

---

## Phase 1 — Core Reply Storage and Rendering

### 1.1 `madblog/config.py`

No new config fields are needed in Phase 1. The replies directory is
derived from `content_dir`:

```
<content_dir>/replies/
```

The `replies_dir` path is computed in `BlogApp.__init__()` rather than
stored in `Config`, matching the existing pattern for `pages_dir`.

### 1.2 `madblog/app.py` — `BlogApp.__init__()`

**Add a `replies_dir` property** alongside `pages_dir`:

```python
self.replies_dir = (
    Path(config.content_dir).expanduser().resolve() / "replies"
)
```

This directory may not exist at startup; code that reads from it must
handle that gracefully.

### 1.3 `madblog/app.py` — `_get_pages_from_files()`

Currently `_get_pages_from_files()` walks `pages_dir` recursively and
includes every `*.md` file. If `replies/` were placed inside
`pages_dir`, replies would appear on the home page.

Because `replies_dir` is under `content_dir` (not under `pages_dir`
which is `content_dir/markdown` or `content_dir` itself), this is
already safe **when the `markdown/` subdirectory exists**. When it does
not (fallback mode where `pages_dir == content_dir`), `replies/` would
be a subdirectory of `pages_dir`.

**Change:** add an explicit skip in the `os.walk` loop:

```python
for root, dirs, files in os.walk(pages_dir, followlinks=True):
    # Exclude the replies directory from the home page listing
    dirs[:] = [d for d in dirs if os.path.join(root, d) != str(self.replies_dir)]
    ...
```

This is a single-line guard that works in both directory layouts.

### 1.4 `madblog/markdown/_mixin.py` — reply metadata parsing

`_parse_metadata_from_markdown()` already extracts arbitrary
`[//]: # (key: value)` headers. The `reply-to` key will be returned
naturally as `metadata["reply-to"]`. No changes needed here.

However, `_parse_page_metadata()` resolves files relative to
`self.pages_dir` and calls `abort(404)` if the file is not under that
directory. Replies live under `replies_dir`, so we need a way to resolve
reply files.

**Add a new method** `_parse_reply_metadata(article_slug, reply_slug)`:

```python
def _parse_reply_metadata(self, article_slug: str, reply_slug: str) -> dict:
    """Parse metadata for a reply file under replies_dir."""
    reply_file = os.path.join(
        self.replies_dir, article_slug, reply_slug + ".md"
    )
    md_file = os.path.realpath(reply_file)
    if not os.path.isfile(md_file) or not md_file.startswith(
        str(self.replies_dir)
    ):
        abort(404)
    # ... same stat/metadata logic as _parse_page_metadata ...
```

This reuses the same metadata extraction but resolves from
`replies_dir` and sets `metadata["uri"]` to
`/reply/<article_slug>/<reply_slug>`.

Alternatively, `_parse_page_metadata` could accept an optional
`base_dir` parameter, but a dedicated method is clearer given the
different URI scheme.

### 1.5 `madblog/app.py` — `get_reply()`

**Add a new method** `get_reply(article_slug, reply_slug)` that
mirrors `get_page()` but:

- Resolves the Markdown file from `replies_dir/<article_slug>/<reply_slug>.md`.
- Calls `_parse_reply_metadata()` for metadata.
- Adds `reply_to` (from `metadata["reply-to"]`) to the template
  context.
- Passes `template_name="reply.html"` (or reuses `article.html` with
  an `is_reply=True` flag — see §1.7).
- Sets the same cache headers as `get_page()`.

### 1.6 `madblog/routes.py` — reply routes

**Add two new routes:**

```python
@app.route("/reply/<path:article_slug>/<reply_slug>", methods=["GET"])
def reply_route(article_slug: str, reply_slug: str):
    return app.get_reply(article_slug, reply_slug)

@app.route("/reply/<path:article_slug>/<reply_slug>.md", methods=["GET"])
def raw_reply_route(article_slug: str, reply_slug: str):
    return app.get_reply(article_slug, reply_slug, as_markdown=True)
```

The `<path:article_slug>` converter handles nested article paths
(e.g. `2025/my-post`).

### 1.7 `madblog/templates/reply.html` (new file)

A new template, structurally similar to `article.html`, with these
differences:

- A **back-link banner** at the top: "↩ In reply to \<link\>" derived
  from the `reply_to` URL.
- No tags section (replies inherit the parent article's tags
  conceptually but do not declare their own).
- The same `content | safe` block for rendered Markdown.
- No webmentions/AP interactions section initially (can be added later
  for nested threads — see Phase 2 remarks).

### 1.8 Summary of Phase 1 file changes

| File | Change |
|---|---|
| `madblog/app.py` | Add `replies_dir`; add `get_reply()`; guard `_get_pages_from_files()` |
| `madblog/markdown/_mixin.py` | Add `_parse_reply_metadata()` |
| `madblog/routes.py` | Add `/reply/…` and `/reply/….md` routes |
| `madblog/templates/reply.html` | New template |
| `tests/test_replies.py` | New test file (see §Testing) |

---

## Phase 2 — Inline Display on Article Pages

### 2.1 `madblog/app.py` — collecting replies for an article

**Add a new method** `_get_article_replies(article_slug)`:

```python
def _get_article_replies(self, article_slug: str) -> list[dict]:
    """
    Scan replies/<article_slug>/ and return a list of parsed reply
    dicts, each containing at minimum:
      - slug, reply_to, published, content_html, permalink
    """
```

This method:

1. Checks if `replies_dir / article_slug` exists.
2. Globs `*.md` files.
3. For each file, parses metadata (title, `reply-to`, published) and
   renders the Markdown body to HTML via `render_html()`.
4. Returns a list of dicts sorted by `published` ascending (oldest
   first, matching the research doc's threading ordering).

### 2.2 `madblog/app.py` — `_get_page_interactions()` augmentation

Currently `_get_page_interactions()` returns a tuple
`(webmentions_html, ap_interactions_html)`. It needs to also return
author replies so the template can interleave them.

**Change the return type** to include replies:

```python
def _get_page_interactions(self, md_file, metadata):
    article_slug = self._article_slug_from_metadata(metadata)
    return (
        self._get_rendered_webmentions(metadata),
        self._get_rendered_ap_interactions(md_file),
        self._get_article_replies(article_slug),
    )
```

`_article_slug_from_metadata()` derives the slug from `metadata["uri"]`
(strip the `/article/` prefix).

### 2.3 Threading model

Each reaction (Webmention or AP interaction) has an identity:

| Type | Identity |
|---|---|
| Webmention | `source` URL |
| AP interaction | `object_id` (fallback: `activity_id`) |

Each author reply has a `reply-to` URL. Threading is resolved by
matching `reply-to` against reaction identities:

- `reply-to` == article URL → **top-level author comment**.
- `reply-to` == a Webmention's `source` → **threaded under that WM**.
- `reply-to` == an AP interaction's `object_id` → **threaded under that
  interaction**.
- `reply-to` == another author reply's permalink → **nested reply** (author
  replying to their own reply, or to a reply-to-a-reply chain).

The threading algorithm:

```
build_thread_tree(reactions, author_replies, article_url):
    nodes = {}
    for r in reactions:
        nodes[r.identity] = ThreadNode(item=r, children=[])
    for reply in author_replies:
        nodes[reply.permalink] = ThreadNode(item=reply, children=[])

    roots = []
    for node in nodes.values():
        parent_id = node.item.reply_to  # None for reactions
        if parent_id in nodes:
            nodes[parent_id].children.append(node)
        else:
            roots.append(node)

    # Sort roots by published DESC, children by published ASC
    roots.sort(key=published, reverse=True)
    for node in nodes.values():
        node.children.sort(key=published)

    return roots
```

This supports arbitrary nesting depth. Reactions that are themselves
replies to other reactions (remote threading) can be handled the same
way if their `target_resource` / `in_reply_to` matches another
reaction's identity.

### 2.4 Rendering threaded reactions — Madblog-side

Instead of passing pre-rendered HTML strings for webmentions and AP
interactions to the article template, the threading logic requires
Madblog to control the rendering loop.

**New approach:**

1. Collect raw Webmention objects and raw Interaction objects (not
   pre-rendered HTML).
2. Collect author reply dicts.
3. Build the thread tree (§2.3).
4. Render the tree in a new Jinja2 template (`reactions.html`) that
   walks the tree recursively using a Jinja2 macro:

```jinja2
{% macro render_thread(node, depth=0) %}
  <div class="reaction-thread reaction-thread-{{ 'nested' if depth else 'top' }}" style="margin-left: {{ depth * 1 }}em">
    {% if node.type == 'webmention' %}
      {{ render_webmention(node.item) }}
    {% elif node.type == 'ap_interaction' %}
      {{ render_ap_interaction(node.item) }}
    {% elif node.type == 'author_reply' %}
      {{ render_author_reply(node.item) }}
    {% endif %}

    {% for child in node.children %}
      {{ render_thread(child, depth + 1) }}
    {% endfor %}
  </div>
{% endmacro %}
```

For rendering individual reactions, Madblog can either:

- (a) Call the library renderers (`handler.render_webmention()`,
  `handler.render_interaction()`) per item.
- (b) Use custom Madblog templates that include the anchor IDs (Phase
  3) from the start.

**Recommendation:** go with (b) — provide custom Madblog templates
that wrap the library defaults and add anchor IDs and permalink buttons.
This avoids changing the external libraries initially and gives full
control over thread rendering.

### 2.5 `madblog/templates/article.html` changes

Replace the current raw `{{ mentions }}` / `{{ ap_interactions }}`
blocks with a single `{% include 'reactions.html' %}` block that
receives the thread tree:

```jinja2
{% if reactions_tree %}
  {% include 'reactions.html' %}
{% endif %}
```

The `reactions_tree` is passed from `_render_page_html()`.

### 2.6 Author reply card styling

Author replies rendered inline should be visually distinct:

- Different background colour or a left-border accent.
- An "Author" badge or the blog author's avatar.
- A permalink icon linking to `/reply/<article-slug>/<reply-slug>`.

This is a CSS + template concern, implemented in `reactions.html` and
the blog stylesheet (`css/blog.css`).

### 2.7 Nesting depth limit

To avoid excessively deep nesting on small screens:

- **CSS:** cap visual indentation at a reasonable depth (e.g. 5
  levels), then flatten further nesting.
- **Or:** use a thin left-border rather than padding, which scales
  better.
- Collapsible threads (via CSS `:has()` + checkbox toggle, matching the
  existing pattern in pubby's `interaction.html`) can be added as a
  follow-up.

### 2.8 Summary of Phase 2 file changes

| File | Change |
|---|---|
| `madblog/app.py` | Add `_get_article_replies()`; change `_get_page_interactions()` return type; add `_article_slug_from_metadata()`; update `get_page()` to pass thread tree |
| `madblog/markdown/_mixin.py` | Update `_render_page_html()` to accept and pass `reactions_tree` |
| `madblog/templates/article.html` | Replace mentions/AP blocks with `reactions.html` include |
| `madblog/templates/reactions.html` | New recursive thread template |
| `madblog/static/css/blog.css` | Thread nesting and author-reply styling |
| `tests/test_replies.py` | Threading and inline display tests |

---

## Phase 3 — Reaction Anchors and Permalinks

### 3.1 Where to implement: upstream in webmentions + pubby

Per the research doc's recommendation, anchor IDs and permalink buttons
are best added **upstream** in the `webmentions` and `pubby` libraries.
This benefits all consumers and keeps Madblog's custom template
overrides minimal.

### 3.2 `webmentions` library changes

**File:** `webmentions/templates/webmention.html`

Current outer div:

```html
<div class="wm-mention">
```

**Change to:**

```html
<div class="wm-mention" id="{{ anchor_id }}">
```

Where `anchor_id` is computed by a new `TemplateUtils` helper and
passed during rendering.

**File:** `webmentions/render/_renderer.py`

Add a `reaction_anchor_id` helper to `TemplateUtils`:

```python
@staticmethod
def reaction_anchor_id(prefix: str, identity: str) -> str:
    """Generate a stable anchor ID from a reaction identity URL."""
    import hashlib
    digest = hashlib.md5(identity.encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"
```

In `render_webmention()`, compute and pass the anchor:

```python
anchor_id = TemplateUtils.reaction_anchor_id("wm", webmention.source)
return self._get_markup(
    template, default="webmention.html",
    mention=webmention, anchor_id=anchor_id,
)
```

**Add a permalink button** in the template footer:

```html
<a class="wm-mention-permalink" href="#{{ anchor_id }}" title="Permalink">🔗</a>
```

### 3.3 `pubby` library changes

**File:** `pubby/templates/interaction.html`

Current outer div:

```html
<div class="ap-interaction ap-interaction-{{ interaction.interaction_type.value }}">
```

**Change to:**

```html
<div class="ap-interaction ap-interaction-{{ interaction.interaction_type.value }}" id="{{ anchor_id }}">
```

**File:** `pubby/render/_renderer.py`

Same pattern — add `reaction_anchor_id` to `TemplateUtils`, compute
`anchor_id` from `interaction.object_id or interaction.activity_id`,
and pass it during rendering. Add a permalink button in the interaction
footer.

### 3.4 Madblog integration

Once the upstream changes are in place, Madblog's thread-rendering
templates (§2.4) can reference the anchor IDs directly. The
`reply-to` URL in an author reply maps to a specific anchor on the
article page, enabling in-page navigation links:

```html
<!-- In the author reply card -->
<a href="#{{ parent_anchor_id }}">↩ in reply to …</a>
```

### 3.5 Fallback (if upstream changes are deferred)

If the upstream PRs are not merged before Phase 3 work begins, Madblog
can pass custom template strings to `render_webmention()` /
`render_interaction()` that include the `id` attribute. Both libraries
already support this via the `template` parameter. The custom templates
would be stored in `madblog/templates/` and would be near-copies of
the library defaults with the added `id` and permalink button.

### 3.6 Summary of Phase 3 file changes

| Repo | File | Change |
|---|---|---|
| webmentions | `render/_renderer.py` | Add `reaction_anchor_id` helper; pass `anchor_id` to template |
| webmentions | `templates/webmention.html` | Add `id="{{ anchor_id }}"` and permalink button |
| pubby | `render/_renderer.py` | Add `reaction_anchor_id` helper; pass `anchor_id` to template |
| pubby | `templates/interaction.html` | Add `id="{{ anchor_id }}"` and permalink button |
| madblog | `templates/reactions.html` | Use anchor IDs for in-page reply-to links |

---

## Phase 4 — Federation

### 4.1 `ContentMonitor` — watching the replies directory

Currently, `ContentMonitor` watches only `pages_dir`. The replies
directory is separate.

**Option A — second `ContentMonitor`:** Create a second
`ContentMonitor` instance watching `replies_dir` with its own set of
registered callbacks. This is clean but requires managing two monitors.

**Option B — extend the existing monitor** to accept multiple root
directories, or instantiate it on a common parent.

**Recommendation:** Option A. The two monitors have different callback
sets (replies do not trigger tag re-indexing, for example). In
`BlogApp.__init__()`:

```python
self.replies_monitor = ContentMonitor(
    root_dir=str(self.replies_dir),
    throttle_seconds=config.throttle_seconds_on_update,
)
```

In `BlogApp.start()`:

```python
self.replies_monitor.register(self._ap_integration.on_reply_change)
if config.enable_webmentions:
    self.replies_monitor.register(
        self.webmentions_storage.on_reply_change
    )
self.replies_monitor.start()
```

In `BlogApp.stop()`:

```python
self.replies_monitor.stop()
```

### 4.2 `ActivityPubIntegration` — publishing replies

**New method** `on_reply_change(change_type, filepath)`:

This mirrors `on_content_change()` but:

1. Derives the reply URL (`/reply/<article_slug>/<reply_slug>`) instead
   of `/article/…`.
2. Calls `build_reply_object()` instead of `build_object()`.

**New method** `build_reply_object(filepath, url, actor_url)`:

Similar to `build_object()` but:

- Sets `type` to `"Note"` (replies are conversational, not articles).
- Reads the `reply-to` metadata and sets `obj.in_reply_to` to that
  URL. The `Object` dataclass already supports `in_reply_to`.
- Sets `obj.name` to `None` (Notes should not have a `name` —
  Mastodon ignores it and some implementations treat named Notes as
  articles).
- Computes `to` / `cc`:
  - Always includes the public collection.
  - Always includes the followers collection.
  - When `reply-to` points to a remote actor's post, resolve the
    original author's actor URL (from the stored interaction's
    `source_actor_id`) and add it to `cc`. This ensures the reply
    shows up in the original author's notifications.

**File-to-URL mapping for replies:**

Add a `reply_file_to_url()` method:

```python
def reply_file_to_url(self, filepath: str) -> str:
    rel = os.path.relpath(filepath, self.replies_dir).rsplit(".", 1)[0]
    # rel = "<article-slug>/<reply-slug>"
    return f"{self.base_url}/reply/{rel}"
```

This requires `replies_dir` to be passed to
`ActivityPubIntegration.__init__()`.

**Startup sync for replies:**

The existing `StartupSyncMixin` syncs files from a single
`_sync_pages_dir`. For replies, either:

- Add a second sync pass for `replies_dir` in `sync_on_startup()`.
- Or create a small `RepliesSync` helper that wraps `StartupSyncMixin`
  for the replies directory.

### 4.3 `FileWebmentionsStorage` — outgoing Webmentions for replies

**New method** `on_reply_change(change_type, filepath)`:

Mirrors `on_content_change()` but uses `reply_file_to_url()` to
compute the source URL (the reply's permalink). The webmentions handler
will then discover any links in the reply's content and send outgoing
Webmentions.

```python
def reply_file_to_url(self, filepath: str) -> str:
    rel = os.path.relpath(filepath, self.replies_dir).rsplit(".", 1)[0]
    return f"{self.base_url}/reply/{rel}"
```

This also requires `replies_dir` to be passed to
`FileWebmentionsStorage.__init__()`.

### 4.4 Replies to remote interactions — `cc` targeting

When the author replies to an AP interaction, the reply's `cc` should
include the original author's actor URL so it shows up as a threaded
reply on their instance. To resolve this:

1. `build_reply_object()` reads `reply-to` from metadata.
2. Looks up the corresponding interaction in pubby storage (by matching
   `object_id == reply_to`).
3. Extracts `source_actor_id` from the matched interaction.
4. Adds it to the `cc` list.

If no matching interaction is found (e.g. the reply-to is the article
itself, or a Webmention), skip this step.

### 4.5 Edit and Delete handling

- **Edit:** `on_reply_change(ChangeType.EDITED, filepath)` triggers an
  `Update` activity via the same `_handle_publish()` flow (which
  already checks `_is_published()` to decide Create vs Update).
- **Delete:** `on_reply_change(ChangeType.DELETED, filepath)` triggers
  a `Delete` activity via `_handle_delete()`.

Both flows are identical to article handling; only the URL derivation
differs.

### 4.6 Summary of Phase 4 file changes

| File | Change |
|---|---|
| `madblog/app.py` | Create and manage `replies_monitor`; pass `replies_dir` to AP integration and WM storage |
| `madblog/activitypub/_integration.py` | Add `replies_dir`; add `on_reply_change()`; add `build_reply_object()`; add `reply_file_to_url()`; add reply startup sync |
| `madblog/webmentions/_storage.py` | Add `replies_dir`; add `on_reply_change()`; add `reply_file_to_url()` |
| `madblog/webmentions/_mixin.py` | Register `on_reply_change` on `replies_monitor` |
| `madblog/activitypub/_mixin.py` | Register `on_reply_change` on `replies_monitor`; pass `replies_dir` to integration |
| `tests/test_replies.py` | Federation tests |

---

## Guestbook Replies

Per the research doc remarks, replies to guestbook entries use the
pseudo-slug `_guestbook`:

```
replies/_guestbook/<reply-slug>.md
```

These replies have `reply-to` set to the remote URL (e.g. the
Mastodon post that was a guestbook mention).

- **URL:** `/reply/_guestbook/<reply-slug>`.
- **Inline display:** On the `/guestbook` page, the same threading
  logic applies — match `reply-to` against guestbook entries'
  identities and render threaded.
- **Federation:** Same as article replies — `inReplyTo` set to the
  remote post URL, `cc` includes the original author.

### Implementation notes

- `_guestbook` is a reserved slug; `_get_pages_from_files()` already
  skips `replies/` entirely so there is no conflict.
- The guestbook route (`/guestbook`) currently calls
  `get_rendered_guestbook_webmentions()` and
  `get_rendered_guestbook_ap_interactions()`. These will need the same
  threading treatment as article pages (collect raw objects, build
  thread tree, render with `reactions.html`).

---

## Testing Strategy

### `tests/test_replies.py` (new file)

Organized by phase:

**Phase 1 tests:**

- `test_reply_route_renders` — create a temp reply file, request
  `/reply/<slug>/<reply>`, assert 200 and content rendered.
- `test_reply_raw_markdown` — request `.md` variant, assert Markdown
  returned.
- `test_reply_404_nonexistent` — request a missing reply, assert 404.
- `test_replies_excluded_from_home` — create replies under
  `replies/`, request `/`, assert they do not appear.
- `test_reply_metadata_parsing` — verify `reply-to` is extracted.

**Phase 2 tests:**

- `test_article_shows_author_replies` — create an article and a reply
  to it, render the article page, assert the reply content appears.
- `test_threading_reply_to_reaction` — create a mock AP interaction
  and an author reply targeting its `object_id`, verify the reply
  appears threaded under the interaction.
- `test_multiple_replies_ordered_by_date` — verify ascending date
  ordering within a thread.
- `test_nested_threading` — verify a reply to a reply renders at the
  correct depth.

**Phase 3 tests:**

- `test_anchor_ids_present` — render reactions and verify `id`
  attributes on reaction divs.
- `test_permalink_buttons` — verify permalink anchor links.
- Tests in the respective `webmentions` and `pubby` repos for the
  upstream changes.

**Phase 4 tests:**

- `test_reply_publishes_ap_note` — mock the AP handler, create a
  reply file, trigger `on_reply_change`, verify `publish_object()`
  called with `in_reply_to` set.
- `test_reply_cc_includes_original_author` — verify the `cc` list
  includes the remote actor when replying to an AP interaction.
- `test_reply_sends_outgoing_webmention` — mock the WM handler,
  create a reply, trigger `on_reply_change`, verify
  `process_outgoing_webmentions()` called.
- `test_reply_edit_triggers_update` — verify `Update` activity type.
- `test_reply_delete_triggers_delete` — verify `Delete` activity.

---

## Implementation Order

The phases are designed to be implemented and merged incrementally:

1. **Phase 1** — standalone, no upstream dependencies. Delivers reply
   pages and the URL scheme.
2. **Phase 3** — can be done in parallel with Phase 2 since it
   targets the upstream libraries. Delivers anchor IDs.
3. **Phase 2** — depends on Phase 3 anchors for the full threading
   UX, but can be started without them (just skip the in-page
   reply-to links until anchors land).
4. **Phase 4** — depends on Phase 1 (needs reply routes) and Phase 2
   (needs reply collection logic). Delivers federation.

---

## Follow-ups (deferred to `03-FOLLOW-UPS.md`)

- Per-article reply feeds: `/reply/<article-slug>/feed.rss`.
- Reply counts in the home page listing.
- Collapsible thread UI.
- Incoming replies to author replies (nested remote threads displayed
  on reply pages).
