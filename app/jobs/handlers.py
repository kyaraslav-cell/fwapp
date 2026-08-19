"""What each kind of job does.

Every handler obeys three rules, because a background worker that breaks them
is a background worker nobody can trust:

1. **Idempotent.** Running it twice does what running it once did. A retry can
   never corrupt what already succeeded.
2. **Declares its prerequisite.** A handler whose input is not ready raises
   `NotReadyYet`, and the queue re-queues it without spending an attempt. A slow
   shoreline must not turn into a red job when nothing is wrong.
3. **Never fabricates.** A failed fetch writes nothing and says so (law 4). The
   page then shows a gap, which is the truth, rather than a plausible number.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.models import Job, Lake
from app.geo import service as geo_service
from app.geo.grid import polygon_area_ha
from app.geo.outline import fetch_osm_outline_strict
from app.ingest.archive import backfill
from app.ingest.open_meteo import ingest_forecast
from app.predict.daily import generate_predictions

logger = logging.getLogger("fishlog.jobs")

OUTLINE = "outline"
WEATHER = "weather_backfill"
FORECAST = "forecast"
GRID = "grid"

# The order a newly discovered water is built in. Outline first because the grid
# needs it; weather before forecast because the pressure norm needs history.
NEW_WATER_PIPELINE = (OUTLINE, WEATHER, FORECAST, GRID)

# One year, not the archive module's default three. The pressure norm needs
# 8760 hours and no more, and a new water should be usable today.
BACKFILL_YEARS = 1


class NotReadyYet(RuntimeError):
    """The prerequisite has not landed. Not an error - come back later."""


def _lake(db: Session, job: Job) -> Lake:
    if job.lake_id is None:
        raise RuntimeError(f"job {job.id} ({job.kind}) has no lake")
    lake = db.get(Lake, job.lake_id)
    if lake is None:
        raise RuntimeError(f"job {job.id} points at lake {job.lake_id}, which is gone")
    return lake


def handle_outline(db: Session, job: Job) -> str:
    """Fetch the shoreline from OpenStreetMap, by location.

    By location rather than by name on purpose: plenty of small waters are
    mapped with a shape and no `name` tag, so a name lookup would report them
    unmapped. Nominatim has already told us *where*; Overpass answers *what*.

    No circle fallback. A water with no polygon keeps its satellite map and
    gets no overlay - see ADR 0005 §4.
    """
    lake = _lake(db, job)
    if lake.outline_geojson:
        return "already had an outline"

    # Strict: a timeout must be retried, an empty answer must not. Collapsing
    # the two marks a mapped lake as unmapped forever over one bad minute.
    # `OverpassUnavailableError` is deliberately not caught - the runner turns
    # it into a backed-off retry, which is exactly the wanted behaviour.
    outline = fetch_osm_outline_strict(lake.centroid_lat, lake.centroid_lon)
    if outline is None:
        # Overpass answered and there is no polygon there. That is a fact about
        # the water, not a failure of this job, so it is recorded and the retry
        # loop stops. The monthly refresh will look again.
        lake.outline_source = "none"
        return "no water polygon in OpenStreetMap near this point"

    lake.outline_geojson = json.dumps(outline)
    lake.outline_source = "osm"
    area = polygon_area_ha(outline)
    if area:
        lake.area_ha = round(area, 2)
    lake.grid_cell_m = geo_service.cell_size_for_area(lake.area_ha)
    return f"outline stored, {lake.area_ha} ha, {lake.grid_cell_m} m cells"


def handle_weather(db: Session, job: Job) -> str:
    """A year of hourly pressure, so the water has a norm of its own.

    `backfill` is already resumable and already records gaps rather than
    inventing hours, so re-running it is safe and repairs a partial run.
    """
    lake = _lake(db, job)
    rows = backfill(db, lake, years=BACKFILL_YEARS)
    return f"{rows} archive hours written"


def handle_forecast(db: Session, job: Job) -> str:
    """Current forecast, then the predictions the day strip reads."""
    lake = _lake(db, job)
    written = ingest_forecast(db, lake)
    predictions = generate_predictions(db, lake)
    return f"{written} forecast hours, {len(predictions)} predictions"


def handle_grid(db: Session, job: Job) -> str:
    """Build the grid and warm the fetch fields the overlay needs.

    Waits for the outline: without a polygon there is nothing to clip a grid
    to, and a grid over a bounding box would put cells on dry land.
    """
    lake = _lake(db, job)
    if not lake.outline_geojson:
        if lake.outline_source == "none":
            return "no outline for this water, so no grid"
        raise NotReadyYet("waiting for the outline")

    outline = json.loads(lake.outline_geojson)
    cell_m = lake.grid_cell_m or geo_service.cell_size_for_area(lake.area_ha)
    lake.grid_cell_m = cell_m
    grid = geo_service.get_grid(lake, outline, cell_m=cell_m)
    return f"grid built: {grid.n_rows}x{grid.n_cols}, {len(grid.cells)} cells at {cell_m} m"


HANDLERS: dict[str, Callable[[Session, Job], str]] = {
    OUTLINE: handle_outline,
    WEATHER: handle_weather,
    FORECAST: handle_forecast,
    GRID: handle_grid,
}
