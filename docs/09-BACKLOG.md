# 09 — Backlog

Requested by the project owner, not yet built. Written down so work can resume
without re-deriving the brief. Ordered roughly by the owner's emphasis.

Status key: **TODO** · **PARTIAL** · **DONE** (done items are dropped once
verified in the app).

---

## 1. Multi-language UI — RU / PL / EN · DONE (needs a native check)

- Three languages: **Russian, Polish, English**. Translate everything the
  angler actually reads: nav, buttons, labels, table headers, weather terms,
  the provenance note, species names, empty states, validation messages.
- **Language switch control visible on the page**, not buried in settings.
- Species already carry `name_en` and `name_pl` in `config/species.yaml`;
  a `name_ru` column needs adding there and to the `species` table.
- Approach: a small dict-based catalogue (`config/i18n/{en,pl,ru}.yaml`) and a
  Jinja global `t("key")`, with the choice stored in a cookie. No new
  dependency — gettext/babel would be heavier than this earns.
- **Still open:** Polish and Russian angling vocabulary needs a native check.
  Translations were written without a native angler reviewing them, and terms
  like "fetch", "margin", "blank session" and "CPUE" are exactly the kind that
  read wrong when translated literally. Species names come from
  `config/species.yaml` (`name_pl`); **`name_ru` is still missing**, so Russian
  currently falls back to English species names.

## 2. Drop the manual phase buttons · DONE

- Remove the `spring warming / summer stagnation / autumn cooling` button row
  from the lake page.
- Derive **one** season/phase automatically from the current period and show
  it as plain text, not a control.
- **Constraint that still stands** (`CLAUDE.md`, ADR 0001 §5): thermal phase
  is a state derived from *modelled water temperature and its trend*, never
  from the calendar. Deriving it from "current period" is a temporary stand-in
  and must be labelled as such in the UI until the water-temperature model
  (`docs/02-DOMAIN.md` Layer 2) exists. Do not quietly turn a date lookup into
  a claimed measurement.

## 3. Terrain and shelter in the heat map · TODO

- Wind shelter from **trees, tree lines, banks and elevation**: a bank with a
  10 m tree line to windward is sheltered no matter what the open-water fetch
  says.
- Needs an elevation/landcover source (SRTM or Copernicus DEM for terrain,
  OSM `natural=wood` / `landuse=forest` polygons for tree cover). New data
  source ⇒ **write an ADR before coding it** (`docs/05-ARCHITECTURE.md`).
- Feeds a shelter multiplier applied to effective fetch per cell, and finally
  makes `bank_aspect_deg` / `tree_line_height_m` on `zone` earn their place.

## 4. Make the map differentiate visibly · DONE (first pass)

Problem the owner reported: **almost the whole lake renders one colour**, so
the overlay says nothing.

- Add more terms to the provisional score so cells actually separate:
  distance to weed edge, shore proximity bands, depth proxy, shelter (§3),
  sun/shade from tree line, and a wind-shadow term.
- Consider **percentile (rank) normalisation** for display instead of min-max:
  guarantees the full colour ramp is used even when raw scores cluster. This
  is a *display* transform — it must not be mistaken for the score itself, and
  must be documented as such.
- Owner's standing instruction: build a provisional formula now, they will
  supply the real one later. Keep it in YAML, keep `provenance:
  ai_authored_provisional`, keep `FORMULA_WIND_ZONE` unfilled.
  See `docs/adr/0002-provisional-zone-score.md`.

## 5. Fish pin interaction · DONE

