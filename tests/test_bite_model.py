"""The three-factor bite model: structure, robustness, and failing closed.

These tests are deliberately about *properties* rather than remembered numbers.
Coefficients in the ruleset are provisional and will move as the calibration
loop learns; the structure must not. A test that pins 0.47 would break on every
honest tuning pass and teach nobody anything.

The properties that must hold:
  * a fatal factor cannot be rescued by two good ones (it is a limiter);
  * pressure cannot change the zone ranking (it is lake-uniform);
  * missing inputs produce no score, never a default;
  * oxygen cannot be manufactured out of arithmetic;
  * an unknown day breaks a settled streak instead of being assumed good.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import yaml

from app.core.config import CONFIG_DIR
from app.features import oxygen as ox
from app.features import stability as stab
from app.features import water_temp as wt
from app.rules import bite

UTC = dt.UTC
NOW = dt.datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def ruleset() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (CONFIG_DIR / "rules.v0.4.yaml").read_text(encoding="utf-8")
    )
    return loaded


# --------------------------------------------------------------------------
# Oxygen — chemistry must not be able to lie
# --------------------------------------------------------------------------


def test_saturation_falls_as_water_warms() -> None:
    values = [ox.saturation_mgl(t) for t in range(0, 35)]
    assert all(a > b for a, b in zip(values, values[1:], strict=False))


def test_respiration_rises_with_temperature(ruleset: dict[str, Any]) -> None:
    cfg = ruleset["oxygen"]["respiration"]
    assert ox.respiration_mgl(10.0, cfg) < ox.respiration_mgl(20.0, cfg)
    assert ox.respiration_mgl(20.0, cfg) < ox.respiration_mgl(30.0, cfg)


@pytest.mark.parametrize("water_c", [5.0, 15.0, 22.0, 30.0, 38.0])
@pytest.mark.parametrize("wind_ms", [0.0, 5.0, 25.0])
def test_wind_can_never_manufacture_oxygen(
    ruleset: dict[str, Any], water_c: float, wind_ms: float
) -> None:
    """Reaeration is driven by the deficit, so it must stop at saturation.

    A storm term that could push water above its own solubility ceiling would
    quietly invent oxygen, and every downstream zone score would inherit it.
    """
    est = ox.estimate(water_c, wind_ms, 1.0, ruleset["oxygen"])
    assert est.dissolved_mgl <= est.saturation_mgl + 1e-9
    assert est.dissolved_mgl >= 0.0


def test_heat_suppresses_oxygen_more_than_saturation_alone(ruleset: dict[str, Any]) -> None:
    """The bug that made the first draft recommend heatwaves.

    Saturation between 20 C and 30 C falls only ~1.6 mg/L. If that were the
    whole story the model would rate a heatwave as merely slightly worse. The
    respiration load is what turns "warmer" into "dead", and this pins it.
    """
    cool = ox.estimate(20.0, 0.0, 0.0, ruleset["oxygen"])
    hot = ox.estimate(30.0, 0.0, 0.0, ruleset["oxygen"])
    saturation_drop = cool.saturation_mgl - hot.saturation_mgl
    dissolved_drop = cool.dissolved_mgl - hot.dissolved_mgl
    assert dissolved_drop > 2 * saturation_drop


def test_oxygen_term_refuses_when_thresholds_are_unfilled() -> None:
    assert ox.oxygen_term(8.0, {"stops_feeding_mgl": None, "not_limiting_mgl": None}) is None


# --------------------------------------------------------------------------
# Water temperature — the lag is the whole point
# --------------------------------------------------------------------------


def _flat_air(hours: int, air_c: float, end: dt.datetime = NOW) -> list[wt.AirSample]:
    return [
        wt.AirSample(end - dt.timedelta(hours=hours - 1 - i), air_c, air_c - 5.0, 0.0, 2.0)
        for i in range(hours)
    ]


def test_deeper_water_lags_further_behind_a_cold_snap(ruleset: dict[str, Any]) -> None:
    cfg = ruleset["water_temp"]
    samples = _flat_air(72, 8.0)
    shallow = wt.simulate(samples, cfg, 1.0, initial_c=25.0)[-1]
    deep = wt.simulate(samples, cfg, 6.0, initial_c=25.0)[-1]
    assert shallow < deep, "a shallow lake must cool faster than a deep one"


def test_water_temperature_fails_closed_on_a_sparse_window(ruleset: dict[str, Any]) -> None:
    """Six hours of weather is not three days, and must not be treated as it."""
    est = wt.estimate(_flat_air(6, 18.0), NOW, ruleset["water_temp"], 2.9, 72, 0.8)
    assert est.celsius is None
    assert not est.available
    assert est.coverage < 0.8


def test_water_temperature_never_claims_to_be_measured(ruleset: dict[str, Any]) -> None:
    est = wt.estimate(_flat_air(72, 18.0), NOW, ruleset["water_temp"], 2.9, 72, 0.8)
    assert est.available
    assert est.is_measured is False


# --------------------------------------------------------------------------
# Stability — the 72-hour window
# --------------------------------------------------------------------------


def _samples(hours: int, value: float, end: dt.datetime = NOW) -> list[stab.Sample]:
    return [stab.Sample(end - dt.timedelta(hours=hours - 1 - i), value) for i in range(hours)]


def test_stability_is_none_when_the_window_is_too_sparse(ruleset: dict[str, Any]) -> None:
    cfg = ruleset["stability"]
    sparse = stab.summarise(_samples(10, 1013.0), NOW, 72)
    full = stab.summarise(_samples(72, 18.0), NOW, 72)
    assert stab.stability_index(sparse, full, cfg) is None


def test_a_settled_window_beats_a_swinging_one(ruleset: dict[str, Any]) -> None:
    cfg = ruleset["stability"]
    calm_p = stab.summarise(_samples(72, 1013.0), NOW, 72)
    calm_t = stab.summarise(_samples(72, 18.0), NOW, 72)
    swing = [
        stab.Sample(NOW - dt.timedelta(hours=71 - i), 1005.0 + (i % 2) * 20.0)
        for i in range(72)
    ]
    rough_p = stab.summarise(swing, NOW, 72)
    calm = stab.stability_index(calm_p, calm_t, cfg)
    rough = stab.stability_index(rough_p, calm_t, cfg)
    assert calm is not None and rough is not None
    assert calm > rough


def test_an_unknown_day_breaks_the_settled_streak(ruleset: dict[str, Any]) -> None:
    """A gap must not be counted as a quiet day. Absence is not evidence."""
    cfg = ruleset["stability"]
    pressure = _samples(24, 1013.0)          # only the most recent day exists
    air = _samples(24, 18.0)
    assert stab.consecutive_stable_days(pressure, air, NOW, cfg) == 1


def test_pressure_norm_refuses_short_history(ruleset: dict[str, Any]) -> None:
    cfg = ruleset["pressure_norm"]
    assert stab.pressure_norm(_samples(72, 1013.0), cfg) is None


def test_pressure_norm_is_a_median_not_a_mean(ruleset: dict[str, Any]) -> None:
    """One storm must not drag this lake's norm."""
    cfg = dict(ruleset["pressure_norm"], min_samples_hours=10)
    calm = _samples(99, 1015.0)
    storm = [stab.Sample(NOW - dt.timedelta(hours=200 + i), 960.0) for i in range(20)]
    norm = stab.pressure_norm(calm + storm, cfg)
    assert norm == 1015.0


