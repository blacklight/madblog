# Feature [#27](https://git.platypush.tech/blacklight/madblog/issues/27): Improved Folder Support

This feature improves navigation and usability when `pages_dir` contains nested
folders.

## Problem

Currently, all Markdown files under `pages_dir` are shown on the home page with
only mild grouping by folder. This becomes confusing with many folders and makes
Full view mode nearly unusable.

## Solution

- Render only current-level articles on each index page
- Add folder navigation with `/~<folder>/` URLs
- Breadcrumb navigation and parent links
- Alphabetical folder sorting, timestamp article sorting

## Documents

- [00-PROBLEM.md](./00-PROBLEM.md) — Original problem statement
- [01-RESEARCH.md](./01-RESEARCH.md) — Research and analysis
- [02-PLAN.md](./02-PLAN.md) — Implementation plan
- [implementation/01-core-implementation.md](./implementation/01-core-implementation.md) — Implementation summary
- [99-FOLLOW-UP.md](./99-FOLLOW-UP.md) — Follow-up items

## HEAD at feature start

```
021dcf4126d8dda948198f91dc0484c0162aa525
```
