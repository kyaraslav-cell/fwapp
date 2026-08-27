"""Compare what this angler catches against what the okreg's register says.

    python tools/calibration_check.py
    python tools/calibration_check.py --user 1 --out reports/calibration/2026-08-27.md

This is the first rung of the calibration loop (roadmap phase 5). Until the
okreg's catch report was imported, the project had **nothing** to check itself
against: no logged sessions, no external measurement, no way to tell whether
any of the scoring beats guessing.

## What this can and cannot calibrate

It compares **kg per angler-day**, per water, from two sources:

  * the okreg's registered catch for a season (`config/catch_reports/`), and
  * this angler's own sessions, from the notebook.

It deliberately does **not** try to validate the day score or the zone score,
and an earlier plan to do exactly that was wrong:

  * the **day score** is about *when* to go. The report is annual - it has no
    daily resolution at all, so there is nothing to correlate a daily score
    against.
  * the **zone score** is about *where on a water* to fish. The report has no
    within-water resolution either.
  * ranking whole waters by their annual catch would measure stock and
    fertility, which the engine deliberately does not model. A correlation
    there would say nothing about the engine, and a good one would be
    misleading.

What it does measure is whether this angler is above or below the water's
registered average - which is a real, honest yardstick, and the thing a
per-water baseline is actually for.

## Units

`kg per angler-day`, on both sides. That is **not** law 3's fish-per-hour, and
the two must never be pooled. The notebook's own `mean_cpue` stays the unit of
success; this is a second, coarser measurement that happens to be the one the
okreg publishes.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db, session_scope  # noqa: E402
from app.core.models import Catch, FishSession, Lake  # noqa: E402
from app.core.time import parse_iso  # noqa: E402
from app.notebook import registered_catch  # noqa: E402


@dataclass
class Comparison:
    lake: str
    registered_kg_day: float | None
    registered_anglers: int | None
    registered_year: int | None
    own_kg_day: float | None
    own_sessions: int
    own_days: float


def _session_days(session: FishSession) -> float:
    """Length of a session in days, floored at a sensible minimum.

    A two-hour session is not a day, and calling it one would understate the
    rate by a factor of ten. Sessions still running contribute nothing - they
    have no end, and guessing one would be inventing effort.
    """
    if not session.ended_at:
        return 0.0
    hours = (parse_iso(session.ended_at) - parse_iso(session.started_at)).total_seconds() / 3600.0
    return max(hours, 0.0) / 24.0


def collect(user_id: int | None) -> list[Comparison]:
    rows: list[Comparison] = []
    with session_scope() as db:
        lakes = db.query(Lake).order_by(Lake.name).all()
        for lake in lakes:
            baseline = registered_catch.newest_for_keys(
                [k for k in (lake.pzw_key, lake.name, lake.name_osm) if k]
            )

            query = db.query(FishSession).filter(FishSession.lake_id == lake.id)
            if user_id is not None:
                query = query.filter(FishSession.user_id == user_id)
            sessions = query.all()

            weights: dict[int, float] = defaultdict(float)
            for catch in db.query(Catch).filter(
                Catch.session_id.in_([s.id for s in sessions] or [-1])
            ):
                if catch.weight_g:
                    weights[catch.session_id] += (catch.weight_g / 1000.0) * (catch.count or 1)

            days = sum(_session_days(s) for s in sessions)
            caught = sum(weights.get(s.id, 0.0) for s in sessions if s.ended_at)
            own = (caught / days) if days > 0 else None

            if baseline is None and not sessions:
                continue
            rows.append(
                Comparison(
                    lake=lake.name,
                    registered_kg_day=baseline.kg_per_angler_day if baseline else None,
                    registered_anglers=baseline.anglers if baseline else None,
                    registered_year=baseline.year if baseline else None,
                    own_kg_day=own,
                    own_sessions=len(sessions),
                    own_days=days,
                )
            )
    return rows


def render(rows: list[Comparison]) -> str:
    out = [
        "# Calibration — own catch against the okreg's register",
        "",
        "Both columns are **kg per angler-day**. That is not law 3's",
        "fish-per-hour and the two must never be pooled; it is the unit the",
        "okreg publishes, so it is the unit a comparison has to use.",
        "",
        "The register is a voluntary sample - `n` is how many anglers returned",
        "one, and it is frequently under thirty (law 5).",
        "",
        "| Water | registered kg/day | n | year | own kg/day | sessions | own days |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        reg = f"{r.registered_kg_day:.2f}" if r.registered_kg_day is not None else "—"
        own = f"{r.own_kg_day:.2f}" if r.own_kg_day is not None else "—"
        out.append(
            f"| {r.lake} | {reg} | {r.registered_anglers or '—'} | {r.registered_year or '—'} "
            f"| {own} | {r.own_sessions} | {r.own_days:.2f} |"
        )

    comparable = [r for r in rows if r.registered_kg_day and r.own_kg_day]
    out.append("")
    if not comparable:
        out += [
            "## Nothing to compare yet",
            "",
            "No water has both a registered baseline and a finished session with",
            "weighed catches. That is the honest state, not a failure: the loop",
            "is wired and waiting for logged effort. A session must be **ended**",
            "to count - an open one has no duration, and inventing one would be",
            "fabricating effort.",
        ]
    else:
        out += ["## Against the baseline", ""]
        for r in comparable:
            assert r.own_kg_day is not None and r.registered_kg_day is not None
            ratio = r.own_kg_day / r.registered_kg_day
            verdict = "above" if ratio > 1 else "below"
            out.append(
                f"- **{r.lake}**: {r.own_kg_day:.2f} vs {r.registered_kg_day:.2f} kg/day — "
                f"{ratio:.2f}× the {r.registered_year} register, {verdict} average "
                f"(their n={r.registered_anglers}, yours={r.own_sessions} sessions)."
            )
        out += [
            "",
            "One angler's handful of sessions against a season's register is not",
            "a calibration. It becomes one over a season of logged effort.",
        ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", type=int, default=None, help="restrict to one angler's notebook")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    init_db()
    rows = collect(args.user)
    text = render(rows)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(text)
        print(f"written to {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
