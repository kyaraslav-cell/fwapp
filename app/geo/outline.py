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


# A proximity search measures distance to a way's *geometry*, so the radius has
# to reach from the centroid to the bank. 500 m was right for a 9 ha pond and
# finds nothing at all on a 3 300 ha reservoir whose centroid sits a kilometre
# or more from any shoreline node. See `_radius_for_area`.
DEFAULT_RADIUS_M = 500
# Overpass is a shared service; an unbounded radius on a mistyped coordinate
# would be a large query asked of somebody else's server.
MAX_RADIUS_M = 20_000


def _radius_for_area(area_ha: float | None) -> int:
    """How far from the centroid the bank could be, given a rough area.

    The radius of a circle of the same area, with half again for a water that
    is long rather than round - which every reservoir on a river is. Below the
    default it stays at the default: a small pond gains nothing from a tighter
    search and loses a mapped neighbour whose centroid is slightly off.
    """
    if not area_ha or area_ha <= 0:
        return DEFAULT_RADIUS_M
    equivalent_radius = math.sqrt(area_ha * 10_000.0 / math.pi)
    return int(min(MAX_RADIUS_M, max(DEFAULT_RADIUS_M, equivalent_radius * 1.5)))


def fetch_osm_outline(
    lat: float,
    lon: float,
    radius_m: int | None = None,
    *,
    osm_type: str | None = None,
    osm_id: int | None = None,
    area_ha: float | None = None,
) -> dict[str, Any] | None:
    """The water polygon nearest a point, or None for any reason at all.

    Kept lenient for the seeded lake, whose caller falls back to a committed
    file or an approximation and must not break on a network failure. Anything
    that has to tell "no polygon" from "no Overpass" calls
    `fetch_osm_outline_strict` instead.
    """
    try:
        return fetch_osm_outline_strict(
            lat, lon, radius_m, osm_type=osm_type, osm_id=osm_id, area_ha=area_ha
        )
    except OverpassUnavailableError:
        return None


def _query_by_id(osm_type: str, osm_id: int) -> str:
    """Ask for exactly the object the geocoder already identified.

    This is the reliable path and the proximity search is the fallback, not the
    other way round: Nominatim has already told us *which* object the angler
    picked, and asking "what water is near this point" instead throws that
    away and re-derives it worse. It is also immune to the radius problem
    entirely - an object has no distance to itself.
    """
    kind = "relation" if osm_type.strip().lower().startswith("r") else "way"
    return f"""
    [out:json][timeout:25];
    {kind}({int(osm_id)});
    out geom;
    """


def fetch_osm_outline_strict(
    lat: float,
    lon: float,
    radius_m: int | None = None,
    *,
    osm_type: str | None = None,
    osm_id: int | None = None,
    area_ha: float | None = None,
) -> dict[str, Any] | None:
    """As above, but raises `OverpassUnavailableError` when the service failed.

    Returns None only when Overpass answered and there is genuinely no water
    polygon there.
    """
    if osm_type and osm_id:
        query = _query_by_id(osm_type, osm_id)
    else:
        radius = radius_m if radius_m is not None else _radius_for_area(area_ha)
        # Rivers are excluded explicitly: the Wkra runs past Pomocnia and its
        # polygon is far larger than the lake, so any "biggest wins" heuristic
        # picks the river instead of the target water.
        query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius},{lat},{lon})["natural"="water"]["water"!~"river|stream|canal|ditch"];
      relation(around:{radius},{lat},{lon})["natural"="water"]["water"!~"river|stream|canal|ditch"];
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
        for ring in _rings_of(element):
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


def _points(geometry: Any) -> list[list[float]]:
    if not isinstance(geometry, list):
        return []
    return [
        [p["lon"], p["lat"]]
        for p in geometry
        if isinstance(p, dict) and "lon" in p and "lat" in p
    ]


def _close(ring: list[list[float]]) -> list[list[float]] | None:
    if len(ring) < 4:
        return None
    if ring[0] != ring[-1]:
        ring = [*ring, ring[0]]
    return ring


def _stitch(segments: list[list[list[float]]]) -> list[list[list[float]]]:
    """Join way fragments end to end into closed rings.

    A large water is a multipolygon relation, and `out geom` hands its outer
    boundary back as however many separate ways the mappers happened to split
    it into - typically one per municipality boundary or per editing session.
    None of them is closed on its own.

    Shared nodes have identical coordinates in the same response, so exact
    comparison is right here and a tolerance would only invent joins that OSM
    does not have. A fragment that cannot be joined is dropped rather than
    forced: half a shoreline closed by a straight line across the water is a
    lie of exactly the kind ADR 0005 §4 refuses.
    """
    remaining = [list(seg) for seg in segments if len(seg) >= 2]
    rings: list[list[list[float]]] = []
    while remaining:
        current = remaining.pop(0)
        joined = True
        while joined and current[0] != current[-1]:
            joined = False
            for i, segment in enumerate(remaining):
                if segment[0] == current[-1]:
                    current = current + segment[1:]
                elif segment[-1] == current[-1]:
                    current = current + segment[-2::-1]
                elif segment[-1] == current[0]:
                    current = segment[:-1] + current
                elif segment[0] == current[0]:
                    current = segment[::-1][:-1] + current
                else:
                    continue
                remaining.pop(i)
                joined = True
                break
        closed = _close(current)
        if closed is not None and closed[0] == closed[-1]:
            rings.append(closed)
    return rings


def _rings_of(element: dict[str, Any]) -> list[list[list[float]]]:
    """Every closed outer ring an Overpass element carries.

    Two shapes arrive here and only one of them used to be read. A **way** has
    a top-level `geometry`. A **relation** has none - its shape lives in
    `members`, each with a `role`. Reading only `geometry` meant every
    multipolygon water was silently skipped, which is every water large enough
    to have islands or to have been mapped by more than one person. The lake
    then reported "no water polygon in OpenStreetMap near this point", which
    was untrue and unfalsifiable from the page.

    Inner rings - islands - are deliberately dropped for now: the grid builder
    takes a single ring, and a lake with an island scored as if the island were
    water is a smaller error than no lake at all. Recorded in docs/13 §11.
    """
    direct = _close(_points(element.get("geometry")))
    if direct is not None:
        return [direct]

    members = element.get("members")
    if not isinstance(members, list):
        return []
    outers = [
        _points(m.get("geometry"))
        for m in members
        if isinstance(m, dict) and m.get("role", "outer") in ("outer", "")
    ]
    return _stitch([seg for seg in outers if seg])
