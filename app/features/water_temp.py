"""Modelled water temperature for a shallow lake - the missing Layer 2.

ADR 0001 §5 forbids deriving thermal phase from the calendar, because a cold
May and a warm April swap places in exactly the years it matters. This module
is what replaces that stand-in.

THE MODEL. A small shallow lake behaves as one well-mixed body with a single
heat capacity, so its temperature chases an equilibrium it never quite reaches:

    dT/dt = (T_eq - T) / tau

`tau` scales with mean depth - deeper water is slower - and for Pomocnia's
~2.9 m it lands near two and a half days. That is precisely why three days of
prior weather is the right window and not an arbitrary one.

`T_eq` is where the water would settle under the current sky: air temperature,
lifted by absorbed sunlight and pulled down by evaporation into dry air, with
wind accelerating the evaporative loss. Four inputs, all already ingested
hourly, and deliberately few free parameters - every extra coefficient is
another thing that can be wrong in a way nobody notices.

NEVER let `is_measured` become True without an actual thermometer in the lake.
The UI must present this as modelled, and law 4's spirit is that a plausible
number is not an observation.

Pure: no I/O, no clock reads, time passed in by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

HOURS_PER_DAY = 24.0


@dataclass(frozen=True)
class AirSample:
    ts: datetime
    air_c: float
    dewpoint_c: float | None
    shortwave_wm2: float | None
    wind_ms: float | None


@dataclass(frozen=True)
class WaterTempEstimate:
    celsius: float | None
    trend_24h_c: float | None
    coverage: float
    hours_simulated: int
    is_measured: bool = False

    @property
    def available(self) -> bool:
        return self.celsius is not None


def equilibrium_c(sample: AirSample, cfg: dict[str, Any]) -> float:
    """Pure. Where this water would settle under the current sky, in Celsius.

    Missing optional inputs fall back to their neutral effect - no sun means no
    solar gain, not an invented radiation figure - so a partial hour degrades
    the estimate instead of discarding it.
    """
    eq = cfg["equilibrium"]
    t = sample.air_c * float(eq["air_weight"])

    if sample.shortwave_wm2 is not None:
        t += float(eq["shortwave_gain_c_per_kwm2"]) * (sample.shortwave_wm2 / 1000.0)

    if sample.dewpoint_c is not None:
        # Vapour-pressure deficit proxy. Dry air evaporates the lake and cools
        # it; wind carries the vapour away and speeds that up, but the wind
        # multiplier is capped so a gale cannot drive the equilibrium absurd.
        deficit = max(0.0, sample.air_c - sample.dewpoint_c)
        wind = sample.wind_ms or 0.0
        gust_factor = min(
            float(eq["wind_factor_cap"]),
            1.0 + wind / float(eq["wind_factor_ref_ms"]),
        )
        t -= float(eq["evaporative_loss_per_c_deficit"]) * deficit * gust_factor

    return t


def simulate(
    samples: list[AirSample],
    cfg: dict[str, Any],
    mean_depth_m: float,
    initial_c: float,
) -> list[float]:
    """Pure. Step the lumped model hourly across `samples`, returning water temps.

    Samples must be in ascending time order. Gaps simply mean fewer steps -
    the model relaxes toward equilibrium over whatever hours it was given,
    which is the physically right behaviour for a missing hour.
    """
    tau_hours = float(cfg["tau_days_per_metre"]) * max(0.3, mean_depth_m) * HOURS_PER_DAY
    if tau_hours <= 0:
        raise ValueError("tau must be positive")

    water = initial_c
    out: list[float] = []
    previous: datetime | None = None
    for sample in samples:
        step_h = 1.0 if previous is None else (sample.ts - previous).total_seconds() / 3600.0
        step_h = max(0.0, min(step_h, tau_hours))  # never overshoot in one jump
        water += (equilibrium_c(sample, cfg) - water) * (step_h / tau_hours)
        out.append(water)
        previous = sample.ts
    return out


def estimate(
    samples: list[AirSample],
    now: datetime,
    cfg: dict[str, Any],
    mean_depth_m: float,
    spin_up_hours: int = 72,
    min_coverage: float = 0.8,
) -> WaterTempEstimate:
    """Pure. Water temperature now, and its 24-hour trend.

    Seeded from the mean air temperature over the window rather than from a
    guess, then relaxed forward. With tau near 2.5 days the seed's influence
    has largely decayed by the end of a 72-hour spin-up, which is the reason
    the spin-up exists.
    """
    window = sorted(
        (s for s in samples if now - timedelta(hours=spin_up_hours) <= s.ts <= now),
        key=lambda s: s.ts,
    )
    coverage = min(1.0, len(window) / spin_up_hours) if spin_up_hours > 0 else 0.0
    if len(window) < 2 or coverage < min_coverage:
        return WaterTempEstimate(None, None, coverage, len(window))

    seed = sum(s.air_c for s in window) / len(window)
    series = simulate(window, cfg, mean_depth_m, seed)

    trend: float | None = None
    day_ago = now - timedelta(hours=24)
    earlier = [t for s, t in zip(window, series, strict=True) if s.ts <= day_ago]
    if earlier:
        trend = series[-1] - earlier[-1]

    return WaterTempEstimate(series[-1], trend, coverage, len(window))
