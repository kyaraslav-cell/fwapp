"""Pull an okreg's own water map - names plus real boundaries - into YAML.

    python tools/pzw_okreg_map.py                      # Okreg Mazowiecki
    python tools/pzw_okreg_map.py --url ... --okreg ...

Okreg Mazowiecki publishes an interactive map at `https://ompzw.pl` whose page
embeds the whole dataset as JavaScript: one `objectsData[i]` record per water
(name, description, kind) and one `objectPoints[i]` array of `LatLng` giving
its **geometry**. 183 waters, and unlike either of the other two sources it
includes both of the owner's.

Why this source is worth having on top of the other two (ADR 0007):

  * the national register at pzw.pl is patchy per okreg - 108 Mazowiecki
    waters against the ~416 the okreg claims, and only 22 of those overlap
    with the okreg's own permit schedule;
  * neither of the others carries geometry, and geometry is what turns
    matching from "does this name look similar" into "does this water's
    position fall inside that water's boundary". Poland has five lakes called
    Czarne; it has only one at any given coordinate.

## `kind` is about geometry, not permission

`closed` is a closed ring - a lake, a reservoir, a pond. `open` is a polyline
- a river reach or a fishing district along one. Only a closed ring can
contain a point, so only those are written with a usable polygon. Nothing here
reads `kind` as "closed to fishing"; several waters marked `closed` are
ordinary lakes anyone may fish.

Run by hand when the okreg redraws its map. The output is committed and read
at runtime; the app never fetches this.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_URL = "https://ompzw.pl/okregi-wedkarskie"
DEFAULT_OKREG = "mazowiecki"
USER_AGENT = "Mozilla/5.0 (compatible; Fishlog/0.1; personal fishing log)"
TIMEOUT_S = 60.0

# One `objectsData[i] = {...}` record, up to the `objectPoints[i]` that follows
# it. Non-greedy and anchored on the following assignment, because the record's
# own description contains braces and quotes.
RECORD = re.compile(
    r"objectsData\[(?P<index>\d+)\]\s*=\s*\{(?P<body>.*?)\}\s*objectPoints\[(?P=index)\]"
    r"\s*=\s*\[(?P<points>.*?)\]\s*;",
    re.S,
)
FIELD = re.compile(r'"{name}"\s*:\s*"(?P<value>(?:[^"\\]|\\.)*)"')
LATLNG = re.compile(r"LatLng\(\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\)")

# A boundary this detailed is far more than a point-in-polygon test needs, and
# 17 000 coordinates would bloat a file the app reads at start-up.
MAX_POINTS = 160

CLOSED_RING = "closed"


@dataclass
class MapWater:
    name: str
    kind: str
    note: str = ""
    ring: list[tuple[float, float]] | None = None
    # The line a river district runs along. PZW cuts a river into numbered
    # districts - Narew nr 6, nr 7, nr 8 - and each is its own water with its
    # own rules; the map draws each as its own polyline. Discarding these kept
    # only the lakes and left every river district with nothing but a point.
    line: list[tuple[float, float]] | None = None
    # A representative position for EVERY water, ring or not. River reaches are
    # polylines and can never contain a point, but they still have a location,
    # and "how far is this water from me" is a question worth answering about
    # them.
    point: tuple[float, float] | None = None


def _decode(value: str) -> str:
    """JavaScript string escapes, then the HTML entities hiding inside them."""
    try:
        decoded = value.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        decoded = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), value)
        decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), decoded)
    decoded = html.unescape(decoded)
    decoded = decoded.replace("\xa0", " ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded)).strip()


def _field(body: str, name: str) -> str:
    match = re.search(FIELD.pattern.format(name=name), body, re.S)
    return _decode(match.group("value")) if match else ""


def _thin(points: list[tuple[float, float]], limit: int = MAX_POINTS) -> list[tuple[float, float]]:
    """Reduce a boundary, keeping its shape and its validity.

    Douglas-Peucker with `preserve_topology`, not every-Nth-point. Dropping
    points by index was the first attempt and it silently wrecked the
    boundaries it shortened: Zegrzynskie's 476-point ring came back
    self-intersecting, so `contains()` could not answer honestly about it.
    Simplification removes the points that carry least shape, and the topology
    flag guarantees the result is still a valid ring.
    """
    if len(points) <= limit:
        return points
    from shapely.geometry import Polygon

    # shapely is (x, y) = (lon, lat); this module's pairs are (lat, lon).
    polygon = Polygon([(lon, lat) for lat, lon in points])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.geom_type != "Polygon":
        return points[:limit]

    # Coarsen until it fits, starting far finer than needed. Degrees, so
    # 1e-5 is about a metre.
    tolerance = 1e-5
    simplified = polygon
    for _ in range(24):
        simplified = polygon.simplify(tolerance, preserve_topology=True)
        if simplified.geom_type == "Polygon" and len(simplified.exterior.coords) <= limit:
            break
        tolerance *= 1.6
    if simplified.geom_type != "Polygon":
        return points[:limit]
    return [(round(lat, 6), round(lon, 6)) for lon, lat in simplified.exterior.coords]


def _thin_line(
    points: list[tuple[float, float]], limit: int = MAX_POINTS
) -> list[tuple[float, float]]:
    """Reduce an open line, keeping its ends.

    Douglas-Peucker needs a ring; an open line is thinned by index instead,
    which is safe here because there is no topology to break - the failure mode
    that forced simplification on rings (a self-intersecting boundary that
    `contains()` could not answer about) does not exist for a line nobody asks
    containment questions of.
    """
    if len(points) <= limit:
        return points
    step = len(points) / float(limit - 1)
    kept = [points[int(i * step)] for i in range(limit - 1)]
    kept.append(points[-1])
    return kept


def parse(page: str) -> list[MapWater]:
    waters: list[MapWater] = []
    for match in RECORD.finditer(page):
        name = _field(match.group("body"), "nazwa")
        if not name:
            continue
        kind = _field(match.group("body"), "kind")
        points = [
            (round(float(lat), 6), round(float(lon), 6))
            for lat, lon in LATLNG.findall(match.group("points"))
        ]
        ring: list[tuple[float, float]] | None = None
        line: list[tuple[float, float]] | None = None
        # A ring needs three distinct corners before it encloses anything.
        if kind == CLOSED_RING and len(points) >= 3:
            ring = _thin(points)
        elif len(points) >= 2:
            line = _thin_line(points)
        note = _field(match.group("body"), "tresc")[:200]
        point = None
        if points:
            point = (
                round(sum(p[0] for p in points) / len(points), 6),
                round(sum(p[1] for p in points) / len(points), 6),
            )
        waters.append(
            MapWater(name=name, kind=kind, note=note, ring=ring, line=line, point=point)
        )
    return waters


def fetch(url: str) -> str:
    import httpx

    with httpx.Client(
        timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        response = client.get(url)
        if response.status_code != 200:
            raise SystemExit(f"{url} returned {response.status_code}")
        return response.text


def to_yaml(waters: list[MapWater], okreg: str, source: str) -> str:
    from app.discover.pzw import normalise

    lines = [
        "# An okreg's own water map: names and boundaries.",
        "#",
        "# GENERATED by tools/pzw_okreg_map.py from",
        f"# {source}",
        "# Do not hand-edit: re-run the tool.",
        "#",
        "# `ring` is a closed boundary as [lat, lon] pairs, thinned - it is used",
        "# for point-in-polygon matching, not for drawing. Waters without one are",
        "# river reaches, which are polylines and cannot contain a point.",
        f"okreg: {okreg}",
        "waters:",
    ]
    for water in sorted(waters, key=lambda w: (normalise(w.name), w.name)):
        key = normalise(water.name)
        if not key:
            continue
        lines.append(f"  - name: {water.name!r}")
        lines.append(f"    key: {key!r}")
        if water.note:
            lines.append(f"    note: {water.note!r}")
        if water.point:
            lines.append(f"    lat: {water.point[0]}")
            lines.append(f"    lon: {water.point[1]}")
        if water.ring:
            lines.append("    ring:")
            for lat, lon in water.ring:
                lines.append(f"      - [{lat}, {lon}]")
        if water.line:
            lines.append("    line:")
            for lat, lon in water.line:
                lines.append(f"      - [{lat}, {lon}]")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--okreg", default=DEFAULT_OKREG)
    parser.add_argument("--page", type=Path, help="parse a saved copy instead of fetching")
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args(argv)

    page = args.page.read_text(encoding="utf-8", errors="replace") if args.page else fetch(args.url)
    waters = parse(page)
    if not waters:
        raise SystemExit("no waters parsed - the page's markup has changed")

    out = args.out or Path(f"config/pzw/{args.okreg}-map.yaml")
    out.parent.mkdir(parents=True, exist_ok=True)
    open(out, "w", encoding="utf-8").write(to_yaml(waters, args.okreg, args.url))

    with_ring = sum(1 for w in waters if w.ring)
    print(f"{len(waters)} waters -> {out}")
    with_line = sum(1 for w in waters if w.line)
    print(f"  with a usable boundary: {with_ring}")
    print(f"  river/canal districts with a course: {with_line}")
    print(f"  with neither: {len(waters) - with_ring - with_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
