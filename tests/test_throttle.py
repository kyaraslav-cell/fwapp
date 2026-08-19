"""Rate limiting, at both levels: the counters, and the form that uses them.

The counters are exercised with an explicit clock, because every window here is
a time window and a test that waited fifteen minutes would never be run.

What these assert, in the order they matter:

1. the tight pair limit stops an ordinary flood;
2. a *different* address from the same IP is not collateral damage, which is
   what makes the pair limit safe to set as low as 5;
3. a right password clears the counter, so a fumbled password on the bank does
   not follow the angler into next week;
4. the refusal happens before the password is checked - the whole point being
   to stop paying scrypt for attempts we are refusing anyway;
5. a forged `X-Forwarded-For` cannot mint a fresh IP per attempt.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import passwords, throttle
from app.core.models import Base
from app.core.time import utcnow

# --------------------------------------------------------------------------
# The counters
# --------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: pathlib.Path) -> Iterator[Session]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'throttle.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_pair_limit_refuses_after_its_budget(db: Session) -> None:
    now = utcnow()
    rule = throttle.LOGIN_RULES[0]
    for i in range(rule.limit):
        assert throttle.check(
            db, throttle.LOGIN_RULES, email="a@example.com", ip="10.0.0.1", now=now
        ).allowed, f"refused after only {i} failures"
        throttle.record(
            db, throttle.LOGIN_FAIL, email="a@example.com", ip="10.0.0.1", now=now
        )

    decision = throttle.check(
        db, throttle.LOGIN_RULES, email="a@example.com", ip="10.0.0.1", now=now
    )
    assert not decision.allowed
    assert decision.rule == "pair"
    # The wait is until the oldest failure leaves the window, never a guess.
    assert decision.retry_after == pytest.approx(rule.window.total_seconds(), abs=2)


def test_another_address_from_the_same_ip_is_untouched(db: Session) -> None:
    """The pair limit is tight, so it must not spill onto the neighbours.

    Without this the family sharing one router would lock each other out, and
    the tight limit could not have been set at 5 at all.
    """
    now = utcnow()
    for _ in range(throttle.LOGIN_RULES[0].limit + 2):
        throttle.record(
            db, throttle.LOGIN_FAIL, email="a@example.com", ip="10.0.0.1", now=now
        )
    assert throttle.check(
        db, throttle.LOGIN_RULES, email="b@example.com", ip="10.0.0.1", now=now
    ).allowed


def test_ip_limit_catches_spraying_across_many_addresses(db: Session) -> None:
    now = utcnow()
    ip_rule = next(r for r in throttle.LOGIN_RULES if r.name == "ip")
    for i in range(ip_rule.limit):
        throttle.record(
            db, throttle.LOGIN_FAIL, email=f"angler{i}@example.com", ip="10.0.0.9", now=now
        )
    decision = throttle.check(
        db, throttle.LOGIN_RULES, email="fresh@example.com", ip="10.0.0.9", now=now
    )
    assert not decision.allowed
    assert decision.rule == "ip"


def test_distributed_guessing_at_one_address_is_caught_by_the_email_rule(
    db: Session,
) -> None:
    now = utcnow()
    email_rule = next(r for r in throttle.LOGIN_RULES if r.name == "email")
    for i in range(email_rule.limit):
        throttle.record(
            db, throttle.LOGIN_FAIL, email="target@example.com", ip=f"10.0.{i}.1", now=now
        )
    decision = throttle.check(
        db, throttle.LOGIN_RULES, email="target@example.com", ip="10.9.9.9", now=now
    )
    assert not decision.allowed
    assert decision.rule == "email"


def test_the_window_slides(db: Session) -> None:
    now = utcnow()
    rule = throttle.LOGIN_RULES[0]
    for _ in range(rule.limit):
        throttle.record(
            db, throttle.LOGIN_FAIL, email="a@example.com", ip="10.0.0.1", now=now
        )
    assert not throttle.check(
        db, throttle.LOGIN_RULES, email="a@example.com", ip="10.0.0.1", now=now
    ).allowed

    later = now + rule.window + timedelta(seconds=1)
    assert throttle.check(
        db, throttle.LOGIN_RULES, email="a@example.com", ip="10.0.0.1", now=later
    ).allowed


def test_success_clears_that_address_only(db: Session) -> None:
    now = utcnow()
    for _ in range(4):
        throttle.record(
            db, throttle.LOGIN_FAIL, email="a@example.com", ip="10.0.0.1", now=now
        )
        throttle.record(
            db, throttle.LOGIN_FAIL, email="b@example.com", ip="10.0.0.1", now=now
        )

    throttle.clear_failures(db, "a@example.com")

    rule = throttle.LOGIN_RULES[0]
    a_count, _ = throttle._count_and_oldest(db, rule, "a@example.com", "10.0.0.1", now)
    b_count, _ = throttle._count_and_oldest(db, rule, "b@example.com", "10.0.0.1", now)
    assert a_count == 0
    assert b_count == 4, "signing in to one account cleared another account's failures"


def test_email_is_normalised_on_the_way_in_and_out(db: Session) -> None:
    """Otherwise `A@Example.COM` and `a@example.com` get a budget each."""
    now = utcnow()
    for _ in range(throttle.LOGIN_RULES[0].limit):
        throttle.record(
            db, throttle.LOGIN_FAIL, email="A@Example.COM ", ip="10.0.0.1", now=now
        )
    assert not throttle.check(
        db, throttle.LOGIN_RULES, email="a@example.com", ip="10.0.0.1", now=now
    ).allowed


def test_a_rule_with_no_value_to_key_on_counts_nothing(db: Session) -> None:
    """A missing client address must not widen "this IP" to "everyone".

    `_matches` returning an empty clause list would have made the where-clause
    match every row in the table, and the first request from behind a proxy
    that hid the address would have locked out the whole world.
    """
    now = utcnow()
    for _ in range(50):
        throttle.record(db, throttle.LOGIN_FAIL, email="a@example.com", ip=None, now=now)
    assert throttle.check(
        db, throttle.LOGIN_RULES, email="b@example.com", ip=None, now=now
    ).allowed


def test_purge_keeps_the_table_bounded(db: Session) -> None:
    now = utcnow()
    throttle.record(
        db,
        throttle.LOGIN_FAIL,
        email="old@example.com",
        ip="10.0.0.1",
        now=now - throttle.RETENTION - timedelta(minutes=1),
    )
    throttle.record(db, throttle.LOGIN_FAIL, email="new@example.com", ip="10.0.0.1", now=now)
    # The second record() prunes as it writes.
    remaining = db.query(throttle.LoginAttempt).all()
    assert [r.email for r in remaining] == ["new@example.com"]


def test_retry_after_minutes_never_says_zero() -> None:
    assert throttle.Decision(allowed=False, retry_after=1).retry_after_minutes == 1
    assert throttle.Decision(allowed=False, retry_after=61).retry_after_minutes == 2


# --------------------------------------------------------------------------
# Through the real form
# --------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("FISHLOG_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("FISHLOG_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.delenv("FISHLOG_TRUST_PROXY", raising=False)
    monkeypatch.setattr(passwords, "DEFAULT_N", 1 << 12)

    import app.core.db as db_module

    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionLocal", None)

    from app.web import app as app_module

    application = app_module.create_app()
    db_module.init_db()
    yield TestClient(application)


ACCOUNT = {
    "email": "angler@example.com",
    "display_name": "Ann",
    "password": "bream-on-the-margin",
    "password_confirm": "bream-on-the-margin",
}


def test_the_login_form_refuses_with_429_and_a_wait(client: TestClient) -> None:
    client.post("/auth/register", data=ACCOUNT, follow_redirects=False)
    client.post("/auth/logout", follow_redirects=False)

    limit = throttle.LOGIN_RULES[0].limit
    for _ in range(limit):
        response = client.post(
            "/auth/login",
            data={"email": ACCOUNT["email"], "password": "wrong-one-entirely"},
            follow_redirects=False,
        )
        assert response.status_code == 401

    refused = client.post(
        "/auth/login",
        data={"email": ACCOUNT["email"], "password": "wrong-one-entirely"},
        follow_redirects=False,
    )
    assert refused.status_code == 429
    assert "try again in" in refused.text.lower()
    # The minutes are substituted, not left as a literal placeholder.
    assert "{minutes}" not in refused.text


def test_the_limit_is_checked_before_the_password_is_hashed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scrypt work is the expensive half; a refused attempt must skip it.

    Verified by making `verify_password` blow up: if the refusal path touched
    it at all, this test would see a 500 instead of a 429.
    """
    client.post("/auth/register", data=ACCOUNT, follow_redirects=False)
    client.post("/auth/logout", follow_redirects=False)

    for _ in range(throttle.LOGIN_RULES[0].limit):
        client.post(
            "/auth/login",
            data={"email": ACCOUNT["email"], "password": "wrong-one-entirely"},
            follow_redirects=False,
        )

    def explode(*args: object, **kwargs: object) -> bool:
        raise AssertionError("scrypt was spent on an attempt we had already refused")

    monkeypatch.setattr(passwords, "verify_password", explode)

    refused = client.post(
        "/auth/login",
        data={"email": ACCOUNT["email"], "password": "wrong-one-entirely"},
        follow_redirects=False,
    )
    assert refused.status_code == 429


