from __future__ import annotations

from typing import Any

from app.rules.expressions import safe_eval


def score_cells(
    ruleset: dict[str, Any],
    phase: str,
    cells: list[tuple[int, int, float, float]],
) -> tuple[list[tuple[int, int, float]], str]:
    """Pure. Score every grid cell and min-max normalise to 0..1.

    `cells` is [(row, col, fetch_m, shore_m)]. All coefficients and the
    expression itself come from the ruleset YAML - no fishing numbers here
    (law 1). Returns ([(row, col, normalised_score)], phase_used).
    """
    cfg = ruleset["zone_score"]
    weights = cfg["phase_weights"]
    phase_used = phase if phase in weights else cfg["default_phase"]
    w = weights[phase_used]

    margin_band = float(cfg["margin_band_m"])
    max_fetch = float(cfg["max_possible_fetch_m"])
    expression = cfg["expression"]

    raw: list[tuple[int, int, float]] = []
    for row, col, fetch_m, shore_m in cells:
        fetch_norm = min(1.0, max(0.0, fetch_m / max_fetch))
        shore_prox = min(1.0, max(0.0, 1.0 - shore_m / margin_band))
        context: dict[str, float | int | bool] = {
            "fetch_norm": fetch_norm,
            "shore_prox": shore_prox,
            "shelter": 1.0 - fetch_norm,
            "w_fetch": float(w["w_fetch"]),
            "w_margin": float(w["w_margin"]),
            "w_shelter": float(w["w_shelter"]),
        }
        raw.append((row, col, float(safe_eval(expression, context))))

    if not raw:
        return [], phase_used

    values = [v for _, _, v in raw]
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0:
        return [(r, c, 0.5) for r, c, _ in raw], phase_used

    return [(r, c, round((v - lo) / span, 3)) for r, c, v in raw], phase_used
