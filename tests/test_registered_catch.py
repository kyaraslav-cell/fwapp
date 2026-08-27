"""The okreg's registered catch: the project's first measured CPUE.

These run against the real committed report, not a fake. A fixture built from
the same assumption as the parser asserts the assumption rather than the
behaviour - the mistake that let the Nominatim `category`/`class` bug live for
a fortnight, and the one that put a 57% carp share on a water whose real share
is 2.8%.
"""

from __future__ import annotations

import pytest

from app.notebook import registered_catch as rc


def test_the_report_loads() -> None:
    assert len(rc.reports()) > 20


def test_pomocnia_matches_the_published_figures() -> None:
    """Checked by hand against the report's own sentence.

    "W sezonie 2024 w Pomocni lowilo 23 wedkarzy, ktorzy zarejestrowali swe
    polowy na poziomie 135,6 kg ryb, a na 1 wedkarza spedzajacego nad woda
    srednio 8,26 dnia, dziennie przypadalo srednio 0,71 kg ryb, a rocznie
    5,90 kg." - and carp at 39,6%, mean weight 3,36 kg.
    """
    found = rc.newest_for_keys(["pomocnia"])

    assert found is not None
    assert found.year == 2024
    assert found.anglers == 23
    assert found.days_per_angler == pytest.approx(8.26)
    assert found.kg_per_angler_day == pytest.approx(0.71)
    assert found.kg_per_angler_year == pytest.approx(5.9)
    assert found.species_pct["carp"] == pytest.approx(39.6)
    assert found.species_mean_kg["carp"] == pytest.approx(3.36)


def test_the_cyprinid_family_is_never_read_as_carp() -> None:
    """`karpiowate` means bream-and-roach-and-rudd, and starts with `karp`.

    Reading it as carp put a 57% carp share on Narew nr 7, whose real carp
    share is 2.8% - the difference between a carp water and a bream water.
    """
    found = rc.newest_for_keys(["obwod rybacki narew nr 7"])

    assert found is not None
    assert found.species_pct["carp"] == pytest.approx(2.8)
    assert found.species_pct.get("rudd") is None, "57% is the bream share, not rudd's"


def test_a_share_stated_before_its_species_is_still_read() -> None:
    """"Najwyzszym udzialem (85%) zaznaczyl sie karp" - percentage first."""
    found = rc.newest_for_keys(["szczesliwickie"])

    assert found is not None
    assert found.species_pct["carp"] == pytest.approx(85.0)
    assert found.kg_per_angler_day == pytest.approx(0.29)


def test_a_water_the_report_does_not_cover_returns_nothing() -> None:
    assert rc.newest_for_keys(["Łowisko Poniaty - Pod Lasem"]) is None
    assert rc.newest_for_keys([]) is None
    assert rc.newest_for_keys(["Loch Ness"]) is None


def test_the_top_species_is_the_largest_share() -> None:
    found = rc.newest_for_keys(["pomocnia"])
    assert found is not None
    top = found.top_species
    assert top is not None and top[0] == "carp"


def test_every_record_carries_its_sample_size() -> None:
    """Law 5: no number without its n.

    The page shows these figures, so a record with a rate and no angler count
    would put an unsupported number in front of the angler.
    """
    missing = [r.name for r in rc.reports() if r.anglers is None]
    assert not missing, f"records with no sample size: {missing}"


def test_no_rate_is_implausible() -> None:
    """A parser reading the wrong number usually reads a wildly wrong one.

    An earlier version reported 97 kg per angler-day for one river district,
    which is roughly a hundred times a good day's fishing.
    """
    for record in rc.reports():
        assert 0.0 < record.kg_per_angler_day < 10.0, (
            f"{record.name}: {record.kg_per_angler_day} kg per angler-day is not a real figure"
        )
        if record.kg_per_angler_year is not None:
            assert 0.0 < record.kg_per_angler_year < 200.0, record.name


def test_species_shares_never_exceed_the_whole_catch() -> None:
    for record in rc.reports():
        for slug, pct in record.species_pct.items():
            assert 0.0 < pct <= 100.0, f"{record.name}: {slug} at {pct}%"
