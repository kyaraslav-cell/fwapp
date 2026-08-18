"""CPUE must never be pooled across water types.

Law 3 makes fish per hour the unit of success for the whole project. A stocked
commercial fishery and a wild PZW lake produce it on completely different
scales, so an average across the two is not a worse number - it is a different
measurement wearing the same name, and it would look entirely reasonable.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from app.core.config import CONFIG_DIR
from app.notebook import water_type as wt


def test_known_types_normalise() -> None:
    assert wt.normalise("PZW ") == wt.PZW
    assert wt.normalise("Commercial") == wt.COMMERCIAL
    assert wt.normalise("lake") is None
    assert wt.normalise(None) is None


def test_one_water_type_aggregates() -> None:
    assert wt.assert_comparable([wt.PZW, wt.PZW]) == wt.PZW


def test_mixing_water_types_is_refused() -> None:
    with pytest.raises(wt.IncomparableWatersError):
        wt.assert_comparable([wt.PZW, wt.COMMERCIAL])


def test_an_unrecorded_water_type_is_also_refused() -> None:
    """Silence is not permission.

    A water nobody classified cannot be shown to be comparable, and defaulting
    it to PZW would be exactly the silent corruption this guard exists to stop.
    """
    with pytest.raises(wt.IncomparableWatersError):
        wt.assert_comparable([wt.PZW, None])


def test_only_pzw_water_is_regulated() -> None:
    assert wt.is_regulated(wt.PZW)
    assert not wt.is_regulated(wt.COMMERCIAL)
    assert not wt.is_regulated(None)


@pytest.fixture(scope="module")
def ruleset() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (CONFIG_DIR / "rules.v0.4.yaml").read_text(encoding="utf-8")
    )
    return loaded


def test_commercial_water_leans_on_the_margin_not_the_wind(ruleset: dict[str, Any]) -> None:
    """On a fed water the fish are where the bait goes in, not where the wind puts it."""
    pzw = wt.zone_weight_overrides(ruleset, wt.PZW)
    commercial = wt.zone_weight_overrides(ruleset, wt.COMMERCIAL)
    assert commercial["w_food"] < pzw["w_food"]
    assert commercial["w_exposure"] < pzw["w_exposure"]
    assert commercial["w_margin"] > pzw["w_margin"]


def test_unset_water_type_falls_back_to_defaults(ruleset: dict[str, Any]) -> None:
    assert wt.zone_weight_overrides(ruleset, None) == wt.zone_weight_overrides(ruleset, wt.PZW)


def test_pomocnia_is_configured_as_pzw() -> None:
    cfg = yaml.safe_load((CONFIG_DIR / "lakes" / "pomocnia.yaml").read_text(encoding="utf-8"))
    assert wt.normalise(cfg.get("water_type")) == wt.PZW
