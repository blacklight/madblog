# Implementation Plan: Folder Support

This document details the implementation phases for improved folder support in
Madblog.

---

## Phase 1: Core Data Model and Helpers

### 1.1 Add folder listing helper

Create `_get_folders_in_dir()` in `madblog/app.py`:

```python
def _get_folders_in_dir(self, folder: str = "") -> List[dict]:
    """
    Return visible subfolders in the given folder path.
    
    - Excludes hidden folders (starting with . or _)
    - Excludes empty folders (no articles, no visible subfolders)
    - Parses index.md for folder metadata if present
    """
```

Returns list of dicts with keys:
- `name`: folder basename
- `path`: relative path from `pages_dir`
- `uri`: `/~<path>/`
- `title`: from `index.md` metadata or folder name
- `description`: from `index.md` metadata
- `image`: from `index.md` metadata

### 1.2 Add folder metadata parser

Create `_parse_folder_metadata()` in `madblog/markdown/_mixin.py`:

```python
def _parse_folder_metadata(self, folder_path: str) -> dict:
    """
    Parse metadata from index.md in the given folder.
    
    Returns:
        - metadata dict if index.md exists
        - {"has_content": True/False} to indicate if it has body content
    """
```

### 1.3 Modify `_get_pages_from_files()`

Add parameters:
- `folder: str = ""` — restrict to this folder
- `recursive: bool = True` — if False, only list direct children

When `recursive=False`:
- Only include `.md` files directly in the folder
- Exclude `index.md` from article listing (it's folder metadata)

### 1.4 Add `get_folder_index()` method

New method in `BlogApp`:

```python
def get_folder_index(
    self,
    folder: str,
    *,
    view_mode: str = "cards",
) -> Response:
    """
    Render folder index page or custom index.md content.
    """
```

Logic:
1. Validate folder path (security check)
2. Check for `index.md` with content → render as article
3. Otherwise, render folder listing with:
   - Breadcrumbs
   - Parent link (if not root)
   - Subfolders (sorted alphabetically)
   - Articles (sorted by time)

---

## Phase 2: Routes

### 2.1 Add folder index route

In `madblog/routes.py`:

```python
@app.route("/~<path:folder>/", methods=["GET"])
@app.route("/~<path:folder>", methods=["GET"])
def folder_index_route(folder: str):
    view_mode = request.args.get("view", config.view_mode)
    if view_mode not in ("cards", "list", "full"):
        view_mode = config.view_mode
    return app.get_folder_index(folder, view_mode=view_mode)
```

### 2.2 Add per-folder feed routes

```python
@app.route("/~<path:folder>/feed.<type>", methods=["GET"])
def folder_feed_route(folder: str, type: str):
    return _get_folder_feed(request, folder, type)
```

Implement `_get_folder_feed()` similar to `_get_feed()` but scoped to folder.

---

## Phase 3: Templates

### 3.1 Extend `index.html`

Add conditional blocks for:
- **Breadcrumbs**: `{% if breadcrumbs %}` block at top
- **Parent link**: `{% if parent_folder is not none %}` block
- **Folders section**: `{% if folders %}` block before articles

Template receives new context variables:
- `breadcrumbs`: list of `{"name": str, "uri": str}`
- `parent_folder`: `{"name": str, "uri": str}` or `None`
- `folders`: list from `_get_folders_in_dir()`
- `current_folder`: relative path string

### 3.2 Add folder card partial

Create `folder-card.html` or inline in `index.html`:

```jinja2
<a class="folder-card" href="{{ folder.uri }}">
  <div class="folder-icon">📁</div>
  <div class="folder-title">{{ folder.title }}</div>
  {% if folder.description %}
  <div class="folder-description">{{ folder.description }}</div>
  {% endif %}
</a>
```

### 3.3 Add CSS for folder cards

In `madblog/static/css/home.css`:
- `.folder-card` styling (similar to article cards)
- `.breadcrumbs` styling

---

## Phase 4: Home Page Changes

### 4.1 Modify `home_route()`

Update to use non-recursive listing:

```python
@app.route("/", methods=["GET"])
def home_route():
    # ... existing view_mode logic ...
    return app.get_pages_response(
        folder="",
        recursive=False,  # NEW
        # ... rest unchanged ...
    )
```

### 4.2 Update `get_pages_response()`

Add `folder` and `recursive` parameters. Pass `folders` context to template.

External feeds should only appear when `folder == ""` (root).

---

## Phase 5: Per-Folder Feeds

### 5.1 Implement `_get_folder_feed()`

Similar to `_get_feed()` but:
- Validate folder path
- Get pages from specific folder (non-recursive)
- Set feed ID/link to folder URL

---

## Phase 6: Tests

### 6.1 Unit tests (`tests/test_folders.py`)

- `test_get_folders_in_dir_excludes_hidden`
- `test_get_folders_in_dir_excludes_empty`
- `test_folder_metadata_from_index_md`
- `test_folder_index_with_custom_content`
- `test_folder_index_default_listing`
- `test_folder_security_path_traversal`
- `test_folder_feed_scoped_to_folder`
- `test_root_shows_only_top_level`
- `test_view_mode_inherited`

### 6.2 Integration tests

- Test nested folder navigation
- Test breadcrumb links
- Test feed content scoping

---

## Phase 7: Documentation

### 7.1 Update README.md

Expand the "Folders" section with:
- URL scheme (`/~folder/`)
- `index.md` usage
- Per-folder feeds
- Hidden folder conventions

### 7.2 Update ARCHITECTURE.md

Add "Folders subsystem" section describing:
- `_get_folders_in_dir()` helper
- `index.md` handling
- Route structure

---

## File Changes Summary

| File | Changes |
|------|---------|
| `madblog/app.py` | Add `_get_folders_in_dir()`, `get_folder_index()`, modify `_get_pages_from_files()`, `get_pages_response()` |
| `madblog/markdown/_mixin.py` | Add `_parse_folder_metadata()` |
| `madblog/routes.py` | Add `/~<folder>/` and `/~<folder>/feed.<type>` routes, modify `home_route()` |
| `madblog/templates/index.html` | Add breadcrumbs, parent link, folders section |
| `madblog/static/css/home.css` | Add folder card, breadcrumb, parent link styles |
| `tests/test_folders.py` | New test file |
| `README.md` | Expand Folders section |
| `docs/ARCHITECTURE.md` | Add Folders subsystem section |

---

## Estimated Complexity

- **Phase 1**: Medium (core logic)
- **Phase 2**: Low (routing)
- **Phase 3**: Medium (template changes)
- **Phase 4**: Low (wiring)
- **Phase 5**: Low (feed variant)
- **Phase 6**: Medium (comprehensive tests)
- **Phase 7**: Low (documentation)

Total: ~400-600 lines of code + tests.