# --------------------------------------------------------------------------
# The combined model — structure
# --------------------------------------------------------------------------


def test_a_fatal_factor_cannot_be_rescued(ruleset: dict[str, Any]) -> None:
    """The reason this is a limiter and not a weighted sum.

    The source insists all three conditions must hold at once. If two excellent
    factors could carry a lethal third, the model would happily send the angler
    out into water with no oxygen in it.
    """
    cfg = ruleset["bite_when"]
    all_good = bite.combine(0.95, 0.95, 0.95, None, 1.0, cfg)
    one_fatal = bite.combine(1.0, 0.0, 1.0, None, 1.0, cfg)
    assert one_fatal < 0.4 * all_good


def test_missing_any_factor_produces_no_score(ruleset: dict[str, Any]) -> None:
    """Law 4's spirit: refuse, do not default."""
    assessment = bite.assess(
        ruleset, "roach", water_c=None, oxygen=None,
        p_now=1013.0, p_norm=None, p_24h_ago=None,
        stability=None, stable_days=0, history_coverage=0.0,
    )
    assert assessment.index is None
    assert not assessment.available
    assert "pressure" in assessment.unavailable
    assert "temperature" in assessment.unavailable


def test_unsourced_species_is_refused_not_guessed(ruleset: dict[str, Any]) -> None:
    value, detail = bite.temperature_factor(19.0, "pike", ruleset)
    assert value is None
    assert "pike" in detail


