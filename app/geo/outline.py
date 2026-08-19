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


class OverpassUnavailableError(RuntimeError):
    """Overpass could not be reached or refused. Distinct from "no polygon".

    The difference decides a water's fate: an empty *answer* means this water
    genuinely has no shoreline in OpenStreetMap and never will until somebody
    maps it, while an unreachable *service* means try again in a minute.
    Collapsing them - which this module did until a live run caught it - marks
    a mapped lake as unmapped forever because of one timeout.
    """


def fetch_osm_outline(lat: float, lon: float, radius_m: int = 500) -> dict[str, Any] | None:
    """The water polygon nearest a point, or None for any reason at all.

    Kept lenient for the seeded lake, whose caller falls back to a committed
    file or an approximation and must not break on a network failure. Anything
    that has to tell "no polygon" from "no Overpass" calls
    `fetch_osm_outline_strict` instead.
    """
    try:
        return fetch_osm_outline_strict(lat, lon, radius_m)
    except OverpassUnavailableError:
        return None


def fetch_osm_outline_strict(
    lat: float, lon: float, radius_m: int = 500
) -> dict[str, Any] | None:
    """As above, but raises `OverpassUnavailableError` when the service failed.

    Returns None only when Overpass answered and there is genuinely no water
    polygon there.
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
        raise OverpassUnavailableError(f"{type(exc).__name__}: {exc}") from exc

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
