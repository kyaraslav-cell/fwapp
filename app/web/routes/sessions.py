from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import Catch, FishSession
from app.media import images
from app.notebook.sessions import (
    active_session,
    add_catch,
    delete_catch,
    end_session,
    update_catch,
)
from app.notebook.species import favourite_species, list_species
from app.web.deps import CurrentUser, get_db, get_lake, require_user, templates

router = APIRouter(prefix="/session")

ALLOWED_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def owned_catch(db: Session, user: CurrentUser, catch_id: int) -> Catch:
    """Fetch a catch, or 404 if it is not this angler's.

    Without this, `/session/catch/17/edit` is an id anyone signed in can type,
    and the notebook stops being private the moment there is a second account.
    404 rather than 403 on purpose: 403 confirms the catch exists.
    """
    catch_row = db.get(Catch, catch_id)
    if catch_row is None:
        raise HTTPException(status_code=404, detail="catch not found")
    session = db.get(FishSession, catch_row.session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="catch not found")
    return catch_row


def _float_or_none(s: str) -> float | None:
    try:
        return float(s.replace(",", ".")) if s.strip() else None
    except ValueError:
        return None


def _int_or_none(s: str) -> int | None:
    value = _float_or_none(s)
    return int(value) if value is not None else None


async def _save_photo(photo: UploadFile | None) -> str | None:
    """Store a catch photo - re-encoded, oriented, and without its EXIF.

    The bytes that arrive are never the bytes written (ADR 0006). The filename
    check stays, because refusing obvious rubbish before decoding it is free,
    but it is a *filename* - the decode is what actually decides. Every stored
    photo is a `.jpg`, whatever was uploaded.
    """
    if photo is None or not photo.filename:
        return None
    suffix = Path(photo.filename).suffix.lower()
    if suffix not in ALLOWED_PHOTO_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"unsupported image type: {suffix}")

    data = await photo.read()
    if len(data) > MAX_PHOTO_BYTES:
        # The cap now bounds what is *accepted*; what is kept is far smaller.
        raise HTTPException(status_code=400, detail="photo larger than 8 MB")

    try:
        stored = images.process(data)
    except images.UnsupportedImageError:
        # An iPhone photo this build cannot decode. Saying so beats storing a
        # file the angler's own browser will refuse to display.
        raise HTTPException(
            status_code=400,
            detail="this server cannot read HEIC photos - send a JPEG",
        ) from None
    except images.NotAnImageError:
        raise HTTPException(status_code=400, detail="that file is not an image") from None

    media_dir = get_settings().media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}{images.OUTPUT_SUFFIX}"
    (media_dir / name).write_bytes(stored)
    return f"/media/{name}"


@router.get("/active")
def active(
    request: Request,
    q: str = "",
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake(db)
    session = active_session(db, lake, user_id=user.id)
    if session is None:
        return RedirectResponse(url="/")

    catches = (
        db.query(Catch).filter(Catch.session_id == session.id).order_by(Catch.id.desc()).all()
    )
    total_fish = sum(c.count for c in catches)
    all_species = list_species(db)

    return templates.TemplateResponse(
        "session_active.html",
        {
            "request": request,
            "session": session,
            "catches": catches,
            "total_fish": total_fish,
            "favourites": favourite_species(db),
            "all_species": all_species,
            "search_results": list_species(db, q) if q.strip() else [],
            "shapes": {s.slug: s.shape for s in all_species},
            "colors": {s.slug: s.color for s in all_species},
            "names": {s.slug: s.name_en for s in all_species},
            "q": q,
            "lake_slug": lake.slug,
            "active_nav": "",
        },
    )


@router.post("/catch")
async def catch(
    species: str = Form(...),
    weight_g: str = Form(default=""),
    length_cm: str = Form(default=""),
    bait: str = Form(default=""),
    notes: str = Form(default=""),
    photo: UploadFile | None = File(default=None),
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake(db)
    session = active_session(db, lake, user_id=user.id)
    if session is None:
        return RedirectResponse(url="/", status_code=303)

    valid = {s.slug for s in list_species(db)}
    if species not in valid:
        return RedirectResponse(url="/session/active", status_code=303)

    add_catch(
        db,
        session.id,
        species,
        weight_g=_int_or_none(weight_g),
        length_cm=_float_or_none(length_cm),
        bait=bait or None,
        notes=notes or None,
        photo_path=await _save_photo(photo),
    )
    return RedirectResponse(url="/session/active", status_code=303)


@router.get("/catch/{catch_id}/edit")
def edit_catch_form(
    catch_id: int,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    catch_row = owned_catch(db, user, catch_id)
    species = list_species(db)
    current = next((s for s in species if s.slug == catch_row.species), None)
    return templates.TemplateResponse(
        "catch_edit.html",
        {
            "request": request,
            "catch": catch_row,
            "species": species,
            "current": current,
            "active_nav": "",
        },
    )


@router.post("/catch/{catch_id}/edit")
async def edit_catch(
    catch_id: int,
    species: str = Form(...),
    weight_g: str = Form(default=""),
    length_cm: str = Form(default=""),
    bait: str = Form(default=""),
    notes: str = Form(default=""),
    photo: UploadFile | None = File(default=None),
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    catch_row = owned_catch(db, user, catch_id)
    update_catch(
        db,
        catch_row,
        species=species,
        weight_g=_int_or_none(weight_g),
        length_cm=_float_or_none(length_cm),
        bait=bait or None,
        notes=notes or None,
        photo_path=await _save_photo(photo),
    )
    return RedirectResponse(url="/session/active", status_code=303)


@router.post("/catch/{catch_id}/delete")
def remove_catch(
    catch_id: int,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    delete_catch(db, owned_catch(db, user, catch_id))
    return RedirectResponse(url="/session/active", status_code=303)


@router.get("/end")
def end_form(
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake(db)
    session = active_session(db, lake, user_id=user.id)
    if session is None:
        return RedirectResponse(url="/")
    n_catches = db.query(Catch).filter(Catch.session_id == session.id).count()
    return templates.TemplateResponse(
        "session_end.html",
        {
            "request": request,
            "session": session,
            "n_catches": n_catches,
            "active_nav": "",
        },
    )


@router.post("/end")
def end(
    reflection: str = Form(default=""),
    water_temp_measured_c: str = Form(default=""),
    water_clarity_cm: str = Form(default=""),
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake(db)
    session = active_session(db, lake, user_id=user.id)
    if session is None:
        return RedirectResponse(url="/", status_code=303)

    end_session(
        db,
        session,
        reflection=reflection or None,
        water_temp_measured_c=_float_or_none(water_temp_measured_c),
        water_clarity_cm=_float_or_none(water_clarity_cm),
    )
    return RedirectResponse(url="/history", status_code=303)
