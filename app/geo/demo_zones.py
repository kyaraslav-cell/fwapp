from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

METERS_PER_DEGREE_LAT = 111_320.0

DEMO_SECTORS = [
    ("North bank", 0.0),
    ("East bank", 90.0),
    ("South bank", 180.0),
    ("West bank", 270.0),
]


@dataclass(frozen=True)
class DemoZoneDef:
    name: str
    bank_aspect_deg: float
    polygon_geojson: dict[str, Any]


def _offset(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """Pure. Flat-earth approximation, fine at lake scale (a few hundred metres)."""
    bearing = math.radians(bearing_deg)
    dx = distance_m * math.sin(bearing)
    dy = distance_m * math.cos(bearing)
    dlat = dy / METERS_PER_DEGREE_LAT
    meters_per_degree_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))
    dlon = dx / meters_per_degree_lon
    return lat + dlat, lon + dlon


def lake_radius_m(area_ha: float) -> float:
    area_m2 = area_ha * 10_000.0
    return math.sqrt(area_m2 / math.pi)


def approximate_outline_geojson(lat: float, lon: float, area_ha: float) -> dict[str, Any]:
    """Pure. A circle of the lake's known area, NOT the real OSM outline.
    Placeholder for visualisation only until Phase 1 auto-resolve runs."""
    r = lake_radius_m(area_ha)
    coords = []
    for bearing in range(0, 361, 15):
        plat, plon = _offset(lat, lon, float(bearing), r)
        coords.append([plon, plat])
    return {"type": "Polygon", "coordinates": [coords]}


def demo_zones(lat: float, lon: float, area_ha: float) -> list[DemoZoneDef]:
    """Pure. Four wedge-shaped placeholder zones split N/E/S/W from the lake
    centroid, sized to the lake's real area. NOT real zone geometry — the
    owner redraws these on the satellite map once mapped for real."""
    r = lake_radius_m(area_ha)
    zones = []
    for name, center_bearing in DEMO_SECTORS:
        coords = [[lon, lat]]
        for offset_deg in range(-45, 46, 9):
            bearing = center_bearing + offset_deg
            plat, plon = _offset(lat, lon, bearing, r)
            coords.append([plon, plat])
        coords.append([lon, lat])
        zones.append(
            DemoZoneDef(
                name=name,
                bank_aspect_deg=center_bearing,
                polygon_geojson={"type": "Polygon", "coordinates": [coords]},
            )
        )
    return zones
