"""Weekly fixed 4+4 / ≤10% net profile library contract."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.v6.net_profile_library import (
    LIBRARY_VERSION,
    PROFILE_VALUES,
    build_profile,
    seal_net_profile_shape,
    validate_library_invariants,
)
from app.services.dynamic_param_score.v6.domain.types import GridLevel
from app.services.dynamic_param_score.v6.v6_scenario_classifier import ClassifiedScenario


def test_library_invariants_hold():
    assert validate_library_invariants() == []
    assert LIBRARY_VERSION.startswith("v6_net_profile_library_weekly_4x4")


@pytest.mark.parametrize("key", sorted(PROFILE_VALUES.keys()))
def test_every_profile_builds_fixed_4x4(key: str):
    classified = ClassifiedScenario(key.split("_", 1)[0], "01", "001", "PB01", "x", "")
    profile = build_profile(key, classified, "STD")
    assert len(profile.buy_grids) == 4
    assert len(profile.sell_grids) == 4
    assert sum(g.amount_pct for g in profile.buy_grids) == 100
    assert sum(g.amount_pct for g in profile.sell_grids) == 100
    assert all(g.amount_pct >= 10 for g in profile.buy_grids + profile.sell_grids)
    assert all(g.distance_pct < 0 for g in profile.buy_grids)
    assert all(g.distance_pct > 0 for g in profile.sell_grids)
    assert profile.modules.get("grid_contract") == "fixed_4x4"
    assert profile.modules.get("weekly_cycle_days") == 7
    auto = bool(profile.modules.get("automatic_apply"))
    if str(PROFILE_VALUES[key][-1]).startswith("Kapalı"):
        assert auto is False
        assert profile.modules.get("reference_plan_only") is True
        assert profile.normal_buy_enabled is False
    else:
        assert auto is True
        assert profile.normal_buy_enabled is True


def test_seal_restores_operator_ladders_after_mutation():
    classified = ClassifiedScenario("R2", "01", "001", "PB01", "x", "")
    library = build_profile("R2_BALANCED_RANGE", classified, "STD")
    mutated = library.copy()
    mutated.base_allocation_pct = 10
    mutated.quote_allocation_pct = 90
    mutated.buy_grids = [GridLevel(-20, 100)]
    mutated.sell_grids = [GridLevel(20, 100)]
    sealed = seal_net_profile_shape(mutated, library)
    assert sealed.base_allocation_pct == 50
    assert [(g.distance_pct, g.amount_pct) for g in sealed.buy_grids] == [
        (-1, 30),
        (-3, 30),
        (-5, 20),
        (-7, 20),
    ]
    assert [(g.distance_pct, g.amount_pct) for g in sealed.sell_grids] == [
        (1, 30),
        (3, 30),
        (5, 20),
        (7, 20),
    ]
