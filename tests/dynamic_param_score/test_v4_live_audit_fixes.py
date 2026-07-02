"""Regression tests from 10-coin live Param Assistant audit (V4)."""

from __future__ import annotations

from app.services.dynamic_param_score.adapters import build_display_regime_label
from app.services.dynamic_param_score.feasibility import _finalize_buy_distribution
from app.services.dynamic_param_score.param_generator.grid_distribution import (
    DEFENSIVE_THREE_GRID,
    normalize_side_distribution,
)
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    MANDATORY_CRITICAL_ROUTES,
)
from app.services.dynamic_param_score.param_generator.v4_resolvers import (
    resolve_adaptive_max_exposure,
)
from app.services.dynamic_param_score.utils import distribute_weights


def test_defensive_two_grid_not_50_50_live_audit():
    dist, changed = normalize_side_distribution([50, 50], defensive=True)
    assert changed
    assert dist == [30, 70]


def test_mandatory_critical_routes_include_live_defensive_shelves():
    required = {
        "A1|R2|S3|V3|DEFENSIVE",
        "A2|R2|S3|V3|DEFENSIVE",
        "A2|R2|S3|V4|DEFENSIVE",
        "A3|R2|S3|V4|DEFENSIVE",
        "A3|R4|S3|V5|DEFENSIVE",
    }
    assert required.issubset(set(MANDATORY_CRITICAL_ROUTES))


def test_defensive_buy_distribution_rejects_distribute_weights_pattern():
    """distribute_weights(3) ≈ 29.8/34.3/35.9 — must become 12/28/60."""
    raw = distribute_weights(3, 0.30)
    fixed = _finalize_buy_distribution(raw, defensive=True)
    assert [round(x * 100) for x in fixed] == list(DEFENSIVE_THREE_GRID)


def test_defensive_buy_distribution_rejects_fractional_near_equal():
    dist, changed = normalize_side_distribution([0.298, 0.343, 0.359], defensive=True)
    assert changed
    assert dist == list(DEFENSIVE_THREE_GRID)


def test_defensive_three_grid_invariants():
    dist, changed = normalize_side_distribution([29, 33, 38], defensive=True)
    assert changed
    assert dist[0] <= 18
    assert dist[-1] >= 50
    assert max(dist) - min(dist) >= 30


def test_adaptive_exposure_pump_v5_caps_at_35():
    sig = {
        "regime_code": "R4",
        "vol_code": "V5",
        "overbought_chop": True,
        "volatility_percentile": 97,
        "return_24h_pct": 23.5,
        "price_in_bb": 0.92,
        "z_score_5m": 2.0,
        "liquidity_score": 50,
        "spread_score": 40,
    }
    cap, reason = resolve_adaptive_max_exposure(sig, current_max=0.55, defensive=True)
    assert cap <= 0.35
    assert reason == "pump_v5_overextension"


def test_regime_label_uses_route_r4_not_balanced():
    label = build_display_regime_label(
        regime_tag="RANGE_BALANCED",
        route_key="A3|R4|S3|V5|DEFENSIVE",
        effective_risk_state="DEFENSIVE",
    )
    assert "Kırılım riski" in label
    assert "Dengeli aralık" not in label


def test_regime_label_from_regime_code_when_route_empty():
    label = build_display_regime_label(
        regime_tag="RANGE_BALANCED",
        route_key="",
        regime_code="R4",
        structure_code="S3",
        vol_code="V5",
        effective_risk_state="DEFENSIVE",
    )
    assert "Kırılım riski" in label
