from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import load_lake_config
from app.core.models import Lake, Zone
from app.core.time import iso, utcnow
from app.geo.demo_zones import demo_zones

DEMO_ZONE_NOTE = (
    "DEMO ZONE — placeholder wedge geometry, not surveyed. Redraw on the "
    "satellite map once the owner maps Pomocnia for real."
)


def ensure_lake_seeded(db: Session) -> Lake:
    cfg = load_lake_config()
    existing = db.execute(select(Lake).where(Lake.slug == cfg["slug"])).scalar_one_or_none()
    if existing is not None:
        _ensure_demo_zones_seeded(db, existing)
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
    _ensure_demo_zones_seeded(db, lake)
    return lake


def _ensure_demo_zones_seeded(db: Session, lake: Lake) -> None:
    existing = db.execute(select(Zone).where(Zone.lake_id == lake.id)).first()
    if existing is not None:
        return
    if lake.area_ha is None:
        return

    for zdef in demo_zones(lake.centroid_lat, lake.centroid_lon, lake.area_ha):
        db.add(
            Zone(
                lake_id=lake.id,
                name=zdef.name,
                polygon_geojson=json.dumps(zdef.polygon_geojson),
                mean_depth_m=lake.mean_depth_m,
                bank_aspect_deg=zdef.bank_aspect_deg,
                access_notes=DEMO_ZONE_NOTE,
                is_active=1,
            )
        )
    db.flush()
