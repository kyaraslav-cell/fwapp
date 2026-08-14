# 03 — Data model (SQLite)

Forward-only numbered migrations in `migrations/`. WAL mode. All timestamps UTC.
`lake_id` is present on every relevant table from day one — the multi-lake insurance
policy, paid for at the cheapest possible moment.

---

## Lake and geometry

```sql
CREATE TABLE lake (
  id                INTEGER PRIMARY KEY,
  slug              TEXT UNIQUE NOT NULL,          -- 'pomocnia'
  name              TEXT NOT NULL,                 -- 'Jezioro Pomocnia'
  centroid_lat      REAL NOT NULL,
  centroid_lon      REAL NOT NULL,
  area_ha           REAL,
  mean_depth_m      REAL,
  max_depth_m       REAL,
  outline_geojson   TEXT,                          -- Polygon, WGS84
  osm_id            TEXT,
  timezone          TEXT NOT NULL DEFAULT 'Europe/Warsaw',
  metar_station     TEXT,                          -- 'EPMO'
  metar_distance_km REAL,
  config_yaml       TEXT,                          -- water-temp model coefficients etc.
  created_at        TEXT NOT NULL
);

CREATE TABLE zone (
  id                 INTEGER PRIMARY KEY,
  lake_id            INTEGER NOT NULL REFERENCES lake(id),
  name               TEXT NOT NULL,
  polygon_geojson    TEXT NOT NULL,
  mean_depth_m       REAL,
  max_depth_m        REAL,
  bottom_type        TEXT,        -- silt|sand|gravel|clay|mixed
  weed_density       INTEGER,     -- 0..3
  weed_species       TEXT,        -- 'grazel,rogatek,moczarka'
  reed_pct           REAL,
  bank_aspect_deg    REAL,        -- outward normal, degrees true
  tree_line_height_m REAL,
  tree_side          TEXT,        -- N|NE|E|SE|S|SW|W|NW|none
  fetch_by_sector    TEXT,        -- JSON: 16 sectors -> metres, auto-derived
  access_notes       TEXT,
  is_active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE swim (
  id                    INTEGER PRIMARY KEY,
  zone_id               INTEGER NOT NULL REFERENCES zone(id),
  name                  TEXT NOT NULL,
  point_lat             REAL NOT NULL,
  point_lon             REAL NOT NULL,
  depth_at_rod_m        REAL,
  distance_to_weed_m    REAL,
  distance_to_reed_m    REAL,
  notes                 TEXT
);

-- free-draw layer: sketches, weed edges, "where I fed", observations
CREATE TABLE annotation (
  id          INTEGER PRIMARY KEY,
  lake_id     INTEGER NOT NULL REFERENCES lake(id),
  kind        TEXT NOT NULL,      -- drawing|note|observation
  geojson     TEXT NOT NULL,      -- stored as geodata, NOT as an image
  label       TEXT,
  colour      TEXT,
  season_year INTEGER,
  created_at  TEXT NOT NULL
);
```

Annotations are **GeoJSON, never a rasterised painting.** That is what allows "show me
every session logged within 20 m of this point" three years from now.

---

## Weather

```sql
CREATE TABLE weather_hourly (
  id            INTEGER PRIMARY KEY,
  lake_id       INTEGER NOT NULL REFERENCES lake(id),
  source        TEXT NOT NULL,        -- openmeteo_archive|openmeteo_forecast|metar
  ts_utc        TEXT NOT NULL,
  is_forecast   INTEGER NOT NULL DEFAULT 0,
  model_run     TEXT,
  temperature_2m       REAL,
  dewpoint_2m          REAL,
  relative_humidity_2m REAL,
  pressure_msl         REAL,
  wind_speed_10m       REAL,
  wind_direction_10m   REAL,
  wind_gusts_10m       REAL,
  cloud_cover          REAL,
  shortwave_radiation  REAL,
  precipitation        REAL,
  fetched_at    TEXT NOT NULL,
  UNIQUE(lake_id, source, ts_utc, is_forecast)
);

CREATE TABLE ingest_gap (
  id         INTEGER PRIMARY KEY,
  lake_id    INTEGER NOT NULL,
  source     TEXT NOT NULL,
  from_utc   TEXT NOT NULL,
  to_utc     TEXT NOT NULL,
  reason     TEXT,
  resolved   INTEGER NOT NULL DEFAULT 0
);
```

