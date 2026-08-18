"""Dissolved oxygen for a shallow productive lake.

The source video's mechanism is that oxygen is what actually switches the bite
on and off, and that cooler water holds more of it. Half of that is chemistry
and half is not, and the split matters:

  * SATURATION is chemistry. `saturation_mgl` is the standard freshwater
    solubility polynomial and is not open to opinion.
  * What the water ACTUALLY holds is not saturation. In a shallow productive
    lake, respiration - plants at night, sediment, bacteria - climbs steeply
    with temperature while the solubility ceiling only sags gently. Ignoring
    that produced a model whose bite peaked at 26 C, which is exactly the
    condition the source describes as killing the fishing. See docs/adr/0003.
  * REAERATION is what makes one bank different from another. Wind mixing rises
    with the square of wind speed and with the fetch it crossed to get there,
    which is the whole mechanism behind "the windward shallow bank fishes".
  * What counts as ENOUGH oxygen for a feeding fish is biology, lives in the
    ruleset YAML, and is not decided here.

Pure: no I/O, no clock reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Freshwater dissolved-oxygen solubility at 1 atm, mg/L. Standard polynomial;
# a physical constant set, not an angling opinion, so it belongs in code.
_SAT_C0 = 14.652
_SAT_C1 = -0.41022
_SAT_C2 = 0.007991
_SAT_C3 = -0.000077774

# Below this the polynomial is being asked about ice, which is out of season.
MIN_MODELLED_C = 0.0
MAX_MODELLED_C = 40.0


@dataclass(frozen=True)
class OxygenEstimate:
    saturation_mgl: float
    respiration_mgl: float
    reaeration_mgl: float
    dissolved_mgl: float

    @property
    def deficit_mgl(self) -> float:
        """How far below the solubility ceiling this water is sitting."""
        return self.saturation_mgl - self.dissolved_mgl


def saturation_mgl(water_c: float) -> float:
    """Pure. Oxygen solubility in fresh water at 1 atm, mg/L."""
    t = max(MIN_MODELLED_C, min(MAX_MODELLED_C, water_c))
    return _SAT_C0 + _SAT_C1 * t + _SAT_C2 * t**2 + _SAT_C3 * t**3


def respiration_mgl(water_c: float, cfg: dict[str, Any]) -> float:
    """Pure. Net biological oxygen demand, mg/L, as a Q10 rate on temperature.

    This is the term that makes a heatwave bad rather than merely warm. It is
    also the least defensible number in the whole ruleset - see the
    `sensitivity_warning` beside it - and the first thing the calibration loop
    should attack once real sessions exist.
    """
    r20 = float(cfg["r20_mgl"])
    q10 = float(cfg["q10"])
    rate: float = q10 ** ((water_c - 20.0) / 10.0)
    return r20 * rate


def reaeration_mgl(
    wind_ms: float, fetch_norm: float, saturation: float, dissolved: float, cfg: dict[str, Any]
) -> float:
    """Pure. Oxygen that wind mixing puts back, mg/L.

    Two guards that matter. Reaeration can never push water above saturation,
    because it is driven by the deficit and stops when the deficit does - and
    it is capped as a fraction of saturation so a storm cannot manufacture
    oxygen out of an arithmetic accident.
    """
    ref = float(cfg["wind_ref_ms"])
    if ref <= 0:
        return 0.0
    energy = max(0.0, min(1.0, max(0.0, fetch_norm) * (max(0.0, wind_ms) / ref) ** 2))
    headroom = max(0.0, saturation - dissolved)
    return min(energy * float(cfg["max_boost"]) * saturation, headroom)


def estimate(
    water_c: float, wind_ms: float, fetch_norm: float, cfg: dict[str, Any]
) -> OxygenEstimate:
    """Pure. Dissolved oxygen at one spot: ceiling, minus demand, plus mixing."""
    sat = saturation_mgl(water_c)
    resp = respiration_mgl(water_c, cfg["respiration"])
    before_wind = max(0.0, sat - resp)
    reaer = reaeration_mgl(wind_ms, fetch_norm, sat, before_wind, cfg["reaeration"])
    return OxygenEstimate(sat, resp, reaer, min(sat, before_wind + reaer))


def oxygen_term(dissolved: float, thresholds: dict[str, Any]) -> float | None:
    """Pure. 0..1 feeding-oxygen term, or None while the thresholds are unfilled.

    Returns None when `src` is still PENDING_OWNER and no provisional stand-in
    is offered. CLAUDE.md law 1: a missing angling threshold is not a licence
    to invent a plausible one.
    """
    stops = thresholds.get("stops_feeding_mgl")
    good = thresholds.get("not_limiting_mgl")
    if stops is None or good is None:
        stops = thresholds.get("provisional_stops_feeding_mgl")
        good = thresholds.get("provisional_not_limiting_mgl")
    if stops is None or good is None or float(good) <= float(stops):
        return None
    return max(0.0, min(1.0, (dissolved - float(stops)) / (float(good) - float(stops))))
