# Phase 1 — Core Reply Storage and Rendering

Implementation summary for the first phase of author replies.

Reference: [`02-PLAN.md` §Phase 1](../02-PLAN.md)

---

## Storage Layout

Replies live under `<content_dir>/replies/<article-slug>/`:

```
<content_dir>/
├── markdown/          # articles (pages_dir)
└── replies/
    ├── my-post/
    │   └── thanks-alice.md
    └── _guestbook/
        └── welcome.md
```

`_guestbook` is the reserved pseudo-slug for replies to guestbook
entries.

## Metadata Format

Reply Markdown files use the standard `[//]: #` comment headers:

```markdown
[//]: # (reply-to: https://mastodon.social/users/alice/statuses/123)
[//]: # (published: 2025-07-02)

# Re: Thanks Alice

Thank you for your thoughtful response!
```

- **`reply-to`** (required) — the URL being replied to (article URL,
  Webmention source, or AP interaction `object_id`).
- **`title`** (optional) — explicit title. Falls back to `# heading`
  inference, then to the reply slug.
- **`published`** (optional) — ISO date. Falls back to file ctime.

## URL Scheme

| URL | Purpose |
|---|---|
| `/reply/<article-slug>/<reply-slug>` | Rendered HTML reply page |
| `/reply/<article-slug>/<reply-slug>.md` | Raw Markdown source |

## Files Changed

### `madblog/app.py`

- **`BlogApp.__init__()`** — added `self.replies_dir` property
  (`<content_dir>/replies`).
- **`_get_pages_from_files()`** — converted from list comprehension to
  loop; prunes `replies_dir` from `os.walk` so replies never appear on
  the home page. This handles the fallback case where `pages_dir ==
  content_dir`.
- **`get_reply(article_slug, reply_slug, *, as_markdown=False)`** —
  new method that mirrors `get_page()` for replies: parses metadata,
  handles cache headers (Last-Modified, ETag, 304), returns rendered
  HTML or raw Markdown.
- **`_render_reply_html()`** — renders the reply Markdown through the
  `reply.html` template; passes `reply_to`, `article_slug`, and
  standard author/date context.

### `madblog/markdown/_mixin.py`

- **`replies_dir: Path`** — declared on the `MarkdownMixin` abstract
  class.
- **`_parse_reply_metadata(article_slug, reply_slug)`** — new method
  that resolves `replies_dir/<article_slug>/<reply_slug>.md`, extracts
  metadata, and sets `uri` to `/reply/<article_slug>/<reply_slug>`.
  Includes path-traversal guard (realpath must start with
  `replies_dir`).
- **`_infer_title_and_url_from_markdown()`** — fixed to skip blank
  lines, YAML front-matter delimiters, and `[//]: #` metadata comment
  lines before looking for a `# heading`. Previously it broke on the
  first non-heading line, which prevented title inference when metadata
  appeared before the heading. Also strips trailing whitespace from the
  captured title. This is a backward-compatible improvement that
  benefits articles too.

### `madblog/routes.py`

- **`/reply/<path:article_slug>/<reply_slug>`** — new route delegating
  to `app.get_reply()`.
- **`/reply/<path:article_slug>/<reply_slug>.md`** — raw Markdown
  variant.

`<path:article_slug>` handles nested article paths (e.g.
`2025/my-post`).

### `madblog/templates/reply.html` (new)

Structurally similar to `article.html` with these differences:

- **Back-link banner** at the top: `↩ In reply to <reply-to URL>`.
- No tags section.
- No webmentions/AP interactions section (to be added in Phase 2 for
  nested threads).
- Uses `common-head.html`, `footer.html`, `common-tail.html` includes.

## Tests

### `tests/test_replies.py` (new — 15 tests)

**`ReplyRouteTest`** (8 tests):

- `test_reply_route_renders` — 200 + content present.
- `test_reply_backlink_rendered` — reply-to URL in HTML.
- `test_reply_raw_markdown` — `.md` route returns `text/markdown`.
- `test_reply_404_nonexistent` — missing reply → 404.
- `test_reply_404_nonexistent_article` — missing article slug → 404.
- `test_guestbook_reply_route` — `_guestbook` pseudo-slug works.
- `test_reply_cache_headers` — Last-Modified, ETag, Cache-Control.
- `test_reply_published_date` — formatted date in HTML.

**`RepliesExcludedFromHomeTest`** (1 test):

- `test_replies_excluded_from_pages_listing` — replies under
  `replies/` do not appear in `_get_pages_from_files()`, even when
  `pages_dir == content_dir`.

**`ReplyMetadataParsingTest`** (4 tests):

- `test_reply_to_extracted` — `reply-to` field parsed.
- `test_reply_uri_scheme` — URI is `/reply/…`.
- `test_reply_title_parsed` — explicit title metadata.
- `test_reply_published_date` — published date parsed.

**`ReplyTitleInferenceTest`** (2 tests):

- `test_title_inferred_from_heading` — heading after metadata lines.
- `test_title_falls_back_to_slug` — no heading, no metadata → slug.

## Gaps / Follow-up Notes

- The `reply.html` template does not yet display reactions (webmentions
  or AP interactions) on the reply page itself. This is needed for
  nested threads and will be addressed in Phase 2.
- No ActivityPub or Webmention federation yet — replies are purely
  local content at this point. Phase 4 will add federation.
- The `_infer_title_and_url_from_markdown` fix is a general
  improvement; existing article tests continue to pass but no
  dedicated regression test was added for articles (the fix is
  exercised by `ReplyTitleInferenceTest`).
