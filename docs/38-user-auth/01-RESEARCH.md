# Research: User Authentication & Web Editor

## 1. Goal

Add frontend user authentication so the blog owner can log in and access a
Web-based Markdown editor to create new posts. Future authenticated features
(replies, likes) will build on the same auth layer.

**Constraint:** Madblog is file-based — no database. The solution must store
secrets and session state on the filesystem (or in-memory) and remain
operationally simple.

---

## 2. Current state

### 2.1 No authentication exists

- Flask's `secret_key` is **never set** anywhere in the codebase.
- There are no session, login, or CSRF-related imports.
- The README explicitly notes that "Madblog does not implement
  authentication" (visibility section).

### 2.2 Existing secrets handling

The only secret currently managed is the **ActivityPub RSA private key**:

| Aspect | How it works |
|--------|-------------|
| **Storage** | PEM file at `<state_dir>/activitypub/private_key.pem` (or user-configured path) |
| **Generation** | Auto-generated on first run via `pubby.crypto.generate_rsa_keypair()` |
| **Permissions** | `chmod 600`; startup check rejects group/other-readable files |
| **Configuration** | Optional `activitypub_private_key_path` in config.yaml / `MADBLOG_ACTIVITYPUB_PRIVATE_KEY_PATH` env var |

This pattern — auto-generate on first run, store in `state_dir`, override via
config/env — is the model we should follow for auth secrets.

### 2.3 State directory layout

```
<state_dir>/                        # config.resolved_state_dir
  activitypub/
    private_key.pem
    state/                          # pubby FileActivityPubStorage
    file_urls.json
  mentions/
    incoming/
    outgoing/
  cache/
    tags-index.json
  reply_metadata_index.json
```

A new `auth/` subtree under `state_dir` is the natural home for auth secrets.

---

## 3. Authentication model

### 3.1 Single-user, owner-only

Madblog is a single-author blogging platform. We need exactly one account: the
blog owner. Multi-user support is out of scope.

### 3.2 Password-based login

The simplest UX that fits the single-user model:

1. Owner sets a password (via config, env var, or a CLI one-time setup
   command).
2. A `/login` page presents a username/password form.
3. On success a server-side session is created.
4. Authenticated routes check the session.

### 3.3 Why not token-only / API-key?

A shared API key (e.g. in a header) would work for API clients but is awkward
for a browser-based editor: the key must be stored in `localStorage` or a
cookie manually, and there is no standard login UX. Password → session is more
natural for a Web frontend.

---

## 4. Secrets storage design

### 4.1 What needs to be stored

| Secret | Purpose | Lifetime |
|--------|---------|----------|
| **Password hash** | Verify login credentials | Persistent (until changed) |
| **Flask `secret_key`** | Sign session cookies (HMAC) | Persistent (regenerating invalidates all sessions) |

### 4.2 Password hash

- Store a **bcrypt** (or argon2) hash, never the plaintext password.
- File: `<state_dir>/auth/password.hash`
- Permissions: `0600` (same discipline as the AP key).
- The password itself is provided via:
  - **Config file:** `auth_password` (not recommended for production but
    simple for dev). On startup, if a plaintext password is found in config
    **and** no hash file exists yet, hash it and write the hash file, then
    warn that the plaintext should be removed.
  - **Environment variable:** `MADBLOG_AUTH_PASSWORD` — same behavior.
  - **CLI command:** `madblog set-password` — interactive prompt, writes the
    hash file directly. This is the recommended flow.

**bcrypt** is preferred over argon2 because it has no C-extension build
complications and is well-supported in pure-Python via the `bcrypt` package
(already widely available as a wheel). However, we should also consider
`passlib` which provides a higher-level wrapper and supports multiple hash
schemes transparently.

### 4.3 Flask secret key

- File: `<state_dir>/auth/secret_key`
- Auto-generated on first run (`os.urandom(32).hex()`, 64 hex chars).
- Loaded at startup and assigned to `app.secret_key`.
- Permissions: `0600`.
- If the operator wants to share sessions across restarts / multiple workers,
  the key persists on disk. If they delete it, a new one is generated and all
  sessions are invalidated (safe, just forces re-login).

### 4.4 Proposed `<state_dir>/auth/` layout

```
<state_dir>/auth/
  secret_key          # 64-char hex Flask signing key (0600)
  password.hash       # bcrypt hash of the owner password (0600)
```

### 4.5 Opt-in activation

Authentication should be **opt-in**, not enabled by default. It activates
when any of these conditions is met:

- `auth_password` is set in config.yaml / `MADBLOG_AUTH_PASSWORD` env var, OR
- `<state_dir>/auth/password.hash` exists (set via `madblog set-password`).

If none of the above, the auth subsystem is not initialized, no `/login` route
is registered, no session middleware is added, and behavior is identical to
today.

---

## 5. Session management

### 5.1 Flask signed cookies (default)

Flask's built-in session uses `itsdangerous` to sign a cookie. This is
**stateless** on the server — no files to manage — and fits Madblog's
philosophy:

- Pros: zero server-side state, works across multiple workers, no cleanup.
- Cons: session data is visible (but not tamperable) to the client; revoking
  a single session requires changing `secret_key` (invalidates all).

For a single-user system, these trade-offs are acceptable.

### 5.2 Session cookie settings

