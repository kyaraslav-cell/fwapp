"""Is this water on the PZW permit, and what does the permit call it?

Reads `config/pzw/*.yaml` - the okreg's own published list of waters its permit
covers, extracted offline by `tools/pzw_extract.py` and committed. Nothing here
fetches anything; the list changes once a season and a runtime dependency on a
club website would fail closed at exactly the wrong moment.

Two questions, both asked when a water is added:

  * **water type.** `pzw` is not a label, it is the segmentation key for every
    CPUE aggregate (law 3, and `app/notebook/water_type.py`). Getting it wrong
    silently corrupts the only measurement the project exists to make, so a
    guess is worse than a blank: this module answers only when it is sure, and
    the add form asks the angler when it is not.
  * **name.** The okreg's spelling is what is printed on the permit, so it is
    what the app shows. OpenStreetMap's spelling is kept alongside rather than
    discarded - it is what the water is findable by, and keeping it is what
    makes a wrong match visible instead of silent.

Pure: no I/O beyond reading the committed YAML once, no clock, no database.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "pzw"

# Leading water-kind words, in the folded form `normalise` produces. "Jezioro
# Pomocnia" and "j. Pomocnia" are the same water and must reduce to the same
# key. Mirrors the same list in tools/pzw_extract.py, which builds the keys.
KIND_PREFIXES = frozenset(
    {
        "jeziora",
        "jezioro",
        "zbiornik",
        "zbiorniki",
        "zalew",
        "staw",
        "stawy",
        "glinianki",
        "glinianka",
        "rzeki",
        "rzeka",
        "kanal",
        "j",
        "rz",
        "zb",
    }
)

# Two tokens count as the same word if they share this much of a prefix. Polish
# waters are routinely listed under one adjectival ending and mapped under
# another - the okreg's "Szczesliwice" against OSM's "Szczesliwickie" - and a
# stemmer for one language is more machinery than one ending is worth.
MIN_PREFIX_CHARS = 4
MIN_PREFIX_RATIO = 0.7

# A token this short carries no identifying weight ("i", "na", "w").
MIN_SIGNIFICANT = 3

# Leading okreg catalogue number, e.g. "0.101 Stobrawa - staw". Mirrors the
# same pattern in tools/pzw_crawl.py, which writes the keys.
CATALOGUE_PREFIX = re.compile(r"^\d+(?:\.\d+)*\s+")


@dataclass(frozen=True)
class PzwWater:
    """One water as the okreg lists it."""

    name: str
    key: str
    okreg: str
    section: str
    place: str = ""
    area_ha: float | None = None


@dataclass(frozen=True)
class Match:
    """What the registry could tell us about a water, and how sure it is."""

    water: PzwWater
    exact: bool


def normalise(name: str) -> str:
    """Fold a water's name to the form keys are compared in.

    Accents removed, case dropped, punctuation dropped, leading water-kind word
    dropped. Must agree with `tools/pzw_extract.py.normalise_name`, which
    writes the keys this is compared against - a test pins that.
    """
    # Some okregi prefix every water with their own catalogue number - Opole
    # lists "0.101 Stobrawa - staw". It is part of the printed name but noise
    # in a key, and `tools/pzw_crawl.py` strips it before writing the key, so
    # this must strip it too or every Opole water becomes unmatchable.
    name = CATALOGUE_PREFIX.sub("", name.strip())
    folded = unicodedata.normalize("NFKD", name.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.replace("ł", "l")
    folded = re.sub(r"[^a-z0-9 ]+", " ", folded)
    words = folded.split()
    while words and words[0] in KIND_PREFIXES:
        words = words[1:]
    return " ".join(words)


def _tokens_match(a: str, b: str) -> bool:
    """Same word, allowing for a different Polish ending."""
    if a == b:
        return True
    shared = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        shared += 1
    if shared < MIN_PREFIX_CHARS:
        return False
    return shared / max(len(a), len(b)) >= MIN_PREFIX_RATIO


def _score(query: str, key: str) -> float:
    """How much of the queried name the registry entry accounts for.

    Asymmetric on purpose. The registry routinely carries a district the map
    does not - "Glinianki Szczesliwice Warszawa Ochota" against OSM's
    "Glinianki Szczesliwickie" - so extra tokens on the registry side must not
    count against a match. Extra tokens on the *query* side do, which is what
    keeps a long unrelated name from matching a short listed one.
    """
    q_tokens = [t for t in query.split() if len(t) >= MIN_SIGNIFICANT]
    k_tokens = [t for t in key.split() if len(t) >= MIN_SIGNIFICANT]
    if not q_tokens or not k_tokens:
        return 0.0
    # The head token is the water's actual name; anything after it is usually a
    # district the registry carries and the map does not ("Szczesliwice
    # Warszawa Ochota"). If the heads do not agree, nothing else can rescue it:
    # without this, the registry's one-token "rz. Jeziorka" matched any query
    # containing the word "jezioro", which is most lakes in Poland.
    if not any(_tokens_match(q_tokens[0], t) for t in k_tokens):
        return 0.0
    matched = sum(1 for t in q_tokens if any(_tokens_match(t, o) for o in k_tokens))
    return matched / len(q_tokens)


def _load_file(path: Path) -> list[PzwWater]:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    okreg = str(raw.get("okreg") or path.stem)
    waters: list[PzwWater] = []
    for row in raw.get("waters") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        key = str(row.get("key") or "").strip()
        if not name or not key:
            continue
        area = row.get("area_ha")
        waters.append(
            PzwWater(
                name=name,
                key=key,
                okreg=okreg,
                section=str(row.get("section") or ""),
                place=str(row.get("place") or ""),
                area_ha=float(area) if isinstance(area, int | float) else None,
            )
        )
    return waters


@lru_cache(maxsize=1)
def registry() -> tuple[PzwWater, ...]:
    """Every listed water, from every committed okreg file.

    An empty registry is a supported state, not an error: the app runs fine
    without the lists, it simply has to ask the angler every time.
    """
    if not CONFIG_DIR.is_dir():
        return ()
    waters: list[PzwWater] = []
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        waters.extend(_load_file(path))
    return tuple(waters)


def lookup(name: str) -> Match | None:
    """Find this water in the registry, or admit that we cannot.

    Returns `None` when nothing matches **and** when more than one water
    matches equally well. Poland has a great many lakes called Czarne and the
    list carries no coordinates to tell them apart, so an ambiguous match is
    not a match - it is a question for the angler. Answering it here would put
    a wrong `water_type` into the CPUE segmentation key without anybody seeing
    it happen.
    """
    query = normalise(name)
    if not query:
        return None

    best: list[tuple[float, PzwWater]] = []
    for water in registry():
        if water.key == query:
            return Match(water=water, exact=True)
        score = _score(query, water.key)
        if score >= 1.0:
            best.append((score, water))

    if len(best) != 1:
        return None
    return Match(water=best[0][1], exact=False)
