from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import CONFIG_DIR, load_yaml
from app.core.models import Species


def ensure_species_seeded(db: Session) -> None:
    existing = db.execute(select(Species.slug)).all()
    if existing:
        return
    cfg = load_yaml(CONFIG_DIR / "species.yaml")
    for entry in cfg["species"]:
        db.add(
            Species(
                slug=entry["slug"],
                name_en=entry["name_en"],
                name_pl=entry["name_pl"],
                scientific=entry.get("scientific"),
                family=entry.get("family"),
                scoring=entry["scoring"],
                is_favourite=1 if entry.get("favourite") else 0,
                shape=entry.get("shape"),
                typical_g=entry.get("typical_g"),
                min_g=entry.get("min_g"),
                max_g=entry.get("max_g"),
                typical_cm=entry.get("typical_cm"),
                min_cm=entry.get("min_cm"),
                max_cm=entry.get("max_cm"),
            )
        )
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
