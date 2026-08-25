# Handoff — 2026-08-25, the hi-res overlay bug the owner actually caught, fixed, and now confirmed

Continues `2026-08-25-1400` directly. That cloud run shipped §19c (the daily
hi-res grid job) with 346/346 tests green and a clear note that the one thing
it could not check was whether the overlay actually *looked* right on a real
screen. It didn't.

## What happened, in order

1. The owner opened `/lake/zalew-zegrzynski` on the real deployment and saw a
   garbled, diagonally-streaked overlay bleeding across farmland and the
   river — nothing like the lake's shape.
2. A separate session (branch `claude/project-status-review-xtzib7`, not this
   one) diagnosed and fixed it. Root cause: `lake_detail.html`'s client JS
   sized the heat canvas and positioned the Leaflet image overlay from the
   page-load `GRID` constant — the *coarse* interactive grid computed once
   when the page rendered. But for `horizon=0` on a qualifying lake,
   `/lake/{slug}/grid` can answer from the daily hi-res cache instead, which
   carries its own `origin_lat`/`n_rows`/`n_cols`/`cell_m` at a different
   resolution (409×412 @ 32 m for Zegrzyński, vs. the coarser interactive
   grid). `loadGrid()` was discarding every field but `cells`, so
   `renderHeat()` wrote hi-res row/col indices into a canvas buffer sized for
   the coarse grid — `idx = (y * GRID.n_cols + col) * 4` overflows row by row
   once `col` exceeds the coarse grid's width. That is exactly the
   diagonal-streak, bled-past-the-shoreline pattern the owner saw.
3. This session found that branch, reviewed the actual diff (not just the
   commit message) to confirm the fix was real before trusting it, ran
   `make check` clean on it (346/346, ruff, mypy `--strict`), fast-forwarded
   it into `claude/repository-edit-push-ggr229`, and rebuilt the deployment.

## The fix, and why it's the right shape

`renderHeat()`, a new `gridStep()`/`gridBounds()` pair, and `pickSpot()` now
all derive their geometry from whichever grid metadata the `/grid` response
actually carries, tracked in a shared `activeGrid` updated on every fetch —
never from a value fixed once at page load. Confirmed the hi-res job's own
payload (`app/jobs/handlers.py`'s `handle_grid_hires`) really does include
the same `origin_lat`/`origin_lon`/`cell_m`/`n_rows`/`n_cols` fields the
coarse route sends, which is what makes `loadGrid()`'s
`data.origin_lat !== undefined` detection actually work rather than silently
falling back to the old broken behaviour.

## Verifying it live, and the workaround that took

Wanted to look at the actual rendered overlay, not just trust the diff — this
project's own standing rule. Two obstacles, both from the in-session browser
tool's own network policy, nothing to do with the app:
- `/static/style.css` has been `net::ERR_BLOCKED_BY_CLIENT` all session (see
  `2026-08-24-2225`'s thumbnail work for the earlier workaround).
- This time the `/grid` fetch itself was also blocked — the exact request
  `loadGrid()` makes to get overlay data, which meant the live page could not
  be screenshotted with the overlay actually drawn.

Worked around it by pulling the real JSON `curl` gets from
`/lake/zalew-zegrzynski/grid?horizon=0` (409×412, 32 m, 20 007 real cells —
not a fixture) into a small standalone local page that runs the **fixed**
`renderHeat()` pixel loop verbatim (`python -m http.server` on localhost,
navigated to from the browser tool — `file://` URLs outside the project
render as inert static snapshots in this tool, so a local HTTP server was the
way in). Screenshotted the result: a clean, correctly-shaped branching
reservoir, smooth colour gradient, no diagonal streaking, no bleed past the
shore. Same shape as `§19a`'s outline-traced thumbnail for the same lake,
which is a nice independent cross-check that both features agree on what
Zalew Zegrzyński actually looks like.

**This is real evidence, not a simulation** — the JSON came from the live,
running deployment; only the *page* rendering it was a stand-in for the parts
of the real page this tool can't currently reach.

## State

Branch `claude/repository-edit-push-ggr229`, pushed through `1de2536` (the
merged fix) plus this session's backlog update. `docs/09-BACKLOG.md §19c` is
now the full record: original build, the bug, the root cause, the fix, and
this verification. §19 as a whole is `19a/19c DONE, 19b open design
question` — everything the owner asked for on 2026-08-24 after the first live
run is either shipped and confirmed, or explicitly left as a design question
for them to answer, not a build task waiting on nothing.

## Worth remembering

**A green test suite and a clean data-level check both said this was fine.
It wasn't.** The bug was purely in how the client JS used response data whose
*shape* (not presence — both grids answer with all five fields) differs by
which grid answered. No unit test exercised the browser rendering path at
all; `tests/test_hires_grid_route.py` checks the JSON response is correct,
which it always was. This is the same lesson `CLAUDE.md` already states
about the fish-pin dive and the species icons, generalised one more time:
**a passing test suite says nothing about whether the pixels are right.**
Produce the artefact and look at it — and when the obvious way to look is
blocked, it is worth finding another way to look rather than reporting the
data check as if it were the same thing.
