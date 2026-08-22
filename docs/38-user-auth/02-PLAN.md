# Plan: User Authentication & Multi-User Support

This plan builds on `01-RESEARCH.md` and incorporates the design decisions
agreed in the follow-up review. It supersedes the single-user-only assumption
of the research doc.

---

## 1. Scope & Guiding Principles

- **Authentication is opt-in.** With no password configured and no user
  directories present, Madblog behaves exactly as today.
- **Multi-user is opt-in on top of auth.** Single-user mode remains the
  default and the simplest configuration.
- **Full back-compatibility.** Existing content (URLs, `markdown/`,
  `replies/` layouts, feeds, ActivityPub actor) must keep working with no
  migration required.
- **Filesystem is the source of truth.** No database is introduced. All
  auth artifacts live under `<state_dir>/auth/` with strict permissions.
- **Small, well-supported dependencies only:** `bcrypt`, `itsdangerous`
  (already a Flask transitive), `flask-wtf`, and optionally
  `flask-limiter` for rate limiting (see §7).

---

## 2. Modes of Operation

Three effective modes emerge from two independent axes (auth on/off,
multi-user on/off):

| Mode | Auth | Multi-user | Behaviour |
|------|------|-----------|-----------|
| **A. Anonymous** (today) | off | off | No `/login`, no session, no editor. Public read-only. |
| **B. Single-user** | on | off | One owner. `/login` unlocks editor. All content owned by the default user. URLs unchanged. |
| **C. Multi-user** | on | on | Multiple accounts. Default user's content keeps legacy URLs. Additional users get `/@<user>/...` namespaced URLs and directories. |

Activation rules:

- **Auth activates** when any of the following is true:
  - `auth_password` set in `config.yaml` / `MADBLOG_AUTH_PASSWORD`, OR
  - `<state_dir>/auth/users/<name>/password.hash` exists (created via
    `madblog set-password`).
- **Multi-user activates** when either:
  - `enable_multi_user: true` in config / `MADBLOG_ENABLE_MULTI_USER=1`, OR
  - More than one user directory exists under `<state_dir>/auth/users/`.

Multi-user without auth is not a valid combination (rejected at startup
with a clear error).

---

## 3. Default User & Back-Compatibility

The **default user** is the identity that owns all pre-existing (i.e.,
non-namespaced) content. This keeps every current URL and file path
working untouched.

### 3.1 Resolution order

1. `default_user` from config / `MADBLOG_DEFAULT_USER` env, if set.
2. Otherwise, `activitypub_username` (already the natural single-owner
   identity of the blog).
3. Otherwise, the literal string `admin`.

### 3.2 What "default user" owns

- All files directly under `markdown/` (i.e. **not** inside an `@user/`
  subtree).
- All files directly under `replies/` (same rule).
- The existing ActivityPub actor (`/@<activitypub_username>` remains the
  actor URL — see §5.3).
- Existing feed, tags, mentions state.

### 3.3 URL routing back-compat

- `/article/<slug>` and `/article/<path>/<slug>` continue to resolve to
  files under `markdown/` and are attributed to the default user.
- `/reply/<slug>` and `/reply/<article_slug>/<reply_slug>` continue to
  resolve to files under `replies/`.
- New per-user routes (see §5) are additive; they never shadow the
  legacy ones.

### 3.4 Rendering attribution

- Templates that today display the single `config.author` block will
  keep doing so when the page is owned by the default user.
- For non-default users, the author block is derived from the user's
  profile (see §4.2).

---

## 4. On-disk Layout

### 4.1 Auth artifacts

```
<state_dir>/auth/                      # 0700
  secret_key                           # 0600, 64-hex Flask signing key
  users/                               # 0700
    <username>/                        # 0700 — one dir per user
      password.hash                    # 0600, bcrypt hash
      profile.yaml                     # 0600, display name, bio, avatar path, rel_me, ...
      sessions/                        # (reserved, may stay empty when using signed cookies)
```

Rules:

- `<username>` MUST match `^[a-z0-9][a-z0-9_-]{0,30}$` (validated by the
  CLI and at load time). This is the same character class Mastodon
  accepts and is safe to embed in URLs and filesystem paths without
  escaping.
- All files under `auth/` are opened with `os.open(..., 0o600)` and any
  parent directories are created with mode `0o700`. On startup Madblog
  refuses to run if any file under `auth/` is group- or world-readable
  (mirroring the ActivityPub private-key check).

### 4.2 User profile (`profile.yaml`)

Minimal, all fields optional:

