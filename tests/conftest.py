"""Test isolation: never let a real `.env` leak into the suite.

`app/web/app.py` ends with a module-level `app = create_app()`, so it can be
handed to uvicorn as `app.web.app:app`. That means `load_env_file()` runs the
instant anything *imports* that module - during pytest's collection phase,
before any fixture, including a function-scoped one here, gets a chance to
run. A test doing `monkeypatch.delenv("FISHLOG_GOOGLE_CLIENT_ID")` to simulate
"not configured" was already too late: the real `.env` had been read at import
time and the var refilled before the test body even started. That only
surfaces once a real `.env` exists, which is exactly what happened on the
owner's machine - see `docs/handoff`, 2026-08-24.

So this has to happen at *module* level, here, before pytest imports the first
test module that pulls in `app.web.app`.
"""

from __future__ import annotations

import pathlib

from app.core import env as env_module

env_module.ENV_FILE = pathlib.Path(__file__).parent / "_no_such_dotenv_for_tests"
