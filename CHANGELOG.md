# Changelog

## 1.3.5

### Fixed

- **Stale cached URLs without scheme**: `file_to_url` and
  `reply_file_to_url` now validate that cached URLs in `file_urls.json`
  have a proper `https://` (or `http://`) scheme. Entries cached before
  the URL normalization fix (v1.3.3) are discarded and regenerated,
  ensuring ActivityPub object IDs are always fully qualified URLs.

## 1.3.4

### Fixed

- Outgoing Webmentions are no longer sent for posts with `visibility:
  direct`, `visibility: followers`, or `visibility: draft`. Previously
  only ActivityPub federation respected visibility; Webmentions were
  always dispatched regardless.

### Changed

- Extracted shared `parse_metadata_header` utility into
  `madblog.markdown` to deduplicate metadata parsing across
  `webmentions/_storage.py`, `tags/_index.py`, and
  `activitypub/_integration.py`.

## 1.3.3

### Fixed

- **URL normalization for `link` and `activitypub_link` config**: Bare hostnames
  (e.g. `blog.example.com`) are now automatically normalized to include `https://`.
  This fixes ActivityPub federation issues where Mastodon/Akkoma couldn't find
  articles because the object `id` was missing the protocol scheme.

## 1.3.2

### Added

- Support both long and short URLs (or any supported URL aliases) for the in
  `reply-to` URL is an ActivityPub object not in the (canonical) long format.

## 1.3.1

### Added

- Support split-domain ActivityPub configuration also for Webmentions.

## 1.3.0

### Added

