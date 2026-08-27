"""Ranking the stretches of a river district against each other. Pure.

**This is a labelled hypothesis, not a measurement.** The owner asked for a
river overlay before a river model exists; ADR 0002 already set the precedent
for that on lakes, and this follows it exactly - every number lives in
`config/rules.v*.yaml` under `river_section`, stamped
`provenance: ai_authored_provisional` and carrying `supersede_with:
FORMULA_RIVER_SECTION` so the owner's real formula replaces it rather than
blending with it.

Two terms, both pure geometry (`app/geo/sections.py`):

  * `bend_index` - how much the stretch bends. The physics is real: flow on
    the outside of a bend scours a deeper channel while the inside silts up.
  * `wind_cross` - how squarely the wind crosses the stretch, which is what
    gives it a windward bank at all. The same idea as `lee_shore` on a lake.

What is missing is the whole of what actually decides a river swim: flow rate,
depth, structure, confluences, weed, bank access. None of it is in any data
this project holds, which is why the display is a **ranking against the other
stretches of the same district today** and never a claim about fishing.

Like the lake overlay, display uses percentile ranking - a colour means
"better than the other stretches of this district today", never "good".
Calibration, when it comes, must read the raw score.
"""

from __future__ import annotations

from typing import Any

from app.geo.sections import Section
from app.rules.expressions import safe_eval


def _raw_score(ruleset: dict[str, Any], section: Section, wind_dir: float | None) -> float:
    config = ruleset["river_section"]
    weights = {k: float(v) for k, v in config["weights"].items()}

    features: dict[str, float] = {
        "bend_index": section.bend_index,
        "bearing_deg": section.bearing_deg,
        # No wind reading is a real state - a water whose ingest has not landed
        # yet. The cross-wind term then contributes nothing rather than being
        # invented, which leaves the bend term ranking the stretches on its own.
        "wind_dir": float(wind_dir) if wind_dir is not None else section.bearing_deg,
    }

    for name, term in (config.get("terms") or {}).items():
        features[name] = float(safe_eval(term["expression"], {**features, **weights}))

    return float(safe_eval(config["expression"], {**features, **weights}))


def _percentile(values: list[float]) -> list[float]:
    """Rank into 0..1, so the full colour ramp is always used.

    A DISPLAY transform, exactly as on the lake overlay: it says "better than
    the other stretches of this district today" and nothing about fishing.
    Anything calibrating against reality must read the raw score.
    """
    if not values:
        return []
    if len(values) == 1:
        return [0.5]
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranked = [0.0] * len(values)
    for position, index in enumerate(order):
        ranked[index] = position / (len(values) - 1)
    return ranked


def score_sections(
    ruleset: dict[str, Any],
    sections: list[Section],
    *,
    wind_dir: float | None = None,
) -> dict[int, float]:
    """Each stretch's rank among the others, 0..1, keyed by section index.

    Returns an empty mapping when the ruleset carries no `river_section`
    block, which the caller reads as "draw the stretches without colour".
    """
    if "river_section" not in ruleset or not sections:
        return {}

    raw = [_raw_score(ruleset, section, wind_dir) for section in sections]

    # Every stretch scoring the same is a real answer - a dead straight canal
    # with the wind along it - and percentile ranking would turn that into a
    # full red-to-green spread out of nothing but floating-point noise.
    if max(raw) - min(raw) < 1e-9:
        return {section.index: 0.5 for section in sections}

    ranked = _percentile(raw)
    return {section.index: value for section, value in zip(sections, ranked, strict=False)}
