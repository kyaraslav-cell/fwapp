"""Security headers, `/health`, error pages, and the notebook's query shape.

The four items from `docs/15 §A1`–`§A4`. What each test is defending:

- headers must reach **every** response, including the ones that skip the
  router - a 404, a static file, an unhandled exception. Those are the exact
  responses that go out bare when the middleware is in the wrong place.
- `/health` must answer **503 when the weather is stale**. A monitor that
  checks only the status code - which is most of them - would otherwise report
  green while the app serves last week's forecast.
- an error must be a page an angler can act on, in their language.
- `list_sessions` must issue a bounded number of queries no matter how many
  sessions there are, and a blank session must still appear in the list.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.auth import passwords
from app.web import security


@pytest.fixture()
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("FISHLOG_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(passwords, "DEFAULT_N", 1 << 12)

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)

    from app.web import app as app_module

    application = app_module.create_app()
    db_module.init_db()
    yield TestClient(application)


# --------------------------------------------------------------------------
# A1 — security headers
# --------------------------------------------------------------------------


def test_every_header_is_present_on_an_ordinary_page(client: TestClient) -> None:
    response = client.get("/")
    for name in security.BASE_HEADERS:
        assert name in response.headers, f"{name} missing"


def test_headers_reach_a_404_as_well(client: TestClient) -> None:
    """The response that skips the router is the one that goes out bare.

    This is why the header middleware is the outermost one.
    """
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "Content-Security-Policy" in response.headers


def test_headers_reach_static_files(client: TestClient) -> None:
    """`/media` serves angler-uploaded files from the session cookie's origin.

    StaticFiles answers without touching the router, so a middleware placed
    inside it would leave exactly the responses that most need `nosniff`
    without it.
    """
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_policy_admits_what_the_page_actually_loads() -> None:
    """A CSP that blocks the map is a CSP somebody will delete in a hurry."""
    assert "https://unpkg.com" in security.CSP           # Leaflet
    assert "arcgisonline.com" in security.CSP            # Esri tiles
    assert "https://fonts.gstatic.com" in security.CSP   # the font FILES, not
    assert "https://fonts.googleapis.com" in security.CSP  # only the stylesheet
    assert "data:" in security.CSP                       # the canvas overlay


def test_the_policy_closes_what_it_should() -> None:
    assert "frame-ancestors 'none'" in security.CSP
    assert "object-src 'none'" in security.CSP
    assert "connect-src 'self'" in security.CSP, (
        "an injected script could post the notebook to another host"
    )


def test_hsts_only_over_https() -> None:
    """Set on plain http it is ignored; set on localhost it pins a developer's
    browser to https for two years, which is genuinely painful to undo."""
    assert "Strict-Transport-Security" not in security.headers_for("http")
    assert "Strict-Transport-Security" in security.headers_for("https")


# --------------------------------------------------------------------------
# A4 — /health
# --------------------------------------------------------------------------


def test_health_is_503_when_nothing_has_ever_been_ingested(client: TestClient) -> None:
    """A fresh install and a dead one look the same from here - honestly so."""
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "stale"
    assert body["latest_observation"] is None


def test_health_is_ok_when_the_weather_is_fresh(client: TestClient) -> None:
    from app.core.db import session_scope
    from app.core.models import WeatherHourly
    from app.core.time import iso, utcnow

    with session_scope() as db:
        db.add(
            WeatherHourly(
                lake_id=1,
                source="openmeteo_forecast",
                ts_utc=iso(utcnow()),
                is_forecast=0,
                pressure_msl=1013.0,
                fetched_at=iso(utcnow()),
            )
        )

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_turns_stale_and_says_so(client: TestClient) -> None:
    """The failure that matters: every page still renders, and is describing
    last week."""
    from datetime import timedelta

    from app.core.db import session_scope
    from app.core.models import WeatherHourly
    from app.core.time import iso, utcnow
    from app.web import health as health_check

    with session_scope() as db:
        db.add(
            WeatherHourly(
                lake_id=1,
                source="openmeteo_forecast",
                ts_utc=iso(utcnow() - timedelta(hours=health_check.FRESH_HOURS + 2)),
                is_forecast=0,
                pressure_msl=1013.0,
                fetched_at=iso(utcnow()),
            )
        )

    response = client.get("/health")
    assert response.status_code == 503, "a monitor watching the status code saw green"
    body = response.json()
    assert body["status"] == "stale"
    assert body["age_hours"] > health_check.FRESH_HOURS


def test_health_is_never_cached(client: TestClient) -> None:
    assert client.get("/health").headers["cache-control"] == "no-store"


def test_health_leaks_nothing_about_who_fishes_here(client: TestClient) -> None:
    """It ends up in logs and other people's dashboards."""
    body = client.get("/health").json()
    assert set(body) == {
        "status",
        "latest_observation",
        "age_hours",
        "unresolved_gaps",
        "detail",
    }


