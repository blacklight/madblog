# Implementation: User Authentication & Multi-User Support

Concrete blueprint for the phases outlined in `02-PLAN.md`. Each section
lists files touched, the shape of the new code, and the tests that gate
the phase.

Prerequisites for every phase:

- `pytest` green.
- `pre-commit run --all-files` green.
- No behaviour change for existing anonymous deployments (regression
  gate: `pytest tests/` without any auth-related env/config must keep
  passing).

---

## Phase 1 — Auth foundation (single-user)

**Goal:** an opt-in login/logout flow with password auth, secure cookies,
CSRF, and rate limiting. No multi-user, no new routing for content.

### 1.1 Dependencies

Edit `setup.py` (or `pyproject.toml` — whichever is authoritative) to
add:

- `bcrypt>=4.0`
- `flask-wtf>=1.2`
- `flask-limiter>=3.5`

`itsdangerous` is already a Flask transitive dependency — no explicit
pin needed. Document these additions in `README.md` under **Dependencies**.

### 1.2 Config (`madblog/config.py`)

Add fields to the `Config` dataclass:

```python
# Authentication
auth_password: str | None = None            # bootstrap only, never stored as-is
auth_login_rate_limit: str = "5/minute"
auth_session_lifetime_days: int = 30

# Multi-user (wired in Phase 3; declared here so config loading is stable)
enable_multi_user: bool = False
default_user: str | None = None
```

Extend `_init_config_from_file()` to read the same keys from
`config.yaml`, and extend the env-var override pass (grep for
`MADBLOG_ACTIVITYPUB_PRIVATE_KEY_PATH` to find the pattern) to accept:

- `MADBLOG_AUTH_PASSWORD`
- `MADBLOG_AUTH_LOGIN_RATE_LIMIT`
- `MADBLOG_AUTH_SESSION_LIFETIME_DAYS`
- `MADBLOG_ENABLE_MULTI_USER`
- `MADBLOG_DEFAULT_USER`

Add a helper property:

```python
@property
def auth_dir(self) -> Path:
    return self.resolved_state_dir / "auth"
```

### 1.3 New package `madblog/auth/`

```
madblog/auth/
  __init__.py            # exports AuthMixin, current_user, login_required
  _mixin.py              # AuthMixin
  _secrets.py            # secret_key + password.hash helpers
  _users.py              # UserStore (Phase 1: single default user)
  _decorators.py         # login_required, owner_required (owner is Phase 2)
  _forms.py              # LoginForm
  _routes.py             # register_auth_routes(app)
```

#### `_secrets.py`

```python
def ensure_secret_key(auth_dir: Path) -> bytes:
    """Return the persisted Flask secret key, creating it if missing."""

def load_password_hash(user_dir: Path) -> bytes | None:
    """Return the bcrypt hash bytes or None if the file is absent."""

def write_password_hash(user_dir: Path, plaintext: str) -> None:
    """Hash *plaintext* with bcrypt and write it atomically with mode 0600."""
```

Rules enforced in this module:

- Directories are created with `mode=0o700` via `os.makedirs(..., 0o700)`
  followed by `os.chmod` (Python creates directories with mode masked
  by `umask`, so an explicit `chmod` is required).
- Files are written via `os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)`
  wrapped by `os.fdopen`, then `os.replace()` for atomicity.
- On load, a `stat` check refuses to proceed if `st_mode & 0o077` is
  non-zero, mirroring the existing check in the ActivityPub key path.

#### `_users.py` (Phase 1 shape)

```python
@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    profile: dict          # parsed profile.yaml (may be empty)
    user_dir: Path

class UserStore:
    def __init__(self, auth_dir: Path, default_username: str): ...
    def default_username(self) -> str: ...
    def get(self, username: str) -> User | None: ...
    def verify(self, username: str, plaintext: str) -> bool: ...
    def set_password(self, username: str, plaintext: str) -> None: ...
    def is_auth_enabled(self) -> bool: ...
    # Phase 2:
    # def list_usernames(self) -> list[str]: ...
    # def owner_of(self, path: Path) -> str: ...
```

`is_auth_enabled()` returns `True` iff either `config.auth_password` is
set or `auth_dir/users/<default>/password.hash` exists.

Username regex: `^[a-z0-9][a-z0-9_-]{0,30}$`. Reserved names (rejected
in `set_password`): `admin` is allowed; `about`, `tags`, `unlisted`,
`guestbook`, `blog`, `article`, `reply`, `img`, `css`, `js`, `fonts`,
`webmentions`, `ap` — refused because they collide with existing
top-level routes.

