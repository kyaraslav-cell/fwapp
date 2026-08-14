from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.rules.expressions import safe_eval


@dataclass(frozen=True)
class PressurePoint:
    ts: datetime
    pressure_msl: float


@dataclass(frozen=True)
class PressureFeatures:
    dp_6h: float | None
    dp_24h: float | None
    pressure_stability_48h: float | None
    regime: str | None


def _value_at_or_before(points: list[PressurePoint], target: datetime) -> float | None:
    candidates = [p for p in points if p.ts <= target]
    if not candidates:
        return None
    return min(candidates, key=lambda p: target - p.ts).pressure_msl


def compute_pressure_features(
    points: list[PressurePoint], now: datetime, regimes: dict[str, str]
) -> PressureFeatures:
    """Pure. `points` and `now` are supplied by the caller — no clock reads here."""
    current = _value_at_or_before(points, now)
    if current is None:
        return PressureFeatures(None, None, None, None)

    p_6h = _value_at_or_before(points, now - timedelta(hours=6))
    p_24h = _value_at_or_before(points, now - timedelta(hours=24))
    dp_6h = current - p_6h if p_6h is not None else None
    dp_24h = current - p_24h if p_24h is not None else None

    window_start = now - timedelta(hours=48)
    window_vals = [p.pressure_msl for p in points if window_start <= p.ts <= now]
    stability = statistics.pstdev(window_vals) if len(window_vals) >= 2 else None

    regime = None
    if dp_6h is not None and stability is not None:
        context: dict[str, float | int | bool] = {
            "dp_6h": dp_6h,
            "pressure_stability_48h": stability,
        }
        for name, expr in regimes.items():
            if safe_eval(expr, context):
                regime = name
                break

    return PressureFeatures(dp_6h, dp_24h, stability, regime)
