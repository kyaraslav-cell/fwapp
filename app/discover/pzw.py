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
    # A closed boundary as (lat, lon) pairs, where the source had one. Only
    # some sources carry geometry, and only lakes have it - a river reach is a
    # polyline and cannot contain a point.
    ring: tuple[tuple[float, float], ...] = ()


# How a match was arrived at, weakest last.
BY_POSITION = "inside"
BY_NAME_EXACT = "exact"
BY_NAME_FUZZY = "fuzzy"


@dataclass(frozen=True)
class Match:
    """What the registry could tell us about a water, and how sure it is."""

    water: PzwWater
    how: str

    @property
    def exact(self) -> bool:
        """True when this is not a fuzzy name guess.

        A position inside a boundary is the strongest answer available: five
        lakes share the name Czarne, but only one of them is at any given
        coordinate.
        """
        return self.how in (BY_POSITION, BY_NAME_EXACT)


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
        ring_raw = row.get("ring") or []
        ring: list[tuple[float, float]] = []
        if isinstance(ring_raw, list):
            for point in ring_raw:
                if isinstance(point, list | tuple) and len(point) == 2:
                    try:
                        ring.append((float(point[0]), float(point[1])))
                    except (TypeError, ValueError):
                        continue
        waters.append(
            PzwWater(
                name=name,
                key=key,
                okreg=okreg,
                section=str(row.get("section") or ""),
                place=str(row.get("place") or ""),
                area_ha=float(area) if isinstance(area, int | float) else None,
                ring=tuple(ring),
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

    return _merge(waters)


def _richest(group: list[PzwWater]) -> PzwWater:
    """One record built from several descriptions of the same water.

    Fields are taken from whichever source has them rather than picking a
    single winning record, because the sources are strong in different places:
    the okreg map carries boundaries but abbreviates names to "Szczesliwice",
    while the permit schedule spells it "Glinianki Szczesliwice" and records
    the district. Choosing one record threw away half of what is known.

    The fullest name is a heuristic, and a safe one: every name in a group
    normalises to the same key by construction, so a longer name is more
    detail about the same water, not a different one.
    """
    best = max(group, key=lambda w: len(w.name))
    ring = next((w.ring for w in group if w.ring), ())
    place = next((w.place for w in group if w.place.strip()), "")
    section = next((w.section for w in group if w.section.strip()), "")
    area = next((w.area_ha for w in group if w.area_ha is not None), None)
    return PzwWater(
        name=best.name,
        key=best.key,
        okreg=best.okreg,
        section=section,
        place=place,
        area_ha=area,
        ring=ring,
    )


def _merge(waters: list[PzwWater]) -> tuple[PzwWater, ...]:
    """Collapse several sources' records of one water into one record.

    Three files can describe the same water: the okreg's permit schedule, the
    national register and the okreg's map. `lookup` refuses whenever several
    entries match, so leaving them separate turns perfectly unambiguous waters
    into questions - Glinianki Szczesliwice appeared twice, once with a place
    and once without, and stopped matching the moment the map was added.

    **The place is what separates waters, not the okreg.** Grouping by okreg as
    well was the first attempt and it merged nothing across files: the national
    register labels every one of its waters `poland`, while the permit schedule
    and the map say `mazowiecki`, so the same lake in two files never met.
    The place does the job on its own - the five lakes called Czarne are in
    Kwilcz, Bobrowo, Olsztyn and so on, and stay five records.

    A record with no place recorded merges into the one place its group names.
    Where a group names two, the place-less records are dropped: they cannot be
    attributed to either, and guessing is how a wrong water_type gets in.
    """
    grouped: dict[str, list[PzwWater]] = {}
    for water in waters:
        grouped.setdefault(water.key, []).append(water)

    out: list[PzwWater] = []
    for group in grouped.values():
        places = {w.place.strip().lower() for w in group if w.place.strip()}
        if len(places) <= 1:
            out.append(_richest(group))
            continue
        # Two different places for one name: two different waters.
        for place in sorted(places):
            same = [w for w in group if w.place.strip().lower() == place]
            out.append(_richest(same))
    return tuple(out)


@lru_cache(maxsize=1)
def _bounded() -> tuple[tuple[PzwWater, tuple[float, float, float, float]], ...]:
    """Waters that carry a boundary, each with its bounding box.

    The box is checked before the polygon because it rejects almost everything
    almost free: a point is compared against 66 rectangles, and only the one or
    two that survive cost a real point-in-polygon test.
    """
    out: list[tuple[PzwWater, tuple[float, float, float, float]]] = []
    for water in registry():
        if len(water.ring) < 3:
            continue
        lats = [p[0] for p in water.ring]
        lons = [p[1] for p in water.ring]
        out.append((water, (min(lats), min(lons), max(lats), max(lons))))
    return tuple(out)


def lookup_by_position(lat: float, lon: float) -> Match | None:
    """The listed water whose boundary contains this point, if exactly one does.

    This is the strongest answer the registry can give, and the reason the
    okreg's own map is worth having: name matching has to refuse whenever
    several waters share a name, and 126 keys do. Position does not care what
    anything is called.

    Still refuses when two boundaries overlap the point - a lake inside a
    reservoir's fishing district, say. Overlap is a genuine question about
    which water someone means, not a tie to be broken silently.
    """
    from shapely.geometry import Point, Polygon

    point = Point(lon, lat)
    hits: list[PzwWater] = []
    for water, (min_lat, min_lon, max_lat, max_lon) in _bounded():
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        polygon = Polygon([(p[1], p[0]) for p in water.ring])
        if not polygon.is_valid:
            # A self-intersecting ring cannot answer "inside" honestly. Buffer
            # by nothing is shapely's idiom for repairing one; if that fails
            # the water simply does not vote.
            polygon = polygon.buffer(0)
            if polygon.is_empty or not polygon.is_valid:
                continue
        if polygon.contains(point):
            hits.append(water)

    if len(hits) != 1:
        return None
    return Match(water=hits[0], how=BY_POSITION)


def lookup(name: str, lat: float | None = None, lon: float | None = None) -> Match | None:
    """Find this water in the registry, or admit that we cannot.

    Position first when it is known, because it is the only input that
    distinguishes two waters sharing a name. Falls back to the name, which is
    all the sources without geometry can offer.

    Returns `None` when nothing matches **and** when more than one water
    matches equally well. An ambiguous match is not a match - it is a question
    for the angler. Answering it here would put a wrong `water_type` into the
    CPUE segmentation key without anybody seeing it happen.
    """
    if lat is not None and lon is not None:
        found = lookup_by_position(lat, lon)
        if found is not None:
            return found

    query = normalise(name)
    if not query:
        return None

    # Every exact match, not the first one. With the national register loaded
    # this matters a great deal: 126 keys are shared by more than one water -
    # five lakes called Czarne, five called Gleboczek, four called Dlugie. An
    # early return on the first hit silently picked one of them and stamped a
    # water_type from it, which is the exact silent corruption this function's
    # ambiguity rule exists to prevent. It was safe-ish against 109 waters
    # from one okreg; it is not safe against 2 193 from thirty-four.
    exact = [w for w in registry() if w.key == query]
    if len(exact) == 1:
        return Match(water=exact[0], how=BY_NAME_EXACT)
    if exact:
        return None

    fuzzy = [w for w in registry() if _score(query, w.key) >= 1.0]
    if len(fuzzy) != 1:
        return None
    return Match(water=fuzzy[0], how=BY_NAME_FUZZY)