- **While dragging:** the pin must stay visibly held under the cursor/finger
  (currently the browser's default drag ghost, which looks wrong on mobile).
  Use pointer events + a follower element rather than HTML5 drag-and-drop.
- **On release:** play a **dive animation, then the splash** — fish enters the
  water, ripples expand. Current build splashes but does not dive.
- Keep the idle bob animation.

## 6. Catch logging UI · DONE (first pass)

- **Species icons**: recognisable per-species silhouettes on the quick-log
  buttons, not text-only chips. Inline SVG (no icon-font dependency).
- **Sliders for weight and length**, pre-centred on that species' typical
  size, so the common case is one drag and no typing. Needs a
  `typical_weight_g` / `typical_length_cm` range per species in
  `config/species.yaml`.
- Rework the catch buttons generally — the current chips and the details
  `<details>` block are slower to use than they should be.
- Governing constraint (`docs/07-UI-SPEC.md`): **~2 seconds per fish**, one
  thumb, wet hands, bright sun. Every added control must pay for itself
  against that.

## 7. General · TODO

- Keep the design fast and uncluttered; the interface should read like an
  instrument, not an app.

---

## Recently closed

- End session button rendered nearly invisible: `--danger` was referenced but
  never defined in the pastel palette, so the background resolved to nothing
  and only the hover rule (a literal colour) showed. Fixed — constant pastel
  red.
- Heat map drawn over the Wkra river instead of the lake: outline selection
  took the largest nearby water polygon. Now containment-first.
- Colour ramp inverted so green = best, red = poor.
- Duplicated Places/History nav on desktop.


---

## Added since

## 8. Terrain shelter is still the big missing input · TODO

Item 3 above remains untouched and is now the largest single gap in the score.
Every term in `zone_score` is open-water geometry; a bank with a tall tree line
to windward is scored as exposed as one with none. Until that lands, the
overlay systematically over-rates sheltered corners in summer.

## 12. Water type: PZW vs commercial · DONE (first pass)

`water_type` on the lake, filter on the places list, CPUE guarded against being
pooled across the two. Closed seasons and size limits are NOT encoded — per
okręg, needs research; `is_regulated()` marks the hook.

## 10. Live zone scores on the published site · SPIKED, undecided

The Pages build answers only twelve wind directions because it has to pre-render
them. `/spike/pyodide/` tests whether the browser could run `app/geo/grid.py` and
`app/rules/zone_score.py` itself instead. Booting CPython in the browser and
scoring all 3 564 cells to an exact match with the server is done and measured;
loading the shapely wheel could not be tested from the build sandbox and is
verified by opening the published page.

**Next:** open it, screenshot the verdict, then decide between the three shapes
in `docs/12-SPIKE-PYODIDE.md` §4. Adopting Pyodide needs an ADR first — a 6 MB
interpreter fetched at page load is a dependency whatever `requirements.txt`
says.

## 9. Session UI while fishing · DONE

`/lake/{slug}` no longer redirects away during an active session, and the
session screen links back to conditions and history.


## 11. The map can only draw rings and a gradient · TODO — the real blocker

The owner's report, looking at the live overlay: *"there are no zones at all,
just huge stain"*. Correct, and the cause is not a bug in the score.

Two faults were found and fixed (see the v0.4 notes): the oxygen term saturated
at 1.0 across the whole interior so the largest weight was constant, and the
wind-exposure term had been folded into oxygen and the thermal lead, both of
which fade to nothing on a settled day. With those fixed the map shows a
windward/lee gradient again and raw spread went 0.212 → 0.326.

**But a gradient is not zones, and no amount of tuning will make it zones.**
Every spatial input the score has is either distance-to-shore or effective
fetch. On a convex 340 m bowl both are smooth functions of position, so the map
can only ever be concentric rings plus a directional gradient. Patches — *this
bay, that weedbed, the shelf by the reeds* — require data the project does not
have:

| Needed | Status |
|---|---|
| Bathymetry / depth contours | none. `shallow_proxy` is distance-to-shore, a documented stand-in |
| Weed beds and their edges | none. `docs/02-DOMAIN.md` argues the weed edge is a primary holding feature |
| Tree lines and terrain shelter | none — this is backlog §3 / §8, still untouched |
| Inflows, springs, structure | none |
| `bank_aspect_deg`, `tree_line_height_m` on `zone` | columns exist, unpopulated |

Cheapest first step by a distance: **the owner walks the lake once and marks
the weed edges and the deeper holes on the map.** Ten minutes of local knowledge
would add more spatial information than any amount of further weather modelling,
because it is the only source of the asymmetry the map is missing.

Second: OSM `natural=wood` for the tree line (backlog §3, needs an ADR).
Third: a depth survey, which for 9 ha is a morning with a marker float.

## 12. Accounts and sign-in · DONE (with three gaps)

- Password sign-in, registration with full form validation, and sign-out.
- Sign in with Google, off until `FISHLOG_GOOGLE_CLIENT_ID`,
  `FISHLOG_GOOGLE_CLIENT_SECRET` and `FISHLOG_GOOGLE_REDIRECT_URI` are set.
- The notebook (history, sessions, catches) is private per angler; the lake,
  the weather and the map stay public, which is what keeps the Pages build
  working.
- Design decisions and what was left out: `docs/adr/0004-accounts-and-sign-in.md`.

Rate limiting on both forms: `app/auth/throttle.py`, and the addendum to
ADR 0004 for why it is three windows rather than one.

**Still open, in the order they will hurt:**

1. **Password reset** - needs an SMTP credential and a sending domain.
2. **The Google flow has never talked to Google.** Register the redirect URI in
   the Google console and sign in once on a real machine.
3. **`FISHLOG_TRUST_PROXY=1` must be set** the day this goes behind Caddy or a
   Tailscale funnel, or every request counts as one address and the per-IP
   limit refuses everybody at once.

## 13. Day strip behind a calendar icon on the lake page · DONE (one caveat)

- Calendar icon beside the lake name, inside the lake page only. Tapping it
  rolls a strip of **today + 7 days** down in place; tapping again rolls it up.
- Each chip carries a **weekday, a date and a colour band**. Nothing else -
  the dawn window used to sit under the band and was removed as clutter. No
  number: the day score is never shown raw, and a "% chance of a fish" would
  claim a calibration this project has not earned - there are no logged
  sessions to calibrate against yet. When the calibration loop (phase 5) has a
  season of data, that percentage becomes computable and this is where it
  goes.
- Every band is read from a stored `prediction` row written before the day it
  describes (law 2). Nothing is recomputed at render time. A day with no row
  shows a hatched "no data" chip and is never filled in from its neighbour
  (law 4).
- Picking a day **recolours the map overlay** for that day's mean forecast
  wind, **swaps the conditions card** to that day's forecast (marked as one,
  and labelled with the day), and puts **one sentence** under the strip saying
  why the day scored as it did: what the pressure is doing, by how much over
  six hours, and how the ruleset rates that state. The rating is worked out
  from the ruleset's own `regime_scores` at render time (`regime_rating()` in
  `app/web/view_helpers.py`), so it inverts by itself if the owner's formula
  inverts the weights - no translation ever restates which pressure is good.
  Pinned by `tests/test_calendar_view.py`.
