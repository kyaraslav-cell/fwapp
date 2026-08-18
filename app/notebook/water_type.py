"""PZW water or commercial fishery, and why the distinction is not cosmetic.

The two are different measurements, not two labels on the same one:

  * A commercial water is stocked and fed. Fish density is an order of
    magnitude higher, the fish are conditioned to a feeding regime, and
    location is driven by where the bait goes in rather than by where the wind
    stacks natural food.
  * A PZW water holds wild populations at natural density, under closed seasons
    and size limits, where weather and natural food dominate.

**Fish per hour is therefore not comparable across the two.** Law 3 makes CPUE
the unit of success for the whole project, so pooling a commercial session and
a PZW session into one average would corrupt the only measurement the app
exists to make - and it would do it silently, producing a number that looks
fine. `assert_comparable` exists to make that impossible by accident.

The scoring consequence is smaller but real: on a commercial water the wind's
food-stacking term is competing with a feed pipe, so it earns less weight. That
adjustment lives in the ruleset YAML, never here (law 1).
"""

from __future__ import annotations

from typing import Any

PZW = "pzw"
COMMERCIAL = "commercial"
KNOWN = (PZW, COMMERCIAL)

LABELS = {
    PZW: "PZW water",
    COMMERCIAL: "Commercial fishery",
}


class IncomparableWatersError(ValueError):
    """Raised when an aggregate would mix water types."""


def normalise(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in KNOWN else None


def label(value: str | None) -> str:
    known = normalise(value)
    return LABELS[known] if known else "Water type not set"


def is_regulated(value: str | None) -> bool:
    """PZW waters carry closed seasons and size limits; commercial ones do not.

    Used to decide whether the app may suggest targeting a species at all. The
    rules themselves are per-okreg and are NOT encoded here - see the backlog.
    """
    return normalise(value) == PZW


def assert_comparable(water_types: list[str | None]) -> str | None:
    """Pure. The guard that stops CPUE being pooled across incomparable waters.

    Returns the single water type present, or raises. An unset water type is
    also a refusal: an aggregate over waters whose type nobody recorded is not
    trustworthy, and quietly averaging it would be the exact failure this
    module exists to prevent.
    """
    distinct = {normalise(w) for w in water_types}
    if not distinct:
        return None
    if None in distinct:
        raise IncomparableWatersError(
            "cannot aggregate CPUE: at least one water has no water_type set"
        )
    if len(distinct) > 1:
        raise IncomparableWatersError(
            f"cannot aggregate CPUE across {sorted(str(d) for d in distinct)} - "
            "stocked and wild waters are different measurements (law 3)"
        )
    return distinct.pop()


def zone_weight_overrides(ruleset: dict[str, Any], water_type: str | None) -> dict[str, float]:
    """Weights for this water type, from the YAML. Falls back to the defaults.

    Code chooses which block to read; it never contains the numbers (law 1).
    """
    weights = dict(ruleset["zone_score"]["weights"])
    by_type = ruleset["zone_score"].get("water_type_weights") or {}
    override = by_type.get(normalise(water_type))
    if isinstance(override, dict):
        weights.update({k: float(v) for k, v in override.items()})
    return {k: float(v) for k, v in weights.items() if isinstance(v, int | float)}
