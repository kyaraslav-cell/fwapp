"""Favourites and removals, and the fact that they belong to one angler.

Two people share this database. A water one of them puts away is very often a
water the other is still fishing, and a global delete would take somebody
else's water - along with the predictions law 2 makes immutable evidence and
the sessions law 3 makes the only measurement there is.

So removal is soft and personal: the water survives, everybody's sessions
survive, and only this angler's list changes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import AnglerLake, Base, Lake
from app.core.time import iso, utcnow
from app.notebook import place_prefs


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def lake(db: Session) -> Lake:
    row = Lake(
        slug="pomocnia",
        name="Jezioro Pomocnia",
        centroid_lat=52.5431,
        centroid_lon=20.6762,
        timezone="Europe/Warsaw",
        created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def test_a_water_starts_neutral(db: Session, lake: Lake) -> None:
    assert place_prefs.preferences(db, 1) == {}


def test_favouriting_and_unfavouriting(db: Session, lake: Lake) -> None:
    assert place_prefs.toggle_favourite(db, 1, lake.id).is_favourite
    assert place_prefs.preferences(db, 1)[lake.id].is_favourite

    assert not place_prefs.toggle_favourite(db, 1, lake.id).is_favourite
    assert not place_prefs.preferences(db, 1)[lake.id].is_favourite


def test_removal_is_soft_and_the_water_survives(db: Session, lake: Lake) -> None:
    """The point of the whole design."""
    place_prefs.remove(db, 1, lake.id)

    assert place_prefs.preferences(db, 1)[lake.id].is_removed
    still_there = db.execute(select(Lake).where(Lake.id == lake.id)).scalar_one_or_none()
    assert still_there is not None, "removing a water must never delete it"


def test_a_removed_water_can_be_put_back(db: Session, lake: Lake) -> None:
    place_prefs.remove(db, 1, lake.id)
    place_prefs.restore(db, 1, lake.id)

    assert not place_prefs.preferences(db, 1)[lake.id].is_removed


def test_one_anglers_removal_does_not_touch_another(db: Session, lake: Lake) -> None:
    """Anhelina's waters are not the owner's to remove (standing rule 18)."""
    place_prefs.remove(db, 1, lake.id)

    assert place_prefs.preferences(db, 2) == {}
    assert not place_prefs.preferences(db, 2).get(lake.id, place_prefs.NEUTRAL).is_removed


def test_favourites_are_per_angler(db: Session, lake: Lake) -> None:
    place_prefs.set_favourite(db, 1, lake.id, on=True)

    assert place_prefs.preferences(db, 1)[lake.id].is_favourite
    assert lake.id not in place_prefs.preferences(db, 2)


def test_a_signed_out_visitor_has_no_preferences(db: Session, lake: Lake) -> None:
    """The published read-only build has no account and must show every water."""
    place_prefs.remove(db, 1, lake.id)

    assert place_prefs.preferences(db, None) == {}


def test_removing_keeps_the_favourite_flag(db: Session, lake: Lake) -> None:
    """Put away and brought back should not silently forget it was pinned."""
    place_prefs.set_favourite(db, 1, lake.id, on=True)
    place_prefs.remove(db, 1, lake.id)
    restored = place_prefs.restore(db, 1, lake.id)

    assert restored.is_favourite


def test_one_row_per_angler_and_water(db: Session, lake: Lake) -> None:
    """Toggling repeatedly must not accumulate rows."""
    for _ in range(4):
        place_prefs.toggle_favourite(db, 1, lake.id)
        place_prefs.remove(db, 1, lake.id)
        place_prefs.restore(db, 1, lake.id)

    rows = db.execute(select(AnglerLake).where(AnglerLake.user_id == 1)).scalars().all()
    assert len(rows) == 1


def test_favourites_sort_before_everything_else() -> None:
    pinned = place_prefs.Preference(is_favourite=True, is_removed=False)
    plain = place_prefs.Preference(is_favourite=False, is_removed=False)

    order = sorted(
        [(plain, "Aaa"), (pinned, "Zzz"), (plain, "Bbb")],
        key=lambda pair: place_prefs.sort_key(pair[0], pair[1]),
    )

    assert [name for _, name in order] == ["Zzz", "Aaa", "Bbb"]
