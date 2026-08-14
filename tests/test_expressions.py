import pytest

from app.rules.expressions import ExpressionError, safe_eval


def test_arithmetic():
    assert safe_eval("dp_6h <= -3.0", {"dp_6h": -4.0}) is True
    assert safe_eval("dp_6h <= -3.0", {"dp_6h": -1.0}) is False


def test_boolean_and():
    ctx = {"dp_6h": -1.0, "pressure_stability_48h": 1.0}
    assert safe_eval("abs(dp_6h) <= 0.7 and pressure_stability_48h < 2.0", ctx) is False
    ctx2 = {"dp_6h": 0.5, "pressure_stability_48h": 1.0}
    assert safe_eval("abs(dp_6h) <= 0.7 and pressure_stability_48h < 2.0", ctx2) is True


def test_unknown_name_rejected():
    with pytest.raises(ExpressionError):
        safe_eval("evil_name > 0", {})


def test_call_rejected_for_non_whitelisted():
    with pytest.raises(ExpressionError):
        safe_eval("__import__('os').system('echo hi')", {})


def test_clamp():
    assert safe_eval("clamp(x, 0.0, 1.0)", {"x": 5.0}) == 1.0
    assert safe_eval("clamp(x, 0.0, 1.0)", {"x": -5.0}) == 0.0
