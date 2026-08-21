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


def create_missing_indexes(engine: Engine) -> list[str]:
    """Create model indexes that an already-existing table never got.

    `Base.metadata.create_all()` creates a table *and* its indexes, but it
    skips a table that already exists - and skips its indexes with it. So an
    index added to a model after the first run never reaches a live database,
    and the query it was meant to speed up keeps scanning, silently and
    forever. The owner's laptop has had `fishlog.db` since the first session;
    without this, the notebook indexes added in `docs/15 §A3` would have
    applied to new installs only.

    Same narrow contract as `add_missing_columns`: additive, idempotent,
    nothing dropped or altered, and no substitute for the numbered forward-only
    migrations `docs/03-DATA-MODEL.md` requires before real season data exists.
    """
    inspector = inspect(engine)
    created: list[str] = []

    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            # create_all will build it and its indexes together.
            continue
        existing = {i["name"] for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in existing:
                continue
            index.create(bind=engine)
            created.append(str(index.name))
            logger.info("created missing index %s on %s", index.name, table.name)

    return created
