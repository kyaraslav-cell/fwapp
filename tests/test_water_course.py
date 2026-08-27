"""Rivers and canals: no shoreline, but still a water and still a map.

Kanał Żerański is a `type=waterway` relation of line segments. OpenStreetMap
has no closed ring for it anywhere - the outline fetch was right to find
nothing - and the lake page then rendered **no map at all**: a null outline
threw inside the map's `try`, and the catch hid the whole element. The angler
got a page that said "everything else works" above a blank space where the
satellite view should be.

A course is not an outline and is never used as one. It cannot be clipped into
a grid, so these waters still get no zone overlay. What it does is put the
water on the map instead of a blank rectangle.

Buffering the centreline by a guessed width would have produced a "shoreline"
nobody has ever surveyed, which is exactly what ADR 0005 §4 refuses.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Job, Lake
from app.core.time import iso, utcnow
from app.geo import outline as outline_mod
from app.jobs import queue
from app.web.build_status import NO_OUTLINE, READY, status_for


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _canal(db: Session, source: str | None = None) -> Lake:
    row = Lake(
        slug="kanal-zeranski",
        name="Kanał Żerański",
        centroid_lat=52.32,
        centroid_lon=21.02,
        timezone="Europe/Warsaw",
        origin="discovered",
        osm_type="relation",
        osm_id=1531086,
        outline_source=source,
        created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def _job(lake: Lake, kind: str, state: str) -> Job:
    return Job(
        lake_id=lake.id, kind=kind, state=state, attempts=1,
        run_after=iso(utcnow()), created_at=iso(utcnow()),
    )


def test_a_relation_of_line_segments_yields_a_course(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real shape of the Overpass answer for a waterway relation."""
    payload = {
        "elements": [
            {
                "type": "relation",
                "members": [
                    {"role": "", "geometry": [
                        {"lat": 52.30, "lon": 21.03}, {"lat": 52.35, "lon": 21.01},
                    ]},
                    {"role": "main_stream", "geometry": [
                        {"lat": 52.35, "lon": 21.01}, {"lat": 52.45, "lon": 20.99},
                    ]},
                ],
            }
        ]
    }

    class _Resp:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> dict[str, object]:
            return payload

    class _Client:
        def __init__(self, *a: object, **kw: object) -> None: ...
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: object) -> None: ...
        def post(self, *a: object, **kw: object) -> _Resp:
            return _Resp()

    monkeypatch.setattr(outline_mod.httpx, "Client", _Client)

    course = outline_mod.fetch_osm_course("relation", 1531086)

    assert course is not None
    assert course["type"] == "MultiLineString"
    assert len(course["coordinates"]) == 2
    # GeoJSON is (lon, lat), not (lat, lon).
    assert course["coordinates"][0][0] == [21.03, 52.30]


def test_members_that_are_not_the_water_are_left_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A waterway relation also carries locks and side channels.

    Drawing those would put lines across the map that are not the canal.
    """
    payload = {
        "elements": [
            {
                "type": "relation",
                "members": [
                    {"role": "main_stream", "geometry": [
                        {"lat": 52.30, "lon": 21.03}, {"lat": 52.35, "lon": 21.01},
                    ]},
                    {"role": "side_stream", "geometry": [
                        {"lat": 52.31, "lon": 21.05}, {"lat": 52.32, "lon": 21.06},
                    ]},
                ],
            }
        ]
    }

    class _Resp:
        @staticmethod
        def raise_for_status() -> None: ...

        @staticmethod
        def json() -> dict[str, object]:
            return payload

    class _Client:
        def __init__(self, *a: object, **kw: object) -> None: ...
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *a: object) -> None: ...
        def post(self, *a: object, **kw: object) -> _Resp:
            return _Resp()

    monkeypatch.setattr(outline_mod.httpx, "Client", _Client)

    course = outline_mod.fetch_osm_course("relation", 1)

    assert course is not None
    assert len(course["coordinates"]) == 1


def test_a_line_water_is_finished_not_broken(db: Session) -> None:
    lake = _canal(db, source="osm_line")
    db.add(_job(lake, "outline", queue.DONE))
    db.flush()

    status = status_for(db, lake)

    assert status.state == NO_OUTLINE
    assert status.message_key == "build.line_only", (
        "'no shoreline' understates a page that is showing the water's course"
    )


def test_a_water_with_a_real_polygon_is_unaffected(db: Session) -> None:
    lake = _canal(db, source="osm")
    db.add(_job(lake, "outline", queue.DONE))
    db.flush()

    assert status_for(db, lake).state == READY
