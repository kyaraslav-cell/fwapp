"""Search for a water by name, and add it.

Two routes, and the split between them is the whole design: `GET /places/new`
does one throttled geocoder call and shows a list; `POST /places/new` writes a
row and queues four jobs, then redirects. Neither touches Overpass, the
archive, or the grid - all of that happens in the background, so the angler is
looking at a map of their lake about a second after they pick it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.time import to_display
from app.discover import nominatim, pzw, service
from app.discover.nominatim import Candidate
from app.web.deps import CurrentUser, get_db, require_user, templates

router = APIRouter()


def _render(
    request: Request, *, status_code: int = 200, **context: Any
) -> Response:
    payload: dict[str, Any] = {
        "request": request,
        "active_nav": "home",
        "query": "",
        "candidates": [],
        "error": None,
        "searched": False,
        "suggestions": [],
        "districts": [],
        "quota_left": None,
        "quota_reset": None,
    }
    payload.update(context)
    return templates.TemplateResponse("place_new.html", payload, status_code=status_code)


@router.get("/places/new")
def search_form(
    request: Request,
    q: str = "",
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    quota = service.quota_left(db, user.id)
    reset = service.next_quota_reset(db, user.id)

    query = q.strip()
    if not query:
        return _render(request, quota_left=quota, quota_reset=_local(reset))

    try:
        found = nominatim.search(query)
    except nominatim.NominatimError:
        # The geocoder is a shared community service and it is allowed to say
        # no. Nothing is created, and the angler is told which part failed
        # rather than "something went wrong".
        return _render(
            request,
            status_code=503,
            query=query,
            searched=True,
            error="discover.error.geocoder",
            quota_left=quota,
            quota_reset=_local(reset),
        )

    # Nothing found is usually a spelling, not a missing water. The PZW
    # registry holds 2 000+ Polish water names, which makes it a better
    # dictionary for this than any spell-checker we could ship - so offer its
    # nearest names as a re-search rather than a dead end.
    suggestions = [w.name for w in pzw.suggest(query)] if not found else []

    # PZW cuts a river into numbered districts and each is a separate water
    # with its own permit and its own rules, so they are offered as themselves
    # rather than hidden behind one OSM river that spans all of them.
    districts = [
        {
            "key": w.key,
            "name": w.name,
            "okreg": w.place or w.okreg,
            "existing_slug": (
                found_lake.slug
                if (found_lake := service.find_existing_district(db, w)) is not None
                else None
            ),
        }
        for w in pzw.districts(query)
    ]

    return _render(
        request,
        query=query,
        searched=True,
        candidates=[_row(db, c) for c in found],
        suggestions=suggestions,
        districts=districts,
        quota_left=quota,
        quota_reset=_local(reset),
    )


@router.post("/places/new")
def add(
    request: Request,
    name: str = Form(...),
    display_name: str = Form(default=""),
    lat: float = Form(...),
    lon: float = Form(...),
    osm_type: str = Form(default=""),
    osm_id: int = Form(default=0),
    area_ha: str = Form(default=""),
    is_water: str = Form(default="1"),
    water_type: str = Form(default=""),
    pzw_key: str = Form(default=""),
    q: str = Form(default=""),
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    """Add the chosen water.

    The candidate is rebuilt from the form rather than re-queried: Nominatim
    allows one request a second, and asking it again to learn what it already
    told us thirty seconds ago is exactly the kind of waste that gets an IP
    blocked.
    """
    if pzw_key.strip():
        listed = pzw.by_key(pzw_key.strip())
        if listed is None:
            return _refused(
                request, db, query=q or name, status_code=404,
                error="discover.error.not_water",
                quota_left=service.quota_left(db, user.id),
            )
        try:
            result = service.add_district(db, listed, user_id=user.id)
        except service.QuotaExceededError:
            return _refused(
                request, db, query=q or name, status_code=429,
                error="discover.error.quota", quota_left=0,
                quota_reset=_local(service.next_quota_reset(db, user.id)),
            )
        return RedirectResponse(url=f"/lake/{result.lake.slug}", status_code=303)

    candidate = Candidate(
        name=name.strip(),
        display_name=display_name.strip() or name.strip(),
        lat=lat,
        lon=lon,
        osm_type=osm_type.strip(),
        osm_id=osm_id,
        kind="",
        area_ha=float(area_ha) if area_ha.strip() else None,
        is_water=is_water == "1",
    )

    try:
        result = service.add_water(db, candidate, user_id=user.id, water_type=water_type)
    except service.QuotaExceededError:
        return _refused(
            request,
            db,
            query=q or name,
            status_code=429,
            error="discover.error.quota",
            quota_left=0,
            quota_reset=_local(service.next_quota_reset(db, user.id)),
        )
    except service.NotAWaterError:
        return _refused(
            request,
            db,
            query=q or name,
            status_code=422,
            error="discover.error.not_water",
            quota_left=service.quota_left(db, user.id),
        )

    # Either way the angler lands on the water's page - a duplicate add opens
    # the water that already exists rather than making a second copy of it.
    return RedirectResponse(url=f"/lake/{result.lake.slug}", status_code=303)


def _refused(
    request: Request,
    db: Session,
    *,
    query: str,
    status_code: int,
    error: str,
    **context: Any,
) -> Response:
    """Say no, and leave the list on the screen.

    A refusal used to render with no candidates at all, so being told "that is
    not a water" also took away every other result - including the right one,
    one row further down. The angler's only move was to retype the search.

    Redrawing the list is free: `nominatim.search` caches per process, so this
    is a dictionary lookup and not a second call against a service that allows
    one request a second. If the cache has been lost the search is simply not
    redrawn - a refusal must never become a geocoder error.
    """
    try:
        candidates = [_row(db, c) for c in nominatim.search(query)] if query else []
    except nominatim.NominatimError:
        candidates = []
    return _render(
        request,
        status_code=status_code,
        query=query,
        searched=True,
        error=error,
        candidates=candidates,
        **context,
    )


def _row(db: Session, candidate: Candidate) -> dict[str, Any]:
    """One search result, with whether we already have it and what PZW calls it.

    The registry lookup happens here so the picker can ask the angler for a
    water type only when it does not already know one. A listed water is added
    in one tap, exactly as before; an unlisted one costs one tap more and gets
    an answer nobody had to guess at.
    """
    existing = service.find_existing(db, candidate)
    listed = pzw.lookup(candidate.name)
    return {
        "candidate": candidate,
        "existing_slug": existing.slug if existing is not None else None,
        "pzw_name": listed.water.name if listed is not None else None,
    }


def _local(moment: Any) -> str | None:
    return to_display(moment).strftime("%H:%M") if moment is not None else None
