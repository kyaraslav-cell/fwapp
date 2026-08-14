from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.db import session_scope
from app.core.seed import ensure_lake_seeded
from app.ingest.open_meteo import ingest_forecast
from app.predict.daily import generate_predictions

logger = logging.getLogger("fishlog.scheduler")


def run_ingest_job() -> None:
    with session_scope() as db:
        lake = ensure_lake_seeded(db)
        written = ingest_forecast(db, lake)
        logger.info("ingest: wrote %d weather_hourly rows", written)


def run_predict_job() -> None:
    with session_scope() as db:
        lake = ensure_lake_seeded(db)
        generate_predictions(db, lake)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_ingest_job, CronTrigger(minute=5), id="fetch_openmeteo_forecast")
    scheduler.add_job(run_predict_job, CronTrigger(hour=4, minute=0), id="generate_prediction")
    return scheduler
