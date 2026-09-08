"""Closing an ingest gap is allowed only on evidence, and filling one never is.

The risk this guards is not that a gap stays open too long - it is that a gap
gets closed while the hours are still missing. That would turn `/health` green
over a hole in the record, which is law 4's exact failure mode, and nothing
downstream would ever notice.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, IngestGap, Lake, WeatherHourly
from app.ingest.gaps import assess, covered_hours, review

NOW = dt.datetime(2026, 9, 6, 20, 5, tzinfo=dt.UTC)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        Lake(
            slug="pomocnia",
            name="Pomocnia",
            centroid_lat=52.5431,
            centroid_lon=20.6762,
            created_at=NOW.isoformat(),
        )
    )
    session.commit()
    return session


def _gap(db: Session, start: dt.datetime, end: dt.datetime | None = None) -> IngestGap:
    gap = IngestGap(
        lake_id=1,
        source="openmeteo_forecast",
        from_utc=start.isoformat(),
        to_utc=(end or start).isoformat(),
        reason="ConnectError: temporary failure in name resolution",
    )
    db.add(gap)
    db.commit()
    return gap


def _hour(db: Session, when: dt.datetime, source: str = "openmeteo_forecast") -> None:
    db.add(
        WeatherHourly(
            lake_id=1,
            ts_utc=when.isoformat(),
            source=source,
            is_forecast=0,
            pressure_msl=1013.0,
            temperature_2m=15.0,
            fetched_at=NOW.isoformat(),
        )
    )
    db.commit()


def test_a_point_gap_covers_the_hour_containing_it() -> None:
    hours = covered_hours(NOW.isoformat(), NOW.isoformat())
    assert hours == [dt.datetime(2026, 9, 6, 20, 0, tzinfo=dt.UTC)]


def test_a_range_gap_covers_every_whole_hour_inclusive() -> None:
    hours = covered_hours(
        dt.datetime(2026, 9, 6, 20, 5, tzinfo=dt.UTC).isoformat(),
        dt.datetime(2026, 9, 6, 23, 40, tzinfo=dt.UTC).isoformat(),
    )
    assert len(hours) == 4
    assert hours[0].hour == 20
    assert hours[-1].hour == 23


def test_a_gap_closes_once_the_hour_is_on_record(db: Session) -> None:
    _gap(db, NOW)
    _hour(db, dt.datetime(2026, 9, 6, 20, 0, tzinfo=dt.UTC))

    verdicts = review(db, apply=True)

    assert len(verdicts) == 1
    assert verdicts[0].complete
    assert verdicts[0].resolved
    assert db.execute(select(IngestGap.resolved)).scalar_one() == 1


def test_a_gap_stays_open_while_its_hour_is_missing(db: Session) -> None:
    _gap(db, NOW)
    # The neighbouring hours arrived; the one the gap recorded did not.
    _hour(db, dt.datetime(2026, 9, 6, 19, 0, tzinfo=dt.UTC))
    _hour(db, dt.datetime(2026, 9, 6, 21, 0, tzinfo=dt.UTC))

    verdicts = review(db, apply=True)

    assert not verdicts[0].complete
    assert not verdicts[0].resolved
    assert verdicts[0].missing == ["2026-09-06T20:00:00+00:00"]
    assert db.execute(select(IngestGap.resolved)).scalar_one() == 0


def test_a_partly_covered_range_is_not_closed(db: Session) -> None:
    _gap(db, NOW, dt.datetime(2026, 9, 6, 23, 40, tzinfo=dt.UTC))
    for hour in (20, 21, 22):
        _hour(db, dt.datetime(2026, 9, 6, hour, 0, tzinfo=dt.UTC))

    verdict = review(db, apply=True)[0]

    assert verdict.hours == 4
    assert verdict.present == 3
    assert not verdict.resolved


def test_dry_run_changes_nothing(db: Session) -> None:
    _gap(db, NOW)
    _hour(db, dt.datetime(2026, 9, 6, 20, 0, tzinfo=dt.UTC))

    verdicts = review(db, apply=False)

    assert verdicts[0].complete
    assert not verdicts[0].resolved
    assert db.execute(select(IngestGap.resolved)).scalar_one() == 0


def test_an_hour_from_another_source_still_counts(db: Session) -> None:
    """A forecast gap filled later by the archive is filled. The record is what matters."""
    _gap(db, NOW)
    _hour(db, dt.datetime(2026, 9, 6, 20, 0, tzinfo=dt.UTC), source="openmeteo_archive")

    verdict = review(db, apply=True)[0]

    assert verdict.resolved
    assert verdict.covered_by == ["openmeteo_archive"]


def test_an_hour_belonging_to_another_lake_does_not_count(db: Session) -> None:
    db.add(
        Lake(
            slug="zegrze",
            name="Zegrze",
            centroid_lat=52.45,
            centroid_lon=21.05,
            created_at=NOW.isoformat(),
        )
    )
    db.commit()
    _gap(db, NOW)
    db.add(
        WeatherHourly(
            lake_id=2,
            ts_utc=dt.datetime(2026, 9, 6, 20, 0, tzinfo=dt.UTC).isoformat(),
            source="openmeteo_forecast",
            is_forecast=0,
            pressure_msl=1013.0,
            temperature_2m=15.0,
            fetched_at=NOW.isoformat(),
        )
    )
    db.commit()

    assert not review(db, apply=True)[0].resolved


def test_an_already_resolved_gap_is_left_alone(db: Session) -> None:
    gap = _gap(db, NOW)
    gap.resolved = 1
    db.commit()

    assert review(db, apply=True) == []


def test_assess_reads_only(db: Session) -> None:
    gap = _gap(db, NOW)
    _hour(db, dt.datetime(2026, 9, 6, 20, 0, tzinfo=dt.UTC))

    verdict = assess(db, gap, {1: "pomocnia"})

    assert verdict.complete
    assert not verdict.resolved
    assert verdict.lake_slug == "pomocnia"
    assert db.execute(select(IngestGap.resolved)).scalar_one() == 0
