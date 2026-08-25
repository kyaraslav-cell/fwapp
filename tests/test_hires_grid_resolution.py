"""The size-gated hi-res resolution tier (docs/09-BACKLOG.md §19c).

Pure arithmetic, no DB, no I/O - `hires_cell_size_for_area` extends
`cell_size_for_area`'s existing area-based scaling, so both are exercised
side by side here.
"""

from __future__ import annotations

from app.geo import service as geo


def test_a_small_lake_is_below_the_hires_threshold() -> None:
    """Pomocnia, 9 ha: the interactive grid is already fine (5 m), so the
    background tier has nothing to add and must say so with None."""
    assert geo.hires_cell_size_for_area(9.0) is None


def test_unknown_area_is_treated_as_small() -> None:
    """A water with no measured area yet is never the large-water case this
    tier exists for - it must not be guessed into a background job."""
    assert geo.hires_cell_size_for_area(None) is None


def test_a_large_lake_gets_a_finer_cell_than_the_interactive_grid() -> None:
    """Zalew Zegrzynski, 2046.8 ha: the interactive endpoint coarsens to 64 m
    (docs/09-BACKLOG.md §19c); the daily background tier must do better."""
    interactive = geo.cell_size_for_area(2046.8)
    hires = geo.hires_cell_size_for_area(2046.8)

    assert hires is not None
    assert hires < interactive


def test_hires_resolution_is_clamped() -> None:
    tiny_above_threshold = geo.hires_cell_size_for_area(geo.HIRES_AREA_THRESHOLD_HA)
    huge = geo.hires_cell_size_for_area(1_000_000.0)

    assert tiny_above_threshold is not None
    assert geo.HIRES_MIN_CELL_M <= tiny_above_threshold <= geo.HIRES_MAX_CELL_M
    assert huge == geo.HIRES_MAX_CELL_M


def test_hires_resolution_grows_coarser_with_area() -> None:
    small = geo.hires_cell_size_for_area(geo.HIRES_AREA_THRESHOLD_HA)
    large = geo.hires_cell_size_for_area(geo.HIRES_AREA_THRESHOLD_HA * 20)

    assert small is not None and large is not None
    assert small <= large