#### `_mixin.py`

```python
class AuthMixin:
    user_store: UserStore

    def _init_auth(self) -> None:
        """Called from BlogApp.__init__ after config is resolved."""
```

`_init_auth` behaviour:

1. Compute `default_username` = `config.default_user or
   config.activitypub_username or "admin"`.
2. Instantiate `UserStore(config.auth_dir, default_username)`.
3. If `config.auth_password` is set and no hash file exists for the
   default user, hash it, write the file, log a warning telling the
   operator to remove the plaintext from config.
4. If `user_store.is_auth_enabled()` is `False`, return — nothing else
   is wired.
5. Otherwise:
   - `app.secret_key = ensure_secret_key(config.auth_dir)`.
   - Apply the session cookie config from §5.2 of the plan.
   - Instantiate `CSRFProtect(app)`; expose `csrf` on the app so
     signature-authenticated endpoints (AP inbox, webmention inbox)
     can be marked `@csrf.exempt` at their registration sites.
   - Instantiate `Limiter(get_remote_address, app=app, storage_uri="memory://")`.
   - Call `register_auth_routes(app)`.
   - Register a Jinja context processor exposing `auth_enabled=True`,
     `current_user`, and a `csrf_token()` proxy.
6. Log a warning if auth is enabled and `config.link` does not start
   with `https://`.

Integrated into `BlogApp` by:

- Adding `AuthMixin` to the `BlogApp` MRO in `madblog/app.py`
  (**first** so its context processors are registered before others).
- Calling `self._init_auth()` inside `BlogApp.__init__` right after
  the existing subsystem initialisers.

#### `_forms.py`

```python
class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=32)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=256)])
    submit = SubmitField("Log in")
```

#### `_routes.py`

Two endpoints (blueprint or direct registration — direct is fine, all
existing routes are in `madblog/routes.py`):

- `GET/POST /login` — renders `login.html`, uses the limiter
  `@limiter.limit(config.auth_login_rate_limit, methods=["POST"])`,
  verifies via `user_store.verify`, sets
  `session["user"] = username; session.permanent = True` on success and
  redirects to `?next=` (validated to be a relative URL) or `/`.
- `POST /logout` — clears the session, redirects to `/`. Requires CSRF.

Rendering the login form does **not** consume the rate limit budget;
only failed/successful `POST /login` does. To keep genuine users out of
the penalty box, the limit is applied per-IP and only decremented on
POST — this is `flask-limiter`'s default when you attach the decorator
to the POST handler.

#### `_decorators.py`

```python
def current_user() -> User | None:
    from flask import current_app, session
    name = session.get("user")
    return current_app.user_store.get(name) if name else None

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login_route", next=request.path))
        return view(*args, **kwargs)
    return wrapped
```

`owner_required` is scaffolded but not used until Phase 3 (the editor
lands later, and Phase 2's owner-resolver is not yet needed by any
write endpoint).

### 1.4 CLI: `madblog set-password`

Modify `madblog/cli.py`:

- Convert `get_args` to a subparser layout, keeping the current
  positional `dir` and `--config` on both subcommands so existing
  invocations (`madblog [dir]`) still work. Strategy: use
  `argparse`'s `subparsers = parser.add_subparsers(dest="command")`
  and register `serve` (default) and `set-password`.
- Backwards compatibility: if `sys.argv[1:]` does not start with a
  known subcommand keyword, prepend `serve` before parsing. This keeps
  every existing invocation working.
- `set-password` handler:

```python
def _cmd_set_password(opts):
    from getpass import getpass
    from .config import init_config
    from .auth._users import UserStore

    config = init_config(config_file=..., args=opts)
    ensure_state_directory()
    store = UserStore(config.auth_dir, _default_username(config))
    username = opts.user or store.default_username()

    pw = os.environ.get("MADBLOG_AUTH_PASSWORD") or getpass("Password: ")
    if not os.environ.get("MADBLOG_AUTH_PASSWORD"):
        if pw != getpass("Confirm: "):
            print("Passwords do not match", file=sys.stderr)
            sys.exit(1)

    store.set_password(username, pw)
    print(f"Password set for user '{username}'.")
```

Update the module entry (`madblog/__main__.py`) to route the command.

### 1.5 Templates

- New: `templates/login.html` — extends the existing base layout,
  renders `form.hidden_tag()` (CSRF), fields, and any flash messages.
- New: `templates/_auth_nav.html` — partial included by
  `common-head.html` and rendered only when `auth_enabled`.
- Edit: `templates/common-head.html` — include `_auth_nav.html`
  guarded by `{% if auth_enabled %}`.

