"""Turning a chosen search result into a water, and queueing the slow work.

The request does two things only: write the row, queue the jobs. Everything
that can be slow - Overpass, the archive, the grid - happens afterwards, so the
angler gets a map with a satellite view and a pin within a second of choosing.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Lake
from app.core.time import iso, parse_iso, utcnow
from app.discover.nominatim import Candidate
from app.jobs import queue
from app.jobs.handlers import NEW_WATER_PIPELINE

# Adding a water costs an Overpass call, a year of archive and (later) a
# research pass. A quota keeps one enthusiastic afternoon from spending the
# free tiers everyone shares.
DAILY_ADD_QUOTA = 5

# Two waters within this distance with the same name are the same water. Broad
# on purpose: Nominatim's point for a lake can sit anywhere inside it, and a
# duplicate row is worse than a near-miss - it splits the notebook.
SAME_WATER_M = 600.0


class QuotaExceededError(RuntimeError):
    """This account has added its allowance of waters today."""


class NotAWaterError(RuntimeError):
    """The chosen result is a village, a street or a bus stop."""


@dataclass(frozen=True)
class AddResult:
    lake: Lake
    created: bool


def slugify(name: str) -> str:
    """A URL-safe slug, with Polish letters folded rather than dropped.

    `Jezioro Zegrzyńskie` -> `jezioro-zegrzynskie`. Without the fold, NFKD
    leaves the diacritic as a separate codepoint and the slug loses the letter
    entirely: `zegrzy-skie`.
    """
    folded = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "water"


def unique_slug(db: Session, base: str) -> str:
    """`jezioro-biale`, then `jezioro-biale-2`. There are many of each in Poland."""
    slug = base
    suffix = 2
    while db.execute(select(Lake).where(Lake.slug == slug)).scalar_one_or_none() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _metres_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Flat-earth distance. Over a few hundred metres the error is centimetres."""
    mid = math.radians((lat1 + lat2) / 2.0)
    dy = (lat1 - lat2) * 111_320.0
    dx = (lon1 - lon2) * 111_320.0 * math.cos(mid)
    return math.hypot(dx, dy)


def find_existing(db: Session, candidate: Candidate) -> Lake | None:
    """The water this result already is, if it is already in the database.

    Matched on the OSM id first - that is an identity, not a guess - then on
    name and proximity, because the same lake can be reached through a
    different OSM object.
    """
    if candidate.osm_id:
        by_osm = db.execute(
            select(Lake).where(
                Lake.osm_type == candidate.osm_type, Lake.osm_id == candidate.osm_id
            )
        ).scalar_one_or_none()
        if by_osm is not None:
            return by_osm

    wanted = candidate.name.strip().lower()
    for lake in db.execute(select(Lake)).scalars().all():
        if lake.name.strip().lower() != wanted:
            continue
        if _metres_between(
            lake.centroid_lat, lake.centroid_lon, candidate.lat, candidate.lon
        ) <= SAME_WATER_M:
            return lake
    return None


def adds_today(db: Session, user_id: int, now: datetime | None = None) -> int:
    now = now or utcnow()
    since = iso(now - timedelta(days=1))
    return int(
        db.execute(
            select(func.count())
            .select_from(Lake)
            .where(Lake.added_by_user_id == user_id, Lake.created_at >= since)
        ).scalar_one()
    )


def quota_left(db: Session, user_id: int, now: datetime | None = None) -> int:
    return max(0, DAILY_ADD_QUOTA - adds_today(db, user_id, now))


def add_water(
    db: Session,
    candidate: Candidate,
    *,
    user_id: int,
    now: datetime | None = None,
) -> AddResult:
    """Create the water if it is new, and queue everything that comes after.

    Returns the existing water untouched when it is already known: a second
    angler searching for the same lake must land on the same page, not create a
    parallel copy that splits every statistic about it.
    """
    now = now or utcnow()

    existing = find_existing(db, candidate)
    if existing is not None:
        return AddResult(lake=existing, created=False)

    if not candidate.is_water:
        raise NotAWaterError(candidate.display_name)

    if quota_left(db, user_id, now) <= 0:
        raise QuotaExceededError(f"{DAILY_ADD_QUOTA} waters a day")

    lake = Lake(
        slug=unique_slug(db, slugify(candidate.name)),
        name=candidate.name,
        centroid_lat=candidate.lat,
        centroid_lon=candidate.lon,
        # From the search result's bounding box, and deliberately provisional:
        # the real area replaces it the moment there is a polygon.
        area_ha=candidate.area_ha,
        timezone="Europe/Warsaw",
        origin="discovered",
        osm_type=candidate.osm_type or None,
        osm_id=candidate.osm_id or None,
        added_by_user_id=user_id,
        created_at=iso(now),
    )
    db.add(lake)
    db.flush()

    for kind in NEW_WATER_PIPELINE:
        queue.enqueue(db, kind, lake_id=lake.id, now=now)

    return AddResult(lake=lake, created=True)


def next_quota_reset(db: Session, user_id: int, now: datetime | None = None) -> datetime | None:
    """When the oldest add in the window falls out of it, or None if under quota."""
    now = now or utcnow()
    if quota_left(db, user_id, now) > 0:
        return None
    since = iso(now - timedelta(days=1))
    oldest = db.execute(
        select(Lake.created_at)
        .where(Lake.added_by_user_id == user_id, Lake.created_at >= since)
        .order_by(Lake.created_at)
        .limit(1)
    ).scalar_one_or_none()
    return parse_iso(oldest) + timedelta(days=1) if oldest else None
