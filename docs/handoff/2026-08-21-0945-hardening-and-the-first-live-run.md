# Handoff — 2026-08-21, the first live run, and hardening before the machine

Continues `2026-08-19-1200`. That session built rate limiting and the Gemini
pass; this one got the app in front of real services for the first time, found
what that exposed, and closed four of the five pre-launch items.

## State

Branch `claude/accounts-calendar-handoff-wdpmcq`, **merged into the default
branch `claude/repository-edit-push-ggr229` after every change and pushed**.
The Pages workflow is green again (it broke once mid-session — see Traps).

`make check` green: ruff, `mypy --strict` over `app/core app/rules app/features
app/auth app/jobs app/discover app/geo app/intel app/media`, **321 tests** —
204 at the start of the previous session, 265 at the start of this one.

## Decisions, and why

**By id, the largest ring wins; by proximity, containment still does.** The
outline fetch asks Overpass one of two questions and the tie-break must follow.
When we ask *by OSM id*, every ring belongs to the object the angler already
picked, so the only question left is which part is the water body — the
largest. "Nearest to the centroid" is actively wrong there: Nominatim's point
for a long reservoir is a *label* position and need not fall inside the
shoreline at all, so nearest would prefer whichever side basin sat closest to
the label over the 3 300 ha main body. The proximity rule is untouched — there
the candidates include waters nobody asked for and the Wkra's polygon is far
larger than Pomocnia's.

**`.env` is applied by the app itself, and the shell always wins.** `docker
compose` reads `.env`; `make dev` did not, so the documented way to configure
the app was a silent no-op outside docker and presented as "the key is wrong".
Thirty lines of stdlib rather than `python-dotenv` and an ADR to justify it.
The precedence rule is what keeps it safe: a variable already in the process is
never overwritten, or `FISHLOG_GEMINI_API_KEY=... make dev` is silently ignored
in favour of a stale line, and the test suite passes or fails by machine.

**A healthcheck reports the age of the weather, not the liveness of the
process, and is 503 for anything but fresh.** The failure worth catching is not
a crash — a crash is obvious. It is the scheduler dying quietly while every
page still renders, describing last Tuesday. Most monitors check the status
code, so `{"status": "stale"}` with a 200 would report green through exactly
that. It reads the database rather than calling Open-Meteo: a healthcheck that
fails when Open-Meteo is briefly slow pages somebody at 3 a.m. for nothing.

**Photos are re-encoded, never stored.** Decode, apply orientation, redraw onto
a clean canvas, shrink, encode. The order is the whole trick: strip EXIF before
honouring the orientation tag and every portrait phone photo lands sideways.
Metadata is removed by *copying pixels onto a new canvas*, not by asking the
encoder to omit it — `save()` carries `info["exif"]` through on some paths, and
"we passed no `exif=` argument" is not a property anyone can verify later.
ADR 0006.

**Framing is denied, with one opt-in that is not an attack.** A dev container
preview pane is an iframe, and `frame-ancestors 'none'` refuses it — the pane
then reads "refused to connect", indistinguishable from a dead server.
`FISHLOG_FRAME_ANCESTORS` narrows the ancestor list for that case only.
`X-Frame-Options` is *dropped* while it is set, because that header has no
usable allowlist (`ALLOW-FROM` is dead everywhere), so leaving `DENY` beside a
CSP ancestor list is a contradiction browsers resolve in favour of DENY — the
pane stays blank while the config looks correct.

**The security-header middleware is the outermost one.** A 404, a static file
and an unhandled exception all skip the router, and those are exactly the
responses that would go out bare.

## Broken / unfinished

1. **Offline is not built** — `docs/15 §A5`, and the largest gap in the
   product. At a PZW water with one bar the lake page will not load and a
   caught fish cannot be logged. `docs/07`'s two-seconds-per-fish target and
   rule 10 in `docs/10 §2` are both unreachable today. Needs its own ADR: an
   outbox means two sources of truth for a while.
2. **Islands are dropped from outlines.** `_rings_of` returns outer rings only,
   because the grid builder takes a single ring. Zegrze has islands, so its
   polygon treats them as water. Fixing it means teaching `app/geo/grid.py`
   about holes.
3. **`'unsafe-inline'` is still in `script-src`** — the map, day strip, fish pin
   and register form are all inline blocks. Removing it means nonces through
   every template or moving that JS into `/static`.
4. **Gemini and Google sign-in have still never run.** Gemini was *skipped*, not
   tested — no key was set. Google cannot be probed by a script at all: the
   consent leg needs a human and a browser, and the redirect URI depends on
   hosting that has not been chosen.
5. Everything in `docs/10 §5` and all of `docs/15 §B`.

## Traps

- **`.gitignore media/` swallowed `app/media/`.** Unanchored, the pattern
  matches a directory named `media` at any depth, so `git add -A` silently
  dropped a whole package. `make check` was green because the files were on
  disk; only a fresh clone disagreed, and the first fresh clone was CI. Now
  `/media/`, and `make check` compares every `.py` under `app/` and `tests/`
  against `git ls-files`.
- **Proving a test fails by sabotage needs `__pycache__` cleared** when the edit
  preserves file length. `if by_id:` and `if False:` are the same number of
  bytes; Python reused the stale bytecode and the restored source kept
  "failing".
- **A local `line` variable shadowed the `line()` reporting helper** in
  `preflight`. Every *failure* path worked and every *success* path raised
  `TypeError` — caught by running it, invisible in review.
- **A `file://` parent cannot test `frame-ancestors *`.** `*` deliberately does
  not match `file:`, so the first framing check reported blocked when the
  feature was fine. Redone over http.
- **Pillow's GPS EXIF fixture needs `exif.get_ifd(0x8825)`**, not a nested dict
  assigned to `exif[0x8825]` — the latter raises inside `_limit_rational`.
- Still live from before: the i18n catalogue is cached per process, and a YAML
  value containing `: ` must be quoted.

## Verified vs assumed

**Observed working, on the owner's networked machine:** Nominatim, Overpass
(2 668-point polygon for Zalew Zegrzyński in 2.4 s) and Open-Meteo, through
`make preflight`. This is the first time any outbound client in this project has
been seen to work.

**Observed working here:** the rate-limited sign-in form in three languages; the
collected-facts section including a dead-source marker; the 404 in three
languages; the app rendering inside a real iframe with the opt-in set and
refused without it; zero CSP violations across home, lake, login and register in
a real browser; photo processing measured at 325 KB → 53 KB with GPS gone and
the image compared side by side; the dependency check reporting a genuinely
uninstalled Pillow; the untracked-source guard naming both files of the package
git had eaten. Every behavioural test in this session was confirmed to fail
against the code before its fix.

**Believed, never observed:** Gemini and Google, as above. Also
`script-src https://unpkg.com` — this sandbox blocks unpkg, so the CSP was never
exercised against a Leaflet that actually loaded. If the first real page load
shows a blank map and "Refused to load" in the console, that line is why.

## Next

1. **A5, offline.** ADR first — service worker for the shell, outbox in
   IndexedDB, each queued catch carrying **its own** timestamp so law 2 and the
   CPUE arithmetic stay honest, and an idempotency key so a retry cannot
   double-log a fish.
2. **Set `FISHLOG_GEMINI_API_KEY` and run `make preflight ARGS=gemini`.** It
   prints the facts and their sources, so the answer can be judged and not just
   the connection.
3. **Pick the machine** (`docs/10 §9`). Everything else about going live waits
   on that, and `FISHLOG_TRUST_PROXY=1` must be set the day it is behind a
   proxy.