**A failed fetch writes an `ingest_gap` row and nothing else.** Never interpolate into
`weather_hourly`; it is a record of what was actually published.

---

## Derived features

```sql
CREATE TABLE derived_hourly (
  id       INTEGER PRIMARY KEY,
  lake_id  INTEGER NOT NULL,
  ts_utc   TEXT NOT NULL,
  is_forecast INTEGER NOT NULL DEFAULT 0,
  dp_3h REAL, dp_6h REAL, dp_9h REAL, dp_12h REAL, dp_24h REAL,
  pressure_stability_48h REAL,
  pressure_regime        TEXT,
  hours_since_regime_change REAL,
  water_temp_bulk_c      REAL,
  water_temp_trend_24h   REAL,
  water_temp_trend_72h   REAL,
  degree_days_above_10c  REAL,
  thermal_phase          TEXT,
  solar_elevation_deg    REAL,
  solar_azimuth_deg      REAL,
  is_interpolated        INTEGER NOT NULL DEFAULT 0,
  features_version       TEXT NOT NULL,
  UNIQUE(lake_id, ts_utc, is_forecast, features_version)
);

CREATE TABLE zone_conditions_hourly (
  id       INTEGER PRIMARY KEY,
  zone_id  INTEGER NOT NULL REFERENCES zone(id),
  ts_utc   TEXT NOT NULL,
  is_forecast INTEGER NOT NULL DEFAULT 0,
  wind_exposure       REAL,   -- -1..+1
  effective_fetch_m   REAL,
  wave_energy         REAL,
  mixing_energy       REAL,
  shade_fraction      REAL,
  insolation_received REAL,
  sun_hours_today     REAL,
  margin_temp_offset_c REAL,
  o2_proxy            REAL,
  features_version    TEXT NOT NULL,
  UNIQUE(zone_id, ts_utc, is_forecast, features_version)
);
```

---

## Rules and predictions

```sql
CREATE TABLE ruleset (
  version      TEXT PRIMARY KEY,     -- 'v1', 'v2'...
  yaml         TEXT NOT NULL,
  parent       TEXT,
  note         TEXT,
  activated_at TEXT,
  created_at   TEXT NOT NULL
);

CREATE TABLE prediction (
  id               INTEGER PRIMARY KEY,
  lake_id          INTEGER NOT NULL,
  target_date      TEXT NOT NULL,
  horizon_days     INTEGER NOT NULL,   -- 0 = today, 1..16 = outlook
  generated_at     TEXT NOT NULL,
  ruleset_version  TEXT NOT NULL REFERENCES ruleset(version),
  features_version TEXT NOT NULL,
  inputs_hash      TEXT NOT NULL,
  day_score        REAL,
  payload_json     TEXT NOT NULL,     -- hour curve, ranked zones, reasons, depth band, tactics
  UNIQUE(lake_id, target_date, horizon_days, ruleset_version, generated_at)
);
```

**`prediction` rows are immutable.** Never regenerate-and-overwrite for a past date.
A new ruleset produces new rows under a new version; the old rows stay. This is the
whole basis of honest calibration.

---

## The notebook