### 1.6 Tests

New directory `tests/auth/` with `conftest.py` providing:

- `tmp_state_dir` fixture that points `config.state_dir` at a
  `tmp_path` and reloads config.
- `auth_enabled_app` fixture that also calls `set_password("admin",
  "hunter2")` and yields a Flask test client with sessions.

Cases (each mapped to a `test_*.py` module):

- `test_secrets.py` — permissions, atomic write, refuse loose modes.
- `test_user_store.py` — username regex, reserved names, bcrypt round-trip.
- `test_login_flow.py` — GET renders, POST valid → 302 + session,
  POST invalid → 401 + no session, CSRF token required, logout clears.
- `test_rate_limit.py` — 6th failed POST within a minute returns 429.
- `test_backcompat.py` — with no password anywhere, `/login` returns
  404, no session cookie is issued, and the app object has no
  `secret_key` attribute set beyond Flask's default None.
- `test_cli_set_password.py` — invokes `madblog set-password` via
  `subprocess`, checks the hash file is created with mode `0600`.

### 1.7 Documentation

- `README.md` — new **Authentication** section: config keys, CLI usage,
  security notes (HTTPS requirement, permissions, plaintext-in-config
  warning).
- `docs/ARCHITECTURE.md` — add the auth subsystem to the module map,
  note the state-dir layout under `auth/`.
- `CHANGELOG.md` — under _Unreleased_ → _Added_: "Opt-in password
  authentication for the blog owner."

### 1.8 Exit criteria

- `pytest` and `pre-commit` green.
- Manual smoke test: fresh blog with no config → unchanged. Same blog
  with `MADBLOG_AUTH_PASSWORD=hunter2` env var → `/login` works, wrong
  password rejected, correct password sets session cookie with `HttpOnly`
  and (if HTTPS) `Secure`.

---

## Phase 2 — Owner resolver & default-user threading

**Goal:** every place that today assumes "one blog, one owner" goes
through a single resolver. No user-visible change; multi-user code in
Phase 3 will slot in without touching call sites.

### 2.1 Extend `UserStore`

```python
def list_usernames(self) -> list[str]:
    """Enumerate directories under auth_dir/users. Cached per-process."""

def owner_of(self, path: Path) -> str:
    """
    Return the username that owns *path*.

    - path under markdown/@<user>/... or replies/@<user>/... where
      <user> is a known user → <user>.
    - anything else under markdown/ or replies/ → default_username().
    - path not under either root → raises ValueError.
    """
```

Phase 2 keeps `list_usernames()` returning `[default]` unless multi-user
is enabled (Phase 3 flips this).

### 2.2 Call sites to migrate

Grep for the following and route them through `owner_of` (returning
default in Phase 2, real owner in Phase 3):

- `MarkdownMixin._parse_metadata_from_markdown` — attach `metadata["owner"]`.
- `RepliesMixin._get_article_replies` — likewise.
- `activitypub/_publish.py` — actor selection point (currently hard-coded
  to the single actor). Phase 2 leaves the actor unchanged but reads
  it via a helper `_actor_for(owner)` that returns the default actor
  regardless. Phase 3 / follow-up wires per-user actors.
- Feeds (`madblog/feeds/`) — author element uses the owner's profile.
- Templates — replace direct `config.author*` reads with a
  `{{ owner_profile.* }}` context variable in a new context processor.

### 2.3 Owner-aware canonical URL builder

New helper `madblog/_urls.py`:

```python
def canonical_article_url(owner: str, slug: str) -> str: ...
def canonical_reply_url(owner: str, article_slug: str | None, slug: str) -> str: ...
```

Phase 2 rule: `owner == default_username()` → legacy `/article/<slug>`
form; else raise (no non-default users exist yet). Phase 3 relaxes the
second clause to produce `/@<user>/…`.

All existing URL construction sites (feeds, AP object IDs, webmention
canonicalisation, sitemap-like listings) are migrated to call these
helpers.

### 2.4 Tests

- `test_owner_resolver.py` — legacy paths → default; `@<user>/…` paths
  where the user is registered → `<user>`; paths escaping the roots
  raise; symlinks refused.
- Regression: full existing test suite must still pass. Any test that
  previously read `config.author` directly is updated to read from the
  owner profile helper.

---

## Phase 3 — Multi-user content & routing

**Goal:** users beyond the default can own articles and replies under
their own namespace, reachable via `/@<user>/…`.

### 3.1 Content discovery

Extend the pages/replies scanners:

