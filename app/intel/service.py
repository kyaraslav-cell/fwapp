"""Storing collected facts, and reading them back for the page.

One rule shapes the writing: **a refresh supersedes, it never overwrites.**
A fact that changed and a fact that was withdrawn look identical if the old row
is updated in place, and the difference matters - a lake that quietly stopped
being stocked is exactly the kind of thing the angler wants to notice. So a new
pass stamps `superseded_at` on the previous rows and inserts fresh ones.

That is not law 2 (which is about `prediction` rows and is stricter), but it is
the same instinct: keep the evidence of what was believed, and when.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.models import WaterFact
from app.core.time import iso, utcnow
from app.intel.facts import TOPICS, Fact


def _standing(db: Session, lake_id: int, lang: str) -> list[WaterFact]:
    conditions = [WaterFact.lake_id == lake_id, WaterFact.superseded_at.is_(None)]
    if lang == "en":
        # NULL is a row written before translation existed (`app/core/models.py`).
        conditions.append(or_(WaterFact.lang == "en", WaterFact.lang.is_(None)))
    else:
        conditions.append(WaterFact.lang == lang)
    return list(db.execute(select(WaterFact).where(*conditions)).scalars().all())


def current_facts(db: Session, lake_id: int, lang: str = "en") -> list[WaterFact]:
    """Everything still standing for this water, in this language, topic order.

    Falls back to English when `lang` has nothing: a translation pass can fail
    on its own (`app/jobs/handlers.py`) while the English collection succeeds,
    and a Russian-reading angler seeing the English facts beats seeing none.

    Topic order rather than insertion order so the section reads the same way
    every time: what is in it, then how deep, then what the bottom is, then how
    to get at it, then what the rules are.
    """
    rows = _standing(db, lake_id, lang)
    if not rows and lang != "en":
        rows = _standing(db, lake_id, "en")
    order = {topic: i for i, topic in enumerate(TOPICS)}
    rows.sort(key=lambda r: (order.get(r.topic, len(TOPICS)), r.key.lower()))
    return rows


def facts_by_topic(
    db: Session, lake_id: int, lang: str = "en"
) -> OrderedDict[str, list[WaterFact]]:
    grouped: OrderedDict[str, list[WaterFact]] = OrderedDict()
    for row in current_facts(db, lake_id, lang):
        grouped.setdefault(row.topic, []).append(row)
    return grouped


def supersede_all(db: Session, lake_id: int, now: datetime | None = None) -> int:
    now = now or utcnow()
    result = db.execute(
        update(WaterFact)
        .where(WaterFact.lake_id == lake_id, WaterFact.superseded_at.is_(None))
        .values(superseded_at=iso(now))
    )
    return int(result.rowcount or 0)


def store(
    db: Session,
    lake_id: int,
    facts: list[Fact],
    *,
    model: str,
    source_ok: dict[str, bool] | None = None,
    now: datetime | None = None,
) -> int:
    """Replace this water's standing facts with a new pass.

    An empty pass still supersedes. "The last look found nothing" is a real
    answer about a small pond, and leaving last month's claims standing would
    quietly present them as this month's.
    """
    now = now or utcnow()
    checked = source_ok or {}
    supersede_all(db, lake_id, now)
    for fact in facts:
        ok = checked.get(fact.source_url)
        db.add(
            WaterFact(
                lake_id=lake_id,
                topic=fact.topic,
                key=fact.key,
                value=fact.value,
                source_url=fact.source_url,
                source_title=fact.source_title,
                source_ok=None if ok is None else int(ok),
                confidence=fact.confidence,
                lang=fact.lang,
                model=model,
                collected_at=iso(now),
                verified_by_owner=0,
            )
        )
    db.flush()
    return len(facts)
