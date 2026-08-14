from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Lake, WeatherHourly
from app.core.time import parse_iso, to_display, utcnow


def _circular_mean_deg(values: list[float]) -> float | None:
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


def current_reading(db: Session, lake: Lake) -> dict[str, Any] | None:
    """The single most recent hour, whatever it is.

    The daily table used to be the only temperature on screen, and a daily
    MEAN reads as badly wrong when you are standing outside in the afternoon:
    a day that runs 12 °C at night and 26 °C at noon averages about 18 °C, and
    a part-finished day averaged before noon is colder still. So the current
    hour is shown separately and prominently, with its own age, and the table
    now shows highs and lows rather than a mean.
    """
    row = db.execute(
        select(WeatherHourly)
        .where(
            WeatherHourly.lake_id == lake.id,
            WeatherHourly.source == "openmeteo_forecast",
            WeatherHourly.temperature_2m.is_not(None),
        )
        .order_by(WeatherHourly.ts_utc.desc())
        .limit(200)
    ).scalars().all()
    if not row:
        return None

    now = utcnow()
    # Nearest hour to now in either direction. Within the current hour the
    # "forecast" row IS the nowcast, so preferring a stale observation would
    # be less accurate, not more honest.
    nearest = min(row, key=lambda r: abs((parse_iso(r.ts_utc) - now).total_seconds()))
    ts = parse_iso(nearest.ts_utc)
    age_min = int((now - ts).total_seconds() // 60)

    return {
        "temp_c": nearest.temperature_2m,
        "pressure_hpa": nearest.pressure_msl,
        "wind_speed": nearest.wind_speed_10m,
        "wind_dir": nearest.wind_direction_10m,
        "wind_compass": _compass(nearest.wind_direction_10m),
        "cloud": nearest.cloud_cover,
        "local_time": to_display(ts).strftime("%H:%M"),
        "age_min": age_min,
        "is_forecast": bool(nearest.is_forecast),
    }


def recent_days(db: Session, lake: Lake, days: int = 5) -> list[dict[str, Any]]:
    """Per-day highs and lows for the last `days` of observed weather.

    Only rows reconciled as observations are used (is_forecast = 0): a
    forecast must never be presented as a past condition (law 4).
    """
    rows = db.execute(
        select(WeatherHourly)
        .where(
            WeatherHourly.lake_id == lake.id,
            WeatherHourly.source == "openmeteo_forecast",
            WeatherHourly.is_forecast == 0,
        )
        .order_by(WeatherHourly.ts_utc.desc())
        .limit(days * 24 + 48)
    ).scalars().all()

    buckets: dict[str, list[WeatherHourly]] = defaultdict(list)
    for row in rows:
        buckets[to_display(parse_iso(row.ts_utc)).date().isoformat()].append(row)

    out: list[dict[str, Any]] = []
    for day in sorted(buckets.keys(), reverse=True)[:days]:
        entries = buckets[day]

        temps = [e.temperature_2m for e in entries if e.temperature_2m is not None]
        winds = [e.wind_speed_10m for e in entries if e.wind_speed_10m is not None]
        press = [e.pressure_msl for e in entries if e.pressure_msl is not None]
        wind_dir = _circular_mean_deg(
            [e.wind_direction_10m for e in entries if e.wind_direction_10m is not None]
        )

        out.append(
            {
                "date": day,
                "label": to_display(parse_iso(entries[0].ts_utc)).strftime("%a %d %b"),
                "temp_min": round(min(temps), 1) if temps else None,
                "temp_max": round(max(temps), 1) if temps else None,
                "wind_max": round(max(winds), 1) if winds else None,
                "wind_dir": wind_dir,
                "wind_compass": _compass(wind_dir),
                "pressure_hpa": round(sum(press) / len(press), 0) if press else None,
                "n_hours": len(entries),
                # A day still in progress, or one with an ingest gap, is not
                # comparable to a full one - say so rather than quietly
                # reporting a high that has not happened yet.
                "is_partial": len(entries) < 20,
            }
        )
    return out
