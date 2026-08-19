from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.models import IngestGap, Lake, WeatherHourly
from app.core.time import iso, utcnow

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "pressure_msl",
    "precipitation",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
]

FIELD_MAP = {
    "temperature_2m": "temperature_2m",
    "relative_humidity_2m": "relative_humidity_2m",
    "dew_point_2m": "dewpoint_2m",
    "pressure_msl": "pressure_msl",
    "precipitation": "precipitation",
    "cloud_cover": "cloud_cover",
    "wind_speed_10m": "wind_speed_10m",
    "wind_direction_10m": "wind_direction_10m",
    "wind_gusts_10m": "wind_gusts_10m",
    "shortwave_radiation": "shortwave_radiation",
}


def fetch_forecast(
    lat: float, lon: float, past_days: int = 3, forecast_days: int = 16
) -> list[dict[str, Any]]:
    # Every value a string: httpx types its params narrowly, and an int here
    # is the difference between a clean type check and a cast nobody reads.
    params = {
        "latitude": str(lat),
        "longitude": str(lon),
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "UTC",
        "past_days": str(past_days),
        "forecast_days": str(forecast_days),
        "wind_speed_unit": "ms",
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    hourly = data["hourly"]
    times = hourly["time"]
    rows = []
    for i, ts in enumerate(times):
        row = {"ts_utc": ts + ":00+00:00" if len(ts) == 16 else ts}
        for api_field, model_field in FIELD_MAP.items():
            values = hourly.get(api_field, [])
            row[model_field] = values[i] if i < len(values) else None
        rows.append(row)
    return rows


def ingest_forecast(db: Session, lake: Lake) -> int:
    now = utcnow()
    try:
        rows = fetch_forecast(lake.centroid_lat, lake.centroid_lon)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        db.add(
            IngestGap(
                lake_id=lake.id,
                source="openmeteo_forecast",
                from_utc=iso(now),
                to_utc=iso(now),
                reason=f"{type(exc).__name__}: {exc}",
            )
        )
        return 0

    existing_ts = {
        r[0]
        for r in db.execute(
            select(WeatherHourly.ts_utc).where(
                WeatherHourly.lake_id == lake.id,
                WeatherHourly.source == "openmeteo_forecast",
            )
        ).all()
    }

    written = 0
    for row in rows:
        ts_dt = datetime.fromisoformat(row["ts_utc"])
        is_forecast = 1 if ts_dt > now else 0
        if row["ts_utc"] in existing_ts:
            db.execute(
                delete(WeatherHourly).where(
                    WeatherHourly.lake_id == lake.id,
                    WeatherHourly.source == "openmeteo_forecast",
                    WeatherHourly.ts_utc == row["ts_utc"],
                )
            )
        db.add(
            WeatherHourly(
                lake_id=lake.id,
                source="openmeteo_forecast",
                ts_utc=row["ts_utc"],
                is_forecast=is_forecast,
                temperature_2m=row.get("temperature_2m"),
                dewpoint_2m=row.get("dewpoint_2m"),
                relative_humidity_2m=row.get("relative_humidity_2m"),
                pressure_msl=row.get("pressure_msl"),
                wind_speed_10m=row.get("wind_speed_10m"),
                wind_direction_10m=row.get("wind_direction_10m"),
                wind_gusts_10m=row.get("wind_gusts_10m"),
                cloud_cover=row.get("cloud_cover"),
                shortwave_radiation=row.get("shortwave_radiation"),
                precipitation=row.get("precipitation"),
                fetched_at=iso(now),
            )
        )
        written += 1
    return written
