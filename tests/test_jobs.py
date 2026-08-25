"""The job queue: the state machine, and the runner surviving bad handlers.

The queue is what makes adding a water feel instant, so its failure modes are
the ones that matter: a job that vanishes, a job that retries forever, a job
that blocks every other water because its prerequisite is slow, and a handler
that raises something nobody predicted.

The clock is passed in everywhere, so every backoff rule here is tested without
waiting for one.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Job, Lake
from app.core.time import iso, parse_iso, utcnow
from app.jobs import queue


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def lake(db: Session) -> Lake:
    row = Lake(
        slug="test", name="Test", centroid_lat=52.0, centroid_lon=21.0,
        timezone="Europe/Warsaw", created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def test_a_queued_job_is_claimed_once(db: Session, lake: Lake) -> None:
    queue.enqueue(db, "outline", lake_id=lake.id)

    first = queue.claim(db)
    second = queue.claim(db)

    assert first is not None and first.kind == "outline"
    assert first.state == queue.RUNNING
    assert first.attempts == 1
    assert second is None, "a running job must not be claimed again"


def test_enqueue_does_not_pile_up_duplicates(db: Session, lake: Lake) -> None:
    """Opening a page twice must not queue the same work twice."""
    first = queue.enqueue(db, "outline", lake_id=lake.id)
    second = queue.enqueue(db, "outline", lake_id=lake.id)

    assert first.id == second.id
    assert db.query(Job).count() == 1


def test_a_finished_job_lets_the_same_kind_be_queued_again(db: Session, lake: Lake) -> None:
    """The monthly refresh depends on this: done is not the same as forbidden."""
    first = queue.enqueue(db, "outline", lake_id=lake.id)
    claimed = queue.claim(db)
    assert claimed is not None
    queue.finish(db, claimed)

    second = queue.enqueue(db, "outline", lake_id=lake.id)
    assert second.id != first.id


def test_failure_backs_off_and_eventually_gives_up(db: Session, lake: Lake) -> None:
    now = utcnow()
    queue.enqueue(db, "outline", lake_id=lake.id, now=now)

    delays = []
    for _ in range(queue.MAX_ATTEMPTS):
        job = queue.claim(db, now=now)
        assert job is not None, "a backed-off job must come back when it is due"
        queue.fail(db, job, "overpass timed out", now=now)
        if job.state == queue.QUEUED:
            delays.append((parse_iso(job.run_after) - now).total_seconds())
            now = parse_iso(job.run_after)

    job = db.query(Job).one()
    assert job.state == queue.FAILED
    assert job.last_error == "overpass timed out"
    assert delays == sorted(delays), f"backoff must grow, got {delays}"
    assert queue.claim(db, now=now + timedelta(days=1)) is None


def test_a_deferred_job_does_not_spend_an_attempt(db: Session, lake: Lake) -> None:
    """A grid waiting on a slow shoreline is not failing, and must not burn out."""
    now = utcnow()
    queue.enqueue(db, "grid", lake_id=lake.id, now=now)

    for _ in range(queue.MAX_ATTEMPTS * 3):
        job = queue.claim(db, now=now)
        assert job is not None
        queue.defer(db, job, "waiting for the outline", now=now)
        now = parse_iso(job.run_after)

    job = db.query(Job).one()
    assert job.state == queue.QUEUED
    assert job.attempts == 0


def test_an_interrupted_job_is_offered_back(db: Session, lake: Lake) -> None:
    """A container that dies mid-job must not leave a water stuck forever."""
    started = utcnow()
    queue.enqueue(db, "outline", lake_id=lake.id, now=started)
    claimed = queue.claim(db, now=started)
    assert claimed is not None

    later = started + timedelta(minutes=queue.STALE_RUNNING_MINUTES + 1)
    assert queue.release_stale(db, now=later) == 1
    assert queue.claim(db, now=later) is not None


def test_a_job_still_running_is_left_alone(db: Session, lake: Lake) -> None:
    started = utcnow()
    queue.enqueue(db, "outline", lake_id=lake.id, now=started)
    queue.claim(db, now=started)

    assert queue.release_stale(db, now=started + timedelta(minutes=1)) == 0


def test_jobs_run_oldest_first(db: Session, lake: Lake) -> None:
    now = utcnow()
    queue.enqueue(db, "outline", lake_id=lake.id, now=now)
    queue.enqueue(db, "weather_backfill", lake_id=lake.id, now=now)

    first = queue.claim(db, now=now)
    assert first is not None and first.kind == "outline"


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


def test_the_runner_survives_a_handler_that_explodes(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad row must not stop every other water in the queue."""
    from app.jobs import handlers, runner

    def explode(db: Session, job: Job) -> str:
        raise ZeroDivisionError("something nobody predicted")

    monkeypatch.setitem(handlers.HANDLERS, "outline", explode)
    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))

    queue.enqueue(db, "outline", lake_id=lake.id)
    message = runner.run_one()

    assert message is not None and "ZeroDivisionError" in message
    job = db.query(Job).one()
    assert job.state == queue.QUEUED  # backed off, not lost
    assert "ZeroDivisionError" in (job.last_error or "")


