"""Ranking a river district's stretches against each other.

**A labelled hypothesis, not a measurement.** The owner asked for a river
overlay before a river model exists, so this follows the precedent ADR 0002
set for lakes: every number lives in the ruleset YAML, stamped
`ai_authored_provisional`, carrying `supersede_with: FORMULA_RIVER_SECTION` so
the owner's real formula replaces it rather than blending with it.

Both terms are pure geometry. What is missing - flow, depth, structure,
confluences, weed - is the whole of what actually decides a river swim, which
is why the display ranks stretches against each other and never claims one is
good.
"""

from __future__ import annotations

import math

from app.geo.sections import split_course
from app.rules import river_score
from app.rules.loader import load_active_ruleset

STRAIGHT_NORTH = {
    "type": "LineString",
    "coordinates": [[21.0, 52.0], [21.0, 52.02]],
}


def _ruleset() -> dict:
    return load_active_ruleset()


def test_the_ruleset_declares_the_river_terms_as_provisional() -> None:
    """Law 1: the numbers live in YAML, and they say what they are."""
    config = _ruleset()["river_section"]

    assert config["provenance"] == "ai_authored_provisional"
    assert config["status"] == "hypothesis"
    assert config["supersede_with"] == "FORMULA_RIVER_SECTION"
    assert set(config["weights"]) == {"w_bend", "w_wind_cross"}


def test_every_stretch_is_ranked() -> None:
    cut = split_course(STRAIGHT_NORTH, section_m=250.0)
    scores = river_score.score_sections(_ruleset(), cut, wind_dir=90.0)

    assert set(scores) == {s.index for s in cut}
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_a_featureless_water_is_not_given_a_spread() -> None:
    """A dead straight canal with the wind along it really is uniform.

    Percentile ranking would happily turn floating-point noise into a full
    red-to-green spread, which would show a difference that is not there.
    """
    cut = split_course(STRAIGHT_NORTH, section_m=250.0)
    # Wind blowing straight along a north-south water: no cross-wind anywhere,
    # and no bends either.
    scores = river_score.score_sections(_ruleset(), cut, wind_dir=0.0)

    assert set(scores.values()) == {0.5}


def test_the_wind_direction_changes_the_ranking() -> None:
    """A crosswind gives a stretch a windward bank; wind along it does not."""
    bent = {
        "type": "LineString",
        "coordinates": [
            [21.0, 52.0], [21.0, 52.004], [21.004, 52.006],
            [21.0, 52.008], [21.0, 52.014],
        ],
    }
    cut = split_course(bent, section_m=300.0)

    across = river_score.score_sections(_ruleset(), cut, wind_dir=90.0)
    along = river_score.score_sections(_ruleset(), cut, wind_dir=0.0)

    assert across != along, "wind must reach the ranking or the term is decorative"


def test_no_wind_reading_still_ranks_by_shape() -> None:
    """A water whose ingest has not landed yet is a real state.

    The cross-wind term contributes nothing rather than being invented, which
    leaves the bend term ranking the stretches on its own.
    """
    bent = {
        "type": "LineString",
        "coordinates": [
            [21.0, 52.0], [21.0, 52.004], [21.006, 52.006],
            [21.0, 52.008], [21.0, 52.014],
        ],
    }
    cut = split_course(bent, section_m=300.0)

    scores = river_score.score_sections(_ruleset(), cut, wind_dir=None)

    assert scores, "no wind must not mean no overlay"
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_a_bend_outranks_a_straight_on_the_same_water() -> None:
    """The one thing the model claims, stated as a test.

    Flow on the outside of a bend scours a deeper channel while the inside
    silts. That is physics; what it is worth is the weight in the YAML.
    """
    with_a_bend = {
        "type": "LineString",
        "coordinates": [
            # a long straight run, then a hairpin
            [21.0, 52.000], [21.0, 52.010],
            [21.010, 52.012], [21.0, 52.014], [21.0, 52.020],
        ],
    }
    cut = split_course(with_a_bend, section_m=600.0)
    scores = river_score.score_sections(_ruleset(), cut, wind_dir=None)

    bendiest = max(cut, key=lambda s: s.bend_index)
    straightest = min(cut, key=lambda s: s.bend_index)
    assert bendiest.bend_index > straightest.bend_index
    assert scores[bendiest.index] >= scores[straightest.index]


def test_nothing_to_score_is_not_an_error() -> None:
    assert river_score.score_sections(_ruleset(), []) == {}


def test_bearing_points_the_way_the_water_runs() -> None:
    cut = split_course(STRAIGHT_NORTH, section_m=2000.0)
    assert math.isclose(cut[0].bearing_deg, 0.0, abs_tol=1.0)
