"""Accounts: hashing, validation, session lifecycle, ownership.

The scrypt cost is deliberately lowered here. The shipped parameters take
around half a second per hash by design, and a suite that hashes twenty
passwords at production cost would take longer than the rest of the tests put
together - so these run at a cost that exercises the same code path and prove
the *format* carries its parameters, which is what makes that safe.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import passwords, service, tokens
from app.auth.google import GoogleAuthError, GoogleIdentity, _identity_from_userinfo
from app.auth.validation import (
    normalise_email,
    validate_email,
    validate_password,
    validate_registration,
)
from app.core.models import AuthSession, Base, FishSession, Lake
from app.core.time import iso, parse_iso, utcnow

CHEAP = passwords.Params(n=1 << 12, r=8, p=1)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture(autouse=True)
def cheap_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same algorithm, lower work factor.

    `Params` reads DEFAULT_N through a default_factory, so patching the module
    constant reaches every call in the app - including the ones inside
    `service.register`, which is the point.
    """
    monkeypatch.setattr(passwords, "DEFAULT_N", CHEAP.n)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_a_password_verifies_against_its_own_hash() -> None:
    stored = passwords.hash_password("pomocnia-margin-2026", CHEAP)
    assert passwords.verify_password("pomocnia-margin-2026", stored)
    assert not passwords.verify_password("pomocnia-margin-2025", stored)


def test_the_same_password_hashes_differently_every_time() -> None:
    """A shared salt would make two anglers with one password visibly equal."""
    first = passwords.hash_password("same-password-twice", CHEAP)
    second = passwords.hash_password("same-password-twice", CHEAP)
    assert first != second
    assert passwords.verify_password("same-password-twice", first)
    assert passwords.verify_password("same-password-twice", second)


def test_a_google_only_account_cannot_be_entered_with_a_blank_password() -> None:
    """password_hash is NULL for Google accounts. NULL is not a password."""
    assert not passwords.verify_password("", None)
    assert not passwords.verify_password("anything", None)


def test_a_corrupt_hash_fails_instead_of_raising() -> None:
    for broken in ("", "scrypt$", "scrypt$a$b$c$d$e", "bcrypt$1$2$3$x$y", "nonsense"):
        assert not passwords.verify_password("whatever", broken)


def test_needs_rehash_only_when_the_stored_cost_is_lower() -> None:
    weak = passwords.hash_password("cost-goes-up", passwords.Params(n=1 << 12))
    strong = passwords.hash_password("cost-goes-up", passwords.Params(n=1 << 14))
    target = passwords.Params(n=1 << 14)
    assert passwords.needs_rehash(weak, target)
    assert not passwords.needs_rehash(strong, target)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_addresses_are_matched_case_insensitively() -> None:
    assert normalise_email("  Angler@Example.COM ") == "angler@example.com"


def test_email_shape_is_checked_but_not_over_checked() -> None:
    assert validate_email("angler+pomocnia@example.co.uk") is None
    assert validate_email("wędkarz@example.pl") is None
    assert validate_email("no-at-sign") == "auth.error.email_invalid"
    assert validate_email("two@@example.com") == "auth.error.email_invalid"
    assert validate_email("") == "auth.error.email_required"


def test_password_rules_are_length_first() -> None:
    assert validate_password("short") == "auth.error.password_too_short"
    assert validate_password("password123") == "auth.error.password_obvious"
    assert validate_password("aaaaaaaaaaaaaa") == "auth.error.password_repetitive"
    assert validate_password("kyaraslav-x9", "kyaraslav@gmail.com") == (
        "auth.error.password_is_email"
    )
    assert validate_password("bream on the margin") is None


def test_the_whole_form_is_validated_at_once() -> None:
    """Three round trips to fix three fields is how an account never gets made."""
    errors = validate_registration("nope", "", "short", "different")
    assert set(errors) == {"email", "name", "password", "confirmation"}


# ---------------------------------------------------------------------------
# Registration and sign-in
# ---------------------------------------------------------------------------


def test_register_then_authenticate(db: Session) -> None:
    user = service.register(
        db, email="Angler@Example.com", display_name="  Ann  ", password="reeds-and-rain"
    )
    assert user.email == "angler@example.com"
    assert user.display_name == "Ann"

    assert service.authenticate(db, email="ANGLER@example.com", password="reeds-and-rain")
    assert service.authenticate(db, email="angler@example.com", password="wrong") is None
    assert service.authenticate(db, email="nobody@example.com", password="x") is None


def test_an_address_cannot_be_registered_twice(db: Session) -> None:
    service.register(db, email="a@example.com", display_name="A", password="first-password")
    with pytest.raises(service.EmailAlreadyRegisteredError):
        service.register(db, email="A@Example.com", display_name="B", password="second-password")


def test_a_disabled_account_is_refused_even_with_the_right_password(db: Session) -> None:
    user = service.register(db, email="a@example.com", display_name="A", password="right-password")
    user.is_disabled = 1
    with pytest.raises(service.AccountDisabledError):
        service.authenticate(db, email="a@example.com", password="right-password")


