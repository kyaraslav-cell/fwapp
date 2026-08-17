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
from app.notebook.sessions import METHODS, active_session, lake_stats, start_session
from app.predict.daily import generate_predictions, latest_prediction
from app.rules.loader import load_active_ruleset
from app.rules.zone_score import score_cells
from app.web.deps import get_db, get_lake, get_lake_by_slug, templates
from app.web.view_helpers import current_conditions, prediction_view
from app.web.weather_table import current_reading, recent_days

router = APIRouter()


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    get_lake(db)  # ensure Pomocnia (and species) are seeded
    lakes = db.execute(select(Lake).order_by(Lake.name)).scalars().all()

    cards = []
    for lk in lakes:
        view = prediction_view(latest_prediction(db, lk, horizon=0))
        n_sessions, last_visited = lake_stats(db, lk)
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
            }
        )

    return templates.TemplateResponse(
        "home.html", {"request": request, "cards": cards, "active_nav": "home"}
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
def new_place(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "place_new.html", {"request": request, "active_nav": "home"}
    )


@router.get("/lake/{slug}")
def lake_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    lake = get_lake_by_slug(db, slug)
    # Deliberately NOT redirecting to an in-progress session: conditions and
    # the map are exactly what you want to check while you are sitting there
    # fishing. The banner offers the way back instead.
    live_session = active_session(db, lake)

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
    season = derive_season(ruleset, to_display(utcnow()).date())

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
    if not phase:
        phase = derive_season(ruleset, to_display(utcnow()).date()).phase
    scored, phase_used = score_cells(ruleset, phase, inputs)

    return JSONResponse(
        {
            "origin_lat": grid.origin_lat,
            "origin_lon": grid.origin_lon,
            "cell_m": grid.cell_m,
            "n_rows": grid.n_rows,
            "n_cols": grid.n_cols,
            "wind_dir": wind_dir,
            "phase": phase_used,
            "cells": [[r, c, v] for r, c, v in scored],
        }
    )


@router.post("/lake/{slug}/refresh")
def refresh_lake(slug: str, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
):
    lake = get_lake_by_slug(db, slug)
    if active_session(db, lake) is not None:
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
    db: Session = Depends(get_db),
):
    lake = get_lake_by_slug(db, slug)
    if method not in METHODS:
        raise HTTPException(status_code=400, detail="unknown method")
    rod_count = max(1, min(6, rod_count))

    if active_session(db, lake) is None:
        pred = latest_prediction(db, lake, horizon=0)
        start_session(
            db,
            lake,
            pred,
            method=method,
            rod_count=rod_count,
            grid_cell=cell or None,
            grid_lat=lat,
            grid_lon=lon,
        )
    return RedirectResponse(url="/session/active", status_code=303)
