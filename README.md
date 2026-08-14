# Fishlog

A 24/7 web application that watches the weather over one small lake, works out what
that weather does to the water in each part of that lake, says where and when to fish,
and then checks itself against what was actually caught.

Target water: **Jezioro Pomocnia** (52.5431 N, 20.6762 E) — 9 ha, mean depth under 3 m,
near Pomiechówek, Mazowieckie. Target fish: roach, bream, rudd, ide. Season April–October.

---

## Read in this order

| Doc | What it settles |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **The five laws.** Read first. Breaking any one silently destroys the project. |
| [`docs/01-SPEC.md`](docs/01-SPEC.md) | What this is, who it's for, what it will honestly not do |
| [`docs/02-DOMAIN.md`](docs/02-DOMAIN.md) | **The conceptual core** — how one weather series becomes a place to fish |
| [`docs/03-DATA-MODEL.md`](docs/03-DATA-MODEL.md) | SQLite schema |
| [`docs/04-RULES-ENGINE.md`](docs/04-RULES-ENGINE.md) | Declarative rule format, the two pending formula slots |
| [`docs/05-ARCHITECTURE.md`](docs/05-ARCHITECTURE.md) | Stack, modules, scheduled jobs, lake auto-resolve |
| [`docs/06-ROADMAP.md`](docs/06-ROADMAP.md) | Phases 0–6 with acceptance criteria |
| [`docs/07-UI-SPEC.md`](docs/07-UI-SPEC.md) | Screens, and why logging ergonomics is the highest-risk item |
| [`docs/08-DEV-WORKFLOW.md`](docs/08-DEV-WORKFLOW.md) | How to work in this repo |
| [`docs/adr/`](docs/adr/) | Decisions already made — don't relitigate them |

## The one-paragraph version

Weather is measured once for the whole lake — at 340 m across, no model or station
resolves anything smaller. All spatial differentiation therefore comes from
**geometry × sun position × zone attributes**: bearing versus wind direction, fetch
ray-cast across the polygon, shading from bank aspect and tree line, weed density
driving an oxygen proxy. Those feed a **declarative, versioned rule set** whose
weights switch on a **thermal phase** derived from modelled water temperature — because
wind is a negative in April and a positive in July, in the same zone. Every prediction
is written down before the session and never rewritten, so that a season later the
logbook can say whether the app was right.

## Current status

**Phase 0 — sharpening the axe.** No application code yet, deliberately.

Blocking item: two formulas pending from the project owner —
`FORMULA_PRESSURE_DEPTH` and `FORMULA_WIND_ZONE`. Do not guess at them.
See [`docs/04-RULES-ENGINE.md`](docs/04-RULES-ENGINE.md).

## Stack

Python 3.12 · FastAPI · SQLite · SQLAlchemy · APScheduler · Jinja2 + HTMX · Leaflet ·
shapely · pytest. One Docker container. No Node build step, no SPA, no database server.

## Data sources

- **Open-Meteo** — primary. Grid point at the lake. ERA5 archive + 16-day forecast. Free, keyless.
- **METAR EPMO (Modlin, 10.4 km)** — independent ground truth.
- **OpenStreetMap / Overpass** — lake outline for the geometry pipeline.

Lake facts sourced from [PZW Koło nr 5](https://kolo5.ompzw.pl/artykul/jezioro-pomocnia)
and [Fishsurfing](https://www.fishsurfing.com/pl/map/jezioro-pomocnia-1770494874/).
