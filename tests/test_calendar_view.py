"""The day strip: what it reads, and what it refuses to invent.

The band on each chip is the whole feature, so these tests are mostly about
where that band comes from. It comes out of a stored `prediction` row written
before the day it describes (law 2). If any of this ever starts recomputing at
render time, the calibration loop loses the evidence it exists to collect.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, Lake, Prediction, WeatherHourly
from app.core.time import iso, to_display, utcnow
from app.web.view_helpers import CONFIDENT_HORIZON_DAYS, calendar_view
from app.web.weather_table import forecast_day_summaries


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def lake(db: Session) -> Lake:
    row = Lake(
        slug="pomocnia",
        name="Pomocnia",
        centroid_lat=52.0,
        centroid_lon=21.0,
        timezone="Europe/Warsaw",
        created_at=iso(utcnow()),
    )
    db.add(row)
    db.flush()
    return row


def write_prediction(
    db: Session,
    lake: Lake,
    horizon: int,
    colour: str,
    regime: str | None = "falling_slow",
    dp_6h: float | None = -1.4,
) -> Prediction:
    target = to_display(utcnow()).date() + timedelta(days=horizon)
    start = utcnow().replace(hour=4, minute=47)
    payload = {
        "day_score": 6.0,
        "go": True,
        "band_color": colour,
        "band_label": colour.title(),
        "best_hours": [
            {"label": "morning", "start": iso(start), "end": iso(start + timedelta(hours=2))}
        ],
        "reasons": [],
        "per_rule_contributions": {},
        "pressure_regime": regime,
        "dp_6h": dp_6h,
    }
    row = Prediction(
        lake_id=lake.id,
        target_date=str(target),
        horizon_days=horizon,
        generated_at=iso(utcnow()),
        ruleset_version="test",
        features_version="test",
        inputs_hash="test",
        day_score=6.0,
        payload_json=json.dumps(payload),
    )
    db.add(row)
    db.flush()
    return row


def latest(db: Session, lake: Lake, horizon: int = 0) -> Prediction | None:
    return (
        db.query(Prediction)
        .filter(Prediction.lake_id == lake.id, Prediction.horizon_days == horizon)
        .one_or_none()
    )


def test_the_strip_starts_today_and_runs_to_the_horizon(db: Session, lake: Lake) -> None:
    for horizon in range(0, 8):
        write_prediction(db, lake, horizon, "green")

    days = calendar_view(db, lake, 7, latest, {})

    assert len(days) == 8
    assert days[0]["is_today"] and days[0]["horizon"] == 0
    assert [d["horizon"] for d in days] == list(range(8))
    today_local = to_display(utcnow()).date()
    assert days[0]["date"] == today_local.isoformat()
    assert days[-1]["date"] == (today_local + timedelta(days=7)).isoformat()


def test_the_band_is_read_from_the_stored_prediction(db: Session, lake: Lake) -> None:
    """Not recomputed. The row is what the app said before the day happened."""
    write_prediction(db, lake, 0, "red")
    write_prediction(db, lake, 1, "green")

    days = calendar_view(db, lake, 1, latest, {})

    assert days[0]["band_color"] == "red"
    assert days[1]["band_color"] == "green"


def test_a_day_with_no_prediction_has_no_colour_and_says_so(db: Session, lake: Lake) -> None:
    """Law 4: a gap is a gap. It is never filled from the day beside it."""
    write_prediction(db, lake, 0, "green")
    write_prediction(db, lake, 2, "green")

    days = calendar_view(db, lake, 2, latest, {})

    assert days[1]["has_data"] is False
    assert days[1]["band_color"] is None
    assert days[1]["best_hours"] == []
    # and the neighbours are untouched
    assert days[0]["band_color"] == "green"
    assert days[2]["band_color"] == "green"


def test_days_past_the_confident_horizon_are_flagged(db: Session, lake: Lake) -> None:
    for horizon in range(0, 8):
        write_prediction(db, lake, horizon, "green")

    days = calendar_view(db, lake, 7, latest, {})

    assert not any(d["is_far"] for d in days[: CONFIDENT_HORIZON_DAYS + 1])
    assert all(d["is_far"] for d in days[CONFIDENT_HORIZON_DAYS + 1 :])


def test_today_carries_no_forecast_wind(db: Session, lake: Lake) -> None:
    """Today's map is scored from the live reading, not from a day mean.

    Handing today a daily average would quietly change what "now" means on the
    one day the angler can actually act on.
    """
    write_prediction(db, lake, 0, "green")
    write_prediction(db, lake, 1, "green")
    today = to_display(utcnow()).date()

    days = calendar_view(
        db,
        lake,
        1,
        latest,
        {
            today.isoformat(): {"wind_dir": 90.0},
            (today + timedelta(days=1)).isoformat(): {"wind_dir": 270.0},
        },
    )

    assert days[0]["wind_dir"] is None
    assert days[1]["wind_dir"] == 270.0


def test_a_day_the_forecast_never_covered_has_no_wind(db: Session, lake: Lake) -> None:
    write_prediction(db, lake, 1, "green")
    days = calendar_view(db, lake, 1, latest, {})
    assert days[1]["wind_dir"] is None


def test_best_hours_are_shown_in_local_time(db: Session, lake: Lake) -> None:
    write_prediction(db, lake, 0, "green")
    days = calendar_view(db, lake, 0, latest, {})
    assert len(days[0]["best_hours"]) == 1
    text = days[0]["best_hours"][0]
    assert "–" in text and len(text) == 11  # HH:MM–HH:MM


def test_no_score_leaks_into_the_strip(db: Session, lake: Lake) -> None:
    """The owner's standing rule: a colour band, never a raw number."""
    write_prediction(db, lake, 0, "green")
    days = calendar_view(db, lake, 0, latest, {})
    assert "day_score" not in days[0]
    assert not any(isinstance(v, float) and 0 <= v <= 10 for v in days[0].values() if v is not None)


