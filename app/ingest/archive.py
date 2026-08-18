"""Deep weather history from the ERA5 archive, for the parts of the model that need years.

WHY THIS EXISTS. The forecast endpoint returns three days of the past. Three
days is exactly right for the water-temperature model - it is this lake's
thermal memory - but it is nowhere near enough for the two things that need a
long record:

  * THE PRESSURE NORM. `config/rules.v*.yaml` requires 8760 hours before it will
    name a norm, because the source video's central claim is that every water
    has its own and a norm computed from three days is a norm of the current
    weather, not of the lake. Until this backfill runs, `pressure_norm` returns
    None, the pressure factor is unavailable, and the whole bite index refuses
    to score. That is correct behaviour and also a permanently blank answer.
  * BACK-TESTING. Law 2 makes predictions immutable so the model can be judged
    against what actually happened. Judging a *new* ruleset needs the weather of
    seasons already past, which no forecast endpoint will ever return.

WHAT IT IS AND IS NOT. ERA5 is reanalysis - a physical model fitted to the
observations that were actually recorded, published by Copernicus and served
here by Open-Meteo's archive endpoint. It is a published record, not a
fabrication, so it belongs in `weather_hourly` under law 4. It is stored with
its own `source` so it is never confused with the forecast series, and it is
never written over an hour that already has a reading.

The archive lags real time by about five days. Rows inside that window simply
are not there yet, which is why `end_date` is pulled back.
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import IngestGap, Lake, WeatherHourly
from app.core.time import iso, utcnow
from app.ingest.open_meteo import FIELD_MAP, HOURLY_VARS

logger = logging.getLogger("fishlog.ingest.archive")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE = "openmeteo_archive"

# ERA5 is published about five days behind. Asking for yesterday returns a gap,
# not an error, so the window is pulled back rather than discovering that per run.
ARCHIVE_LAG_DAYS = 6

# One request per year. The endpoint will serve a decade in one call, but a
# failure halfway through a decade loses the lot, and a year is a natural unit
# to retry.
CHUNK_DAYS = 365


def fetch_archive(
    lat: float, lon: float, start: dt.date, end: dt.date, timeout: float = 60.0
) -> list[dict]:
    """One archive request. Raises on transport or shape errors; the caller logs a gap."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "UTC",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "wind_speed_unit": "ms",
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.get(ARCHIVE_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    hourly = payload["hourly"]
    times = hourly["time"]
    rows: list[dict] = []
    for i, ts in enumerate(times):
        row: dict = {"ts_utc": ts + ":00+00:00" if len(ts) == 16 else ts}
        for api_field, model_field in FIELD_MAP.items():
            values = hourly.get(api_field, [])
            row[model_field] = values[i] if i < len(values) else None
        rows.append(row)
    return rows


def _existing_timestamps(db: Session, lake: Lake) -> set[str]:
    return set(
        db.execute(
            select(WeatherHourly.ts_utc).where(
                WeatherHourly.lake_id == lake.id,
                WeatherHourly.source == SOURCE,
                WeatherHourly.is_forecast == 0,
            )
        )
        .scalars()
        .all()
    )


def backfill(db: Session, lake: Lake, years: int = 3, now: dt.datetime | None = None) -> int:
    """Fill `weather_hourly` backwards from the archive. Returns rows written.

    Resumable and idempotent: hours already stored under this source are skipped,
    so an interrupted run is repaired by running it again, and a nightly top-up
    costs one short request.

    Never raises on a failed chunk. Law 4 - a chunk that cannot be fetched is
    recorded as an `ingest_gap` and left empty, because a hole in the record is
    honest and an interpolated year is not.
    """
    moment = now or utcnow()
    end = (moment - dt.timedelta(days=ARCHIVE_LAG_DAYS)).date()
    start = end - dt.timedelta(days=365 * years)

    have = _existing_timestamps(db, lake)
    written = 0
    cursor = start

    while cursor < end:
        chunk_end = min(cursor + dt.timedelta(days=CHUNK_DAYS), end)
        try:
            rows = fetch_archive(lake.centroid_lat, lake.centroid_lon, cursor, chunk_end)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            db.add(
                IngestGap(
                    lake_id=lake.id,
                    source=SOURCE,
                    from_utc=iso(dt.datetime.combine(cursor, dt.time.min, dt.UTC)),
                    to_utc=iso(dt.datetime.combine(chunk_end, dt.time.min, dt.UTC)),
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            logger.warning("archive %s..%s failed: %s", cursor, chunk_end, exc)
            cursor = chunk_end + dt.timedelta(days=1)
            continue

        fetched = iso(moment)
        for row in rows:
            ts = row["ts_utc"]
            if ts in have:
                continue
            # An hour with no pressure and no temperature carries nothing this
            # model uses; storing it would only pad the coverage statistics.
            if row.get("pressure_msl") is None and row.get("temperature_2m") is None:
                continue
            db.add(
                WeatherHourly(
                    lake_id=lake.id, source=SOURCE, is_forecast=0, fetched_at=fetched, **row
                )
            )
            have.add(ts)
            written += 1

        db.flush()
        logger.info("archive %s..%s: %d rows", cursor, chunk_end, written)
        cursor = chunk_end + dt.timedelta(days=1)

    return written


def main() -> int:
    """`python -m app.ingest.archive [--years N]` - safe to re-run, it resumes."""
    import argparse

    from app.core.db import init_db, session_scope

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--slug", default="pomocnia")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init_db()
    with session_scope() as db:
        lake = db.execute(select(Lake).where(Lake.slug == args.slug)).scalar_one_or_none()
        if lake is None:
            logger.error("no lake %r - start the app once to seed it", args.slug)
            return 2
        written = backfill(db, lake, years=args.years)
    print(f"{written} archive rows written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
