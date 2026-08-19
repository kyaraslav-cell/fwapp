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


# Past this many days ahead the pressure forecast that drives the day score is
# not worth much. The days are still shown - hiding them would be its own lie
# about how far the model sees - but they are drawn faded and say why.
CONFIDENT_HORIZON_DAYS = 5


def calendar_view(
    db: Session,
    lake: Lake,
    days: int,
    latest_prediction_fn: Any,
    forecast_summaries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """One entry per day from today to `days` ahead, for the day strip.

    Every band here is read out of a stored `prediction` row. Nothing is
    recomputed at render time: law 2 makes those rows the immutable record of
    what the app said before the day happened, and a calendar that quietly
    re-derived them would erase the only evidence the app was ever wrong.

    A day with no prediction row - an ingest gap, or a horizon the writer has
    not reached - comes back with `has_data: False` and no colour. It is never
    filled in from a neighbouring day (law 4).
    """
    today_local = to_display(utcnow()).date()
    entries: list[dict[str, Any]] = []

    for horizon in range(0, days + 1):
        target = today_local + timedelta(days=horizon)
        pred = latest_prediction_fn(db, lake, horizon=horizon)
        payload = json.loads(pred.payload_json) if pred is not None else None

        best_hours: list[str] = []
        if payload:
            for window in payload["best_hours"]:
                start = to_display(parse_iso(window["start"])).strftime("%H:%M")
                end = to_display(parse_iso(window["end"])).strftime("%H:%M")
                best_hours.append(f"{start}\u2013{end}")

        # The weather that day, for the conditions card while it is selected.
        # Today never takes one: its card shows the live reading.
        summary = {} if horizon == 0 else forecast_summaries.get(target.isoformat(), {})

        entries.append(
            {
                "date": target.isoformat(),
                "horizon": horizon,
                "weekday": target.strftime("%a"),
                "day_of_month": target.day,
                "label": target.strftime("%a %d %b"),
                "has_data": payload is not None,
                "band_color": payload["band_color"] if payload else None,
                "best_hours": best_hours,
                # Why the colour is what it is. The regime is a name the ruleset
                # assigned (data, not code); the sentence around it is looked up
                # per language in the template, so the number and the wording
                # never disagree.
                "pressure_regime": payload.get("pressure_regime") if payload else None,
                "dp_6h": payload.get("dp_6h") if payload else None,
                # The bearing the map re-scores with when this day is picked.
                # None for today, and for any day the forecast did not cover.
                "wind_dir": summary.get("wind_dir"),
                "wind_compass": summary.get("wind_compass"),
                "wind_max": summary.get("wind_max"),
                "temp_max": summary.get("temp_max"),
                "temp_min": summary.get("temp_min"),
                "pressure_hpa": summary.get("pressure_hpa"),
                "is_today": horizon == 0,
                "is_far": horizon > CONFIDENT_HORIZON_DAYS,
            }
        )

    return entries


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
