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
