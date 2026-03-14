# Author Replies — Follow-ups

Items deferred from the initial implementation phases.

---

## Per-article Reply Feeds

Expose an RSS/Atom feed for replies under a given article:

```
/reply/<article-slug>/feed.rss
/reply/<article-slug>/feed.atom
```

This lets followers subscribe to the author's conversation activity on
a specific post without polling the full article page.

---

## Reply Counts in the Home Page Listing

Show a small reply/reaction count badge on each article card in the
home page listing (e.g. "3 replies"). Requires a lightweight scan of
`replies/<article-slug>/` (file count) during `_get_pages_from_files()`
or a cached count.

---

## Collapsible Thread UI

Add a CSS/JS toggle to collapse and expand long threads, following the
existing collapsible-content pattern used in pubby's
`interaction.html` (checkbox + `:has()` selector). Useful when a post
accumulates many nested replies.

---

## Incoming Replies to Author Replies

When someone on the fediverse replies to an author reply, the incoming
interaction's `target_resource` will be the reply's permalink URL
(e.g. `https://blog.example.com/reply/my-post/thanks-alice`). These
nested remote reactions should eventually be displayed on the reply's
own page, creating deeper thread trees. The data model already supports
this (the interaction is stored with `target_resource` pointing at the
reply URL); only the rendering and collection logic needs extending.
