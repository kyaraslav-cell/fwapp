from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import COOKIE_NAME, normalise
from app.core.models import Lake
from app.core.time import parse_iso, to_display, utcnow
from app.features.season import derive_season
from app.geo import hires_cache
from app.geo import service as geo_service
from app.geo.thumbnail import outline_thumbnail_path
from app.ingest.open_meteo import ingest_forecast
from app.intel import service as intel_service
from app.notebook import registered_catch
from app.notebook import water_type as water_type_mod
from app.notebook.sessions import METHODS, active_session, lake_stats, start_session
from app.notebook.species import list_species
from app.predict.daily import OUTLOOK_DAYS, generate_predictions, latest_prediction
from app.rules.loader import load_active_ruleset
from app.web import bite_view
from app.web.build_status import status_for
from app.web.deps import (
    CurrentUser,
    current_user,
    get_db,
    get_lake,
    get_lake_by_slug,
    require_user,
    templates,
)
from app.web.view_helpers import calendar_view, current_conditions, prediction_view
from app.web.weather_table import current_reading, forecast_day_summaries, recent_days

router = APIRouter()


def water_outline(db: Session, lake: Lake) -> dict[str, Any] | None:
    """This water's shoreline, or None if it has not got one.

    Only the seeded lake may fall back to the circle approximation: it has a
    committed, eyeballed polygon and the fallback is a hedge for a network
    failure. For a discovered water the same fallback would be an invented
    shoreline nobody has ever looked at, so it returns None and the page shows
    a satellite map with no overlay (ADR 0005 §4).
    """
    if lake.origin == "seed":
        return geo_service.ensure_outline(db, lake)
    if lake.outline_geojson:
        loaded: dict[str, Any] = json.loads(lake.outline_geojson)
        return loaded
    return None


@router.get("/")
def home(request: Request, water: str = "", db: Session = Depends(get_db)):
    """Places, optionally filtered to one kind of water.

    The filter lives here and nowhere else. Once you have picked a water you
    are on it, and the distinction stops being a choice - so it does not follow
    you into the lake page or a live session, where it would be one more thing
    between the angler and the fish.
    """
    get_lake(db)  # ensure Pomocnia (and species) are seeded
    lakes = db.execute(select(Lake).order_by(Lake.name)).scalars().all()

    # Signed in: your own sessions. Signed out (and the published read-only
    # build, which has no cookie): everything on the water, exactly as before
    # accounts existed. Counts only - no CPUE is shown here.
    viewer = current_user(request)
    viewer_id = viewer.id if viewer else None

    selected = water_type_mod.normalise(water)
    if selected is not None:
        lakes = [lk for lk in lakes if water_type_mod.normalise(lk.water_type) == selected]

    cards = []
    for lk in lakes:
        view = prediction_view(latest_prediction(db, lk, horizon=0))
        n_sessions, last_visited = lake_stats(db, lk, user_id=viewer_id)
        # Reuses the same outline every lake page already draws on its map -
        # no extra fetch, just a local file/DB read (`water_outline` above).
        outline = water_outline(db, lk)
        cards.append(
            {
                "slug": lk.slug,
                "name": lk.name,
                "n_sessions": n_sessions,
                "last_visited": (
                    to_display(parse_iso(last_visited)).strftime("%d %b %Y")
                    if last_visited
                    else "Not visited yet"
                ),
                "band_color": view["band_color"] if view else None,
                "band_label": view["band_label"] if view else None,
                "water_type": water_type_mod.normalise(lk.water_type),
                "thumb_path": outline_thumbnail_path(outline) if outline else None,
            }
        )

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "cards": cards,
            "active_nav": "home",
            "water_filter": selected or "",
        },
    )


@router.get("/lang/{code}")
def set_language(code: str, next: str = "/"):
    """Switch UI language and return to where the angler was."""
    lang = normalise(code)
    # Only ever redirect to a path on this app, never to an absolute URL.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(url=target, status_code=303)
    response.set_cookie(
        COOKIE_NAME, lang, max_age=60 * 60 * 24 * 365, httponly=False, samesite="lax"
    )
    return response


