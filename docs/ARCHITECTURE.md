# Madblog Architecture

This document describes the high-level architecture of **Madblog**, a Python
Markdown-based blogging platform built on Flask, with optional ActivityPub and
Webmentions support.

## Overview

Madblog is structured as a small Flask application class (`madblog.app.BlogApp`)
that composes independent feature areas via mixins:

- `MarkdownMixin` for content loading and Markdown → HTML rendering
- `CacheMixin` for HTTP cache validation helpers (ETag / If-Modified-Since)
- `FeedsMixin` for aggregating remote RSS/Atom feeds into the homepage
- `WebmentionsMixin` for inbound/outbound Webmentions storage and processing
- `ActivityPubMixin` for ActivityPub actor + object publishing (optional)
- `GuestbookMixin` for aggregating public mentions into a guestbook page
- `RepliesMixin` for author reply management and interaction threading

The runtime app is created in `madblog/app.py` and routes are registered in
`madblog/routes.py`.

## Package map

Top-level Python modules:

| Module | Description |
|---|---|
| `activitypub` | Optional ActivityPub support |
| `app` | Main application class |
| `cache` | Cache handling + HTTP headers |
| `cli` | Command-line interface |
| `config` | Configuration handling |
| `constants` | Constants and regular expressions |
| `feeds` | RSS+Atom feed handling |
| `guestbook` | Guestbook support |
| `markdown` | Markdown subsystem |
| `reactions` | Reaction thread tree builder (combines Webmentions, AP interactions, author replies) |
| `replies` | Author replies management and interaction threading |
| `monitor` | Background filesystem monitor |
| `notifications` | Notifications handling |
| `routes` | Flask routes |
| `state` | State directory management and migrations |
| `sync` | Background sync tasks |
| `tags` | Tags subsystem |
| `uwsgi.py` | uWSGI entry point |
| `webmentions` | Webmentions subsystem |
| `__main__.py` | CLI entry point |


The `static/` and `templates/` directories under `madblog/` provide the default
UI assets.

## Entry points and boot

### CLI entry point

- `madblog/__main__.py`
  - Delegates to `madblog.cli.run()`.

- `madblog/cli.py`
  - Reads CLI args (`--config`, `--host`, `--port`, `--debug`) and determines the
    blog directory.
  - Initializes configuration via `madblog.config.init_config()`.
  - Imports the application instance from `madblog.app` (`from .app import app`).
  - Starts background services (`app.start()`), runs the Flask dev server
    (`app.run(...)`), and stops background services (`app.stop()`).

### uWSGI/gunicorn entry point

- `madblog/uwsgi.py`
  - Initializes configuration primarily from environment variables.
  - Imports the app instance (`from .app import app`) and exposes
    `application = app` for WSGI servers.
  - Starts the background filesystem monitor only once using a lock file and, in
    uWSGI, only in worker 1.

## Configuration

- `madblog/config.py`
  - Defines `Config` (dataclass) and a global singleton `config`.
  - Loads config from:
    - A YAML config file (typically `config.yaml` in the content directory)
    - Environment variables (`MADBLOG_*`)
    - CLI arguments (where applicable)

Configuration controls:

- Content locations (`content_dir`)
- Site metadata (title, description, link, language)
- Optional integrations (webmentions, ActivityPub)
- Email notifications (SMTP)
- Feed aggregation (external feeds)

## Core application

- `madblog/app.py`
  - Defines `BlogApp`, which inherits:
    - `flask.Flask`
    - `RepliesMixin`, `ActivityPubMixin`, `CacheMixin`, `FeedsMixin`,
      `GuestbookMixin`, `MarkdownMixin`, `WebmentionsMixin`
  - Establishes content directory layout:
    - Markdown pages: `<content_dir>/markdown` (fallback: `<content_dir>`)
    - Assets: `<content_dir>/{img,css,js,fonts,templates}` with fallback to
      package-provided defaults.
  - Initializes feature subsystems:
    - Webmentions (`_init_webmentions`) which creates `ContentMonitor`.
    - ActivityPub (`_init_activitypub`) which binds pubby routes and registers
      a content-change hook.
    - Tag index (`TagIndex`) and registers it to content change notifications.

### Background services

`BlogApp.start()` is responsible for:

- Building the tag index (`TagIndex.build()`).
- Registering callbacks on `content_monitor`.
- Starting the filesystem monitor (`ContentMonitor.start()`).

