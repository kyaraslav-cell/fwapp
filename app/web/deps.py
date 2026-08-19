from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import google
from app.auth.service import resolve_session
from app.auth.tokens import COOKIE_NAME as AUTH_COOKIE
from app.core.db import get_sessionmaker
from app.core.i18n import COOKIE_NAME, language_names, normalise, translate
from app.core.models import Lake, User
from app.core.seed import ensure_lake_seeded
from app.core.time import parse_iso, to_display


@dataclass(frozen=True)
class CurrentUser:
    """What the templates are allowed to know about who is signed in.

    A plain frozen value rather than the ORM row: the row belongs to a session
    that is closed by the time Jinja renders, and touching a lazy attribute
    then raises a DetachedInstanceError in the middle of a page.
    """

    id: int
    display_name: str
    email: str


def _i18n_context(request: Request) -> dict[str, object]:
    """Per-request, so `t()` is never shared mutable state between requests."""
    lang = normalise(request.cookies.get(COOKIE_NAME))
    return {
        "lang": lang,
        "languages": language_names(),
        "t": lambda key: translate(lang, key),
        "current_path": request.url.path,
        # Set by the middleware in app.py; absent on any request that bypassed
        # it, which must read as "signed out" rather than blow up.
        "current_user": getattr(request.state, "user", None),
        "google_enabled": google.is_configured(),
    }


templates = Jinja2Templates(
    directory="app/web/templates", context_processors=[_i18n_context]
)


def _local_time(iso_ts: str | None) -> str:
    """UTC ISO string -> HH:MM in Europe/Warsaw.

    Everything is stored UTC and displayed in the lake's timezone
    (CLAUDE.md style rules). Templates were slicing the raw ISO string, which
    showed UTC and read as an hour or two wrong all summer.
    """
    if not iso_ts:
        return "—"
    return to_display(parse_iso(iso_ts)).strftime("%H:%M")


def _local_datetime(iso_ts: str | None) -> str:
    if not iso_ts:
        return "—"
    return to_display(parse_iso(iso_ts)).strftime("%a %d %b, %H:%M")


templates.env.filters["localtime"] = _local_time
templates.env.filters["localdatetime"] = _local_datetime


def get_db() -> Iterator[Session]:
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class NotSignedInError(Exception):
    """Raised by `require_user`. The handler in app.py turns it into a redirect.

    An exception rather than a returned response because it has to work from
    inside a dependency, where there is nothing to return to.
    """

    def __init__(self, next_path: str) -> None:
        super().__init__(next_path)
        self.next_path = next_path


def current_user(request: Request) -> CurrentUser | None:
    """Who is signed in, or None. Never raises - use it for optional display."""
    user: CurrentUser | None = getattr(request.state, "user", None)
    return user


def require_user(request: Request) -> CurrentUser:
    """Dependency for everything that reads or writes one angler's notebook."""
    user = current_user(request)
    if user is None:
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        raise NotSignedInError(target)
    return user


def resolve_request_user(db: Session, request: Request) -> CurrentUser | None:
    """Cookie -> CurrentUser. The one place the auth cookie is read."""
    row: User | None = resolve_session(db, request.cookies.get(AUTH_COOKIE))
    if row is None:
        return None
    return CurrentUser(id=row.id, display_name=row.display_name, email=row.email)


def get_lake(db: Session) -> Lake:
    return ensure_lake_seeded(db)


def get_lake_by_slug(db: Session, slug: str) -> Lake:
    ensure_lake_seeded(db)
    lake = db.execute(select(Lake).where(Lake.slug == slug)).scalar_one_or_none()
    if lake is None:
        raise HTTPException(status_code=404, detail=f"no lake with slug '{slug}'")
    return lake
