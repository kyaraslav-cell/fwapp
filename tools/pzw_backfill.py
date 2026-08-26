"""Set `water_type` and the PZW name on waters added before the registry existed.

Every water the add-a-water pipeline created before ADR 0007 has
`water_type = NULL`, because nothing ever set it. That is not cosmetic: it is
the segmentation key for every CPUE aggregate, and `assert_comparable` refuses
to pool sessions across waters whose type nobody recorded (law 3).

    python tools/pzw_backfill.py --dry-run     # say what would change
    python tools/pzw_backfill.py               # do it

Only fills blanks. A water that already has a `water_type` is never
overwritten - if a human answered, that answer stands, and this tool is not
entitled to second-guess it. Renaming likewise only applies to waters this run
actually matched, and always keeps the OSM name in `name_osm`.

Waters the registry cannot identify are listed and left alone. They need a
human answer; see `--set`.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.db import init_db, session_scope
from app.core.models import Lake
from app.discover import pzw
from app.discover.service import SOURCE_ANGLER, SOURCE_REGISTRY
from app.notebook import water_type as water_type_mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="SLUG=TYPE",
        help="answer for a water the registry does not list, e.g. lowisko-x=commercial",
    )
    args = parser.parse_args(argv)

    manual: dict[str, str] = {}
    for pair in args.set:
        slug, _, value = pair.partition("=")
        normalised = water_type_mod.normalise(value)
        if not slug or normalised is None:
            parser.error(f"--set expects SLUG=pzw or SLUG=commercial, got {pair!r}")
        manual[slug] = normalised

    init_db()
    unresolved: list[str] = []
    with session_scope() as db:
        for lake in db.execute(select(Lake).order_by(Lake.id)).scalars().all():
            listed = pzw.lookup(lake.name_osm or lake.name)
            answer = manual.get(lake.slug)

            changes: list[str] = []
            if lake.water_type is None:
                if answer is not None:
                    changes.append(f"water_type={answer} (angler)")
                    if not args.dry_run:
                        lake.water_type = answer
                        lake.water_type_source = SOURCE_ANGLER
                elif listed is not None:
                    changes.append(f"water_type=pzw (registry: {listed.water.name})")
                    if not args.dry_run:
                        lake.water_type = water_type_mod.PZW
                        lake.water_type_source = SOURCE_REGISTRY
                else:
                    unresolved.append(lake.slug)

            # Rename only where the registry identified the water and the name
            # actually differs. The OSM spelling is kept, never dropped.
            #
            # The seeded water is exempt: its name comes from
            # config/lakes/*.yaml and is re-applied at boot, so renaming it in
            # the database would either be undone or fight the seed forever.
            renameable = lake.origin != "seed"
            if renameable and listed is not None and listed.water.name != lake.name:
                changes.append(f"name {lake.name!r} -> {listed.water.name!r}")
                if not args.dry_run:
                    if not lake.name_osm:
                        lake.name_osm = lake.name
                    lake.name = listed.water.name
            if listed is not None and not lake.pzw_key and not args.dry_run:
                lake.pzw_key = listed.water.key

            if changes:
                print(f"{lake.slug}: {'; '.join(changes)}")

        if args.dry_run:
            db.rollback()

    if unresolved:
        print("\nNot on the PZW list - these need an answer:")
        for slug in unresolved:
            print(f"  {slug}    (--set {slug}=commercial, or =pzw)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
