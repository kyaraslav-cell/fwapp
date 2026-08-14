from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import FishSession, Lake, Zone
from app.core.time import parse_iso, to_display, utcnow
from app.features.wind import wind_exposure
from app.ingest.open_meteo import ingest_forecast
from app.notebook.sessions import METHODS, active_session, lake_stats, start_session
from app.predict.daily import generate_predictions, latest_prediction
from app.web.deps import get_db, get_lake, get_lake_by_slug, templates
from app.web.view_helpers import current_conditions, outlook_view, prediction_view

router = APIRouter()


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    get_lake(db)  # ensure Pomocnia (and its demo zones) are seeded
    lakes = db.execute(select(Lake).order_by(Lake.name)).scalars().all()

    cards = []
    for lk in lakes:
        pred = latest_prediction(db, lk, horizon=0)
        view = prediction_view(pred)
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
        "home.html",
        {"request": request, "cards": cards, "active_nav": "home"},
    )


@router.get("/places/new")
def new_place(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "place_new.html", {"request": request, "active_nav": "home"}
    )


@router.get("/lake/{slug}")
def lake_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    lake = get_lake_by_slug(db, slug)
    active = active_session(db, lake)
    if active is not None:
        return RedirectResponse(url="/session/active")

    pred = latest_prediction(db, lake, horizon=0)
    view = prediction_view(pred)
    outlook = outlook_view(db, lake, days=5, latest_prediction_fn=latest_prediction)
    conditions = current_conditions(db, lake)

    zones = db.execute(
        select(Zone).where(Zone.lake_id == lake.id, Zone.is_active == 1).order_by(Zone.id)
    ).scalars().all()

    zone_session_counts: dict[int, int] = {}
    for zid, count in db.execute(
        select(FishSession.zone_id, func.count())
        .where(FishSession.lake_id == lake.id, FishSession.ended_at.is_not(None))
        .group_by(FishSession.zone_id)
    ).all():
        if zid is not None:
            zone_session_counts[zid] = count

    zone_payload = []
    for z in zones:
        exposure = None
        if (
            conditions
            and conditions.get("wind_direction_10m") is not None
            and z.bank_aspect_deg is not None
        ):
            exposure = wind_exposure(z.bank_aspect_deg, conditions["wind_direction_10m"])
        zone_payload.append(
            {
                "id": z.id,
                "name": z.name,
                "polygon": json.loads(z.polygon_geojson) if z.polygon_geojson else None,
                "bank_aspect_deg": z.bank_aspect_deg,
                "wind_exposure": exposure,
                "is_demo": bool(z.access_notes and "DEMO ZONE" in z.access_notes),
                "n_sessions": zone_session_counts.get(z.id, 0),
            }
        )

    return templates.TemplateResponse(
        "lake_detail.html",
        {
            "request": request,
            "lake": lake,
            "prediction": view,
            "outlook": outlook,
            "conditions": conditions,
            "zones": zone_payload,
            "zones_json": json.dumps(zone_payload),
            "now_local": to_display(utcnow()).strftime("%a %d %b, %H:%M"),
            "active_nav": "home",
        },
    )


@router.post("/lake/{slug}/refresh")
def refresh_lake(slug: str, db: Session = Depends(get_db)):
    lake = get_lake_by_slug(db, slug)
    ingest_forecast(db, lake)
    generate_predictions(db, lake)
    return RedirectResponse(url=f"/lake/{slug}", status_code=303)


@router.get("/lake/{slug}/zone/{zone_id}/start")
def zone_start_form(slug: str, zone_id: int, request: Request, db: Session = Depends(get_db)):
    lake = get_lake_by_slug(db, slug)
    if active_session(db, lake) is not None:
        return RedirectResponse(url="/session/active")
    zone = db.get(Zone, zone_id)
    if zone is None or zone.lake_id != lake.id:
        raise HTTPException(status_code=404, detail="zone not found")
    return templates.TemplateResponse(
        "zone_start.html",
        {"request": request, "lake": lake, "zone": zone, "methods": METHODS, "active_nav": "home"},
    )


@router.post("/lake/{slug}/zone/{zone_id}/start")
def zone_start_submit(
    slug: str,
    zone_id: int,
    method: str = Form(...),
    rod_count: int = Form(...),
    db: Session = Depends(get_db),
):
    lake = get_lake_by_slug(db, slug)
    zone = db.get(Zone, zone_id)
    if zone is None or zone.lake_id != lake.id:
        raise HTTPException(status_code=404, detail="zone not found")
    if method not in METHODS:
        raise HTTPException(status_code=400, detail="unknown method")
    rod_count = max(1, min(6, rod_count))

    if active_session(db, lake) is None:
        pred = latest_prediction(db, lake, horizon=0)
        start_session(db, lake, pred, zone_id=zone.id, method=method, rod_count=rod_count)
    return RedirectResponse(url="/session/active", status_code=303)