# ---------------------------------------------------------------------------
# The per-day wind the map re-scores with
# ---------------------------------------------------------------------------


def add_hour(db: Session, lake: Lake, when, wind_dir: float | None, is_forecast: int) -> None:
    db.add(
        WeatherHourly(
            lake_id=lake.id,
            source="openmeteo_forecast",
            ts_utc=iso(when),
            is_forecast=is_forecast,
            wind_direction_10m=wind_dir,
            fetched_at=iso(utcnow()),
        )
    )


def test_forecast_winds_are_averaged_per_day(db: Session, lake: Lake) -> None:
    tomorrow = utcnow() + timedelta(days=1)
    base = tomorrow.replace(hour=6, minute=0, second=0, microsecond=0)
    for offset, bearing in enumerate([80.0, 90.0, 100.0]):
        add_hour(db, lake, base + timedelta(hours=offset), bearing, is_forecast=1)
    db.flush()

    summaries = forecast_day_summaries(db, lake, 7)
    day = to_display(base).date().isoformat()
    assert summaries[day]["wind_dir"] == 90.0


def test_the_average_wraps_around_north(db: Session, lake: Lake) -> None:
    """350 and 10 degrees average to north, not to south."""
    tomorrow = utcnow() + timedelta(days=1)
    base = tomorrow.replace(hour=6, minute=0, second=0, microsecond=0)
    add_hour(db, lake, base, 350.0, is_forecast=1)
    add_hour(db, lake, base + timedelta(hours=1), 10.0, is_forecast=1)
    db.flush()

    summaries = forecast_day_summaries(db, lake, 7)
    assert summaries[to_display(base).date().isoformat()]["wind_dir"] == 0.0