def test_the_right_password_still_works_after_a_few_wrong_ones(
    client: TestClient,
) -> None:
    client.post("/auth/register", data=ACCOUNT, follow_redirects=False)
    client.post("/auth/logout", follow_redirects=False)

    for _ in range(throttle.LOGIN_RULES[0].limit - 1):
        client.post(
            "/auth/login",
            data={"email": ACCOUNT["email"], "password": "not-it"},
            follow_redirects=False,
        )
    ok = client.post(
        "/auth/login",
        data={"email": ACCOUNT["email"], "password": ACCOUNT["password"]},
        follow_redirects=False,
    )
    assert ok.status_code == 303

    # And the counter is empty again: a full budget of wrong guesses is
    # available immediately afterwards.
    client.post("/auth/logout", follow_redirects=False)
    for _ in range(throttle.LOGIN_RULES[0].limit):
        again = client.post(
            "/auth/login",
            data={"email": ACCOUNT["email"], "password": "not-it"},
            follow_redirects=False,
        )
        assert again.status_code == 401


def test_a_forged_forwarded_header_cannot_mint_fresh_addresses(
    client: TestClient,
) -> None:
    """With FISHLOG_TRUST_PROXY unset, X-Forwarded-For is ignored.

    Trusting it by default would hand an attacker a new IP per request and make
    the per-IP rule decorative.
    """
    ip_rule = next(r for r in throttle.LOGIN_RULES if r.name == "ip")
    for i in range(ip_rule.limit):
        client.post(
            "/auth/login",
            data={"email": f"angler{i}@example.com", "password": "not-it"},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
            follow_redirects=False,
        )
    refused = client.post(
        "/auth/login",
        data={"email": "someone@example.com", "password": "not-it"},
        headers={"X-Forwarded-For": "203.0.113.250"},
        follow_redirects=False,
    )
    assert refused.status_code == 429


def test_registration_is_capped_per_address(client: TestClient) -> None:
    limit = throttle.REGISTER_RULES[0].limit
    for i in range(limit):
        made = client.post(
            "/auth/register",
            data={
                "email": f"angler{i}@example.com",
                "display_name": f"Angler {i}",
                "password": "bream-on-the-margin",
                "password_confirm": "bream-on-the-margin",
            },
            follow_redirects=False,
        )
        assert made.status_code == 303

    refused = client.post(
        "/auth/register",
        data={
            "email": "one-too-many@example.com",
            "display_name": "Nope",
            "password": "bream-on-the-margin",
            "password_confirm": "bream-on-the-margin",
        },
        follow_redirects=False,
    )
    assert refused.status_code == 429


def test_a_rejected_registration_does_not_spend_the_quota(client: TestClient) -> None:
    """Typos are not rationed - only accounts that actually got created are."""
    for _ in range(throttle.REGISTER_RULES[0].limit + 3):
        client.post(
            "/auth/register",
            data={
                "email": "not-an-address",
                "display_name": "",
                "password": "short",
                "password_confirm": "nope",
            },
            follow_redirects=False,
        )
    made = client.post("/auth/register", data=ACCOUNT, follow_redirects=False)
    assert made.status_code == 303