```yaml
display_name: Jane Doe
bio: "Occasional writer."
avatar: /img/jane.png
url: https://jane.example.com
rel_me:
  - https://mastodon.social/@jane
```

If absent, sensible defaults are derived from the username and global
config.

### 4.3 Content directories

- Default user's content stays where it is: `markdown/…`, `replies/…`.
- Additional users get a **namespaced subtree** whose top-level directory
  starts with `@`:

```
<content_dir>/
  markdown/
    my-first-post.md                   # owned by default user
    2025/
      new-year.md                      # owned by default user
    @jane/                             # user 'jane' (multi-user only)
      hello.md                         # -> /@jane/hello
      2025/
        recap.md                       # -> /@jane/2025/recap
  replies/
    some-slug/
      re-1.md                          # default user reply
    @jane/
      some-slug/
        re-1.md                        # jane's reply
```

Rules:

- Any top-level entry under `markdown/` or `replies/` whose name starts
  with `@` is treated as a user namespace.
- The suffix after `@` must match a known user (i.e. have a matching
  `auth/users/<name>/` directory). Otherwise the directory is **ignored
  and logged as a warning** at startup — never served.
- Nested `@user/` directories (e.g. `markdown/@jane/@bob/...`) are
  explicitly forbidden and skipped.

### 4.4 Security considerations for `@user/` directories

The main risks are path traversal, cross-user writes, and privilege
confusion. Mitigations:

- **Canonical realpath check.** Every resolved article/reply path must
  satisfy `realpath(target).startswith(realpath(user_root) + os.sep)`
  before it is opened (extends the existing check in
  `MarkdownMixin._resolve_and_parse_metadata`).
- **User binding is derived from the path prefix, not the request.** A
  request for `/@jane/foo` maps to `markdown/@jane/foo.md`. The owning
  user is `jane` iff the resolved file is inside `markdown/@jane/`.
  Authorisation for writes (editor, replies) is checked against this
  filesystem-derived owner, not against any request parameter.
- **Filename validation.** Slugs must match `^[A-Za-z0-9._-]+$` for the
  leaf; path segments must not contain `..`, symlinks are rejected
  (`os.path.islink`) unless they resolve inside the same user root.
- **Case handling.** Usernames are lowercased before comparison to
  prevent `@Jane` vs `@jane` confusion on case-insensitive filesystems.
- **Reserved names.** `@guestbook`, `@about`, `@tags`, `@unlisted`, and
  any name colliding with existing top-level routes are refused by
  `set-password`.

---

## 5. URL Scheme

We adopt the Mastodon convention (`@user`) as the user-namespace prefix.

### 5.1 Routes (additive)

| URL | Handler | Notes |
|-----|---------|-------|
| `/article/<slug>` | default-user article (unchanged) | back-compat |
| `/reply/<slug>` | default-user reply (unchanged) | back-compat |
| `/@<user>` | user profile page | HTML profile derived from `profile.yaml` |
| `/@<user>/<path:slug>` | user's article | resolves to `markdown/@<user>/<slug>.md` |
| `/@<user>/<path:slug>.md` | raw Markdown | same, `as_markdown=True` |
| `/@<user>/reply/<slug>` | user's top-level reply | `replies/@<user>/<slug>.md` |
| `/@<user>/reply/<article>/<slug>` | user's reply to `<article>` | `replies/@<user>/<article>/<slug>.md` |

### 5.2 Interaction with the existing `/@<username>` route

Today `routes.py:161` uses `/@<username>` to serve the ActivityPub actor
profile for `config.activitypub_username`. That route stays. The new
per-user routes are registered after it and only handle usernames that
resolve to an entry in `auth/users/`. Precedence rules:

1. If `<user> == activitypub_username` **and** that user is the default
   user → keep current behaviour (blog home + rel="me"), unchanged.
2. Else if `<user>` is a known non-default user → render the user
   profile page.
3. Else → 404.

### 5.3 ActivityPub

- **v1: only the default user has an actor.** The AP actor URL, keys,
  inbox, outbox, and federation flow are unchanged.
- Non-default users get an HTML profile but no `application/activity+json`
  representation yet.
- Full multi-actor ActivityPub is a follow-up (see §11); it requires a
  key-per-user and per-user inbox storage.

### 5.4 Canonicalisation

- Anywhere Madblog builds a canonical URL for a piece of content it must
  ask the owner resolver "who owns this file?" and, for non-default
  users, produce the `/@<user>/…` form. The default user always yields
  the legacy `/article/…` / `/reply/…` form. This keeps feed URLs, AP
  object IDs and Webmention `source`/`target` values stable for the
  default user.

---

## 6. Auth Subsystem

