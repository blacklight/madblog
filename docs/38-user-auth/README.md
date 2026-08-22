# 38 – User Authentication & Web Editor

Frontend user authentication for Madblog, enabling an authenticated author
to create and edit posts through a Web editor UI. The feature introduces
password-based auth (with rate-limited `/login`/`/logout` flows that use
CSRF-protected WTForms), session hardening, file-based user storage under
`<state_dir>/auth/`, and the `madblog set-password` CLI helper for credential
management.

## Summary

- Password protections guard the admin UI while leaving public feeds and
  ActivityPub endpoints accessible by default.
- Sessions respect `SESSION_COOKIE_SECURE`, `HTTPOnly`, and `SameSite=Lax`, and
  the auth subsystem wires `flask-limiter`, `flask-wtf`, and `itsdangerous`
  helpers into `BlogApp` via `AuthMixin`.
- Configurable knobs (`auth_password`, `auth_login_rate_limit`,
  `auth_session_lifetime_days`, `MADBLOG_ENABLE_MULTI_USER`, `MADBLOG_DEFAULT_USER`)
  and environment overrides ensure the feature is operable in scriptable
  deployments.
- All sensitive data is hashed with `bcrypt` and stored with strict
  permissions (`0700` dirs/`0600` files) managed through `madblog/auth/_secrets.py`.

## Documents

- [01-RESEARCH.md](01-RESEARCH.md) — Findings and proposed approaches for
  auth, secrets, rate limiting, and session handling.
- [02-PLAN.md](02-PLAN.md) — Implementation phases, including CLI wiring,
  template updates, and test stability work.
- [03-IMPLEMENTATION.md](03-IMPLEMENTATION.md) — Detailed implementation notes
  and debugging steps for the auth mixin, routes, and helper utilities.
- [99-FOLLOW-UP.md](99-FOLLOW-UP.md) — Outstanding follow-up tasks identified
  during the project (e.g., multi-user UI polish, reintroducing stable login
  flow tests).
