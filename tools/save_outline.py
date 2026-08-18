"""Capture the lake's real shoreline into the repository, once.

THE BUG THIS FIXES. `ensure_outline` used to fetch the polygon from Overpass at
build time. Overpass rate-limits cloud IP ranges hard, so the GitHub Actions
runner kept failing and falling back to a CIRCLE - while any developer machine
with ordinary network got the true outline. Identical code, two completely
different lakes on screen, and the published map was scoring a circle that does
not exist.

The shoreline does not change. It should be captured once, committed, and read
from disk forever after - no network call in the build at all.

Run this from somewhere that can reach Overpass (a Codespace, a laptop):

    python tools/save_outline.py            # fetch, or export what the DB cached
    python tools/save_outline.py --force    # re-fetch even if a file exists

then commit `config/lakes/<slug>.outline.geojson`. Nothing else needs changing:
the next build picks it up and `outline_source` reads `osm_committed`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import init_db, session_scope  # noqa: E402
from app.core.models import Lake  # noqa: E402
from app.geo.outline import fetch_osm_outline  # noqa: E402
from app.geo.service import outline_file  # noqa: E402


def ring_of(geojson: dict) -> list:
    coords = geojson.get("coordinates") or []
    return coords[0] if coords else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", default="pomocnia")
    parser.add_argument("--force", action="store_true", help="re-fetch over an existing file")
    args = parser.parse_args()

    target = outline_file(args.slug)
    if target.is_file() and not args.force:
        existing = json.loads(target.read_text(encoding="utf-8"))
        print(f"{target} already exists ({len(ring_of(existing))} points). Use --force to replace.")
        return 0

    init_db()
    with session_scope() as db:
        lake = db.execute(select(Lake).where(Lake.slug == args.slug)).scalar_one_or_none()
        if lake is None:
            print(f"no lake {args.slug!r} - start the app once to seed it", file=sys.stderr)
            return 2

        outline = fetch_osm_outline(lake.centroid_lat, lake.centroid_lon)
        source = "overpass"
        if outline is None and lake.outline_geojson:
            # Overpass is unreachable but this database already holds a real
            # polygon from an earlier successful run - that is just as good, and
            # it is why this tool is worth running even on a bad connection.
            outline = json.loads(lake.outline_geojson)
            source = "database cache"

        if outline is None:
            print(
                "could not obtain a real outline: Overpass unreachable and no polygon "
                "cached in this database. Run this from a machine with normal network.",
                file=sys.stderr,
            )
            return 1

        ring = ring_of(outline)
        if len(ring) < 8:
            # A circle fallback has a smooth, regular ring. Committing one would
            # bake the very bug this tool exists to remove.
            print(f"refusing to save: only {len(ring)} points, that is not a surveyed shore",
                  file=sys.stderr)
            return 1

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(outline, indent=1), encoding="utf-8")

    print(f"wrote {target}")
    print(f"  {len(ring)} boundary points, from {source}")
    print("  commit this file - the published build will stop drawing a circle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
