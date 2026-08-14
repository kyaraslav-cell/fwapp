from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Lake, WeatherHourly
from app.core.time import parse_iso, to_display


def _circular_mean_deg(values: list[float]) -> float | None:
    import math

    if not values:
        return None
    sin_sum = sum(math.sin(math.radians(v)) for v in values)
    cos_sum = sum(math.cos(math.radians(v)) for v in values)
    if sin_sum == 0 and cos_sum == 0:
        return None
    return round(math.degrees(math.atan2(sin_sum, cos_sum)) % 360, 0)


def _compass(deg: float | None) -> str:
    if deg is None:
        return "—"
    points = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return points[int((deg + 22.5) % 360 // 45)]


def recent_days(db: Session, lake: Lake, days: int = 5) -> list[dict[str, Any]]:
    """Daily summary of the last `days` of actually-observed weather.

    Only rows already reconciled as observations are used (is_forecast = 0):
    a forecast must never be presented as a past condition (law 4).
    """
    rows = db.execute(
        select(WeatherHourly)
        .where(
            WeatherHourly.lake_id == lake.id,
            WeatherHourly.source == "openmeteo_forecast",
            WeatherHourly.is_forecast == 0,
        )
        .order_by(WeatherHourly.ts_utc.desc())
        .limit(days * 24 + 24)
    ).scalars().all()

    buckets: dict[str, list[WeatherHourly]] = defaultdict(list)
    for row in rows:
        local_day = to_display(parse_iso(row.ts_utc)).date().isoformat()
        buckets[local_day].append(row)

    out: list[dict[str, Any]] = []
    for day in sorted(buckets.keys(), reverse=True)[:days]:
        entries = buckets[day]

        def avg(attr: str) -> float | None:
            vals = [getattr(e, attr) for e in entries if getattr(e, attr) is not None]
            return round(statistics.fmean(vals), 1) if vals else None

        wind_dir = _circular_mean_deg(
            [e.wind_direction_10m for e in entries if e.wind_direction_10m is not None]
        )
        out.append(
            {
                "date": day,
                "label": to_display(parse_iso(entries[0].ts_utc)).strftime("%a %d %b"),
                "temp_c": avg("temperature_2m"),
                "pressure_hpa": avg("pressure_msl"),
                "wind_speed": avg("wind_speed_10m"),
                "wind_dir": wind_dir,
                "wind_compass": _compass(wind_dir),
                "cloud": avg("cloud_cover"),
                "n_hours": len(entries),
            }
        )
    return out
