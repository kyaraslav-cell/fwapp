"""Accounts and sign-in against the database.

The clock is always passed in (`now`), so every expiry rule here is testable
without waiting and without monkeypatching time - the same discipline
`app/rules/` and `app/features/` follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import passwords, tokens
from app.auth.google import GoogleIdentity
from app.auth.validation import normalise_email, normalise_name
from app.core.models import AuthSession, FishSession, User
from app.core.time import iso, parse_iso, utcnow


class EmailAlreadyRegisteredError(RuntimeError):
    """Someone already has that address."""


class AccountDisabledError(RuntimeError):
    """The account exists and is switched off."""


@dataclass(frozen=True)
class SignIn:
    """A successful sign-in: the user, and the raw token to put in the cookie.

    The raw token exists only here and in the cookie. What is stored is its
    hash, so this object must never be logged.
    """

    user: User
    token: str
    expires_at: datetime


def user_count(db: Session) -> int:
    return int(db.execute(select(func.count()).select_from(User)).scalar_one())


def get_by_email(db: Session, email: str) -> User | None:
    return db.execute(
        select(User).where(User.email == normalise_email(email))
    ).scalar_one_or_none()


def get_by_google_sub(db: Session, sub: str) -> User | None:
    return db.execute(select(User).where(User.google_sub == sub)).scalar_one_or_none()


def claim_unowned_sessions(db: Session, user: User) -> int:
    """Give every ownerless fishing session to the first account created.

    Sessions logged before accounts existed have `user_id IS NULL`. Once the
    notebook is scoped per angler they would simply disappear from history,
    which for the owner's own season would look exactly like data loss. The
    first account to exist is the owner's, so it inherits them. Later accounts
    claim nothing.
    """
    if user_count(db) > 1:
        return 0
    result = db.execute(
        update(FishSession).where(FishSession.user_id.is_(None)).values(user_id=user.id)
    )
    return int(result.rowcount or 0)


def register(
    db: Session,
    *,
    email: str,
    display_name: str,
    password: str,
    now: datetime | None = None,
) -> User:
    """Create a password account. Validation has already run in the route."""
    now = now or utcnow()
    address = normalise_email(email)
    if get_by_email(db, address) is not None:
        raise EmailAlreadyRegisteredError(address)
    user = User(
        email=address,
        display_name=normalise_name(display_name) or address.split("@")[0],
        password_hash=passwords.hash_password(password),
        created_at=iso(now),
    )
    db.add(user)
    db.flush()
    claim_unowned_sessions(db, user)
    return user


def authenticate(
    db: Session, *, email: str, password: str, now: datetime | None = None
) -> User | None:
    """Return the user, or None. The caller must not say which half failed.

    "No such account" and "wrong password" are the same answer to the angler
    and two different answers to someone enumerating addresses.
    """
    now = now or utcnow()
    user = get_by_email(db, email)
    if user is None:
        # Spend the time anyway. Returning instantly for an unknown address
        # tells a prober which addresses exist, which is the whole point of
        # giving both cases the same message.
        passwords.verify_password(password, passwords.hash_password("timing-equaliser"))
        return None
    if not passwords.verify_password(password, user.password_hash):
        return None
    if user.is_disabled:
        raise AccountDisabledError(user.email)
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    user.last_login_at = iso(now)
    return user


def upsert_google_user(
    db: Session, identity: GoogleIdentity, now: datetime | None = None
) -> User:
    """Find or create the account behind a Google identity.

    Matching is by subject first. An account that already exists under the same
    address and has no Google link gets linked - that is the angler who
    registered with a password and later pressed the Google button, and making
    them a second account would split their notebook in two.
    """
    now = now or utcnow()
    user = get_by_google_sub(db, identity.sub)
    if user is None:
        user = get_by_email(db, identity.email)
        if user is not None:
            user.google_sub = identity.sub
    if user is None:
        user = User(
            email=normalise_email(identity.email),
            display_name=normalise_name(identity.name) or identity.email.split("@")[0],
            password_hash=None,
            google_sub=identity.sub,
            created_at=iso(now),
        )
        db.add(user)
        db.flush()
        claim_unowned_sessions(db, user)
    if user.is_disabled:
        raise AccountDisabledError(user.email)
    user.last_login_at = iso(now)
    return user


def start_auth_session(
    db: Session,
    user: User,
    *,
    now: datetime | None = None,
    user_agent: str | None = None,
) -> SignIn:
    now = now or utcnow()
    token = tokens.new_token()
    expires_at = now + timedelta(days=tokens.SESSION_DAYS)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=tokens.token_hash(token),
            created_at=iso(now),
            expires_at=iso(expires_at),
            last_seen_at=iso(now),
            user_agent=(user_agent or "")[:200] or None,
        )
    )
    db.flush()
    return SignIn(user=user, token=token, expires_at=expires_at)


def resolve_session(
    db: Session, token: str | None, now: datetime | None = None
) -> User | None:
    """Cookie -> user, refreshing the expiry when it is running down.

    Returns None for anything not currently valid: unknown, revoked, expired,
    or belonging to a disabled account. The row is left in place for expired
    sessions so that `sign_out_everywhere` and any later audit still see it.
    """
    if not token:
        return None
    now = now or utcnow()
    row = db.execute(
        select(AuthSession).where(AuthSession.token_hash == tokens.token_hash(token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    if parse_iso(row.expires_at) <= now:
        return None

    user = db.get(User, row.user_id)
    if user is None or user.is_disabled:
        return None

    row.last_seen_at = iso(now)
    if parse_iso(row.expires_at) - now < timedelta(days=tokens.REFRESH_WITHIN_DAYS):
        row.expires_at = iso(now + timedelta(days=tokens.SESSION_DAYS))
    return user


def sign_out(db: Session, token: str | None, now: datetime | None = None) -> None:
    """Revoke one browser. Idempotent - signing out twice is not an error."""
    if not token:
        return
    now = now or utcnow()
    row = db.execute(
        select(AuthSession).where(AuthSession.token_hash == tokens.token_hash(token))
    ).scalar_one_or_none()
    if row is not None and row.revoked_at is None:
        row.revoked_at = iso(now)


def sign_out_everywhere(db: Session, user: User, now: datetime | None = None) -> int:
    """Revoke every live session for one account - the lost-phone button."""
    now = now or utcnow()
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=iso(now))
    )
    return int(result.rowcount or 0)
