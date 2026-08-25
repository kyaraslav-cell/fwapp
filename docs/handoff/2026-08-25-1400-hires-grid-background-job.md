# Handoff — 2026-08-25, the daily hi-res grid background job (§19c)

Cloud sandbox session, no access to the owner's live deployment. Continues
`2026-08-24-2225` directly — that session scoped §19c in detail and
deliberately left it unstarted. This session built it.

## What got built

The sketch in `docs/09-BACKLOG.md §19c` was specific enough to build from
directly, no re-derivation needed:

- **`geo_service.hires_cell_size_for_area(area_ha)`** (`app/geo/service.py`)
  extends `cell_size_for_area`'s area-based scaling with its own target-cell
  count and clamp, gated behind `HIRES_AREA_THRESHOLD_HA = 50.0` ha. Returns
  `None` below the threshold — Pomocnia (9 ha) stays untouched; Zalew
  Zegrzynski (2046.8 ha) gets 32 m cells against the interactive endpoint's
  64 m. Both numbers are compute-cost engineering choices, not fishing
  judgement, so per CLAUDE.md law 1 they stay in code, not
  `config/rules.v*.yaml`.
- **`GRID_HIRES = "grid_hires"`** in `app/jobs/handlers.py`, deliberately
  *not* in `NEW_WATER_PIPELINE` — it is a recurring daily refresh keyed to
  *today*, not a one-time build step. Its own scheduler entry,
  `run_hires_grid_job` in `app/ingest/scheduler.py`, runs at
  `CronTrigger(hour=4, minute=15)`, right after the 04:00 prediction pass so
  "today's wind" already reflects the fresh forecast. It queues one job per
  qualifying lake; the existing 30 s `run_jobs_tick` drains it like any other
  job kind, so nothing about the runner needed to change.
- The handler works out today's wind the same way the live lake page already
  picks a default — `current_conditions`, falling back to `recent_days`'
  first entry — factored into `_todays_wind_dir` so the two paths can't
  quietly disagree. It defers (`NotReadyYet`) rather than fails when the
  outline or today's weather isn't in yet, same contract as every other
  handler here.
- **New table, `HiresGridCache`** (`app/core/models.py`), keyed on
  `(lake_id, for_date)`, replaced idempotently rather than appended to —
  `app/geo/hires_cache.py` holds the store/fetch pair. `for_date` is a
  Europe/Warsaw calendar date (`to_display(utcnow()).date().isoformat()`),
  matching how the day strip already reasons about "today".
- **The one refactor beyond the sketch**: the three-factor/v0.3-fallback
  scoring logic used to live inline in the `/lake/{slug}/grid` route. Pulled
  it out into `bite_view.score_grid_cells` so the route and the background
  job call the exact same scoring path — the cache can never disagree with
  what a live request would have computed for the same inputs. Without this
  the job would have been a second, hand-copied implementation of the same
  ~30 lines, which is exactly the kind of drift law 2's whole "one scoring
  path" discipline exists to prevent.
- **`/lake/{slug}/grid`** gained a `horizon` query param (0 = today, matching
  the day strip's own numbering) and checks the cache first only when
  `horizon == 0`. Every other horizon, and every lake below the size
  threshold (whose cache is simply never written), falls through to the
  existing on-demand path unchanged — the route doesn't need its own size
  check, because a small lake's cache lookup always misses.

## A bug caught mid-session, not by a test

`gridUrl()` in `lake_detail.html` needed to start sending `horizon`. The day
strip already tracks it (`currentHorizon`, set in `showDay`). But there is a
second interactive path — clicking a row in the "recent conditions" weather
table sets `currentWind` to that day's wind and reloads the grid, independent
of the day strip, to let you preview a past day's wind. That table's rows had
no horizon of their own, so without a fix every click there would have left
`currentHorizon` at whatever it last was (usually 0) — meaning a click on
*yesterday's* wind, on a lake with a hi-res cache, would have silently kept
answering with *today's* cached grid. Gave each row `data-horizon="{{
-loop.index0 }}"` (0 for the first/most-recent row, negative for the rest)
and had the click handler set `currentHorizon` from it. Caught by re-reading
the handler after the first pass, before writing tests — worth flagging
because it's exactly the kind of gap a route-level test alone would have
missed, since the route itself was correct; the bug was only in which
`horizon` the page sent.

