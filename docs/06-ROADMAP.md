# 06 — Roadmap

> *"If I had six hours to chop down a tree, I'd spend four sharpening the axe."*

Phase 0 is the sharpening. It produces no running software and it is the phase most
projects skip and always regret.

**The critical sequencing decision: the notebook ships before the prediction engine.**
Weather history can be backfilled instantly at any point in the future. Fishing
sessions cannot. Every week without logging is data permanently lost. Building the
scoring engine first is tempting because it is the fun part — but a prediction engine
with nothing to check it against is just an opinion with extra steps.

---

## Phase 0 — Sharpen the axe *(design only, no application code)*

**These are the irreversible decisions.** Get the session-log schema wrong and every
session recorded before the fix is wasted data.

- [ ] API spike: verify Open-Meteo forecast + ERA5 archive, Overpass polygon, EPMO METAR
- [ ] Confirm lake outline for Pomocnia is usable, or plan the manual editor
- [ ] Owner defines zones on a satellite map — including **bank aspect** and **tree
      line**, the two everyone forgets
- [ ] Lock the session-log schema
- [ ] Lock the ruleset YAML format and the feature registry
- [ ] **Receive the two formulas** from the owner, with units, species coefficients,
      provenance and valid range; record in an ADR
- [ ] ADRs for: SQLite, Open-Meteo primary + METAR secondary, no-ML decision

**Exit criteria:** schema frozen, formats agreed, external APIs proven reachable.

---

## Phase 1 — Data spine

- [ ] Repo skeleton, Docker, migrations, CI
- [ ] Lake auto-resolve pipeline (geocode → polygon → bearings → fetch sectors)
- [ ] Open-Meteo forecast + archive ingest
- [ ] METAR ingest for EPMO
- [ ] APScheduler jobs + `ingest_gap` handling + healthcheck
- [ ] **Backfill 10 years of ERA5 history for Pomocnia**

**Exit criteria:** a decade of hourly weather in the database, updating hourly,
unattended, with gaps visible. Immediate value: last season's conditions are already
queryable — no waiting a year.

---

## Phase 2 — The notebook *(highest priority; ship as early as physically possible)*

- [ ] Leaflet map with satellite basemap, lake outline, zone polygons, swim pins
- [ ] Free-draw annotation layer stored as **GeoJSON, not images**
- [ ] Zone attribute editor (depth, bottom, weed, reed, aspect, tree line)
- [ ] Session logging: Start → catches → End, under 60 seconds
- [ ] `session_leg` support for mobile bank sessions
- [ ] **One-tap blank session**
- [ ] Water temperature + clarity fields
- [ ] Auto-snapshot conditions at session start
- [ ] PWA: installable, offline-capable logging, background sync
- [ ] Basic history browser

**Exit criteria:** the owner logs a real session on his phone, at the lake, with no
signal, in under a minute. **Until this is true, nothing else matters.**

---

## Phase 3 — Feature engine

- [ ] Pressure derivatives + regime classification
- [ ] Water temperature model, spun up from archive
- [ ] Thermal phase state machine with hysteresis
- [ ] Solar position, per-zone shading, sun hours
- [ ] Per-zone wind exposure, effective fetch, wave and mixing energy
- [ ] Margin temperature offset
- [ ] Oxygen proxy *(flagged as hypothesis)*
- [ ] Feature registry + ruleset validation against it

**Exit criteria:** every feature in `docs/02-DOMAIN.md` computed hourly for every
zone, for both history and forecast, with golden tests on fixture weather.

---

## Phase 4 — Scoring and daily output

- [ ] Safe expression evaluator (restricted AST — never `eval`)
- [ ] Ruleset loader, versioning, activation
- [ ] Wire `FORMULA_PRESSURE_DEPTH` and `FORMULA_WIND_ZONE`
- [ ] Depth-band clamping + weed-edge fallback
- [ ] Day score, hour curve, ranked zones with reason strings and confidence
- [ ] Immutable prediction writer
- [ ] Dashboard: today's answer
- [ ] 7-day outlook

**Exit criteria:** every morning at 04:00 an immutable prediction exists for today and
the next seven days, each zone score carrying its sample size.

---

## Phase 5 — The loop

- [ ] Statistics: CPUE by zone, by phase, by condition bucket, by bait
- [ ] Coverage view — hours per zone, under-sampled zones flagged
- [ ] **Exploration nudge** — proposes sessions in thin zones
- [ ] Prediction vs outcome: rank correlation, per-rule hit rate
- [ ] Back-test harness: replay past seasons under a candidate ruleset
- [ ] Weight proposals surfaced for approval, **never auto-applied**
- [ ] Ruleset v2 authored from real evidence

**Exit criteria:** the owner can answer "is this app actually better than my
intuition?" with a number and a confidence interval — and has changed or killed at
least one rule on the evidence of his own data.

---

## Phase 6 — Polish

- [ ] Push notifications for high-scoring days
- [ ] Season summary
- [ ] Export
- [ ] Second lake, to prove the multi-lake path

---

## Sequencing constraints

```
Phase 0 ──► Phase 1 ──► Phase 3 ──► Phase 4 ──► Phase 5
       └──► Phase 2 ─────────────────────┘
```

Phase 2 runs in **parallel** with 1 and 3 and must not wait for them. It is the
long-lead item: it generates the asset that Phase 5 consumes, and that asset
accumulates only in real time.
