"""Rate limiting for the sign-in and registration forms.

Until now the only defence against password guessing was that
`app/auth/passwords.py` makes one verification cost about half a second of CPU
(ADR 0004, and `docs/10 §5` item 8 has carried "build it before this is on a
public URL" ever since). Half a second is a real cost to somebody guessing one
password at a time and no cost at all to somebody opening forty connections —
and it is a cost *this* server pays as well, so a guessing attack doubles as a
denial of service against the angler trying to log a fish in the rain.

Two consequences shape everything here:

**The limit is checked before the hash is verified.** A refused attempt must be
cheap for us and expensive for them. Checking afterwards would still spend the
scrypt work on every rejected guess, which is the half of the problem that
actually hurts.

**Three windows, not one.** A single counter can only be wrong in one of two
directions:

| Counter | Stops | Fails against |
|---|---|---|
| email + IP together | the ordinary flood: one machine, one account | anyone who changes either |
| email alone | a distributed guess at one known account | nothing, but see below |
| IP alone | spraying one common password across many addresses | a botnet |

The reason email+IP exists at all, and is the tight one, is that a *tight* limit
on the email alone is a weapon: type someone's address wrongly five times and
they cannot sign in for a quarter of an hour. So the pair is tight (5), the
address alone is loose (20 over an hour, which no honest angler reaches and no
prankster can drive from one machine without hitting the pair limit first), and
the address-alone window only ever catches a genuinely distributed attempt.

Successes clear the failures for that address, so an angler who mistypes four
times and then gets it right starts again from zero rather than carrying a
nearly-full counter into next week.

Registration is limited by IP only: there is no prior identity to key on, and
the thing being rationed is rows in the database rather than guesses at a
secret.

The clock is passed in, as everywhere else in `app/auth/`, so every window here
is testable without waiting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.orm import Session

from app.auth.validation import normalise_email
from app.core.models import LoginAttempt
from app.core.time import iso, parse_iso, utcnow

LOGIN_FAIL = "login_fail"
REGISTER = "register"


@dataclass(frozen=True)
class Rule:
    """One counter: how many of `kind`, keyed on what, over how long.

    `by` names the columns the count is grouped on. It is data rather than
    three near-identical functions so that the reason a sign-in was refused can
    be reported as one of these rows, and so a fourth window is a line here.
    """

    name: str
    kind: str
    by: tuple[str, ...]
    limit: int
    window: timedelta


# Sign-in. Tight on the pair, loose on either half alone - see the module
# docstring for why that asymmetry is the whole design.
LOGIN_RULES: tuple[Rule, ...] = (
    Rule("pair", LOGIN_FAIL, ("email", "ip"), limit=5, window=timedelta(minutes=15)),
    Rule("email", LOGIN_FAIL, ("email",), limit=20, window=timedelta(hours=1)),
    Rule("ip", LOGIN_FAIL, ("ip",), limit=30, window=timedelta(minutes=15)),
)

# Account creation. One angler and their family is a handful; anything past
# that from one address in an hour is a script.
REGISTER_RULES: tuple[Rule, ...] = (
    Rule("ip", REGISTER, ("ip",), limit=5, window=timedelta(hours=1)),
)

# Nothing is kept longer than the longest window it could still count in, plus
# a margin so a clock adjustment cannot prune a row that is still live.
RETENTION = timedelta(hours=2)


@dataclass(frozen=True)
class Decision:
    """Whether to let this attempt through, and if not, for how long.

    `retry_after` is seconds until the *oldest* attempt in the window falls out
    of it, which is the earliest moment the counter can drop below the limit.
    It is what the form tells the angler, so it must never be a guess.
    """

    allowed: bool
    rule: str = ""
    retry_after: int = 0

    @property
    def retry_after_minutes(self) -> int:
        """Rounded up: "try again in 0 minutes" is worse than no number."""
        return max(1, -(-self.retry_after // 60))


def _matches(
    rule: Rule, email: str | None, ip: str | None
) -> list[ColumnElement[bool]]:
    """The where-clause for one rule, or an empty list if it cannot apply."""
    clauses: list[ColumnElement[bool]] = [LoginAttempt.kind == rule.kind]
    for column in rule.by:
        value = email if column == "email" else ip
        if not value:
            # A rule keyed on something this request does not have cannot
            # count anything. Returning no clauses would silently widen it to
            # "every attempt ever", which would lock out the whole world the
            # first time a proxy hid the client address.
            return []
        clauses.append(getattr(LoginAttempt, column) == value)
    return clauses


def _count_and_oldest(
    db: Session, rule: Rule, email: str | None, ip: str | None, now: datetime
) -> tuple[int, datetime | None]:
    clauses = _matches(rule, email, ip)
    if not clauses:
        return 0, None
    since = iso(now - rule.window)
    row = db.execute(
        select(func.count(), func.min(LoginAttempt.created_at))
        .select_from(LoginAttempt)
        .where(*clauses, LoginAttempt.created_at >= since)
    ).one()
    count = int(row[0] or 0)
    oldest = parse_iso(str(row[1])) if row[1] else None
    return count, oldest


def check(
    db: Session,
    rules: tuple[Rule, ...],
    *,
    email: str | None = None,
    ip: str | None = None,
    now: datetime | None = None,
) -> Decision:
    """May this attempt proceed? Call before spending any real work on it."""
    now = now or utcnow()
    address = normalise_email(email) if email else None
    for rule in rules:
        count, oldest = _count_and_oldest(db, rule, address, ip, now)
        if count >= rule.limit and oldest is not None:
            wait = (oldest + rule.window) - now
            return Decision(
                allowed=False,
                rule=rule.name,
                retry_after=max(1, int(wait.total_seconds())),
            )
    return Decision(allowed=True)


def record(
    db: Session,
    kind: str,
    *,
    email: str | None = None,
    ip: str | None = None,
    now: datetime | None = None,
) -> None:
    """Write one attempt, and take the chance to prune old ones.

    Pruning here rather than on a timer keeps the table bounded without another
    scheduled job, and it costs one indexed delete on a path that is already
    doing a write. A quiet server never prunes, and a quiet server has nothing
    to prune.
    """
    now = now or utcnow()
    db.add(
        LoginAttempt(
            kind=kind,
            email=normalise_email(email) if email else None,
            ip=ip,
            created_at=iso(now),
        )
    )
    db.flush()
    purge(db, now)


def clear_failures(
    db: Session, email: str, *, now: datetime | None = None
) -> int:
    """A correct password wipes that address's failures.

    Only this address's rows, so signing in to an account you own does not
    also clear the failures your IP has accumulated against other people's.
    """
    result = db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.kind == LOGIN_FAIL,
            LoginAttempt.email == normalise_email(email),
        )
    )
    return int(result.rowcount or 0)


def purge(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    result = db.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < iso(now - RETENTION))
    )
    return int(result.rowcount or 0)