```sql
CREATE TABLE session (
  id             INTEGER PRIMARY KEY,
  lake_id        INTEGER NOT NULL REFERENCES lake(id),
  zone_id        INTEGER REFERENCES zone(id),
  swim_id        INTEGER REFERENCES swim(id),
  started_at     TEXT NOT NULL,
  ended_at       TEXT,
  effort_minutes INTEGER,             -- derived, but stored: the CPUE denominator
  method         TEXT,                -- float|feeder|method|waggler|pole
  is_mobile      INTEGER DEFAULT 0,   -- moved along the bank
  prediction_id  INTEGER REFERENCES prediction(id),   -- what the app said BEFOREHAND
  conditions_snapshot TEXT,           -- JSON, frozen at session start
  water_temp_measured_c REAL,         -- the €5 thermometer. Highest-value field here.
  water_clarity_cm      REAL,
  notes          TEXT,
  reflection     TEXT,                -- 20-second "what worked"
  created_at     TEXT NOT NULL
);

CREATE TABLE session_leg (      -- for mobile sessions: time split across zones
  id         INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES session(id),
  zone_id    INTEGER NOT NULL REFERENCES zone(id),
  swim_id    INTEGER REFERENCES swim(id),
  from_ts    TEXT NOT NULL,
  to_ts      TEXT
);

CREATE TABLE catch (
  id         INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES session(id),
  leg_id     INTEGER REFERENCES session_leg(id),
  species    TEXT NOT NULL,       -- roach|bream|rudd|ide|carp|crucian|pike|perch|...
  count      INTEGER NOT NULL DEFAULT 1,
  weight_g   INTEGER,
  length_cm  REAL,
  caught_at  TEXT,
  depth_m    REAL,
  distance_m REAL,
  bait       TEXT,
  rig        TEXT,
  notes      TEXT
);

CREATE TABLE session_tactic (
  session_id     INTEGER PRIMARY KEY REFERENCES session(id),
  groundbait     TEXT,
  hookbaits      TEXT,
  feeding_pattern TEXT,
  depth_fished_m REAL,
  distance_fished_m REAL,
  hook_size      TEXT,
  line_kg        REAL
);
```

`session_leg` exists because the owner fishes **both** fixed-swim and mobile. Without
it, a mobile session either fabricates a single zone or is excluded — both wrong.
Effort is attributed per leg; CPUE is computed per leg and rolled up.

---

## Calibration

```sql
CREATE TABLE calibration_run (
  id              INTEGER PRIMARY KEY,
  ruleset_version TEXT NOT NULL,
  period_from     TEXT NOT NULL,
  period_to       TEXT NOT NULL,
  n_sessions      INTEGER NOT NULL,
  n_blanks        INTEGER NOT NULL,
  metrics_json    TEXT NOT NULL,   -- rank corr, per-rule hit rate, coverage by zone
  created_at      TEXT NOT NULL
);

CREATE TABLE weight_proposal (
  id              INTEGER PRIMARY KEY,
  calibration_id  INTEGER NOT NULL REFERENCES calibration_run(id),
  rule_id         TEXT NOT NULL,
  current_weight  REAL,
  proposed_weight REAL,
  evidence_json   TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending',  -- pending|accepted|rejected
  decided_at      TEXT
);
```

Nothing in `weight_proposal` is ever auto-applied.

---

## Views the app relies on

```sql
-- the only legitimate success metric
CREATE VIEW v_cpue_by_leg AS
SELECT l.id AS leg_id, l.session_id, l.zone_id,
       (julianday(COALESCE(l.to_ts, s.ended_at)) - julianday(l.from_ts)) * 24.0 AS hours,
       COALESCE(SUM(c.count), 0) AS fish,
       COALESCE(SUM(c.count), 0) /
         NULLIF((julianday(COALESCE(l.to_ts, s.ended_at)) - julianday(l.from_ts)) * 24.0, 0) AS cpue
FROM session_leg l
JOIN session s ON s.id = l.session_id
LEFT JOIN catch c ON c.leg_id = l.id
GROUP BY l.id;

-- sample size per zone: drives every confidence band and the exploration nudge
CREATE VIEW v_zone_coverage AS
SELECT zone_id, COUNT(*) AS n_legs, SUM(hours) AS total_hours
FROM v_cpue_by_leg GROUP BY zone_id;
```

Note the `LEFT JOIN` — a leg with no catches yields `cpue = 0`, not a missing row.
Blanks are data.
