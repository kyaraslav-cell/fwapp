# 02 — Domain model: from weather to a place to fish

This is the conceptual heart of the app. Read it before touching `app/features/` or
`app/rules/`.

## The central idea

> **Weather is measured once for the whole lake. What the water experiences varies by
> zone. The difference between those two things is computed from geometry.**

Jezioro Pomocnia is 9 ha — about 340 m across. No weather model grid cell and no
meteorological station resolves anything smaller than the entire lake. So there is
exactly **one** wind vector, **one** pressure, **one** air temperature, **one** cloud
cover for the whole water at any hour.

All spatial differentiation therefore comes from **geometry × sun position × zone
attributes**. This is not a limitation; it is the mechanism.

```
   ONE weather series                  PER-ZONE response
   ─────────────────────               ──────────────────────────
   pressure_msl          ┐             wind exposure  (bearing vs wind dir)
   air temperature       │             effective fetch (ray-cast upwind)
   wind speed + dir      ├──► × geometry ──►  mixing energy
   cloud cover           │        ×          sun hours / shading
   shortwave radiation   │    sun position   margin temp offset
   precipitation         ┘        ×          oxygen proxy
                              zone attributes
```

---

## Layer 1 — Raw observations

Fetched hourly, stored verbatim, never modified.

| Field | Unit | Source |
|---|---|---|
| `pressure_msl` | hPa | Open-Meteo, METAR |
| `temperature_2m` | °C | Open-Meteo, METAR |
| `dewpoint_2m` | °C | Open-Meteo, METAR |
| `wind_speed_10m` | m/s | Open-Meteo, METAR |
| `wind_direction_10m` | ° true | Open-Meteo, METAR |
| `wind_gusts_10m` | m/s | Open-Meteo |
| `cloud_cover` | % | Open-Meteo |
| `shortwave_radiation` | W/m² | Open-Meteo |
| `precipitation` | mm | Open-Meteo |
| `relative_humidity_2m` | % | Open-Meteo |

**Two sources, both stored.**

- **Open-Meteo** — primary. Grid point at the lake centroid. Hourly, archive back
  decades (ERA5), forecast 16 days. Free, no API key.
- **METAR from Modlin / EPMO (52.451 N, 20.652 E, 10.4 km south)** — independent
  ground truth, roughly half-hourly. No history depth, no forecast, but it is a real
  instrument near the water.

Storing both allows measuring model bias at this specific lake and correcting for it.
Neither is discarded.

*(For reference: the nearest full synoptic station, Warszawa-Okęcie, is 46 km away —
useless for wind at this lake.)*

---

## Layer 2 — Lake-level derived features

### Pressure — the derivative is the signal

The absolute value carries almost no information. 1013 hPa says nothing. "Down 6 hPa
in the last 9 hours" says a front is arriving.

| Feature | Definition |
|---|---|
| `dp_3h`, `dp_6h`, `dp_9h`, `dp_12h`, `dp_24h` | hPa change over trailing window |
| `pressure_stability_48h` | standard deviation over trailing 48 h |
| `pressure_regime` | classified: `falling_fast`, `falling_slow`, `stable`, `rising_slow`, `rising_fast` |
| `hours_since_regime_change` | how long the current regime has held |

Regime thresholds live in the ruleset, not in code.

### Water temperature — modelled, because air temperature is a bad proxy

Air temperature swings 15 °C in a day. A lake's upper layer lags by days and
integrates. We model bulk water temperature with a single-layer energy balance:

```
dT_w/dt = [ α·SW·(1−a) − k_conv·(T_w − T_air) − k_evap·(e_s(T_w) − e_a) ] / (ρ·c_p·d)
```

where `d` is effective mixed-layer depth, `SW` shortwave radiation, `a` albedo, and
`k_conv` is scaled by wind speed (wind drives sensible heat exchange and mixing).

- **Initialise** from ERA5 archive, spun up over at least 60 days before the target
  date so the initial condition washes out.
- **Calibrate** `α`, `k_conv`, `k_evap` against any measured water temperatures the
  owner logs. **A €5 thermometer readings logged each session is the single highest-value
  data point in the whole project** — it turns a guessed model into a fitted one.
- Coefficients live in the lake config, not in code.

Derived from it: `water_temp_bulk`, `water_temp_trend_24h`, `water_temp_trend_72h`,
`degree_days_above_10c` (cumulative since 1 March).

### Thermal phase — a state, not a date

Selects which weight set the ruleset uses. Derived from `water_temp_bulk` and its
trend, **never** from the calendar.

| Phase | Rough trigger | What changes |
|---|---|---|
| `spring_warming` | water < ~14 °C and rising | Find the warmest water. Sheltered, sunlit, shallow margins. **Wind is a negative** — it mixes away the warm layer. Rate of warming beats absolute temperature. |
| `summer_stagnation` | water > ~18 °C, weed dense | Avoid the oxygen sag. **Wind flips to a positive** — mixing is life. Weedy sheltered corners become traps in hot still weather, worst at dawn. |
| `autumn_cooling` | water falling through ~14 °C | Fish follow food, not temperature. Weed dies back: stops producing oxygen, keeps consuming it. Turnover event possible. |

Transitional phases (`late_spring`, `early_autumn`) with blended weights are
permitted; hysteresis is required so the phase does not flap day to day.

**The same wind is good in July and bad in April, in the same zone.** This is why the
phase state exists.

### Light and time

`day_length`, `civil_dawn`, `sunrise`, `solar_noon`, `sunset`, `civil_dusk`,
`day_length_trend`. Feeding windows anchor to light, not to clock time.