`BlogApp.stop()` stops the content monitor.

Important invariant:

- `content_monitor` is created by `WebmentionsMixin` (even if webmentions are
  disabled, it is still used to observe content changes for other features).

## HTTP routes

- `madblog/routes.py`
  - Imports the global `app` instance from `madblog.app`.
  - Registers Flask routes for:
    - **Home page** (`/`): list of posts, including remote feed items.
    - **Articles** (`/article/...`): render a Markdown file as HTML.
    - **Raw Markdown** (`/article/... .md`): returns Markdown source.
    - **Assets** (`/img`, `/css`, `/js`, `/fonts`, `/manifest.json`).
    - **Feeds** (`/feed.rss`, `/feed.atom`, `/rss`): blog article feeds.
    - **Guestbook feeds** (`/guestbook/feed.rss`, `/guestbook/feed.atom`).
    - **Tags** (`/tags`, `/tags/<tag>`).
    - **Guestbook** (`/guestbook`): aggregated mentions page.
    - **ActivityPub helpers** (`/@<username>` redirect, `/followers`).

Routes delegate most content and caching logic back to `BlogApp` methods such as
`get_page()` and `get_pages_response()`.

### Feed generation

Feed routes use `feedgen.FeedGenerator` to produce RSS 2.0 and Atom 1.0 feeds:

- `_get_feed()`: Generates blog article feeds from `app.get_pages()`. Supports
  `?limit`, `?short` query parameters and HTTP cache validation
  (`If-Modified-Since`, `If-None-Match`).
- `_get_guestbook_feed()`: Generates guestbook feeds from
  `app.get_guestbook_webmentions()` and `app.get_guestbook_ap_interactions()`.
  Supports `?limit` (default 25) and `?offset` query parameters.

## Markdown subsystem

- `madblog/markdown/_mixin.py` (`MarkdownMixin`)
  - Resolves and validates Markdown file paths under `pages_dir`.
  - Extracts metadata from “comment headers” of the form:
    ` [//]: # (key: value)`
  - Infers the page title and optional external URL from the first `# Title`
    header.
  - Handles published date inference from filesystem metadata when missing.

- `madblog/markdown/_render.py`
  - Defines `render_html(md_text: str) -> str`.
  - Uses Python-Markdown with a predefined extension pipeline.

- `madblog/markdown/_processors/*`
  - Custom Python-Markdown preprocessors:
    - `autolink.py`: wraps bare URLs in `<...>`.
    - `tasklist.py`: task-list rendering.
    - `toc.py`: table-of-contents marker support.
    - `latex.py`: LaTeX rendering (and related caching).
    - `mermaid.py`: Mermaid blocks rendered to SVG via `mmdc`/`npx`.
    - `tags.py`: converts `#tags` to links to `/tags/<tag>`.
    - `activitypub.py`: converts `@user@domain` to profile links.

### Render cache

- `madblog/cache/_render.py` (`RenderCache`)
  - Shared file-based cache for expensive rendering steps (e.g. Mermaid).
  - Stored under the system temporary directory.

## Feeds subsystem (remote aggregation)

- `madblog/feeds/_mixin.py` (`FeedsMixin`)
  - Creates a `FeedParser` for `config.external_feeds`.
  - Transforms parsed feed entries into “page-like” dicts which are merged into
    the homepage list.

- `madblog/feeds/_parser.py` (`FeedParser`)
  - Concurrent parsing using `feedparser` and a `ThreadPoolExecutor`.
  - Simple in-memory cache with optional expiry.

- `madblog/feeds/_model.py`
  - Dataclasses for `Feed`, `FeedEntry`, `FeedAuthor`, `FeedLink`.
  - Handles robust date parsing for common RSS/Atom timestamp formats.

## Tags subsystem

- `madblog/tags/_index.py` (`TagIndex`)
  - Builds and persists a mapping `tag -> posts`.
  - Stores its JSON index in: `<state_dir>/cache/tags-index.json`.
  - Extracts tags from multiple sources:
    - Metadata field `tags` (comma-separated)
    - Hashtags in title/description/body (with code/link protection)
    - Hashtags found in stored incoming webmention markdown for the post
  - Supports incremental updates via `TagIndex.reindex_file()` which is called
    on content changes.

- `madblog/tags/_parsers.py`
  - Shared tag normalization and hashtag extraction utilities.

## Folders subsystem

