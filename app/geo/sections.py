"""A river district split into fishable stretches. Pure - no I/O, no clock.

A lake gets a 2D grid because an angler on one picks a *spot* in open water.
A river is not fished that way: you pick a **stretch** and work it, so the unit
that matters is a length of bank, not a square of surface.

That is also the only honest option here. A river or canal has no polygon in
OpenStreetMap - only the line it runs along (`fetch_osm_course`) - and a grid
needs an area to clip against. Buffering the centreline by a guessed width
would manufacture both a shoreline and an overlay, which is the fabrication
ADR 0005 §4 refuses.

**Sections carry no score yet, and that is deliberate.** The zone model is
built from wind fetch and distance-to-bank (`config/rules.v0.3.yaml`), and
neither means anything on a 25 m canal: every point is a metre from the bank
and there is no fetch to speak of. What actually decides a river swim - flow,
depth, structure, confluences, weed - is not modelled at all
(`docs/09-BACKLOG.md §15`). So this divides the water honestly and leaves the
colour to a river model that does not exist yet. Colouring them from the lake
model would look authoritative and mean nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# How long a stretch is. Long enough that a section is a decision an angler
# would actually make - "the bend below the bridge" - and short enough that a
# district is a handful of them rather than one.
DEFAULT_SECTION_M = 500.0

# Below this a district is one section: splitting a 300 m canal spur into two
# tells nobody anything.
MIN_SECTIONS = 1
MAX_SECTIONS = 120

# Roughly how many stretches a district should offer. A 78 km district cut
# every 500 m is 157 choices, which is not a choice at all; the same district
# in 40 is a list somebody can read.
TARGET_SECTIONS = 40
MIN_SECTION_M = 250.0
MAX_SECTION_M = 2500.0

M_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class Section:
    """One fishable stretch of a district."""

    index: int
    points: tuple[tuple[float, float], ...]   # (lat, lon), in order along the water
    length_m: float
    start_m: float

    @property
    def midpoint(self) -> tuple[float, float]:
        """Where to put a label or a marker for this stretch."""
        target = self.length_m / 2.0
        walked = 0.0
        for a, b in zip(self.points, self.points[1:], strict=False):
            step = _metres(a, b)
            if walked + step >= target and step > 0:
                fraction = (target - walked) / step
                return (
                    a[0] + (b[0] - a[0]) * fraction,
                    a[1] + (b[1] - a[1]) * fraction,
                )
            walked += step
        return self.points[len(self.points) // 2]


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Flat-earth distance between two (lat, lon) points, in metres."""
    mid = math.radians((a[0] + b[0]) / 2.0)
    dy = (a[0] - b[0]) * M_PER_DEG_LAT
    dx = (a[1] - b[1]) * M_PER_DEG_LAT * math.cos(mid)
    return math.hypot(dx, dy)


def _lines_from(course: dict[str, Any] | None) -> list[list[tuple[float, float]]]:
    """GeoJSON (lon, lat) -> lines of (lat, lon)."""
    if not course:
        return []
    kind = course.get("type")
    raw = course.get("coordinates") or []
    if kind == "LineString":
        groups = [raw]
    elif kind == "MultiLineString":
        groups = list(raw)
    else:
        return []

    out: list[list[tuple[float, float]]] = []
    for group in groups:
        line = [
            (float(point[1]), float(point[0]))
            for point in group
            if isinstance(point, list | tuple) and len(point) >= 2
        ]
        if len(line) >= 2:
            out.append(line)
    return out


def suggested_section_m(course: dict[str, Any] | None) -> float:
    """A stretch length that suits this district's size.

    A fixed 500 m turns a 78 km river into 157 sections and a 2 km canal spur
    into four. Aiming for a readable number of stretches instead keeps both
    useful, clamped so a section is never shorter than a swim or longer than a
    day's walking.
    """
    total = course_length_m(course)
    if total <= 0:
        return DEFAULT_SECTION_M
    ideal = total / TARGET_SECTIONS
    return float(min(MAX_SECTION_M, max(MIN_SECTION_M, round(ideal / 50.0) * 50.0)))


def split_course(
    course: dict[str, Any] | None, *, section_m: float | None = None
) -> list[Section]:
    """Cut a district's course into stretches of roughly `section_m`.

    Each mapped line is cut separately and never joined across a gap: two
    segments of a district can be kilometres apart - the Narew nr 7 district
    carries the Narew and an arm of the Bug - and a stretch spanning the gap
    would be a piece of water that does not exist.

    A section boundary lands wherever the running length crosses the target, so
    sections are approximately equal rather than exactly: moving a real
    coordinate to make them exact would move the water.
    """
    if section_m is None:
        section_m = suggested_section_m(course)

    sections: list[Section] = []
    index = 0
    for line in _lines_from(course):
        current: list[tuple[float, float]] = [line[0]]
        run = 0.0
        travelled = 0.0
        start_m = 0.0
        for a, b in zip(line, line[1:], strict=False):
            step = _metres(a, b)
            # A boundary is cut where it falls, part way along a segment, not
            # at the next mapped vertex. The course is thinned to 160 points,
            # so vertices can be a kilometre apart and boundaries snapped to
            # them made "500 m" sections that ran to 1 100 m.
            while step > 0 and run + step >= section_m and index < MAX_SECTIONS:
                remaining = section_m - run
                fraction = remaining / step
                cut = (
                    a[0] + (b[0] - a[0]) * fraction,
                    a[1] + (b[1] - a[1]) * fraction,
                )
                current.append(cut)
                sections.append(
                    Section(
                        index=index,
                        points=tuple(current),
                        length_m=round(section_m, 1),
                        start_m=round(start_m, 1),
                    )
                )
                index += 1
                travelled += remaining
                start_m = travelled
                current = [cut]
                a = cut
                step -= remaining
                run = 0.0
            current.append(b)
            run += step
            travelled += step
            if index >= MAX_SECTIONS:
                break
        # The tail. Folded into the previous stretch when it is a stub, because
        # a 40 m section beside a 500 m one is not a choice anybody makes.
        if len(current) >= 2 and run > 0:
            if run < section_m * 0.35 and sections:
                previous = sections.pop()
                sections.append(
                    Section(
                        index=previous.index,
                        points=previous.points + tuple(current[1:]),
                        length_m=round(previous.length_m + run, 1),
                        start_m=previous.start_m,
                    )
                )
            else:
                sections.append(
                    Section(
                        index=index,
                        points=tuple(current),
                        length_m=round(run, 1),
                        start_m=round(start_m, 1),
                    )
                )
                index += 1
    return sections


def course_length_m(course: dict[str, Any] | None) -> float:
    """How much water this district actually is."""
    total = 0.0
    for line in _lines_from(course):
        for a, b in zip(line, line[1:], strict=False):
            total += _metres(a, b)
    return round(total, 1)


def to_geojson(sections: list[Section]) -> dict[str, Any]:
    """Sections as a FeatureCollection the map can draw.

    No score and no colour: see this module's docstring. The properties carry
    what is actually known - which stretch it is, how long, and how far along
    the district it starts.
    """
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lat, lon in section.points],
                },
                "properties": {
                    "index": section.index,
                    "length_m": section.length_m,
                    "start_m": section.start_m,
                    "mid_lat": round(section.midpoint[0], 6),
                    "mid_lon": round(section.midpoint[1], 6),
                },
            }
            for section in sections
        ],
    }
