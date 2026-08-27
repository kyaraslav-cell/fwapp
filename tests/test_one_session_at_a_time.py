"""An angler has one session running, or none. Never two.

Two sessions open at once overlap in time, and that makes both of their CPUE
figures wrong: the effort is counted twice while the catches are split between
them (law 3). It is not a UI preference, it is a correctness rule about the
only measurement the project exists to make.

The guard used to live in the route and was scoped to the water being started
on, so an angler already fishing lake A could start a second session on lake
B. It now lives in `start_session`, where no caller can miss it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Lake
from app.core.time import iso, utcnow
from app.notebook.sessions import (
    SessionAlreadyRunningError,
    active_session_for_user,
    end_session,
    start_session,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _lake(db: Session, slug: str) -> Lake:
    row = Lake(
        slug=slug,
        name=slug.title(),
        centroid_lat=52.0,
        centroid_lon=21.0,
        timezone="Europe/Warsaw",
        origin="discovered",
        created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def test_a_second_session_on_another_water_is_refused(db: Session) -> None:
    """The exact hole the owner found."""
    first = _lake(db, "pomocnia")
    second = _lake(db, "zegrzynski")
    start_session(db, first, None, user_id=1)

    with pytest.raises(SessionAlreadyRunningError):
        start_session(db, second, None, user_id=1)


def test_a_second_session_on_the_same_water_is_refused(db: Session) -> None:
    lake = _lake(db, "pomocnia")
    start_session(db, lake, None, user_id=1)

    with pytest.raises(SessionAlreadyRunningError):
        start_session(db, lake, None, user_id=1)


def test_the_refusal_names_the_session_still_running(db: Session) -> None:
    """So the angler can be told where they already are, not just 'no'."""
    first = _lake(db, "pomocnia")
    second = _lake(db, "zegrzynski")
    running = start_session(db, first, None, user_id=1)

    with pytest.raises(SessionAlreadyRunningError) as caught:
        start_session(db, second, None, user_id=1)

    assert caught.value.session.id == running.id
    assert caught.value.session.lake_id == first.id


def test_another_angler_is_unaffected(db: Session) -> None:
    """Two people on the same bank each have their own session."""
    lake = _lake(db, "pomocnia")
    start_session(db, lake, None, user_id=1)

    started = start_session(db, lake, None, user_id=2)

    assert started.user_id == 2


def test_a_new_session_is_allowed_once_the_last_one_ended(db: Session) -> None:
    first = _lake(db, "pomocnia")
    second = _lake(db, "zegrzynski")
    running = start_session(db, first, None, user_id=1)
    end_session(db, running)

    started = start_session(db, second, None, user_id=1)

    assert started.lake_id == second.id
    found = active_session_for_user(db, 1)
    assert found is not None and found.id == started.id


def test_a_signed_out_start_is_not_blocked_by_someone_elses_session(db: Session) -> None:
    """The published read-only build has no user; it must not be gated on one."""
    lake = _lake(db, "pomocnia")
    start_session(db, lake, None, user_id=1)

    anonymous = start_session(db, lake, None, user_id=None)

    assert anonymous.user_id is None
