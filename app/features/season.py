from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class SeasonHint:
    phase: str
    label: str
    is_measured: bool
    caveat: str


def derive_season(ruleset: dict[str, Any], on_date: date) -> SeasonHint:
    """Pure. Pick a thermal phase from the calendar month.

    This is a deliberate stand-in, not the real thing. ADR 0001 §5 requires
    the phase to come from modelled water temperature and its trend precisely
    because a cold May and a warm April swap places; a month lookup gets that
    wrong in exactly the years it matters most. It exists only so the zone
    score has a weight set before the water-temperature model is built, and
    every caller must present it as an assumption rather than a measurement.
    """
    cfg = ruleset.get("season_hint")
    if not cfg:
        phase = ruleset["zone_score"]["default_phase"]
        return SeasonHint(
            phase=phase,
            label=phase.replace("_", " "),
            is_measured=False,
            caveat="No season rule configured; using the default weight set.",
        )

    phase = cfg["months"].get(on_date.month, cfg["default"])
    return SeasonHint(
        phase=phase,
        label=phase.replace("_", " "),
        is_measured=False,
        caveat=(
            "Assumed from the date, not measured. Water temperature drives the "
            "real phase — a cold May or a warm April will fool this."
        ),
    )


def derive_phase_from_water(
    water_c: float | None,
    trend_24h_c: float | None,
    t_opt_c: float | None,
    cfg: dict[str, Any],
) -> SeasonHint:
    """Pure. Thermal phase from modelled water temperature and its trend.

    What ADR 0001 §5 has asked for since the beginning, and what
    `derive_season` above was only ever standing in for. Read against the
    species optimum rather than as absolute bands, so the same rule serves a
    cold water and a warm one.

    Still `is_measured=False`: the water temperature behind it is modelled, and
    the difference between "derived from physics that tracks the real weather"
    and "measured" must not blur. But it is no longer a lookup table of month
    names, and a cold May will now read as a cold May.
    """
    if water_c is None or trend_24h_c is None or t_opt_c is None:
        return SeasonHint(
            phase="unknown",
            label="unknown",
            is_measured=False,
            caveat="Not enough weather on record to model the water temperature.",
        )

    warming = float(cfg["warming_c_per_day"])
    cooling = float(cfg["cooling_c_per_day"])

    if water_c >= t_opt_c:
        phase = "summer_stagnation"
    elif trend_24h_c >= warming:
        phase = "spring_warming"
    elif trend_24h_c <= cooling:
        phase = "autumn_cooling"
    else:
        phase = "holding"

    return SeasonHint(
        phase=phase,
        label=phase.replace("_", " "),
        is_measured=False,
        caveat=(
            f"From modelled water temperature ({water_c:.1f} °C, "
            f"{trend_24h_c:+.1f} °C/day) - not a thermometer reading, but not "
            "the calendar either."
        ),
    )
