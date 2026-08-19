"""What a collected fact is, and what disqualifies one. Pure - no I/O, no clock.

The whole module exists to be strict about a single thing: **a claim with no
source is not a fact.** A language model asked about a small Polish lake will
happily produce a paragraph about its bream fishing whether or not it has ever
seen a word about that lake, and the paragraph reads exactly like one that is
true. The source URL is the only thing that makes the difference checkable by
the owner, so a claim arriving without one is dropped here rather than stored
with an empty column that later gets read as "source unknown".

That is law 4 applied one level out. `weather_hourly` is a record of what was
actually published; `water_fact` is a record of what somebody actually wrote
about this water. Neither is a place for something plausible.

What is deliberately *not* here: anything numeric that could reach the score.
Topics are fixed, and a "weight", "coefficient" or "score" topic has no way in -
ADR 0005 §2, and the reason is that a per-water constant invented by a model
makes the calibration loop unable to attribute a miss to anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

# The only topics that can be stored. A fact under any other topic is dropped:
# an open vocabulary here would be the crack through which a "recommended
# depth multiplier" eventually arrives.
TOPICS: tuple[str, ...] = (
    "species",   # which fish are in it
    "depth",     # maximum and mean depth, shelves, holes
    "bottom",    # silt, gravel, weed, snags
    "access",    # banks, swims, parking, boats
    "rules",     # permits, closed seasons, size limits, night fishing
    "stocking",  # what is put in, and when
)

CONFIDENCE = ("high", "medium", "low")

MAX_VALUE_CHARS = 300
MAX_KEY_CHARS = 60


@dataclass(frozen=True)
class Fact:
    """One claim about one water, with the page it came from.

    `value` is prose because that is what the sources are. Nothing downstream
    parses it - it is shown to the angler, who is the one who decides whether
    a claim about their own lake is true.
    """

    topic: str
    key: str
    value: str
    source_url: str
    source_title: str
    confidence: str


class RejectedFact(RuntimeError):
    """Why one item in the model's answer was not stored."""


def is_usable_source(url: str) -> bool:
    """An http(s) URL with a host. Nothing else counts as a citation.

    Not a check that the page exists or says what it is claimed to say - that
    needs the network, and `app/intel/gemini.py` marks each URL reachable or
    not separately. This is only the shape.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.netloc.split("@")[-1].split(":")[0]
    return "." in host and not host.endswith(".")


def _clean(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit].strip()


def parse_fact(raw: Any) -> Fact:
    """One item of the model's JSON -> a Fact, or `RejectedFact` saying why."""
    if not isinstance(raw, dict):
        raise RejectedFact("not an object")

    topic = _clean(raw.get("topic"), MAX_KEY_CHARS).lower()
    if topic not in TOPICS:
        raise RejectedFact(f"topic {topic!r} is not one of {', '.join(TOPICS)}")

    key = _clean(raw.get("key"), MAX_KEY_CHARS)
    value = _clean(raw.get("value"), MAX_VALUE_CHARS)
    if not key or not value:
        raise RejectedFact("empty key or value")

    source_url = _clean(raw.get("source_url"), 500)
    if not is_usable_source(source_url):
        # The one rule this module exists for.
        raise RejectedFact(f"no usable source for {topic}/{key}")

    confidence = _clean(raw.get("confidence"), 10).lower()
    if confidence not in CONFIDENCE:
        # An unstated confidence is the lowest one, never the highest. A model
        # that omits the field is not thereby more certain.
        confidence = "low"

    return Fact(
        topic=topic,
        key=key,
        value=value,
        source_url=source_url,
        source_title=_clean(raw.get("source_title"), 200) or urlparse(source_url).netloc,
        confidence=confidence,
    )


def parse_facts(payload: Any) -> tuple[list[Fact], list[str]]:
    """The whole answer -> the facts worth keeping, and why the rest were not.

    Both halves are returned because the rejections are the interesting half
    when this misbehaves: "12 claims, 11 with no source" is a diagnosis, and a
    silently short list is not.
    """
    if not isinstance(payload, dict):
        return [], ["answer was not a JSON object"]

    items = payload.get("facts")
    if not isinstance(items, list):
        return [], ["answer carried no 'facts' list"]

    kept: list[Fact] = []
    rejected: list[str] = []
    seen: set[tuple[str, str]] = set()
    for raw in items:
        try:
            fact = parse_fact(raw)
        except RejectedFact as exc:
            rejected.append(str(exc))
            continue
        identity = (fact.topic, fact.key.lower())
        if identity in seen:
            rejected.append(f"duplicate {fact.topic}/{fact.key}")
            continue
        seen.add(identity)
        kept.append(fact)
    return kept, rejected
