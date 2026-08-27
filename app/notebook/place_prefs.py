"""Which waters an angler keeps pinned, and which they have put away.

Both are **per angler and never global**. Two people share this database:
a water one of them removes is very often a water the other is still fishing,
and a favourite is by definition personal.

Removal is a soft delete. The water, its predictions and everybody's sessions
on it survive untouched - law 2 makes predictions immutable evidence and law 3
makes sessions the only measurement the project has. All that changes is
whether this angler's places list shows it, and they can put it back.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AnglerLake
from app.core.time import iso, utcnow


@dataclass(frozen=True)
class Preference:
    """What one angler has said about one water."""

    is_favourite: bool
    is_removed: bool


NEUTRAL = Preference(is_favourite=False, is_removed=False)


def _row(db: Session, user_id: int, lake_id: int) -> AnglerLake | None:
    return db.execute(
        select(AnglerLake).where(
            AnglerLake.user_id == user_id, AnglerLake.lake_id == lake_id
        )
    ).scalar_one_or_none()


def _ensure(db: Session, user_id: int, lake_id: int) -> AnglerLake:
    row = _row(db, user_id, lake_id)
    if row is None:
        row = AnglerLake(
            user_id=user_id,
            lake_id=lake_id,
            is_favourite=0,
            removed_at=None,
            created_at=iso(utcnow()),
        )
        db.add(row)
        db.flush()
    return row


def preferences(db: Session, user_id: int | None) -> dict[int, Preference]:
    """Every stated preference for this angler, keyed by lake id.

    A signed-out visitor has none - the published read-only build has no
    account, and it must show every water rather than nothing.
    """
    if user_id is None:
        return {}
    rows = db.execute(select(AnglerLake).where(AnglerLake.user_id == user_id)).scalars().all()
    return {
        row.lake_id: Preference(
            is_favourite=bool(row.is_favourite), is_removed=row.removed_at is not None
        )
        for row in rows
    }


def set_favourite(db: Session, user_id: int, lake_id: int, *, on: bool) -> Preference:
    row = _ensure(db, user_id, lake_id)
    row.is_favourite = 1 if on else 0
    db.flush()
    return Preference(is_favourite=on, is_removed=row.removed_at is not None)


def toggle_favourite(db: Session, user_id: int, lake_id: int) -> Preference:
    current = _row(db, user_id, lake_id)
    on = not (current is not None and current.is_favourite)
    return set_favourite(db, user_id, lake_id, on=on)


def remove(db: Session, user_id: int, lake_id: int) -> Preference:
    """Put this water away for this angler. Nothing is deleted."""
    row = _ensure(db, user_id, lake_id)
    row.removed_at = iso(utcnow())
    db.flush()
    return Preference(is_favourite=bool(row.is_favourite), is_removed=True)


def restore(db: Session, user_id: int, lake_id: int) -> Preference:
    row = _ensure(db, user_id, lake_id)
    row.removed_at = None
    db.flush()
    return Preference(is_favourite=bool(row.is_favourite), is_removed=False)


def sort_key(preference: Preference, name: str) -> tuple[int, str]:
    """Favourites first, then alphabetical.

    Returned as a key rather than applied here so the caller keeps one sort
    over whatever it has already assembled.
    """
    return (0 if preference.is_favourite else 1, name.lower())
