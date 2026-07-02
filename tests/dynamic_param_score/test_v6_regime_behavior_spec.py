"""V6 regime behavior spec — 8 rejim şartnamesi doğrulama."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile
from app.services.dynamic_param_score.v6.engine import V6Engine
from app.services.dynamic_param_score.v6.v6_regime_behavior_spec import (
    REGIME_BEHAVIOR_TEMPLATES,
    apply_regime_behavior_spec,
)
from tests.dynamic_param_score.test_v6_opportunity_oriented_logic import _base_inp


def _empty_profile(regime: str, severity: str = "STD") -> V6CatalogProfile:
    return V6CatalogProfile(
        profile_id="spec_test",
        scenario=ScenarioIdentity(regime, "01", "001", "PB01", severity),  # type: ignore[arg-type]
        base_allocation_pct=30,
        quote_allocation_pct=70,
        normal_buy_enabled=True,
        buy_grids=[GridLevel(-5, 50), GridLevel(-8, 50)],
        sell_grids=[GridLevel(5, 50), GridLevel(8, 50)],
        buyback_after_sell_enabled=True,
        profit_sell_after_buyback_enabled=True,
    )


@pytest.mark.parametrize("regime", ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"])
@pytest.mark.parametrize("severity", ["DEF", "STD", "ACT"])
def test_all_regime_severity_templates_produce_valid_profile(regime: str, severity: str):
    assert regime in REGIME_BEHAVIOR_TEMPLATES
    assert severity in REGIME_BEHAVIOR_TEMPLATES[regime]
    inp = _base_inp(symbol="TESTUSDT")
    trace = [
        {"name": "asset_fragility", "class": "F1"},
        {"name": "btc_context", "class": "B1"},
        {"name": "volatility", "class": "V2"},
    ]
    prof, notes = apply_regime_behavior_spec(
        _empty_profile(regime, severity),
        inp,
        trace,
        regime_id=regime,
        severity=severity,  # type: ignore[arg-type]
    )
    assert notes.get("params_valid") is True
    assert prof.sell_grids, f"{regime}/{severity} must have sell grids"
    assert prof.base_allocation_pct + prof.quote_allocation_pct == 100
    if regime == "R8" and severity == "DEF":
        assert not prof.normal_buy_enabled or not prof.buy_grids


def test_r8_def_never_empty_params():
    inp = _base_inp(
        symbol="CRASHUSDT",
        return_24h_pct=-15.0,
        drawdown_7d_pct=20.0,
        crash_velocity=-3.0,
        asset_fragility_class="F3",
    )
    result = V6Engine().run(inp)
    assert result.profile is not None
    assert len(result.profile.sell_grids) >= 1
    spec = (result.telemetry.get("opportunity_notes") or {})
    assert spec.get("params_valid") is True
    assert spec.get("regime_behavior_spec") is True


def test_r2_std_profit_loop_distances():
    inp = _base_inp(symbol="ETHUSDT", range_stability=0.72, volatility_percentile=28.0)
    trace = [{"name": "asset_fragility", "class": "F0"}, {"name": "volatility", "class": "V2"}]
    prof, _ = apply_regime_behavior_spec(
        _empty_profile("R2"), inp, trace, regime_id="R2", severity="STD"
    )
    buy_first = abs(prof.buy_grids[0].distance_pct) if prof.buy_grids else 99
    sell_first = prof.sell_grids[0].distance_pct if prof.sell_grids else 99
    assert buy_first <= 3
    assert sell_first <= 3
    assert prof.buyback_after_sell_enabled
    assert prof.profit_sell_after_buyback_enabled


def test_severity_downgrade_btc_weak():
    from app.services.dynamic_param_score.v6.v6_regime_behavior_spec import resolve_effective_severity

    inp = _base_inp(symbol="ALTUSDT")
    trace = [{"name": "btc_context", "class": "B3"}]
    assert resolve_effective_severity("ACT", "R2", inp, trace) in ("DEF", "STD")
