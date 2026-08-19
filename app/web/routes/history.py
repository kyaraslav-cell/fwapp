from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.time import parse_iso, to_display
from app.notebook.sessions import list_sessions
from app.web.deps import CurrentUser, get_db, get_lake, require_user, templates

router = APIRouter()


@router.get("/history")
def history(
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    lake = get_lake(db)
    # One angler's own record. Law 3 again: a CPUE averaged over two people is
    # a different measurement, so history never mixes them.
    summaries = list_sessions(db, lake, user_id=user.id)

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
                "method": s.session.method,
                "rod_count": s.session.rod_count,
            }
        )

    n_sessions = len(rows)
    n_blanks = sum(1 for r in rows if r["is_blank"])

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "rows": rows,
            "n_sessions": n_sessions,
            "n_blanks": n_blanks,
            "active_nav": "history",
        },
    )
