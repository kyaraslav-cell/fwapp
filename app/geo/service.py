from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import CONFIG_DIR
from app.core.models import Lake
from app.geo.demo_zones import approximate_outline_geojson
from app.geo.grid import LakeGrid, build_grid, geometry_inputs
from app.geo.outline import fetch_osm_outline

logger = logging.getLogger("fishlog.geo.service")

DEFAULT_CELL_M = 5.0

# Overpass and the grid maths are both too slow to run per request, and the
# outline never changes - so both are cached. Outline is cached in the database,
# grid and fetch fields in process.
_grid_cache: dict[tuple[int, float], LakeGrid] = {}
_fetch_cache: dict[tuple[int, float, int], list[tuple[int, int, float, float]]] = {}


def outline_file(slug: str) -> Path:
    """Where a surveyed outline lives once it has been captured to the repo."""
    return CONFIG_DIR / "lakes" / f"{slug}.outline.geojson"


def ensure_outline(db: Session, lake: Lake) -> dict[str, Any]:
    """Return the lake's water polygon.

    Order matters, and the first step is the one that fixes a real bug. The
    shoreline never changes, so fetching it from Overpass on every build was
    always the wrong shape of solution - and it failed in exactly the place it
    mattered: GitHub's runners share heavily rate-limited cloud IPs, so the
    published site kept falling back to a CIRCLE while a developer machine with
    ordinary network got the true polygon. Same code, two different lakes on
    screen.

    So a committed `config/lakes/<slug>.outline.geojson` wins over everything.
    Capture it once with `python tools/save_outline.py` from a machine that can
    reach Overpass, commit it, and every build afterwards draws the real shore
    with no network call at all.

    Order: committed file -> database cache -> Overpass -> circle. The source is
    recorded either way so the UI can say which one you are looking at rather
    than implying the crude shape is surveyed truth.
    """
    surveyed = outline_file(lake.slug)
    if surveyed.is_file():
        stored: dict[str, Any] = json.loads(surveyed.read_text(encoding="utf-8"))
        if not lake.outline_geojson:
            lake.outline_geojson = json.dumps(stored)
            db.flush()
        lake.outline_source = "osm_committed"
        return stored

    if lake.outline_geojson:
        outline: dict[str, Any] = json.loads(lake.outline_geojson)
        return outline

    osm = fetch_osm_outline(lake.centroid_lat, lake.centroid_lon)
    if osm is not None:
        lake.outline_geojson = json.dumps(osm)
        lake.outline_source = "osm"
        db.flush()
        logger.info("cached OSM outline for %s", lake.slug)
        return osm

    fallback = approximate_outline_geojson(
        lake.centroid_lat, lake.centroid_lon, lake.area_ha or 9.0
    )
    # Not persisted: a later run with working network should still get the real
    # outline rather than being stuck with the approximation forever.
    lake.outline_source = "circle_fallback"
    return fallback


def get_grid(lake: Lake, outline: dict[str, Any], cell_m: float = DEFAULT_CELL_M) -> LakeGrid:
    key = (lake.id, cell_m)
    if key not in _grid_cache:
        _grid_cache[key] = build_grid(outline, cell_m)
    return _grid_cache[key]


def get_geometry_inputs(
    lake: Lake, outline: dict[str, Any], grid: LakeGrid, wind_from_deg: float
) -> list[tuple[int, int, float, float]]:
    """[(row, col, fetch_m, shore_m)], cached per wind direction bucket."""
    # Rounded to 10 degrees: finer than the wind data justifies, and keeps the
    # cache small.
    bucket = int(round(wind_from_deg / 10.0) * 10) % 360
    key = (lake.id, grid.cell_m, bucket)
    if key not in _fetch_cache:
        _fetch_cache[key] = geometry_inputs(outline, grid, float(bucket))
    return _fetch_cache[key]


def invalidate(lake_id: int) -> None:
    for key in [k for k in _grid_cache if k[0] == lake_id]:
        del _grid_cache[key]
    for key in [k for k in _fetch_cache if k[0] == lake_id]:
        del _fetch_cache[key]
