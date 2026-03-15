# Research: Folder Support Improvements

## Current Implementation

### How pages are indexed

`BlogApp._get_pages_from_files()` in `madblog/app.py` walks `pages_dir`
recursively using `os.walk()`:

```python
for root, dirs, files in os.walk(pages_dir, followlinks=True):
    # Exclude the replies directory from the home page listing
    dirs[:] = [d for d in dirs if os.path.join(root, d) != replies_dir]
    for f in files:
        if not f.endswith(".md"):
            continue
        pages.append({
            "path": os.path.join(root[len(pages_dir) + 1 :], f),
            "folder": root[len(pages_dir) + 1 :],
            ...
        })
```

- Every `.md` file under `pages_dir` (recursively) is included
- Each page gets a `folder` key with the relative path from `pages_dir`
- The `replies/` directory is explicitly excluded

### How pages are sorted

`PagesSortByTimeGroupedByFolder` in `madblog/_sorters.py` groups articles by
folder, sorted by most recent article within each folder:

```python
def __call__(self, page: dict) -> Tuple:
    return (
        self._max_date_by_folder[page.get("folder", "")],
        _normalize_dt(page.get("published", self._default_published)),
    )
```

### How the index is rendered

`index.html` template detects folder changes and renders folder headers:

```jinja2
{% for i, page in pages %}
  {% if 'cur_folder' not in state or page.get('folder') != state.get('cur_folder') %}
    <div class="folder">
      {% set folder = page.get('folder') %}
      {% if folder %}
        <div id="{{ folder.replace('/', '-') }}" class="folder-title">
          <a href="#{{ folder.replace('/', '-') }}">{{ folder }}</a>
        </div>
      {% endif %}
```

Currently, folder titles are just anchor links (`#folder-name`), not navigation
links.

### Article URL scheme

Articles are served at `/article/<path>/<article>` where `<path>` includes any
folder hierarchy. This already handles nested folders correctly.

---

## Reserved URL Namespaces

Based on analysis of `routes.py`, the following top-level paths are reserved:

| Path | Purpose |
|------|---------|
| `/` | Home page |
| `/@<username>` | ActivityPub profile |
| `/article/` | Article pages |
| `/reply/` | Author replies |
| `/img/`, `/js/`, `/css/`, `/fonts/` | Static assets |
| `/tags`, `/tags/<tag>` | Tag pages |
| `/guestbook`, `/guestbook/feed.*` | Guestbook |
| `/followers` | ActivityPub followers list |
| `/feed.*`, `/rss` | RSS/Atom feeds |
| `/api/` | Mastodon-compatible API |
| `/manifest.json`, `/favicon.ico` | PWA assets |
| `/pwabuilder-sw*.js` | Service worker |
| `/ap/` | ActivityPub endpoints (via pubby) |
| `/webmentions` | Webmentions endpoint |
| `/.well-known/` | WebFinger, nodeinfo |

**Conflict risk**: If a folder under `pages_dir` is named `img`, `tags`, `guestbook`, `api`, `ap`, etc., direct mapping (`/folder/index`) would clash with existing routes.

---

## Proposed Solutions Analysis

### Option A: Folders rendered on index (with prefix)

**URL scheme**: `/~<folder>/` for folder index, `/~<folder>/<subfolder>/` for nested folders

**Rationale for `~`**:
- Semantically suggests "contents of" or "belonging to" (Unix home directory convention)
- URL-safe, no encoding needed
- Short and unobtrusive
- Not used by any reserved namespace
- Clearly distinguishes folder navigation from articles

**Alternatives considered**:
- `/folder/<name>` — verbose, adds noise
- `/!<name>` — works but `!` may need encoding in some contexts
- `/$<name>`, `/%<name>` — `$` and `%` have special meaning in URLs
- `/+<name>` — works but less intuitive than `~`

**Pros**:
- Simple, flat URL structure
- No ambiguity with reserved paths
- Easy to implement

**Cons**:
- Slightly non-standard URLs

### Option B: Folders as collapsible `<details>` blocks

**URL scheme**: Same as Option A for folder index links, but folders are rendered inline on the parent index with expand/collapse.

**Pros**:
- More interactive UX
- Users can preview folder contents without navigation

**Cons**:
- More complex UI/JS
- Could become overwhelming with many nested folders
- Full view mode becomes even more problematic
- Harder to deep-link to folder contents

