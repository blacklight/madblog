# Follow-ups

Items identified during implementation that are out of scope for the initial
release but should be considered for future work.

## `external_feeds_as_folders` config option

Allow external RSS/Atom feeds (from `external_feeds` config) to be rendered as
virtual folder entries on the home page rather than mixed with local articles.

**Rationale**: Some users may prefer to visually separate syndicated content
from local content while still keeping it accessible from the home page.

## Folder-level ActivityPub

Optional per-folder ActivityPub actors, allowing followers to subscribe to
specific sections of the blog.

**Complexity**: High — requires significant changes to the ActivityPub
integration and may introduce federation complexity.

**Status**: Likely out of scope unless there's strong demand.
