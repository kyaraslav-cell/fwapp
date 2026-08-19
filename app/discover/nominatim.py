"""Name -> place, via OpenStreetMap's geocoder.

Nominatim's usage policy is strict and this app obeys all of it:

- **at most one request per second**, enforced process-wide here rather than
  per user, because the limit is per IP and every angler shares this one;
- a real User-Agent that identifies the app;
- results cached, so the same search never asks twice.

Free, open data, no key. The trade is that it is a shared community service:
it can be slow, and it can say no. Both fail closed - a search that cannot be
answered says so and creates nothing.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("fishlog.discover.nominatim")

SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Fishlog/0.1 (personal fishing log; contact via repo)"
TIMEOUT_S = 15.0
MIN_INTERVAL_S = 1.0
MAX_RESULTS = 8

# What counts as water. Nominatim's `class`/`type` pair; anything else is a
# village, a street or a bus stop with a lake's name.
WATER_TYPES = frozenset(
    {
        ("natural", "water"),
        ("water", "lake"),
        ("water", "pond"),
        ("water", "reservoir"),
        ("water", "basin"),
        ("water", "oxbow"),
        ("landuse", "reservoir"),
        ("landuse", "basin"),
        ("waterway", "riverbank"),
        ("leisure", "fishing"),
    }
)

_lock = threading.Lock()
_last_call_at = 0.0
_cache: dict[str, list[Candidate]] = {}


class NominatimError(RuntimeError):
    """The geocoder could not be reached, or refused."""


@dataclass(frozen=True)
class Candidate:
    """One place the geocoder thinks the name might mean."""

    name: str
    display_name: str
    lat: float
    lon: float
    osm_type: str
    osm_id: int
    kind: str          # "natural=water" etc, for the picker
    area_ha: float | None
    is_water: bool


def _throttle() -> None:
    """Block until a second has passed since the last call. Policy, not politeness."""
    global _last_call_at
    with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _area_ha_from_bbox(box: list[str] | None) -> float | None:
    """Rough area from the result's bounding box, in hectares.

    Only used to pick a grid resolution before the real polygon arrives, and to
    sort candidates. A bounding box overestimates any lake that is not square,
    which is why the real area replaces it as soon as there is an outline.
    """
    if not box or len(box) != 4:
        return None
    try:
        south, north, west, east = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    mid = math.radians((south + north) / 2.0)
    height_m = abs(north - south) * 111_320.0
    width_m = abs(east - west) * 111_320.0 * math.cos(mid)
    if height_m <= 0 or width_m <= 0:
        return None
    return round(height_m * width_m / 10_000.0, 2)


def _to_candidate(row: dict[str, Any]) -> Candidate | None:
    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    cls = str(row.get("class", ""))
    typ = str(row.get("type", ""))
    display = str(row.get("display_name", ""))
    return Candidate(
        name=display.split(",")[0].strip() or display,
        display_name=display,
        lat=lat,
        lon=lon,
        osm_type=str(row.get("osm_type", "")),
        osm_id=int(row.get("osm_id", 0) or 0),
        kind=f"{cls}={typ}" if cls else typ,
        area_ha=_area_ha_from_bbox(row.get("boundingbox")),
        is_water=(cls, typ) in WATER_TYPES,
    )


def search(name: str, *, country_codes: str = "pl", limit: int = MAX_RESULTS) -> list[Candidate]:
    """Look a water up by name. Water results first, non-water kept but marked.

    Non-water results are not thrown away: a fishery is often mapped as a
    `leisure` area or tagged oddly, and silently dropping everything that is not
    `natural=water` would make findable places look missing. They are marked so
    the picker can show them differently.
    """
    query = " ".join(name.split())
    if len(query) < 3:
        return []

    key = f"{country_codes}:{query.lower()}"
    if key in _cache:
        return _cache[key]

    _throttle()
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(limit),
        "addressdetails": "0",
        "countrycodes": country_codes,
    }
    try:
        with httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(SEARCH_URL, params=params)
            if response.status_code != 200:
                raise NominatimError(f"geocoder returned {response.status_code}")
            rows: list[dict[str, Any]] = response.json()
    except NominatimError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Nominatim search failed (%s: %s)", type(exc).__name__, exc)
        raise NominatimError(str(exc)) from exc

    candidates = [c for c in (_to_candidate(row) for row in rows) if c is not None]
    # Water first, then bigger first - the named water someone means is more
    # often the lake than the hamlet beside it.
    candidates.sort(key=lambda c: (not c.is_water, -(c.area_ha or 0.0)))
    _cache[key] = candidates
    return candidates