### Option C: Separate "📂 Folders" page

**URL scheme**: `/~folders` or nav link to a dedicated folders listing

**Pros**:
- Clean separation of concerns

**Cons**:
- Extra navigation step
- Less discoverable
- Folders feel like second-class citizens

---

## Chosen Approach

**Option A** — render folders directly on the index, above articles, with links
to `/~<folder>/`.

### Key design decisions

1. **Index pages only show current level**
   - Root `/` shows only root-level `.md` files + folder links
   - `/~folder/` shows only that folder's `.md` files + subfolder links
   - No recursive listing

2. **URL scheme**
   - Folder index: `/~<folder>/` (trailing slash optional, canonicalized)
   - Nested: `/~<folder>/<subfolder>/`
   - Per-folder feeds: `/~<folder>/feed.rss`, `/~<folder>/feed.atom`
   - Articles remain at `/article/<folder>/<article>`

3. **Folder rendering position**
   - Folders appear **above** articles on the index
   - Sorted alphabetically
   - Articles sorted by timestamp (existing behavior)

4. **Back-link to parent**
   - A `📁 ..` or `↩ Back` link at the top of each folder index
   - Links to parent folder or root

5. **Navigation breadcrumbs**
   - Show current path: `Home > Folder > Subfolder`
   - Each segment is a clickable link

6. **Security**
   - Path traversal protection via `os.path.realpath()` + startswith check
   - Consistent with existing `_resolve_and_parse_metadata()` pattern

### Folder index pages

Folder index pages inherit **all features** from the root index:
- View modes (cards, list, full) via `?view=` query param
- Same template structure and styling
- Breadcrumb navigation added

### `index.md` support

If a folder contains an `index.md` file:

1. **With content** (non-empty after trimming): The file is rendered as the
   folder's index page, completely overriding the default folder listing. This
   allows fully custom landing pages for sections.

2. **Metadata only** (empty or whitespace-only content): The file provides
   folder metadata (title, description, image) used in:
   - The folder card on the parent index
   - The folder's `<head>` metadata
   - The breadcrumb display name

Metadata format follows the standard `[//]: # (key: value)` convention.

### Folder visibility rules

- **Hidden folders**: Folders starting with `.` or `_` are not shown (e.g.,
  `.drafts`, `_archive`). This is consistent with common conventions.
- **Empty folders**: Folders with no visible articles AND no visible subfolders
  are hidden. A folder containing only an `index.md` (metadata-only) is
  considered empty unless it has subfolders.

### Feed and ActivityPub considerations

- Root feeds (`/feed.rss`, `/feed.atom`) continue to aggregate **all** articles
  recursively (unchanged behavior)
- Per-folder feeds at `/~<folder>/feed.rss` and `/~<folder>/feed.atom` include
  only articles in that folder (non-recursive)
- ActivityPub: articles continue to use `/article/` URLs, unchanged

### External feeds

- External feeds (from `external_feeds` config) are rendered **only at root
  level** (current behavior preserved)
- **Follow-up**: Add `external_feeds_as_folders` config option to render
  external feeds as virtual folders

---

## Implementation Outline

### Phase 1: Core routing and data model
- Add `/~<path:folder>/` route
- Add `/~<path:folder>/feed.<type>` route
- Modify `_get_pages_from_files()` to accept optional `folder` and `recursive`
  parameters
- Add `_get_folders_in_dir()` helper with hidden/empty folder filtering
- Add `_parse_folder_metadata()` for `index.md` handling

### Phase 2: Templates
- Extend `index.html` to handle folder context (breadcrumbs, parent link,
  folder cards)
- Add folder card styling (reuse article card structure)
- Ensure view mode selector works on folder pages

### Phase 3: Home page changes
- Modify root `/` to use non-recursive listing
- Render folder links above articles
- Ensure external feeds still appear at root

### Phase 4: Per-folder feeds
- Implement `/~<folder>/feed.rss` and `/~<folder>/feed.atom`
- Feed includes only articles in that specific folder

### Phase 5: Documentation
- Update README (Folders section)
- Update ARCHITECTURE.md

---

## Follow-ups

1. **`external_feeds_as_folders`** config option — render external feeds as
   virtual folder entries on the home page
2. **Folder-level ActivityPub** — optional per-folder actors (complex, likely
   out of scope)
