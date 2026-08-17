from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import CONFIG_DIR, load_yaml
from app.core.models import Species

# Every `species` column that is reference data owned by config/species.yaml
# rather than by the angler. Nothing in the UI writes any of these, so the YAML
# is authoritative and can be re-applied on every start.
_REFERENCE_FIELDS = (
    "name_en", "name_pl", "scientific", "family", "scoring",
    "shape", "color",
    "typical_g", "min_g", "max_g", "typical_cm", "min_cm", "max_cm",
)


def _reference_values(entry: dict[str, object]) -> dict[str, object | None]:
    values: dict[str, object | None] = {f: entry.get(f) for f in _REFERENCE_FIELDS}
    values["is_favourite"] = 1 if entry.get("favourite") else 0
    return values


def ensure_species_seeded(db: Session) -> None:
    """Insert missing species and re-sync reference columns from the YAML.

    This used to return early whenever *any* species row existed, which quietly
    broke every database created before a column was added: `shape` and `color`
    arrived in a later commit, `add_missing_columns` added them as NULL, and the
    seed then refused to backfill. Every icon fell through
    `fish_icon(shape or 'roach')` and the whole app rendered six identical
    roach - through two rounds of "redrawn" icons that were never being
    rendered at all.

    Species rows are reference data, not user data. Re-applying the YAML is
    therefore safe and idempotent, and it means adding a column to
    `config/species.yaml` is enough to populate it everywhere.
    """
    cfg = load_yaml(CONFIG_DIR / "species.yaml")
    existing = {s.slug: s for s in db.execute(select(Species)).scalars().all()}

    for entry in cfg["species"]:
        values = _reference_values(entry)
        row = existing.get(entry["slug"])
        if row is None:
            db.add(Species(slug=entry["slug"], **values))
            continue
        for field, value in values.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
    db.flush()


def list_species(db: Session, query: str = "") -> list[Species]:
    stmt = select(Species)
    rows = db.execute(stmt).scalars().all()
    q = query.strip().lower()
    if q:
        rows = [
            s
            for s in rows
            if q in s.name_en.lower()
            or q in s.name_pl.lower()
            or q in s.slug.lower()
            or (s.scientific or "").lower().find(q) >= 0
        ]
    # Favourites first, then alphabetical - the four target species should
    # always be reachable without typing.
    return sorted(rows, key=lambda s: (0 if s.is_favourite else 1, s.name_en))


def favourite_species(db: Session) -> list[Species]:
    return list(
        db.execute(
            select(Species).where(Species.is_favourite == 1).order_by(Species.id)
        ).scalars().all()
    )
