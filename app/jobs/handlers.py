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
from app.core.time import to_display, utcnow
from app.geo import hires_cache
from app.geo import service as geo_service
from app.geo.grid import polygon_area_ha
from app.geo.outline import fetch_osm_outline_strict
from app.ingest.archive import backfill
from app.ingest.open_meteo import ingest_forecast
from app.intel import gemini
from app.intel import service as intel_service
from app.predict.daily import generate_predictions
from app.rules.loader import load_active_ruleset
from app.web import bite_view
from app.web.view_helpers import current_conditions
from app.web.weather_table import recent_days

logger = logging.getLogger("fishlog.jobs")

OUTLINE = "outline"
WEATHER = "weather_backfill"
FORECAST = "forecast"
GRID = "grid"
INTEL = "intel"
# Not in NEW_WATER_PIPELINE: this is a recurring daily refresh keyed to
# *today*, not a one-time build step for a newly added water - see its own
# scheduler entry in app/ingest/scheduler.py and docs/09-BACKLOG.md §19c.
GRID_HIRES = "grid_hires"

# The order a newly discovered water is built in. Outline first because the grid
# needs it; weather before forecast because the pressure norm needs history.
# Intel last: it is the only step nothing else waits on, and the only one that
# costs money, so it runs after the water is already usable.
NEW_WATER_PIPELINE = (OUTLINE, WEATHER, FORECAST, GRID, INTEL)

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
    # By OSM id when the geocoder gave one: it is the object the angler
    # actually picked, and it makes the whole proximity question - and its
    # radius - go away. The area is the fallback's radius hint.
    outline = fetch_osm_outline_strict(
        lake.centroid_lat,
        lake.centroid_lon,
        osm_type=lake.osm_type,
        osm_id=lake.osm_id,
        area_ha=lake.area_ha,
    )
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


def _todays_wind_dir(db: Session, lake: Lake) -> float | None:
    """The same "wind right now, or the next best thing" the lake page itself
    falls back through when picking a default - see `lake_detail` in
    `app/web/routes/places.py`. Kept in sync deliberately: the background job
    and the live page should agree on what "today's wind" means.
    """
    conditions = current_conditions(db, lake)
    if conditions is not None and conditions.get("wind_direction_10m") is not None:
        wind: float = conditions["wind_direction_10m"]
        return wind
    days = recent_days(db, lake, days=1)
    if days and days[0]["wind_dir"] is not None:
        wind_fallback: float = days[0]["wind_dir"]
        return wind_fallback
    return None


def handle_grid_hires(db: Session, job: Job) -> str:
    """Once a day, a finer grid for one large water's TODAY conditions only.

    Docs/09-BACKLOG.md §19c: big waters get coarse cells from
    `geo_service.cell_size_for_area` because the interactive endpoint has to
    stay cheap on every request. This runs once, in the background, and
    caches the result (`app/geo/hires_cache.py`) for `/lake/{slug}/grid` to
    serve on every request for today without recomputing - see that route.

    Skips small waters outright rather than queuing pointless work: a lake
    below the hi-res threshold gets nothing finer to compute in the first
    place.
    """
    lake = _lake(db, job)
    hires_cell_m = geo_service.hires_cell_size_for_area(lake.area_ha)
    if hires_cell_m is None:
        return "below the hi-res size threshold, skipped"

    if not lake.outline_geojson:
        if lake.outline_source == "none":
            return "no outline for this water, so no hi-res grid"
        raise NotReadyYet("waiting for the outline")

    outline = json.loads(lake.outline_geojson)
    grid = geo_service.get_grid(lake, outline, cell_m=hires_cell_m)

    wind_dir = _todays_wind_dir(db, lake)
    if wind_dir is None:
        raise NotReadyYet("waiting for today's weather")

    inputs = geo_service.get_geometry_inputs(lake, outline, grid, wind_dir)
    ruleset = load_active_ruleset()
    scored, phase_used, model_used = bite_view.score_grid_cells(
        db, lake, ruleset, inputs, wind_dir
    )

    for_date = to_display(utcnow()).date().isoformat()
    payload = {
        "origin_lat": grid.origin_lat,
        "origin_lon": grid.origin_lon,
        "cell_m": grid.cell_m,
        "n_rows": grid.n_rows,
        "n_cols": grid.n_cols,
        "wind_dir": wind_dir,
        "phase": phase_used,
        "model": model_used,
        "cells": [[r, c, v] for r, c, v in scored],
    }
    hires_cache.store(
        db, lake.id, for_date, hires_cell_m, wind_dir, phase_used, model_used, payload
    )
    return (
        f"hi-res grid cached for {for_date}: {grid.n_rows}x{grid.n_cols}, "
        f"{len(grid.cells)} cells at {hires_cell_m} m"
    )


