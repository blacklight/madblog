# Media Attachments in Replies — Research

## Current State

### Data Sources

#### 1. ActivityPub Interactions

AP interactions store the full object in `metadata["raw_object"]`, which includes an `attachment` array. Each attachment follows the ActivityPub format:

```json
{
  "type": "Image",      // or "Video", "Audio", "Document"
  "mediaType": "image/png",
  "url": "https://example.com/media/image.png",
  "name": "Alt text / description"
}
```

**Location**: `pubby/_model.py` defines `Interaction.metadata` as a dict. The inbox handler (`pubby/handlers/_inbox.py:420`) stores `{"raw_object": obj_data}`.

**Current rendering**: `reactions.html:render_ap_interaction` does NOT render attachments — only `interaction.content`.

#### 2. Webmentions

Webmentions store mf2 metadata in `metadata["mf2"]`, including:
- `photo` / `photo_url`: List of photo URLs
- `video` / `video_url`: List of video URLs  
- `audio` / `audio_url`: List of audio URLs

**Location**: `webmentions/handlers/_parser.py:261-269` populates these fields from h-entry properties.

**Current rendering**: `reactions.html:render_webmention` (lines 187-222) already renders mf2 media inside a `.reaction-mf2` container. This is a working reference.

#### 3. Author Replies

Author replies are Markdown files rendered via `_get_article_replies()` in `replies/_mixin.py`. Media in the Markdown body becomes part of `content_html`.

**Current state**: No explicit attachment metadata. Images are inline in content.

---

## Proposed Approach

### Shared Rendering Logic