Also `moon_phase` and `moon_illumination` — weak evidence, free to collect, testable
against the owner's own logs later. Collect from day one; score at weight zero until
the data says otherwise.

---

## Layer 3 — Zone attributes (entered once, by the owner, on a satellite map)

These are the manual input that makes everything else work. Roughly ten minutes of
work per lake.

| Attribute | Why it matters |
|---|---|
| `polygon` | geometry for every downstream calculation |
| `mean_depth_m`, `max_depth_m` | depth-band clamping |
| `bottom_type` | silt / sand / gravel / clay |
| `weed_density` (0–3) | oxygen proxy driver, primary structure on this lake |
| `weed_species` | *grążel żółty*, *rogatek*, *moczarka* — recorded for the E and S of Pomocnia |
| `reed_pct` | proportion of shoreline with reed fringe |
| `bank_aspect_deg` | which way the bank faces — drives sun exposure |
| `tree_line_height_m` + `tree_side` | shading geometry |
| `access_notes` | practical |

Two of these — **bank aspect** and **tree line** — are the ones people forget. Without
them there is no shade model.

## Layer 4 — Per-zone derived conditions

Computed hourly for every zone, from the lake weather + zone attributes + sun position.

### Wind exposure

```
exposure = cos(θ_wind_from − θ_zone_outward_normal)
```

`+1` = fully windward (wind blowing straight into that bank), `−1` = fully leeward.

**Effective fetch** is ray-cast from the zone across the lake polygon along the upwind
bearing. Capped here at roughly 400 m by lake size — short, but not uniform, and a
westerly stacking food into the eastern weed edge is a genuinely different
proposition from a northerly.

```
wave_energy ∝ f(wind_speed², effective_fetch)
mixing_energy ∝ wind_speed³ · exposure_positive · fetch_factor
```

Wind blowing *into* a bank pushes plankton and suspended food, colours the water, and
oxygenates it. Classic angling lore ("wind in your face, fish in your place") falls
straight out of the geometry — but its *sign* depends on thermal phase.

### Sun and shade

Solar azimuth and elevation are exactly calculable for lat/lon/time. Combined with
bank aspect, tree line height and reed height:

- `sun_hours_today` per zone
- `shade_fraction` at each hour
- `insolation_received` (W/m² adjusted for shading and cloud)

A south bank with tall trees is shaded all morning; the north-east margin bakes from
midday.

### Margin temperature offset

Shallow, sheltered, sunlit margins can run **3–5 °C above the open water** on a still
spring day. In April and May that is the whole game.

```
margin_offset = f(insolation_received, margin_depth, shelter, mixing_energy)
```

High insolation + shallow + sheltered + low mixing → large positive offset.

### Oxygen proxy

Weed respires at night. On a shallow, silted, heavily weeded lake this is likely a
**stronger driver than pressure in July**.

```
o2_proxy = base
         + k_mix · mixing_energy
         + k_photo · insolation_received · weed_density      (daytime production)
         − k_resp  · weed_density · f(water_temp) · night_hours   (night consumption)
         − k_bod   · silt_factor · f(water_temp)
```

Hot + still + overcast night + dense weed → dawn oxygen crash in exactly the weedy
east and south of this lake. Suppress those zones; favour the open windward corner.

All coefficients live in the ruleset. This is a **hypothesis to be tested against the
owner's logs**, not an established fact — flag it as such in the UI.

---

## Layer 5 — Scoring

The ruleset combines everything into:

1. **Day score** (0–10) + go/no-go
2. **Hour curve** — bite probability by hour, anchored to light windows
3. **Ranked zones**, each with a plain-language reason and a confidence based on `n`
4. **Target depth band** per species — from `FORMULA_PRESSURE_DEPTH`, **clamped to the
   depth actually available in that zone.** On a 3 m lake the requested band often
   will not exist; the fallback variable is distance to weed edge.
5. **Tactics hint** — derived from conditions plus the owner's own logged history

Priority order, revised from the original brief:

| Rank | Driver | Note |
|---|---|---|
| 1 | Modelled water temperature + trend | sets thermal phase, gates everything |
| 2 | Per-zone wind exposure | the only true spatial discriminator |
| 3 | Oxygen proxy | probably beats pressure on this water in summer |
| 4 | Pressure trend | modulator, and input to the depth formula |

Pressure moves from headline variable to modulator. On a 3 m lake in July, oxygen
wins.

---

## Layer 6 — Calibration, and the trap it must avoid

**The selection-bias trap.** The owner only logs where he fished. If he fishes the
north bay 70% of the time, the north bay wins regardless of truth.

Three mandatory defences:

1. **CPUE, never counts.** Fish per hour. Blanks included, always.
2. **Track hours-per-zone** as a first-class quantity. Every zone score carries its
   sample size and confidence band.
3. **Active exploration.** The app deliberately proposes sessions in under-sampled
   zones, and flags when a ranking is built on thin evidence. Without this, the system
   converges on the owner's existing habits and calls it insight.

Calibration then measures, per ruleset version:

- Did higher-ranked zones actually produce higher CPUE? (rank correlation)
- Did high day-scores produce better sessions than low ones?
- Per-rule hit rate — which rules are earning their weight and which are noise?
- **Back-test**: replay past seasons under a candidate ruleset and compare.

Proposed weight changes are **surfaced for human approval, never auto-applied.** The
owner stays in the loop; he learns something, instead of being handed a black box.
