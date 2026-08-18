"""A committed shoreline must beat everything, because the network is unreliable
in exactly the place it matters.

The bug: `ensure_outline` fetched from Overpass at build time. Overpass throttles
cloud IP ranges, so GitHub's runner failed and fell back to a circle while a
developer machine got the true polygon - the published map scored a lake shape
that does not exist, and nothing failed loudly.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Lake
from app.geo import service as geo

REAL_RING = [
    [20.670, 52.545], [20.676, 52.546], [20.682, 52.544], [20.683, 52.541],
    [20.679, 52.539], [20.673, 52.539], [20.669, 52.541], [20.668, 52.543],
    [20.670, 52.545],
]
SURVEYED: dict[str, Any] = {"type": "Polygon", "coordinates": [REAL_RING]}


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        Lake(
            slug="testlake", name="Test", centroid_lat=52.5431, centroid_lon=20.6762,
            area_ha=9.0, created_at=dt.datetime(2026, 8, 18, tzinfo=dt.UTC).isoformat(),
        )
    )
    session.commit()
    return session


@pytest.fixture()
def committed(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    lakes = tmp_path / "lakes"
    lakes.mkdir()
    monkeypatch.setattr(geo, "CONFIG_DIR", tmp_path)
    return lakes / "testlake.outline.geojson"


def _lake(db: Session) -> Lake:
    return db.execute(select(Lake)).scalars().one()


def test_committed_outline_is_used_without_touching_the_network(
    db: Session, committed: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    committed.write_text(json.dumps(SURVEYED), encoding="utf-8")

    def must_not_be_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("Overpass must not be called when a shoreline is committed")

    monkeypatch.setattr(geo, "fetch_osm_outline", must_not_be_called)

    lake = _lake(db)
    assert geo.ensure_outline(db, lake) == SURVEYED
    assert lake.outline_source == "osm_committed"


def test_without_a_committed_file_a_failed_fetch_falls_back_to_a_circle(
    db: Session, committed: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old behaviour, kept and pinned - this is what the published site was
    doing every single build, and the point is that it now says so."""
    monkeypatch.setattr(geo, "fetch_osm_outline", lambda lat, lon: None)
    lake = _lake(db)
    outline = geo.ensure_outline(db, lake)
    assert outline["type"] == "Polygon"
    assert lake.outline_source == "circle_fallback"


def test_the_two_shapes_are_actually_different(
    db: Session, committed: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards the whole point: a circle is not the lake.

    If these ever compared equal, the fallback would be harmless and none of
    this would matter. They do not, which is why the published map and the
    development map showed different lakes.
    """
    monkeypatch.setattr(geo, "fetch_osm_outline", lambda lat, lon: None)
    circle = geo.ensure_outline(db, _lake(db))

    committed.write_text(json.dumps(SURVEYED), encoding="utf-8")
    lake = _lake(db)
    lake.outline_geojson = None
    surveyed = geo.ensure_outline(db, lake)

    assert surveyed != circle
    assert len(circle["coordinates"][0]) != len(surveyed["coordinates"][0])