def test_the_first_account_inherits_sessions_logged_before_accounts_existed(
    db: Session,
) -> None:
    """Otherwise the owner's whole season silently vanishes from history."""
    lake = Lake(
        slug="pomocnia", name="Pomocnia", centroid_lat=52.0, centroid_lon=21.0,
        timezone="Europe/Warsaw", created_at=iso(utcnow()),
    )
    db.add(lake)
    db.flush()
    for _ in range(3):
        db.add(FishSession(lake_id=lake.id, started_at=iso(utcnow()), created_at=iso(utcnow())))
    db.flush()

    first = service.register(
        db, email="owner@example.com", display_name="Owner", password="the-first-one"
    )
    assert all(s.user_id == first.id for s in db.query(FishSession).all())

    second = service.register(
        db, email="guest@example.com", display_name="Guest", password="the-second-one"
    )
    assert service.claim_unowned_sessions(db, second) == 0


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def test_the_cookie_token_is_never_stored(db: Session) -> None:
    """A leaked database backup must not be a set of working sessions."""
    user = service.register(db, email="a@example.com", display_name="A", password="cookie-check-pw")
    signed_in = service.start_auth_session(db, user)
    rows = db.query(AuthSession).all()
    assert len(rows) == 1
    assert signed_in.token not in rows[0].token_hash
    assert rows[0].token_hash == tokens.token_hash(signed_in.token)


def test_a_live_token_resolves_and_a_junk_one_does_not(db: Session) -> None:
    user = service.register(db, email="a@example.com", display_name="A", password="resolve-me-now")
    signed_in = service.start_auth_session(db, user)
    assert service.resolve_session(db, signed_in.token) is not None
    assert service.resolve_session(db, "not-a-real-token") is None
    assert service.resolve_session(db, None) is None


def test_an_untouched_session_expires(db: Session) -> None:
    """A phone left in a drawer for a month is signed out when it comes back.

    Nothing resolves the token in between on purpose - one look inside the
    refresh window would push the expiry out, which is the *next* test.
    """
    now = utcnow()
    user = service.register(db, email="a@example.com", display_name="A", password="expiry-check-x")
    signed_in = service.start_auth_session(db, user, now=now)
    expired = now + timedelta(days=tokens.SESSION_DAYS + 1)
    assert service.resolve_session(db, signed_in.token, now=expired) is None


def test_a_session_in_regular_use_slides_forward(db: Session) -> None:
    now = utcnow()
    user = service.register(db, email="a@example.com", display_name="A", password="sliding-window")
    signed_in = service.start_auth_session(db, user, now=now)
    original = signed_in.expires_at

    # Seen inside the refresh window: pushed back out to a full term.
    late = now + timedelta(days=tokens.SESSION_DAYS - 1)
    assert service.resolve_session(db, signed_in.token, now=late) is not None
    row = db.query(AuthSession).one()
    assert parse_iso(row.expires_at) > original


def test_signing_out_revokes_only_that_browser(db: Session) -> None:
    user = service.register(db, email="a@example.com", display_name="A", password="two-browsers-x")
    phone = service.start_auth_session(db, user)
    laptop = service.start_auth_session(db, user)

    service.sign_out(db, phone.token)
    assert service.resolve_session(db, phone.token) is None
    assert service.resolve_session(db, laptop.token) is not None

    assert service.sign_out_everywhere(db, user) == 1
    assert service.resolve_session(db, laptop.token) is None


def test_signing_out_twice_is_not_an_error(db: Session) -> None:
    user = service.register(db, email="a@example.com", display_name="A", password="idempotent-out")
    signed_in = service.start_auth_session(db, user)
    service.sign_out(db, signed_in.token)
    service.sign_out(db, signed_in.token)
    service.sign_out(db, None)


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


def test_google_identity_needs_a_subject_and_an_email() -> None:
    with pytest.raises(GoogleAuthError):
        _identity_from_userinfo({"email": "a@example.com"})
    with pytest.raises(GoogleAuthError):
        _identity_from_userinfo({"sub": "1234"})
    identity = _identity_from_userinfo(
        {"sub": "1234", "email": "A@Example.com", "name": "Ann", "email_verified": True}
    )
    assert identity.sub == "1234"
    assert identity.email == "a@example.com"


def test_google_matches_on_subject_not_on_address(db: Session) -> None:
    """Addresses get recycled and changed; the subject does not."""
    first = service.upsert_google_user(
        db, GoogleIdentity(sub="sub-1", email="old@example.com", name="Ann", email_verified=True)
    )
    again = service.upsert_google_user(
        db, GoogleIdentity(sub="sub-1", email="new@example.com", name="Ann", email_verified=True)
    )
    assert again.id == first.id


def test_google_links_to_an_existing_password_account(db: Session) -> None:
    """One angler, one notebook - pressing the Google button must not fork it."""
    user = service.register(
        db, email="angler@example.com", display_name="Ann", password="password-account"
    )
    linked = service.upsert_google_user(
        db,
        GoogleIdentity(sub="sub-9", email="angler@example.com", name="Ann", email_verified=True),
    )
    assert linked.id == user.id
    assert linked.google_sub == "sub-9"
    # And the password still works: linking adds a way in, it does not replace one.
    assert service.authenticate(db, email="angler@example.com", password="password-account")
