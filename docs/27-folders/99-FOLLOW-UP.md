# Follow-ups

Items identified during implementation that are out of scope for the initial
release but should be considered for future work.

## ~~`external_feeds_as_folders` config option~~ ✅ Implemented

~~Allow external RSS/Atom feeds (from `external_feeds` config) to be rendered as
virtual folder entries on the home page rather than mixed with local articles.~~

**Status**: Implemented. Enable via `external_feeds_as_folders: true` in config
or `MADBLOG_EXTERNAL_FEEDS_AS_FOLDERS=1` env var.

## Folder-level ActivityPub

Optional per-folder ActivityPub actors, allowing followers to subscribe to
specific sections of the blog.

**Complexity**: High — requires significant changes to the ActivityPub
integration and may introduce federation complexity.

**Status**: Likely out of scope unless there's strong demand.
