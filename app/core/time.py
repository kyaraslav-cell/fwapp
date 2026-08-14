from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Europe/Warsaw")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def to_display(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(DISPLAY_TZ)