def test_observations_are_not_treated_as_forecast(db: Session, lake: Lake) -> None:
    """is_forecast = 0 is a record of what happened, and this asks about ahead."""
    tomorrow = (utcnow() + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    add_hour(db, lake, tomorrow, 123.0, is_forecast=0)
    db.flush()

    assert forecast_day_summaries(db, lake, 7) == {}


# ---------------------------------------------------------------------------
# What a picked day hands to the page
# ---------------------------------------------------------------------------


def test_a_day_carries_the_regime_that_explains_its_colour(db: Session, lake: Lake) -> None:
    """The sentence under the strip is built from these two, not from prose.

    Keeping the regime name and the number separate is what lets the wording be
    translated without anybody restating a threshold in a language file.
    """
    write_prediction(db, lake, 1, "green", regime="falling_fast", dp_6h=-4.2)
    days = calendar_view(db, lake, 1, latest, {})

    assert days[1]["pressure_regime"] == "falling_fast"
    assert days[1]["dp_6h"] == -4.2


def test_a_day_with_no_prediction_explains_nothing(db: Session, lake: Lake) -> None:
    days = calendar_view(db, lake, 1, latest, {})
    assert days[1]["pressure_regime"] is None
    assert days[1]["dp_6h"] is None


def test_a_forecast_day_carries_its_own_weather(db: Session, lake: Lake) -> None:
    """The conditions card takes these while that day is selected."""
    write_prediction(db, lake, 1, "green")
    tomorrow = (to_display(utcnow()).date() + timedelta(days=1)).isoformat()

    days = calendar_view(
        db,
        lake,
        1,
        latest,
        {tomorrow: {
            "wind_dir": 270.0, "wind_compass": "W", "wind_max": 6.4,
            "temp_min": 11.0, "temp_max": 19.5, "pressure_hpa": 1011,
        }},
    )

    assert days[1]["temp_max"] == 19.5
    assert days[1]["wind_compass"] == "W"
    assert days[1]["wind_max"] == 6.4
    assert days[1]["pressure_hpa"] == 1011


def test_today_never_takes_a_forecast_summary(db: Session, lake: Lake) -> None:
    """Today's card shows the live reading. A day mean is not a reading."""
    write_prediction(db, lake, 0, "green")
    today = to_display(utcnow()).date().isoformat()

    days = calendar_view(
        db, lake, 0, latest,
        {today: {"wind_dir": 270.0, "wind_compass": "W", "temp_max": 30.0, "pressure_hpa": 999}},
    )

    assert days[0]["temp_max"] is None
    assert days[0]["wind_dir"] is None
    assert days[0]["pressure_hpa"] is None


def test_a_day_the_forecast_missed_has_no_weather(db: Session, lake: Lake) -> None:
    write_prediction(db, lake, 1, "green")
    days = calendar_view(db, lake, 1, latest, {})
    assert days[1]["temp_max"] is None
    assert days[1]["wind_max"] is None


def test_the_rating_is_derived_from_the_ruleset_not_written_down(db: Session, lake: Lake) -> None:
    """Reorder the ruleset's regime scores and the sentence follows.

    This is the test that keeps law 1 honest for the explanation line: which
    pressure state is good is a weight in the YAML, and the wording under the
    strip has to read it rather than repeat it.
    """
    from app.web.view_helpers import regime_rating

    scores = {"falling_slow": 1.0, "stable": 0.6, "rising_slow": 0.4,
              "falling_fast": 0.3, "rising_fast": -0.5}
    assert regime_rating(scores, "falling_slow") == "best"
    assert regime_rating(scores, "rising_fast") == "worst"

    # The owner's real formula lands and inverts the ranking.
    flipped = {name: -value for name, value in scores.items()}
    assert regime_rating(flipped, "falling_slow") == "worst"
    assert regime_rating(flipped, "rising_fast") == "best"


def test_an_unscored_regime_gets_no_rating(db: Session, lake: Lake) -> None:
    from app.web.view_helpers import regime_rating

    assert regime_rating({"stable": 1.0}, None) is None
    assert regime_rating({"stable": 1.0}, "not_a_regime") is None
    assert regime_rating({}, "stable") is None


def test_the_rating_travels_with_the_day(db: Session, lake: Lake) -> None:
    write_prediction(db, lake, 1, "green", regime="rising_fast", dp_6h=5.0)
    days = calendar_view(
        db, lake, 1, latest, {},
        regime_scores={"falling_slow": 1.0, "rising_fast": -0.5},
    )
    assert days[1]["regime_rating"] == "worst"
