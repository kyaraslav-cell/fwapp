"""Read and write the daily hi-res grid cache (`docs/09-BACKLOG.md §19c`).

Its own module rather than living in `app/jobs/handlers.py` or a route file:
the daily `grid_hires` job writes it, `/lake/{slug}/grid` reads it, and
neither package should have to import the other just to agree on one row
shape.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import HiresGridCache
from app.core.time import iso, utcnow


def store(
    db: Session,
    lake_id: int,
    for_date: str,
    cell_m: float,
    wind_dir: float,
    phase: str,
    model: str,
    payload: dict[str, Any],
) -> None:
    """Replace the row for this lake+date. Idempotent, per the handler contract."""
    row = db.execute(
        select(HiresGridCache).where(
            HiresGridCache.lake_id == lake_id, HiresGridCache.for_date == for_date
        )
    ).scalar_one_or_none()
    if row is None:
        row = HiresGridCache(lake_id=lake_id, for_date=for_date)
        db.add(row)
    row.cell_m = cell_m
    row.wind_dir = wind_dir
    row.phase = phase
    row.model = model
    row.payload_json = json.dumps(payload)
    row.generated_at = iso(utcnow())
    db.flush()


def fetch(db: Session, lake_id: int, for_date: str) -> dict[str, Any] | None:
    """The cached `/grid` response body for this lake+date, or None."""
    row = db.execute(
        select(HiresGridCache).where(
            HiresGridCache.lake_id == lake_id, HiresGridCache.for_date == for_date
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    payload: dict[str, Any] = json.loads(row.payload_json)
    return payload
