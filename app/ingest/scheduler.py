from __future__ import annotations

import argparse
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.db import init_db, session_scope
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


def main(argv: list[str] | None = None) -> int:
    """Run one ingest-and-predict pass and exit.

    For environments with no long-lived process to hold APScheduler: the
    GitHub Pages workflow runs this on its own cron before rebuilding the site.

    It exits 0 even when the fetch fails. That is deliberate and follows law 4 -
    a failed fetch writes no observation and records a gap, which is a correct
    outcome, not a broken build. Making it fail here would either block the
    publish or invite someone to paper over the gap with a fabricated reading.
    """
    parser = argparse.ArgumentParser(prog="app.ingest.scheduler")
    parser.add_argument(
        "--once", action="store_true",
        help="run one ingest + prediction pass instead of starting a scheduler",
    )
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("only --once is supported; the app itself starts the scheduler")

    logging.basicConfig(level=logging.INFO)
    # The tables are created by the FastAPI lifespan, which never runs here.
    # Without this the first call dies on "no such table: species" the moment
    # the database file is absent - invisible locally, where fishlog.db already
    # exists, and fatal on a fresh CI runner.
    init_db()
    try:
        run_ingest_job()
    except Exception:
        logger.exception("ingest failed - leaving the gap unfilled (law 4)")
    try:
        run_predict_job()
    except Exception:
        logger.exception("prediction pass failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