@router.get("/lake/{slug}")
def lake_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    lake = get_lake_by_slug(db, slug)
    viewer = current_user(request)
    # Deliberately NOT redirecting to an in-progress session: conditions and
    # the map are exactly what you want to check while you are sitting there
    # fishing. The banner offers the way back instead.
    live_session = active_session(db, lake, user_id=viewer.id) if viewer else None

    conditions = current_conditions(db, lake)
    days = recent_days(db, lake, days=5)
    now_wx = current_reading(db, lake)

    # A discovered water may have no outline yet, or never get one. Only the
    # seeded lake is allowed the circle approximation - see ADR 0005 §4.
    build = status_for(db, lake)

    # Matched on every name this water is known by - the register uses the
    # okreg's spelling, the lake may be stored under OSM's.
    registered = registered_catch.newest_for_keys(
        [k for k in (lake.pzw_key, lake.name, lake.name_osm) if k]
    )
    registered_species = None
    if registered is not None and registered.top_species is not None:
        slug, share = registered.top_species
        named = next((sp for sp in list_species(db) if sp.slug == slug), None)
        if named is not None:
            lang = normalise(request.cookies.get(COOKIE_NAME))
            registered_species = (named.name_pl if lang == "pl" else named.name_en, share)
    outline = water_outline(db, lake)
    grid = (
        geo_service.get_grid(
            lake, outline, cell_m=geo_service.cell_size_for_area(lake.area_ha)
        )
        if outline
        else None
    )

    default_wind = None
    if conditions and conditions.get("wind_direction_10m") is not None:
        default_wind = conditions["wind_direction_10m"]
    elif days and days[0]["wind_dir"] is not None:
        default_wind = days[0]["wind_dir"]

    ruleset = load_active_ruleset()

    # The day strip. Bands come from stored prediction rows and are never
    # recomputed here (law 2); the per-day wind is what the map re-scores with
    # when a day is picked. The regime scores are passed in so the sentence
    # under the strip can say how the ruleset rates that day's pressure without
    # anyone writing that ranking down a second time.
    calendar_days = calendar_view(
        db,
        lake,
        OUTLOOK_DAYS,
        latest_prediction,
        forecast_day_summaries(db, lake, OUTLOOK_DAYS),
        regime_scores=next(
            (r for r in ruleset["rules"] if r["id"] == "pressure_trend"), {}
        ).get("regime_scores", {}),
    )

    zone_cfg = ruleset["zone_score"]

    # Thermal phase from modelled water temperature when the active ruleset
    # supports it, and only then falling back to the calendar stand-in that
    # ADR 0001 §5 forbids. Feature-detected rather than version-checked so a
    # rollback needs no code change.
    view = bite_view.build(db, lake, ruleset) if bite_view.supports_bite_model(ruleset) else None
    season = view.phase if view is not None else derive_season(
        ruleset, to_display(utcnow()).date()
    )

    return templates.TemplateResponse(
        "lake_detail.html",
        {
            "request": request,
            "lake": lake,
            "live_session": live_session,
            "season": season,
            "conditions": conditions,
            "days": days,
            "calendar_days": calendar_days,
            "now_wx": now_wx,
            "days_json": json.dumps(days),
            "outline_json": json.dumps(outline) if outline else "null",
            "outline_source": lake.outline_source or "unknown",
            # Collected local knowledge. Empty for almost every water, which is
            # the honest state and renders as nothing at all rather than as an
            # empty section announcing its own emptiness.
            "intel": intel_service.facts_by_topic(
                db, lake.id, normalise(request.cookies.get(COOKIE_NAME))
            ),
            # What other anglers actually caught here, from the okreg's own
            # register. Measured, unlike everything else on this page - and
            # carrying its sample size, which is often under thirty (law 5).
            "registered": registered,
            "registered_species": registered_species,
            "build": build,
            "grid_meta": json.dumps(
                {
                    "origin_lat": grid.origin_lat,
                    "origin_lon": grid.origin_lon,
                    "cell_m": grid.cell_m,
                    "n_rows": grid.n_rows,
                    "n_cols": grid.n_cols,
                }
                if grid
                else {}
            ),
            "default_wind": default_wind if default_wind is not None else "null",
            "zone_provenance": zone_cfg["provenance"],
            "display_cfg": json.dumps(zone_cfg["display"]),
            "methods": METHODS,
            "now_local": to_display(utcnow()).strftime("%a %d %b, %H:%M"),
            "active_nav": "home",
            # Live serving answers /grid itself; only the static build overrides
            # these (see tools/build_static.py).
            "static_grid": None,
            "static_grid_step": 30,
        },
    )


