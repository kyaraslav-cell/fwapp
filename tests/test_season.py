from datetime import date

import yaml

from app.features.season import derive_season

RULESET = yaml.safe_load(
    """
season_hint:
  status: calendar_stand_in
  derived_from: month
  months:
    4: spring_warming
    7: summer_stagnation
    10: autumn_cooling
  default: summer_stagnation
zone_score:
  default_phase: summer_stagnation
"""
)


def test_months_map_to_phases():
    assert derive_season(RULESET, date(2026, 4, 12)).phase == "spring_warming"
    assert derive_season(RULESET, date(2026, 7, 12)).phase == "summer_stagnation"
    assert derive_season(RULESET, date(2026, 10, 12)).phase == "autumn_cooling"


def test_unmapped_month_uses_default():
    assert derive_season(RULESET, date(2026, 1, 12)).phase == "summer_stagnation"


def test_season_never_claims_to_be_measured():
    """ADR 0001 §5: phase must come from water temperature. Until it does, the
    UI must not present this calendar guess as a measurement."""
    hint = derive_season(RULESET, date(2026, 4, 12))
    assert hint.is_measured is False
    assert hint.caveat


def test_missing_season_config_falls_back_to_default_phase():
    hint = derive_season({"zone_score": {"default_phase": "autumn_cooling"}}, date(2026, 5, 1))
    assert hint.phase == "autumn_cooling"
    assert hint.is_measured is False
