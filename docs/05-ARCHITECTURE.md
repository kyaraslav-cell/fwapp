# 05 — Architecture

## Selection principle

Optimised for **never having to babysit it**. This is a solo project that must run 24/7
without an operator. Every dependency is a thing that can break at 3 a.m. while the
owner is at work.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | the feature/limnology maths is natural here |
| Web | FastAPI | async ingest, simple, well documented |
| DB | **SQLite** (WAL) | one file. No server to maintain. Backup = copy the file. Handles this volume for decades |
| ORM | SQLAlchemy 2.x | migrations, typed |
| Scheduler | **APScheduler in-process** | no external cron, no second moving part |
| Templates | Jinja2 + **HTMX** | interactivity without a build pipeline |
| Map | **Leaflet** + Esri World Imagery | satellite basemap, free tiles, GeoJSON native |
| Geometry | shapely + pyproj | bearings, ray-cast fetch, areas |
| Solar | `pvlib` or `astral` | exact solar azimuth/elevation |
| Tests | pytest + hypothesis | |
| Deploy | one Docker container | |

**No Node build step. No SPA framework. No message queue. No separate database
server.** This single set of refusals removes most of the operational burden.

Adding a dependency requires an ADR in `docs/adr/` justifying it first.

## Module layout

```
app/
  ingest/          open_meteo.py, metar.py, backfill.py, scheduler.py
  geo/             osm_lookup.py, outline.py, bearings.py, fetch.py, solar.py
  features/        pressure.py, water_temp.py, thermal_phase.py, zone_conditions.py
  rules/           loader.py, expressions.py, evaluator.py, registry.py
  predict/         daily.py, outlook.py
  notebook/        sessions.py, catches.py, annotations.py
  calibrate/       metrics.py, backtest.py, proposals.py
  web/             routes/, templates/, static/
  core/            db.py, models.py, config.py, time.py
migrations/
config/
tests/
```

**`app/features/` and `app/rules/` are pure.** No database access, no `datetime.now()`.
Time and data are passed in. This is not fastidiousness — it is the only way
back-testing a candidate ruleset over five past seasons is possible.

## Scheduled jobs

| Job | Cadence | Notes |
|---|---|---|
| `fetch_openmeteo_forecast` | hourly | 16-day horizon |
| `fetch_metar` | hourly | EPMO ground truth |
| `reconcile_archive` | daily 03:00 | replace forecast rows with archive actuals |
| `compute_features` | hourly, after ingest | lake-level then per-zone |
| `generate_prediction` | daily 04:00 | today + 7-day outlook; **writes immutable rows** |
| `calibration_run` | weekly | metrics + weight proposals |
| `backup` | daily | copy SQLite file, keep 30 days |

All jobs are idempotent and re-runnable. Failures write `ingest_gap` rows and alert;
they never write fabricated observations.

## The lake auto-resolve pipeline

Generic, so it scales to any lake added later:

1. Type a lake name → geocode (Nominatim) → candidate list with coordinates
2. Pull the water polygon from OpenStreetMap (Overpass) → GeoJSON outline
3. **Auto-derive**: centroid, area, bounding box; shoreline segmented into ~25 m
   pieces, each with outward normal bearing; fetch per 16 sectors by ray-casting
   across the polygon
4. **Auto-attach weather**: Open-Meteo grid point at centroid; nearest METAR station
   lookup
5. Render on Leaflet over satellite tiles; owner draws zones and marks swims

Steps 1–4 need no human input. Step 5 is roughly ten minutes per lake.

**Caveat, must be handled:** OSM outlines for small Polish lakes exist but are
sometimes crude. A manual "nudge the outline" editor is required, not optional.

**Caveat, must be respected:** Nominatim and Overpass have strict usage policies.
Cache aggressively, set a real `User-Agent`, rate-limit to 1 req/s, and never call
them from a request handler — resolution is a one-time background job per lake.

## Verification status of external APIs

Not yet live-tested from the design session. **First build task is a spike** that
confirms, for Pomocnia's coordinates:

- Open-Meteo forecast endpoint returns hourly data for all required variables
- Open-Meteo ERA5 archive returns history back at least 10 years
- Overpass returns a usable water polygon near 52.5431, 20.6762
- A METAR source for EPMO is reachable and parseable

If any fails, the ADR records the fallback before code is written against it.

## Deployment

Single container, single volume for the SQLite file and backups. A €4–5/month VPS,
or a free tier on Fly.io / Railway. Healthcheck endpoint exposing last successful
ingest time — if ingest silently dies, the app must say so loudly rather than serving
stale predictions as if they were current.

## Multi-lake and multi-user

`lake_id` is on every table from day one. Multi-lake requires only UI work.
Multi-user would require an auth layer and a `user_id` column — deliberately deferred,
but nothing in the schema blocks it.