Folders provide hierarchical navigation within `pages_dir`. The implementation
lives primarily in `madblog/app.py` with routes in `madblog/routes.py`.

### URL scheme

- `/~<folder>/` — folder index page
- `/~<folder>/feed.rss`, `/~<folder>/feed.atom` — per-folder feeds
- Articles remain at `/article/<folder>/<article>`

### Key methods in `BlogApp`

- `_get_folders_in_dir(folder)` — returns visible subfolders with metadata
- `_is_folder_empty(folder)` — checks if folder has no visible content
- `_is_hidden_folder(name)` — checks for `.` or `_` prefix
- `_build_breadcrumbs(folder)` — generates navigation breadcrumbs
- `_get_parent_folder(folder)` — returns parent folder info
- `get_folder_index(folder)` — renders folder listing or custom `index.md`

### Folder metadata

- `MarkdownMixin._parse_folder_metadata(folder_path)` parses `index.md` in a
  folder to extract title, description, image, and detect if it has body content.
- If `index.md` has content, it is rendered as a custom landing page.
- If `index.md` has only metadata, it provides folder card information.

### Visibility rules

- Folders starting with `.` or `_` are hidden
- Empty folders (no articles or visible subfolders) are not shown
- The `replies/` directory is always excluded

## Webmentions subsystem

Webmentions are provided by the external `webmentions` package, with a Madblog
file-based storage implementation.

- `madblog/webmentions/_mixin.py` (`WebmentionsMixin`)
  - Builds `FileWebmentionsStorage`.
  - Builds a `WebmentionsHandler`.
  - Binds Flask endpoints via `webmentions.server.adapters.flask.bind_webmentions`
    when enabled.
  - Creates the `ContentMonitor` and registers `FileWebmentionsStorage` as a
    listener when webmentions are enabled.

- `madblog/webmentions/_storage.py` (`FileWebmentionsStorage`)
  - Persists each webmention as a Markdown file under:
    `<state_dir>/mentions/{incoming|outgoing}/<post-slug>/webmention-*.md`.
  - Implements outgoing webmention processing on content changes.
  - Implements startup resync via `StartupSyncMixin`.

- `madblog/webmentions/_notifications.py`
  - Optional email notifications on new inbound webmentions.

## ActivityPub subsystem

ActivityPub is optional and only active when enabled in configuration and the
external dependency `pubby` is installed.

- `madblog/activitypub/_mixin.py` (`ActivityPubMixin`)
  - Validates/generates the ActivityPub RSA private key file.
  - Instantiates pubby’s `ActivityPubHandler` and binds Flask endpoints via
    `pubby.server.adapters.flask.bind_activitypub`.
  - Creates an `ActivityPubIntegration` instance and registers it as a
    `ContentMonitor` callback.
  - Handles content negotiation:
    - If the client prefers `application/activity+json`, `BlogApp.get_page()` can
      return an ActivityPub object representation of the page.

- `madblog/activitypub/_integration.py` (`ActivityPubIntegration`)
  - Bridges filesystem content changes to ActivityPub publishing.
  - Tracks published objects and deleted URLs in `<state_dir>/activitypub/`.

- `madblog/activitypub/_mixin.py` (`ActivityPubMixin`)
  - Validates/generates the ActivityPub RSA private key file at
    `<state_dir>/activitypub/private_key.pem` (or custom path via
    `activitypub_private_key_path` config).
  - Stores pubby's `FileActivityPubStorage` data under
    `<state_dir>/activitypub/state/`.
  - Renders Markdown to HTML via `madblog.markdown.render_html` for ActivityPub
    objects.
  - Uses `StartupSyncMixin` to publish new/changed content on startup.

- `madblog/activitypub/_notifications.py`
  - Optional email notifications for ActivityPub interactions.

## Guestbook subsystem

The guestbook provides a dedicated page (`/guestbook`) aggregating public
mentions from Webmentions and ActivityPub into a single "guest registry" view.

