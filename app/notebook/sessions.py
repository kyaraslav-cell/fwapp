from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Catch, FishSession, Lake, Prediction
from app.core.time import iso, parse_iso, utcnow

SPECIES_PRIMARY = ["roach", "bream", "rudd", "ide"]
SPECIES_SECONDARY = ["carp", "crucian"]
SPECIES_LOGGED_ONLY = ["pike", "perch", "catfish", "eel", "tench"]
ALL_SPECIES = SPECIES_PRIMARY + SPECIES_SECONDARY + SPECIES_LOGGED_ONLY

METHODS = ["carp", "feeder", "float"]


def start_session(
    db: Session,
    lake: Lake,
    prediction: Prediction | None,
    zone_id: int | None = None,
    method: str | None = None,
    rod_count: int | None = None,
) -> FishSession:
    now = utcnow()
    session = FishSession(
        lake_id=lake.id,
        zone_id=zone_id,
        started_at=iso(now),
        method=method,
        rod_count=rod_count,
        prediction_id=prediction.id if prediction else None,
        conditions_snapshot=prediction.payload_json if prediction else None,
        is_blank=0,
        created_at=iso(now),
    )
    db.add(session)
    db.flush()
    return session


def add_catch(
    db: Session,
    session_id: int,
    species: str,
    count: int = 1,
    weight_g: int | None = None,
    length_cm: float | None = None,
) -> Catch:
    catch = Catch(
        session_id=session_id,
        species=species,
        count=count,
        weight_g=weight_g,
        length_cm=length_cm,
        caught_at=iso(utcnow()),
    )
    db.add(catch)
    db.flush()
    return catch


def end_session(
    db: Session,
    session: FishSession,
    is_blank: bool,
    reflection: str | None = None,
    water_temp_measured_c: float | None = None,
    water_clarity_cm: float | None = None,
) -> FishSession:
    now = utcnow()
    session.ended_at = iso(now)
    started = parse_iso(session.started_at)
    session.effort_minutes = max(1, int((now - started).total_seconds() // 60))
    session.is_blank = 1 if is_blank else 0
    session.reflection = reflection
    session.water_temp_measured_c = water_temp_measured_c
    session.water_clarity_cm = water_clarity_cm
    db.flush()
    return session


@dataclass(frozen=True)
class SessionSummary:
    session: FishSession
    total_fish: int
    cpue: float


def list_sessions(db: Session, lake: Lake, limit: int = 50) -> list[SessionSummary]:
    sessions = db.execute(
        select(FishSession)
        .where(FishSession.lake_id == lake.id, FishSession.ended_at.is_not(None))
        .order_by(FishSession.started_at.desc())
        .limit(limit)
    ).scalars().all()

    summaries = []
    for s in sessions:
        total_fish = db.execute(
            select(Catch).where(Catch.session_id == s.id)
        ).scalars().all()
        fish_count = sum(c.count for c in total_fish)
        hours = (s.effort_minutes or 0) / 60.0
        cpue = fish_count / hours if hours > 0 else 0.0
        summaries.append(SessionSummary(session=s, total_fish=fish_count, cpue=round(cpue, 2)))
    return summaries


def active_session(db: Session, lake: Lake) -> FishSession | None:
    return db.execute(
        select(FishSession)
        .where(FishSession.lake_id == lake.id, FishSession.ended_at.is_(None))
        .order_by(FishSession.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def lake_stats(db: Session, lake: Lake) -> tuple[int, str | None]:
    """(session_count, last_visited_iso) for a lake, ended sessions only."""
    rows = db.execute(
        select(FishSession.started_at)
        .where(FishSession.lake_id == lake.id, FishSession.ended_at.is_not(None))
        .order_by(FishSession.started_at.desc())
    ).all()
    if not rows:
        return 0, None
    return len(rows), rows[0][0]
