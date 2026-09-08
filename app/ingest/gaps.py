"""Close an `ingest_gap` when — and only when — the hours it recorded arrived.

A gap row says "a fetch failed, so hours may be missing". Nothing in this
project ever set `resolved`, so every gap ever written stayed open forever:
`/health` and `scripts/check.ps1` warn about a DNS blip from months ago with
the same voice they would use for an ingest that died this morning. A warning
that never clears is a warning nobody reads.

The rule here is evidence, not tidying. A gap is resolved because
`weather_hourly` now actually contains every hour the gap covers — usually
because the next scheduled fetch an hour later wrote them. A gap whose hours
are still absent stays open, however old and however annoying, because law 4
says a hole in the record is honest and papering over it is not.

That asymmetry is the whole design: this module can close a gap, and it can
never fill one.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import IngestGap, Lake, WeatherHourly
from app.core.time import parse_iso

# How many missing hours to name in a report before saying "and N more". A gap
# spanning a failed archive chunk covers thousands of hours, and a list that
# long buries the one line that matters.
MAX_LISTED = 6


@dataclass(frozen=True)
class GapVerdict:
    """What is true about one gap, and what was done about it."""

    gap_id: int
    lake_slug: str
    source: str
    from_utc: str
    to_utc: str
    hours: int
    present: int
    missing: list[str] = field(default_factory=list)
    covered_by: list[str] = field(default_factory=list)
    resolved: bool = False

    @property
    def complete(self) -> bool:
        return self.hours > 0 and self.present == self.hours

    def describe(self) -> str:
        if self.complete:
            by = ", ".join(self.covered_by) or "?"
            return f"all {self.hours} h present (from {by}) - closing"
        first = ", ".join(self.missing[:MAX_LISTED])
        more = len(self.missing) - MAX_LISTED
        tail = f" and {more} more" if more > 0 else ""
        return f"{len(self.missing)} of {self.hours} h still missing: {first}{tail}"


def covered_hours(from_utc: str, to_utc: str) -> list[dt.datetime]:
    """The whole hours a gap covers, inclusive at both ends.

    A forecast gap stores the moment the attempt failed, so `from` and `to` are
    the same instant and the answer is the single hour containing it. An archive
    gap stores a chunk of days. Both are the same question once the ends are
    floored to the hour.
    """
    start = parse_iso(from_utc).astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)
    end = parse_iso(to_utc).astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)
    if end < start:
        start, end = end, start
    out: list[dt.datetime] = []
    cursor = start
    while cursor <= end:
        out.append(cursor)
        cursor += dt.timedelta(hours=1)
    return out


def assess(db: Session, gap: IngestGap, slug_by_id: dict[int, str] | None = None) -> GapVerdict:
    """Decide whether this gap's hours are on record. Reads only."""
    wanted = covered_hours(gap.from_utc, gap.to_utc)
    lo, hi = wanted[0], wanted[-1]

    # Deliberately not filtered by source. The gap asks "is this hour on
    # record"; an hour the archive later supplied for a failed forecast fetch
    # is on record just as truly, and refusing to see it would keep a gap open
    # over a bookkeeping detail.
    # The bounds are a coarse pre-filter compared as strings, so they are
    # widened by a day at each end: a row written with a different timezone
    # offset would sort outside a tight window and read as missing, which is
    # the one error this module must never make. Exact matching happens below,
    # on parsed datetimes.
    rows = db.execute(
        select(WeatherHourly.ts_utc, WeatherHourly.source).where(
            WeatherHourly.lake_id == gap.lake_id,
            WeatherHourly.ts_utc >= (lo - dt.timedelta(days=1)).isoformat(),
            WeatherHourly.ts_utc <= (hi + dt.timedelta(days=1)).isoformat(),
        )
    ).all()

    have: dict[dt.datetime, str] = {}
    for ts_utc, source in rows:
        try:
            stamp = parse_iso(str(ts_utc)).astimezone(dt.UTC)
        except ValueError:
            continue
        have.setdefault(stamp.replace(minute=0, second=0, microsecond=0), str(source))

    missing = [h.isoformat() for h in wanted if h not in have]
    sources = sorted({have[h] for h in wanted if h in have})

    slug = (slug_by_id or {}).get(gap.lake_id, f"lake:{gap.lake_id}")
    return GapVerdict(
        gap_id=gap.id,
        lake_slug=slug,
        source=gap.source,
        from_utc=gap.from_utc,
        to_utc=gap.to_utc,
        hours=len(wanted),
        present=len(wanted) - len(missing),
        missing=missing,
        covered_by=sources,
    )


def review(db: Session, *, apply: bool) -> list[GapVerdict]:
    """Assess every unresolved gap; with `apply`, close the ones now covered.

    Returns a verdict per gap in the order they were written, so a report can
    be printed whether or not anything was changed.
    """
    slug_by_id = {
        int(row[0]): str(row[1]) for row in db.execute(select(Lake.id, Lake.slug)).all()
    }
    gaps = (
        db.execute(select(IngestGap).where(IngestGap.resolved == 0).order_by(IngestGap.id))
        .scalars()
        .all()
    )

    verdicts: list[GapVerdict] = []
    for gap in gaps:
        verdict = assess(db, gap, slug_by_id)
        if verdict.complete and apply:
            gap.resolved = 1
            verdict = replace(verdict, resolved=True)
        verdicts.append(verdict)

    if apply:
        db.commit()
    return verdicts