- The strip closes on the icon, on a tap anywhere outside it, or on Escape.
  **Closing always returns to today** - map, card and the ability to start a
  session all come back to now in one action, so there is no stale state to
  notice.
- **A session cannot be started from a forecast day.** Tapping the map while
  one is selected names the day and offers no start link - a session is always
  logged against now.
- Days past +5 are faded and the strip says why: the pressure forecast that
  drives the day score is weak that far out.

**The caveat, in one line:** a future day's overlay uses that day's forecast
*wind* with **today's** modelled water temperature and oxygen. The v0.4 bite
model is built from current conditions and there is no forward water-temperature
run yet. The UI only ever claims wind, but anyone extending this should know the
thermal half of the overlay is not a forecast.

**Open, and only worth doing once there is data:** past days in the strip
showing what was predicted beside what was actually caught. That view is the
calibration loop's face and is empty until sessions are logged.

## 14. The thermal-phase line on the lake page · REMOVED

It printed *"Assuming spring warming — from modelled water temperature
(15.8 °C, +0.4 °C/day)…"* above the map. Removed at the owner's request in
August: it read as a claim about the season, was wrong often enough to
undermine the rest of the page, and named nothing the angler could act on.

**The phase itself is untouched** - it still drives the overlay and is passed to
`/grid`. What went is the sentence about it. The provenance note under the map
remains, and is now the only place the page states that the overlay is modelled
and provisional. `tests/test_season.py` still asserts the phase never claims to
be measured.

If a phase display comes back, it needs to be something the angler can act on -
a depth band or a bank, not the name of a season.

## 15. Add a water by name · PARTIAL — the backbone is in

Built: search by name (Nominatim, throttled to their 1 req/s), a candidate
picker that marks non-water results rather than hiding them, dedupe by OSM id
and by name-plus-proximity, a per-account daily quota, and a **job queue** that
builds the water in the background — shoreline, a year of pressure history,
forecast, grid — while the angler already has a satellite map and a pin.

Design and reasoning: `docs/13-ADD-A-WATER.md`, `docs/adr/0005-adding-waters.md`.

The **Gemini pass is now built** (`app/intel/`, job kind `intel`, table
`water_fact`, shown on the lake page as "Local knowledge"). Six closed topics,
every claim dropped unless it cites an http(s) URL, each URL HEAD-checked, and
nothing it collects reaches the score. `docs/13 §10` and the addendum to
ADR 0005. **Now translated into all three site languages and trimmed to
essentials** — see `docs/handoff/2026-08-24-2152-...md`: `MAX_FACTS` 24→14,
`stocking` capped to one summarising fact instead of one row per species, and
a second Gemini call translates the kept English facts into Polish and Russian
rather than re-researching per language (`WaterFact.lang`, falls back to
English if a translation pass fails).

3. **A live run — DONE, 2026-08-24.** Nominatim, Overpass, Open-Meteo and
   Gemini all reached and working: `zalew-zegrzynski` was added live (outline
   2046.8 ha real OSM shoreline, 8784 h weather backfill, 4985-cell grid,
   intel pass in all 3 languages). `docs/13 §8`'s failure table has not needed
   to be exercised yet — nothing failed.

**Not built yet, in the order they matter:**

1. **Rivers.** Beat boundaries are findable, but flow is not modelled at all.
2. **Raster auto-tracing** for waters OSM has no polygon for. Deliberately
   deferred until the named-water path shows how often it is actually needed;
   it needs numpy and a GeoTIFF reader, so it gets its own ADR.



## 16. Pre-launch review · TODO — see `docs/15-PRE-LAUNCH-REVIEW.md`

A read of the codebase before it goes on a real machine. Five things to fix
(**four now done**: security headers, photo downscale + EXIF strip, the
`list_sessions` N+1 and missing FK indexes, `/health` and error pages —
**offline support is the one left**) and six
directions for the product (prediction-vs-reality, angler-marked features,
legality checks, a shareable session card, CSV export, moon phase).

The one that matters most: **the app does not work without a signal, and the
bank is where it is used.** `docs/15 §A5`.

## 17. Offline is the one pre-launch item left · TODO

