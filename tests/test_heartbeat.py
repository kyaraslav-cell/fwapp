"""The heartbeat's job is to be wrong in only one direction.

A monitor that misses a real failure is useless, and one that cries wolf gets
muted, which turns it into the first kind. So the cases below are about which
of the two URLs gets called, and about the heartbeat never being able to take
the app down with it.
"""

from __future__ import annotations

import pytest

from app.core import heartbeat
from app.web.health import Health

URL = "https://hc-ping.com/00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(heartbeat, "_misses", 0)
    monkeypatch.setattr(heartbeat, "_last_status", None)
    monkeypatch.setenv("FISHLOG_HEALTHCHECK_URL", URL)


def _health(status: str) -> Health:
    return Health(
        status=status,
        latest_observation="2026-09-09T06:00:00Z",
        age_hours=1.0,
        unresolved_gaps=0,
        detail="",
    )


def _capture(monkeypatch, health_status="ok", post_ok=True):
    calls: list[tuple[str, str]] = []

    def fake_post(url, body):
        calls.append((url, body))
        return post_ok

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(heartbeat, "_post", fake_post)
    monkeypatch.setattr(heartbeat, "session_scope", lambda: _Session())
    monkeypatch.setattr(heartbeat.health_mod, "check", lambda db: _health(health_status))
    return calls


def test_healthy_pings_the_plain_url(monkeypatch):
    calls = _capture(monkeypatch, "ok")
    heartbeat.beat()
    assert len(calls) == 1
    assert calls[0][0] == URL


@pytest.mark.parametrize("status", ["stale", "unknown"])
def test_unhealthy_pings_fail(monkeypatch, status):
    """The case this whole module exists for.

    A stale app is up and serving pages built from old weather. Reporting that
    as healthy - which any liveness ping would - hides exactly the failure the
    monitor is for.
    """
    calls = _capture(monkeypatch, status)
    heartbeat.beat()
    assert calls[0][0] == URL + "/fail"


def test_unreadable_database_reports_failure_rather_than_silence(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(heartbeat, "_post", lambda u, b: calls.append((u, b)) or True)

    def boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(heartbeat, "session_scope", boom)
    heartbeat.beat()
    assert calls[0][0] == URL + "/fail"
    assert "RuntimeError" in calls[0][1]


def test_unset_url_sends_nothing(monkeypatch):
    monkeypatch.delenv("FISHLOG_HEALTHCHECK_URL", raising=False)
    calls = _capture(monkeypatch, "ok")
    heartbeat.beat()
    assert calls == []


def test_a_broken_monitor_cannot_break_the_app(monkeypatch):
    """httpx raising must never escape. The scheduler job has no try/except of
    its own precisely because this is guaranteed here."""

    def explode(*a, **k):
        raise OSError("network on fire")

    monkeypatch.setattr(heartbeat.httpx, "post", explode)
    assert heartbeat._post(URL, "x") is False


def test_body_carries_no_lake_names(monkeypatch):
    calls = _capture(monkeypatch, "stale")
    heartbeat.beat()
    body = calls[0][1]
    assert "status" in body and "gaps" in body
    assert "pomocnia" not in body.lower()
