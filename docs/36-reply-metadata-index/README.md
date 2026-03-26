# 36 — Reply Metadata Index

A general-purpose, JSON-persisted metadata index for reply files under
`replies/`. Eliminates per-request full-directory scans by maintaining a
slug → metadata mapping that is incrementally updated via `ContentMonitor`.

- [01-RESEARCH.md](01-RESEARCH.md) — analysis of existing indices and scan patterns
- [02-PLAN.md](02-PLAN.md) — implementation plan (phased)
- [99-FOLLOW-UP.md](99-FOLLOW-UP.md) — agreed follow-ups

**HEAD at start:** `e7eb0580172f31cf1bcbdc93a07f972a3506d5fd`