`docs/15 §A5`. Four of the five are done (security headers, `/health` + error
pages, the N+1 + indexes, photo processing). This is the fifth, the largest,
and the one that decides whether the app works where it is used: at a PZW water
with one bar, the lake page will not load and **a caught fish cannot be
logged**.

Needs its own ADR before any code — an outbox is a second source of truth for
as long as the signal is down. Each queued catch must carry **its own**
timestamp (law 2, and CPUE) and an idempotency key, or a retry double-logs a
fish.

## 18. Islands are dropped from a water's outline · TODO

`_rings_of` in `app/geo/outline.py` returns outer rings only, because
`app/geo/grid.py` takes a single ring. Zalew Zegrzyński has islands and is
currently scored as though they were water. Recorded honestly in `docs/13 §11`
rather than fixed quietly.

## 19. From the first live session on the owner's machine · 19a/19c DONE (19c live-verified after a real bug + fix), 19b open design question

Three things the owner asked for on 2026-08-24, after seeing the app running
for real for the first time. Not started - written down so the brief survives
to whichever session picks each one up.

**19a. A lake thumbnail on the home/places list · DONE, 2026-08-24.** Every water card
(`app/web/templates/*.html`, the places list) currently shows a generic teal
gradient square regardless of which lake it is. Wanted: a small icon that is
*this water's actual shape* - "can be a satellite image, small resolution, so
it's lightweight". Two designs worth weighing before coding:
- **Trace the stored outline.** `Lake.outline_geojson` is already fetched and
  cached per water (real OSM shoreline, `docs/10 §1`) - render it as a small
  filled silhouette (SVG path or a tiny rasterised PNG, generated once when the
  outline job finishes, cached like everything else in `app/jobs/handlers.py`).
  No new external dependency, no per-request cost, matches rule 15 (MVP,
  lightweight, free).
- **A real satellite crop.** Truer to what the owner asked for literally, but
  needs a tile source (Esri, already used for the map background per `docs/10
  §6` — untested from this sandbox) cropped to the lake's bounding box and
  downsampled hard (thumbnail-sized, so bandwidth stays trivial). Costs one
  fetch per water at add-time, cacheable forever after since a lake's shape
  does not move.
Recommend starting with the outline trace - it's free, already-available data,
and ships the actual differentiator (Pomocnia's round bowl vs. Zegrzyński's
long reservoir look nothing alike as silhouettes alone).

**Built: the outline trace, not the satellite crop.** `app/geo/thumbnail.py`
(`outline_thumbnail_path`, pure, no I/O) turns a lake's `outline_geojson` outer
ring into a small SVG path — downsampled to at most 120 points regardless of
how dense the real shoreline is (Zegrzyński's outer ring alone runs ~2 700
points), so the icon stays cheap however large the water. `home()` in
`app/web/routes/places.py` reuses the same `water_outline()` call the lake
page's own map already makes — no extra fetch. Rendered white on the existing
gradient tile in `home.html`; a lake with no outline yet falls back to the
plain gradient square, unchanged. **Verified by rendering** (`tests/
test_thumbnail.py` covers the geometry; the actual visual result was screenshotted
live and the two real lakes are clearly, correctly distinct shapes — Pomocnia
a rounded bowl, Zegrzyński a long branching reservoir).

**19b. Weather cross-checked against a second source.** The owner compared the
app's numbers against Google's weather for the same place and saw them differ.
**Read `CLAUDE.md` before touching this**: *"There is exactly one weather
series for the whole lake"* and law 4 (never fabricate an observation) argue
against silently blending in a second live source - that would make it
unclear which number a stored `prediction` was ever computed from, which is
exactly what law 2's immutability exists to keep provable. Before adding
anything, this needs investigating, not assuming a bug:
1. Confirm the ingest is asking Open-Meteo for the right coordinates and the
   right variable (`temperature_2m` at 2 m, not surface skin temp) -
   `app/ingest/open_meteo.py`.
2. Confirm the *display* layer converts UTC to `Europe/Warsaw` correctly
   (`app/core/time.py`) - a display-only offset bug would look exactly like a
   "wrong temperature" complaint.
3. If both check out, some divergence from Google's own forecast model is
   normal - two different weather models over the same hour routinely differ
   by a degree or two. The honest fix then is not matching Google, it's making
   the app's own provenance visible enough (source, run time, "forecast" vs
   "observed") that the owner can tell divergence from a bug at a glance.
Only after that investigation, if the owner still wants a second live source
shown alongside the first for comparison, does that become a design decision
(and a law 4 conversation) rather than a bug fix.

**Investigated, 2026-08-24 — no bug found in either place checked:**
1. `app/ingest/open_meteo.py` requests `temperature_2m` (the standard 2 m air
   reading, same variable every consumer-facing weather product shows) at
   `lake.centroid_lat`/`centroid_lon` - `52.5431, 20.6762` for Pomocnia, which
   `config/lakes/pomocnia.yaml` already documents as corroborated by two
   independent published sources to ~150 m. A live direct query against
   Open-Meteo confirms it snaps to grid point `52.541195, 20.66278` (its
   nearest model node, ~200 m away) - normal behaviour for any gridded
   forecast model, not a coordinate bug.
