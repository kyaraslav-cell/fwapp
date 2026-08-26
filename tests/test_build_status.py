"""What the lake page says about a water that is still being built.

The banner exists so an unfinished water does not look like a broken one. It
managed to invert that: Zalew Zegrzynski collected 42 local-knowledge facts,
had a duplicate `intel` job queued half an hour later which timed out against
Gemini, and the page then told the angler that preparing the water had failed
- while displaying the facts it had supposedly failed to collect.

A job kind is a *stage*, not an attempt. A stage that finished is finished,
however many later attempts at it fell over.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Job, Lake
from app.core.time import iso, utcnow
from app.jobs import queue
from app.web.build_status import FAILED, NO_OUTLINE, PREPARING, READY, status_for


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def lake(db: Session) -> Lake:
    row = Lake(
        slug="zegrzynski",
        name="Zalew Zegrzynski",
        centroid_lat=52.49,
        centroid_lon=21.07,
        timezone="Europe/Warsaw",
        origin="discovered",
        outline_source="osm",
        created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def _job(lake: Lake, kind: str, state: str) -> Job:
    return Job(
        lake_id=lake.id,
        kind=kind,
        state=state,
        attempts=1,
        run_after=iso(utcnow()),
        created_at=iso(utcnow()),
    )


def test_a_seeded_water_with_no_jobs_is_ready(db: Session, lake: Lake) -> None:
    """The absence of jobs must never read as 'stuck'."""
    assert status_for(db, lake).state == READY


def test_a_retry_that_failed_after_the_stage_succeeded_is_not_a_failure(
    db: Session, lake: Lake
) -> None:
    """The live bug, exactly."""
    db.add(_job(lake, "intel", queue.DONE))
    db.add(_job(lake, "intel", queue.FAILED))
    db.flush()

    assert status_for(db, lake).state == READY


def test_a_stage_that_never_succeeded_is_still_reported(db: Session, lake: Lake) -> None:
    """The fix must not turn into 'hide every failure'."""
    db.add(_job(lake, "outline", queue.DONE))
    db.add(_job(lake, "intel", queue.FAILED))
    db.flush()

    status = status_for(db, lake)
    assert status.state == FAILED
    assert status.message_key == "build.failed"


def test_work_still_queued_reads_as_preparing_not_failed(db: Session, lake: Lake) -> None:
    db.add(_job(lake, "intel", queue.FAILED))
    db.add(_job(lake, "grid", queue.QUEUED))
    db.flush()

    status = status_for(db, lake)
    assert status.state == PREPARING
    assert status.in_progress


def test_a_water_osm_has_no_polygon_for_is_finished_not_broken(
    db: Session, lake: Lake
) -> None:
    lake.outline_source = "none"
    db.add(_job(lake, "outline", queue.DONE))
    db.flush()

    assert status_for(db, lake).state == NO_OUTLINE