- `madblog/guestbook/_mixin.py` (`GuestbookMixin`)
  - Mixed into `BlogApp` to provide guestbook functionality.
  - **Data sources:**
    - Webmentions where the target URL is the home page (`get_guestbook_webmentions()`)
    - ActivityPub mentions targeting the actor that are not replies to articles
      (`get_guestbook_ap_interactions()`)
  - **Key methods:**
    - `get_guestbook_webmentions()`: Queries `webmentions_handler` for mentions
      targeting the base URL (with and without trailing slash), deduplicates by
      source URL, filters blocked actors, and sorts by published date.
    - `get_guestbook_ap_interactions()`: Queries `activitypub_handler.storage`
      for interactions with `target_resource` set to the actor ID, filters to
      `interaction_type == "mention"`, applies blocklist, deduplicates by
      activity/object ID, and sorts by published date.
    - `get_rendered_guestbook_webmentions()`: Returns rendered HTML via
      `webmentions_handler.render_webmentions()`.
    - `get_rendered_guestbook_ap_interactions()`: Returns rendered HTML via
      `activitypub_handler.render_interactions()`.
    - `get_guestbook_count()`: Returns total entry count (webmentions + AP).

- `madblog/guestbook/__init__.py`
  - Exports `GuestbookMixin`.

### Route

- `madblog/routes.py` (`/guestbook`)
  - Returns 404 if `config.enable_guestbook` is false.
  - Retrieves raw Webmentions and AP interactions, builds a threaded
    reactions tree via `build_thread_tree()`, computes reaction counts,
    and renders `guestbook.html` with the tree.
  - Sets `Cache-Control: no-store` to ensure fresh data.

### Frontend

- `madblog/templates/guestbook.html`
  - Displays title, description with interaction instructions (Webmention and/or
    Fediverse mention links depending on enabled features).
  - Includes the unified `reactions.html` template to render the threaded
    reactions tree.
  - Empty state message when no entries exist.

- `madblog/templates/common-head.html`
  - Conditionally renders a "Guestbook" navigation link when
    `config.enable_guestbook` is true.

### Configuration

- `config.enable_guestbook` (default: `true`)
  - Config file: `enable_guestbook: true|false`
  - Environment variable: `MADBLOG_ENABLE_GUESTBOOK=1|0`

## Author Replies subsystem

Author replies allow the blog owner to respond to incoming reactions
(Webmentions, ActivityPub interactions, or other replies) as plain
Markdown files. Replies are threaded inline on article pages and
federated via ActivityPub.

### Storage layout

Reply files live under `<content_dir>/replies/`, organized by article
slug:

```
<content_dir>/replies/<article-slug>/<reply-slug>.md
```

The special slug `_guestbook` holds replies to guestbook entries.
Replies are excluded from the home page listing by an explicit guard in
`BlogApp._get_pages_from_files()`.

### Metadata and `reply-to` derivation

