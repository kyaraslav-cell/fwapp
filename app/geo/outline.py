from __future__ import annotations

import logging
import math
from typing import Any

import httpx

logger = logging.getLogger("fishlog.geo.outline")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass usage policy: real User-Agent, cached aggressively, never called
# from a request handler. See docs/05-ARCHITECTURE.md.
USER_AGENT = "Fishlog/0.1 (personal fishing log; one lake; contact via repo)"


def fetch_osm_outline(lat: float, lon: float, radius_m: int = 500) -> dict[str, Any] | None:
    """Fetch the water polygon nearest the given point from OpenStreetMap.

    Returns a GeoJSON Polygon dict, or None if nothing usable came back.
    Never raises on network failure - the caller falls back to an approximation.
    """
    # Rivers are excluded explicitly: the Wkra runs past Pomocnia and its
    # polygon is far larger than the lake, so any "biggest wins" heuristic
    # picks the river instead of the target water.
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius_m},{lat},{lon})["natural"="water"]["water"!~"river|stream|canal|ditch"];
      relation(around:{radius_m},{lat},{lon})["natural"="water"]["water"!~"river|stream|canal|ditch"];
    );
    out geom;
    """
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Overpass fetch failed (%s: %s)", type(exc).__name__, exc)
        return None

    candidates: list[tuple[list[list[float]], float]] = []
    for element in data.get("elements", []):
        geometry = element.get("geometry")
        if not geometry:
            continue
        ring = [[p["lon"], p["lat"]] for p in geometry if "lon" in p and "lat" in p]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        candidates.append((ring, _ring_area_deg(ring)))

    if not candidates:
        logger.warning("Overpass returned no usable water polygon near %s,%s", lat, lon)
        return None

    # Containment first. Picking the biggest polygon is wrong near a river:
    # the water we want is the one the lake's own coordinates fall inside.
    containing = [(ring, area) for ring, area in candidates if _point_in_ring(lon, lat, ring)]
    if containing:
        ring, _ = max(containing, key=lambda c: c[1])
        return {"type": "Polygon", "coordinates": [ring]}

    # Nothing contains the point (coordinates slightly off, or a crude
    # outline): fall back to whichever polygon comes nearest to it, NOT the
    # largest one.
    ring = min(candidates, key=lambda c: _min_distance_deg(lon, lat, c[0]))[0]
    logger.warning("no OSM polygon contained %s,%s - using the nearest instead", lat, lon)
    return {"type": "Polygon", "coordinates": [ring]}


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    """Standard ray-casting point-in-polygon, in degrees."""
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < x_cross:
                inside = not inside
    return inside


def _min_distance_deg(x: float, y: float, ring: list[list[float]]) -> float:
    return min(math.hypot(px - x, py - y) for px, py in ring)


def _ring_area_deg(ring: list[list[float]]) -> float:
    """Shoelace area in square degrees. Only used to pick the largest candidate."""
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0
