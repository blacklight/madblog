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

The runtime app is created in `madblog/app.py` and routes are registered in
`madblog/routes.py`.

## Package map

Top-level Python package:

- `madblog/`
  - `app.py`
  - `routes.py`
  - `config.py`
  - `cli.py`, `__main__.py`, `uwsgi.py`
  - `markdown/`
  - `activitypub/`
  - `webmentions/`
  - `feeds/`
  - `tags/`
  - `cache/`
  - `monitor.py`
  - `sync.py`
  - `notifications.py`
  - `constants/`

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
    - `ActivityPubMixin`, `CacheMixin`, `FeedsMixin`, `MarkdownMixin`,
      `WebmentionsMixin`
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
    - **Feeds** (`/feed.rss`, `/feed.atom`, `/rss`).
    - **Tags** (`/tags`, `/tags/<tag>`).
    - **ActivityPub helpers** (`/@<username>` redirect, `/followers`).

Routes delegate most content and caching logic back to `BlogApp` methods such as
`get_page()` and `get_pages_response()`.

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
  - Stores its JSON index in: `<content_dir>/.madblog/cache/tags-index.json`.
  - Extracts tags from multiple sources:
    - Metadata field `tags` (comma-separated)
    - Hashtags in title/description/body (with code/link protection)
    - Hashtags found in stored incoming webmention markdown for the post
  - Supports incremental updates via `TagIndex.reindex_file()` which is called
    on content changes.

- `madblog/tags/_parsers.py`
  - Shared tag normalization and hashtag extraction utilities.

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
    `<content_dir>/mentions/{incoming|outgoing}/<post-slug>/webmention-*.md`.
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
  - Tracks published objects and deleted URLs in
    `<content_dir>/.madblog/activitypub/*`.
  - Renders Markdown to HTML via `madblog.markdown.render_html` for ActivityPub
    objects.
  - Uses `StartupSyncMixin` to publish new/changed content on startup.

- `madblog/activitypub/_notifications.py`
  - Optional email notifications for ActivityPub interactions.

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
  - Shared blocklist checker for both Webmentions and ActivityPub.
  - Supports blocking by domain, URL, ActivityPub FQN, or regex.
  - Used by `WebmentionsMixin` and `ActivityPubMixin` to wrap incoming
    handlers and filter rendered interactions.

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
6. Webmentions + ActivityPub interactions are retrieved and rendered and passed
   into templates.
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

## Notes and operational considerations

- ActivityPub and Mermaid rendering depend on optional external tooling:
  - ActivityPub: Python package `pubby`
  - Mermaid: `mmdc` (Mermaid CLI) or `npx @mermaid-js/mermaid-cli`
- When running multiple WSGI workers, only one should run filesystem monitoring.
  `uwsgi.py` includes a lock-based guard for this.
