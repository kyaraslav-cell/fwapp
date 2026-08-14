# ADR 0002 — Provisional AI-authored zone score

Status: **accepted (provisional)** · Date: 2026-08-14 · Supersedes nothing ·
Superseded on arrival of `FORMULA_WIND_ZONE`

## Context

`CLAUDE.md` law 1 forbids fishing knowledge in code, and the "Awaiting input"
section states plainly that `FORMULA_PRESSURE_DEPTH` and `FORMULA_WIND_ZONE`
are owed by the project owner and **must not be guessed at**, because "a
plausible wrong formula is worse than a loud missing one: it will quietly
poison a season of calibration data."

The owner has since asked, explicitly and directly, for a zone-rating formula
to be authored now rather than waiting, so that the map overlay has something
to show.

## Decision

Add a `zone_score` block to a new ruleset version `v0.2`, authored by Claude
from the mechanisms already documented in `docs/02-DOMAIN.md`.

Constraints kept intact:

1. **It lives in YAML, not code.** `config/rules.v0.2.yaml` holds the
   expression and every coefficient. `app/rules/zone_score.py` only evaluates
   it, through the existing restricted-AST evaluator. Law 1 is not broken.
2. **It is stamped `provenance: ai_authored_provisional` and
   `status: hypothesis`.** Per `docs/04-RULES-ENGINE.md`, provenance decides
   how aggressively calibration may override a formula — this one may be
   overridden freely and without ceremony.
3. **It does not occupy the owner's slot.** `FORMULA_WIND_ZONE` remains
   PENDING and unfilled. The block carries `supersede_with: FORMULA_WIND_ZONE`,
   and when the real formula arrives it replaces this block outright rather
   than being blended with it.
4. **It is a new ruleset version.** v0 predictions keep their `v0` stamp;
   predictions written under the new scoring are stamped `v0.2`. Immutability
   (law 2) holds.
5. **The UI says so.** The map carries a visible note that the overlay is
   provisional, AI-authored, geometry-only, and unvalidated against any logged
   catch.

## The formula

```
score = w_fetch · fetch_norm + w_margin · shore_prox + w_shelter · shelter
```

Inputs are pure geometry, computed per grid cell:

| Input | Meaning |
|---|---|
| `fetch_norm` | upwind open water ÷ max possible fetch (0–1) |
| `shore_prox` | 1 at the bank → 0 at `margin_band_m` offshore |
| `shelter` | `1 − fetch_norm` |

Weights switch on thermal phase, preserving the sign inversion that
`docs/02-DOMAIN.md` insists on: wind is **negative** in `spring_warming`
(it mixes away the warm margin) and **positive** in `summer_stagnation`
(mixing is oxygen). `tests/test_zone_score.py` asserts that inversion.

Scores are min-max normalised across the lake's own cells before display, so
the overlay always expresses *relative* preference within this water on this
day — never an absolute claim about catch rate.

## Known weaknesses, recorded deliberately

- **Phase is chosen by the angler, not derived.** The single-layer
  water-temperature model that should derive it (`docs/02-DOMAIN.md`, Layer 2)
  is not built. Until it is, the phase selector is an input, and the UI must
  never present it as a measurement. This is the weakest part of the design.
- **No depth term.** Pomocnia has no bathymetry; `max_depth_m` is unknown.
  Depth-band output remains blocked on `FORMULA_PRESSURE_DEPTH`.
- **No oxygen proxy, no weed, no shading.** These need per-zone attributes the
  owner has not yet mapped, so the score currently ignores what
  `docs/02-DOMAIN.md` argues is probably the dominant summer driver.
- **Not fitted to anything.** Zero logged sessions informed these weights.

## Consequences

The map becomes useful immediately and the surrounding machinery (grid,
scoring, rendering, calibration hooks) gets exercised for real. The risk the
original rule guarded against — a plausible-looking wrong formula silently
becoming the baseline — is mitigated by provenance stamping, the visible UI
warning, and this record, not eliminated. First calibration run with real
sessions should be treated as a test *of this formula*, and killing it outright
is an expected, acceptable outcome.
