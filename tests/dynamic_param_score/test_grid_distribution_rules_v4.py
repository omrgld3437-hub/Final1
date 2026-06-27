"""V4 grid distribution hard rules."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.audit_v4.auditor import audit_profile_distribution
from app.services.dynamic_param_score.distribution_policy import (
    THREE_GRID_DEFENSIVE,
    THREE_GRID_NORMAL,
)


def test_two_grid_fifty_fifty_rejected():
    profile = {
        "buy_grid_count": 2,
        "sell_grid_count": 2,
        "buy_grid_ladder_pcts": [1.0, 2.0],
        "sell_grid_ladder_pcts": [1.0, 2.0],
        "buy_distribution": [50, 50],
        "sell_distribution": [50, 50],
        "final_action": "ACTIVE",
    }
    fails = audit_profile_distribution(profile)
    assert any("fifty_fifty" in f for f in fails)


def test_three_grid_equal_rejected():
    profile = {
        "buy_grid_count": 3,
        "sell_grid_count": 3,
        "buy_grid_ladder_pcts": [1.0, 2.0, 3.0],
        "sell_grid_ladder_pcts": [1.0, 2.0, 3.0],
        "buy_distribution": [33, 33, 34],
        "sell_distribution": [33, 33, 34],
        "final_action": "ACTIVE",
    }
    fails = audit_profile_distribution(profile)
    assert any("equal_three" in f for f in fails)


def test_preferred_three_grid_normal():
    w = list(THREE_GRID_NORMAL)
    assert sum(w) == pytest.approx(100.0, abs=0.1)
    assert w == [15, 30, 55]


def test_preferred_three_grid_defensive():
    w = list(THREE_GRID_DEFENSIVE)
    assert sum(w) == pytest.approx(100.0, abs=0.1)
    assert w == [12, 28, 60]


def test_distribution_sums_to_100():
    profile = {
        "buy_grid_count": 2,
        "sell_grid_count": 2,
        "buy_grid_ladder_pcts": [1.0, 2.0],
        "sell_grid_ladder_pcts": [1.0, 2.0],
        "buy_distribution": [40, 60],
        "sell_distribution": [35, 65],
        "final_action": "ACTIVE",
    }
    fails = audit_profile_distribution(profile)
    assert not any("distribution_fail" in f for f in fails)
