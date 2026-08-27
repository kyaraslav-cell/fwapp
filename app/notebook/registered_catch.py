"""What other anglers actually caught here, from the okreg's own register.

Reads `config/catch_reports/*.yaml`, produced offline by
`tools/catch_report_extract.py` from the okreg's annual "Ocena presji i
polowow wedkarskich" report. Nothing here fetches anything.

**This is the only measured CPUE the project has.** Law 3 makes fish-per-hour
the unit of success, and until this landed there was nothing to compare
anything against - no logged session, no calibration, no way to know whether
the scoring engine beats guessing.

Three things it is not, all of which have to travel with it:

  * **kg per angler-day, not fish per hour.** Comparable between waters and
    between seasons; not the same quantity `mean_cpue` computes from the
    notebook. The two must never be averaged together.
  * **A voluntary sample.** Only anglers who returned a register are in it,
    and there are often fewer than thirty. `anglers` is the sample size and
    law 5 says it is shown wherever the number is.
  * **One season.** It describes 2024, not what a water "is".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.discover import pzw

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "catch_reports"


@dataclass(frozen=True)
class RegisteredCatch:
    """One water's registered catch for one season."""

    name: str
    key: str
    year: int
    okreg: str
    kg_per_angler_day: float
    anglers: int | None = None
    days_per_angler: float | None = None
    kg_per_angler_year: float | None = None
    species_pct: dict[str, float] = field(default_factory=dict)
    species_mean_kg: dict[str, float] = field(default_factory=dict)

    @property
    def top_species(self) -> tuple[str, float] | None:
        """The species with the largest share, if any share is recorded."""
        if not self.species_pct:
            return None
        slug = max(self.species_pct, key=lambda s: self.species_pct[s])
        return (slug, self.species_pct[slug])


def _load_file(path: Path) -> list[RegisteredCatch]:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    year = int(raw.get("year") or 0)
    okreg = str(raw.get("okreg") or path.stem)
    out: list[RegisteredCatch] = []
    for row in raw.get("waters") or []:
        if not isinstance(row, dict):
            continue
        rate = row.get("kg_per_angler_day")
        key = str(row.get("key") or "")
        if not key or not isinstance(rate, int | float):
            continue
        out.append(
            RegisteredCatch(
                name=str(row.get("name") or key),
                key=key,
                year=year,
                okreg=okreg,
                kg_per_angler_day=float(rate),
                anglers=int(row["anglers"]) if isinstance(row.get("anglers"), int) else None,
                days_per_angler=(
                    float(row["days_per_angler"])
                    if isinstance(row.get("days_per_angler"), int | float)
                    else None
                ),
                kg_per_angler_year=(
                    float(row["kg_per_angler_year"])
                    if isinstance(row.get("kg_per_angler_year"), int | float)
                    else None
                ),
                species_pct={
                    str(k): float(v)
                    for k, v in (row.get("species_pct") or {}).items()
                    if isinstance(v, int | float)
                },
                species_mean_kg={
                    str(k): float(v)
                    for k, v in (row.get("species_mean_kg") or {}).items()
                    if isinstance(v, int | float)
                },
            )
        )
    return out


@lru_cache(maxsize=1)
def reports() -> tuple[RegisteredCatch, ...]:
    """Every registered-catch record from every committed report."""
    if not CONFIG_DIR.is_dir():
        return ()
    out: list[RegisteredCatch] = []
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        out.extend(_load_file(path))
    return tuple(out)


def for_keys(keys: list[str], year: int | None = None) -> RegisteredCatch | None:
    """The record for a water known by any of these names.

    Refuses an ambiguous match, exactly as `pzw.lookup` does and for the same
    reason: showing one water's measured catch on another water's page would
    be a fabricated observation with a citation attached, which is worse than
    showing nothing.
    """
    candidates = [r for r in reports() if year is None or r.year == year]
    normalised = [pzw.normalise(k) for k in keys if k]
    normalised = [k for k in normalised if k]
    if not normalised:
        return None

    exact = [r for r in candidates if r.key in normalised]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None

    fuzzy = [r for r in candidates if any(pzw.keys_match(k, r.key) for k in normalised)]
    if len(fuzzy) != 1:
        return None
    return fuzzy[0]


def newest_for_keys(keys: list[str]) -> RegisteredCatch | None:
    """The most recent season's record for this water."""
    years = sorted({r.year for r in reports()}, reverse=True)
    for year in years:
        found = for_keys(keys, year=year)
        if found is not None:
            return found
    return None
