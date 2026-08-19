"""The job state machine. No domain knowledge, no network, no clock reads.

    queued --claim--> running --ok--> done
                         |
                         +--fail--> queued (backoff)  ... until max attempts
                         +--fail--> failed             (attempts exhausted)

Time is always passed in, so every backoff rule is testable without waiting -
the same discipline `app/rules/` and `app/auth/service.py` follow.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Job
from app.core.time import iso, parse_iso, utcnow

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

MAX_ATTEMPTS = 4
# 30 s, 2 min, 8 min. Long enough that a rate-limited Overpass has actually
# recovered, short enough that a new water is not stuck for an hour.
BACKOFF_BASE_SECONDS = 30
BACKOFF_FACTOR = 4
# A job that claims to be running for longer than this was interrupted - the
# container restarted mid-run - and is offered back to the queue.
STALE_RUNNING_MINUTES = 30


def enqueue(
    db: Session,
    kind: str,
    *,
    lake_id: int | None = None,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
    unique: bool = True,
) -> Job:
    """Add a job, or return the one already waiting.

    `unique` is the default because every caller so far means "make sure this
    water gets an outline", not "fetch it again" - and a queue that grows a
    duplicate every time a page is opened is a queue that never drains.
    """
    now = now or utcnow()
    if unique:
        existing = db.execute(
            select(Job).where(
                Job.kind == kind,
                Job.lake_id == lake_id,
                Job.state.in_((QUEUED, RUNNING)),
            )
        ).scalars().first()
        if existing is not None:
            return existing

    job = Job(
        lake_id=lake_id,
        kind=kind,
        state=QUEUED,
        attempts=0,
        run_after=iso(now),
        payload_json=json.dumps(payload) if payload else None,
        created_at=iso(now),
    )
    db.add(job)
    db.flush()
    return job


def release_stale(db: Session, now: datetime | None = None) -> int:
    """Put interrupted jobs back in the queue.

    A container that dies mid-job leaves a row marked running forever. Without
    this the water it belonged to never finishes and nothing says why.
    """
    now = now or utcnow()
    cutoff = now - timedelta(minutes=STALE_RUNNING_MINUTES)
    stale = db.execute(select(Job).where(Job.state == RUNNING)).scalars().all()
    released = 0
    for job in stale:
        started = parse_iso(job.started_at) if job.started_at else None
        if started is None or started <= cutoff:
            job.state = QUEUED
            job.started_at = None
            job.last_error = "interrupted, requeued"
            released += 1
    return released


def claim(db: Session, now: datetime | None = None) -> Job | None:
    """Take the oldest job that is due, or None.

    One at a time on purpose: this is a single container talking to services
    that rate-limit by IP, so parallelism would only reach the limit sooner.
    """
    now = now or utcnow()
    job = db.execute(
        select(Job)
        .where(Job.state == QUEUED, Job.run_after <= iso(now))
        .order_by(Job.run_after, Job.id)
        .limit(1)
    ).scalars().first()
    if job is None:
        return None
    job.state = RUNNING
    job.started_at = iso(now)
    job.attempts += 1
    db.flush()
    return job


def finish(db: Session, job: Job, now: datetime | None = None) -> None:
    now = now or utcnow()
    job.state = DONE
    job.finished_at = iso(now)
    job.last_error = None


def defer(db: Session, job: Job, reason: str, now: datetime | None = None) -> None:
    """Not an error: the job's prerequisite is not ready yet.

    `grid` needs an outline. If Overpass is slow, the grid job must wait rather
    than fail - otherwise a slow shoreline turns into a red job the angler has
    to be told about, when nothing is actually wrong.
    """
    now = now or utcnow()
    job.state = QUEUED
    job.started_at = None
    job.last_error = reason
    # Deferrals do not count against the attempt budget.
    job.attempts = max(0, job.attempts - 1)
    job.run_after = iso(now + timedelta(seconds=BACKOFF_BASE_SECONDS))


def fail(db: Session, job: Job, error: str, now: datetime | None = None) -> None:
    """Record the failure and either back off or give up - visibly, either way."""
    now = now or utcnow()
    job.last_error = error[:2000]
    if job.attempts >= MAX_ATTEMPTS:
        job.state = FAILED
        job.finished_at = iso(now)
        return
    delay = BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR ** (job.attempts - 1))
    job.state = QUEUED
    job.started_at = None
    job.run_after = iso(now + timedelta(seconds=delay))


def jobs_for_lake(db: Session, lake_id: int) -> list[Job]:
    return list(
        db.execute(
            select(Job).where(Job.lake_id == lake_id).order_by(Job.id)
        ).scalars().all()
    )


def payload_of(job: Job) -> dict[str, Any]:
    if not job.payload_json:
        return {}
    loaded: dict[str, Any] = json.loads(job.payload_json)
    return loaded
