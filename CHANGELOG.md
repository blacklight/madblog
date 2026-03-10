# Changelog

## 0.9.2

### Added
- **Guestbook page** (`/guestbook`) aggregating homepage Webmentions and non-reply ActivityPub mentions, with `enable_guestbook` config/env t
oggle.
- **Guestbook feeds**: `/guestbook/feed.atom` and `/guestbook/feed.rss` with `limit`/`offset` pagination, plus template/header feed links.
- **Moderation allowlist mode** via `allowed_actors` (config/env), including shared permission checks, cached moderation lists, and follower 
reconciliation behavior.

### Changed
- Moderation semantics generalized from blocklist-only to **blocklist or allowlist** (mutually exclusive), applied consistently across Activi
tyPub, Webmentions, and guestbook rendering/processing.
- README/architecture docs expanded: feature overview, quickstart, installation clarifications, Markdown metadata/tags, configuration referen
ce, PWA notes, and guestbook documentation.

### Fixed
- **Email notifications**: strip HTML from ActivityPub/Webmention content/excerpts for plaintext emails (new `html_to_text` + tests).
- **Webmentions metadata parsing**: capture remaining Markdown body text as `content`.
- **ActivityPub key generation**: ensure private key directory exists before writing.

## 0.9.1

**Added**
- **ActivityPub**:
  - Exposed ActivityPub actor URL for `rel=me` verification, improving compatibility with decentralized identity tools.

## 0.9.0

**Added**
- **ActivityPub**:
  - **Mastodon-compatible API**:
    - Read-only subset of the Mastodon REST API, automatically registered when
      ActivityPub is enabled. Powered by Pubby's `bind_mastodon_api()` adapter.
    - Pubby-provided endpoints: `/api/v1/instance`, `/api/v2/instance`,
      `/api/v1/instance/peers`, `/api/v1/accounts/lookup`,
      `/api/v1/accounts/:id`, `/api/v1/accounts/:id/statuses`,
      `/api/v1/accounts/:id/followers`, `/api/v1/statuses/:id`,
      `/nodeinfo/2.0[.json]`, `/nodeinfo/2.1.json`.
    - Madblog-specific endpoints: `/api/v1/tags/:tag` (tag entity with 7-day
      usage history from TagIndex), `/api/v2/search` (search accounts, hashtags,
      and statuses).
- **Moderation**:
  - New `blocked_actors` configuration option to block unwanted Webmentions
    and ActivityPub interactions by domain, URL, FQN, or regular expression.
  - Blocked actors are rejected at ingestion time (before storage or Accept
    delivery) and also filtered at render time for pre-existing data.
  - Blocked followers are excluded from outgoing delivery (fan-out) and
    public follower counts, but kept on disk marked as `"blocked"`.
  - On startup, followers whose matching blocklist rule was removed are
    automatically restored.
  - Blocklist is cached with a 5-minute TTL to avoid filesystem
    round-trips during publish.
  - Configurable via `config.yaml` (list) or `MADBLOG_BLOCKED_ACTORS`
    environment variable (comma/space-separated).

**Fixed**
- **Webmentions**:
  - Ignore malformed URLs when processing outgoing mentions.

**Changed**
- **Docker**:
  - Full Dockerfile no longer explicitly installs Pubby.

## 0.8.4

- **ActivityPub**:
  - Added `rel=me` links for separate ActivityPub domains to ensure compatibility with Mastodon and other federated platforms.
  - Make `pubby` a required dependency. ActivityPub integration is now natively provided by Madblog.

## 0.8.3

**Fixed**
- **Webmentions**:
  - Store Webmention sync cache under `root_dir` to ensure consistency and avoid permission issues.

- **ActivityPub**:
  - Fixed object ID/URL separation for cross-domain ActivityPub setups.
  - Ensured proper separation of ActivityPub object IDs and public URLs for compatibility.

## 0.8.0

**Added**
- **ActivityPub enhancements**:
  - Display ActivityPub handle (e.g., `@user@domain`) in the navigation bar and followers page.
  - Show follower count in the navigation bar and a dedicated followers page (`/followers`).
  - Added a followers counter bar on the home page.
  - Support for `activitypub_link` and `activitypub_domain` configuration options to override ActivityPub actor/profile URLs and WebFinger domains.
  - Allow separate base URLs for ActivityPub content and assets (e.g., images).
  - Turn inline HTML/Markdown images into ActivityPub attachments for richer federated posts.
  - Added support for configurable ActivityPub actor profile fields.
- **UI/UX improvements**:
  - Moved followers and feed links into a hamburger menu for cleaner navigation.
  - Added tag pill styles for better visual hierarchy.
  - Tweaked header opacity, padding, and sidebar rounding for improved aesthetics.
