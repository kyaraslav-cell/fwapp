# ADR 0001 — Foundational decisions

Status: **accepted** · Date: 2026-08-13

Decisions taken during the design session, recorded so they are not relitigated.

---

## 1. SQLite, not Postgres

One file. No server process. Backup is a file copy. Data volume — one lake, hourly
weather, a decade of history, a few hundred sessions a year — is trivial for SQLite
for the foreseeable life of the project.

*Revisit if:* multi-user is ever built, or concurrent writers appear.

## 2. Open-Meteo primary, METAR (EPMO) secondary

Open-Meteo provides a grid point at the lake's own coordinates, hourly, with ERA5
archive going back decades **and** a 16-day forecast, free and keyless. No station
provides both history depth and forecast.

Modlin / EPMO is 10.4 km away and publishes real measurements roughly half-hourly.
Warszawa-Okęcie, the nearest full synoptic station, is 46.4 km away — useless for wind
at this lake.

Both are stored. This allows measuring and correcting model bias at this specific
water, which is better than either source alone.

## 3. No machine learning in v1

30–60 sessions per year. Any model on that sample memorises noise and explains
nothing. A transparent versioned rule set with human-approved weight changes is the
correct tool at this sample size, and it teaches the owner something.

*Revisit if:* several thousand sessions ever accumulate. They will not.

## 4. One weather series per lake; all spatial variation from geometry

Jezioro Pomocnia is 9 ha, roughly 340 m across. No weather model grid or station
resolves below the whole lake. Per-zone *weather* is therefore meaningless; per-zone
*response to weather* — computed from bearing, fetch, aspect, shading, weed density
and sun position — is the only available mechanism, and is sufficient.

## 5. Thermal phase is a state derived from water temperature, not a calendar date

A cold May and a warm April swap places regularly. Wind is a negative in spring
(it mixes away the warm margin) and a positive in summer (mixing is life). Getting
this from the calendar would invert the sign of a major rule in a bad year.

## 6. Predictions are immutable

Stamped with ruleset version and inputs hash, written before the session, never
regenerated over a past date. This is the entire basis of honest calibration.

## 7. Notebook ships before the scoring engine

Weather history backfills instantly at any time. Fishing sessions accumulate only in
real time and cannot be recovered. Delay in shipping logging is permanent data loss.

## 8. Priority order revised from the original brief

The original brief named wind, temperature and pressure as the three analysed
variables. After examining the lake, the operative order is:

1. Modelled water temperature and trend (sets thermal phase)
2. Per-zone wind exposure (the only true spatial discriminator)
3. Oxygen proxy (likely dominant on a shallow, silted, weedy lake in summer)
4. Pressure trend (modulator, and input to the depth formula)

Pressure is a modulator, not the headline. The original three become inputs rather
than outputs.

## 9. Free-draw annotations stored as GeoJSON, never as images

Painted strokes cannot be aggregated or queried. GeoJSON supports "show every session
within 20 m of this point" years later. The structured layer drives statistics; the
free-draw layer carries human memory. Two layers, one map.

---

## Pending — awaiting the project owner

- `FORMULA_PRESSURE_DEPTH` — pressure state → target depth band per species
- `FORMULA_WIND_ZONE` — wind vector × geometry → zone preference

Each to be recorded in its own ADR on arrival, with inputs, units, expression,
output, species coefficients, provenance and valid range. Provenance determines how
aggressively calibration may override them.
