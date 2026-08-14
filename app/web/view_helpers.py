from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Lake, Prediction, WeatherHourly
from app.core.time import parse_iso, to_display, utcnow


def prediction_view(pred: Prediction | None) -> dict[str, Any] | None:
    if pred is None:
        return None
    payload = json.loads(pred.payload_json)
    best_hours = []
    for w in payload["best_hours"]:
        start = to_display(parse_iso(w["start"])).strftime("%H:%M")
        end = to_display(parse_iso(w["end"])).strftime("%H:%M")
        best_hours.append(f"{start}–{end}")
    return {
        "go": payload["go"],
        "band_color": payload["band_color"],
        "band_label": payload["band_label"],
        "best_hours": best_hours,
        "reasons": payload["reasons"],
        "pressure_regime": payload.get("pressure_regime"),
        "dp_6h": payload.get("dp_6h"),
    }


def outlook_view(
    db: Session, lake: Lake, days: int, latest_prediction_fn: Any
) -> list[dict[str, Any]]:
    outlook = []
    for h in range(1, days + 1):
        p = latest_prediction_fn(db, lake, horizon=h)
        if p:
            target = to_display(utcnow() + timedelta(days=h)).strftime("%a %d %b")
            payload = json.loads(p.payload_json)
            outlook.append(
                {
                    "label": target,
                    "band_color": payload["band_color"],
                    "band_label": payload["band_label"],
                }
            )
    return outlook


def current_conditions(db: Session, lake: Lake) -> dict[str, Any] | None:
    now = utcnow()
    row = db.execute(
        select(WeatherHourly)
        .where(
            WeatherHourly.lake_id == lake.id,
            WeatherHourly.source == "openmeteo_forecast",
            WeatherHourly.is_forecast == 0,
        )
        .order_by(WeatherHourly.ts_utc.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None or row.pressure_msl is None:
        return None
    age_minutes = int((now - parse_iso(row.ts_utc)).total_seconds() // 60)
    return {
        "temperature_2m": row.temperature_2m,
        "pressure_msl": row.pressure_msl,
        "wind_speed_10m": row.wind_speed_10m,
        "wind_direction_10m": row.wind_direction_10m,
        "cloud_cover": row.cloud_cover,
        "age_minutes": age_minutes,
    }
