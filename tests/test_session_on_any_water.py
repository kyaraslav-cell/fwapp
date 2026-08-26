"""A session must be reachable on the water it was started on.

The whole `/session/*` route family did `lake = get_lake(db)`, and `get_lake`
returns the **seeded** lake - always Pomocnia - regardless of which water the
angler is standing at. So starting a session on any added water wrote the row
and then lost it: the redirect to `/session/active` looked for a session on
Pomocnia, found none, and bounced the angler to the places list.

From the bank that looks exactly like a dead button. It is worse than dead:
every tap created another session that could never be opened, ended, or logged
against. The owner's live database had two such orphans, and the second real
user had one, before this was found.

The existing suite passed throughout, because every session test used the
seeded lake.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, FishSession, Lake
from app.core.time import iso, utcnow
from app.notebook.sessions import (
    active_session,
    active_session_for_user,
    open_sessions_for_user,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _lake(db: Session, slug: str, origin: str = "discovered") -> Lake:
    row = Lake(
        slug=slug,
        name=slug.title(),
        centroid_lat=52.0,
        centroid_lon=21.0,
        timezone="Europe/Warsaw",
        origin=origin,
        created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def _session(db: Session, lake: Lake, user_id: int, *, minutes_ago: int = 0) -> FishSession:
    from datetime import timedelta

    started = utcnow() - timedelta(minutes=minutes_ago)
    row = FishSession(
        lake_id=lake.id,
        user_id=user_id,
        started_at=iso(started),
        is_blank=0,
        created_at=iso(started),
    )
    db.add(row)
    db.flush()
    return row


def test_a_session_on_an_added_water_is_found(db: Session) -> None:
    """The bug, in one assertion."""
    _lake(db, "pomocnia", origin="seed")
    zegrzynski = _lake(db, "zegrzynski")
    started = _session(db, zegrzynski, user_id=1)

    found = active_session_for_user(db, user_id=1)

    assert found is not None, "the session was created and then became unreachable"
    assert found.id == started.id
    assert found.lake_id == zegrzynski.id


def test_looking_only_at_the_seeded_lake_misses_it(db: Session) -> None:
    """Why the old code failed, kept so the cause stays legible."""
    pomocnia = _lake(db, "pomocnia", origin="seed")
    zegrzynski = _lake(db, "zegrzynski")
    _session(db, zegrzynski, user_id=1)

    assert active_session(db, pomocnia, user_id=1) is None
    assert active_session_for_user(db, user_id=1) is not None


def test_another_anglers_session_is_not_returned(db: Session) -> None:
    """Two people on the same bank each have their own notebook."""
    lake = _lake(db, "zegrzynski")
    _session(db, lake, user_id=2)

    assert active_session_for_user(db, user_id=1) is None


def test_an_ended_session_is_not_active(db: Session) -> None:
    lake = _lake(db, "zegrzynski")
    row = _session(db, lake, user_id=1)
    row.ended_at = iso(utcnow())
    db.flush()

    assert active_session_for_user(db, user_id=1) is None


def test_the_newest_open_session_wins_and_the_rest_survive(db: Session) -> None:
    """The orphans this bug created are real logged effort, not junk.

    Law 3: blank sessions are data. Starting a session must not silently end
    another one, so `open_sessions_for_user` can still see every one of them
    and the angler can close them deliberately.
    """
    poniaty = _lake(db, "poniaty")
    zegrzynski = _lake(db, "zegrzynski")
    older = _session(db, poniaty, user_id=1, minutes_ago=30)
    newer = _session(db, zegrzynski, user_id=1, minutes_ago=1)

    assert active_session_for_user(db, user_id=1).id == newer.id
    assert [s.id for s in open_sessions_for_user(db, user_id=1)] == [newer.id, older.id]
