"""Turn a river added as one OSM object into the PZW district it really is.

    python tools/pzw_district_convert.py --dry-run
    python tools/pzw_district_convert.py --slug narew

PZW cuts a river into numbered districts - Narew nr 6, nr 7, nr 8 - and each
is a separate water with its own permit, closed seasons, size limits and catch
statistics. A river added through the OSM search is one arbitrary way: neither
the whole river nor any one district, and pooling it across several sets of
rules is exactly the corruption law 3 exists to prevent.

This finds the district a water's position falls nearest to and converts the
row in place: PZW's name, PZW's stretch of course, the district's registry
key. **Nothing is deleted.** The row keeps its id, so its weather history, its
prediction rows (immutable evidence, law 2) and any sessions logged on it
survive the rename.

It refuses when the nearest district is further away than `--max-km`, because
a water that is not near any listed district is not a district and guessing
would put a wrong permit on somebody's fishing.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db, session_scope  # noqa: E402
from app.core.models import Lake  # noqa: E402
from app.discover import pzw  # noqa: E402
from app.notebook import water_type as water_type_mod  # noqa: E402

DEFAULT_MAX_KM = 8.0


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mid = math.radians((lat1 + lat2) / 2.0)
    return math.hypot((lon1 - lon2) * 111.320 * math.cos(mid), (lat1 - lat2) * 111.320)


def nearest_district(lat: float, lon: float) -> tuple[pzw.PzwWater, float] | None:
    """The listed district whose course passes closest to this point.

    Distance to the nearest vertex, not to the nearest segment: these courses
    carry up to 160 points over a few tens of kilometres, so the two answers
    differ by less than the uncertainty in the position being tested.
    """
    best: tuple[pzw.PzwWater, float] | None = None
    for water in pzw.registry():
        if not pzw.is_district(water) or not water.line:
            continue
        distance = min(km_between(lat, lon, p[0], p[1]) for p in water.line)
        if best is None or distance < best[1]:
            best = (water, distance)
    return best


def convert(lake: Lake, district: pzw.PzwWater) -> list[str]:
    changes: list[str] = []
    if lake.name != district.name:
        changes.append(f"name {lake.name!r} -> {district.name!r}")
        if not lake.name_osm:
            lake.name_osm = lake.name
        lake.name = district.name
    if lake.pzw_key != district.key:
        changes.append(f"pzw_key -> {district.key!r}")
        lake.pzw_key = district.key
    if district.line:
        course = {
            "type": "MultiLineString",
            "coordinates": [[[lon, lat] for lat, lon in district.line]],
        }
        lake.course_geojson = json.dumps(course)
        # The district's stretch replaces whatever OSM polygon was picked up:
        # that polygon is a fragment of a different water from this district.
        lake.outline_geojson = None
        lake.outline_source = "pzw_line"
        lake.centroid_lat = sum(p[0] for p in district.line) / len(district.line)
        lake.centroid_lon = sum(p[1] for p in district.line) / len(district.line)
        changes.append(f"course -> {len(district.line)} points from the okreg map")
    if lake.water_type != water_type_mod.PZW:
        lake.water_type = water_type_mod.PZW
        changes.append("water_type -> pzw")
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", action="append", default=[], help="convert only these waters")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-km", type=float, default=DEFAULT_MAX_KM)
    parser.add_argument(
        "--to",
        default=None,
        metavar="PZW_KEY",
        help=(
            "convert to this district explicitly, skipping the distance check. "
            "For a water on a stretch whose okreg map has not been imported - "
            "the geometry search can only find districts we actually hold."
        ),
    )
    args = parser.parse_args(argv)

    init_db()
    with session_scope() as db:
        query = db.query(Lake)
        if args.slug:
            query = query.filter(Lake.slug.in_(args.slug))
        for lake in query.order_by(Lake.id).all():
            # Already a district, or never a river: nothing to do.
            if lake.pzw_key and pzw.is_district(pzw.by_key(lake.pzw_key) or lake):  # type: ignore[arg-type]
                continue
            if args.to:
                chosen = pzw.by_key(args.to)
                if chosen is None:
                    parser.error(f"no listed water with key {args.to!r}")
                changes = convert(lake, chosen)
                print(f"{lake.slug}: (chosen by hand) " + "; ".join(changes))
                continue

            found = nearest_district(lake.centroid_lat, lake.centroid_lon)
            if found is None:
                continue
            district, distance = found
            if distance > args.max_km:
                if args.slug:
                    print(
                        f"{lake.slug}: nearest district is {district.name!r} at "
                        f"{distance:.1f} km - beyond --max-km {args.max_km}, refusing to guess"
                    )
                continue
            changes = convert(lake, district)
            if changes:
                print(f"{lake.slug}: ({distance:.1f} km) " + "; ".join(changes))
        if args.dry_run:
            db.rollback()
            print("\n(dry run - nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
