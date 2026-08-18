"""Deep history backfill: resumable, idempotent, and honest about gaps.

The network is not touched - `fetch_archive` is replaced. What is under test is
the behaviour around it, which is where the risks are: writing a value twice,
silently swallowing a failed year, or filling a hole with something invented.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.models import Base, IngestGap, Lake, WeatherHourly
from app.ingest import archive

NOW = dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.UTC)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        Lake(
            slug="pomocnia", name="Pomocnia",
            centroid_lat=52.5431, centroid_lon=20.6762,
            created_at=NOW.isoformat(),
        )
    )
    session.commit()
    return session


def _lake(db: Session) -> Lake:
    return db.execute(select(Lake)).scalars().one()


def _fake_rows(start: dt.date, end: dt.date, hours_per_day: int = 2) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    day = start
    while day <= end:
        for hour in range(hours_per_day):
            ts = dt.datetime.combine(day, dt.time(hour), dt.UTC)
            rows.append(
                {
                    "ts_utc": ts.isoformat(),
                    "temperature_2m": 15.0,
                    "pressure_msl": 1013.0,
                    "dewpoint_2m": 9.0,
                    "relative_humidity_2m": 70.0,
                    "wind_speed_10m": 3.0,
                    "wind_direction_10m": 270.0,
                    "wind_gusts_10m": 6.0,
                    "cloud_cover": 40.0,
                    "shortwave_radiation": 100.0,
                    "precipitation": 0.0,
                }
            )
        day += dt.timedelta(days=1)
    return rows


def test_backfill_writes_history(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "fetch_archive", lambda lat, lon, s, e, **k: _fake_rows(s, e))
    written = archive.backfill(db, _lake(db), years=1, now=NOW)
    assert written > 700, "a year of two-hourly rows should land"
    stored = db.execute(
        select(func.count())
        .select_from(WeatherHourly)
        .where(WeatherHourly.source == archive.SOURCE)
    ).scalar_one()
    assert stored == written


def test_backfill_is_idempotent(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running twice must not double the record.

    This matters more than it looks: the pressure norm is a median over the
    stored series, and duplicated hours would quietly reweight it.
    """
    monkeypatch.setattr(archive, "fetch_archive", lambda lat, lon, s, e, **k: _fake_rows(s, e))
    first = archive.backfill(db, _lake(db), years=1, now=NOW)
    second = archive.backfill(db, _lake(db), years=1, now=NOW)
    assert first > 0
    assert second == 0


def test_a_failed_chunk_becomes_a_gap_not_an_exception(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Law 4: a year that could not be fetched is a hole in the record, recorded."""

    def boom(lat: float, lon: float, s: dt.date, e: dt.date, **k: Any) -> list[dict[str, Any]]:
        raise httpx.ConnectError("archive unreachable")

    monkeypatch.setattr(archive, "fetch_archive", boom)
    written = archive.backfill(db, _lake(db), years=2, now=NOW)
    assert written == 0
    gaps = db.execute(select(IngestGap).where(IngestGap.source == archive.SOURCE)).scalars().all()
    assert gaps, "a failed chunk must leave a gap row behind"
    assert "ConnectError" in (gaps[0].reason or "")


def test_archive_never_overwrites_the_forecast_series(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two sources stay separable so `weather_hourly` keeps its provenance."""
    lake = _lake(db)
    ts = dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.UTC).isoformat()
    db.add(
        WeatherHourly(
            lake_id=lake.id, source="openmeteo_forecast", ts_utc=ts, is_forecast=0,
            temperature_2m=99.0, pressure_msl=900.0, fetched_at=ts,
        )
    )
    db.commit()
    monkeypatch.setattr(archive, "fetch_archive", lambda lat, lon, s, e, **k: _fake_rows(s, e))
    archive.backfill(db, lake, years=1, now=NOW)

    kept = db.execute(
        select(WeatherHourly).where(WeatherHourly.source == "openmeteo_forecast")
    ).scalars().one()
    assert kept.temperature_2m == 99.0, "the original reading must survive untouched"


def test_backfill_enables_the_pressure_norm(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of the whole module.

    Without deep history `pressure_norm` returns None, the pressure factor is
    unavailable and the bite index refuses to score at all. This is the test
    that says the backfill actually unblocks it.
    """
    import yaml

    from app.core.config import CONFIG_DIR
    from app.features import stability as stab

    ruleset = yaml.safe_load((CONFIG_DIR / "rules.v0.4.yaml").read_text(encoding="utf-8"))
    cfg = ruleset["pressure_norm"]

    monkeypatch.setattr(
        archive, "fetch_archive", lambda lat, lon, s, e, **k: _fake_rows(s, e, hours_per_day=24)
    )
    archive.backfill(db, _lake(db), years=2, now=NOW)

    rows = db.execute(
        select(WeatherHourly).where(WeatherHourly.source == archive.SOURCE)
    ).scalars().all()
    samples = [
        stab.Sample(dt.datetime.fromisoformat(r.ts_utc), r.pressure_msl)
        for r in rows
        if r.pressure_msl is not None
    ]
    assert len(samples) >= int(cfg["min_samples_hours"])
    assert stab.pressure_norm(samples, cfg) == 1013.0
