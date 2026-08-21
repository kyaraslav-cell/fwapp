"""`/health` — is this app actually still doing its job?

`docs/05-ARCHITECTURE.md` asks for "a healthcheck endpoint exposing the last
successful ingest time", and the reason is specific rather than ceremonial.

**The failure this catches is not a crash.** A crashed app is obvious: the page
does not load and somebody notices within a day. The dangerous failure for an
unattended weather app is the quiet one - APScheduler's job dies, or Open-Meteo
starts refusing, and the app carries on serving the *last* forecast it managed
to fetch. Every page still renders. The day strip still shows colours. They are
just describing last Tuesday, and nothing anywhere says so.

So the check is not "does the process answer HTTP" - it is **how old is the
newest observation, and when did an ingest last succeed**.

Three states, chosen so that a monitor can act on them without reading prose:

    ok       ingested within FRESH_HOURS. Nothing to do.
    stale    no successful ingest recently, but the app is up and serving.
             This is the state that matters: everything looks fine and is not.
    unknown  the database itself could not be read. Reported as 503 too, but
             named differently, because "no weather" and "no database" need
             different hands.

Deliberately public and deliberately dull: no counts of users, no session
data, no lake list. A healthcheck ends up in logs, uptime services and other
people's dashboards, and none of those need to know who fishes here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import IngestGap, WeatherHourly
from app.core.time import iso, parse_iso, utcnow

# Open-Meteo is ingested hourly. Six hours is five missed runs - long enough
# that a single transient failure does not page anybody, short enough that a
# morning's fishing is never planned on yesterday's pressure.
FRESH_HOURS = 6


@dataclass(frozen=True)
class Health:
    status: str                      # "ok" | "stale" | "unknown"
    latest_observation: str | None   # newest measured hour, UTC ISO
    age_hours: float | None
    unresolved_gaps: int
    detail: str

    @property
    def http_status(self) -> int:
        """200 only for ok. A stale app is a failing app, not a warning.

        Returning 200 with `"status": "stale"` in the body means every monitor
        that checks the code - which is most of them - reports green while the
        app serves last week's forecast.
        """
        return 200 if self.status == "ok" else 503

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def check(db: Session, now: datetime | None = None) -> Health:
    """Read the two facts that decide it. No writes, no external calls.

    A healthcheck that calls Open-Meteo would fail when Open-Meteo is briefly
    slow, page somebody at 3 a.m., and be indistinguishable from the app
    actually being broken. This asks the database what the app has, which is
    the thing the pages are rendered from.
    """
    now = now or utcnow()

    try:
        newest = db.execute(
            select(func.max(WeatherHourly.ts_utc)).where(
                WeatherHourly.is_forecast == 0
            )
        ).scalar_one_or_none()
        gaps = int(
            db.execute(
                select(func.count())
                .select_from(IngestGap)
                .where(IngestGap.resolved == 0)
            ).scalar_one()
        )
    except Exception as exc:  # noqa: BLE001 - a healthcheck may never raise
        return Health(
            status="unknown",
            latest_observation=None,
            age_hours=None,
            unresolved_gaps=0,
            detail=f"database unreadable: {type(exc).__name__}",
        )

    if not newest:
        # A fresh install before the first ingest looks exactly like a dead
        # one from here, and honestly so: there is no weather either way.
        return Health(
            status="stale",
            latest_observation=None,
            age_hours=None,
            unresolved_gaps=gaps,
            detail="no measured weather has ever been ingested",
        )

    age = (now - parse_iso(str(newest))).total_seconds() / 3600.0
    fresh = age <= FRESH_HOURS
    return Health(
        status="ok" if fresh else "stale",
        latest_observation=iso(parse_iso(str(newest))),
        age_hours=round(age, 1),
        unresolved_gaps=gaps,
        detail=(
            f"newest observation is {age:.1f} h old"
            if fresh
            else f"newest observation is {age:.1f} h old, over the {FRESH_HOURS} h limit"
        ),
    )


def stale_before(now: datetime | None = None) -> datetime:
    """The instant an observation older than which counts as stale."""
    return (now or utcnow()) - timedelta(hours=FRESH_HOURS)
