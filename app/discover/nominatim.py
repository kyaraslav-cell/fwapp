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

# What counts as water.
#
# An exhaustive allowlist of `class`/`type` pairs was the first design and it
# was a trap. It was survivable while non-water results were still shown and
# merely marked; the moment the picker became waters-only, every kind missing
# from the list stopped being findable at all. `waterway=canal` was missing,
# so Kanał Żerański - a real PZW water in the Zegrzyński district - returned
# an empty page rather than a result.
#
# So the rule is now per category, and it fails OPEN: a whole OSM category is
# water, with a short exclusion list for the structures inside it. Getting it
# slightly too wide shows an angler one odd row they can ignore. Getting it too
# narrow tells them their water does not exist.
WATER_CATEGORIES = frozenset({"water", "natural", "waterway", "landuse", "leisure"})

# Inside those categories, the types that are not a water body. `weir`, `dam`
# and `lock_gate` are structures ON water; `wood` and `scrub` are `natural` but
# emphatically dry.
NOT_WATER_TYPES = frozenset(
    {
        "weir",
        "dam",
        "lock_gate",
        "sluice_gate",
        "waterfall",
        "boatyard",
        "water_point",
        "wood",
        "scrub",
        "heath",
        "grassland",
        "sand",
        "beach",
        "tree",
        "tree_row",
        "peak",
        "wetland",
        "park",
        "garden",
        "pitch",
        "playground",
        "sports_centre",
        "farmland",
        "meadow",
        "forest",
        "residential",
        "industrial",
        "commercial",
        "retail",
        "allotments",
        "cemetery",
        "quarry",
        "farmyard",
        "orchard",
        "vineyard",
        "grass",
    }
)

# `leisure` is mostly dry - pitches, parks, playgrounds - so it is the one
# category that keeps an allowlist rather than an exclusion list.
LEISURE_WATER_TYPES = frozenset({"fishing", "marina", "swimming_area", "water_park"})


def is_water_tag(category: str, type_name: str) -> bool:
    """Does this OSM class/type pair describe a water body?"""
    category = category.strip().lower()
    type_name = type_name.strip().lower()
    if category not in WATER_CATEGORIES:
        return False
    if type_name in NOT_WATER_TYPES:
        return False
    if category == "leisure":
        return type_name in LEISURE_WATER_TYPES
    if category == "landuse":
        return type_name in {"reservoir", "basin", "aquaculture", "salt_pond"}
    if category == "natural":
        return type_name in {"water", "spring", "bay", "strait", "lagoon"}
    # `water=*` and `waterway=*` are water by definition, minus the structures
    # excluded above: lake, pond, reservoir, oxbow, canal, river, riverbank,
    # stream, ditch, drain, dock.
    return True


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
    kind: str          # "natural=water" etc, shown on the picker card
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
    # `jsonv2` renames `class` to `category`. Reading only `class` made every
    # result - Zalew Zegrzynski included - come back with an empty category,
    # never match WATER_TYPES, and be refused as "not a water". The whole
    # add-a-water flow was dead, and the tests did not catch it because the
    # fixtures were written to match the code rather than the API.
    # Both names are read so the parser survives a format change either way.
    cls = str(row.get("category") or row.get("class") or "")
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
        is_water=is_water_tag(cls, typ),
    )


def search(name: str, *, country_codes: str = "pl", limit: int = MAX_RESULTS) -> list[Candidate]:
    """Look a water up by name. Waters only - villages and streets are dropped.

    Non-water results used to be kept and merely marked, on the theory that a
    fishery is sometimes tagged oddly and hiding it would make a findable place
    look missing. In practice the opposite happened: searching a lake's name in
    Poland returns the village, the gmina and the street of the same name
    first, and the angler had to read tag labels to find the water. The lake is
    what the app is for, so the lake is what the picker offers.

    `is_water_tag` fails open by design - see its comment. An allowlist of
    tag pairs looked tidy and hid `waterway=canal`, so a real PZW water
    returned an empty page. Showing one odd row costs a glance; hiding a water
    costs the whole feature.
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

    candidates = [c for c in (_to_candidate(row) for row in rows) if c is not None and c.is_water]
    # Bigger first - the named water someone means is more often the reservoir
    # than the farm pond sharing its name.
    candidates.sort(key=lambda c: -(c.area_ha or 0.0))
    _cache[key] = candidates
    return candidates