def handle_intel(db: Session, job: Job) -> str:
    """Collect what is publicly documented about this water, or say why not.

    Three things this deliberately does *not* do.

    It does not fail when there is no API key. A missing key is a deployment
    that has not switched this on, not a broken water, and a red job on the
    lake page would tell the angler something is wrong when nothing is.

    It does not fail when the answer is empty. Most small waters have nothing
    written about them, and "nothing found" is the correct answer for those -
    turning it into an error would push the next retry towards inventing
    something.

    It does not touch the score. Facts land in `water_fact` marked unverified
    and stay out of every ranking until a human confirms them (ADR 0005 §2).

    Collected once, in English, then translated rather than re-researched per
    language (`app/intel/gemini.py`) - the site switches between three
    languages (`app/core/i18n.py`) and every one of them must show the same
    claims from the same sources, not a second independent lookup that could
    drift. A translation that fails for one language is not this job failing -
    `intel_service.current_facts` falls back to English for a viewer in that
    language rather than showing nothing.
    """
    lake = _lake(db, job)
    config = gemini.load_config()
    if config is None:
        return "no Gemini API key configured, skipped"

    collection = gemini.collect(
        config, name=lake.name, lat=lake.centroid_lat, lon=lake.centroid_lon
    )
    all_facts = list(collection.facts)
    translated_counts: dict[str, int] = {}
    for lang, language_name in gemini.TRANSLATABLE_LANGUAGES:
        try:
            translated = gemini.translate_facts(
                config, collection.facts, lang, language_name
            )
        except gemini.GeminiError as exc:
            logger.info(
                "intel translation to %s failed for %s: %s", lang, lake.slug, exc
            )
            translated = []
        translated_counts[lang] = len(translated)
        all_facts.extend(translated)

    stored = intel_service.store(
        db,
        lake.id,
        all_facts,
        model=collection.model,
        source_ok=collection.source_ok,
    )
    if collection.rejected:
        # Kept in the job row rather than only in the log: "11 of 12 claims had
        # no source" is the diagnosis when this feature starts misbehaving, and
        # a short list of facts on the page looks the same either way.
        logger.info(
            "intel for %s dropped %d claims: %s",
            lake.slug,
            len(collection.rejected),
            "; ".join(collection.rejected[:10]),
        )
    unreachable = sum(1 for ok in collection.source_ok.values() if not ok)
    detail = (
        f"{stored} facts stored ({len(collection.facts)} en, "
        + ", ".join(f"{n} {lang}" for lang, n in translated_counts.items())
        + ")"
    )
    if collection.rejected:
        detail += f", {len(collection.rejected)} dropped"
    if unreachable:
        detail += f", {unreachable} source(s) did not answer"
    return detail


HANDLERS: dict[str, Callable[[Session, Job], str]] = {
    OUTLINE: handle_outline,
    WEATHER: handle_weather,
    FORECAST: handle_forecast,
    GRID: handle_grid,
    GRID_HIRES: handle_grid_hires,
    INTEL: handle_intel,
}
