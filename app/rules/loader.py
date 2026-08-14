from __future__ import annotations

from typing import Any

from app.core.config import load_ruleset_yaml

REQUIRED_RULE_IDS = {"pressure_trend", "light_window"}


def load_active_ruleset() -> dict[str, Any]:
    ruleset = load_ruleset_yaml()
    rule_ids = {r["id"] for r in ruleset["rules"]}
    missing = REQUIRED_RULE_IDS - rule_ids
    if missing:
        raise ValueError(f"ruleset missing required rules: {missing}")
    return ruleset
