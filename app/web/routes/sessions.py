from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.models import Catch
from app.notebook.sessions import (
    ALL_SPECIES,
    SPECIES_PRIMARY,
    SPECIES_SECONDARY,
    active_session,
    add_catch,
    end_session,
)
from app.web.deps import get_db, get_lake, templates

router = APIRouter(prefix="/session")


@router.get("/active")
def active(request: Request, db: Session = Depends(get_db)):
    lake = get_lake(db)
    session = active_session(db, lake)
    if session is None:
        return RedirectResponse(url="/")

    catches = (
        db.query(Catch).filter(Catch.session_id == session.id).order_by(Catch.id.desc()).all()
    )
    total_fish = sum(c.count for c in catches)

    return templates.TemplateResponse(
        "session_active.html",
        {
            "request": request,
            "session": session,
            "catches": catches,
            "total_fish": total_fish,
            "species_primary": SPECIES_PRIMARY,
            "species_secondary": SPECIES_SECONDARY,
            "active_nav": "",
        },
    )


@router.post("/catch")
def catch(species: str = Form(...), db: Session = Depends(get_db)):
    lake = get_lake(db)
    session = active_session(db, lake)
    if session is None:
        return RedirectResponse(url="/", status_code=303)
    if species not in ALL_SPECIES:
        return RedirectResponse(url="/session/active", status_code=303)
    add_catch(db, session.id, species)
    return RedirectResponse(url="/session/active", status_code=303)


@router.get("/end")
def end_form(request: Request, db: Session = Depends(get_db)):
    lake = get_lake(db)
    session = active_session(db, lake)
    if session is None:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        "session_end.html", {"request": request, "session": session, "active_nav": ""}
    )


@router.post("/end")
def end(
    is_blank: str = Form(default=""),
    reflection: str = Form(default=""),
    water_temp_measured_c: str = Form(default=""),
    water_clarity_cm: str = Form(default=""),
    db: Session = Depends(get_db),
):
    lake = get_lake(db)
    session = active_session(db, lake)
    if session is None:
        return RedirectResponse(url="/", status_code=303)

    def _float_or_none(s: str) -> float | None:
        try:
            return float(s) if s.strip() else None
        except ValueError:
            return None

    end_session(
        db,
        session,
        is_blank=bool(is_blank),
        reflection=reflection or None,
        water_temp_measured_c=_float_or_none(water_temp_measured_c),
        water_clarity_cm=_float_or_none(water_clarity_cm),
    )
    return RedirectResponse(url="/history", status_code=303)
