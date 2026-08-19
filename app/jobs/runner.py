"""Drain the queue, one job at a time.

Called on a timer by APScheduler. Deliberately dull: claim a job, run its
handler, record what happened, commit. Everything interesting is in the
handler; everything about *when* is in `queue.py`.

The whole tick is wrapped so that a handler which raises something nobody
predicted marks its job failed and lets the next tick continue. A background
worker that dies on one bad row stops every water in the queue, and the only
symptom is a page that says "preparing" forever.
"""

from __future__ import annotations

import logging

from app.core.db import session_scope
from app.jobs import queue
from app.jobs.handlers import HANDLERS, NotReadyYet

logger = logging.getLogger("fishlog.jobs.runner")


def run_one() -> str | None:
    """Run at most one due job. Returns a short description, or None if idle."""
    with session_scope() as db:
        queue.release_stale(db)
        job = queue.claim(db)
        if job is None:
            return None
        kind, job_id, lake_id = job.kind, job.id, job.lake_id

        handler = HANDLERS.get(kind)
        if handler is None:
            queue.fail(db, job, f"no handler for job kind '{kind}'")
            logger.error("job %s has unknown kind %r", job_id, kind)
            return f"job {job_id}: unknown kind {kind}"

        try:
            outcome = handler(db, job)
        except NotReadyYet as exc:
            queue.defer(db, job, str(exc))
            logger.info("job %s (%s) deferred: %s", job_id, kind, exc)
            return f"job {job_id} ({kind}) deferred: {exc}"
        except Exception as exc:  # noqa: BLE001 - the point is to survive anything
            # The type is half the information when reading a queue later:
            # "timed out" and "TimeoutError: timed out" cost the same to store,
            # and only one of them says which layer gave up.
            detail = f"{type(exc).__name__}: {exc}"
            queue.fail(db, job, detail)
            logger.warning("job %s (%s) failed: %s", job_id, kind, detail, exc_info=True)
            return f"job {job_id} ({kind}) failed: {detail}"

        queue.finish(db, job)
        logger.info("job %s (%s, lake %s): %s", job_id, kind, lake_id, outcome)
        return f"job {job_id} ({kind}): {outcome}"


def drain(limit: int = 20) -> int:
    """Run due jobs until the queue is empty or `limit` is reached.

    The limit exists so one very full queue cannot hold the scheduler thread
    for an unbounded time; whatever is left is picked up on the next tick.
    """
    done = 0
    while done < limit:
        if run_one() is None:
            break
        done += 1
    return done
