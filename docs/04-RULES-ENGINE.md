# 04 — Rules engine

## Why a rules engine and not a model

30–60 sessions a year. Any machine-learning model on that sample size memorises noise
and hands back a confident number with no justification. A transparent, versioned rule
set with human-approved weight changes is not a compromise here — it is the correct
tool. The owner learns something; the black box would teach him nothing.

## Design contract

1. Rules are **declarative YAML**, never Python.
2. Every rule is **named**, so calibration can measure it individually.
3. Weights are **per thermal phase** — the same wind is good in July and bad in April.
4. Evaluation is a **pure function**: `(ruleset, features) -> ScoreBundle`. No I/O, no
   clock. This is what makes back-testing possible.
5. Every rule emits a **human-readable reason string**. A score with no explanation is
   useless to an angler and unfalsifiable to a developer.
6. Rulesets are **immutable once activated**. Changes create a new version.

## File layout

```
config/
  rules.v1.yaml            the active ruleset
  lakes/pomocnia.yaml      lake constants, water-temp model coefficients, zone defaults
tests/fixtures/
  rules.fake.yaml          fake formulas for testing — CLEARLY MARKED FAKE
```

## Structure

```yaml
version: v1
features_version: f1

thermal_phases:
  spring_warming:
    enter_when: "water_temp_bulk_c < 14 and water_temp_trend_72h > 0.2"
    hysteresis_hours: 48
  summer_stagnation:
    enter_when: "water_temp_bulk_c >= 18"
    hysteresis_hours: 48
  autumn_cooling:
    enter_when: "water_temp_bulk_c < 14 and water_temp_trend_72h < -0.2"
    hysteresis_hours: 48

rules:
  - id: wind_exposure
    scope: zone
    inputs: [wind_exposure, effective_fetch_m, wind_speed_10m]
    expression: "FORMULA_WIND_ZONE"        # <-- PENDING, supplied by owner
    weights:
      spring_warming:    -0.4    # wind mixes away the warm margin: NEGATIVE
      summer_stagnation: +0.9    # mixing is life: POSITIVE
      autumn_cooling:    +0.5
    reason_template: >
      {zone} is {exposure_words} today ({wind_dir_words} {wind_speed} m/s,
      {fetch} m fetch).

  - id: oxygen_proxy
    scope: zone
    inputs: [o2_proxy, weed_density, mixing_energy, water_temp_bulk_c]
    weights:
      spring_warming:     0.1
      summer_stagnation:  1.0
      autumn_cooling:     0.4
    status: hypothesis          # shown in UI as unproven, pending owner's own data
    reason_template: >
      Oxygen likely {o2_words} here — {weed_words} weed, {mixing_words} mixing.

  - id: margin_warmth
    scope: zone
    inputs: [margin_temp_offset_c, insolation_received, shade_fraction]
    weights:
      spring_warming:    1.0     # in April and May this is the whole game
      summer_stagnation: -0.2
      autumn_cooling:     0.3

  - id: pressure_trend
    scope: lake
    inputs: [dp_6h, dp_9h, dp_24h, pressure_stability_48h, pressure_regime]
    weights:
      spring_warming:    0.5
      summer_stagnation: 0.4
      autumn_cooling:    0.5

  - id: light_window
    scope: lake
    inputs: [solar_elevation_deg, civil_dawn, sunset, cloud_cover]
    weights: { spring_warming: 0.6, summer_stagnation: 0.8, autumn_cooling: 0.6 }

  - id: moon
    scope: lake
    inputs: [moon_phase, moon_illumination]
    weights: { spring_warming: 0.0, summer_stagnation: 0.0, autumn_cooling: 0.0 }
    note: collected from day one, scored at zero until the owner's data says otherwise

depth_band:
  expression: "FORMULA_PRESSURE_DEPTH"     # <-- PENDING, supplied by owner
  clamp_to_zone_depth: true
  fallback_when_unavailable: distance_to_weed_edge
  species_coefficients:
    roach:   { TODO: pending }
    bream:   { TODO: pending }
    rudd:    { TODO: pending }
    ide:     { TODO: pending }
    carp:    { TODO: pending }
    crucian: { TODO: pending }

aggregation:
  day_score:   { method: weighted_sum, normalise: 0..10 }
  zone_score:  { method: weighted_sum, normalise: 0..10 }
  min_sessions_for_confidence: 5
  exploration_bonus:
    enabled: true
    applies_when_zone_hours_below: 10
    magnitude: 0.8
```

## The two pending formulas

**Do not invent these.** They are supplied by the project owner.

| Slot | Purpose |
|---|---|
| `FORMULA_PRESSURE_DEPTH` | pressure state → target depth band, per species |
| `FORMULA_WIND_ZONE` | wind vector × zone geometry → zone preference |

Until delivered, the evaluator raises `FormulaNotSuppliedError`. Build all surrounding
machinery, wire the slot, and test against `tests/fixtures/rules.fake.yaml`.

When they arrive, capture alongside each: **inputs and units, the expression, output
and units, species coefficients, provenance, and valid range.** Record provenance in
an ADR — it determines how aggressively calibration is allowed to override them.

### Two constraints the owner has already been warned about

- **Depth output must be clamped.** Pomocnia averages under 3 m. A formula returning
  "5.5 m" has nowhere to go. Clamp to zone depth; where the band cannot be met, fall
  back to distance-to-weed-edge, which is the variable that actually varies here.
- **Wind sign is phase-dependent.** Any wind formula must be applied through the phase
  weight table above, not directly.

## Evaluator

```python
def evaluate(ruleset: RuleSet, features: FeatureBundle) -> ScoreBundle:
    """Pure. No I/O. No clock. Deterministic given inputs."""
```

`ScoreBundle` carries: `day_score`, `hour_curve`, `ranked_zones` (each with score,
reason strings, confidence, `n`), `depth_band`, `tactics_hint`, and
`per_rule_contributions` — the last of these is what makes per-rule calibration
possible. Without it you can measure the whole ruleset but never a single rule.

## Safe expression evaluation

Expressions are arithmetic over named features. Use a restricted AST evaluator
(whitelisted node types: numbers, names, binary/unary ops, comparisons, boolean ops,
plus a whitelist of `min`, `max`, `abs`, `clamp`, `exp`, `log`, `sqrt`, `cos`, `sin`,
`radians`). **Never `eval()` or `exec()`.** Unknown names are a load-time error, not a
runtime surprise — validate the whole ruleset against the feature registry when it is
activated.