def test_a_broken_database_is_reported_as_unknown_not_as_stale() -> None:
    """"No weather" and "no database" need different hands."""
    from app.web import health as health_check

    class Broken:
        def execute(self, *a: object, **k: object) -> object:
            raise RuntimeError("disk I/O error")

    report = health_check.check(Broken())  # type: ignore[arg-type]
    assert report.status == "unknown"
    assert report.http_status == 503


# --------------------------------------------------------------------------
# A4 — error pages
# --------------------------------------------------------------------------


def test_a_404_is_a_page_not_json(client: TestClient) -> None:
    response = client.get("/no-such-page", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert "<html" in response.text.lower()
    assert "Back to your places" in response.text


def test_the_error_page_is_translated(client: TestClient) -> None:
    client.cookies.set("fishlog_lang", "pl")
    response = client.get("/no-such-page", headers={"accept": "text/html"})
    assert "Wróć do łowisk" in response.text


def test_an_api_style_request_still_gets_json(client: TestClient) -> None:
    """Swapping an error page into an HTMX fragment looks broken in a much
    more confusing way than a plain message."""
    response = client.get("/no-such-page", headers={"accept": "application/json"})
    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"


# --------------------------------------------------------------------------
# A3 — the notebook's query shape
# --------------------------------------------------------------------------


def test_listing_sessions_does_not_scale_its_query_count(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The N+1: 200 sessions used to mean 201 queries, growing every trip.

    Counted rather than timed - a timing assertion on a fast machine passes
    with the bug still in place.
    """
    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "n1.db"))
    monkeypatch.setenv("FISHLOG_MEDIA_DIR", str(tmp_path / "media"))

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)
    db_module.init_db()

    from app.core.models import Catch, FishSession, Lake
    from app.core.time import iso, utcnow
    from app.notebook.sessions import list_sessions

    with db_module.session_scope() as db:
        lake = Lake(
            slug="probe",
            name="Probe",
            centroid_lat=52.5,
            centroid_lon=20.6,
            area_ha=9.0,
            timezone="Europe/Warsaw",
            created_at=iso(utcnow()),
        )
        db.add(lake)
        db.flush()
        lake_id = lake.id
        for i in range(12):
            fs = FishSession(
                lake_id=lake_id,
                user_id=1,
                started_at=iso(utcnow()),
                ended_at=iso(utcnow()),
                effort_minutes=120,
                created_at=iso(utcnow()),
            )
            db.add(fs)
            db.flush()
            # Every other session is a blank one. Law 3: a zero is data, and
            # it must survive a rewrite that groups by catches.
            if i % 2 == 0:
                db.add(Catch(session_id=fs.id, species="roach", count=3))

    counts: list[str] = []

    engine = db_module.get_engine()

    def record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        counts.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with db_module.session_scope() as db:
            lake = db.get(Lake, lake_id)
            assert lake is not None
            summaries = list_sessions(db, lake, user_id=1)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(summaries) == 12
    selects = [s for s in counts if s.strip().upper().startswith("SELECT")]
    assert len(selects) <= 3, (
        f"{len(selects)} queries for 12 sessions - the N+1 is back:\n"
        + "\n".join(selects)
    )

    # And the blank sessions are still there, with a real zero.
    blanks = [s for s in summaries if s.total_fish == 0]
    assert len(blanks) == 6, "blank sessions were dropped by the grouped query"
    assert all(s.cpue == 0.0 for s in blanks)


def test_the_notebook_foreign_keys_are_indexed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQLite indexes primary keys and nothing else; a FK scans until told."""
    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "idx.db"))

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)
    db_module.init_db()

    from sqlalchemy import inspect

    inspector = inspect(db_module.get_engine())
    for table, expected in (
        ("session", "ix_session_lake_user"),
        ("catch", "ix_catch_session"),
        ("session_leg", "ix_session_leg_session"),
    ):
        names = {i["name"] for i in inspector.get_indexes(table)}
        assert expected in names, f"{table} has no {expected}: {names}"


def test_an_index_added_later_reaches_an_existing_database(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`create_all` skips a table that exists — and skips its indexes with it.

    Without `create_missing_indexes`, every index added after the first run
    would apply to fresh installs only, and the owner's own database — the one
    with the season in it — would keep scanning forever.
    """
    from sqlalchemy import Index, inspect

    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "later.db"))

    import app.core.db as db_module
    from app.core.migrate import create_missing_indexes
    from app.core.models import Base, Catch

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)
    db_module.init_db()
    engine = db_module.get_engine()

    added = Index("ix_catch_added_later", Catch.__table__.c.species)
    try:
        assert "ix_catch_added_later" not in {
            i["name"] for i in inspect(engine).get_indexes("catch")
        }
        created = create_missing_indexes(engine)
        assert "ix_catch_added_later" in created
        assert "ix_catch_added_later" in {
            i["name"] for i in inspect(engine).get_indexes("catch")
        }
        # Idempotent: a second run must not try to create it again.
        assert "ix_catch_added_later" not in create_missing_indexes(engine)
    finally:
        Base.metadata.tables["catch"].indexes.discard(added)
