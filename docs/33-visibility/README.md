# Visibility Model for Author Posts

This feature adds a visibility model for author posts (articles and replies), supporting:

- **Global default visibility** via `default_visibility` config parameter
- **Per-post visibility** via `visibility` Markdown metadata

## Visibility Levels

| Level | Blog Index | Unlisted Page | reactions.html | ActivityPub | Direct URL |
|-------|------------|---------------|----------------|-------------|------------|
| `public` | ✓ | ✗ | ✓ | `to: [Public]`, `cc: [followers]` | ✓ |
| `unlisted` | ✗ | ✓ | ✓ | `to: [followers]`, `cc: [Public]` | ✓ |
| `followers` | ✗ | ✗ | ✗ | `to: [followers]`, `cc: []` | ✓ |
| `direct` | ✗ | ✗ | ✗ | `to: [mentions]`, `cc: []` | ✓ |
| `draft` | ✗ | ✗ | ✗ | Not federated | ✓ |

## Documentation

- [01-RESEARCH.md](./01-RESEARCH.md) — Research findings and current state analysis
- [02-PLAN.md](./02-PLAN.md) — Implementation plan

## Reference Commit

HEAD at feature start: `ab4e7d67329ca0a856c13b12c30344e410ca6961`
