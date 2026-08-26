"""What stage a water is at, for the page to say so.

A newly added water is usable before it is finished: satellite map and a pin
immediately, colours when the weather lands, an overlay when the grid does.
The page has to name that stage, because a page that just looks empty is
indistinguishable from a broken one.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.models import Lake
from app.jobs import queue
from app.jobs.handlers import GRID, OUTLINE

READY = "ready"
PREPARING = "preparing"
NO_OUTLINE = "no_outline"
FAILED = "failed"


@dataclass(frozen=True)
class BuildStatus:
    state: str
    # i18n key for the sentence shown to the angler, or None when ready.
    message_key: str | None
    # True while anything is still queued or running, so the page can poll.
    in_progress: bool


def status_for(db: Session, lake: Lake) -> BuildStatus:
    """Where this water is in its pipeline.

    Pomocnia and anything else seeded predates the pipeline and has no jobs, so
    it is ready by definition - the absence of jobs must never read as "stuck".
    """
    jobs = queue.jobs_for_lake(db, lake.id)
    if not jobs:
        return BuildStatus(READY, None, False)

    pending = [j for j in jobs if j.state in (queue.QUEUED, queue.RUNNING)]
    failed = [j for j in jobs if j.state == queue.FAILED]

    # A water Overpass has no polygon for is finished, not broken. It keeps the
    # satellite map and the forecast; it simply never gets an overlay.
    if lake.outline_source == "none" and not pending:
        return BuildStatus(NO_OUTLINE, "build.no_outline", False)

    if pending:
        waiting_for = pending[0].kind
        if waiting_for == OUTLINE:
            return BuildStatus(PREPARING, "build.outline", True)
        if waiting_for == GRID:
            return BuildStatus(PREPARING, "build.grid", True)
        return BuildStatus(PREPARING, "build.weather", True)

    if failed:
        # Only failures that nothing else made good. A job kind is a *stage*,
        # not an attempt: the intel pass for Zalew Zegrzynski succeeded, was
        # queued a second time, timed out, and the page then told the angler
        # the water had failed to build while sitting on 42 collected facts.
        # A stage counts as failed only if no job of that kind ever finished.
        done_kinds = {j.kind for j in jobs if j.state == queue.DONE}
        unresolved = [j for j in failed if j.kind not in done_kinds]
        if unresolved:
            # Named rather than hidden: a silent failure is why an angler
            # decides the app is broken instead of busy.
            return BuildStatus(FAILED, "build.failed", False)

    return BuildStatus(READY, None, False)
