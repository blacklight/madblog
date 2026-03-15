# Implementation Summary: Folder Support

## Files Modified

### `madblog/app.py`

- Added `_is_hidden_folder(name)` — checks for `.` or `_` prefix
- Added `_get_folders_in_dir(folder)` — returns visible subfolders with metadata
- Added `_is_folder_empty(folder)` — recursive check for content
- Added `_build_breadcrumbs(folder)` — generates navigation path
- Added `_get_parent_folder(folder)` — returns parent folder info
- Added `get_folder_index(folder)` — renders folder listing or custom index.md
- Modified `_get_pages_from_files()` — added `folder` and `recursive` parameters
- Modified `get_pages()` — added `folder`, `recursive`, `include_external_feeds`
- Modified `get_pages_response()` — added folder context to template

### `madblog/markdown/_mixin.py`

- Added `_parse_folder_metadata(folder_path)` — parses index.md for folder
  metadata and detects if it has body content

### `madblog/routes.py`

- Modified `home_route()` — now uses `recursive=False` for non-recursive listing
- Added `folder_index_route()` — handles `/~<folder>/` URLs
- Added `_get_folder_feed()` — generates per-folder RSS/Atom feeds
- Added `folder_feed_route()` — handles `/~<folder>/feed.<type>` URLs

### `madblog/templates/index.html`

- Added breadcrumb navigation block
- Added parent link block
- Added folders section with folder cards
- Updated page title/description/URL for folder context
- Simplified article listing (removed old folder grouping)

### `madblog/static/css/home.css`

- Added `.breadcrumbs` styles
- Added `.folders-section` and `.folders-grid` styles
- Added `.folder-card` styles with responsive breakpoints

### `tests/test_folders.py`

New test file with 35 tests covering:
- Folder visibility (hidden, empty folders)
- Folder metadata from index.md
- Folder routing (index, feeds, nested)
- Home page folder listing
- Breadcrumb navigation
- View mode inheritance

## Test Results

All 415 tests pass (380 existing + 35 new folder tests).
