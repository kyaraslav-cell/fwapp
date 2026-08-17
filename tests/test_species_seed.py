"""Species reference data must survive a schema that grew after seeding.

The bug this pins: `shape` and `color` were added to the model long after the
species table was first seeded. `add_missing_columns` adds them as NULL, and
the old seed returned early whenever any species row existed, so it never
backfilled. Every icon then fell through `fish_icon(shape or 'roach')` and the
app rendered the same roach for every species - which is exactly what the owner
kept reporting while two rounds of icon redraws changed symbols nothing was
using.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Species
from app.notebook.species import ensure_species_seeded


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_seeding_populates_a_shape_for_every_species(db: Session) -> None:
    ensure_species_seeded(db)
    rows = db.execute(select(Species)).scalars().all()
    assert rows, "no species seeded"
    missing = [s.slug for s in rows if not s.shape]
    assert not missing, f"species with no icon shape: {missing}"


def test_seeding_backfills_columns_added_after_the_first_seed(db: Session) -> None:
    ensure_species_seeded(db)
    # Simulate a database seeded before `shape`/`color` existed.
    for row in db.execute(select(Species)).scalars().all():
        row.shape = None
        row.color = None
        row.typical_g = None
    db.flush()

    ensure_species_seeded(db)

    rows = db.execute(select(Species)).scalars().all()
    assert all(s.shape for s in rows), "shape was not backfilled"
    assert all(s.color for s in rows), "color was not backfilled"
    assert any(s.typical_g for s in rows), "sizes were not backfilled"


def test_reseeding_does_not_duplicate_rows(db: Session) -> None:
    ensure_species_seeded(db)
    first = len(db.execute(select(Species)).scalars().all())
    ensure_species_seeded(db)
    ensure_species_seeded(db)
    assert len(db.execute(select(Species)).scalars().all()) == first


def test_the_primary_species_do_not_share_one_silhouette(db: Session) -> None:
    """The owner's complaint, as an assertion.

    Roach, bream, rudd, ide, carp and crucian are the six buttons on the
    quick-log grid. If any two of them resolve to the same icon shape the grid
    reads as one fish repeated, whatever the drawings look like.
    """
    ensure_species_seeded(db)
    primary = ["roach", "bream", "rudd", "ide", "carp", "crucian"]
    shapes = [
        db.execute(select(Species).where(Species.slug == slug)).scalar_one().shape
        for slug in primary
    ]
    assert len(set(shapes)) == len(primary), f"quick-log species share a shape: {shapes}"
