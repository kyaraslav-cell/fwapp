"""Adapter between the stored weather series and the three-factor bite model.

The model in `app/rules/bite.py` and `app/features/*` is pure by design - it
reads no clock and touches no database. This is the impure layer that feeds it:
it pulls the hourly series out of SQLite, hands them to the model, and returns
something a template can render.

It is also the single place that decides whether the active ruleset supports
the new model at all. Feature-detected on `bite_when` rather than on a version
string, so rolling back to v0.3 with FISHLOG_RULESET needs no code change.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Lake, WeatherHourly
from app.core.time import parse_iso, utcnow
from app.features import oxygen as ox
from app.features import stability as stab
from app.features import water_temp as wt
from app.features.season import SeasonHint, derive_phase_from_water
from app.rules import bite

DEFAULT_SPECIES = "roach"


def supports_bite_model(ruleset: dict[str, Any]) -> bool:
    return "bite_when" in ruleset and "water_temp" in ruleset


@dataclass(frozen=True)
class BiteView:
    water: wt.WaterTempBand | None
    oxygen: ox.OxygenEstimate | None
    assessment: bite.BiteAssessment | None
    phase: SeasonHint
    water_24h_c: float | None
    stability: float | None
    stable_days: int
    t_opt_c: float | None

    @property
    def water_label(self) -> str:
        """Never a bare number: the band travels with it (law 5)."""
        if self.water is None:
            return "—"
        return f"{self.water.central:.1f} ±{self.water.half_width:.1f} °C (modelled)"


def _series(
    db: Session, lake: Lake
) -> tuple[list[wt.AirSample], list[stab.Sample], list[stab.Sample]]:
    rows = (
        db.execute(
            select(WeatherHourly)
            .where(WeatherHourly.lake_id == lake.id)
            .order_by(WeatherHourly.ts_utc)
        )
        .scalars()
        .all()
    )
    air: list[wt.AirSample] = []
    pressure: list[stab.Sample] = []
    air_t: list[stab.Sample] = []
    for r in rows:
        ts = parse_iso(r.ts_utc)
        if ts is None:
            continue
        if r.temperature_2m is not None:
            air.append(
                wt.AirSample(
                    ts, r.temperature_2m, r.dewpoint_2m,
                    r.shortwave_radiation, r.wind_speed_10m,
                )
            )
            air_t.append(stab.Sample(ts, r.temperature_2m))
        if r.pressure_msl is not None:
            pressure.append(stab.Sample(ts, r.pressure_msl))
    return air, pressure, air_t


def build(
    db: Session, lake: Lake, ruleset: dict[str, Any], species: str = DEFAULT_SPECIES
) -> BiteView:
    """Everything the lake page needs from the new model, or an honest blank.

    Never raises on missing weather: an empty database yields a view whose
    every field is None and whose phase says why. The page then shows an
    unavailable state rather than a fabricated one.
    """
    air, pressure, air_t = _series(db, lake)
    phase_cfg = ruleset["thermal_phase"]
    entry = ruleset["species_response"].get(species) or {}
    t_opt = entry.get("t_opt_c")

    if not air:
        return BiteView(None, None, None,
                        derive_phase_from_water(None, None, None, phase_cfg),
                        None, None, 0, t_opt)

    now = max(max(s.ts for s in air), utcnow())
    wcfg = ruleset["water_temp"]
    water = wt.band(
        air, now, wcfg, float(wcfg["mean_depth_m"]),
        offset_c=float(getattr(lake, "water_temp_offset_c", 0.0) or 0.0),
        spin_up_hours=int(wcfg["spin_up_hours"]),
        min_coverage=float(wcfg["min_coverage_ratio"]),
    )

    scfg = ruleset["stability"]
    hours = int(scfg["lookback_hours"])
    p_stats = stab.summarise(pressure, now, hours)
    t_stats = stab.summarise(air_t, now, hours)
    stability = stab.stability_index(p_stats, t_stats, scfg)
    stable_days = stab.consecutive_stable_days(pressure, air_t, now, scfg)

    if water is None:
        return BiteView(None, None, None,
                        derive_phase_from_water(None, None, None, phase_cfg),
                        None, stability, stable_days, t_opt)

    point = wt.estimate(air, now, wcfg, float(wcfg["mean_depth_m"]),
                        int(wcfg["spin_up_hours"]), float(wcfg["min_coverage_ratio"]))
    # Yesterday's water temperature, for the SIGNED thermal direction in the
    # zone term. Deriving it from the trend rather than re-running the ensemble
    # keeps the two consistent with each other.
    water_24h = (
        water.central - point.trend_24h_c if point.trend_24h_c is not None else water.central
    )
    phase = derive_phase_from_water(water.central, point.trend_24h_c, t_opt, phase_cfg)

    wind_now = next((s.wind_ms for s in reversed(air) if s.wind_ms is not None), 0.0) or 0.0
    oxygen = ox.estimate(water.central, wind_now, 0.5, ruleset["oxygen"])

    p_now = pressure[-1].value if pressure else None
    day_ago = now - dt.timedelta(hours=24)
    p_24 = next((s.value for s in reversed(pressure) if s.ts <= day_ago), None)
    p_norm = stab.pressure_norm(pressure, ruleset["pressure_norm"])

    assessment = bite.assess(
        ruleset, species, water.central, oxygen, p_now, p_norm, p_24,
        stability, stable_days, min(p_stats.coverage, t_stats.coverage),
    )
    return BiteView(
        water, oxygen, assessment, phase, water_24h, stability, stable_days, t_opt
    )


def zone_scores(
    db: Session,
    lake: Lake,
    ruleset: dict[str, Any],
    inputs: list[tuple[int, int, float, float]],
    view: BiteView,
    margin_band_m: float,
    max_fetch_m: float,
) -> list[tuple[int, int, float]]:
    """Per-cell raw scores from the new model, normalised for display elsewhere.

    `shallow_proxy` is shore proximity, because this lake has no bathymetry.
    A documented proxy, and the UI must not present it as a survey.
    """
    if view.water is None or view.t_opt_c is None:
        return []

    cells: list[bite.ZoneInputs] = []
    for row, col, fetch_m, shore_m in inputs:
        fetch_norm = min(1.0, max(0.0, fetch_m / max_fetch_m))
        shore_prox = min(1.0, max(0.0, 1.0 - shore_m / margin_band_m))
        cells.append(
            bite.ZoneInputs(row, col, fetch_norm, shore_prox,
                            fetch_norm * shore_prox, shore_prox)
        )

    air, _, _ = _series(db, lake)
    wind = next((s.wind_ms for s in reversed(air) if s.wind_ms is not None), 0.0) or 0.0

    oxygen_by_cell = {
        (c.row, c.col): ox.estimate(view.water.central, wind, c.fetch_norm, ruleset["oxygen"])
        for c in cells
    }
    return bite.score_zones(
        ruleset, cells, oxygen_by_cell, view.water.central,
        view.water_24h_c if view.water_24h_c is not None else view.water.central,
        view.t_opt_c,
    )
