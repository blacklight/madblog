# Changelog

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
