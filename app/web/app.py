from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.db import init_db, session_scope
from app.core.seed import ensure_lake_seeded
from app.ingest.open_meteo import ingest_forecast
from app.ingest.scheduler import build_scheduler
from app.predict.daily import generate_predictions
from app.web.routes import history, sessions, today

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as db:
        lake = ensure_lake_seeded(db)
        ingest_forecast(db, lake)
        generate_predictions(db, lake)

    scheduler = build_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Fishlog", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
    app.include_router(today.router)
    app.include_router(sessions.router)
    app.include_router(history.router)
    return app


app = create_app()
