# Follow-ups: User Authentication & Multi-User Support

Items intentionally deferred out of the initial auth + multi-user
delivery. Ordered by priority.

---

## 1. Web-based Markdown editor (highest priority)

The main user-facing feature that Phase 1–3 unlocks. Builds directly on
`@login_required` and `@owner_required`, and needs no federation work,
so it can ship independently of any of the follow-ups below.

Minimum viable scope:

- `GET /editor/new` — blank editor for a new post owned by the current
  user (writes under `markdown/@<user>/` in multi-user mode, or the
  legacy `markdown/` root for the default user).
- `GET /editor/<path:slug>` — loads an existing post for editing;
  `@owner_required` gates it to the file's owner.
- `POST /editor/<path:slug>` — atomic write (temp file + `os.replace`),
  refreshes the content monitor, triggers AP publish if enabled.
- `POST /editor/preview` — renders Markdown through the existing
  `render_html` pipeline and returns HTML.
- `POST /editor/upload` — image upload to `img/@<user>/` with MIME and
  size checks; returns the URL to embed.
- `POST /editor/<path:slug>/delete` — optional; move to a
  `markdown/@<user>/.trash/` subdir rather than hard delete.

Security considerations:

- CSRF on all POST endpoints.
- Reject slugs that don't match `^[A-Za-z0-9._/-]+$` (path segments
  validated individually, no `..`, no leading `/`).
- Realpath containment check identical to the read path.
- Rate-limit uploads to avoid disk exhaustion.

UI:

- `templates/editor.html` with a plain `<textarea>` first, split-pane
  live preview as a follow-up.
- Minimal JS — no framework required.

---

## 2. Per-user ActivityPub actors with the default actor as a `Group`

Once multi-user content works over plain HTTP, federation is the
natural next step. The design goal is:

- The **default user** (the historical single actor of the blog)
  becomes an ActivityPub `Group` actor.
- Each **additional user** becomes a `Person` actor.
- Group membership models the blog: publishing under `@blog@domain`
  fans out to everyone who follows the group, while each user can
  independently be followed at `@user@domain`.

This section is a research/planning sketch, not a final spec — the
implementation of this follow-up should get its own
`docs/<nnn>-multi-actor-ap/` directory with the usual research → plan →
implementation flow.

### 1.1 Actor model

Two actor types, one identity per user directory:

| Actor | Type | `preferredUsername` | Owned by |
|-------|------|---------------------|----------|
| Blog / default | `Group` | `config.activitypub_username` (unchanged) | default user |
| Each additional user | `Person` | `<user>` | that user |

- The `Group` actor keeps the current key material, inbox, outbox,
  followers, and URL — critical for federation continuity. Existing
  followers must not be forced to re-follow.
- The `Group` actor's `attributedTo` and `audience` fields link to
  the individual `Person` actors, making the membership discoverable
  by federated servers that understand `Group` semantics (Mastodon
  Glitch/Sharkey/Guppe-style groups, Lemmy).
- Fallback for clients that ignore `Group` semantics: the Group
  continues to post as it does today (its outbox contains everything
  the blog publishes). Following the Group therefore keeps working
  even on servers that render it as a plain actor.

### 1.2 Directory layout

Extend `<state_dir>/auth/users/<user>/` with an `activitypub/`
subtree:

```
<state_dir>/
  activitypub/                  # existing: the Group's keys and state
    private_key.pem
    state/
    file_urls.json
  auth/
    users/
      <user>/
        activitypub/            # new: per-Person actor state
          private_key.pem       # 0600
          state/                # pubby FileActivityPubStorage
```

The default user's `Group` actor keeps its existing top-level
`<state_dir>/activitypub/` directory — no migration required.

### 1.3 URLs

- Group actor: `<link>/ap/actor` (unchanged) and profile page
  `/@<activitypub_username>` (unchanged).
- Person actor: `<link>/@<user>/ap/actor`, with all standard
  collections nested underneath (`/@<user>/ap/inbox`,
  `/@<user>/ap/outbox`, `/@<user>/ap/followers`,
  `/@<user>/ap/following`).
- WebFinger: `acct:<user>@<domain>` returns the Person actor,
  `acct:<activitypub_username>@<domain>` continues to return the Group
  actor. Both are served by the same WebFinger endpoint dispatching on
  the resource name.

### 1.4 Publish flow

When a user publishes to `markdown/@<user>/`:

1. The `Person` actor is the primary `attributedTo` of the AS2 object.
2. The `Group` actor is added to `audience` (and, for wide fan-out,
   to `cc`).
3. Delivery targets:
   - Followers of the `Person` (their `sharedInbox`/`inbox`), and
   - Followers of the `Group` (so long-time subscribers of the blog
     keep receiving everything).
