# Migrations

v0 (MVP) creates the schema via `Base.metadata.create_all()` on startup
(`app/core/db.py::init_db`), idempotent and driven entirely by
`app/core/models.py`. This is a deliberate simplification: `docs/03-DATA-MODEL.md`
and `docs/08-DEV-WORKFLOW.md` call for forward-only numbered SQL migrations,
which matters once real season data exists and a schema change must not
touch it. Introduce the first numbered migration (`0001_init.sql` capturing
the v0 schema as a baseline) before the first breaking model change ships.
