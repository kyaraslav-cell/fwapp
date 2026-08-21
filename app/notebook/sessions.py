from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Catch, FishSession, Lake, Prediction
from app.core.time import iso, parse_iso, utcnow
from app.notebook.water_type import assert_comparable

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
    user_id: int | None = None,
    method: str | None = None,
    rod_count: int | None = None,
    grid_cell: str | None = None,
    grid_lat: float | None = None,
    grid_lon: float | None = None,
) -> FishSession:
    now = utcnow()
    session = FishSession(
        lake_id=lake.id,
        user_id=user_id,
        zone_id=zone_id,
        started_at=iso(now),
        method=method,
        rod_count=rod_count,
        grid_cell=grid_cell,
        grid_lat=grid_lat,
        grid_lon=grid_lon,
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
    bait: str | None = None,
    notes: str | None = None,
    photo_path: str | None = None,
) -> Catch:
    catch = Catch(
        session_id=session_id,
        species=species,
        count=count,
        weight_g=weight_g,
        length_cm=length_cm,
        bait=bait,
        notes=notes,
        photo_path=photo_path,
        caught_at=iso(utcnow()),
    )
    db.add(catch)
    db.flush()
    return catch


def update_catch(
    db: Session,
    catch: Catch,
    species: str | None = None,
    weight_g: int | None = None,
    length_cm: float | None = None,
    bait: str | None = None,
    notes: str | None = None,
    photo_path: str | None = None,
) -> Catch:
    if species:
        catch.species = species
    catch.weight_g = weight_g
    catch.length_cm = length_cm
    catch.bait = bait
    catch.notes = notes
    if photo_path is not None:
        catch.photo_path = photo_path
    db.flush()
    return catch


def delete_catch(db: Session, catch: Catch) -> None:
    db.delete(catch)
    db.flush()


def end_session(
    db: Session,
    session: FishSession,
    reflection: str | None = None,
    water_temp_measured_c: float | None = None,
    water_clarity_cm: float | None = None,
) -> FishSession:
    now = utcnow()
    session.ended_at = iso(now)
    started = parse_iso(session.started_at)
    session.effort_minutes = max(1, int((now - started).total_seconds() // 60))
    # A blank is simply a session that caught nothing - derived, never asked
    # for. It still counts fully in every statistic (law 3).
    n_catches = db.execute(
        select(Catch).where(Catch.session_id == session.id)
    ).scalars().all()
    session.is_blank = 0 if n_catches else 1
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


def list_sessions(
    db: Session, lake: Lake, limit: int = 50, user_id: int | None = None
) -> list[SessionSummary]:
    """Ended sessions, newest first, optionally only one angler's.

    `user_id=None` means "every session on this water", which is what the
    published read-only site and any pre-accounts caller get. Signed-in views
    always pass an id: CPUE across two anglers is not a better-sampled CPUE, it
    is a different measurement (law 3, ADR 0004) - skill varies more than the
    weather does, so pooling would bury the signal this project is trying to
    find.
    """
    query = (
        select(FishSession)
        .where(FishSession.lake_id == lake.id, FishSession.ended_at.is_not(None))
    )
    if user_id is not None:
        query = query.where(FishSession.user_id == user_id)
    sessions = db.execute(
        query.order_by(FishSession.started_at.desc()).limit(limit)
    ).scalars().all()

    # One grouped query for every session's fish, not one query per session.
    # The loop this replaced ran 201 queries for a 200-session season, and the
    # season is the point of the project - this page gets slower every trip.
    #
    # A session with no catches has no row here at all, which is exactly why
    # the lookup below defaults to 0 rather than skipping: **a blank session is
    # data** (law 3), it must appear in the list, and its CPUE is a real zero.
    ids = [s.id for s in sessions]
    counts: dict[int, int] = {}
    if ids:
        counts = {
            int(session_id): int(total or 0)
            for session_id, total in db.execute(
                select(Catch.session_id, func.sum(Catch.count))
                .where(Catch.session_id.in_(ids))
                .group_by(Catch.session_id)
            ).all()
        }

    summaries = []
    for s in sessions:
        fish_count = counts.get(s.id, 0)
        hours = (s.effort_minutes or 0) / 60.0
        cpue = fish_count / hours if hours > 0 else 0.0
        summaries.append(SessionSummary(session=s, total_fish=fish_count, cpue=round(cpue, 2)))
    return summaries


def active_session(
    db: Session, lake: Lake, user_id: int | None = None
) -> FishSession | None:
    """The session in progress, if there is one.

    Scoped per angler when an id is given: two people on the same bank each
    have their own session running, and the banner must not offer one of them
    the other's notebook.
    """
    query = select(FishSession).where(
        FishSession.lake_id == lake.id, FishSession.ended_at.is_(None)
    )
    if user_id is not None:
        query = query.where(FishSession.user_id == user_id)
    return db.execute(
        query.order_by(FishSession.started_at.desc()).limit(1)
    ).scalar_one_or_none()


def mean_cpue(summaries: list[SessionSummary], water_types: list[str | None]) -> float | None:
    """Mean fish per hour across sessions, or a refusal if the waters differ.

    Blank sessions are included deliberately - a zero is data (law 3), and
    filtering them would inflate every average the project produces.

    Raises IncomparableWatersError when the sessions span more than one water
    type, or any water whose type was never recorded. Averaging a stocked
    commercial water against a wild PZW lake produces a number that looks
    perfectly reasonable and means nothing.
    """
    assert_comparable(water_types)
    if not summaries:
        return None
    return round(sum(s.cpue for s in summaries) / len(summaries), 2)


def lake_stats(
    db: Session, lake: Lake, user_id: int | None = None
) -> tuple[int, str | None]:
    """(session_count, last_visited_iso) for a lake, ended sessions only."""
    query = (
        select(FishSession.started_at)
        .where(FishSession.lake_id == lake.id, FishSession.ended_at.is_not(None))
    )
    if user_id is not None:
        query = query.where(FishSession.user_id == user_id)
    rows = db.execute(query.order_by(FishSession.started_at.desc())).all()
    if not rows:
        return 0, None
    return len(rows), rows[0][0]
