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


def test_position_settles_what_a_name_cannot() -> None:
    """The reason the okreg's map is worth carrying.

    Name matching has to refuse whenever several waters share a name, and 126
    keys do. A coordinate does not care what anything is called: there are five
    lakes named Czarne, but only one water at 52.5431, 20.6762.
    """
    match = pzw.lookup_by_position(52.5431, 20.6762)
    assert match is not None
    assert match.water.name == "Jezioro Pomocnia"
    assert match.how == pzw.BY_POSITION
    assert match.exact, "a boundary containing the point is not a fuzzy guess"


def test_position_is_preferred_over_the_name() -> None:
    match = pzw.lookup("Jezioro Pomocnia", 52.5431, 20.6762)
    assert match is not None and match.how == pzw.BY_POSITION


def test_a_point_in_no_listed_water_matches_nothing() -> None:
    """Somewhere in the North Sea."""
    assert pzw.lookup_by_position(56.0, 3.0) is None


def test_the_name_still_answers_when_there_is_no_position() -> None:
    """Most sources carry no geometry, so the name path has to keep working."""
    match = pzw.lookup("Jezioro Pomocnia")
    assert match is not None and match.how == pzw.BY_NAME_EXACT


def test_every_stored_boundary_is_a_usable_polygon() -> None:
    """Thinning a boundary must not destroy it.

    Reducing rings by dropping every Nth point wrecked the ones it shortened -
    Zegrzynskie's 476-point ring came back self-intersecting, so `contains()`
    could not answer honestly. The tool uses topology-preserving
    simplification now; this checks the committed result, not the intent.
    """
    from shapely.geometry import Polygon

    checked = 0
    for water in pzw.registry():
        if len(water.ring) < 3:
            continue
        checked += 1
        polygon = Polygon([(lon, lat) for lat, lon in water.ring])
        assert polygon.is_valid, f"{water.name} has a self-intersecting boundary"
        assert polygon.area > 0
    assert checked > 20, "expected the okreg map's boundaries to be loaded"


def test_sources_describing_one_water_are_merged_not_multiplied() -> None:
    """Three files describe the same waters at different levels of detail.

    Left separate they make an unambiguous water ambiguous: Glinianki
    Szczesliwice appeared once with a district and once with a boundary, and
    stopped matching the moment the okreg map was added. Merging must take the
    fullest name AND the boundary AND the district, not pick one record.
    """
    match = pzw.lookup("Glinianki Szczęśliwickie", 52.2050369, 20.9619064)
    assert match is not None
    assert match.water.name == "Glinianki Szczęśliwice", "the fuller name survived"
    assert match.water.place == "Warszawa Ochota", "the district survived"
    assert match.water.ring, "the boundary survived"


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