@router.get("/lake/{slug}/grid")
def lake_grid(
    slug: str,
    wind_dir: float = 270.0,
    phase: str = "",
    horizon: int = 0,
    db: Session = Depends(get_db),
):
    """Per-cell provisional zone scores for one wind direction and phase.

    `horizon` is the day strip's own horizon (0 = today) - the only thing
    that tells this route whether a cached hi-res grid (`docs/09-BACKLOG.md
    §19c`) is even allowed to answer. A forecast day always recomputes on
    demand: the background job only ever scores today.
    """
    lake = get_lake_by_slug(db, slug)
    outline = water_outline(db, lake)
    if outline is None:
        # No shoreline, no overlay. An empty cell list rather than an error:
        # the map is working, it simply has nothing to colour, and the page
        # already says why.
        return JSONResponse(
            {"cells": [], "model": "no_outline", "wind_dir": wind_dir, "phase": phase},
            status_code=200,
        )

    if horizon == 0:
        cached = hires_cache.fetch(db, lake.id, to_display(utcnow()).date().isoformat())
        if cached is not None:
            return JSONResponse(cached)

    grid = geo_service.get_grid(
        lake, outline, cell_m=geo_service.cell_size_for_area(lake.area_ha)
    )
    inputs = geo_service.get_geometry_inputs(lake, outline, grid, wind_dir)

    ruleset = load_active_ruleset()
    scored, phase_used, model_used = bite_view.score_grid_cells(
        db, lake, ruleset, inputs, wind_dir, phase
    )

    return JSONResponse(
        {
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
    )


@router.post("/lake/{slug}/refresh")
def refresh_lake(
    slug: str,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake_by_slug(db, slug)
    ingest_forecast(db, lake)
    generate_predictions(db, lake)
    return RedirectResponse(url=f"/lake/{slug}", status_code=303)


@router.get("/lake/{slug}/spot")
def spot_start_form(
    slug: str,
    request: Request,
    lat: float,
    lon: float,
    cell: str = "",
    score: float | None = None,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake_by_slug(db, slug)
    if active_session(db, lake, user_id=user.id) is not None:
        return RedirectResponse(url="/session/active")
    return templates.TemplateResponse(
        "spot_start.html",
        {
            "request": request,
            "lake": lake,
            "lat": lat,
            "lon": lon,
            "cell": cell,
            "score": score,
            "methods": METHODS,
            "active_nav": "home",
        },
    )


@router.post("/lake/{slug}/spot")
def spot_start_submit(
    slug: str,
    lat: float = Form(...),
    lon: float = Form(...),
    cell: str = Form(default=""),
    method: str = Form(...),
    rod_count: int = Form(...),
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake_by_slug(db, slug)
    if method not in METHODS:
        raise HTTPException(status_code=400, detail="unknown method")
    rod_count = max(1, min(6, rod_count))

    if active_session(db, lake, user_id=user.id) is None:
        pred = latest_prediction(db, lake, horizon=0)
        start_session(
            db,
            lake,
            pred,
            user_id=user.id,
            method=method,
            rod_count=rod_count,
            grid_cell=cell or None,
            grid_lat=lat,
            grid_lon=lon,
        )
    return RedirectResponse(url="/session/active", status_code=303)
