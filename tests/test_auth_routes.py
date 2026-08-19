"""The security boundary, exercised through the real app.

`tests/test_auth.py` proves the pieces. This proves the wiring: which pages need
an account, that a form comes back with its errors, that one angler cannot open
another's catch, and that signing out actually ends the session.

The app is built against a temporary database (`FISHLOG_DB_PATH`), and the
scheduler and the startup ingest are skipped - a test that reaches Open-Meteo
would be a test of the network.
"""

from __future__ import annotations

import os
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
    # TestClient is used without entering the lifespan: `with TestClient(...)`
    # would run it, which starts APScheduler and calls Open-Meteo.
    yield TestClient(application)


GOOD = {
    "email": "angler@example.com",
    "display_name": "Ann",
    "password": "bream-on-the-margin",
    "password_confirm": "bream-on-the-margin",
}


def register(client: TestClient, **overrides: str):
    payload = dict(GOOD)
    payload.update(overrides)
    return client.post("/auth/register", data=payload, follow_redirects=False)


def test_the_lake_stays_open_and_the_notebook_does_not(client: TestClient) -> None:
    """The published site reads; the notebook is private. That is the boundary."""
    assert client.get("/").status_code == 200
    assert client.get("/lake/pomocnia").status_code == 200

    for private in ("/history", "/session/active", "/session/end", "/places/new"):
        response = client.get(private, follow_redirects=False)
        assert response.status_code == 303, private
        assert response.headers["location"].startswith("/auth/login?next=")


def test_sign_in_sends_you_back_where_you_were(client: TestClient) -> None:
    response = client.get("/history", follow_redirects=False)
    assert response.headers["location"] == "/auth/login?next=/history"


def test_register_signs_you_in_and_sets_an_httponly_cookie(client: TestClient) -> None:
    response = register(client)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "fishlog_auth=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite", "SameSite")
    assert client.get("/history").status_code == 200


def test_a_bad_registration_comes_back_with_every_error_at_once(client: TestClient) -> None:
    response = register(
        client, email="not-an-email", display_name="", password="short", password_confirm="other"
    )
    assert response.status_code == 422
    body = response.text
    assert "does not look like an email" in body
    assert "Enter a name" in body
    assert "at least 10 characters" in body
    assert "do not match" in body


def test_the_password_never_comes_back_in_the_re_rendered_form(client: TestClient) -> None:
    """A form that echoes the password puts it in every proxy log and cache."""
    response = register(client, email="not-an-email", password="hunter2-hunter2",
                        password_confirm="hunter2-hunter2")
    assert response.status_code == 422
    assert "hunter2-hunter2" not in response.text


def test_the_same_address_cannot_register_twice(client: TestClient) -> None:
    assert register(client).status_code == 303
    client.cookies.clear()
    again = register(client)
    assert again.status_code == 409
    assert "already an account" in again.text


