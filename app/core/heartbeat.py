"""Dead man's switch: ping an outside service, let it raise the alarm.

`app/web/health.py` answers "is this app still doing its job?" to whoever
asks. Nobody asks. A machine that slept, lost power or had its process killed
serves no `/health` at all, and a `/health` nobody polls is a light in an empty
room.

So this inverts it: the app pings healthchecks.io on a schedule, and that
service raises the alarm when the pings stop. A program cannot report its own
death - anything sent on the way out assumes it got the chance.

**What it sends is the health verdict, not a pulse.** That distinction is the
whole point here and it is what makes this different from the same feature in
the other two apps. For a mail watcher, "the process is alive" is the answer.
For this app it is not: the dangerous failure is APScheduler's ingest job dying
while uvicorn keeps serving pages built from last Tuesday's weather. Every page
renders, the day strip shows colours, and it is all describing last week. A
liveness ping would report green through the entire failure.

Therefore:

    status ok      -> ping the check. Fresh weather, doing its job.
    anything else  -> ping /fail. The process is alive and that is exactly
                      the problem worth being woken for.

With FISHLOG_HEALTHCHECK_URL unset nothing here runs and nothing leaves the
machine, which is how every other optional integration in this app behaves.

The body is counts only - status, age, gaps. A healthcheck ends up in logs and
other people's dashboards, and none of those need to know which waters anyone
fishes. Same reasoning as the `/health` endpoint it reads from.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.core.db import session_scope
from app.web import health as health_mod

logger = logging.getLogger("fishlog.heartbeat")

# Short. A heartbeat that hangs holds an APScheduler worker, and a late ping is
# worth nothing anyway - the check's grace period is what absorbs a slow
# network, not this.
TIMEOUT_SECONDS = 10.0

# Said once on the way down and once on the way back, rather than every five
# minutes. A day of network trouble should not bury the ingest log.
_QUIET_AFTER = 3

# Two plainly typed module globals rather than one dict. A dict of mixed value
# types infers as `int | None`, which makes every read of it a mypy error under
# --strict - the counter cannot be incremented and the status cannot hold a
# string. Separate names cost nothing and type themselves.
_misses: int = 0
_last_status: str | None = None


def _url() -> str | None:
    value = os.environ.get("FISHLOG_HEALTHCHECK_URL", "").strip()
    return value or None


def is_configured() -> bool:
    """Whether anything outside this machine will hear from us.

    Exists so startup can say so out loud. "Switched off" and "configured and
    working" were indistinguishable from outside this module, and that is the
    shape the 2026-09-09 fault took: the URL sat in `.env`, `docker-compose.yml`
    did not pass it through, the container read an empty string, and the app
    reported nothing about a monitor that was never running.
    """
    return _url() is not None


def _summary(h: health_mod.Health) -> str:
    age = "?" if h.age_hours is None else f"{h.age_hours} h"
    return f"status {h.status}, newest observation {age}, unresolved gaps {h.unresolved_gaps}"


def _post(url: str, body: str) -> bool:
    """Send one ping. Never raises: a monitor must not break the monitored."""
    try:
        httpx.post(
            url,
            content=body.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            timeout=TIMEOUT_SECONDS,
        )
        return True
    except Exception:  # noqa: BLE001 - see docstring
        return False


def beat() -> None:
    """One heartbeat. Safe to call from a scheduler; swallows everything.

    Reading the database can fail too, and that failure is itself worth
    reporting rather than hiding - `health.check` already turns it into the
    "unknown" status, so it arrives as a /fail with a reason rather than as
    silence indistinguishable from a dead machine.
    """
    url = _url()
    if not url:
        return

    try:
        with session_scope() as db:
            h = health_mod.check(db)
        body = _summary(h)
        healthy = h.status == "ok"
    except Exception as exc:  # noqa: BLE001
        body = f"heartbeat could not read health: {type(exc).__name__}"
        healthy = False

    sent = _post(url if healthy else url.rstrip("/") + "/fail", body)

    global _misses, _last_status

    if sent:
        if _misses >= _QUIET_AFTER:
            logger.info("heartbeat: monitoring reachable again")
        _misses = 0
        # Only on change: a healthy app says nothing, a newly stale one says so
        # once, and recovery is visible in the log rather than inferred.
        status = "ok" if healthy else "fail"
        if _last_status != status:
            logger.info("heartbeat: reported %s - %s", status, body)
            _last_status = status
    else:
        _misses += 1
        if _misses == _QUIET_AFTER:
            logger.warning("heartbeat: cannot reach the monitor (%d attempts)", _QUIET_AFTER)


def report_failure(reason: str) -> None:
    """Report a crash on the way out, so the alarm is immediate.

    Best effort by definition - a process being killed outright never reaches
    this, which is exactly why the scheduled ping above is the real mechanism
    and this is only a way to shorten the wait when there happens to be time.
    """
    url = _url()
    if not url:
        return
    _post(url.rstrip("/") + "/fail", reason)
