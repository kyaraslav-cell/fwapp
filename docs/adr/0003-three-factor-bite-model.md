# ADR 0003 — The three-factor bite model, and what was not taken from it

**Status:** proposed. `config/rules.v0.4-draft.yaml` is written and validated
but **not active**; `config/rules.v0.3.yaml` still serves.
**Date:** 2026-08-18
**Source:** `docs/sources/2026-08-carp-three-factor-video-ru.md` — a Russian
carp-fishing video supplied by the owner as screenshots, named by them as the
backbone of the zone formula.

---

## Context

`docs/10 §4` records the weakest point of the current scoring: thermal phase is
picked from the **calendar month**, which ADR 0001 §5 explicitly forbids. Every
zone term in v0.3 is open-water geometry — nothing in it knows the water's
temperature or its oxygen, which `docs/02-DOMAIN.md` argues is probably the
dominant summer driver.

The owner supplied a source that addresses exactly that, and asked for a
formula built on it, using at least three days of prior weather, with stable
weather treated as the ideal case.

## Decision

Adopt the video's structure — **pressure, oxygen, water temperature, and all
three at once** — as the skeleton of v0.4, with the following departures. Each
departure exists because taking the video literally would have broken one of
the five laws or one of this lake's physical facts.

### 1. The pressure norm is computed, never quoted

The video's single most important claim is that the norm is **specific to each
water body** (1:36). It then says "there is a simple formula to calculate it"
and never gives it — that is the paid upsell in its final episode.

So the norm is not taken from the video. It is the long-run **median** of this
lake's own `pressure_msl` from the ERA5 archive Open-Meteo already serves at
the lake's coordinates. A central tendency of a measured series is arithmetic,
not angling judgement, which is precisely why it is safe under law 1 — and it
is strictly better than a number recited from a video about a different lake.

**Unit trap, recorded so nobody trips on it later:** the video's "750 мм рт.
ст." is a *station* reading at that lake's altitude (≈1000 hPa). We store
`pressure_msl`, which is sea-level reduced. Comparing the two directly would put
the norm ~13 hPa wrong.

### 2. A limiter, not a weighted sum

Video 4:20: *"Все три условия совпали одновременно"* — all three at once. A
weighted sum lets a superb pressure reading paper over lethal oxygen, which is
the opposite of what the source claims and of Liebig's law. `bite_when.combine`
is therefore a `min()` softened by a 0.35 blend, so two good factors still
count for something without ever rescuing a fatal third.

### 3. Pressure is excluded from the zone term

Video 2:43: *"давление на водоёме на всём будет одинаковое"* — pressure is the
same everywhere on the water; temperature and oxygen are what vary by place and
depth.

This is the same fact `CLAUDE.md` already states as "there is exactly one
weather series for the whole lake", arrived at independently. Adding a
lake-uniform term to every cell would shift all scores equally, change no
ranking, and imply a spatial claim that does not exist. It is left out.

### 4. Three days is this lake's memory, not a preference

The owner asked for ≥3 days of prior weather. That turns out to be physically
exact rather than arbitrary: a lake with a mean depth under 3 m has a thermal
time constant of roughly one to three days, so **the last ~72 hours of air
temperature effectively *are* the water temperature signal.** The lookback is
set to 72 h for that reason and is documented as such.

### 5. Stability drives the score *and* the confidence

Splitting these was deliberate. Stability raises the score (a settled fish
feeds), but it also raises how much the model deserves to be believed — a
72-hour-mean-driven estimate is simply worth less when those 72 hours were
chaotic. Law 5 already demands that `n` and a confidence band travel with every
number; stability now feeds that band. Instability damps the score to a floor
of 0.55 rather than to zero: fish still feed in a front, just less predictably.

### 6. Presence is not a bite

The sharpest observation in the source is not the three factors — it is that
the carp **did** move to the deep water by the dam and then **did not feed**
there (4:47–5:17), while a nearby group took three grass carp in the same spot
because 25–30 °C suits grass carp exactly when it is starving carp of oxygen.

A map of where fish *are* is not a map of where they *bite*. `activity_gate`
encodes that: below an oxygen floor the zone score collapses even though the
fish may be sitting there. Without this the model would confidently send the
angler to the refuge.

### 7. Nothing was invented for the four primary species

The video is about carp. This project scores **roach, bream, rudd and ide**,
and the video gives no figure for any of them. The one temperature range it
states — grass carp, 25–30 °C — is for a species that is out of scoring scope.

`species_response` therefore carries `src: PENDING_OWNER` and `t_opt_c: null`
for all four primaries plus crucian carp. The evaluator must refuse to score
rather than fall back to a plausible-looking guess. This is law 1 and it is the
whole reason the formula slots exist.

## Adaptations forced by this lake

The source's water is a dammed river: deep at the dam, shallow at the tail.
Pomocnia is 9 ha, ~340 m across, mean depth under 3 m.

| The video assumes | Pomocnia |
|---|---|
| A deep refuge to escape heat | None. In a heatwave the whole lake goes hypoxic together, and the honest output is "do not go", not "fish the deep end" |
| Depth varies enough to matter | `shallow_proxy` is **distance to shore**, because there is no bathymetry. A proxy, and the UI must never present it as survey |
| Long fetch, slow mixing | 340 m maximum fetch mixes the whole lake quickly, so the windward/lee split is real but much weaker |

## Consequences

**Good.** The calendar-month thermal phase can be deleted once `water_temp`
lands — closing the ADR 0001 §5 violation that `docs/10 §4` flags. Oxygen and
water temperature enter the score for the first time. `FORMULA_WIND_ZONE`
remains **unfilled**; v0.4 still carries `supersede_with: FORMULA_WIND_ZONE` and
is replaced outright when the owner's own formula arrives.

**Costs.** `features_version: f1` names features that do not exist yet —
`t_water`, `o2_sat`, and the 72-hour statistics — so nothing can evaluate this
ruleset until three pure modules are built (`app/features/water_temp.py`,
`oxygen.py`, `stability.py`). Until then v0.4 is a specification, not a running
score.

**Evidence.** None. The source is one angler, one session, 17 fish, no control
and no blank sessions counted. It is a coherent *mechanism*, which is worth
having, and it is not *validation*, which this project only gets from its own
calibration loop. Everything here is stamped `ai_provisional` or `video` and may
be overridden without ceremony.

## Verification done

All 14 expressions in `config/rules.v0.4-draft.yaml` were executed through the
project's real restricted-AST evaluator with a populated context; all 14
evaluate. One was found broken on the first run — a YAML folded-scalar
indentation bug had split `bite_when.combine` across two lines — and fixed.