- **Documentation**:
  - Added `ARCHITECTURE.md` for an overview of the project’s structure.
  - Replaced the `README.md` title with a logo image.
  - Added contributor guidelines for AGENTS (AI-assisted development).

**Changed**
- **Refactoring**:
  - Split email notifiers into dedicated `activitypub` and `webmentions` modules.
  - Extracted caching, webmentions, and app helpers into dedicated mixins for better maintainability.
  - Applied `black` formatting for consistent code style.
- **ActivityPub**:
  - Run ActivityPub startup tasks (e.g., follower sync) in a background thread to avoid blocking the main application.
  - Use canonical object URLs when fetching interactions to ensure consistency.

**Fixed**
- **ActivityPub**:
  - Guarded request/app context in content negotiation and caching to prevent runtime errors.
  - Aligned actor profile URLs and `rel=me` verification for Mastodon compatibility.
  - Made metadata parsing more tolerant to avoid crashes on malformed input.

## 0.7.0

- Full **ActivityPub** integration (closes #11)

## 0.6.17

**Added**

- Support for **tags** (closes #16)

## 0.6.15

**Added**

- Added Drone CI integration for automated testing and deployment
- Added ASCII-art splash logo displayed at application start

**Changed**

- Always display splash logo at start instead of conditionally showing it
- Updated Docker installation approach with new Dockerfiles for minimal and
  full installations using quay.io base image
- Enhanced installation documentation in README.md with clearer minimal and
  full installation sections and recommended pre-built image commands

## 0.6.14

**Added**

- Added `Language` headers for articles and pages with support for
  article-level language metadata (`[//]: # (language: xx-XX)`) and global
  configuration fallback
- Added `ETag` headers for robust cache validation based on file modification
  times with support for `If-None-Match` header validation
- Extended cache headers (`Last-Modified`, `Cache-Control`, `ETag`, `Language`)
  to home page/index and RSS/Atom feeds
- Added comprehensive conditional request handling supporting both
  `If-Modified-Since` and `If-None-Match` headers
- Added test suites for cache validation, language headers, and ETag
  functionality

**Changed**

- Enhanced cache implementation to avoid redundant file system traversal by reusing modification times from page metadata parsing
- Improved metadata parsing to include file modification times (`file_mtime`) for optimized cache header generation
- Cache validation now supports multiple validation methods (timestamp-based and ETag-based) for maximum browser compatibility

**Fixed**

- Fixed cache invalidation to properly detect when markdown files are modified and serve fresh content immediately
- Fixed browser caching behavior to eliminate need for force refresh (Ctrl+F5) when content changes

## 0.6.13

**Added**

- Added proper cache headers

**Fixed**

- Fixed Markdown metadata parser to be more robust — it now correctly skips
  blank lines, YAML front-matter delimiters (`---`), and heading lines instead
  of silently breaking on them.

**Changed**

- Media elements (`img`, `video`, `audio`) now always have `max-width: 100%`
  regardless of nesting depth (not just direct children of `<p>`), and are
  capped at `max-height: 75vh` to prevent oversized embeds.
- Blockquotes are now styled with italic text, a left border, and padding for
  better visual distinction.

## 0.6.7

**Fixed**

- Fixed regression in the installation of static JS resources

## 0.6.6

**Added**

- Added copy to clipboard button for code blocks

## 0.6.4

**Fixed**

- Don't break page rendering if a Markdown contains LaTeX block but either
  `latex` is missing on the system or the blocks content is wrong.

## 0.6.3

**Added**

- Added raw Markdown page viewer (see [issue
  #15](https://git.fabiomanganiello.com/madblog/issues/15))

## 0.6.2

**Changed**

- **Changed project license from MIT to AGPL-3.0-only.**
- LaTeX support is now auto-detected from content delimiters (`$$`, `$`,
  `\(...\)`, `\[...\]`) — the `latex: 1` metadata header is no longer
  required.
- Rewrote LaTeX delimiter parsing with proper block vs inline classification.
- Reduced default LaTeX font size by ~25%.
- Added dark mode support for rendered LaTeX expressions.
- Moved LaTeX CSS to `blog.css` and fixed inline expression vertical alignment.

## 0.6.1

**Added**

- Added support for tasklists in Markdown files

## 0.6.0

**Added**

- Support for Mermaid diagrams (see [issue
  #12](https://git.fabiomanganiello.com/madblog/issues/12))

- Support for [[TOC]] markers in Markdown files (see [issue
  #13](https://git.fabiomanganiello.com/madblog/issues/13))

**Fixed**

- Fixed undetermined behaviour where both `madblog` and `uwsgi` or `gunicorn`
  try and parse `sys.argv`

## 0.5.3

**Added**

- Added Docker support

## 0.5.2

**Changed**

- Minor stylistic improvements on the homepage view

## 0.5.0

**Added**

- Support for "_aggregator mode_" (see [issue
  #9](https://git.fabiomanganiello.com/madblog/issues/9)). This allows you to
  render content from external sources on your Website too, as long as they
  provide an RSS/Atom feed.
- Added authors information to generated RSS/Atom feeds

**Changed**

- `config`: Renamed `webmentions_email` to `author_email`

## 0.4.14

**Added**

- Added `rel=me` attribute to author URL on articles

**Changed**

- Use `feedgen2` (self-maintained fork of `feedgen`) to generate RSS/Atom feeds,
  since `feedgen` is no longer maintained and it includes serious bugs in the
  Atom feed generation.

**Fixed**

- Don't break rendering if `config.link` is not configured

## 0.4.13

**Changed**

- Many stylistic improvements

## 0.4.11

**Added**

- Support for configurable blog home view modes: `cards` (default), `list`, and
  `full`. Set via `view_mode` in config, `MADBLOG_VIEW_MODE` env var, or
  override at runtime with the `?view=` query parameter.

- Frontend support to toggle view mode on the home page

## 0.4.5

**Fixed**

- Send notifications only on new Webmentions (not edited/deleted ones)

## 0.4.2

**Changed**

- Changed format routes: `/feed?format=rss` -> `/feed.rss` and `/feed?format=atom` -> `/feed.atom`

## 0.4.0

**Added**

- Support for dark theme (closes #8)
- sans-serif font instead of serif for articles body
- Several stylistic improvements

## 0.3.8

**Added**

- Added `limit` parameter to feed routes

## 0.3.7

**Fixed**

- The legacy `/rss` route should transparently provide the same content as `/feed?type=rss` - not a redirect.

## 0.3.6

**Fixed**

- Fixed feeds generation

## 0.3.3

**Added**

- Added Atom feeds under `/feed?type=atom`.
- Added `max_entries_per_feed` configuration parameters for RSS and Atom feeds (default: 10).

**Changed**

- Feed generation migrated to the new `feedgen` library.
- Default RSS route changed from `/rss` to `/feed?type=rss` for consistency with Atom feed.

## 0.3.2

**Added**

- Added support for email notifications on Webmentions

- Added `default_webmention_stats`

## 0.3.1

**Changed**

- Use the new `render_webmentions` API from the `webmentions` library to render
  mentions instead of managing templates directly.

## 0.3.0

**Added**

- [Support for Webmentions](https://git.fabiomanganiello.com/blacklight/madblog/pulls/1)
  (see [issue #2](https://git.fabiomanganiello.com/blacklight/madblog/issues/2)).
- Support for `rel="me"` links in the blog header for Mastodon and other social profiles.

## 0.2.37

**Added**

- Support for passing article URL to `article.html` and `common-head.html` for improved Open Graph meta tags.
- Updated `index.html` to include URL, ensuring consistent metadata structure across templates.

**Changed**

- Adjusted Markdown processing to apply proper extensions in rendering.

## 0.2.35

- Use _Lora_ font for the article body.

## 0.2.24

- Better default fonts - `sans-serif` style for the index and the titles,
  `serif` for the articles' body.

## 0.2.19

- Added `short_feed` configuration flag to permanently disable returning the
  full content of the articles in the RSS feed.

## 0.2.16

- Removed `alt` attribute from LaTeX rendered `<img>` tags. It may generate
  non-standard Unicode characters that break the RSS feed.

## 0.2.14

- Better support for PWA tags and added a default config-generated `/manifest.json`.

## 0.2.3

- Fix for broken RSS feed URLs when a blog has no pages.
- Propagate the command-line arguments even when the app is launched through uWSGI.

## 0.2.2

- Proper support for PWA (progressive web app) optional logic.

## 0.2.1

- Support for serving a `manifest.json`.

## 0.2.0

- If `img` and `markdown` aren't present under `content_dir` then treat
  `content_dir` itself as a root folder for images and pages.

- Improved rendering of articles on smaller screens.

- Support for articles/pages organized in folders.

- Infer the title from the Markdown header or from the file name if it's
  not provided in the Markdown metadata.

- Infer published date from the file's creation date if it's not provided
  in the Markdown metadata.

## 0.1.12

- Infer the published date from the file creation date if it's not available in
  the Markdown metadata.

## 0.1.11

- Fixed `max-width` for article body on large screens.

## 0.1.9

- Fixed `overflow-x` on articles template.

## 0.1.8

- Added rendering of the main article image on the article header.

## 0.1.7

- Added footer to pages.

## 0.1.6

- Support for `/rss?short` URL for short articles description on the RSS feed.

## 0.1.5

- Support for config.logo = false.

## 0.1.4

- Titles of HTML pages now match the configured blog title.

## 0.1.2

- Fixed RSS feed support.
- Added `header` configuration option (the blog header can now be removed).

## 0.1.1

First usable version, with several bug fixes and better documentation.

## 0.1.0

First draft.
