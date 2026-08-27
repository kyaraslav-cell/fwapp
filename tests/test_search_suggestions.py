"""Misspelt a Polish water's name? Offer the register's spelling.

Polish water names are long, diacritic-heavy and easy to mistype, and a search
that finds nothing is a dead end - the angler has no way to know whether they
spelled it wrong or the water simply is not mapped.

The PZW register now holds 2 000+ real Polish water names, which makes it a
better dictionary for this than any spell-checker we could ship.

This is a spelling aid, never a matcher: `lookup` has to be certain before it
puts a `water_type` on a water, `suggest` only has to be close enough to be
worth offering, and the angler decides.
"""

from __future__ import annotations

from app.discover import pzw


def test_a_missing_diacritic_still_finds_the_water() -> None:
    """"Kanal Zeranski" for "Kanał Żerański" - the owner's own example."""
    names = [w.name for w in pzw.suggest("Kanal Zeranski")]
    assert "Kanał Żerański" in names


def test_a_wrong_ending_still_finds_the_water() -> None:
    names = [w.name for w in pzw.suggest("Zegrzynsi")]
    assert any("Zegrzy" in n for n in names)


def test_a_transposed_letter_still_finds_the_water() -> None:
    names = [w.name for w in pzw.suggest("Pomocnja")]
    assert "Jezioro Pomocnia" in names


def test_the_best_guess_comes_first() -> None:
    """A list is only useful if the likely answer is at the top of it."""
    suggestions = pzw.suggest("Pomocnia")
    assert suggestions and suggestions[0].name == "Jezioro Pomocnia"


def test_nonsense_suggests_nothing() -> None:
    """Better an honest dead end than a page of unrelated lakes."""
    assert pzw.suggest("asdfghjkl") == []
    assert pzw.suggest("zzzzzzzzzz") == []


def test_a_query_too_short_to_mean_anything_is_ignored() -> None:
    assert pzw.suggest("") == []
    assert pzw.suggest("je") == []


def test_suggestions_are_distinct_waters() -> None:
    """Three spellings of one lake is not three suggestions."""
    suggestions = pzw.suggest("Czarne", limit=5)
    keys = [w.key for w in suggestions]
    assert len(keys) == len(set(keys))


def test_the_limit_is_respected() -> None:
    assert len(pzw.suggest("Jezioro Biale", limit=3)) <= 3
