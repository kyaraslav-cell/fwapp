from __future__ import annotations

from collections.abc import Iterator

from fastapi.templating import Jinja2Templates
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
