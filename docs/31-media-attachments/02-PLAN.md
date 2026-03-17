# Media Attachments in Replies — Implementation Plan

## Decisions from Research Review

- **Approach**: Option C (hybrid template + normalization in macro)
- **Attachment limit**: Max 4 visible, with expand/collapse for more (reuse existing collapsible pattern)
- **Click behavior**: Link to source URL (no lightbox)
- **Loading**: Lazy-loading with placeholder styles
- **Author replies**: Skip — media already inline in Markdown content

---

## Phase 1: CSS Styles

Add media grid and placeholder styles to `madblog/static/css/reactions.css`.

### Tasks

1. **Media grid container** (`.reaction-media-grid`)
   - CSS Grid with responsive layouts based on attachment count
   - Gap between items
   - Rounded corners with overflow hidden

2. **Media item styles** (`.reaction-media-item`)
   - Max height constraint
   - Object-fit cover for images
   - Lazy-loading placeholder (background color/gradient)

3. **Collapsible overflow** (`.reaction-media-overflow`)
   - Reuse existing `.reaction-collapsible` pattern
   - Show first 4, hide rest behind toggle

4. **Responsive breakpoints**
   - Single column on narrow screens

---

## Phase 2: Template Macro

Add shared `render_media_attachments` macro to `madblog/templates/reactions.html`.

### Tasks

1. **Normalization logic in macro**
   - Accept raw `metadata` dict
   - Extract attachments from AP format (`metadata.raw_object.attachment`)
   - Extract attachments from WM format (`metadata.mf2.photo/video/audio`)
   - Normalize to common structure

2. **Type detection**
   - Primary: check `mediaType` prefix (`image/`, `video/`, `audio/`)
   - Fallback: check `type` field (lowercase: `image`, `video`, `audio`, `document`)

3. **Rendering**
   - Images: `<a href="url"><img src="url" alt="name" loading="lazy" referrerpolicy="no-referrer" /></a>`
   - Videos: `<video controls preload="metadata"><source src="url" type="mediaType" /></video>`
   - Audio: `<audio controls preload="metadata"><source src="url" type="mediaType" /></audio>`

4. **Overflow handling**
   - If > 4 attachments, wrap extras in collapsible container
   - Reuse checkbox toggle pattern from existing reaction content

5. **Security**
   - Use `safe_url` filter on all URLs
   - Add `rel="nofollow noopener noreferrer"` on links
   - Add `referrerpolicy="no-referrer"` on media elements

---

## Phase 3: Integration

Integrate macro into existing reaction rendering.

### Tasks

1. **`render_ap_interaction` macro**
   - Call `render_media_attachments(interaction.metadata)` after content div
   - Pass interaction metadata directly

2. **`render_webmention` macro**
   - Replace existing mf2 photo/video/audio rendering with shared macro. **Yes please, replace them with the new templates for consistency**
   - Or keep existing and add macro call (evaluate during implementation)

3. **Testing**
   - Verify with existing stored interactions (AP)
   - Verify with webmentions containing media
   - Test overflow behavior with 5+ attachments

---

## Phase 4: Tests & Documentation

### Tasks

1. **Unit tests**
   - Test attachment normalization logic
   - Test with various AP attachment formats (Image, Document, Video, Audio)
   - Test with mf2 photo/video/audio arrays

2. **Visual verification**
   - Test grid layouts (1, 2, 3, 4, 5+ attachments)
   - Test responsive behavior
   - Test lazy-loading placeholders

3. **Documentation**
   - Update CHANGELOG.md

---

## Files Modified

| File | Changes |
|------|---------|
| `madblog/static/css/reactions.css` | Add media grid styles |
| `madblog/templates/reactions.html` | Add `render_media_attachments` macro, integrate into AP/WM macros |
| `tests/test_replies.py` | Add tests for media attachment rendering |
| `CHANGELOG.md` | Document new feature |

---

## Out of Scope

- Lightbox/modal for images
- Blurhash placeholder rendering (could be follow-up)
- Author reply frontmatter attachments
- Local media caching/proxying
