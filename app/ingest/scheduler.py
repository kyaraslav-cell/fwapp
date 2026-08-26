from __future__ import annotations

import argparse
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import init_db, session_scope
from app.core.models import Lake
from app.core.seed import ensure_lake_seeded
from app.geo import service as geo_service
from app.ingest.open_meteo import ingest_forecast
from app.predict.daily import generate_predictions

logger = logging.getLogger("fishlog.scheduler")


def _all_lakes(db: Session) -> list[Lake]:
    """Every water in the database, with the seeded one guaranteed to exist.

    Both hourly jobs below used to call `ensure_lake_seeded` and operate on its
    single return value, so a water added through the discover pipeline got one
    forecast at add-time and was then never touched again. Symptoms, all from
    that one cause: a "Right now" card frozen at whatever hour the water was
    added, a day strip that ran out a week later, and "no data yet" on the
    places list forever, because `home()` asks for a horizon-0 prediction and
    nothing ever wrote one.
    """
    ensure_lake_seeded(db)
    return list(db.execute(select(Lake).order_by(Lake.id)).scalars().all())


def run_ingest_job() -> None:
    """Fetch the forecast for every water, one at a time.

    Each water is its own try/except: Open-Meteo refusing one set of
    coordinates must not cost every other water its hourly update. A failure
    here is already recorded as an `ingest_gap` by `ingest_forecast` itself
    (law 4 - write nothing, log the gap), so this only has to keep going.
    """
    with session_scope() as db:
        lakes = _all_lakes(db)
        total = 0
        for lake in lakes:
            try:
                total += ingest_forecast(db, lake)
            except Exception:  # noqa: BLE001 - one bad water must not stop the rest
                logger.exception("ingest failed for %s", lake.slug)
        logger.info("ingest: wrote %d weather_hourly rows across %d water(s)", total, len(lakes))


def run_predict_job() -> None:
    """Write today's prediction row for every water.

    Same isolation as the ingest pass, and for the same reason. A water whose
    pressure history is too short to score raises rather than inventing a
    number, and that must not deny every other water its row.
    """
    with session_scope() as db:
        lakes = _all_lakes(db)
        written = 0
        for lake in lakes:
            try:
                generate_predictions(db, lake)
                written += 1
            except Exception:  # noqa: BLE001 - see run_ingest_job
                logger.exception("prediction failed for %s", lake.slug)
        logger.info("predict: wrote predictions for %d/%d water(s)", written, len(lakes))


def run_jobs_tick() -> None:
    """Drain the background queue: outlines, grids, backfills for new waters.

    Every 30 seconds rather than on a cron, because these jobs are what an
    angler is waiting for after typing a lake's name - a minute of dead time
    with the page saying "preparing" is the difference between a feature that
    feels alive and one that feels broken.
    """
    from app.jobs.runner import drain

    drained = drain()
    if drained:
        logger.info("jobs: ran %s", drained)


def run_monthly_refresh_job() -> None:
    """Re-check every discovered water's shoreline once a month.

    OSM improves: a pond mapped as a blob in 2024 gets a proper shore in 2026.
    One Overpass call per water per month is nothing against their allowance,
    and it is the cheapest way to let the map get better on its own.
    """
    from app.core.models import Lake
    from app.jobs import queue
    from app.jobs.handlers import OUTLINE

    with session_scope() as db:
        waters = db.query(Lake).filter(Lake.origin == "discovered").all()
        for lake in waters:
            # Clearing the cached polygon is what makes the outline job refetch;
            # the handler is a no-op for a water that still has one.
            lake.outline_geojson = None
            queue.enqueue(db, OUTLINE, lake_id=lake.id)
        logger.info("monthly refresh queued for %s waters", len(waters))


def run_hires_grid_job() -> None:
    """Queue today's finer grid for every water large enough to want one.

    Its own daily cadence, not part of `NEW_WATER_PIPELINE`: adding a water
    happens once, but "today" changes every day, so this has to re-run on a
    schedule of its own (`docs/09-BACKLOG.md §19c`). Queued, not run inline,
    so a slow grid build never delays this tick - `run_jobs_tick` drains it
    like every other job.
    """
    from app.core.models import Lake
    from app.jobs import queue
    from app.jobs.handlers import GRID_HIRES

    with session_scope() as db:
        waters = db.query(Lake).all()
        queued = 0
        for lake in waters:
            if geo_service.hires_cell_size_for_area(lake.area_ha) is None:
                continue
            queue.enqueue(db, GRID_HIRES, lake_id=lake.id)
            queued += 1
        logger.info("hi-res grid queued for %s water(s)", queued)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_ingest_job, CronTrigger(minute=5), id="fetch_openmeteo_forecast")
    scheduler.add_job(run_predict_job, CronTrigger(hour=4, minute=0), id="generate_prediction")
    scheduler.add_job(run_jobs_tick, IntervalTrigger(seconds=30), id="drain_job_queue")
    scheduler.add_job(
        run_monthly_refresh_job,
        CronTrigger(day=1, hour=3, minute=0),
        id="refresh_discovered_waters",
    )
    # After the 04:00 prediction pass, so today's forecast is already in when
    # this reads "today's wind" - not tied to that job otherwise.
    scheduler.add_job(
        run_hires_grid_job,
        CronTrigger(hour=4, minute=15),
        id="queue_hires_grid",
    )
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
