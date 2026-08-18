"""Every expression in every ruleset must actually parse and evaluate.

This exists because the same bug landed twice. A YAML folded scalar (`>`) keeps
more-indented continuation lines literal, so an expression written across
several lines with a hanging indent arrives at the evaluator split in two and
dies on a SyntaxError - at request time, in the browser, not in review.

Nothing else catches it: the YAML parses, the file looks right, and the only
symptom is a route that raises. So walk every ruleset, pull out every
`expression`, and put it through the real restricted evaluator.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from app.core.config import CONFIG_DIR
from app.rules.expressions import safe_eval

# A generous context: any name any ruleset expression might reference. Values
# are plausible rather than meaningful - this asserts that expressions parse and
# run, not what they return.
CONTEXT: dict[str, float | int | bool] = {
    "p_now": 1012.0, "p_norm": 1015.0, "p_dev_24h_ago": -7.0, "p_dev_full_hpa": 14.0,
    "p_approach_full_hpa": 6.0, "p_range_72h": 5.0, "t_air_range_72h": 6.0,
    "pressure_range_full_hpa": 12.0, "air_temp_range_full_c": 14.0,
    "dp_6h": -1.5, "pressure_stability_48h": 1.2,
    "t_water": 19.4, "t_water_24h": 18.1, "t_opt": 26.8, "t_zero_c": 4.0,
    "t_span_c": 9.0, "t_dir_full_c": 2.0,
    "o2_sat": 9.1, "o2_saturation": 9.1, "o2_respiration": 1.9, "o2_stops": 5.0,
    "o2_not_limiting": 8.5, "o2_max_boost": 0.35, "o2_bite_floor": 0.45,
    "oxygen_zone": 0.72, "r20_mgl": 2.0, "q10": 2.3,
    "fetch_norm": 0.6, "shore_prox": 0.4, "lee_shore": 0.24, "shelter": 0.4,
    "mix_index": 0.5, "shallow_proxy": 0.4, "wind_u": 4.5, "wind_ref_ms": 6.0,
    "f_pressure": 0.8, "f_oxygen": 0.7, "f_temp": 0.9, "f_approach": 0.3,
    "f_stability": 0.85, "blend": 0.35, "w_approach": 0.25, "stability_floor": 0.55,
    "heat_stress_penalty": 0.35,
    "w_o2": 0.45, "w_temp": 0.30, "w_food": 0.15, "w_margin": 0.10,
    "w_exposure": 0.25,
    "w_fetch": 0.3, "w_shelter": 0.2, "w_lee": 1.0,
    "lead": 0.2, "thermal_direction": 0.6,
    "consecutive_stable_days": 2, "ideal_consecutive_stable_days": 2,
    "history_coverage": 0.9,
}


def _expressions(node: Any, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "expression" and isinstance(value, str):
                found.append((path, value))
            elif key == "pressure_regimes" and isinstance(value, dict):
                found.extend((f"{path}.{key}.{k}", v) for k, v in value.items())
            else:
                found.extend(_expressions(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_expressions(value, f"{path}[{i}]"))
    return found


PENDING_SLOTS = ("FORMULA_PRESSURE_DEPTH", "FORMULA_WIND_ZONE")


def _is_pending_slot(expr: str) -> bool:
    return any(slot in expr for slot in PENDING_SLOTS)


def _rulesets() -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(CONFIG_DIR.glob("rules.v*.yaml")):
        out.append((path.name, yaml.safe_load(path.read_text(encoding="utf-8"))))
    return out


@pytest.mark.parametrize("name,ruleset", _rulesets(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_expression_parses_and_evaluates(name: str, ruleset: dict[str, Any]) -> None:
    found = _expressions(ruleset)
    assert found, f"{name} has no expressions - did the walker break?"
    for path, expr in found:
        if _is_pending_slot(expr):
            # The owner's two formula slots are placeholders on purpose and the
            # evaluator is REQUIRED to refuse them (CLAUDE.md). Asserting they
            # evaluate would be asserting the opposite of the rule.
            continue
        assert "\n" not in expr.strip(), (
            f"{name}: {path} arrived split across lines. A YAML folded scalar keeps "
            f"more-indented continuation lines literal - align them with the first."
        )
        safe_eval(expr, CONTEXT)