def test_wrong_password_and_unknown_address_give_the_same_answer(client: TestClient) -> None:
    """Otherwise the login form tells a prober which addresses exist."""
    register(client)
    client.cookies.clear()

    wrong = client.post(
        "/auth/login", data={"email": GOOD["email"], "password": "not-it-at-all"}
    )
    unknown = client.post(
        "/auth/login", data={"email": "nobody@example.com", "password": "not-it-at-all"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert "Wrong email or password" in wrong.text
    assert "Wrong email or password" in unknown.text


def test_sign_out_ends_the_session(client: TestClient) -> None:
    register(client)
    assert client.get("/history").status_code == 200
    client.post("/auth/logout", follow_redirects=False)
    assert client.get("/history", follow_redirects=False).status_code == 303


def test_a_stale_cookie_does_not_sign_anybody_in(client: TestClient) -> None:
    register(client)
    client.post("/auth/logout", follow_redirects=False)
    # Put the revoked token back by hand - a stolen cookie replayed.
    client.cookies.set("fishlog_auth", "clearly-not-a-real-token")
    assert client.get("/history", follow_redirects=False).status_code == 303


def test_one_angler_cannot_open_another_anglers_catch(client: TestClient) -> None:
    """The IDOR that accounts create if nothing checks ownership."""
    register(client)
    start = client.post(
        "/lake/pomocnia/spot",
        data={"lat": "52.0", "lon": "21.0", "cell": "r1c1", "method": "feeder", "rod_count": "2"},
        follow_redirects=False,
    )
    assert start.status_code == 303
    client.post("/session/catch", data={"species": "roach"}, follow_redirects=False)

    from app.core.db import session_scope
    from app.core.models import Catch

    with session_scope() as db:
        catch_id = db.query(Catch).one().id

    client.cookies.clear()
    register(client, email="other@example.com", display_name="Other")
    assert client.get(f"/session/catch/{catch_id}/edit").status_code == 404
    assert client.post(f"/session/catch/{catch_id}/delete").status_code == 404

    with session_scope() as db:
        assert db.query(Catch).count() == 1, "the other angler's catch was deleted"


def test_the_google_button_is_hidden_when_google_is_not_configured(client: TestClient) -> None:
    assert "auth/google" not in client.get("/auth/login").text
    assert client.get("/auth/google", follow_redirects=False).status_code == 503


def test_the_google_button_appears_once_it_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FISHLOG_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("FISHLOG_GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("FISHLOG_GOOGLE_REDIRECT_URI", "https://fish.example/auth/google/callback")

    assert "auth/google" in client.get("/auth/login").text
    start = client.get("/auth/google", follow_redirects=False)
    assert start.status_code == 303
    assert start.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "fishlog_oauth_state=" in start.headers["set-cookie"]


def test_a_google_callback_with_the_wrong_state_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the state check the callback accepts a code anyone can plant."""
    monkeypatch.setenv("FISHLOG_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("FISHLOG_GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("FISHLOG_GOOGLE_REDIRECT_URI", "https://fish.example/auth/google/callback")

    client.get("/auth/google", follow_redirects=False)
    response = client.get(
        "/auth/google/callback?code=whatever&state=not-the-one", follow_redirects=False
    )
    assert response.status_code == 400
    assert "expired" in response.text


def test_the_login_form_will_not_bounce_you_off_site(client: TestClient) -> None:
    """`next` is attacker-supplied. An open redirect on a login page is a phish."""
    register(client)
    client.cookies.clear()
    response = client.post(
        "/auth/login",
        data={"email": GOOD["email"], "password": GOOD["password"], "next": "//evil.example/"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_registration_still_works_with_google_configured_but_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sandbox cannot reach Google (docs/10 §6). Passwords must not care."""
    monkeypatch.setenv("FISHLOG_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("FISHLOG_GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("FISHLOG_GOOGLE_REDIRECT_URI", "https://fish.example/auth/google/callback")
    assert register(client).status_code == 303


def test_os_environ_is_left_as_it_was_found() -> None:
    """Guards the fixture itself: a leaked env var would make later tests lie."""
    assert "FISHLOG_GOOGLE_CLIENT_ID" not in os.environ


def test_the_day_strip_is_public_and_carries_no_score(client: TestClient) -> None:
    """The calendar is weather, not notebook - it stays open like the map.

    Also guards the owner's standing rule at the page level: the strip may
    carry colours and times, never a number out of ten.
    """
    body = client.get("/lake/pomocnia").text
    assert 'id="calendar-toggle"' in body
    assert 'class="day-strip"' in body
    assert body.count("day-chip ") >= 8 or body.count('class="day-chip') >= 8
    # No day_score anywhere in the rendered strip.
    strip = body[body.index('id="day-strip"'): body.index("day-strip-note")]
    assert "day_score" not in strip


# ---------------------------------------------------------------------------
# Adding a water, through the real app
# ---------------------------------------------------------------------------


def test_adding_a_water_needs_an_account(client: TestClient) -> None:
    response = client.get("/places/new", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/auth/login?next=")


def test_a_search_that_finds_nothing_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.discover import nominatim

    monkeypatch.setattr(nominatim, "search", lambda *a, **k: [])
    register(client)

    body = client.get("/places/new?q=Nonexistent+Lake").text
    assert "Nothing found" in body


def test_a_geocoder_outage_creates_nothing_and_says_which_part_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure mode that will actually happen: a shared free service saying no."""
    from app.core.db import session_scope
    from app.core.models import Lake
    from app.discover import nominatim

    def down(*args: object, **kwargs: object) -> list[nominatim.Candidate]:
        raise nominatim.NominatimError("503")

    monkeypatch.setattr(nominatim, "search", down)
    register(client)

    response = client.get("/places/new?q=Jezioro")
    assert response.status_code == 503
    assert "map search service" in response.text
    with session_scope() as db:
        assert db.query(Lake).count() == 0, "a failed search must create nothing"


def test_adding_a_water_creates_it_and_queues_the_work(client: TestClient) -> None:
    from app.core.db import session_scope
    from app.core.models import Job, Lake

    register(client)
    response = client.post(
        "/places/new",
        data={
            "name": "Jezioro Zegrzyńskie",
            "display_name": "Jezioro Zegrzyńskie, Poland",
            "lat": "52.45",
            "lon": "21.05",
            "osm_type": "way",
            "osm_id": "12345",
            "area_ha": "3300",
            "is_water": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/lake/jezioro-zegrzynskie"

    with session_scope() as db:
        lake = db.query(Lake).filter(Lake.slug == "jezioro-zegrzynskie").one()
        assert lake.origin == "discovered"
        assert db.query(Job).filter(Job.lake_id == lake.id).count() == 4


def test_a_water_with_no_outline_still_has_a_working_page(client: TestClient) -> None:
    """Satellite map, pin and forecast work; the overlay is absent and says so.

    This is the whole "no circle fallback" decision (ADR 0005 §4) checked end to
    end: the page must render, and /grid must answer with no cells rather than
    with cells computed over an invented shoreline.
    """
    register(client)
    client.post(
        "/places/new",
        data={
            "name": "Staw Testowy", "display_name": "Staw Testowy", "lat": "52.1",
            "lon": "21.1", "osm_type": "way", "osm_id": "777", "area_ha": "4",
            "is_water": "1",
        },
        follow_redirects=False,
    )

    page = client.get("/lake/staw-testowy")
    assert page.status_code == 200
    assert "shoreline" in page.text or "OpenStreetMap" in page.text

    grid = client.get("/lake/staw-testowy/grid?wind_dir=270")
    assert grid.status_code == 200
    assert grid.json() == {
        "cells": [], "model": "no_outline", "wind_dir": 270.0, "phase": "",
    }


def test_the_quota_stops_the_sixth_water(client: TestClient) -> None:
    from app.discover.service import DAILY_ADD_QUOTA

    register(client)
    for i in range(DAILY_ADD_QUOTA):
        client.post(
            "/places/new",
            data={
                "name": f"Jezioro Test {i}", "display_name": "x", "lat": str(52.0 + i),
                "lon": "21.0", "osm_type": "way", "osm_id": str(500 + i),
                "area_ha": "10", "is_water": "1",
            },
            follow_redirects=False,
        )

    response = client.post(
        "/places/new",
        data={
            "name": "One Too Many", "display_name": "x", "lat": "60.0", "lon": "21.0",
            "osm_type": "way", "osm_id": "9999", "area_ha": "10", "is_water": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 429
    assert "allowance" in response.text
