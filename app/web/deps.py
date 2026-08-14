from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.i18n import COOKIE_NAME, language_names, normalise, translate
from app.core.models import Lake
from app.core.seed import ensure_lake_seeded
from app.core.time import parse_iso, to_display


def _i18n_context(request: Request) -> dict[str, object]:
    """Per-request, so `t()` is never shared mutable state between requests."""
    lang = normalise(request.cookies.get(COOKIE_NAME))
    return {
        "lang": lang,
        "languages": language_names(),
        "t": lambda key: translate(lang, key),
        "current_path": request.url.path,
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


def get_lake(db: Session) -> Lake:
    return ensure_lake_seeded(db)


def get_lake_by_slug(db: Session, slug: str) -> Lake:
    ensure_lake_seeded(db)
    lake = db.execute(select(Lake).where(Lake.slug == slug)).scalar_one_or_none()
    if lake is None:
        raise HTTPException(status_code=404, detail=f"no lake with slug '{slug}'")
    return lake
