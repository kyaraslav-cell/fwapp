"""Weather stability over the previous days, and the lake's own pressure norm.

Why 72 hours and not some other number: a lake with a mean depth under 3 m has
a thermal time constant of roughly one to three days, so the last three days of
air temperature effectively *are* its water temperature. The window is this
lake's memory, not a preference. See docs/adr/0003.

Stability does two separate jobs and the split is deliberate:

  * it raises the bite score, because a settled fish feeds;
  * it raises CONFIDENCE, because a model driven by a 72-hour mean deserves
    less belief when those 72 hours were chaotic (law 5).

Everything here is pure: samples and `now` are passed in, nothing reads a clock
and nothing touches the database. Every function returns `None` rather than a
plausible-looking number when the data will not support one - law 4 applies to
derived statistics just as much as to observations.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class Sample:
    ts: datetime
    value: float


@dataclass(frozen=True)
class WindowStats:
    """What a lookback window actually contained, gaps included."""

    hours: int
    expected: int
    present: int
    minimum: float | None
    maximum: float | None
    mean: float | None

    @property
    def coverage(self) -> float:
        if self.expected <= 0:
            return 0.0
        return min(1.0, self.present / self.expected)

    @property
    def span(self) -> float | None:
        """Max minus min - the range the owner cares about, not the variance."""
        if self.minimum is None or self.maximum is None:
            return None
        return self.maximum - self.minimum

    def available(self, min_coverage: float) -> bool:
        return self.present >= 2 and self.coverage >= min_coverage


def in_window(samples: list[Sample], now: datetime, hours: int) -> list[Sample]:
    start = now - timedelta(hours=hours)
    return [s for s in samples if start <= s.ts <= now]


def summarise(samples: list[Sample], now: datetime, hours: int) -> WindowStats:
    """Pure. Describe one lookback window, including how much of it is missing."""
    window = in_window(samples, now, hours)
    values = [s.value for s in window]
    return WindowStats(
        hours=hours,
        expected=hours,
        present=len(values),
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        mean=statistics.fmean(values) if values else None,
    )


def _range_term(span: float | None, full: float) -> float | None:
    """1.0 when nothing moved, 0.0 once the range reaches `full`."""
    if span is None or full <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - span / full))


def stability_index(
    pressure: WindowStats, air_temp: WindowStats, cfg: dict[str, Any]
) -> float | None:
    """Pure. 0..1, or None when the window is too sparse to judge.

    A product rather than a mean: a settled barometer during a 15 degree
    temperature swing is not a stable spell, and averaging would call it half
    of one.
    """
    min_coverage = float(cfg["min_coverage_ratio"])
    if not pressure.available(min_coverage) or not air_temp.available(min_coverage):
        return None

    p_term = _range_term(pressure.span, float(cfg["pressure_range_full_hpa"]))
    t_term = _range_term(air_temp.span, float(cfg["air_temp_range_full_c"]))
    if p_term is None or t_term is None:
        return None
    return p_term * t_term


def daily_spans(samples: list[Sample], now: datetime, days: int) -> list[float | None]:
    """Pure. The range of each of the last `days` 24-hour blocks, most recent first."""
    out: list[float | None] = []
    for day in range(days):
        end = now - timedelta(hours=24 * day)
        block = [s.value for s in samples if end - timedelta(hours=24) <= s.ts <= end]
        out.append(max(block) - min(block) if len(block) >= 2 else None)
    return out


def consecutive_stable_days(
    pressure: list[Sample], air_temp: list[Sample], now: datetime, cfg: dict[str, Any]
) -> int:
    """Pure. How many days back the weather has been settled, counting from now.

    Stops at the first day that fails or that has no data - an unknown day
    breaks the streak rather than being assumed good.
    """
    limits = cfg["stable_day"]
    p_max = float(limits["pressure_range_hpa_max"])
    t_max = float(limits["air_temp_range_c_max"])
    horizon = 7

    p_spans = daily_spans(pressure, now, horizon)
    t_spans = daily_spans(air_temp, now, horizon)

    streak = 0
    for p_span, t_span in zip(p_spans, t_spans, strict=True):
        if p_span is None or t_span is None:
            break
        if p_span > p_max or t_span > t_max:
            break
        streak += 1
    return streak


def pressure_norm(history: list[Sample], cfg: dict[str, Any]) -> float | None:
    """Pure. This water body's own pressure norm: the median of its own record.

    The source video's central claim is that the norm differs per water body,
    and it withholds the formula. So none is borrowed: a long-run median of the
    lake's own observed series IS the norm, and a median rather than a mean
    because storms should not drag it.

    Returns None when there is not enough history. That is the whole point -
    an invented norm would silently poison every pressure term downstream.
    """
    values = [s.value for s in history]
    if len(values) < int(cfg["min_samples_hours"]):
        return None
    return statistics.median(values)
