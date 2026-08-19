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

**v0 MVP is running code.** Single lake (Pomocnia, hardcoded), weather ingest,
a deliberately narrow rules engine, and the full session-logging notebook.

v0 scores day quality from **only** `pressure_trend` and `light_window` — the
two v1 rules that need neither a zone (none are mapped yet) nor a pending
formula. `FORMULA_PRESSURE_DEPTH` and `FORMULA_WIND_ZONE` are still owed by
the project owner and nothing in v0 guesses at them — see
[`docs/04-RULES-ENGINE.md`](docs/04-RULES-ENGINE.md) and
[`config/rules.v0.yaml`](config/rules.v0.yaml). Zones, the satellite map, the
water-temperature model and oxygen proxy are deferred; `rules.v1.yaml` stays
the target to grow into once those inputs exist.

## Getting started

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
make check          # ruff + mypy --strict + pytest
make dev            # http://localhost:8000, auto-reload
```

Or with Docker:

```bash
docker compose up --build
```

### Keys, and checking that they work

Optional features (the Gemini local-knowledge pass, sign in with Google) are
switched on by environment variables. Copy `.env.example` to `.env` — which is
gitignored, and is the only place a real key belongs — and fill in what you
have. Both `make dev` and `docker compose` read it; a variable already set in
your shell always wins over the file.

```bash
cp .env.example .env
make preflight        # calls every external service and says which one refused
```

`make preflight` is worth running once on any new machine. Everything this app
talks to — Nominatim, Overpass, Open-Meteo, Google, Gemini — is unreachable
from the sandbox it was built in, so those clients are unverified until this
passes somewhere with a network. It never prints a key and writes nothing.

Open `http://localhost:8000`. On first boot the app seeds the Pomocnia lake
row from `config/lakes/pomocnia.yaml`, fetches Open-Meteo forecast data, and
generates today's + a 7-day prediction. A failed weather fetch never
fabricates data — it writes an `ingest_gap` row and the day score falls back
to the light-window component alone (see Law 4 in `CLAUDE.md`).

## Stack

Python 3.12 · FastAPI · SQLite · SQLAlchemy · APScheduler · Jinja2 + HTMX · Leaflet ·
shapely · pytest. One Docker container. No Node build step, no SPA, no database server.

## Data sources

- **Open-Meteo** — primary. Grid point at the lake. ERA5 archive + 16-day forecast. Free, keyless.
- **METAR EPMO (Modlin, 10.4 km)** — independent ground truth.
- **OpenStreetMap / Overpass** — lake outline for the geometry pipeline.

Lake facts sourced from [PZW Koło nr 5](https://kolo5.ompzw.pl/artykul/jezioro-pomocnia)
and [Fishsurfing](https://www.fishsurfing.com/pl/map/jezioro-pomocnia-1770494874/).
