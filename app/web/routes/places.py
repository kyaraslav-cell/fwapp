from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import COOKIE_NAME, normalise
from app.core.models import Lake
from app.core.time import parse_iso, to_display, utcnow
from app.features.season import derive_season
from app.geo import service as geo_service
from app.ingest.open_meteo import ingest_forecast
from app.notebook import water_type as water_type_mod
from app.notebook.sessions import METHODS, active_session, lake_stats, start_session
from app.predict.daily import generate_predictions, latest_prediction
from app.rules.loader import load_active_ruleset
from app.rules.zone_score import _percentile_normalise, score_cells
from app.web import bite_view
from app.web.deps import (
    CurrentUser,
    current_user,
    get_db,
    get_lake,
    get_lake_by_slug,
    require_user,
    templates,
)
from app.web.view_helpers import current_conditions, prediction_view
from app.web.weather_table import current_reading, recent_days

router = APIRouter()


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


@router.get("/places/new")
def new_place(
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        "place_new.html", {"request": request, "active_nav": "home"}
    )


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

    outline = geo_service.ensure_outline(db, lake)
    grid = geo_service.get_grid(lake, outline)

    default_wind = None
    if conditions and conditions.get("wind_direction_10m") is not None:
        default_wind = conditions["wind_direction_10m"]
    elif days and days[0]["wind_dir"] is not None:
        default_wind = days[0]["wind_dir"]

    ruleset = load_active_ruleset()
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
            "now_wx": now_wx,
            "days_json": json.dumps(days),
            "outline_json": json.dumps(outline),
            "outline_source": lake.outline_source or "unknown",
            "grid_meta": json.dumps(
                {
                    "origin_lat": grid.origin_lat,
                    "origin_lon": grid.origin_lon,
                    "cell_m": grid.cell_m,
                    "n_rows": grid.n_rows,
                    "n_cols": grid.n_cols,
                }
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
    db: Session = Depends(get_db),
):
    """Per-cell provisional zone scores for one wind direction and phase."""
    lake = get_lake_by_slug(db, slug)
    outline = geo_service.ensure_outline(db, lake)
    grid = geo_service.get_grid(lake, outline)
    inputs = geo_service.get_geometry_inputs(lake, outline, grid, wind_dir)

    ruleset = load_active_ruleset()

    if bite_view.supports_bite_model(ruleset):
        view = bite_view.build(db, lake, ruleset)
        raw = bite_view.zone_scores(
            db, lake, ruleset, inputs, view,
            float(ruleset["zone_score"].get("margin_band_m", 25.0)),
            float(ruleset["zone_score"].get("max_possible_fetch_m", 400.0)),
        )
        # Percentile display is a presentation transform and is shared with
        # v0.3 on purpose - colour still means "better than other spots on this
        # lake today", never "good fishing".
        scored = _percentile_normalise(raw) if raw else []
        phase_used = view.phase.phase
        if not scored:
            # No water temperature, so the three-factor model has nothing to
            # say. Fall back to the v0.3 geometry-only score rather than
            # publish a blank lake - the Pages build starts from an empty
            # database every run, so a failed ingest would otherwise ship a map
            # with no colour on it at all.
            #
            # Falling back is only acceptable because the answer SAYS it fell
            # back: `model` names which one produced these cells, and the page
            # must not present the two as the same thing.
            legacy = {"zone_score": ruleset["zone_score"]["fallback"]}
            fallback_phase = derive_season(legacy, to_display(utcnow()).date()).phase
            scored, phase_used = score_cells(legacy, fallback_phase, inputs)
            model_used = "geometry_only_v0.3"
        else:
            model_used = "three_factor_v0.4"
    else:
        if not phase:
            phase = derive_season(ruleset, to_display(utcnow()).date()).phase
        scored, phase_used = score_cells(ruleset, phase, inputs)
        model_used = "geometry_only_v0.3"

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
