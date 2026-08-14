from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.time import parse_iso, to_display
from app.notebook.sessions import list_sessions
from app.web.deps import get_db, get_lake, templates

router = APIRouter()


@router.get("/history")
def history(request: Request, db: Session = Depends(get_db)):
    lake = get_lake(db)
    summaries = list_sessions(db, lake)

    rows = []
    for s in summaries:
        started = to_display(parse_iso(s.session.started_at))
        rows.append(
            {
                "started": started.strftime("%a %d %b, %H:%M"),
                "effort_minutes": s.session.effort_minutes,
                "total_fish": s.total_fish,
                "cpue": s.cpue,
                "is_blank": bool(s.session.is_blank),
                "reflection": s.session.reflection,
            }
        )

    n_sessions = len(rows)
    n_blanks = sum(1 for r in rows if r["is_blank"])

    return templates.TemplateResponse(
        "history.html",
        {"request": request, "rows": rows, "n_sessions": n_sessions, "n_blanks": n_blanks},
    )
