from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text

from app.core.models import Base

logger = logging.getLogger("fishlog.migrate")


def add_missing_columns(engine: Engine) -> list[str]:
    """Add columns present in the models but missing from an existing SQLite table.

    `Base.metadata.create_all()` creates missing *tables* but never alters
    existing ones, so adding a model column used to break any database created
    before it. This closes that gap for the additive case, which is the only
    case v0 has needed so far.

    Interim measure, deliberately narrow: it only ever ADDs nullable columns.
    It does not drop, rename or retype anything, and it is not a substitute for
    the forward-only numbered migrations that `docs/03-DATA-MODEL.md` requires
    before real season data exists. See migrations/README.md.
    """
    inspector = inspect(engine)
    applied: list[str] = []

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable and column.default is None:
                    logger.warning(
                        "skipping non-nullable column %s.%s with no default - "
                        "needs a real migration",
                        table.name,
                        column.name,
                    )
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')
                )
                applied.append(f"{table.name}.{column.name}")
                logger.info("added missing column %s.%s", table.name, column.name)

    return applied