def test_an_unknown_job_kind_fails_visibly(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import runner

    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, "not_a_real_kind", lake_id=lake.id)

    message = runner.run_one()

    assert message is not None and "unknown kind" in message
    assert "no handler" in (db.query(Job).one().last_error or "")


def test_the_runner_is_idle_when_there_is_nothing_to_do(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import runner

    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    assert runner.run_one() is None


def _fake_scope(db: Session):  # type: ignore[no-untyped-def]
    """Hand the runner the test's own session instead of opening a real one."""
    from contextlib import contextmanager

    @contextmanager
    def scope():  # type: ignore[no-untyped-def]
        yield db
        db.flush()

    return scope


# ---------------------------------------------------------------------------
# The distinction a live run caught: no polygon vs no Overpass
# ---------------------------------------------------------------------------


def test_an_unreachable_overpass_is_retried_not_recorded_as_no_shoreline(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One timeout must not mark a mapped lake as unmapped forever.

    Both cases used to come back as None, so a network blip wrote
    `outline_source = "none"` and nothing looked again for a month.
    """
    from app.geo.outline import OverpassUnavailableError
    from app.jobs import handlers, runner

    def unavailable(*args: object, **kwargs: object) -> None:
        raise OverpassUnavailableError("ReadTimeout: overpass")

    monkeypatch.setattr(handlers, "fetch_osm_outline_strict", unavailable)
    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, handlers.OUTLINE, lake_id=lake.id)

    runner.run_one()

    job = db.query(Job).one()
    assert job.state == queue.QUEUED, "a timeout must come back"
    assert lake.outline_source is None, "a timeout is not a statement about the water"


def test_an_empty_answer_is_recorded_and_not_retried(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overpass answering "nothing here" is a fact, and the loop must stop."""
    from app.jobs import handlers, runner

    monkeypatch.setattr(handlers, "fetch_osm_outline_strict", lambda *a, **k: None)
    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, handlers.OUTLINE, lake_id=lake.id)

    runner.run_one()

    assert db.query(Job).one().state == queue.DONE
    assert lake.outline_source == "none"


def test_the_grid_waits_for_a_shoreline_rather_than_failing(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import handlers, runner

    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, handlers.GRID, lake_id=lake.id)

    message = runner.run_one()

    assert message is not None and "deferred" in message
    job = db.query(Job).one()
    assert job.state == queue.QUEUED and job.attempts == 0


# ---------------------------------------------------------------------------
# The daily hi-res grid (docs/09-BACKLOG.md §19c)
# ---------------------------------------------------------------------------


@pytest.fixture()
def big_lake(db: Session) -> Lake:
    """Well above HIRES_AREA_THRESHOLD_HA - a Zegrzynski-sized water."""
    row = Lake(
        slug="big", name="Big Water", centroid_lat=52.45, centroid_lon=21.05,
        area_ha=2046.8, timezone="Europe/Warsaw", created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def _fake_scored_cells(
    *args: object, **kwargs: object
) -> tuple[list[tuple[int, int, float]], str, str]:
    return [(0, 0, 0.5)], "summer_stagnation", "geometry_only_v0.3"


def _give_outline(lake: Lake) -> None:
    import json

    from app.geo.demo_zones import approximate_outline_geojson

    lake.outline_geojson = json.dumps(
        approximate_outline_geojson(lake.centroid_lat, lake.centroid_lon, lake.area_ha)
    )


def _give_weather(db: Session, lake: Lake) -> None:
    from app.core.models import WeatherHourly

    db.add(
        WeatherHourly(
            lake_id=lake.id, source="openmeteo_forecast", ts_utc=iso(utcnow()),
            is_forecast=0, pressure_msl=1013.0, wind_direction_10m=225.0,
            wind_speed_10m=4.0, fetched_at=iso(utcnow()),
        )
    )
    db.flush()


def test_hires_grid_skips_a_lake_below_the_size_threshold(
    db: Session, lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pomocnia-sized water: nothing finer to compute, so nothing is queued."""
    from app.core.models import HiresGridCache
    from app.jobs import handlers, runner

    lake.area_ha = 9.0
    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, handlers.GRID_HIRES, lake_id=lake.id)

    message = runner.run_one()

    assert message is not None and "below the hi-res size threshold" in message
    assert db.query(Job).one().state == queue.DONE
    assert db.query(HiresGridCache).count() == 0


def test_hires_grid_waits_for_a_shoreline(
    db: Session, big_lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import handlers, runner

    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, handlers.GRID_HIRES, lake_id=big_lake.id)

    message = runner.run_one()

    assert message is not None and "deferred" in message
    job = db.query(Job).one()
    assert job.state == queue.QUEUED and job.attempts == 0


def test_hires_grid_waits_for_todays_weather(
    db: Session, big_lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import handlers, runner

    _give_outline(big_lake)
    db.flush()
    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, handlers.GRID_HIRES, lake_id=big_lake.id)

    message = runner.run_one()

    assert message is not None and "deferred" in message
    assert "weather" in (db.query(Job).one().last_error or "")


def test_hires_grid_caches_todays_cells(
    db: Session, big_lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.models import HiresGridCache
    from app.core.time import to_display
    from app.jobs import handlers, runner

    _give_outline(big_lake)
    _give_weather(db, big_lake)
    monkeypatch.setattr(handlers.bite_view, "score_grid_cells", _fake_scored_cells)
    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))
    queue.enqueue(db, handlers.GRID_HIRES, lake_id=big_lake.id)

    message = runner.run_one()

    assert message is not None and "hi-res grid cached" in message
    assert db.query(Job).one().state == queue.DONE

    row = db.query(HiresGridCache).one()
    assert row.lake_id == big_lake.id
    assert row.for_date == to_display(utcnow()).date().isoformat()
    assert row.wind_dir == 225.0
    payload = json.loads(row.payload_json)
    assert payload["cells"] == [[0, 0, 0.5]]
    assert payload["model"] == "geometry_only_v0.3"


def test_hires_grid_replaces_rather_than_duplicates(
    db: Session, big_lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running twice in one day - e.g. a redeploy - must not pile up rows."""
    from app.core.models import HiresGridCache
    from app.jobs import handlers, runner

    _give_outline(big_lake)
    _give_weather(db, big_lake)
    monkeypatch.setattr(handlers.bite_view, "score_grid_cells", _fake_scored_cells)
    monkeypatch.setattr(runner, "session_scope", _fake_scope(db))

    queue.enqueue(db, handlers.GRID_HIRES, lake_id=big_lake.id)
    runner.run_one()
    queue.finish(db, db.query(Job).one())
    queue.enqueue(db, handlers.GRID_HIRES, lake_id=big_lake.id)
    runner.run_one()

    assert db.query(HiresGridCache).count() == 1
