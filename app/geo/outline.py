from __future__ import annotations

import logging
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
    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius_m},{lat},{lon})["natural"="water"];
      relation(around:{radius_m},{lat},{lon})["natural"="water"];
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

    best: list[list[float]] | None = None
    best_area = 0.0

    for element in data.get("elements", []):
        geometry = element.get("geometry")
        if not geometry:
            continue
        ring = [[p["lon"], p["lat"]] for p in geometry if "lon" in p and "lat" in p]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        area = _ring_area_deg(ring)
        if area > best_area:
            best_area = area
            best = ring

    if best is None:
        logger.warning("Overpass returned no usable water polygon near %s,%s", lat, lon)
        return None

    return {"type": "Polygon", "coordinates": [best]}


def _ring_area_deg(ring: list[list[float]]) -> float:
    """Shoelace area in square degrees. Only used to pick the largest candidate."""
    total = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0
