from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Lake, Prediction, Ruleset, WeatherHourly
from app.core.time import iso, to_display, utcnow
from app.features.pressure import PressurePoint, compute_pressure_features
from app.features.solar import compute_sun_times
from app.rules.evaluator import FeatureBundle, ScoreBundle, evaluate
from app.rules.loader import load_active_ruleset

OUTLOOK_DAYS = 7


def _ensure_ruleset_row(db: Session, ruleset: dict) -> None:
    version = ruleset["version"]
    existing = db.get(Ruleset, version)
    if existing is None:
        db.add(
            Ruleset(
                version=version,
                yaml=json.dumps(ruleset),
                parent=None,
                note=ruleset.get("note"),
                activated_at=iso(utcnow()),
                created_at=iso(utcnow()),
            )
        )
        db.flush()


def _load_pressure_points(db: Session, lake: Lake, now: datetime) -> list[PressurePoint]:
    window_start = iso(now - timedelta(hours=72))
    window_end = iso(now + timedelta(days=OUTLOOK_DAYS + 1))
    rows = db.execute(
        select(WeatherHourly.ts_utc, WeatherHourly.pressure_msl)
        .where(
            WeatherHourly.lake_id == lake.id,
            WeatherHourly.source == "openmeteo_forecast",
            WeatherHourly.ts_utc >= window_start,
            WeatherHourly.ts_utc <= window_end,
            WeatherHourly.pressure_msl.is_not(None),
        )
        .order_by(WeatherHourly.ts_utc)
    ).all()
    return [
        PressurePoint(ts=datetime.fromisoformat(ts), pressure_msl=p) for ts, p in rows
    ]


def _score_for_horizon(
    ruleset: dict, points: list[PressurePoint], lake: Lake, target_date, horizon: int
) -> tuple[ScoreBundle, FeatureBundle]:
    anchor = datetime.combine(target_date, time(12, 0), tzinfo=UTC)
    pressure_features = compute_pressure_features(points, anchor, ruleset["pressure_regimes"])
    sun = compute_sun_times(lake.centroid_lat, lake.centroid_lon, target_date)
    features = FeatureBundle(now=anchor, pressure=pressure_features, sun=sun)
    return evaluate(ruleset, features), features


def generate_predictions(db: Session, lake: Lake) -> list[Prediction]:
    ruleset = load_active_ruleset()
    _ensure_ruleset_row(db, ruleset)
    now = utcnow()
    points = _load_pressure_points(db, lake, now)

    today_local = to_display(now).date()
    generated_at = iso(now)
    predictions: list[Prediction] = []

    for horizon in range(0, OUTLOOK_DAYS + 1):
        target_date = today_local + timedelta(days=horizon)
        bundle, features = _score_for_horizon(ruleset, points, lake, target_date, horizon)

        payload = {
            "day_score": bundle.day_score,
            "go": bundle.go,
            "band_color": bundle.band_color,
            "band_label": bundle.band_label,
            "best_hours": [
                {
                    "label": w.label,
                    "start": iso(w.start),
                    "end": iso(w.end),
                }
                for w in bundle.best_hours
            ],
            "reasons": bundle.reasons,
            "per_rule_contributions": bundle.per_rule_contributions,
            "pressure_regime": features.pressure.regime,
            "dp_6h": features.pressure.dp_6h,
        }

        inputs_hash = hashlib.sha256(
            json.dumps(
                {
                    "ruleset_version": ruleset["version"],
                    "target_date": str(target_date),
                    "n_points": len(points),
                    "dp_6h": features.pressure.dp_6h,
                    "dp_24h": features.pressure.dp_24h,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

        pred = Prediction(
            lake_id=lake.id,
            target_date=str(target_date),
            horizon_days=horizon,
            generated_at=generated_at,
            ruleset_version=ruleset["version"],
            features_version=ruleset["features_version"],
            inputs_hash=inputs_hash,
            day_score=bundle.day_score,
            payload_json=json.dumps(payload),
        )
        db.add(pred)
        predictions.append(pred)

    db.flush()
    return predictions


def latest_prediction(db: Session, lake: Lake, horizon: int = 0) -> Prediction | None:
    today_local = to_display(utcnow()).date() + timedelta(days=horizon)
    return db.execute(
        select(Prediction)
        .where(
            Prediction.lake_id == lake.id,
            Prediction.target_date == str(today_local),
            Prediction.horizon_days == horizon,
        )
        .order_by(Prediction.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