def test_limiting_factor_names_the_real_minimum(ruleset: dict[str, Any]) -> None:
    o2 = ox.estimate(30.0, 0.0, 0.0, ruleset["oxygen"])   # hot, starved
    assessment = bite.assess(
        ruleset, "roach", water_c=30.0, oxygen=o2,
        p_now=1013.0, p_norm=1013.0, p_24h_ago=1013.0,
        stability=1.0, stable_days=3, history_coverage=1.0,
    )
    assert assessment.available
    assert assessment.limiting == "oxygen"


def test_improving_weather_is_not_punished_as_unsettled(ruleset: dict[str, Any]) -> None:
    """Settled OR improving.

    The video's winning session happened during a change, not a settled spell.
    A pure stability multiplier marked that down and made the model contradict
    the source it was built from.
    """
    cfg = ruleset["bite_when"]
    unsettled_and_drifting = bite.combine(0.7, 0.7, 0.7, -0.8, 0.0, cfg)
    unsettled_but_improving = bite.combine(0.7, 0.7, 0.7, 0.9, 0.0, cfg)
    assert unsettled_but_improving > unsettled_and_drifting


def test_confidence_rises_with_a_settled_spell(ruleset: dict[str, Any]) -> None:
    """Stability drives trust separately from score - law 5."""
    chaotic = bite.confidence(0.05, 0, 1.0, ruleset)
    settled = bite.confidence(0.95, 3, 1.0, ruleset)
    assert chaotic is not None and settled is not None
    assert settled > chaotic


# --------------------------------------------------------------------------
# Zones — pressure is lake-uniform and must not be able to reorder them
# --------------------------------------------------------------------------


def _cells() -> list[bite.ZoneInputs]:
    return [
        bite.ZoneInputs(0, 0, fetch_norm=0.9, shore_prox=0.8, lee_shore=0.72, shallow_proxy=0.8),
        bite.ZoneInputs(0, 1, fetch_norm=0.1, shore_prox=0.2, lee_shore=0.02, shallow_proxy=0.2),
        bite.ZoneInputs(1, 0, fetch_norm=0.5, shore_prox=0.5, lee_shore=0.25, shallow_proxy=0.5),
    ]


def test_zone_scores_differentiate(ruleset: dict[str, Any]) -> None:
    cells = _cells()
    o2 = {
        (c.row, c.col): ox.estimate(19.0, 5.0, c.fetch_norm, ruleset["oxygen"]) for c in cells
    }
    scored = bite.score_zones(ruleset, cells, o2, 19.0, 21.0, 26.8)
    values = [v for _, _, v in scored]
    assert len(values) == 3
    assert max(values) > min(values), "a zone map that is one colour says nothing"


def test_wind_direction_reverses_which_bank_is_best(ruleset: dict[str, Any]) -> None:
    """The signed thermal direction, which the source's own example turns on.

    Cooling toward the optimum: the fastest-changing water leads and wins.
    Warming away from it: the same bank is the worst place on the lake. A fixed
    preference for windward banks would get one of these exactly backwards.
    """
    cells = _cells()
    o2 = {
        (c.row, c.col): ox.estimate(24.0, 5.0, c.fetch_norm, ruleset["oxygen"]) for c in cells
    }
    toward = dict(
        ((r, c), v) for r, c, v in bite.score_zones(ruleset, cells, o2, 24.0, 22.0, 26.8)
    )
    # ...and drifting away from it: 22 C yesterday, 24 C now, optimum 20 C.
    away = dict(
        ((r, c), v) for r, c, v in bite.score_zones(ruleset, cells, o2, 24.0, 22.0, 20.0)
    )
    exposed, sheltered = (0, 0), (0, 1)
    assert toward[exposed] > toward[sheltered], "leading water wins while closing on the optimum"
    assert away[exposed] - away[sheltered] < toward[exposed] - toward[sheltered], (
        "the exposed bank's advantage must shrink or reverse when the lake is "
        "moving away from the optimum"
    )


