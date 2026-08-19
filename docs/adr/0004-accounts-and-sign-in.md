# ADR 0004 — Accounts, sign-in, and where the boundary between public and private runs

**Status:** built and tested. `app/auth/`, `app/web/routes/auth.py`,
`user` + `auth_session` tables, `session.user_id`.
**Date:** 2026-08-19
**Supersedes:** nothing. `docs/05-ARCHITECTURE.md` §"Multi-lake and multi-user"
said an auth layer and a `user_id` column were "deliberately deferred"; the
owner asked for them, so this is the record of how they were built.

---

## Context

`docs/01-SPEC.md` scoped multi-user accounts out of v1 and `docs/05` deferred
them, both on the reasoning that one angler and one lake need no accounts. The
owner asked for sign-in with a password and, optionally, with a Google
credential.

Nothing in the schema blocked it — `lake_id` was on every table from day one —
but three things in this project make the design non-obvious:

1. **The published site is public and read-only.** `tools/build_static.py`
   renders the app through `TestClient` and puts it on GitHub Pages. Anything
   that demands a cookie on a read path breaks that build.
2. **CPUE is the unit of success (law 3), and it is not pooled.**
   `app/notebook/water_type.py` already refuses to average across a PZW water
   and a commercial fishery, because they are different measurements wearing
   one name. Two anglers are the same problem.
3. **The owner already has sessions logged.** Whatever ownership model lands
   must not make them vanish.

## Decision

### 1. The boundary is read vs. notebook, not page vs. page

| Open to everyone | Needs an account |
|---|---|
| places list, lake page, conditions, five-day table, map and overlay, `/grid` | `/history`, `/session/*`, `/places/new`, `POST /lake/*/refresh`, `/lake/*/spot` |

The lake's weather is a public fact; the notebook is one person's record. That
split is also exactly what keeps the Pages build working with no special case
in the app — the static build only ever renders the left column.

Enforced in one place, `app/web/app.py`, where the notebook routers are
included with `dependencies=[Depends(require_user)]`. A security boundary that
is a list of decorators scattered across five files is a boundary that will be
forgotten on the sixth.

### 2. scrypt from the standard library, not passlib/bcrypt/argon2

`hashlib.scrypt` is memory-hard, in the stdlib, and needs no new dependency for
one function — `docs/adr/0001` requires an ADR before adding a dependency, and
this did not earn one. Parameters are OWASP's 2024 floor (n=2¹⁷, r=8, p=1) and
are stored **inside** the hash string, so raising the cost later leaves old
hashes verifiable and `needs_rehash()` rewrites them on next sign-in.

Measured on the build machine: ~0.5 s to verify. **If the app ends up on a Pi
(docs/10 §9 says it might), drop to n=2¹⁶ with p=2** rather than living with a
three-second login.

### 3. Server-side sessions, and only the hash is stored

A signed cookie (`itsdangerous`, JWT) cannot be revoked, and "sign out
everywhere" after a lost phone has to delete something. So: a random 256-bit
token in an HttpOnly cookie, `sha256(token)` in `auth_session`.

`docs/05` tells the owner their backup strategy is copying the SQLite file. A
database full of usable session tokens would make every backup a set of keys.
Unsalted SHA-256 is correct here and would be wrong for a password: the input
is already 256 bits of entropy, so there is nothing to precompute.

Thirty-day term, sliding — a session seen inside its last week is pushed back
out to a full term, so a phone in regular use is never signed out on the bank.

### 4. Google: authorization code flow, userinfo instead of JWT verification

Verifying Google's `id_token` locally means fetching and caching their rotating
JWKS and doing RSA verification — `google-auth` or `pyjwt[crypto]` as a
dependency. Instead the code is exchanged for an access token and the profile
is read from Google's userinfo endpoint over TLS. Same three fields, same
origin, transport does the authentication. Cost: one extra HTTPS round trip,
once a month per angler.

Consequences recorded honestly:

- **Accounts join on `sub`, never on email.** Google addresses change and get
  recycled; the subject does not. Matching on email would hand a stranger
  somebody's notebook the day an address is reissued.
- **An existing password account with the same address is linked, not
  duplicated** — the angler who registered with a password and later pressed
  the Google button has one notebook, not two. The password keeps working.
- **`email_verified: false` is refused.** Otherwise anyone able to create a
  Google account claiming an address walks into the account holding it.
- **Not configured is a state, not an error.** With no client id/secret in the
  environment the button is not rendered and the routes answer 503. No fallback
  that looks like it worked.
- **This has never run against Google.** The sandbox reaches no external host
  (`docs/10 §6`). The flow is tested to the boundary — config presence, the
  authorization URL, the CSRF state check, the identity parser — and its first
  real exchange will be on the owner's machine. `docs/11` needs the redirect URI
  registered in the Google console before it can work.

### 5. CPUE is scoped per angler; counts are not

`list_sessions`, `active_session` and `lake_stats` take an optional `user_id`.
Signed-in views always pass one. This is law 3 again: pooling two anglers' fish
per hour is not a better-sampled CPUE, it is a different measurement, because
skill varies more than the weather does — which would bury the only signal the
project exists to find.

`user_id=None` keeps the old behaviour (everything on the water) for the
published read-only build and any anonymous reader. The home page shows session
*counts* that way, never CPUE.

### 6. The first account claims the sessions logged before accounts existed

`session.user_id` is nullable, and `claim_unowned_sessions` gives every
ownerless session to the first account created. The owner's season is the whole
dataset; making it disappear behind a login would look exactly like data loss.
Later accounts claim nothing.

### 7. Validation rules live in one pure module and return i18n keys

`app/auth/validation.py` returns keys like `auth.error.password_too_short`,
never sentences, so one rule reads the same in all three languages and is
testable without a browser. The register form runs a copy of the rules in the
browser to save a round trip; the server runs the real ones on every submission
and is the only thing that decides.

Length floor of 10, no composition rules. NIST SP 800-63B dropped
"must contain a symbol" because it produces `Password1!`; a length floor plus a
short obvious-password list is worth more.

## What was deliberately not built

- **Password reset by email.** It needs an SMTP credential and a deliverable
  sending domain, neither of which this deployment has. Until then the recovery
  path is the owner's own database. Say so rather than ship a "forgot password"
  link that goes nowhere.
- **Rate limiting on the login form.** Correct answer is per-IP and per-account
  throttling with a shared store; the app is one process on one box, so an
  in-memory counter would be the whole implementation and it would reset on
  every deploy. The mitigation in place is that scrypt makes each attempt cost
  ~0.5 s of CPU. **Build this before the app is on a public URL.**
- **Email verification for password accounts.** One angler on one lake; the
  address is not used for anything yet.
- **CSRF tokens on the app's own POST forms.** Session cookies are
  `SameSite=Lax`, which stops cross-site form posts in every browser this app
  will meet. Revisit if anything ever needs `SameSite=None`.
- **Per-user lakes and per-user zones.** Out of scope; the lake is shared.

## Consequences

- One more table pair to back up, and `session.user_id` on every future query
  that reports a number about one angler. A query that forgets it silently
  pools people — the same failure mode as forgetting `water_type`.
- The published Pages site now hides the sign-in link (`tools/build_static.py`),
  because accounts need a server and a door with no room behind it is worse
  than no door.
- `mypy --strict` now covers `app/auth` as well as `app/core`, `app/rules` and
  `app/features`.