- `MarkdownMixin` and the pages listing helpers must:
  - Ignore any top-level entry under `markdown/` starting with `@`
    when multi-user is disabled (current behaviour by omission — make
    it explicit and covered by tests).
  - When multi-user is enabled, enumerate `markdown/@<user>/` for each
    known user and merge results with the default-user pages,
    attributing each page to `<user>`.
  - Refuse `markdown/@<unknown>/` (log warning, skip).
  - Refuse nested `@user/@user2/` (log warning, skip).
- Analogous treatment for `replies/@<user>/`.

### 3.2 Routes (`madblog/routes.py`)

Add, **after** the existing `/@<username>` AP-profile route:

```python
@app.route("/@<user>/", methods=["GET"])
@app.route("/@<user>", methods=["GET"])
def user_profile_route(user): ...

@app.route("/@<user>/<path:slug>", methods=["GET"])
def user_article_route(user, slug): ...

@app.route("/@<user>/<path:slug>.md", methods=["GET"])
def user_raw_article_route(user, slug): ...

@app.route("/@<user>/reply/<slug>", methods=["GET"])
def user_toplevel_reply_route(user, slug): ...

@app.route("/@<user>/reply/<path:article_slug>/<reply_slug>", methods=["GET"])
def user_reply_route(user, article_slug, reply_slug): ...
```

Each handler:

1. Lowercases `user`, looks it up via `user_store.get(user)`.
2. If the user is `None` or is the default user **and** matches
   `activitypub_username`, delegate to the existing profile behaviour
   (back-compat for the AP actor route).
3. Otherwise builds the filesystem path under `markdown/@<user>/…` or
   `replies/@<user>/…`, runs the realpath containment check from
   `MarkdownMixin._resolve_and_parse_metadata`, and calls the existing
   `get_page` / `get_reply` machinery with the resolved path.

### 3.3 Profile page

`templates/user-profile.html`:

- Header: avatar, display name, `@user@<domain>`, bio.
- `rel="me"` links from profile.
- Post listing filtered to the user's `markdown/@<user>/` subtree,
  reusing the existing pages listing template.

### 3.4 CLI

- `madblog set-password <user>` already exists from Phase 1; validate
  in multi-user mode that `<user>` is provided when creating an
  additional account.
- Add `madblog list-users` for operator convenience.

### 3.5 Tests

- `test_multi_user_routing.py` — all new routes, plus:
  - `/@jane/foo` → 200 when `markdown/@jane/foo.md` exists.
  - `/@jane/../bob/secret` → 404 (path traversal).
  - Symlink pointing outside `markdown/@jane/` → 404.
  - Unknown user `/@ghost/foo` → 404.
  - Existing `/article/foo` still 200 for default-user content.
  - `/@<activitypub_username>` route still serves the AP-profile
    behaviour when that user is the default.
- `test_multi_user_content_discovery.py` — feeds and index list both
  default and per-user posts (with the flag on) and only default-user
  posts (with the flag off).
- `test_multi_user_authz.py` — session for user A cannot POST to a
  hypothetical `@owner_required` endpoint for user B's content
  (uses a test-only dummy endpoint).

### 3.6 Documentation

- `README.md` — new **Multi-user** subsection under Authentication:
  enabling the flag, directory layout, URL scheme, security caveats.
- `docs/ARCHITECTURE.md` — updated diagram/layout.
- `CHANGELOG.md` — under _Unreleased_ → _Added_: "Optional multi-user
  content with `@user`-namespaced URLs and directories."

---

## Phase 4 — Wrap-up

- Fold implementation summaries into
  `docs/38-user-auth/implementation/<nn>-<phase>.md`.
- Populate `99-FOLLOW-UP.md` with anything discovered during
  implementation.
- Final `README.md` / `ARCHITECTURE.md` sweep for consistency.
- Verify `CHANGELOG.md` _Unreleased_ section is coherent.
- Generate the commit message per AGENTS.md conventions.

---

## Cross-cutting checklist

- [ ] Every new file under `auth/` created via `os.open(..., 0o600)`
      and verified to be `0600` in tests.
- [ ] `CSRFProtect` explicitly exempts:
      `webmentions/inbox`, `ap/inbox`, and any other signature-verified
      federation endpoints (grep for `@app.route.*inbox`).
- [ ] Session cookie `Secure` flag derived from `config.link`.
- [ ] `flask-limiter` uses `memory://` and is documented as
      single-process.
- [ ] `set-password` refuses reserved usernames and mode-loose files.
- [ ] All new code paths are opt-in — the anonymous smoke test in §1.8
      must still pass at the end of every phase.
