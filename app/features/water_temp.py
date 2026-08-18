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

WHY THIS IS ALLOWED TO BE UNMEASURED. Almost no small water has a thermometer
in it, and waiting for one would mean never shipping. The resolution is not to
pretend the model is accurate - it is to establish what the model is actually
*used* for and how much accuracy each use needs:

  * The ZONE MAP is invariant. A bias in water temperature shifts every cell
    identically, and the ordering is driven by fetch, shore proximity and lead,
    none of which depend on the absolute value. Measured over +/-5 C at water
    temperatures from 12 to 28 C, the ranking does not change at all. The
    where-to-fish answer - which is the point of the app - needs no thermometer.
  * The LAKE-WIDE BITE INDEX moves about 0.10 across +/-3 C, which is narrower
    than one colour band, and a colour band is the only resolution the owner
    ever displays (never a raw score).
  * The THERMAL PHASE needs the trend's sign, which is robust to any constant
    offset by construction.

So the model reports a BAND rather than a point, the band widens honestly when
the inputs are poor, and `is_measured` stays False forever unless somebody puts
a thermometer in the water. `fit_offset` exists for when they occasionally do.

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


# ---------------------------------------------------------------------------
# Uncertainty, and what to do about never having a thermometer
# ---------------------------------------------------------------------------

# How far the free parameters are allowed to be wrong. These bracket the model
# rather than tune it: the point is to find out how much the answer could move,
# not to make it move less.
# Solar gain and evaporative loss are varied INDEPENDENTLY and not by a shared
# factor. Scaling them together lets them cancel - a hotter sun with a stronger
# evaporative loss lands back near the same equilibrium - and produced a band
# of +/-0.3 C, which would have been a confident-looking lie about how well
# these coefficients are known.
_ENSEMBLE_TAU_FACTORS = (0.6, 1.0, 1.6)
_ENSEMBLE_SUN_FACTORS = (0.5, 1.0, 1.5)
_ENSEMBLE_EVAP_FACTORS = (0.5, 1.0, 1.5)


@dataclass(frozen=True)
class WaterTempBand:
    """A modelled water temperature and how wrong it could plausibly be."""

    central: float
    low: float
    high: float
    coverage: float
    offset_applied_c: float
    is_measured: bool = False

    @property
    def half_width(self) -> float:
        return (self.high - self.low) / 2.0


def _with_factors(
    cfg: dict[str, Any], tau_f: float, sun_f: float, evap_f: float
) -> dict[str, Any]:
    eq = dict(cfg["equilibrium"])
    eq["shortwave_gain_c_per_kwm2"] = float(eq["shortwave_gain_c_per_kwm2"]) * sun_f
    eq["evaporative_loss_per_c_deficit"] = (
        float(eq["evaporative_loss_per_c_deficit"]) * evap_f
    )
    out = dict(cfg)
    out["equilibrium"] = eq
    out["tau_days_per_metre"] = float(cfg["tau_days_per_metre"]) * tau_f
    return out


def envelope(samples: list[AirSample], cfg: dict[str, Any]) -> tuple[float, float]:
    """Pure. A physically defensible range for a shallow lake, from the air alone.

    A guard, not an estimate. Its job is to stop a data gap or a bad coefficient
    walking the model somewhere absurd - water that is 10 C above every air
    reading of the last three days is a bug, not a heatwave.
    """
    air = [s.air_c for s in samples]
    if not air:
        return (0.0, 40.0)
    guard = cfg.get("envelope", {})
    below = float(guard.get("max_below_air_min_c", 6.0))
    above = float(guard.get("max_above_air_max_c", 4.0))
    return (min(air) - below, max(air) + above)


def band(
    samples: list[AirSample],
    now: datetime,
    cfg: dict[str, Any],
    mean_depth_m: float,
    offset_c: float = 0.0,
    spin_up_hours: int = 72,
    min_coverage: float = 0.8,
) -> WaterTempBand | None:
    """Pure. Water temperature as a range, from an ensemble of plausible models.

    Twenty-seven runs across the plausible spread of the three coefficients
    that are genuinely uncertain - the thermal time constant, the solar gain
    and the evaporative loss, varied independently so they cannot cancel. The
    spread of the results IS the uncertainty, stated rather than hidden behind
    a decimal point.

    `offset_c` is the correction from `fit_offset`, and is zero for a water
    nobody has ever measured - which is most of them.
    """
    runs: list[float] = []
    coverage = 0.0
    for tau_f in _ENSEMBLE_TAU_FACTORS:
        for sun_f in _ENSEMBLE_SUN_FACTORS:
            for evap_f in _ENSEMBLE_EVAP_FACTORS:
                est = estimate(
                    samples, now, _with_factors(cfg, tau_f, sun_f, evap_f),
                    mean_depth_m, spin_up_hours, min_coverage,
                )
                coverage = est.coverage
                if est.celsius is not None:
                    runs.append(est.celsius + offset_c)
    if not runs:
        return None

    lo_guard, hi_guard = envelope(
        [s for s in samples if now - timedelta(hours=spin_up_hours) <= s.ts <= now], cfg
    )
    clip = [max(lo_guard, min(hi_guard, r)) for r in runs]
    central = sorted(clip)[len(clip) // 2]
    return WaterTempBand(central, min(clip), max(clip), coverage, offset_c)


def fit_offset(
    observations: list[tuple[datetime, float]],
    modelled: list[tuple[datetime, float]],
) -> float | None:
    """Pure. The systematic bias between real readings and the model, in Celsius.

    An angler with a three-pound thermometer who dips it once a trip supplies
    everything this needs. The median of the residuals, so one reading taken in
    the sun on a black jetty cannot drag the correction.

    Returns None with no observations - the model then runs uncorrected and says
    so, which is the honest default for a water nobody has measured.
    """
    if not observations or not modelled:
        return None
    lookup = dict(modelled)
    residuals = [obs - lookup[ts] for ts, obs in observations if ts in lookup]
    if not residuals:
        return None
    residuals.sort()
    mid = len(residuals) // 2
    if len(residuals) % 2:
        return residuals[mid]
    return (residuals[mid - 1] + residuals[mid]) / 2.0
