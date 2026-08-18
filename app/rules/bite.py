"""The three-factor bite model, assembled.

One place where pressure, oxygen and water temperature are combined, for the
lake as a whole and then for each cell of the grid. Everything numeric comes
from the ruleset YAML; this module evaluates, it does not decide (law 1).

TWO STRUCTURAL CHOICES, both load-bearing:

1. **A limiter, not a weighted sum.** The source insists all three conditions
   must hold at once. A sum lets a superb barometer paper over lethal oxygen,
   which is the opposite of what it claims and of Liebig's law, so the factors
   combine as a softened `min`. The softening keeps two excellent factors worth
   something without ever letting them rescue a fatal third.

2. **Pressure is absent from the zone term.** Pressure is identical across nine
   hectares. Adding it per cell would shift every cell equally, change no
   ranking, and imply a spatial claim that does not exist.

FAILING CLOSED. If any factor cannot be computed - too few hours of weather, a
pressure norm without enough history, an angling threshold still owed by the
owner - the index is `None` and the caller must say so. It is never quietly
replaced with a default. A wrong number that looks confident is worse here than
no number, because the calibration loop would learn from it.

Pure: no I/O, no clock reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.features.oxygen import OxygenEstimate, oxygen_term
from app.rules.expressions import safe_eval


@dataclass(frozen=True)
class Factor:
    name: str
    value: float | None
    detail: str


@dataclass(frozen=True)
class BiteAssessment:
    index: float | None
    confidence: float | None
    factors: tuple[Factor, ...]
    limiting: str | None
    unavailable: tuple[str, ...]
    water_temp_is_measured: bool

    @property
    def available(self) -> bool:
        return self.index is not None


@dataclass(frozen=True)
class ZoneInputs:
    row: int
    col: int
    fetch_norm: float
    shore_prox: float
    lee_shore: float
    shallow_proxy: float


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def pressure_factor(
    p_now: float | None, p_norm: float | None, p_24h_ago: float | None, cfg: dict[str, Any]
) -> tuple[float | None, float | None]:
    """Pure. (comfort 0..1, approach -1..1).

    Comfort is distance from this water's own norm, in either direction -
    the swim-bladder argument is symmetric. Approach is whether that distance
    is shrinking, which the source treats as a rising bite even while still
    off the norm.
    """
    if p_now is None or p_norm is None:
        return None, None

    comfort_cfg = cfg["pressure_comfort"]
    comfort = _clamp01(
        float(
            safe_eval(
                comfort_cfg["expression"],
                {
                    "p_now": p_now,
                    "p_norm": p_norm,
                    "p_dev_full_hpa": float(comfort_cfg["p_dev_full_hpa"]),
                },
            )
        )
    )

    approach: float | None = None
    if p_24h_ago is not None:
        approach_cfg = cfg["pressure_approach"]
        approach = float(
            safe_eval(
                approach_cfg["expression"],
                {
                    "p_now": p_now,
                    "p_norm": p_norm,
                    "p_dev_24h_ago": p_24h_ago - p_norm,
                    "p_approach_full_hpa": float(approach_cfg["p_approach_full_hpa"]),
                },
            )
        )
    return comfort, approach


def temperature_factor(
    water_c: float | None, species: str, ruleset: dict[str, Any]
) -> tuple[float | None, str]:
    """Pure. Ascending limb only - the heat collapse belongs to oxygen.

    A symmetric curve around the growth optimum would model the summer crash a
    second time and, worse, claim roach stop feeding at 14 C. Returns None when
    the species has no sourced optimum: guessing one is exactly what law 1
    forbids.
    """
    if water_c is None:
        return None, "no modelled water temperature"

    responses = ruleset["species_response"]
    entry = responses.get(species)
    if not isinstance(entry, dict) or entry.get("t_opt_c") is None:
        return None, f"no sourced temperature optimum for {species}"

    t_opt = float(entry["t_opt_c"])
    t_zero = float(responses["t_zero_c"])
    if t_opt <= t_zero:
        return None, "temperature optimum below the feeding floor"

    expr = ruleset["bite_when"]["temperature_term"]["expression"]
    value = _clamp01(
        float(safe_eval(expr, {"t_water": water_c, "t_opt": t_opt, "t_zero_c": t_zero}))
    )
    confidence = str(entry.get("confidence", "unknown"))
    return value, f"{species} optimum {t_opt} C (confidence {confidence})"


def combine(
    f_pressure: float,
    f_oxygen: float,
    f_temp: float,
    approach: float | None,
    stability: float | None,
    cfg: dict[str, Any],
) -> float:
    """Pure. The softened limiter, with the approach nudge and stability damping."""
    combine_cfg = cfg["combine"]
    return _clamp01(
        float(
            safe_eval(
                combine_cfg["expression"],
                {
                    "f_pressure": f_pressure,
                    "f_oxygen": f_oxygen,
                    "f_temp": f_temp,
                    "f_approach": approach if approach is not None else 0.0,
                    "f_stability": stability if stability is not None else 1.0,
                    "blend": float(combine_cfg["blend"]),
                    "w_approach": float(cfg["pressure_approach"]["weight"]),
                    "stability_floor": float(combine_cfg["stability_floor"]),
                },
            )
        )
    )


def confidence(
    stability: float | None,
    stable_days: int,
    history_coverage: float,
    ruleset: dict[str, Any],
) -> float | None:
    """Pure. How much this estimate deserves to be believed (law 5).

    Deliberately separate from the score. A settled three days makes the same
    number worth more, because the model is driven by a 72-hour mean and that
    mean means less when the window was chaotic.
    """
    if stability is None:
        return None
    cfg = ruleset["confidence"]
    ideal = float(ruleset["stability"]["ideal_consecutive_stable_days"])
    return _clamp01(
        float(
            safe_eval(
                cfg["expression"],
                {
                    "f_stability": stability,
                    "consecutive_stable_days": float(stable_days),
                    "ideal_consecutive_stable_days": max(1.0, ideal),
                    "history_coverage": _clamp01(history_coverage),
                },
            )
        )
    )


def assess(
    ruleset: dict[str, Any],
    species: str,
    water_c: float | None,
    oxygen: OxygenEstimate | None,
    p_now: float | None,
    p_norm: float | None,
    p_24h_ago: float | None,
    stability: float | None,
    stable_days: int,
    history_coverage: float,
) -> BiteAssessment:
    """Pure. The lake-wide bite window, or an honest refusal to give one."""
    cfg = ruleset["bite_when"]

    comfort, approach = pressure_factor(p_now, p_norm, p_24h_ago, cfg)
    f_temp, temp_detail = temperature_factor(water_c, species, ruleset)

    f_oxygen: float | None = None
    o2_detail = "no water temperature, so no oxygen estimate"
    if oxygen is not None:
        f_oxygen = oxygen_term(oxygen.dissolved_mgl, ruleset["oxygen"]["thresholds"])
        o2_detail = (
            f"{oxygen.dissolved_mgl:.2f} mg/L "
            f"(saturation {oxygen.saturation_mgl:.2f}, demand {oxygen.respiration_mgl:.2f})"
            if f_oxygen is not None
            else "oxygen thresholds still owed by the owner"
        )

    factors = (
        Factor(
            "pressure",
            comfort,
            "no pressure norm yet - needs more history"
            if comfort is None
            else f"{p_now:.1f} hPa against a norm of {p_norm:.1f}",
        ),
        Factor("oxygen", f_oxygen, o2_detail),
        Factor("temperature", f_temp, temp_detail),
    )
    missing = tuple(f.name for f in factors if f.value is None)
    if missing:
        return BiteAssessment(None, None, factors, None, missing, False)

    values = {f.name: f.value for f in factors if f.value is not None}
    index = combine(
        values["pressure"], values["oxygen"], values["temperature"], approach, stability, cfg
    )
    limiting = min(values, key=lambda name: values[name])
    return BiteAssessment(
        index=index,
        confidence=confidence(stability, stable_days, history_coverage, ruleset),
        factors=factors,
        limiting=limiting,
        unavailable=(),
        water_temp_is_measured=False,
    )


def score_zones(
    ruleset: dict[str, Any],
    cells: list[ZoneInputs],
    oxygen_by_cell: dict[tuple[int, int], OxygenEstimate],
    water_c: float,
    water_c_24h: float,
    t_opt: float,
) -> list[tuple[int, int, float]]:
    """Pure. Raw per-cell scores. Pressure is deliberately not an input here.

    `thermal_direction` is signed on purpose: the fastest-changing water is an
    advantage only while the lake is heading toward the species optimum. In the
    source's cooling spell the windward shallow won; during a heatwave the same
    bank is the worst place on the lake, and a fixed preference for windward
    banks would get that exactly backwards.
    """
    cfg = ruleset["zone_score"]
    terms = cfg["terms"]
    weights = cfg["weights"]
    gate = cfg["activity_gate"]
    thresholds = ruleset["oxygen"]["thresholds"]

    direction = float(
        safe_eval(
            terms["thermal_direction"]["expression"],
            {
                "t_water": water_c,
                "t_water_24h": water_c_24h,
                "t_opt": t_opt,
                "t_dir_full_c": float(terms["thermal_direction"]["t_dir_full_c"]),
            },
        )
    )

    out: list[tuple[int, int, float]] = []
    for cell in cells:
        estimate = oxygen_by_cell.get((cell.row, cell.col))
        if estimate is None:
            continue
        o2_zone = oxygen_term(estimate.dissolved_mgl, thresholds)
        if o2_zone is None:
            continue

        lead = _clamp01(
            float(
                safe_eval(
                    terms["lead"]["expression"],
                    {"mix_index": cell.fetch_norm, "shallow_proxy": cell.shallow_proxy},
                )
            )
        )
        core = float(
            safe_eval(
                cfg["expression"],
                {
                    "oxygen_zone": o2_zone,
                    "lead": lead,
                    "thermal_direction": direction,
                    "lee_shore": cell.lee_shore,
                    "shore_prox": cell.shore_prox,
                    "w_o2": float(weights["w_o2"]),
                    "w_temp": float(weights["w_temp"]),
                    "w_food": float(weights["w_food"]),
                    "w_margin": float(weights["w_margin"]),
                },
            )
        )
        # Presence is not a bite: below the oxygen floor the fish may well be
        # sitting there and will not feed, so the score collapses rather than
        # sending the angler to a refuge.
        gated = core * _clamp01(
            float(
                safe_eval(
                    gate["expression"],
                    {"oxygen_zone": o2_zone, "o2_bite_floor": float(gate["o2_bite_floor"])},
                )
            )
        )
        out.append((cell.row, cell.col, gated))
    return out