Create a **shared Jinja macro** `render_media_attachments(attachments)` that:
1. Accepts a normalized list of attachment dicts: `[{type, url, name, media_type}, ...]`
2. Renders them in a responsive grid layout (similar to Mastodon's media grid)
3. Supports image, video, and audio elements

### Attachment Normalization

To share rendering logic, normalize attachments from different sources into a common format:

```python
{
    "type": "image" | "video" | "audio",  # lowercase normalized
    "url": str,                            # required
    "name": str | None,                    # alt text / description
    "media_type": str | None,              # e.g. "image/jpeg"
}
```

#### For AP Interactions
Extract from `interaction.metadata.get("raw_object", {}).get("attachment", [])`:

**Works retroactively** — existing stored interactions already contain the full `raw_object` with attachments. Example from stored Mastodon reply:
```json
"attachment": [{
  "type": "Document",
  "mediaType": "image/jpeg",
  "url": "https://files.mastodon.social/.../original/6fcad595359203ca.jpg",
  "name": "Stock image",
  "blurhash": "UYHd{ZIrM|t6...",
  "width": 534,
  "height": 800
}]
```

Normalization rules:
- **Type detection**: Use `mediaType` as primary (Mastodon uses `type: "Document"` for images, not `"Image"`)
  - `mediaType.startswith("image/")` → `"image"`
  - `mediaType.startswith("video/")` → `"video"`
  - `mediaType.startswith("audio/")` → `"audio"`
  - Fallback to `type` field if no `mediaType`
- Use `url` directly (may be string or `{"href": "..."}`)
- Use `name` for alt text
- Optional: `blurhash`, `width`, `height` for placeholders/aspect ratio

#### For Webmentions
Already normalized in mf2 metadata. Extract from `wm.metadata.mf2`:
- `photo` → `[{type: "image", url: url}]`
- `video` → `[{type: "video", url: url}]`
- `audio` → `[{type: "audio", url: url}]`

#### For Author Replies
Not needed initially — media is embedded in `content_html`. Could be added later via frontmatter metadata.

### Template Structure

```jinja
{# Shared macro for media grid #}
{% macro render_media_attachments(attachments) %}
  {% if attachments %}
  <div class="reaction-media-grid" data-count="{{ attachments|length }}">
    {% for att in attachments %}
      {% if att.type == 'image' %}
        <a href="{{ att.url }}" class="reaction-media-item" ...>
          <img src="{{ att.url }}" alt="{{ att.name or '' }}" loading="lazy" referrerpolicy="no-referrer" />
        </a>
      {% elif att.type == 'video' %}
        <video class="reaction-media-item" controls preload="metadata" ...>
          <source src="{{ att.url }}" {% if att.media_type %}type="{{ att.media_type }}"{% endif %} />
        </video>
      {% elif att.type == 'audio' %}
        <audio class="reaction-media-item" controls preload="metadata">
          <source src="{{ att.url }}" {% if att.media_type %}type="{{ att.media_type }}"{% endif %} />
        </audio>
      {% endif %}
    {% endfor %}
  </div>
  {% endif %}
{% endmacro %}
```

### CSS Grid Layout

Similar to Mastodon's approach with a responsive grid that adapts based on attachment count:

```css
.reaction-media-grid {
  display: grid;
  gap: 0.25em;
  margin-top: 0.75em;
  border-radius: 0.5em;
  overflow: hidden;
}

/* 1 item: full width */
.reaction-media-grid[data-count="1"] {
  grid-template-columns: 1fr;
}

/* 2 items: side by side */
.reaction-media-grid[data-count="2"] {
  grid-template-columns: 1fr 1fr;
}

/* 3 items: 1 large + 2 stacked */
.reaction-media-grid[data-count="3"] {
  grid-template-columns: 2fr 1fr;
  grid-template-rows: 1fr 1fr;
}
.reaction-media-grid[data-count="3"] .reaction-media-item:first-child {
  grid-row: 1 / 3;
}

/* 4+ items: 2x2 grid */
.reaction-media-grid[data-count="4"],
.reaction-media-grid:not([data-count="1"]):not([data-count="2"]):not([data-count="3"]) {
  grid-template-columns: 1fr 1fr;
}

.reaction-media-item {
  width: 100%;
  max-height: 300px;
  object-fit: cover;
}
```

---

## Security Considerations

### External Media URLs

Since we're rendering remote URLs directly (not storing locally), consider:

1. **Content Security Policy (CSP)**: Current CSP may need `img-src *` or specific domains. Since this is user-generated content from federated sources, wildcards are likely needed.

2. **Referrer Policy**: Use `referrerpolicy="no-referrer"` on all external media to prevent leaking the user's current page URL to remote servers.

3. **Link Safety**: Use `rel="nofollow noopener noreferrer"` on clickable media links.

4. **Loading Behavior**: Use `loading="lazy"` for images and `preload="metadata"` for video/audio to minimize unnecessary fetches.

5. **URL Validation**: The template filter `safe_url` already exists in reactions.html (used for mf2 URLs). Reuse it for attachment URLs to filter out `javascript:` and other malicious protocols.

### Existing Pattern

The webmention mf2 media rendering (`reactions.html:187-222`) already follows these patterns:
```jinja
{% set purl = url | safe_url %}
{% if purl %}
  <img ... src="{{ purl }}" ... loading="lazy" referrerpolicy="no-referrer" />
{% endif %}
```

---

## Implementation Options

### Option A: Template-Only (Recommended)

Extract attachments directly in the template using Jinja filters:
- Add a custom Jinja filter `extract_attachments(interaction)` that normalizes attachments
- Keep all logic in templates — minimal Python changes
- Reuses existing `safe_url` filter

**Pros**: Minimal code changes, easy to maintain
**Cons**: Template logic can get complex

### Option B: Model Enhancement

Add an `attachments` property to the reaction rendering:
- Normalize attachments in Python before passing to template
- Add `attachments` field to the reaction dict/node

**Pros**: Cleaner templates, easier testing
**Cons**: More code changes across multiple files

### Option C: Hybrid

- Use a Jinja macro that accepts the raw metadata dict
- The macro handles both AP and WM formats internally
- Keeps normalization in template layer but encapsulated

**Pros**: Self-contained, reusable
**Cons**: Complex macro

---

## Recommended Approach

**Option C (Hybrid)** with the following steps:

1. Create a shared `render_media_attachments` macro in `reactions.html`
2. The macro accepts raw metadata and handles normalization internally
3. Call from both `render_ap_interaction` and `render_webmention` macros
4. Add CSS grid styles to `reactions.css`
5. Ensure security attributes are applied

This approach:
- Shares rendering logic across all reaction types
- Keeps normalization logic close to rendering
- Requires minimal changes to existing Python code
- Follows existing patterns in the codebase

---

## Files to Modify

1. **`madblog/templates/reactions.html`**
   - Add `render_media_attachments` macro
   - Call it from `render_ap_interaction` (after content)
   - Refactor `render_webmention` mf2 media to use shared macro (optional)

2. **`madblog/static/css/reactions.css`**
   - Add `.reaction-media-grid` styles
   - Add `.reaction-media-item` styles
   - Responsive grid layouts

3. **`madblog/templates/filters.py`** (if exists) or template setup
   - Verify `safe_url` filter is available (already used in reactions.html)

---

## Questions / Follow-ups

1. Should we limit the number of displayed attachments (e.g., max 4 with "+N more" indicator)?
2. Should clicking an image open a lightbox, or just link to the source?
3. Should we add lazy-loading skeleton/placeholder styles?
4. Do we want to add media attachment support to author replies via frontmatter?
