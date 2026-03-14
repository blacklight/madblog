# Author Replies — Design Document

## Goal

Allow the blog author to reply to:

1. Their own articles (top-level comments on a post).
2. Webmention or ActivityPub interactions received on any article or on the
   guestbook.

Replies are authored as Markdown files (same workflow as posts), rendered via
the existing Markdown pipeline, and each reply gets its own permalink URL.
However, replies must **not** appear in the home page post listing or in the
blog RSS/Atom feeds.

---

## Current State

### Posts

- Stored as `*.md` files under `<pages_dir>` (typically
  `<content_dir>/markdown`).
- Metadata is encoded as Markdown comment headers:
  `[//]: # (key: value)`.
- URL scheme: `/article/<slug>` (slug = relative path minus `.md`).
- All `*.md` files under `pages_dir` are walked recursively by
  `_get_pages_from_files()` and appear on the home page.

### Incoming Webmentions

- Stored by `FileWebmentionsStorage` as Markdown files under
  `<state_dir>/mentions/incoming/<post-slug>/webmention-*.md`.
- Each webmention has a `source` URL (the remote page) that serves as
  its external identity.
- No internal permalink is currently assigned to individual webmentions.

### Incoming ActivityPub Interactions

- Stored by pubby's `FileActivityPubStorage` as JSON files under
  `<state_dir>/activitypub/state/interactions/<sanitized-target>/`.
- Each interaction carries `activity_id` and `object_id` fields — both
  are remote URLs (e.g.
  `https://mastodon.social/users/alice/statuses/123`).
- No internal permalink is currently assigned to individual interactions.

### Rendering of Reactions

- **Webmentions** are rendered via the `webmentions` library's Jinja2
  template (`webmention.html`). The outer `<div class="wm-mention">`
  currently has **no `id` attribute** — there is no anchor for linking to
  a specific mention.
- **AP interactions** are rendered via pubby's `interaction.html`. The
  outer `<div class="ap-interaction ...">` also has **no `id`
  attribute**.
- Both templates support custom template overrides (path, string, or
  `Template` object), so Madblog can inject its own templates that add
  anchor IDs without forking the libraries.

---

## Proposed Storage Format

### Directory Layout

Replies live in a dedicated directory, **separate from `pages_dir`**, so
they are never picked up by `_get_pages_from_files()`:

```
<content_dir>/
└── replies/
    └── <article-slug>/
        ├── <reply-slug>.md          # direct reply to the article
        └── <reply-slug>.md          # reply to someone's reaction
```

All replies for a given article are grouped under the article's slug.
This keeps the filesystem browsable and makes it easy to list all author
replies for a given post.

### Identifying the Reply Target (Metadata)

Each reply Markdown file uses the standard `[//]: #` metadata header
convention to declare what it is replying to:

```markdown
[//]: # (reply-to: https://mastodon.social/users/alice/statuses/123)
[//]: # (published: 2025-07-01)

# Re: Great discussion

Thank you for your thoughtful response...
```

The `reply-to` field contains:

| Reply target | `reply-to` value |
|---|---|
| Own article | The article's canonical URL, e.g. `https://blog.example.com/article/my-post` |
| A webmention | The webmention's `source` URL |
| An AP interaction | The interaction's `object_id` (the remote post URL) |

This approach:

- Keeps the filesystem hierarchy simple — everything under
  `replies/<article-slug>/`.
- Uses a single metadata field (`reply-to`) to express the target,
  regardless of whether it is the article itself, a webmention, or an AP
  interaction.
- Avoids encoding the reaction's identity into the directory structure,
  which would be fragile and produce deeply nested paths.

### Reply Slug

The reply filename (minus `.md`) becomes the slug. The author is free to
choose it. Examples:

- `replies/my-post/thanks-alice.md` → slug `thanks-alice`
- `replies/my-post/re-thread.md` → slug `re-thread`

### URL Scheme

Replies are served at:

```
/reply/<article-slug>/<reply-slug>
```

Examples:

- `/reply/my-post/thanks-alice`
- `/reply/my-post/re-thread`

The `/reply/` prefix keeps the namespace clean and distinct from
`/article/`. The raw Markdown is available at
`/reply/<article-slug>/<reply-slug>.md`, mirroring the article
convention.

---

## Rendering

### Reply Page

