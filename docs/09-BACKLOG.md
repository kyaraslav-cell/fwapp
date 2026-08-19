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
ADR 0005. **Never run against Gemini** — no key and no network here.

**Not built yet, in the order they matter:**

1. **Rivers.** Beat boundaries are findable, but flow is not modelled at all.
2. **Raster auto-tracing** for waters OSM has no polygon for. Deliberately
   deferred until the named-water path shows how often it is actually needed;
   it needs numpy and a GeoTIFF reader, so it gets its own ADR.
3. **A live run.** Nothing here has ever reached Nominatim, Overpass or
   Gemini — the
   sandbox has no outbound network. The pipeline was driven end to end against
   a stubbed geocoder and a real queue; the first true search will be on the
   owner's machine, and `docs/13 §8` is the table of what should happen when
   each part fails.

