from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.time import parse_iso, to_display, utcnow
from app.ingest.open_meteo import ingest_forecast
from app.notebook.sessions import active_session
from app.predict.daily import generate_predictions, latest_prediction
from app.web.deps import get_db, get_lake, templates

router = APIRouter()


def _prediction_view(pred) -> dict | None:
    if pred is None:
        return None
    payload = json.loads(pred.payload_json)
    best_hours = []
    for w in payload["best_hours"]:
        start = to_display(parse_iso(w["start"])).strftime("%H:%M")
        end = to_display(parse_iso(w["end"])).strftime("%H:%M")
        best_hours.append(f"{start}–{end}")
    return {
        "day_score": payload["day_score"],
        "go": payload["go"],
        "best_hours": best_hours,
        "reasons": payload["reasons"],
        "pressure_regime": payload.get("pressure_regime"),
    }


@router.get("/")
def root():
    return RedirectResponse(url="/today")


@router.get("/today")
def today(request: Request, db: Session = Depends(get_db)):
    lake = get_lake(db)
    pred = latest_prediction(db, lake, horizon=0)
    active = active_session(db, lake)

    outlook = []
    for h in range(1, 8):
        p = latest_prediction(db, lake, horizon=h)
        if p:
            target = to_display(utcnow() + timedelta(days=h)).strftime("%a %d %b")
            go = json.loads(p.payload_json)["go"]
            outlook.append({"label": target, "day_score": p.day_score, "go": go})

    return templates.TemplateResponse(
        "today.html",
        {
            "request": request,
            "lake": lake,
            "prediction": _prediction_view(pred),
            "active_session": active,
            "outlook": outlook,
            "now_local": to_display(utcnow()).strftime("%a %d %b, %H:%M"),
        },
    )


@router.post("/refresh")
def refresh(db: Session = Depends(get_db)):
    lake = get_lake(db)
    ingest_forecast(db, lake)
    generate_predictions(db, lake)
    return RedirectResponse(url="/today", status_code=303)
