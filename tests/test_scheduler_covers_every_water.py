"""The hourly jobs must touch every water, not just the seeded one.

Both `run_ingest_job` and `run_predict_job` used to call `ensure_lake_seeded`
and operate on its single return value. A water added through the discover
pipeline therefore got one forecast at add-time and was never updated again.

Three separate owner-reported bugs came out of that one line:

  * the "Right now" card on Zalew Zegrzynski was frozen at the hour the water
    was added, two days earlier;
  * its day strip ran out, because predictions stopped at add-time + 7;
  * the places list said "no data yet" against it forever, because `home()`
    asks for a horizon-0 prediction and nothing ever wrote one.

A test that only checked the seeded lake would have passed throughout.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Lake
from app.core.time import iso, utcnow
from app.ingest import scheduler


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _lake(db: Session, slug: str, origin: str) -> Lake:
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


@pytest.fixture()
def three_waters(db: Session, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    _lake(db, "pomocnia", "seed")
    _lake(db, "zegrzynski", "discovered")
    _lake(db, "poniaty", "discovered")

    class _Scope:
        def __enter__(self) -> Session:
            return db

        def __exit__(self, *a: object) -> None: ...

    monkeypatch.setattr(scheduler, "session_scope", lambda: _Scope())
    # The seeded lake already exists here; seeding again would need config and
    # a real species table, and is not what these tests are about.
    monkeypatch.setattr(scheduler, "ensure_lake_seeded", lambda _db: None)
    return ["pomocnia", "zegrzynski", "poniaty"]


def test_ingest_fetches_for_every_water(
    three_waters: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        scheduler, "ingest_forecast", lambda _db, lake: seen.append(lake.slug) or 1
    )

    scheduler.run_ingest_job()

    assert sorted(seen) == sorted(three_waters)


def test_predictions_are_written_for_every_water(
    three_waters: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        scheduler, "generate_predictions", lambda _db, lake: seen.append(lake.slug) or []
    )

    scheduler.run_predict_job()

    assert sorted(seen) == sorted(three_waters)


def test_one_water_failing_does_not_rob_the_others(
    three_waters: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open-Meteo refusing one set of coordinates is not a reason to skip the rest."""
    seen: list[str] = []

    def _flaky(_db: Session, lake: Lake) -> int:
        if lake.slug == "zegrzynski":
            raise RuntimeError("Open-Meteo said no")
        seen.append(lake.slug)
        return 1

    monkeypatch.setattr(scheduler, "ingest_forecast", _flaky)

    scheduler.run_ingest_job()

    assert sorted(seen) == ["pomocnia", "poniaty"]


def test_one_water_failing_does_not_rob_the_others_of_predictions(
    three_waters: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def _flaky(_db: Session, lake: Lake) -> list[object]:
        if lake.slug == "pomocnia":
            raise RuntimeError("pressure history too short")
        seen.append(lake.slug)
        return []

    monkeypatch.setattr(scheduler, "generate_predictions", _flaky)

    scheduler.run_predict_job()

    assert sorted(seen) == ["poniaty", "zegrzynski"]