4. Deduplication: the recipient set is unioned on inbox URL to avoid
   sending duplicate `Create` activities to the same shared inbox.

For default-user content, the `Group` remains the sole `attributedTo`
(no `Person` involved). This preserves back-compat for existing
articles' AP object IDs and for the current federation contract.

### 1.5 Announce fan-out (alternative delivery model)

An alternative to the union delivery in §1.4 is the Guppe-style flow:

1. `Person` sends `Create Note` only to its own followers.
2. `Person` sends the same object as an `Announce` addressed to the
   `Group`.
3. The `Group` receives the `Announce` on its inbox and re-`Announce`s
   it to its followers.

Advantages: cleanly models "group boosts a member's post" and works
even with strict receivers that reject direct posts addressed to a
Group. Disadvantage: double the outgoing traffic.

Decision: start with the simpler unioned direct delivery (§1.4) and
add Announce-relay as an option (`activitypub_group_relay: true`) if
we hit compatibility issues.

### 1.6 Inbox routing

- The Group inbox continues to accept everything it accepts today.
- Each Person inbox handles Follow/Undo/Like/Announce/Reply targeted
  at that user's posts.
- A follow addressed to the Group is stored on the Group actor.
- A follow addressed to a Person is stored on that Person actor.
- Reply attribution follows the `inReplyTo` object's `attributedTo`.

### 1.7 Signing keys

- Each Person actor has its own RSA keypair generated on first startup
  using `pubby.crypto.generate_rsa_keypair` (same helper the Group
  currently uses).
- HTTP signatures on outbound requests use the actor doing the sending
  (Group for Group-authored activities, Person otherwise).

### 1.8 Migration for the default user

None required. The default user's `Group` actor **is** the current
single actor — same URL, same keys, same inbox. Existing federation
edges keep working. The `type` field flips from `Person` to `Group`
only if the operator opts in via a new config key
`activitypub_default_actor_type: group` (default remains `Person` for
strict back-compat). Servers that don't understand `Group` degrade
to treating it as a regular actor.

### 1.9 Open questions to resolve in the follow-up research doc

- Do we want `Group.membership` populated with Person actor URIs, or
  is `attributedTo` sufficient?
- How do we surface member accounts on the Group's profile page for
  non-AP clients?
- Does switching the default actor from `Person` to `Group` cause
  Mastodon to drop or re-request followers? (Empirically: no, but
  needs to be verified against current Mastodon versions.)
- Nodeinfo / instance metadata implications when multiple actors live
  on the same origin.

---

## 3. IndieAuth / OpenID Connect / OAuth login

- **IndieAuth**: philosophically aligned with the IndieWeb roots of
  Madblog; lets an owner log in with their own domain. Would coexist
  with password auth (either method sets the same session).
- **OpenID Connect / OAuth**: useful for teams with an existing IdP
  (self-hosted Keycloak, Authelia, etc.).

Both are additive on top of the Phase 1 session layer.

---

## 4. WebAuthn / passkeys

Modern, phishing-resistant, but requires:

- Storage for credential public keys under
  `<state_dir>/auth/users/<user>/webauthn.json`.
- Client-side JS in the login template.
- Fallback to password when a browser lacks support.

---

## 5. Cross-worker rate limiting

`flask-limiter` with `memory://` is single-process. If Madblog is
deployed with more than one gunicorn worker, brute-force protection is
per-worker, not per-service. Options:

- Switch the limiter storage to a file-backed SQLite URL.
- Optional Redis backend for larger deployments.

Neither is worth doing until we see multi-worker deployments in the
wild.

---

## 6. User self-service password change

- `POST /account/password` protected by `@login_required` and CSRF.
- Requires current password re-entry.
- Simple UI under a new `templates/account.html`.

---

## 7. Session revocation / device list

Signed-cookie sessions cannot be revoked individually without either
rotating `secret_key` (kills all sessions) or maintaining a
server-side blocklist. A minimal server-side "session generation
counter" per user in `profile.yaml` would suffice: incrementing it
invalidates all outstanding cookies for that user. Adds one extra
lookup per authenticated request.

---

## 8. Audit log

Append-only file `<state_dir>/auth/audit.log` recording login
success/failure, password change, and (once the editor exists)
content mutations. Small operational win, easy to add.

---

## 9. `remove-user` CLI

Mentioned as a stretch goal in `02-PLAN.md`. Needs to:

- Delete `<state_dir>/auth/users/<user>/` after confirmation.
- Refuse if `markdown/@<user>/` or `replies/@<user>/` still contain
  files (safer than orphaning content).
- Emit a warning about federated followers if per-user AP actors are
  enabled (see §1) so the operator can send `Delete Actor` first.