Follows the mixin pattern already used by the other subsystems.

```
madblog/auth/
  __init__.py           # AuthMixin, current_user helper
  _mixin.py             # init, session config, login/logout, CSRF wiring
  _secrets.py           # secret_key + password hash load/store
  _users.py             # UserStore: enumerate users, load profile, verify password
  _decorators.py        # @login_required, @owner_required
  _forms.py             # LoginForm (flask-wtf)
  routes.py             # /login, /logout (registered when auth is enabled)
```

### 6.1 `UserStore`

- Discovers users by scanning `<state_dir>/auth/users/`.
- Caches user list; invalidated by an inotify hook or on-demand rescan
  (initial version: rescan on each write, cache reads for the process
  lifetime and rely on restart to pick up new users — acceptable for
  a self-hosted blog).
- Exposes:
  - `list_usernames() -> list[str]`
  - `get(username) -> User | None`
  - `verify(username, password) -> bool` (bcrypt, constant time)
  - `set_password(username, plaintext) -> None`
  - `default_username() -> str`
  - `owner_of(path: Path) -> str` — the "who owns this file?" resolver
    used across the app.

### 6.2 Session cookies

- `app.secret_key` loaded from `<state_dir>/auth/secret_key` (auto-gen
  on first run).
- Flask's default session backend uses `itsdangerous` HMAC-signing under
  the hood — no extra dependency needed for signing.
- Cookie flags:

```python
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.link.startswith("https://"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
```

- A warning is logged if auth is enabled but `config.link` is not
  HTTPS: sessions are still signed but not marked `Secure`, and the
  operator is told to fix their deployment.

### 6.3 CSRF

- `flask-wtf`'s `CSRFProtect` is initialised once when auth is enabled.
- All state-changing POST endpoints (login, logout, future editor) use
  Flask-WTF forms or the `csrf_token()` template helper.
- CSRF is scoped to authenticated forms only; public endpoints
  (webmentions inbox, ActivityPub inbox) already have their own
  signature-based authentication and are explicitly exempted via
  `@csrf.exempt`.

### 6.4 Rate limiting

Applied to `/login` to slow brute force:

- **Preferred:** `flask-limiter` with the in-memory storage backend
  (`memory://`). Small dependency, well maintained, no external service
  required. Default policy: `5 per minute; 20 per hour` per remote
  address, keyed via `X-Forwarded-For` when a trusted proxy header is
  configured.
- **Fallback if we want zero extra deps:** a small in-process
  `collections.deque`-based limiter in `_mixin.py`. Configurable via
  `auth_login_rate_limit` (default `5/minute`).

Both options remain single-process — sufficient for the typical single
gunicorn/uwsgi worker Madblog deployment. Cross-worker rate limiting is
a follow-up.

### 6.5 Decorators

- `@login_required` — requires any authenticated user.
- `@owner_required(get_owner)` — requires the session user to equal
  the resource owner returned by `get_owner(**view_kwargs)`. Used by
  the future editor to prevent user A from editing user B's posts.

---

## 7. Configuration Additions

New fields in `Config`:

| Field | Env var | Default | Notes |
|-------|---------|---------|-------|
| `enable_multi_user` | `MADBLOG_ENABLE_MULTI_USER` | `False` | Turns on `/@<user>/...` routing and namespaced dirs. |
| `default_user` | `MADBLOG_DEFAULT_USER` | derived (see §3.1) | Owner of legacy content. |
| `auth_password` | `MADBLOG_AUTH_PASSWORD` | — | Bootstrap password for the default user; hashed and removed from memory on first run. |
| `auth_login_rate_limit` | `MADBLOG_AUTH_LOGIN_RATE_LIMIT` | `5/minute` | Passed to `flask-limiter`. |
| `auth_session_lifetime_days` | `MADBLOG_AUTH_SESSION_LIFETIME_DAYS` | `30` | Cookie lifetime. |

No `enable_auth` flag: auth is implicitly enabled by the presence of a
password (config, env, or hash file). This keeps the surface small.

---

## 8. CLI Additions

```
madblog set-password [--config CONFIG] [dir] [user]
```

- `user` is optional. If omitted:
  - In single-user mode: applies to the default user.
  - In multi-user mode with no existing users: creates the default
    user.
  - In multi-user mode with existing users: errors out and asks for an
    explicit username.
- Prompts for password twice (using `getpass.getpass`) unless
  `MADBLOG_AUTH_PASSWORD` is set (useful for automation / tests).
- Validates the username per §4.1.
- Creates `<state_dir>/auth/users/<user>/` at mode `0700` and writes
  `password.hash` at mode `0600` using `bcrypt.hashpw` with the default
  cost factor.
