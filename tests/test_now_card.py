"""The "Right now" card, and the bug that made it show next week.

`current_reading` used to select `order_by(ts_utc.desc()).limit(200)` and then
pick the row nearest to now out of that slice. Sorted descending, those 200
rows are the ones furthest into the *future*, so on a water with a full
fifteen-day forecast the nearest-to-now candidate was already about eight days
out. The live page showed 31 August, 18:00 as the current conditions on the
morning of the 26th - 23 °C and 1011 hPa while it was 16 °C and 1023 hPa
outside.

These tests pin the window, not the slice.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Lake, WeatherHourly
from app.core.time import iso, utcnow
from app.web.weather_table import NOW_WINDOW_HOURS, current_reading


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def lake(db: Session) -> Lake:
    row = Lake(
        slug="zegrzynski",
        name="Zalew Zegrzynski",
        centroid_lat=52.49,
        centroid_lon=21.07,
        timezone="Europe/Warsaw",
        created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def _hour(lake: Lake, offset_h: float, temp: float, *, forecast: int = 1) -> WeatherHourly:
    ts = utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=offset_h)
    return WeatherHourly(
        lake_id=lake.id,
        source="openmeteo_forecast",
        ts_utc=iso(ts),
        is_forecast=forecast,
        temperature_2m=temp,
        pressure_msl=1023.0,
        wind_speed_10m=2.0,
        wind_direction_10m=200.0,
        fetched_at=iso(utcnow()),
    )


def test_the_current_hour_wins_over_a_fortnight_of_forecast(db: Session, lake: Lake) -> None:
    """The exact shape of the live bug: many future rows, one row at now."""
    db.add(_hour(lake, 0, 16.0))
    # 15 days of forecast, hourly - far more than the old limit of 200 rows,
    # which is what let the slice miss "now" entirely. Starts at +2 h so the
    # nearest row is unambiguous whatever minute of the hour the suite runs at:
    # the floored "now" row is at most 59 minutes back, the first forecast row
    # at least 61 minutes forward.
    for h in range(2, 15 * 24):
        db.add(_hour(lake, h, 23.0))
    db.flush()

    reading = current_reading(db, lake)

    assert reading is not None
    assert reading["temp_c"] == 16.0, "the card reached into the forecast for its 'now'"


def test_the_nearest_hour_is_chosen_in_either_direction(db: Session, lake: Lake) -> None:
    db.add(_hour(lake, -2, 12.0))
    db.add(_hour(lake, 1, 18.0))
    db.flush()

    reading = current_reading(db, lake)

    assert reading is not None
    assert reading["temp_c"] == 18.0


def test_a_stalled_ingest_shows_nothing_rather_than_something_old(
    db: Session, lake: Lake
) -> None:
    """Law 4, applied to the display layer.

    A water whose ingest has stopped still has rows; they are simply all old.
    Presenting a two-day-old hour as "now" is the same fabrication as
    interpolating one, just in a smaller font.
    """
    db.add(_hour(lake, -(NOW_WINDOW_HOURS + 5), 12.0, forecast=0))
    db.flush()

    assert current_reading(db, lake) is None


def test_an_observation_and_a_forecast_at_the_same_hour_do_not_crash(
    db: Session, lake: Lake
) -> None:
    db.add(_hour(lake, 0, 16.0, forecast=0))
    db.add(_hour(lake, 0, 16.5, forecast=1))
    db.flush()

    reading = current_reading(db, lake)

    assert reading is not None
    assert reading["temp_c"] in (16.0, 16.5)