- **Reply Metadata Index** (`ReplyMetadataIndex`): A JSON-persisted metadata
  index for reply files that provides O(1) lookups without full directory scans.
  Stores `reply_to`, `like_of`, `visibility`, `published`, `has_content`, and
  `title` per file. Incrementally updated via `ContentMonitor` callbacks.
  Query methods: `get_unlisted_slugs()`, `get_ap_reply_slugs()`,
  `get_article_reply_slugs()`, `get_likes_for_target()`.
  ([#36](https://git.fabiomanganiello.com/madblog/issues/36))
- **Unlisted page**: Added _Posts and Replies_ tab.

### Changed

- **Author likes lookup migrated**: `author_likes` rendering in article and
  reply pages now uses `ReplyMetadataIndex.get_likes_for_target()`.

## 1.2.11

### Changed

- Removed **`guess_lang`** from codehilite extension for performance and
  stability reasons.

## 1.2.10

### Changed

- **Gunicorn `--preload` support**: Deferred content monitor startup from
  module-level to a `before_request` hook so that file-watcher threads are
  created *after* fork. This allows `gunicorn --preload` to share the
  loaded application across workers via copy-on-write, significantly
  reducing total memory usage.
- **Memory optimizations in `uwsgi` entry point**: Applied malloc arena
  limiting (`MALLOC_ARENA_MAX=2`) and reduced thread stack size (2 MB) to
  the gunicorn/uWSGI entry point, matching the CLI entry point.

### Added

- Expanded Quick Start section in README with `config.yaml` example and
  `docker run` usage.

## 1.2.9

### Added

- Support for **`new_tab`** configuration option for `nav_links`.

### Fixed

- **Threaded replies on root-level reply pages**: Author replies to fediverse
  replies were not rendered as nested children on root-level reply pages
  (e.g. `/reply/slug`). Three issues were fixed:
  - `_get_article_replies` now scans root-level `.md` files in the replies
    directory when `article_slug` is `None`, so other root-level replies can
    be discovered as thread descendants.
  - `_add_interaction_urls` now includes fediverse URL aliases (e.g.
    `/@user/ID` ↔ `/users/user/statuses/ID`) when building the set of valid
    parent URLs, so reply-to matching works regardless of URL format.
  - `_get_reply_interactions` now uses an iterative loop (instead of a fixed
    two-pass approach) to discover arbitrarily deep alternating chains of
    author replies and fediverse reactions (bounded to 10 iterations).

## 1.2.6

### Changed

- **External links configuration refactored**: Split `external_links` into three
  separate configurations:
  - `rel_me`: Links rendered as `<link rel="me">` in `<head>` for identity
    verification (e.g., Mastodon profile verification), not displayed visually.
  - `external_links`: Links displayed on the `/about` page, supporting both
    simple URLs and objects with `display_name` and `url` fields.
  - `nav_links`: Links added to the navigation panel, supporting `url`,
    `display_name`, and `icon` fields.

## 1.2.5

### Added

- **About page**: Optional `/about` page with
  [h-card](http://microformats.org/wiki/h-card) microformat support. Create an
  `ABOUT.md` file in your `pages_dir` to enable. Supports author metadata fields
  including name, photo, email, job title, organizations, PGP key, and rel="me"
  links. Falls back to existing config values (`author`, `author_url`, etc.)
  when metadata is not provided.

- **`hide_email` config option**: New configuration option to prevent email
  addresses from being displayed publicly on the About page while still allowing
  them to be used for notifications. Set `hide_email: true` in config.yaml or
  `MADBLOG_HIDE_EMAIL=1` environment variable.

- **Customizable default index page**: New `default_index` configuration option
  to set the default page shown at `/`. Supported values: `blog` (default),
  `about`, `tags`, `guestbook`. The blog index is always available at `/blog`
  regardless of this setting. Navigation menu now includes a "Blog" link.

## 1.2.4

### Fixed

- **Lists**: Support both 2-spaces and 4-spaces indentation in ordered and
  unordered lists in Markdown content.

- Fixed minor bug where Madblog still tried to federate draft messages but
  failed.

## 1.2.3

### Changed

- Better styling for **tables** in articles and posts.

## 1.2.2

### Fixed

- **Redundant profile update events on startup sync**: We don't need to send
  profile info to federated instance on every startup sync - only if they have
  changed since the last execution. This prevents verified profile links from
  going temporarily unverified until the next verification cycle on the remote
  instance is scheduled.

- **Duplicate Like activities**: Fixed an issue where Like activities were
  republished on every server restart when file mtimes changed (e.g., due to
  deployments, git operations, or file syncs). Likes are now skipped if the
  target URL hasn't changed, preventing duplicate like notifications to remote
  users.

## 1.2.1

### Fixed

- **ActivityPub**: Fixed minor activity parsing issue when the deliver object
  is a list

## 1.2.0

### Added

- **Auto-mention in replies**: Author replies now automatically mention the
  target author (e.g., `@user@domain`) in the ActivityPub payload, ensuring
  proper notification delivery. The mention is prepended to the HTML content
  and included in the AP `tag` and `cc` fields. Skipped if the author is
  already mentioned in the content.
- **Post visibility model**: Posts (articles and replies) now support visibility
  levels that control where they appear and how they are federated:
  - `public` (default): Appears in index/feeds, federated publicly
  - `unlisted`: Not in index, listed on `/unlisted`, federated with Public in CC
  - `followers`: Only via direct URL, federated to followers only
  - `direct`: Only via direct URL, federated to mentioned actors only
  - `draft`: Only via direct URL, not federated (for previewing)
- **`default_visibility` config**: Set global default visibility via
  `default_visibility` in config.yaml or `MADBLOG_DEFAULT_VISIBILITY` env var
- **Per-post visibility**: Override with `[//]: # (visibility: <level>)` metadata
- **Enhanced `/unlisted` page**: Now includes articles with `visibility: unlisted`
  in addition to root-level unlisted replies

### Changed

- **Unlisted replies**: Root-level replies without `reply-to`/`like-of` now
  default to `unlisted` visibility (backward compatible behavior)
- **Reactions filtering**: Replies with `followers`, `direct`, or `draft`
  visibility are excluded from article reactions display

### Fixed

- **Standalone likes publish state**: Standalone like files (author likes in
  reply folders) are now correctly marked as published during reply publish,
  preventing startup sync from reprocessing them on restart.
- **Private AP interactions filtered**: ActivityPub interactions that are not
  publicly addressed (missing `https://www.w3.org/ns/activitystreams#Public` in
  `to`/`cc`) are now filtered out before rendering in article comments and
  guestbook. This is a defense-in-depth measure complementing the upstream
  pubby fix.

## 1.1.7

### Added

- `/unlisted` timeline page for short-form "Fediverse-only" posts found in
  `replies/` root that contain content but no `reply-to`/` like-of` metadata.

### Fixed
- ActivityPub profile field verification: preserve the full URL (including
  scheme) in `rel="me"` link text (Mastodon verification compatibility).

## 1.1.6

### Added

- **Reactions:** Media attachments (images, videos, audio) from ActivityPub
  interactions and Webmentions are now rendered in a responsive grid layout
  below the reaction content. Supports up to 4 visible attachments with a
  collapsible overflow for additional media. Uses lazy-loading with placeholder
  animations and applies security attributes (`referrerpolicy="no-referrer"`,
  `rel="nofollow noopener noreferrer"`) on external media URLs.

## 1.1.5

### Added
- **Reactions**: Add per-interaction “liked by the author” mapping so author
  likes targeting remote Fediverse URLs are indexed and shown on the specific
  interaction (including fediverse URL aliases).
- **Replies:** Fix handling of standalone `like-of` files under
  `replies/<slug>` so they’re treated as likes (and excluded from replies) even
  when `reply-to` is auto-derived. This allows author likes to replies on
  articles to be rendered as likes on the liked post itself rather than generic
  author replies on the root level.

### Fixed
- **Feeds:** Fixed Python ≤ 3.10 compatibility in feed models (annotations +
  avoid forward-reference/walrus usage).

## 1.1.4

### Fixed
- Replies: exclude standalone “like” posts (entries with `like-of` but no
  `reply-to` and no content) when building the replies list, so author likes
  aren’t misclassified as replies.

## 1.1.3

### Added

- **Folder support:** Organize Markdown files in nested folders within
  `pages_dir`. Folders provide hierarchical navigation with:
  - Folder index pages at `/~folder/` with breadcrumbs and parent links
  - Per-folder RSS/Atom feeds at `/~folder/feed.rss` and `/~folder/feed.atom`
  - Folder metadata via `index.md` (title, description, image)
  - Custom landing pages when `index.md` has body content
  - Home page shows only root-level articles with folder cards
  - Hidden folders (`.` or `_` prefix) and empty folders are excluded
- **External feeds as folders:** New `external_feeds_as_folders` config option
  to display external RSS/Atom feeds as virtual folder entries on the home page
  instead of mixing them with local articles.

### Changed

- **Refactoring:** Extracted shared cache helpers (`compute_pages_mtime`,
  `set_cache_headers`, `make_304_response`) into `madblog/cache/_helpers.py`.
- **Refactoring:** Consolidated `get_page`/`get_reply` shared flow into
  `_make_content_response`.
- **Refactoring:** Split `_get_pages_from_files` into focused recursive and
  non-recursive helpers.

## 1.1.2

### Added
- **Reactions UI:** Show the *Reactions* section even when there are no
  reactions yet, as long as **Webmentions** or **ActivityPub** is enabled.
- **Reactions UI:** Added an expandable **“How to interact with this page”**
  panel with guidance for Webmentions and ActivityPub, plus new
  styling/animations.

### Changed
- **ActivityPub:** Enabled **async delivery** for outbound ActivityPub
  messages.
- **Dependencies:** Bumped **pubby** requirement to **>= 0.2.16**

## 1.1.1

### Added
- **Author reactions (likes):** Blog authors can now "like" posts on the
  Fediverse by adding `like-of: <URL>` metadata to articles or reply files.
  Likes are published as ActivityPub `Like` activities and automatically
  undone when the file is deleted or the metadata removed. A footer on the
  source page shows the liked URL, and target pages display a badge when
  liked by another of your posts.
- **Per-interaction reaction counters:** Individual reactions (ActivityPub
  interactions, Webmentions, and author replies) now display inline counters
  showing their own likes, replies, boosts, etc. Counters are fetched via
  efficient O(1) indexed lookups and include author reply children counted
  directly from the thread tree. URL translation handles cases where
  `activitypub_link` differs from the main blog `link`.

### Fixed
- **Guestbook thread leaking:** Fediverse replies to author replies (targeting
  `/reply/` URLs) and replies-to-replies (targeting remote fediverse URLs that
  are part of an article thread) were incorrectly shown in the guestbook. The
  guestbook filter now recognizes both `/article/` and `/reply/` URLs, and
  walks the reply chain via `get_interaction_by_object_id` to detect remote
  targets belonging to article threads.
- **Article page missing nested fediverse replies:** Fediverse
  reply-to-reply chains (e.g. a Mastodon reply to another Mastodon reply
  on an author reply) were not fetched for the article page. The article
  and reply page interaction logic now iteratively follows reply chains
  by collecting `object_id`s and fetching interactions targeting them.
- **Reply-to Mastodon pretty URLs:** Author replies using the Mastodon
  web UI URL format (`/@user/statuses/ID`) in their `reply-to` header
  were not threaded under the corresponding AP interaction (which uses
  the canonical `/users/user/statuses/ID` format). AP interaction nodes
  are now registered under both URL forms.

## 1.0.2

### Fixed
- **ActivityPub:** Replies now include the same quote policy fields as articles
  (`quote_control`, `quote_policy`, and `interaction_policy`), honoring the
  configured quote control rules.

### Tests
- Added coverage to ensure reply objects include the expected quote
  policy/interaction policy fields (e.g., for `activitypub_quote_control =
  "public"`).

## 1.0.1

### Fixed
- **activitypub:** Serve homepage content for HTML requests to `/ap/actor` and
  `/@<username>` instead of issuing an HTTP redirect, enabling Mastodon
  `rel="me"` profile verification. Adds `meta_redirect_to` support to inject a
  meta refresh redirect while still showing the correct HTML content, and
  updates content negotiation logic and tests accordingly.
- **docs:** Clarify author replies behavior: replies without `reply-to` act
  like “unlisted” posts (not shown on the index but available by
  URL/ActivityPub). Document guestbook posts under `replies/_guestbook/` and
  how replies work there.

## 1.0.0

### Added
- **Author replies:** Blog authors can now write replies to comments directly
  as Markdown files in `replies/<article-slug>/`. Replies are displayed inline
  in threaded reaction sections on article pages, with in-page navigation
  anchors and a dedicated `/reply/<article>/<slug>` route.
- **Author reply federation:** Author replies are federated via ActivityPub as
  `Note` objects with proper `inReplyTo` threading, and served as AP JSON when
  requested.
- **Reactions on reply pages:** Reply pages (`/reply/...`) now display their
  own threaded reactions (likes, boosts, replies from ActivityPub and
  Webmentions).
- **mf2 metadata rendering:** Webmentions now render microformats2 metadata
  including bookmarks, follows, RSVP, location, categories, syndication links,
  photos, videos, and audio attachments.
- **Mention cache persistence:** ActivityPub mention resolution cache is now
  persisted to disk, improving reliability across restarts.
- **Config flags for rendering features:** Added `enable_latex` and
  `enable_mermaid` configuration options (default: `true`) to explicitly
  disable LaTeX or Mermaid rendering even when dependencies are available.
  This helps reduce memory usage in environments where these features aren't
  needed. Configurable via `config.yaml` or environment variables
  (`MADBLOG_ENABLE_LATEX`, `MADBLOG_ENABLE_MERMAID`).

### Changed
- **Lazy loading of rendering extensions:** LaTeX and Mermaid markdown
  extensions are now loaded lazily on first render, not at module import time.
  This defers memory allocation until the features are actually used and
  respects the new config flags.
- **Deferred webmentions sync:** Webmentions `sync_on_startup` now runs after
  server start rather than during initialization, improving startup time.

### Fixed
- **Relative URL resolution:** Markdown relative URLs are now properly resolved
  to absolute URLs before rendering and outgoing webmention processing.
- **ActivityPub reply threading:** Fediverse replies now correctly thread under
  author replies across domains, with proper reply ID persistence to avoid
  delete/recreate collisions.
- **ActivityPub actor redirect:** `/ap/actor` now redirects HTML clients to the
  absolute profile URL for better browser compatibility.
- **Webmentions content normalization:** Legacy `"None"` string values in
  webmention content fields are now properly normalized to `null`.
- **Reply-to inference:** Author replies now correctly infer their parent from
  article slug paths when `reply-to` metadata is missing.

### Performance
- **Cache validation:** 304 responses now validate against interaction and
  tag index modification times, not just article content.

## 0.9.14

- **Fix:** Guestbook ActivityPub interactions now include **mentions** and
  **replies to non-article targets**, while continuing to exclude replies to
  articles (shown on article pages) and non-relevant interaction types
  (likes/boosts/quotes). Added tests covering the updated filtering behavior.
- **Chore:** Added an `md-toc` pre-commit hook and replaced the README’s
  placeholder TOC with an auto-generated one.
- **Docs:** Enhanced README with additional repository and package badges
  (issues, stars, forks, last commit, license, PyPI, Codacy, sponsor)

## 0.9.13

### Changed
- **feat(config):** Add configurable `state_dir` (config file +
  `MADBLOG_STATE_DIR`) with `resolved_state_dir` helper (default:
  `<content_dir>/.madblog`).
- **refactor(state):** Move all integration state under the resolved state directory:
  - **ActivityPub** state now stored in `<state_dir>/activitypub/state/` and
    keys default to `<state_dir>/activitypub/private_key.pem`.
  - **Webmentions** data moved to `<state_dir>/mentions/` and sync cache to
    `<state_dir>/webmentions_sync.json`.
  - **Tags** index cache moved to `<state_dir>/cache/tags-index.json`.
- **migration:** Automatically detect and migrate legacy layouts
  (`<content_dir>/activitypub`, `<content_dir>/mentions`) to the new `.madblog
  ` state directory, preserving file mtimes; runs early from CLI and uWSGI
  entrypoints.
- **tests/docs:** Add migration/state-dir resolution test coverage and update
  documentation + Docker volume examples to mount `/data/.madblog` for
  persistence.

## 0.9.10

### Fixed
- Tags page now applies the selected client-side sort on initial load (not only
  after clicking a sort button).

### Performance
- Reduced CLI/runtime memory overhead by capping glibc malloc arenas (apply
  `mallopt(M_ARENA_MAX=2)` and default `MALLOC_ARENA_MAX=2` for child
  processes).
- Lowered default thread stack size from 8 MB to 2 MB for daemon threads.

## 0.9.9

### Added
- **Guestbook:** Include ActivityPub interactions that *mention* the local
  actor (when storage supports `get_interactions_mentioning`), not just those
  targeting the actor URL.

### Changed
- **ActivityPub email notifications:** Detect actor mentions via
  `interaction.mentioned_actors` (instead of scanning HTML content) and notify
  even when the interaction targets a non-local URL, as long as the local actor
  is mentioned.

### Fixed
- **ActivityPub storage:** Limit stored interactions to local base URLs only
  (to avoid persisting interactions for third-party resources on single-user
  blogs); pass `local_base_urls` and `store_local_only` to the handler.
- **Tests:** Update notification tests to use `mentioned_actors` and improve coverage for mention vs non-local target filtering.

## 0.9.8

## Fixed
- ActivityPub email notifications now only trigger for **local targets**,
  preventing emails for interactions aimed at remote resources.

## 0.9.7

### Fixed
- ActivityPub content negotiation now correctly matches `Accept:
  application/ld+json` headers that include media type parameters (e.g.
  `profile="…"`) by stripping parameters before comparing.

## 0.9.6

### Fixed
- **ActivityPub content cleanup:** Strip common TOC marker lines (e.g.
  `[[TOC]]`, `[TOC]`, `{{ TOC }}`, `<!-- TOC -->`) from federated post content
  to prevent TOC artifacts from being published.
- **ActivityPub content negotiation:** Treat `Accept: application/ld+json` as
  requesting ActivityPub JSON (alongside `application/activity+json`),
  preferring AP JSON over `text/html` when appropriate.

### Tests
- Added coverage for TOC marker stripping across multiple formats.
- Added test ensuring `application/ld+json` Accept returns ActivityPub JSON.
- Tightened tests for mypy/nullability around attachments and response mimetype.

## 0.9.5

### Fixed
- Prevent WebFinger mention resolution from blocking request handling by moving lookups to background publish threads.
- Add a mention resolution cache and provide offline-safe fallback actor URLs (`https://{domain}/@{user}`) when the cache is empty.

### Changed
- Replace Pubby `extract_mentions` usage with explicit mention parsing + resolution via `Mention`/`resolve_actor_url`.
- Remove the manual publish retry loop; rely on Pubby’s internal Outbox delivery retries/backoff.
- Keep “mark as published” behavior before delivery to avoid re-queuing on restart after failures.

### Tests
- Update/replace publish retry tests to validate single publish call behavior, failure marking, mention caching, and bounded concurrency/non-blocking publish flow.

## 0.9.4

### Changed
- ActivityPub publishing now builds the AP object only once (including WebFinger/mention resolution) and retries **delivery only**
.
- Published entries are marked as processed **before** delivery to prevent startup sync re-queuing after crashes/restarts.

### Fixed
- Prevent runaway background publishing by capping concurrent publish threads (max 4) and de-duplicating publishes for the same UR
L (drops overlapping requests).

### Tests
- Added coverage for single-build behavior across retries, marking-as-published timing, build failures, URL de-dupe, and concurren
cy limits.

## 0.9.3

### Changed
- ActivityPub Create/Update deliveries now run in a background daemon thread to avoid blocking the content monitor loop.

### Fixed
- Added retry logic for Create/Update publishing: up to **3 attempts** with **60s backoff** between failures.
- After exhausting retries, failed publishes are still marked as processed to prevent repeated retries during startup sync.

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
