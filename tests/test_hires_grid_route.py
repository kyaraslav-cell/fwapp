"""/lake/{slug}/grid: does it actually serve the daily hi-res cache for today,
and only for today (docs/09-BACKLOG.md §19c)?

Full app, not the bare function, because the thing worth proving is the
wiring: the route has to ask for `horizon`, and a forecast day must never be
answered from a cache the background job only ever writes for today.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import passwords


@pytest.fixture()
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("FISHLOG_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.delenv("FISHLOG_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("FISHLOG_GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("FISHLOG_GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.setattr(passwords, "DEFAULT_N", 1 << 12)

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)

    from app.web import app as app_module

    application = app_module.create_app()
    db_module.init_db()
    # TestClient is used without entering the lifespan - see test_auth_routes.py.
    yield TestClient(application)


CACHED_CELLS = [[99, 99, 0.777]]


def _seed_big_lake_with_cache() -> str:
    from app.core.db import session_scope
    from app.core.models import Lake
    from app.core.time import iso, to_display, utcnow
    from app.geo import hires_cache
    from app.geo.demo_zones import approximate_outline_geojson

    with session_scope() as db:
        lake = Lake(
            slug="big", name="Big Water", centroid_lat=52.45, centroid_lon=21.05,
            area_ha=2046.8, origin="discovered", timezone="Europe/Warsaw",
            created_at=iso(utcnow()),
        )
        db.add(lake)
        db.flush()
        lake.outline_geojson = json.dumps(
            approximate_outline_geojson(lake.centroid_lat, lake.centroid_lon, lake.area_ha)
        )
        lake.outline_source = "osm"
        db.flush()

        today = to_display(utcnow()).date().isoformat()
        hires_cache.store(
            db, lake.id, today, 32.0, 225.0, "summer_stagnation", "geometry_only_v0.3",
            {
                "origin_lat": lake.centroid_lat, "origin_lon": lake.centroid_lon,
                "cell_m": 32.0, "n_rows": 1, "n_cols": 1,
                "wind_dir": 225.0, "phase": "summer_stagnation",
                "model": "geometry_only_v0.3", "cells": CACHED_CELLS,
            },
        )
    return lake.slug


def test_todays_grid_is_served_from_the_hires_cache(client: TestClient) -> None:
    slug = _seed_big_lake_with_cache()

    response = client.get(f"/lake/{slug}/grid?horizon=0")

    assert response.status_code == 200
    body = response.json()
    assert body["cells"] == CACHED_CELLS
    assert body["cell_m"] == 32.0


def test_a_forecast_day_never_reads_the_hires_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is only ever written for today - horizon=1 must recompute,
    even though a (stale, wrong-day) row exists for this lake."""
    slug = _seed_big_lake_with_cache()

    from app.web import bite_view

    def fake_score(
        *args: object, **kwargs: object
    ) -> tuple[list[tuple[int, int, float]], str, str]:
        return [(1, 1, 0.25)], "summer_stagnation", "geometry_only_v0.3"

    monkeypatch.setattr(bite_view, "score_grid_cells", fake_score)

    response = client.get(f"/lake/{slug}/grid?horizon=1&wind_dir=180")

    assert response.status_code == 200
    body = response.json()
    assert body["cells"] != CACHED_CELLS
    assert body["cells"] == [[1, 1, 0.25]]


def test_a_lake_with_no_cache_falls_back_to_the_live_endpoint(client: TestClient) -> None:
    """Pomocnia is below the hi-res threshold, so the job never writes a row -
    `/grid` for today must still answer, from the on-demand path."""
    response = client.get("/lake/pomocnia/grid?horizon=0")

    assert response.status_code == 200
    assert response.json()["model"] in {"three_factor_v0.4", "geometry_only_v0.3"}
