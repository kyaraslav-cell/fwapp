from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from astral import Observer
from astral.sun import sun


@dataclass(frozen=True)
class SunTimes:
    civil_dawn: datetime
    sunrise: datetime
    solar_noon: datetime
    sunset: datetime
    civil_dusk: datetime


def compute_sun_times(lat: float, lon: float, on_date: date) -> SunTimes:
    """Pure. `on_date` is supplied by the caller — no clock reads here."""
    observer = Observer(latitude=lat, longitude=lon)
    s = sun(observer, date=on_date, tzinfo=UTC)
    return SunTimes(
        civil_dawn=s["dawn"],
        sunrise=s["sunrise"],
        solar_noon=s["noon"],
        sunset=s["sunset"],
        civil_dusk=s["dusk"],
    )