# --------------------------------------------------------------------------
# How much the map depends on a water temperature nobody can measure
# --------------------------------------------------------------------------


def _spread_cells() -> list[bite.ZoneInputs]:
    """Fetch and shore proximity varying INDEPENDENTLY.

    This matters. An earlier version of this fixture let the two co-vary, which
    made the ranking trivially "most exposed first" - it could not move, and
    the invariance result read off it was meaningless.
    """
    cells: list[bite.ZoneInputs] = []
    i = 0
    for f in (0.9, 0.6, 0.3, 0.05):
        for s in (0.9, 0.6, 0.3, 0.05):
            cells.append(bite.ZoneInputs(0, i, f, s, f * s, s))
            i += 1
    return cells


def _map_scores(ruleset: dict[str, Any], water_c: float) -> dict[int, float]:
    cells = _spread_cells()
    o2 = {
        (c.row, c.col): ox.estimate(water_c, 5.0, c.fetch_norm, ruleset["oxygen"])
        for c in cells
    }
    scored = bite.score_zones(ruleset, cells, o2, water_c, water_c - 1.5, 26.8)
    return {col: v for _, col, v in scored}


def _spearman(a: dict[int, float], b: dict[int, float]) -> float:
    ka = sorted(a, key=lambda k: -a[k])
    kb = sorted(b, key=lambda k: -b[k])
    ra = {k: i for i, k in enumerate(ka)}
    rb = {k: i for i, k in enumerate(kb)}
    n = len(ra)
    d2 = sum((ra[k] - rb[k]) ** 2 for k in ra)
    return 1 - 6 * d2 / (n * (n * n - 1))


def test_water_temperature_actually_moves_the_map(ruleset: dict[str, Any]) -> None:
    """If it did not, the thermal term would be decoration.

    The counterpart to the tolerance test below: before asking how much error
    the map absorbs, check the input matters at all.
    """
    orders = {
        tuple(sorted(_map_scores(ruleset, t), key=lambda k: -_map_scores(ruleset, t)[k]))
        for t in (10.0, 18.0, 26.0, 30.0)
    }
    assert len(orders) > 1, "water temperature must be able to reorder the zones"


@pytest.mark.parametrize("truth", [14.0, 18.0, 22.0])
def test_map_survives_the_models_own_uncertainty(
    ruleset: dict[str, Any], truth: float
) -> None:
    """The band is about +/-0.8 C; the map has to hold across it.

    Not a claim of invariance - the ordering does shift. The claim is that it
    shifts less than the angler could notice, and the metric is rank
    correlation rather than exact permutation equality, because a swap in the
    middle of the pack changes nothing anyone would act on.
    """
    base = _map_scores(ruleset, truth)
    for bias in (-1.0, 1.0):
        assert _spearman(base, _map_scores(ruleset, truth + bias)) > 0.95


def test_heat_stress_lowers_confidence(ruleset: dict[str, Any]) -> None:
    """Measured: near the oxygen gate a 1-2 C error reshuffles the top of the map.

    So a heat-stressed lake must be reported as one the model knows less about,
    even when the weather has been perfectly settled.
    """
    settled_and_cool = bite.confidence(0.95, 3, 1.0, ruleset, f_oxygen=1.0)
    settled_but_gasping = bite.confidence(0.95, 3, 1.0, ruleset, f_oxygen=0.05)
    assert settled_and_cool is not None and settled_but_gasping is not None
    assert settled_but_gasping < settled_and_cool
