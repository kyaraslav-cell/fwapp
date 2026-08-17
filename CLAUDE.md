# CLAUDE.md — working rules for this repository

You are building **Fishlog**: a 24/7 web application that ingests weather for a lake,
derives limnological features, ranks fishing zones, and learns from a logged fishing
notebook.

Read `docs/01-SPEC.md` before your first change. Read `docs/08-DEV-WORKFLOW.md` before
opening a pull request.

**Starting a new session? Read [`docs/10-SESSION-HANDOVER.md`](docs/10-SESSION-HANDOVER.md)
first.** It carries the standing rules the owner gave in conversation (which are not
in this file), what is already built, what is known broken, and two hard-won
verification rules. Outstanding requests are in
[`docs/09-BACKLOG.md`](docs/09-BACKLOG.md).

## Verification rules — these cost real rework

- **Motion cannot be checked from a screenshot, or by reading your own keyframes.**
  The fish-pin dive shipped three times diving *tail first*. Use
  `tools/animation_filmstrip.py`.
- **Visual design cannot be checked from your own diff.** The species icons were
  declared "redrawn" three times and still looked identical. Render the result and
  compare old against new **side by side** before saying a change landed, and put
  the comparison in front of the owner rather than describing it.

### Species icons: no shared assets

An icon set where every fish is the same drawing in another colour is worth less
than no icons at all — it costs a tap to read and teaches the angler nothing. So:

- **Every species owns its geometry.** Body outline, tail, dorsal fin, anal fin
  and head are drawn per species. Not one path recoloured, not one path rescaled,
  not one path with a different gradient.
- **The tail alone must identify the fish** with the body hidden. A crucian's tail
  is a rounded fan, a bream's is a long unequal fork, a carp's is broad and
  shallow. If two species share a tail wedge, the set has failed.
- **Curved forms only.** Organic bezier outlines. No polygon fins, no triangles
  standing in for a tail.
- **Silhouette carries the recognition, not detail.** These render at ~24 device
  pixels tall. Scales, spots and barbels are garnish; body depth, back curvature,
  fin placement and tail shape are the whole signal.
- **Verify by rendering.** `tools/icon_sheet.py` draws the real sprite through the
  real stylesheet, and `--compare` puts the previous set beside it.

`tests/test_species_seed.py` asserts the six quick-log species never collapse onto
a shared shape key. That test only catches the wiring, not the drawing — the
drawing is checked by looking.

For anything visual or temporal: produce the artefact and look at it. A green test
suite says nothing about whether a fish is upside down.

---

## The five laws

These exist because breaking any one of them silently destroys the value of the
project. They are not style preferences.

### 1. No fishing knowledge in code. Ever.

Every angling heuristic, threshold, coefficient and weight lives in
`config/rules.v*.yaml`. Code evaluates rules; it does not contain them.

```python
# FORBIDDEN
if pressure_delta_6h < -4:
    score += 0.3

# REQUIRED
score += ruleset.evaluate("pressure_trend", features)
```

If you find yourself typing a number that came from fishing intuition rather than
physics or arithmetic, stop — it belongs in the YAML.

Physical constants (water heat capacity, gravity, Earth radius) are fine in code.
Fishing thresholds are not.

### 2. The prediction is written before the session, never after.

`prediction` rows are immutable once created and are stamped with `ruleset_version`
and `inputs_hash`. A prediction may never be regenerated for a past date and
overwritten. If the ruleset changes, generate a *new* prediction row under the new
version; keep the old one.

This is the entire basis of the calibration loop. Overwrite a prediction and you have
destroyed the evidence that the app was wrong.

### 3. CPUE, never catch count.

The unit of success is **fish per hour**, computed from logged effort. Any query,
statistic, chart or ranking that uses raw catch counts is a bug.

Corollary: **blank sessions are data.** A session with zero catches must be as easy to
record as a good one, must be included in every statistic, and must never be filtered
out of an aggregate.

### 4. Never fabricate an observation.

If a weather fetch fails, write nothing and log the gap. Do not interpolate, do not
carry the last value forward into the observations table, do not substitute a
forecast for a measurement.

Derived features may be interpolated — but only in the `derived_*` tables, and only
with `is_interpolated = 1` set.

The `weather_hourly` table is a record of what was actually published. Keep it clean.

### 5. Sample size travels with every number.

No score, ranking or recommendation is ever rendered without its supporting `n`
and a confidence band. A zone scored from three sessions and a zone scored from
ninety must not look alike in the UI.

---

## Domain facts you must not re-derive

The target water, Jezioro Pomocnia, is **9 ha** — roughly 340 m across.

- **There is exactly one weather series for the whole lake.** No weather model or
  station resolves anything smaller than the entire water body. Do not build
  per-zone *weather*. Build per-zone *response to weather*, computed from geometry.
- **Mean depth is under 3 m.** Any depth recommendation must be clamped to the depth
  actually available in the target zone. Where the requested band does not exist,
  fall back to distance-to-weed-edge.
- **Season is April–October.** No ice mode. Do not build one.
- **Thermal phase is derived from modelled water temperature and its trend, never
  from calendar date.** A cold May and a warm April swap places regularly.

## Species scope

Primary: **roach, bream, rudd, ide** (cyprinids, bank-fished).
Secondary, because they dominate this water: **carp, crucian carp**.
Out of scope for scoring: pike, perch, catfish, eel — log them, do not score them.

## Awaiting input — do not invent these

Two formulas are supplied by the project owner and are **not yet delivered**:

| Slot | Purpose | Status |
|---|---|---|
| `FORMULA_PRESSURE_DEPTH` | pressure state → target depth band per species | **PENDING** |
| `FORMULA_WIND_ZONE` | wind vector × geometry → zone preference | **PENDING** |

Their placeholders are in `config/rules.v1.yaml`. **Do not guess at them.** If a task
requires them, build the surrounding machinery, wire the slot, and leave the
evaluator raising `FormulaNotSuppliedError`. Write the tests against a fixture
formula in `tests/fixtures/`, clearly marked as fake.

## Stack — do not substitute

Python 3.12 · FastAPI · SQLite (WAL) · SQLAlchemy · APScheduler · Jinja2 + HTMX ·
Leaflet · shapely + pyproj · pytest. One Docker container. No Node build step, no
SPA framework, no external message queue, no separate database server.

If you believe a dependency is needed, add it to `docs/adr/` as a decision record
with the justification first.

## Style

- Type hints everywhere. `mypy --strict` on `app/core/` and `app/rules/`.
- Pure functions in `app/rules/` and `app/features/` — no I/O, no clock reads.
  Time is always passed in. This is what makes the engine testable and back-testable.
- All timestamps stored UTC. Display in `Europe/Warsaw`.
- All distances metres, temperatures Celsius, pressure hPa, bearings degrees true.
- Migrations are forward-only and numbered.
