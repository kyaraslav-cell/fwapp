"""Close ingest gaps whose hours actually arrived, and name the ones that did not.

    python tools/resolve_gaps.py --dry-run    # say what would change
    python tools/resolve_gaps.py              # close what is genuinely covered

Nothing in this project ever set `ingest_gap.resolved`, so every gap ever
recorded stayed open. `/health` and `scripts/check.ps1` report the count, which
means one DNS failure in September is still being reported in March with the
same urgency as an ingest that died an hour ago - and a warning that never
clears is a warning that stops being read.

This closes a gap only on evidence: `weather_hourly` contains every hour the
gap covers, normally because the next scheduled fetch wrote them. A gap whose
hours are still absent is left open and its missing hours are listed, because
law 4 makes a hole in the record honest and its concealment a bug. This tool
can close a gap; it can never fill one.

On the deployment the database lives in a docker volume and `tools/` is not in
the image, so run it with the repo's tools mounted, from the repo directory:

    docker compose run --rm -v C:\\Users\\admin\\fwapp\\tools:/srv/fishlog/tools \\
        fishlog python tools/resolve_gaps.py --dry-run

See `docs/21-MOVE-AND-RUN.md`.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.core.db import init_db, session_scope  # noqa: E402
from app.ingest.gaps import review  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report only; change nothing",
    )
    args = parser.parse_args(argv)

    init_db()
    with session_scope() as db:
        verdicts = review(db, apply=not args.dry_run)

    if not verdicts:
        print("No unresolved gaps. Nothing to do.")
        return 0

    closed = [v for v in verdicts if v.complete]
    open_still = [v for v in verdicts if not v.complete]

    for verdict in verdicts:
        mark = "closed " if verdict.complete else "OPEN   "
        if args.dry_run and verdict.complete:
            mark = "would  "
        print(f"{mark} #{verdict.gap_id} {verdict.lake_slug} [{verdict.source}]")
        print(f"         {verdict.from_utc} .. {verdict.to_utc}")
        print(f"         {verdict.describe()}")

    print()
    verb = "would close" if args.dry_run else "closed"
    print(f"{verb} {len(closed)} of {len(verdicts)} unresolved gap(s).")
    if open_still:
        stays = "stays" if len(open_still) == 1 else "stay"
        print(
            f"{len(open_still)} {stays} open because those hours are genuinely not "
            "on record. That is the correct state - do not clear them by hand."
        )
    if args.dry_run and closed:
        print("Re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
