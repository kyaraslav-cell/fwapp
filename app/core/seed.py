from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import load_lake_config
from app.core.models import Lake
from app.core.time import iso, utcnow


def ensure_lake_seeded(db: Session) -> Lake:
    cfg = load_lake_config()
    existing = db.execute(select(Lake).where(Lake.slug == cfg["slug"])).scalar_one_or_none()
    if existing is not None:
        return existing

    lake = Lake(
        slug=cfg["slug"],
        name=cfg["name"],
        centroid_lat=cfg["centroid"]["lat"],
        centroid_lon=cfg["centroid"]["lon"],
        area_ha=cfg.get("geometry", {}).get("area_ha"),
        mean_depth_m=cfg.get("geometry", {}).get("mean_depth_m"),
        max_depth_m=cfg.get("geometry", {}).get("max_depth_m"),
        timezone=cfg.get("timezone", "Europe/Warsaw"),
        metar_station=cfg.get("weather", {}).get("secondary", {}).get("station"),
        metar_distance_km=cfg.get("weather", {}).get("secondary", {}).get("distance_km"),
        created_at=iso(utcnow()),
    )
    db.add(lake)
    db.flush()
    return lake
