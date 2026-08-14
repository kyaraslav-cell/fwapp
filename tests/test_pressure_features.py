from datetime import UTC, datetime, timedelta

from app.features.pressure import PressurePoint, compute_pressure_features

REGIMES = {
    "falling_fast": "dp_6h <= -3.0",
    "falling_slow": "dp_6h < -0.7 and dp_6h > -3.0",
    "stable": "abs(dp_6h) <= 0.7 and pressure_stability_48h < 2.0",
    "rising_slow": "dp_6h > 0.7 and dp_6h < 3.0",
    "rising_fast": "dp_6h >= 3.0",
}


def _points(base: datetime, hourly_values: list[float]) -> list[PressurePoint]:
    return [
        PressurePoint(ts=base - timedelta(hours=len(hourly_values) - 1 - i), pressure_msl=v)
        for i, v in enumerate(hourly_values)
    ]


def test_falling_fast_regime():
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    values = [1015.0] * 43 + [1015.0, 1014.5, 1013.5, 1012.5, 1011.5, 1010.5, 1009.5]
    points = _points(now, values)
    features = compute_pressure_features(points, now, REGIMES)
    assert features.dp_6h == -5.5
    assert features.regime == "falling_fast"


def test_stable_regime():
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    values = [1013.0] * 49
    points = _points(now, values)
    features = compute_pressure_features(points, now, REGIMES)
    assert features.dp_6h == 0.0
    assert features.regime == "stable"


def test_no_data_returns_none_regime():
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    features = compute_pressure_features([], now, REGIMES)
    assert features.regime is None
    assert features.dp_6h is None