```python
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True   # if config.link starts with https
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
```

### 5.3 CSRF protection

The editor will submit POST requests. We need CSRF tokens. Options:

- **Flask-WTF** — the standard Flask CSRF solution. Adds a dependency but is
  lightweight and battle-tested.
- **Manual double-submit cookie** — no dependency, but more error-prone.

Recommendation: use **Flask-WTF** for CSRF. It's a small, well-maintained
package (`flask-wtf` + `wtforms`).

---

## 6. Architecture: `auth` module

Following the mixin pattern used by all other subsystems:

```
madblog/auth/
  __init__.py          # exports AuthMixin
  _mixin.py            # AuthMixin: init, password verification, session setup
  _secrets.py          # load/generate secret_key, load/write password hash
  _decorators.py       # @login_required decorator
```

### 6.1 `AuthMixin`

Mixed into `BlogApp` alongside the other mixins:

- `_init_auth()` — called from `BlogApp.__init__()`:
  - Checks if auth is enabled (password configured or hash file exists).
  - Loads or generates `secret_key`.
  - Loads the password hash.
  - Sets `app.secret_key` and session cookie config.
- `verify_password(plaintext) -> bool` — bcrypt check.

### 6.2 Routes

Registered in `routes.py` (or a dedicated `auth/routes.py`):

- `GET /login` — renders login form.
- `POST /login` — validates credentials, sets session, redirects.
- `POST /logout` — clears session, redirects.
- `GET /editor` — (future) renders the Markdown editor (protected).
- `POST /editor` — (future) saves a new/edited post (protected).

### 6.3 `@login_required` decorator

```python
from functools import wraps
from flask import session, redirect, url_for

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated
```

### 6.4 Template integration

- A "Login" / "Logout" link in the nav (in `common-head.html`), conditional
  on `auth_enabled` context variable.
- Login page: `templates/login.html`.

---

## 7. Configuration additions

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `auth_username` | `MADBLOG_AUTH_USERNAME` | `admin` | Username for login |
| `auth_password` | `MADBLOG_AUTH_PASSWORD` | — | Plaintext password (hashed on first run; prefer `madblog set-password`) |

No `enable_auth` flag — auth is implicitly enabled when a password is
configured.

---

## 8. CLI addition

```
madblog set-password [--config CONFIG] [dir]
```

- Prompts for password (with confirmation).
- Writes bcrypt hash to `<state_dir>/auth/password.hash`.
- Creates `<state_dir>/auth/` and sets `0700` on the directory.

---

## 9. Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `bcrypt` | Password hashing | Pure wheel, no build deps |
| `flask-wtf` | CSRF protection | Lightweight; pulls in `wtforms` |

Both are small, well-maintained, and available as wheels for all platforms.

---

## 10. Security considerations

1. **Password hash algorithm:** bcrypt with default work factor (12 rounds).
   Sufficient for a single-user system.
2. **Timing-safe comparison:** bcrypt's `checkpw` is inherently
   constant-time.
3. **Brute-force protection:** Consider optional rate-limiting on `/login`
   (e.g. 5 attempts per minute). Could be simple in-memory counter — no file
   state needed. Not a hard requirement for v1; a follow-up.
4. **HTTPS:** Session cookie should be `Secure` when `config.link` uses
   `https://`. A warning should be logged if auth is enabled without HTTPS.
5. **Password in config:** If `auth_password` is found in `config.yaml`,
   the hash file is written and a warning is logged advising removal of the
   plaintext. The plaintext value is never persisted by Madblog — only the
   hash.
6. **File permissions:** The `auth/` directory and its files get `0700`/`0600`
   respectively, mirroring the AP key discipline.

---

## 11. Open questions / alternatives considered

### 11.1 Token-based API auth (future)

For a headless editor or mobile client, a separate bearer-token mechanism
could be added later. It would coexist with session auth: the session is for
the browser, the token for API clients. Not needed for v1.

### 11.2 OAuth / IndieAuth

IndieAuth would be philosophically aligned (IndieWeb), but adds significant
complexity (external HTTP callbacks, authorization endpoints). Could be a
follow-up for multi-user scenarios or to allow login via your own domain.

### 11.3 WebAuthn / passkeys

Modern and phishing-resistant, but requires JavaScript, browser support, and
a credential store. The server-side state (credential public keys) would be a
JSON file. Viable as a future enhancement on top of password auth.

### 11.4 `argon2` vs `bcrypt`

Argon2 is the newer recommendation (PHC winner) but `argon2-cffi` requires a
C compiler at install time on some platforms. `bcrypt` ships pre-built wheels
everywhere. For a single-user blog the security margin difference is
negligible. We can support both via `passlib` if desired, but for simplicity
`bcrypt` alone is sufficient.

---

## 12. Summary of proposed approach

- **Single-user password auth** with bcrypt hash stored in
  `<state_dir>/auth/password.hash`.
- **Flask signed cookie sessions** with auto-generated `secret_key` in
  `<state_dir>/auth/secret_key`.
- **CSRF via Flask-WTF.**
- **Opt-in:** only active when a password is configured.
- **Mixin pattern** (`AuthMixin`) following existing architecture.
- **Two new dependencies:** `bcrypt`, `flask-wtf`.
- **CLI `set-password` command** for the recommended setup flow.