2. `app/core/time.py` uses stdlib `zoneinfo` with `ZoneInfo("Europe/Warsaw")`,
   which handles the CEST/CET transition correctly by name rather than a fixed
   offset. `/health` on the live deploy reports the newest observation at 0.4 h
   old at the moment this was checked - the pipeline is not stale either.
3. So per point 3 above: this is very likely two different forecast models
   (Open-Meteo's blend vs. whatever Google Weather uses) legitimately
   disagreeing by a degree or two over the same hour, which is normal and not
   a defect in this app. `config/lakes/pomocnia.yaml` already has a
   `weather.secondary` entry on file for exactly this situation - METAR
   station EPMO (Warszawa-Modlin), 10.4 km away, real instrument readings, not
   wired into the app.

**Still open, now a design question rather than a bug hunt:** does the owner
want the app's own provenance made more visible (source name, model run time,
"forecast" vs "observed" wording) so a real divergence reads as expected
rather than alarming? Needs the owner's answer before building anything -
recommend asking rather than guessing at a UI change here.

**19c. A background job for a higher-resolution heat map on large waters.**
Grid cell size already scales with area (`geo_service.cell_size_for_area`) -
Zalew Zegrzyński (2046.8 ha) came out at 64 m cells / 4985 cells versus
Pomocnia's 5 m / ~3564 cells for 9 ha. The owner wants big waters rendered
finer, but computed **in the background, for today only**, "essential but
should not cost a lot of resources" - i.e. not a blocking on-demand
recompute, and not attempting all 8 forecast days at high resolution.
Sketch, for whoever builds it:
- A resolution floor/ceiling by `area_ha` (mirroring `cell_size_for_area`'s
  existing scaling, just extended rather than replacing it), gated behind a
  size threshold so small lakes are untouched.
- A new job kind alongside `outline`/`grid`/`forecast`/`intel`
  (`app/jobs/handlers.py`, `NEW_WATER_PIPELINE`) that runs once daily per
  qualifying lake - `build_scheduler` in `app/ingest/scheduler.py` already
  has a daily-cadence pattern to copy (`run_monthly_refresh_job`'s sibling).
  Compute for **today's** wind direction/phase only, cache the result (a
  second, finer `Grid`/scored-cell set, keyed by lake + date), and serve it
  from `/lake/{slug}/grid` when a hi-res cache exists and the request is for
  today; fall back to the existing on-demand coarse grid for every other day
  and for lakes below the size threshold.
- Cost stays bounded because it is one recompute per qualifying lake per day,
  not per request and not per forecast day.

