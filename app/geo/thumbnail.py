"""A water's own shape, small enough for a list row. Pure - no I/O, no clock.

The home page used to show the same gradient square on every card regardless
of which water it was - Pomocnia's round bowl and Zegrzynski's long reservoir
looked identical. This turns the outline every water already carries
(`app/geo/outline.py`, `water_outline()` in `app/web/routes/places.py`) into
an SVG path sized for that card, so the icon *is* the water rather than
decoration next to its name.
"""

from __future__ import annotations

from typing import Any

# A real shoreline can carry thousands of points (Zalew Zegrzynski's outer
# ring has ~2 700). None of that detail survives at list-icon size, and
# sending it all to the page on every request is the opposite of "lightweight" -
# so this is the one place a water's outline gets deliberately thrown away.
MAX_POINTS = 120


def outline_thumbnail_path(
    outline_geojson: dict[str, Any] | None,
    *,
    size: float = 56.0,
    padding: float = 4.0,
    max_points: int = MAX_POINTS,
) -> str | None:
    """The outer ring of a GeoJSON `Polygon`, as an SVG path `d` fit to `size`.

    Plain lon/lat, not a projection - a projection earns its cost when
    accuracy matters (`app/geo/grid.py`); a 56 px icon cannot show the
    difference. Returns None for anything that is not a non-empty `Polygon`,
    which the caller reads as "fall back to the plain icon" rather than
    rendering an empty shape.
    """
    if not outline_geojson or outline_geojson.get("type") != "Polygon":
        return None
    rings = outline_geojson.get("coordinates")
    if not rings or not rings[0] or len(rings[0]) < 3:
        return None

    ring: list[list[float]] = rings[0]
    if len(ring) > max_points:
        step = len(ring) / max_points
        ring = [ring[int(i * step)] for i in range(max_points)]

    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    span_lon = max_lon - min_lon or 1e-9
    span_lat = max_lat - min_lat or 1e-9

    usable = size - 2 * padding
    scale = usable / max(span_lon, span_lat)
    off_x = padding + (usable - span_lon * scale) / 2
    off_y = padding + (usable - span_lat * scale) / 2

    points = []
    for lon, lat in ring:
        x = off_x + (lon - min_lon) * scale
        # SVG y grows downward; latitude grows north, so this flips it upright.
        y = off_y + (max_lat - lat) * scale
        points.append(f"{x:.1f},{y:.1f}")

    return "M " + " L ".join(points) + " Z"
