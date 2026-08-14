from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.models import Lake
from app.core.seed import ensure_lake_seeded

templates = Jinja2Templates(directory="app/web/templates")


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
