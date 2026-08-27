from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

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
        "t": lambda key, **params: translate(lang, key, **params),
        "current_path": request.url.path,
        # Set by the middleware in app.py; absent on any request that bypassed
        # it, which must read as "signed out" rather than blow up.
        "current_user": getattr(request.state, "user", None),
        "google_enabled": google.is_configured(),
    }


def _running_session_context(request: Request) -> dict[str, Any]:
    """The angler's open session, for the pill in the header.

    A context processor rather than a line in every route: the pill has to be
    on *every* page - that is the whole point of it - and adding it route by
    route guarantees one gets missed.

    It fails quiet. This runs on every render including the error pages, and a
    banner that raises while rendering a 500 turns one broken page into two.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        return {"running_session": None, "running_session_lake": None}
    try:
        from app.core.db import session_scope
        from app.core.models import Lake
        from app.notebook.sessions import active_session_for_user

        with session_scope() as db:
            session = active_session_for_user(db, user.id)
            if session is None:
                return {"running_session": None, "running_session_lake": None}
            lake = db.get(Lake, session.lake_id)
            return {
                "running_session": {
                    "started_at": session.started_at,
                    "method": session.method,
                },
                "running_session_lake": lake.name if lake is not None else None,
            }
    except Exception:  # noqa: BLE001 - see the docstring
        return {"running_session": None, "running_session_lake": None}


templates = Jinja2Templates(
    directory="app/web/templates",
    context_processors=[_i18n_context, _running_session_context],
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


def client_ip(request: Request) -> str | None:
    """The address to rate-limit on, and the one decision that makes it safe.

    `X-Forwarded-For` is a request header: anyone can write it. Trusting it by
    default would let one machine present a fresh address on every attempt and
    walk straight through the per-IP limit, and would let it forge somebody
    else's address into the counter. So it is read **only** when
    `FISHLOG_TRUST_PROXY=1` says this app is genuinely behind a proxy that sets
    it (Caddy, or Tailscale funnel per `docs/10 §9`); otherwise the socket peer
    is the truth.

    Get this wrong in the other direction and every request appears to come
    from the proxy - one address for the whole internet - so the per-IP limit
    locks out everybody at once. Hence: opt in, deliberately, per deployment.
    """
    if os.environ.get("FISHLOG_TRUST_PROXY", "").strip() == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else None


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