**Built, 2026-08-25 - DONE, live-verified except one visual check.** Followed the sketch above
directly:
- `geo_service.hires_cell_size_for_area(area_ha)` (`app/geo/service.py`)
  extends `cell_size_for_area`'s scaling with its own target-cell-count and
  clamp, gated behind `HIRES_AREA_THRESHOLD_HA = 50.0` ha - well above
  Pomocnia (9 ha, untouched, returns `None`) and below Zalew Zegrzynski
  (2046.8 ha, gets 32 m cells vs. the interactive endpoint's 64 m). Both the
  threshold and the target-cell-count are compute-cost engineering choices,
  not fishing judgement, so per CLAUDE.md law 1 they stay in code rather than
  `config/rules.v*.yaml`.
- `GRID_HIRES = "grid_hires"` in `app/jobs/handlers.py`, deliberately **not**
  in `NEW_WATER_PIPELINE` - its own daily `CronTrigger(hour=4, minute=15)`
  entry in `app/ingest/scheduler.py`, right after the 04:00 prediction pass so
  "today's wind" already reflects the fresh forecast. `run_hires_grid_job`
  queues one job per qualifying lake; the existing 30 s `run_jobs_tick` drains
  it like every other job kind, so a slow grid build never blocks the tick.
- The handler computes today's wind the same way the live lake page already
  picks a default (`current_conditions`, falling back to `recent_days`'
  first entry - factored out as `_todays_wind_dir` so the two cannot drift),
  scores the grid through a **new shared function**,
  `bite_view.score_grid_cells`, and writes the result to a new table,
  `HiresGridCache` (`app/core/models.py`), keyed on `(lake_id, for_date)` and
  replaced idempotently rather than appended to.
- `bite_view.score_grid_cells` is the one refactor beyond the sketch: the
  three-factor/v0.3-fallback scoring logic used to live inline in the
  `/lake/{slug}/grid` route. Pulled out so the route and the background job
  call the exact same scoring path - the cache can never disagree with what a
  live request would have computed for the same inputs.
- `/lake/{slug}/grid` gained a `horizon` query param (0 = today, matching the
  day strip's own horizon numbering) and checks the cache first when
  `horizon == 0`; every other horizon, and every lake below the size
  threshold (whose cache is simply never written), falls through to the
  existing on-demand coarse path unchanged. `gridUrl()` in
  `lake_detail.html` now sends `horizon`, kept in sync by the day strip
  *and* by the "recent conditions" weather-table row click - that table lets
  you preview a past day's wind independently of the day strip, and without
  giving those rows their own (negative) horizon the cache would have kept
  answering with today's wind no matter which past row was clicked. Caught
  by re-reading the click handler after the first pass, not by a test.
- Tests: `tests/test_hires_grid_resolution.py` (pure resolution/threshold
  arithmetic), `tests/test_jobs.py` (the new handler - threshold skip,
  waits on outline, waits on today's weather, writes the cache, replaces
  rather than duplicates on a second run), `tests/test_hires_grid_route.py`
  (full app via `TestClient` - today is served from a seeded cache row, a
  forecast horizon never reads it even when a same-lake row exists, a
  below-threshold lake falls back to live scoring). `make check` green: ruff,
  `mypy --strict` on the required packages including the now-larger
  `app/geo` and `app/jobs`, 346/346 tests passing (up from 333).
- **Live-verified on the owner's actual deployment, 2026-08-25, after the
  cloud run pushed this**: pulled the commit, rebuilt the container, ran
  `handle_grid_hires` for real against the real Zalew Zegrzynski outline and
  weather (not a fixture) - `hi-res grid cached for 2026-08-25: 409x412,
  20007 cells at 32.0 m`, matching the predicted resolution exactly.
  `/lake/zalew-zegrzynski/grid?horizon=0` served those same 20 007 cells;
  `?horizon=1` (a forecast day) correctly fell through to the coarse
  4 985-cell on-demand path instead of reading the cache; `/lake/pomocnia/grid`
  (below the 50 ha threshold) was untouched. Container logs confirmed
  APScheduler registered `run_hires_grid_job` for its daily cadence.
- **The pixel-level render was checked, on the owner's real deployment, and it
  was broken — a real bug, not the known "rings not zones" limitation.** The
  owner opened `/lake/zalew-zegrzynski` and the overlay was a garbled
  rectangle bleeding far outside the real shoreline (over farmland, across
  the river) with diagonal streaking bearing no relation to the lake's
  branching shape.
  **Root cause:** `lake_detail.html`'s client JS sizes the heat canvas and
  positions the Leaflet image overlay from the page-load `GRID` constant
  (the coarse interactive grid, computed once when the page rendered) - but
  for `horizon=0` on a qualifying lake, `/lake/{slug}/grid` can answer from
  the daily hi-res cache instead, which carries its **own** `origin_lat` /
  `n_rows` / `n_cols` / `cell_m` at a different resolution
  (409×412 @ 32 m for Zegrzynski vs. the interactive endpoint's coarser
  grid). `loadGrid()` discarded every field but `cells`, so `renderHeat()`
  wrote hi-res row/col indices into a canvas buffer sized for the coarse
  grid - `idx = (y * GRID.n_cols + col) * 4` overflows row-by-row into the
  wrong pixels once `col` exceeds the coarse grid's width, which is exactly
  the diagonal-streak, bled-past-the-shoreline pattern the owner saw.
  **Fixed** in `app/web/templates/lake_detail.html`: `renderHeat()` and the
  image-overlay bounds are now derived from whichever grid metadata the
  `/grid` response actually carries (`gridStep()` / `gridBounds()`, new
  helpers), not the page-load constant; `pickSpot()`'s cell math follows the
  same `activeGrid`, kept in sync by `loadGrid()` on every fetch. Verified by
  reading the invariant this restores (canvas dimensions and cell indices
  now always come from the same grid object, so `idx` can never exceed the
  buffer) and by a standalone reproduction of the old vs. new index math
  outside the app (mismatched dimensions silently drop/scramble cells; matched
  dimensions reproduce the input shape exactly) - not yet re-verified live,
  since this cloud sandbox cannot reach the owner's Tailscale deployment.

  **Merged, redeployed, and re-checked live, 2026-08-25 - confirmed fixed.**
  Pulled the fix branch, ran `make check` clean (346/346, ruff, mypy
  `--strict`), fast-forward merged into `claude/repository-edit-push-ggr229`,
  rebuilt the container. The in-session browser tool's own network blocker
  (the same one that already interfered with `/static/style.css`, `§19a`'s
  handoff) also refused the `/grid` request itself, so the live page couldn't
  be screenshotted directly - worked around it by pulling the exact same JSON
  `/lake/zalew-zegrzynski/grid?horizon=0` returns (409×412, 32 m, 20 007 real
  cells, fetched with `curl`, not a fixture) into a standalone local page
  running the **fixed** `renderHeat()` pixel loop verbatim, and rendering
  that. Result: a clean, correctly-shaped branching-reservoir silhouette,
  smooth colour gradient, no diagonal streaking, no bleed past the shore -
  the same shape `§19a`'s thumbnail traces from the same lake's outline. The
  fix holds against real production data.
- One deliberate scope cut: the hi-res cells are only ever computed for the
  wind direction and phase at ~04:15 UTC. If the wind swings hard later the
  same day, today's cached overlay does not follow it - the interactive
  coarse grid still does, for every water below the size threshold or on any
  other horizon. This is the sketch's own trade (§19c: "not a blocking
  on-demand recompute"), not an oversight, but it means a large water's map
  can go a few hours stale on wind direction specifically, on a day the wind
  actually shifts. Worth a line to the owner if it turns out to matter more
  than expected once Zalew Zegrzynski is used for real.

## 20. Automated bug/UX sweep (site-audit) · DONE, scheduled and triaged — 2026-08-25

Requested after the §19c overlay bug (above) was only caught because the
owner happened to look and screenshot it - the owner asked for an
independent tool that finds this class of thing (dead controls, visual
regressions, accessibility issues) without waiting on a human to notice,
free and lightweight, with a repeatable procedure ("we will use it in the
future").

Researched paid/AI options (Percy, Applitools, testRigor, BugBug, Autify,
Skyvern, Stagehand, browser-use) and rejected all of them for this app: paid
SaaS either costs money past a small free tier or needs the app reachable
from third-party infrastructure (this app is self-hosted behind a Tailscale
funnel by design, `docs/10 §9`); AI browser agents call an LLM on every
navigation decision, which burns credits on every run for a small, fixed
set of pages that don't need rediscovering each time.

**Built:** `tools/site_audit.py` — Playwright (already an undeclared
dependency of four existing tools; now actually in `requirements-dev.txt`)
drives register → home → lake page → pick a spot → start a session → log a
catch → end session in a real browser, and reports:
- **dead controls** - any `<a>`/`<button>` with no href, handler, htmx
  attribute or enclosing form, via an init script that tags every element a
  real `addEventListener` call touches;
- **console/page errors** and **failed (4xx/5xx) requests**, per page;
- **visual diffs** against `tools/baselines/*.png` (committed to the repo,
  same convention as `tools/icon_sheet.py --compare`) via a Pillow pixel
  diff;
- **accessibility violations** (serious/critical only) via `axe-core-python`
  (the real axe-core, vendored by the pip package - no CDN fetch at
  runtime).

No LLM in the loop anywhere in the script itself - every check is
deterministic, so a run costs compute, not credits. Triage (is a finding
actually a bug, judged against CLAUDE.md and the docs rather than taste) is
the separate job of whoever - or whichever session - reads the report; see
the new `site-audit` skill (`.claude/skills/site-audit/SKILL.md`) for that
procedure.

**Caught a real bug on its first real run**, before this item was even
finished: `screenshot_and_diff` hard-timed-out instead of skipping cleanly
when a target was legitimately hidden (the map's own `try/catch` fallback
when the Leaflet CDN can't be reached - which is the normal state *in this
cloud sandbox specifically*, since `unpkg.com` is outside its network
allowlist). Fixed by checking visibility first. Left as a live example, in
this file, of the tool paying for itself immediately.

**Not yet wired to a schedule or a milestone** - deliberately, per the
owner ("we will decide it later"). Runs on request for now
(`/site-audit` or asking for a bug sweep).

**What this cloud sandbox could verify, and what it could not:**
- Verified here: the script runs end-to-end against a fresh local instance
  (throwaway SQLite DB, the seeded Pomocnia lake, no real network needed)
  through registration and the home/lake pages.
- **Not verified: the full flow against a real map.** This sandbox cannot
  reach `unpkg.com` (Leaflet's CDN), so the map never loads here and the
  pick-a-spot → start-session → log-a-catch steps never execute - the
  script degrades to a note rather than crashing, but that is not the same
  as a real pass. **First thing to check on the owner's machine** (or a
  local Claude session there, which has real network both to Leaflet's CDN
  and to the live deployment): run `tools/site_audit.py` against
  `http://127.0.0.1:8090` (a local `make dev`) and then against the real
  Tailscale URL, and read whether it gets all the way through logging a
  catch.
- **The open question is answered and built, 2026-08-25: no, concurrent
  login is not allowed.** `app/auth/service.py`'s `start_auth_session` now
  revokes every existing session for the account before creating the new
  one (reusing `sign_out_everywhere`, the same mechanism the lost-phone
  button already had) - one active session per angler, not one per browser.
  Pinned by `tests/test_auth_routes.py::test_a_new_sign_in_revokes_the_previous_one`.
  Also recorded as a standing rule, `docs/10-SESSION-HANDOVER.md §2` rule 17.
  The trade this makes is deliberate, not an oversight: switching from phone
  to laptop mid-trip signs the phone out - worth a line to the owner if that
  turns out to be annoying in practice, since the alternative (allow several,
  offer a "sign out everywhere" button) is a real design the owner could
  choose instead.

**Scheduled, 2026-08-25: nightly, via the host's own cron, not Claude Code
Remote.** The owner asked for "every day at night," then specifically chose
cron on the machine running the app over a cloud-scheduled Routine, once it
was clear a cloud Routine could only ever repeat the degraded smoke-test
path - this cloud sandbox cannot reach either `unpkg.com` or the real
deployment (confirmed: the outbound proxy returns a policy 403 for the
Tailscale host), and a Routine fired into this same environment would face
the identical restriction. Cron on the real machine has real network to the
real app for free, with no new infrastructure.

A second issue surfaced while designing this, before it ever ran against
production: the tool's full flow (register → session → log a catch) writes
real rows. Run nightly against a real database forever, that is a fake
angler's fake catch fabricated into the real notebook every night - exactly
what CLAUDE.md law 3 forbids. Fixed by splitting `tools/site_audit.py`:
`audit_public_pages()` (dead controls, console/network errors, a11y, visual
diffs on the public home/lake pages - nothing writes) and
`audit_authenticated_flow()` (the writing part), selected by a new
`--public-only` flag. The nightly job always passes `--public-only`; the
full flow stays on-demand, against a throwaway database only.

**Built:** `tools/nightly_audit.sh` - checks the working tree is clean
before syncing to the branch tip (never discards uncommitted work), runs
`site_audit.py --public-only` against `http://127.0.0.1:8000` (localhost,
not the Tailscale funnel - the script runs on the same machine as the
container, so there's no reason to round-trip through the funnel), and
only when it finds something: writes `reports/site_audit/<date>.md`,
commits and pushes it to `claude/repository-edit-push-ggr229`, with one
retry after resyncing if the push races another writer. A clean night
writes and commits nothing - the repo's history only ever shows nights that
found something, per the owner's chosen delivery mechanism (commit the
report to git, not a local-only log file).

**Scheduled for real, 2026-08-25 - but not via crontab.** The owner's
machine is Windows (Git Bash/MSYS), not Linux - no `crontab` exists there at
all. Used **Windows Task Scheduler** instead, the direct equivalent: task
`FishlogNightlyAudit`, daily at 02:00, running
`C:\Users\...\run_fishlog_audit.bat` -> Git Bash -> `tools/nightly_audit.sh`,
logging to a plain file in the owner's home directory. Verified twice: once
run by hand, once triggered through the actual Task Scheduler mechanism
(`schtasks /Run`) to prove the unattended path itself works, not just the
script in isolation.

Two real bugs found on that first live run, both fixed:
1. `nightly_audit.sh` hardcoded `.venv/bin/python` (Linux venv layout) -
   detects `Scripts/` vs `bin/` now instead of assuming.
2. The script only ever `git add`s the report, not a newly-written baseline
   image - so the very first run against any page with no baseline yet
   leaves the tree dirty and the script's own safety guard would refuse
   every run after it. Committed the missing `lake.png` baseline by hand to
   unblock tonight; the script itself should probably `git add
   tools/baselines/*.png` too, so a newly-added page can't wedge the job
   later without a human noticing.

**First real findings, triaged and closed, 2026-08-25:**
- `meta-viewport` critical violation - already fixed in an earlier commit
  (`76fad88`), just never redeployed. Rebuilding the container was the whole
  fix.
- Color-contrast, serious, on every *interactive* low-contrast element
  flagged (language switcher, sign-in, the water-type filter tabs): real
  WCAG AA failures, confirmed by computing the actual contrast ratio
  (`--muted` #6c8299 on `--surface-alt` is 3.5:1, needs 4.5:1). Fixed with a
  new `--muted-strong` token (#4a5f75, ~5.9:1) - same naming pattern as the
  existing `--primary-strong`/`--danger-strong`, same muted slate-blue
  family, just legible. Rendered and looked at the result (the audit tool's
  own fresh screenshot) before calling it done, per `CLAUDE.md`'s
  verification rule.
- Home-page 5.8% visual diff: **not a bug** - two real lakes had been added
  to the live database since the baseline was captured (see below).
  Baselines refreshed to the current, real state.

**Left open, deliberately - a design decision, not a bug fix:** the same
color-contrast failure exists on ~40 more `--muted` usages across the
stylesheet - section headers, secondary metadata text, table headers. All
non-interactive (informational text, not controls). Fixing every one is a
stylesheet-wide contrast pass that trades against the pastel/soft aesthetic
`CLAUDE.md` rule 8 asks for, so it wasn't done unilaterally at the tail end
of a long session. The owner's call: raise contrast everywhere `--muted`
appears, or accept the softer look for non-interactive text and only fix
what's flagged going forward.

**A more important finding than any of the above:** the visual diff and the
new lakes on the home page turned out not to be test data at all. A real
second user (`tsaranhelina5@gmail.com`, "Anhelina", registered
2026-08-24 20:33) has been using the app for real - added a real water
("Glinianki Szczęśliwickie") and started two fishing sessions, neither of
which was ever ended. The owner's own account separately added a second new
water ("Łowisko Poniaty - Pod Lasem", 0.01 ha) the same morning. None of
this was documented anywhere before this session found it while
investigating why the visual-diff check fired. Nothing here was touched -
it is real user data.