## What was verified, and how

- `tests/test_hires_grid_resolution.py` — pure arithmetic: below-threshold
  returns `None`, unknown area treated as small, a large lake gets a finer
  cell than the interactive grid, clamped at both ends, grows coarser with
  area.
- `tests/test_jobs.py` — the new handler against a real (if small) polygon
  from `app.geo.demo_zones.approximate_outline_geojson`: skips a lake below
  threshold without touching the cache table, defers on a missing outline,
  defers on missing weather, writes the cache with the right date/lake key,
  and replaces rather than duplicates the row on a second run the same day.
- `tests/test_hires_grid_route.py` — full app through `TestClient`: today is
  served verbatim from a seeded cache row; a forecast horizon (1) never reads
  it even when a same-lake cache row exists for today, monkeypatching
  `bite_view.score_grid_cells` to prove the live path actually ran instead;
  a lake with no cache (Pomocnia, below threshold) still answers from the
  live path.
- `make check` — ruff clean, `mypy --strict` clean on the required packages
  (`app/geo` and `app/jobs` both grew: `hires_cache.py`, the new handler,
  the `HIRES_*` constants — no `Any` leaks, no untyped defs), **346/346
  tests passing** (up from the 333 this session started with). Ran from a
  fresh `python -m venv .venv && pip install -r requirements-dev.txt`, not
  reused from a prior session.
- Smoke-tested `/lake/pomocnia` and `/lake/pomocnia/grid` end to end through
  a real `TestClient` against a throwaway SQLite file, both horizons — pages
  render, routes answer 200, no template error from the new `data-horizon`
  attribute.

## What is NOT verified, and can't be from here

Per this task's own brief and `docs/10 §6` — nothing in this app has ever
reached a real network from this sandbox, and that pattern holds:

- **The real APScheduler entry actually firing at 04:15 UTC** against a live
  process. Only unit-level: the handler and the scheduler function are
  tested directly, not the cron wiring itself running for real.
- **Zalew Zegrzynski's real outline and real weather producing a sane 32 m
  grid.** Every test here uses a fixture circle from `approximate_outline_geojson`
  or a hand-built outline — the real ~2 700-point OSM ring, and Open-Meteo's
  actual hourly series for that lake, have never driven this code.
- **The rendered overlay itself, on the Leaflet canvas.** This is the one
  worth calling out deliberately, per this project's own hard-won rule that
  visual and motion changes cannot be verified by reading the diff or the
  tests. Nothing in `tools/` currently screenshots the heat overlay — 
  `tools/animation_filmstrip.py` and `tools/icon_sheet.py` cover motion and
  species icons, not this. **First thing to check on the owner's machine:**
  open Zalew Zegrzynski's lake page, confirm the overlay is visibly finer
  than before, and confirm a forecast day still recomputes (coarser) rather
  than showing the same fine grid as today.
- **The size threshold against a water this app doesn't have yet.** 50 ha was
  picked because it sits cleanly between the two real lakes on file; there is
  no third lake to check it against, so the number is defensible reasoning,
  not calibrated data.

## A scope trade worth flagging to the owner if it turns out to matter

The hi-res cells are only ever computed once, at ~04:15 UTC, for the wind
direction and phase at that moment. If wind swings hard later the same day,
today's cached overlay does not follow it — every other water (below
threshold, or on a different horizon) still gets the live, current-wind
overlay on every request. This is the sketch's own trade ("essential but
should not cost a lot of resources", §19c: "not a blocking on-demand
recompute"), not an oversight — but it means a large water's map can go a few
hours stale on wind direction specifically, on a day the wind actually
shifts direction. Not worth solving speculatively; worth a line to the owner
once Zalew Zegrzynski gets real use.

## State

Branch `claude/repository-edit-push-ggr229`, this session's commits pushed
through this point. `docs/09-BACKLOG.md §19c` updated with the same detail as
above; §19's header now reads "19a/19c DONE, 19b open design question".

## Next

Per this task's own instruction: stopped here rather than inventing further
scope. The live-deployment check above is the one thing this session
genuinely could not do and the owner's own next step. Everything else in
`docs/10 §8`'s suggested-next-session list is unchanged: the eight
old-style fish icons, terrain/tree shelter, `name_ru`, numbered migrations,
then the calibration loop.
