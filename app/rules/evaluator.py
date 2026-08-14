from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.time import to_display
from app.features.pressure import PressureFeatures
from app.features.solar import SunTimes


@dataclass(frozen=True)
class FeatureBundle:
    now: datetime
    pressure: PressureFeatures
    sun: SunTimes


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime
    label: str


@dataclass(frozen=True)
class ScoreBundle:
    day_score: float
    go: bool
    best_hours: list[TimeWindow]
    reasons: list[str]
    per_rule_contributions: dict[str, float] = field(default_factory=dict)


def _pressure_component(
    ruleset: dict[str, Any], features: PressureFeatures
) -> tuple[float, str]:
    rule = next(r for r in ruleset["rules"] if r["id"] == "pressure_trend")
    if features.regime is None:
        return 0.0, "not enough pressure history yet"
    score = rule["regime_scores"].get(features.regime, 0.0)
    reason = rule["reason_template"].format(
        regime=features.regime.replace("_", " "),
        dp_6h=round(features.dp_6h, 1) if features.dp_6h is not None else "?",
    )
    return score, reason


def _light_windows(ruleset: dict[str, Any], sun: SunTimes) -> list[TimeWindow]:
    rule = next(r for r in ruleset["rules"] if r["id"] == "light_window")
    offset = timedelta(hours=rule["dawn_dusk_window_hours"])
    morning = TimeWindow(sun.civil_dawn, sun.sunrise + offset, "morning")
    evening = TimeWindow(sun.sunset - offset, sun.civil_dusk, "evening")
    return [morning, evening]


def evaluate(ruleset: dict[str, Any], features: FeatureBundle) -> ScoreBundle:
    """Pure. No I/O, no clock reads — everything comes from `features`."""
    pressure_rule = next(r for r in ruleset["rules"] if r["id"] == "pressure_trend")
    light_rule = next(r for r in ruleset["rules"] if r["id"] == "light_window")

    pressure_score, pressure_reason = _pressure_component(ruleset, features.pressure)
    windows = _light_windows(ruleset, features.sun)
    light_score = light_rule["score_in_window"]

    weighted_sum = pressure_score * pressure_rule["weight"] + light_score * light_rule["weight"]
    day_score = max(0.0, min(10.0, 5.0 + 5.0 * weighted_sum))
    go_threshold = ruleset["aggregation"]["go_threshold"]

    reasons = [pressure_reason]
    for w in windows:
        reasons.append(
            light_rule["reason_template"].format(
                label=w.label.capitalize(),
                start=to_display(w.start).strftime("%H:%M"),
                end=to_display(w.end).strftime("%H:%M"),
            )
        )

    return ScoreBundle(
        day_score=round(day_score, 1),
        go=day_score >= go_threshold,
        best_hours=windows,
        reasons=reasons,
        per_rule_contributions={
            "pressure_trend": round(pressure_score * pressure_rule["weight"], 3),
            "light_window": round(light_score * light_rule["weight"], 3),
        },
    )
