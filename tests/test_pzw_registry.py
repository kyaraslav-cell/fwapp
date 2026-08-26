"""Matching a water against the okreg's published permit list.

`water_type` is not a label. It is the segmentation key for every CPUE
aggregate (law 3), so a wrong answer here silently corrupts the only
measurement the project exists to make. That is why almost every test below is
about the matcher *refusing* rather than matching.
"""

from __future__ import annotations

import pytest

from app.discover import pzw

# The real committed list is the fixture. Matching is only meaningful against
# the spellings the okreg actually publishes, and a hand-written fake would
# assert the assumption rather than the behaviour - the mistake that let the
# Nominatim `category`/`class` bug live for a fortnight.


def test_the_registry_loads() -> None:
    assert len(pzw.registry()) > 50


def test_the_okreg_spelling_is_found_from_the_osm_spelling() -> None:
    """OSM says "Zalew Zegrzynski"; the permit says "Zbiornik Zegrzynski"."""
    match = pzw.lookup("Zalew Zegrzyński")
    assert match is not None
    assert match.water.name == "Zbiornik Zegrzyński"


def test_the_kind_prefix_does_not_decide_identity() -> None:
    """"Jezioro Pomocnia" and "j. Pomocnia" are one water."""
    match = pzw.lookup("Jezioro Pomocnia")
    assert match is not None
    assert match.exact


def test_a_different_polish_ending_still_matches() -> None:
    """The okreg lists Szczesliwice; OSM maps it as Szczesliwickie."""
    match = pzw.lookup("Glinianki Szczęśliwickie")
    assert match is not None
    assert match.water.name == "Glinianki Szczęśliwice"
    assert not match.exact, "this is a fuzzy match and must not claim otherwise"


def test_a_district_the_map_does_not_carry_is_not_held_against_a_match() -> None:
    """The registry entry carries "Warszawa Ochota"; the OSM name does not."""
    assert pzw.lookup("Glinianki Szczęśliwickie") is not None


def test_a_commercial_fishery_is_not_in_the_list() -> None:
    """The real one from the live database. It is a private water, correctly absent."""
    assert pzw.lookup("Łowisko Poniaty - Pod Lasem") is None


def test_a_shared_word_is_not_a_match() -> None:
    """The bug this nearly shipped with.

    Scoring only the shorter side let the registry's one-token "rz. Jeziorka"
    match any query containing the word "jezioro" - which is most lakes in
    Poland, and would have marked them all as PZW waters.
    """
    assert pzw.lookup("Jakieś Nieistniejące Jezioro") is None


def test_an_unrelated_name_matches_nothing() -> None:
    assert pzw.lookup("Loch Ness") is None
    assert pzw.lookup("") is None


def test_a_name_shared_by_several_waters_is_refused() -> None:
    """The national register made this urgent.

    126 keys are shared by more than one water - five lakes called Czarne,
    five Gleboczek, four Dlugie. `lookup` used to return on the FIRST exact
    key match, which silently picked one of them and stamped a water_type
    from it. Safe-ish against 109 waters from one okreg; not against 2 000+
    from thirty-four.
    """
    assert pzw.lookup("Jezioro Czarne") is None
    assert pzw.lookup("Jezioro Białe") is None


def test_a_uniquely_named_water_still_matches() -> None:
    """The refusal must not swallow the unambiguous case."""
    match = pzw.lookup("Jezioro Pomocnia")
    assert match is not None and match.water.name == "Jezioro Pomocnia"


def test_the_same_water_listed_in_two_files_is_not_ambiguity() -> None:
    """A duplicate is not a choice.

    The okreg's permit schedule and the national register both carry some
    waters. Left uncollapsed, the duplicate would make a perfectly
    unambiguous water refuse. Only identical key AND identical place
    collapses - waters that merely share a name are genuinely different and
    must keep refusing.
    """
    keyed: dict[tuple[str, str], int] = {}
    for water in pzw.registry():
        identity = (water.key, water.place.strip().lower())
        keyed[identity] = keyed.get(identity, 0) + 1

    assert not [k for k, n in keyed.items() if n > 1], (
        "the registry contains an exact duplicate; it would refuse a water it can name"
    )


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("Jezioro Pomocnia", "pomocnia"),
        ("j. Pomocnia", "pomocnia"),
        ("POMOCNIA", "pomocnia"),
        ("Zalew Zegrzyński", "zegrzynski"),
        ("Glinianki Szczęśliwice", "szczesliwice"),
    ],
)
def test_normalisation_folds_the_spellings_that_mean_the_same_water(
    spelling: str, expected: str
) -> None:
    assert pzw.normalise(spelling) == expected


def test_the_runtime_normaliser_agrees_with_the_extractor() -> None:
    """The keys in the YAML are written by the tool; they are read by the app.

    If the two normalisers drift, every key in the committed file stops
    matching and the registry silently answers "not listed" for everything -
    which looks exactly like a water genuinely not being on the permit.
    """
    from tools.pzw_extract import normalise_name

    for water in pzw.registry():
        assert pzw.normalise(water.name) == normalise_name(water.name) == water.key
