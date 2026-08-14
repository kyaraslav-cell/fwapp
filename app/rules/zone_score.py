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
            "lee_shore": fetch_norm * shore_prox,
            "w_fetch": float(w["w_fetch"]),
            "w_margin": float(w["w_margin"]),
            "w_shelter": float(w["w_shelter"]),
            "w_lee": float(w.get("w_lee", 0.0)),
        }
        raw.append((row, col, float(safe_eval(expression, context))))

    if not raw:
        return [], phase_used

    mode = cfg.get("display", {}).get("normalisation", "minmax")
    if mode == "percentile":
        return _percentile_normalise(raw), phase_used
    return _minmax_normalise(raw), phase_used


def _minmax_normalise(raw: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    values = [v for _, _, v in raw]
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0:
        return [(r, c, 0.5) for r, c, _ in raw]
    return [(r, c, round((v - lo) / span, 3)) for r, c, v in raw]


def _percentile_normalise(raw: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    """Rank cells and spread them evenly over 0..1.

    Display only. Raw scores on a small round lake cluster tightly, so min-max
    left nearly every cell in one colour band. Ranking guarantees the whole
    ramp is used - which also means colour is strictly relative to the other
    cells on this lake today, never an absolute claim about fishing quality.
    Ties share the mean rank so identical cells never get different colours.
    """
    order = sorted(range(len(raw)), key=lambda i: raw[i][2])
    n = len(raw)
    if n == 1:
        return [(raw[0][0], raw[0][1], 0.5)]

    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and raw[order[j + 1]][2] == raw[order[i]][2]:
            j += 1
        mean_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1

    return [
        (raw[i][0], raw[i][1], round(ranks[i] / (n - 1), 3)) for i in range(n)
    ]