Each reply file uses the same `[//]: # (key: value)` metadata format as
articles. The `reply-to` key specifies the URL of the reaction being
replied to (a Webmention source, an AP interaction `object_id`, or
another reply's permalink).

When `reply-to` is omitted, `ActivityPubRepliesMixin._parse_reply_metadata()`
derives it from the directory structure:
`replies/<article-slug>/…` → `{base_url}/article/<article-slug>`.

### Threading model (`madblog/reactions.py`)

`build_thread_tree()` combines raw Webmentions, AP interactions, and
author reply dicts into a single tree of `ThreadNode` objects:

1. Each reaction/reply is assigned a **unique identity**:
   - Webmentions: `source` URL
   - AP interactions: `object_id` (fallback: `activity_id`)
   - Author replies: `full_url` (`config.link + permalink`)

2. Each node's `reply_to` is resolved:
   - Webmentions: `None` (top-level for now)
   - AP interactions (reply/quote type): `target_resource`
   - Author replies: `reply-to` metadata value

3. Nodes are linked: if `reply_to` matches another node's identity, the
   node becomes a child; otherwise it is a root.

4. Roots are sorted by published date descending; children ascending.

### Dual-domain alias mechanism

When `activitypub_link` differs from `link`, author reply URLs have two
origins: `config.link + permalink` (public/blog domain) and
`ap_integration.base_url + permalink` (AP domain). AP interactions
arriving from the Fediverse use `target_resource` set from the AP
domain, which would not match the blog-domain identity.

To bridge this, `_get_page_interactions()` annotates each author reply
with an `ap_full_url` key when the two domains differ. `build_thread_tree()`
registers author reply nodes under **both** the primary identity and the
AP alias, so AP interactions can find their parent regardless of which
domain they target. A deduplication guard (`seen` set on object `id()`)
prevents alias entries from creating duplicate roots during tree
construction.

### Interaction loading

`BlogApp._get_page_interactions()` fetches AP interactions for an
article by querying `storage.get_interactions(target_resource=...)`:

1. The article's own AP URL (from `ap_integration.file_to_url()`).
2. Each author reply's AP URL (via `extra_target_urls`), so that
   Fediverse replies to author replies are included in the tree.

pubby's `FileActivityPubStorage` stores interactions in directories
named after a sanitized + SHA-256-hashed `target_resource`, so the
lookup URL must match the stored `target_resource` exactly.

### Federation (`madblog/activitypub/_replies.py`)

`ActivityPubRepliesMixin` handles publishing replies as AP `Note`
objects:

- `build_reply_object()`: builds a `Note` with `in_reply_to` set from
  the `reply-to` metadata. The `cc` list includes the original author's
  actor ID (resolved via `get_interaction_by_object_id()`) so the reply
  threads correctly on their instance.
- `on_reply_change()`: callback for the `replies_monitor`
  `ContentMonitor`. Dispatches Create/Update/Delete activities.
- `sync_replies_on_startup()`: walks `replies_dir` and publishes any
  new or modified replies missed while the server was down.

A second `ContentMonitor` instance (`replies_monitor`) watches
`replies_dir` independently from the main `content_monitor` that watches
`pages_dir`.

### Rendering

The unified `reactions.html` template renders the thread tree
recursively using Jinja2 macros. It handles all three node types
(Webmention, AP interaction, author reply) and supports arbitrary
nesting depth with CSS-based indentation (capped at depth 5).

### Routes

- `GET /reply/<article-slug>/<reply-slug>` → rendered reply page
- `GET /reply/<article-slug>/<reply-slug>.md` → raw Markdown source

### Key files

| File | Role |
|---|---|
| `madblog/app.py` | `get_reply()`, `replies_dir`, `replies_monitor` |
| `madblog/routes.py` | `/reply/…` routes |
| `madblog/reactions.py` | `build_thread_tree()`, `ThreadNode`, `ReactionType`, AP alias handling |
| `madblog/replies/_mixin.py` | `RepliesMixin`: `_get_article_replies()`, `_get_page_interactions()`, `_get_reply_interactions()`, `_render_reply_html()` |
| `madblog/activitypub/_replies.py` | `ActivityPubRepliesMixin`: AP Note publishing, reply-to derivation, startup sync |
| `madblog/templates/reply.html` | Reply page template |
| `madblog/templates/reactions.html` | Unified threaded reactions template |

## Shared infrastructure

- `madblog/monitor.py` (`ContentMonitor`)
  - Watchdog-based recursive filesystem monitor.
  - Dispatches `ChangeType` events (added/edited/deleted) to registered
    callbacks.
  - Implements per-path throttling/debouncing.

- `madblog/sync.py` (`StartupSyncMixin`)
  - Generic mtime-tracking for “sync on startup” behavior.
  - Used by Webmentions storage and ActivityPub integration.

- `madblog/moderation.py`
  - Shared moderation checker for both Webmentions and ActivityPub.
  - Supports two mutually exclusive modes:
    - **Blocklist mode** (`blocked_actors`): actors matching patterns are rejected.
    - **Allowlist mode** (`allowed_actors`): only actors matching patterns are
      permitted; all others are rejected.
  - Pattern matching supports domain, URL, ActivityPub FQN, or regex.
  - `ModerationCache` (aliased as `BlocklistCache` for backwards compatibility):
    TTL-based cache (5 min) around `config.blocked_actors`/`config.allowed_actors`
    to avoid filesystem lookups during fan-out delivery.
  - `validate_moderation_config()`: raises `ModerationConfigError` if both
    blocklist and allowlist are configured.
  - `is_actor_permitted()`: convenience function that checks permission based
    on the current moderation mode.
  - Used by `WebmentionsMixin` and `ActivityPubMixin` to wrap incoming
    handlers, filter rendered interactions, and exclude non-permitted followers
    from outgoing delivery.
  - At startup, `ActivityPubMixin` reconciles follower JSON files:
    - In blocklist mode: followers matching the blocklist are marked
      `"blocked": true`; previously blocked followers whose rule was removed
      are restored.
    - In allowlist mode: followers NOT matching the allowlist are marked
      `"blocked": true`; previously blocked followers who now match the
      allowlist are restored.

- `madblog/notifications.py`
  - Shared SMTP helper (`send_email`) and `SmtpConfig`.

- `madblog/constants/_regex.py`
  - Central regex patterns used across features:
    - Hashtags
    - Markdown metadata
    - Mermaid blocks
    - Bare URLs
    - ActivityPub mentions

## Dependency structure (high level)

A simplified dependency view (arrows point “uses”):

- `routes.py` -> `app.py` -> mixins
- `app.py` -> `config.py`, `monitor.py`, `tags/`, `markdown/`, `feeds/`,
  `webmentions/`, `activitypub/`
- `webmentions/_storage.py` -> `monitor.py`, `sync.py`, external `webmentions`
- `activitypub/_integration.py` -> `monitor.py`, `sync.py`, `markdown/`, external `pubby`
- `markdown/_render.py` -> `markdown/_processors/*`, external `markdown`
- `tags/_index.py` -> `constants`, `tags/_parsers.py`

Key architectural choice:

- The application core is intentionally thin: most features are isolated behind
  mixins and are wired together in `BlogApp.__init__()`.

## Main request flows

### Render a page (HTML)

1. Request `GET /article/<slug>`.
2. `routes.py` calls `app.get_page(slug)`.
3. `MarkdownMixin` parses metadata and resolves the markdown file.
4. `CacheMixin` checks `If-Modified-Since` / `If-None-Match`.
5. Markdown content is rendered to HTML via `markdown.render_html()`.
6. Webmentions, ActivityPub interactions, and author replies are collected,
   combined into a threaded tree via `build_thread_tree()`, and passed into
   templates.
7. Response headers are set:
   - `Last-Modified`, `ETag`, `Cache-Control`
   - `Link: <...>; rel="webmention"` (if enabled)
   - `Link: <...>; rel="alternate"; type="application/activity+json"` (if AP bound)

### Render a page (ActivityPub JSON)

1. Client sends `Accept: application/activity+json` (and prefers it over HTML).
2. `BlogApp.get_page()` detects the preference.
3. `ActivityPubIntegration.build_object()` constructs an AP object for the file.
4. Response is returned with `application/activity+json` and cache headers.

### Home page list

1. Request `GET /`.
2. `routes.py` calls `app.get_pages_response(...)`.
3. `BlogApp.get_pages()` collects:
   - Local Markdown posts (`_get_pages_from_files`)
   - Remote feed items (`FeedsMixin._get_pages_from_feeds`)
4. Pages are sorted using a sorter from `madblog/_sorters.py`.
5. Index template is rendered; response cache headers are computed from the most
   recent local post mtime.

### Content change propagation

1. `ContentMonitor` observes filesystem changes under `pages_dir`.
2. It dispatches `(ChangeType, path)` events after throttling.
3. Registered listeners are invoked:
   - Webmentions storage: (re)process outgoing webmentions for that article
   - ActivityPub integration: publish updates
   - Tag index: reindex the changed file

## Progressive Web App (PWA)

Madblog is installable as a Progressive Web App, providing offline access and an
app-like experience on supported devices.

### Components

- **Web App Manifest** (`/manifest.json`)
  - Served by `madblog/routes.py`.
  - If a custom `manifest.json` exists in `content_dir`, it is used directly;
    otherwise a default manifest is generated from `config.title` with standard
    icon sizes and standalone display mode.

- **Service Worker** (`madblog/static/js/pwabuilder-sw.js`)
  - Uses [Workbox](https://developer.chrome.com/docs/workbox/) for caching.
  - Implements a **stale-while-revalidate** strategy: cached assets are served
    immediately while fetching fresh versions in the background.
  - Background sync plugin retries failed requests for up to 24 hours.

- **Registration** (`madblog/static/js/pwabuilder-sw-register.js`)
  - Registers the service worker and adds a `<pwa-update>` component to notify
    users when a new version is available.

### Timeline notifications

When ActivityPub is enabled, followers on Mastodon and other fediverse platforms
receive new and updated articles directly in their home timelines. This provides
a push-like notification experience without requiring browser push APIs — users
simply follow the blog's ActivityPub actor and see new posts appear alongside
their regular fediverse feed.

## Notes and operational considerations

- ActivityPub and Mermaid rendering depend on optional external tooling:
  - ActivityPub: Python package `pubby`
  - Mermaid: `mmdc` (Mermaid CLI) or `npx @mermaid-js/mermaid-cli`
- When running multiple WSGI workers, only one should run filesystem monitoring.
  `uwsgi.py` includes a lock-based guard for this.