Browsing `/reply/<article-slug>/<reply-slug>` renders the reply through
the same Markdown → HTML pipeline used for articles. The existing
`_parse_page_metadata()` / `_render_page_html()` flow can be reused with
minimal adaptation (resolve the file from the replies directory instead
of `pages_dir`).

The rendered page should include:

- The reply content (rendered Markdown).
- A visible back-link to the parent article or reaction being replied
  to (derived from `reply-to`).
- Standard page metadata (published date, author info).

A dedicated template (e.g. `reply.html`) or the existing `article.html`
with a "reply" mode flag can be used.

### Replies Displayed on Article Pages

When rendering an article page, the system should collect any author
replies from `replies/<article-slug>/` and display them inline among
(or after) the reactions section. This requires:

1. Scanning the replies directory for the article slug.
2. Parsing each reply's `reply-to` metadata to determine placement:
   - If `reply-to` matches the article URL → top-level author reply.
   - If `reply-to` matches a reaction's identity → threaded under that
     reaction.
3. Rendering each reply as an inline card (similar to reactions but
   visually distinguished as the author's response), with a permalink
   button pointing to `/reply/<article-slug>/<reply-slug>`.

### Ordering and nesting

- Replies should be placed below the item they are replying to.

- A group consisting of a root message + its replies is conventionally named a
  "_thread_".

- Threads can be recursive/nested.

- Ordering of items within a thread is the opposite of the ordering of root
  mentions/interactions. While interactions on the root level are sorted by
  creation date descending, replies should be sorted by creation date
  ascending.

- Consider how to visually render recursive threads. Some proposals:
    - Nesting with horizontal padding and an optionally a thin border. Be
      mindful in that case about excessive nesting that may make deeply nested
      items too small on small screens.
    - Collapsible threads.
    - Mindful visual indicators (e.g. shadows and borders) between threads.

### Domain of the changes

- Consider which changes apply only to Madblog and which ones would be wise to
  implement in the rendering structure of
  [Webmentions](file:///home/blacklight/git_tree/webmentions) or [Pubby](file:///home/blacklight/git_tree/pubby) instead
  (same goes for applying IDs/permanent anchors to reactions).

---

## Reaction Permalinks and Anchor IDs

### The Problem

Currently, neither the webmentions nor pubby templates emit `id`
attributes on individual reaction containers. This means:

- There is no way to link to a specific reaction on an article page via
  a fragment anchor (e.g. `#reaction-abc123`).
- Author replies that target a specific reaction cannot visually link to
  that reaction in-page.

### Proposed Solution

Add `id` attributes to each rendered reaction `<div>`, using a
deterministic, URL-safe hash derived from the reaction's identity:

| Reaction type | Identity source | Anchor ID scheme |
|---|---|---|
| Webmention | `source` URL | `wm-<md5(source)[:12]>` |
| AP interaction | `object_id` or `activity_id` | `ap-<md5(object_id)[:12]>` |

This produces stable, short anchors like `#wm-a1b2c3d4e5f6` or
`#ap-f6e5d4c3b2a1`.

### Where to Implement

The anchor IDs should be added in the **rendering templates**, not in
the libraries' core logic. Two approaches:

1. **Custom templates in Madblog** — override the default
   `webmention.html` and `interaction.html` templates by passing custom
   template strings/paths to `render_webmentions()` /
   `render_interactions()`. This avoids any changes to the webmentions
   or pubby libraries.

2. **Upstream in webmentions/pubby** — add optional `id` attributes to
   the default templates. This is cleaner long-term and benefits all
   consumers. The `id` could be computed via a new Jinja2 helper
   exposed in `TemplateUtils`.

**Recommendation:** implement upstream in both libraries (option 2).
The `id` attribute is semantically correct HTML and broadly useful. If
upstream changes are not immediately feasible, option 1 provides a
quick Madblog-only fallback.

### Permalink Button

Each rendered reaction should include a small permalink/anchor button
(e.g. 🔗 or a chain-link icon) that:

- Sets `window.location.hash` to the reaction's anchor.
- Copies the full URL (`<article-url>#<anchor-id>`) to the clipboard.

This can be implemented as a small inline `<a>` or `<button>` next to
the reaction's date/footer. Like anchor IDs, this is best implemented
upstream in the webmentions/pubby templates so all consumers benefit.

---

## Federation

### ActivityPub

When an author reply is created or updated, it should be published as an
ActivityPub `Note` (or the configured object type) with:

- `inReplyTo` set to the `reply-to` URL (the target article or remote
  post).
- `id` set to the reply's canonical URL
  (`https://blog.example.com/reply/<article-slug>/<reply-slug>`).
- `attributedTo` set to the blog's AP actor.
- `to` / `cc` including the public collection and, when replying to a
  remote interaction, the original author's actor URL.

This makes the reply appear as a threaded response on Mastodon and
other fediverse platforms.

The existing `ActivityPubIntegration.on_content_change()` and
`ContentMonitor` can be extended to watch the replies directory.
`build_object()` would need a small adaptation to populate `inReplyTo`
from the `reply-to` metadata.

### Webmentions

When a reply targets a URL that supports Webmentions (including the
blog's own articles), an outgoing Webmention should be sent. The
existing `FileWebmentionsStorage.on_content_change()` mechanism can be
reused — it just needs to know about the replies directory.

---

## Implementation Outline

### Phase 1 — Core Reply Storage and Rendering

1. Add a `replies_dir` property to `BlogApp` pointing at
   `<content_dir>/replies`.
2. Add a `/reply/<path:article_slug>/<reply_slug>` route (and `.md`
   variant) that resolves files from `replies_dir` and renders them via
   the existing Markdown pipeline.
3. Parse `reply-to` metadata and render a back-link in the reply page.
4. Ensure `_get_pages_from_files()` explicitly excludes `replies_dir`.

### Phase 2 — Inline Display on Article Pages

5. On article render, scan `replies/<article-slug>/` for reply files.
6. Match each reply to its target (article itself or a specific
   reaction) via `reply-to`.
7. Render author replies inline in the reactions section with a
   visual distinction and a permalink.

### Phase 3 — Reaction Anchors and Permalinks

8. Add `id` attributes to rendered reactions (upstream in
   webmentions/pubby, or via custom Madblog templates as fallback).
9. Add a permalink button to each reaction.

### Phase 4 — Federation

10. Extend `ContentMonitor` to watch `replies_dir`.
11. Extend `ActivityPubIntegration` to publish replies with `inReplyTo`.
12. Extend `FileWebmentionsStorage` to send outgoing webmentions for
    replies.

---

## Open Questions

1. **Should replies appear in a dedicated feed?** A `/replies/feed.rss`
   endpoint could be useful for followers who want to track the author's
   conversation activity, but it adds complexity. This can be deferred.
   **Perhaps better a `/replies/<article-slug>/feed.rss`? And yes, it's a good
   idea. For now keep it to `docs/replies/03-FOLLOW-UPS.md`.**

2. **Guestbook replies.** Guestbook entries are not tied to a specific
   article. If the author wants to reply to a guestbook mention, the
   reply could live under `replies/_guestbook/<reply-slug>.md` (using a
   reserved `_guestbook` pseudo-slug). Alternatively, a `reply-to` URL
   pointing to the remote source is sufficient — the `<article-slug>`
   directory would simply be `_guestbook`. **Mentioning the remote URL should
   probably suffice (and be documented). All guestbook entries must have a URL
   anyway, since likes/boosts don't count. Ok for
   `replies/_guesbook/<reply-slug>[.md]`.** as a pseudo-slug.

3. **Multiple replies to the same target.** Nothing prevents multiple
   reply files with different slugs but the same `reply-to` value. The
   display logic should handle this gracefully (show all of them,
   ordered by published date). **Yes - keep date-based ordering consistent, and
   consider using <slug>, <slug>-1, <slug>-2, etc.**

4. **Editing and deleting replies.** Edits should trigger an AP
   `Update` activity (same as article edits). Deleting a reply file
   should trigger an AP `Delete`. The existing `ChangeType.EDITED` /
   `ChangeType.DELETED` machinery handles this. **Yes, edits should go through
   the same AP processing logic.**

5. **Reply to a reply.** In theory, someone on the fediverse could
   reply to the author's reply, creating a deeper thread. These
   incoming reactions would be stored as interactions targeting the
   reply's URL. Displaying such nested threads is out of scope for the
   initial implementation but the data model supports it. **Consider this in
   the current implementation too, as mentioned in one of my previous comments
   too. Consider specifically how to render nested threads and how to adapt
   Webmentions and Pubby accordingly. However, from a data model perspective,
   not much should change - `in-reply-to` will still unamibiguously identify
   the parent. Then it's just up to the rendering logic to disentangle the
   threads.**