- Optionally creates a stub `profile.yaml` (only if none exists).
- Exits 0 on success, 1 on any validation/permission error, with a
  clear message.

Also added, but as a follow-up if scope allows:

- `madblog list-users` — enumerates users and their profile summary.
- `madblog remove-user <user>` — deletes the user directory after
  confirmation (does **not** touch content dirs; a warning is emitted
  if `markdown/@<user>/` or `replies/@<user>/` still exist).

---

## 9. Templates & UI

- `templates/login.html` — minimal form with CSRF token; styled
  consistently with existing pages.
- `templates/common-head.html` — a conditional Login/Logout affordance
  when `auth_enabled` is truthy. Displays the current user's display
  name when logged in.
- `templates/user-profile.html` — profile page for `/@<user>` in
  multi-user mode: display name, bio, avatar, `rel="me"` links, and a
  listing of the user's posts (reuses the existing pages listing).
- Author metadata rendered on a post honours the resolved owner (§3.4).

Editor UI is deliberately out of scope for this plan (research §6.2
mentions it as future work); this plan lays the groundwork so the
editor can be added on top without further architectural changes.

---

## 10. Testing Strategy

New tests live under `tests/` following existing structure.

- `tests/auth/test_user_store.py`
  - user discovery, username validation, permission checks (0600/0700).
  - `owner_of()` returns default user for legacy paths, `@<user>` for
    namespaced paths, refuses paths outside content roots.
- `tests/auth/test_password.py`
  - bcrypt round-trip, `set-password` CLI happy path and error paths.
- `tests/auth/test_login_flow.py`
  - `/login` renders, valid creds set session, invalid creds do not.
  - CSRF token required.
  - Rate limiter kicks in after N failures.
  - `Secure` flag set when `config.link` is https.
- `tests/auth/test_multi_user_routes.py`
  - `/@<user>/foo` resolves to the correct file.
  - `/@<user>` resolves to the profile page.
  - Legacy `/article/foo` and `/reply/foo` still work.
  - The existing `/@<activitypub_username>` route keeps serving the AP
    actor when that name is the default user.
  - Path traversal attempts (`/@jane/../bob/secret`) return 404.
- `tests/auth/test_backcompat.py`
  - With no `auth_password` and no `auth/` dir the app behaves exactly
    as today (regression suite: `pytest -k "not auth"` should pass
    unchanged before the auth code path activates).

`pre-commit run --all-files` and `pytest` must both be green before
each phase is considered done.

---

## 11. Follow-ups (out of scope for this plan)

Tracked in `99-FOLLOW-UP.md`:

- **IndieAuth** as an alternative login mechanism (natural fit for
  IndieWeb; would coexist with password auth).
- **OpenID Connect / OAuth login** for teams using an existing IdP.
- **WebAuthn / passkeys.**
- **Per-user ActivityPub actors** (key material, inbox/outbox storage
  under `auth/users/<name>/activitypub/`, WebFinger for
  `acct:user@domain`).
- **Web-based Markdown editor** built on top of `@login_required` /
  `@owner_required`.
- **Cross-worker rate limiting** via a shared backend if/when Madblog
  is commonly deployed with multiple workers.
- **User self-service password change** UI.

---

## 12. Phased Implementation

Each phase ends with green `pytest` and `pre-commit`, plus doc/CHANGELOG
updates as required by AGENTS.md.

1. **Phase 1 — Auth foundation (single-user).**
   Config fields, `<state_dir>/auth/` layout, `secret_key`, password
   hash, `AuthMixin`, `/login`, `/logout`, CSRF, rate limit,
   `madblog set-password`, tests, README + ARCHITECTURE updates.

2. **Phase 2 — Owner resolver & default user.**
   Introduce `UserStore.owner_of()` and thread the concept through
   metadata, feeds, and canonical-URL builders. No behaviour change
   yet (only the default user exists), but all code paths now go
   through the resolver. Regression tests must still pass.

3. **Phase 3 — Multi-user routing & directories.**
   `enable_multi_user` flag, `@user/` directory discovery, new
   `/@<user>/…` routes, profile page, template attribution, security
   checks (§4.4). Additional CLI (`list-users`, `remove-user`) if time
   permits.

4. **Phase 4 — Documentation & wrap-up.**
   Update `README.md` (multi-user section, CLI reference), refresh
   `docs/ARCHITECTURE.md`, write `CHANGELOG.md` _Unreleased_ entry,
   fill `99-FOLLOW-UP.md`, produce implementation summaries under
   `docs/38-user-auth/implementation/`.
