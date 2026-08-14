from datetime import UTC, datetime

import yaml

from app.features.pressure import PressureFeatures
from app.features.solar import compute_sun_times
from app.rules.evaluator import FeatureBundle, evaluate

RULESET_YAML = """
version: v0
features_version: f0
rules:
  - id: pressure_trend
    scope: lake
    weight: 0.6
    regime_scores:
      { falling_slow: 1.0, stable: 0.6, falling_fast: 0.3, rising_slow: 0.4, rising_fast: -0.5 }
    reason_template: "pressure {regime} ({dp_6h} hPa / 6h)"
  - id: light_window
    scope: lake
    weight: 0.4
    dawn_dusk_window_hours: 2.0
    score_in_window: 1.0
    score_outside_window: 0.3
    reason_template: "{label} light window ({start}–{end})"
aggregation:
  day_score: { normalise: [0, 10] }
  go_threshold: 5.5
"""


def _ruleset() -> dict:
    return yaml.safe_load(RULESET_YAML)


def test_evaluate_falling_slow_is_go():
    sun = compute_sun_times(52.5431, 20.6762, datetime(2026, 6, 15).date())
    features = FeatureBundle(
        now=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        pressure=PressureFeatures(
            dp_6h=-1.5, dp_24h=-2.0, pressure_stability_48h=1.0, regime="falling_slow"
        ),
        sun=sun,
    )
    bundle = evaluate(_ruleset(), features)
    assert 0.0 <= bundle.day_score <= 10.0
    assert bundle.go is True
    assert len(bundle.best_hours) == 2
    assert bundle.best_hours[0].end > bundle.best_hours[0].start


def test_evaluate_rising_fast_scores_lower_than_falling_slow():
    sun = compute_sun_times(52.5431, 20.6762, datetime(2026, 6, 15).date())
    base_now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    good = evaluate(
        _ruleset(),
        FeatureBundle(
            now=base_now,
            pressure=PressureFeatures(-1.5, -2.0, 1.0, "falling_slow"),
            sun=sun,
        ),
    )
    bad = evaluate(
        _ruleset(),
        FeatureBundle(
            now=base_now,
            pressure=PressureFeatures(4.0, 5.0, 3.0, "rising_fast"),
            sun=sun,
        ),
    )
    assert good.day_score > bad.day_score
    assert good.go is True


def test_go_threshold_boundary():
    sun = compute_sun_times(52.5431, 20.6762, datetime(2026, 6, 15).date())
    base_now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    ruleset = _ruleset()
    ruleset["rules"][0]["regime_scores"]["rising_fast"] = -5.0

    bad = evaluate(
        ruleset,
        FeatureBundle(
            now=base_now,
            pressure=PressureFeatures(4.0, 5.0, 3.0, "rising_fast"),
            sun=sun,
        ),
    )
    assert bad.go is False


def test_no_pressure_data_is_neutral_not_a_crash():
    sun = compute_sun_times(52.5431, 20.6762, datetime(2026, 6, 15).date())
    features = FeatureBundle(
        now=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        pressure=PressureFeatures(None, None, None, None),
        sun=sun,
    )
    bundle = evaluate(_ruleset(), features)
    assert 0.0 <= bundle.day_score <= 10.0
