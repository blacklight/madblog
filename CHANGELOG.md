# Changelog

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
