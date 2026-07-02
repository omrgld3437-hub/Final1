"""V6 PA/DM display and BotParams profit-loop consistency."""

from __future__ import annotations

import json

import pytest

from app.services.dynamic_param_score.adapters import (
    decision_to_param_assistant_result,
    params_to_grid_config,
)
from app.services.dynamic_param_score.models import BotParams, DynamicParamDecision
from app.services.dynamic_param_score.v6.v6_botparams_adapter import v6_profile_to_bot_params
from app.services.dynamic_param_score.v6.v6_pa_display import enrich_v6_display
from app.services.dynamic_param_score.v6.v6_profile_catalog import get_profile_by_regime_behavior


def _grid_cfg(bp: BotParams) -> dict:
    return params_to_grid_config(bp, pool_version="v6", ui_display=True)


def test_rebuy_disabled_forces_profit_sell_disabled():
    p = get_profile_by_regime_behavior("R3", "PB15", "STD")
    assert p is not None
    assert p.buyback_after_sell_enabled is False
    bp = v6_profile_to_bot_params(p)
    cfg = _grid_cfg(bp)
    assert cfg["rebuy_enabled"] is False
    assert cfg["resell_enabled"] is False


def _v6_decision(**kwargs) -> DynamicParamDecision:
    base = dict(
        decision_id="test-v6-display",
        symbol="BTCUSDT",
        timestamp=1,
        run_source="param_assistant",
        final_action="CONTROLLED_GRID",
        deployable=True,
        param_score=70,
        confidence_score=70,
        risk_score=40,
        regime_tag="R6",
        risk_state="NORMAL",
        selected_profile_name="DPLV6_TEST",
        selected_profile_bucket="V6",
        params=None,
        safety_gates=[],
        blocking_reasons=[],
        warnings=[],
        explain="V6 test",
        telemetry={},
    )
    base.update(kwargs)
    return DynamicParamDecision(**base)


def test_post_sell_buyback_enabled_without_normal_buy_grids():
    p = get_profile_by_regime_behavior("R6", "PB06", "STD")
    assert p is not None
    bp = v6_profile_to_bot_params(p)
    assert bp.buy_grid_count == 0
    assert bp.sell_grid_count >= 1
    assert bp.rebuy_enabled is True
    cfg = _grid_cfg(bp)
    assert cfg["rebuy_enabled"] is True
    assert cfg["resell_enabled"] is True


def test_pb11_post_sell_buyback_keeps_profit_loop():
    p = get_profile_by_regime_behavior("R8", "PB11", "STD")
    assert p is not None
    bp = v6_profile_to_bot_params(p)
    assert bp.buy_grid_count == 0
    assert bp.rebuy_enabled is True
    assert bp.resell_enabled is True


def test_normal_buy_disabled_implies_zero_buy_grids():
    p = get_profile_by_regime_behavior("R6", "PB06", "STD")
    bp = v6_profile_to_bot_params(p)
    assert bp.buy_grid_count == 0


def test_v6_pa_result_has_no_legacy_v5_display_strings():
    p = get_profile_by_regime_behavior("R6", "PB06", "STD")
    bp = v6_profile_to_bot_params(p)
    v6_display = enrich_v6_display(
        {
            "catalog_profile_id": p.profile_id,
            "final_profile_id": f"{p.profile_id}__ADJ_DQ_0_BTC_B2_F_F0_V1_L0_FINAL",
            "severity": "STD",
            "buy_grid_count": bp.buy_grid_count,
            "sell_grid_count": bp.sell_grid_count,
            "rebuy_enabled": bp.rebuy_enabled,
            "normal_buy_enabled": p.normal_buy_enabled,
            "adjuster_trace": [{"name": "data_quality", "class": "DQ0", "score": 0}],
        },
        deployable=True,
    )
    decision = _v6_decision(
        selected_profile_name=p.profile_id,
        params=bp,
        telemetry={
            "pool_version": "v6",
            "v6_display": v6_display,
            "param_pool": {"pool_version": "v6"},
        },
    )
    result = decision_to_param_assistant_result(decision, budget=1000.0, symbol="BTCUSDT")
    blob = json.dumps(result, default=str).lower()
    assert "raf (v5)" not in blob
    assert "referans / bekle" not in blob
    assert "fee verisi yok" not in blob
    assert result["profile_tile_label"] == "V6 Profil Kimliği"
    assert result["fee_display"]["fee_mode"] == "disabled"
    assert result["final_action_label"] != "Referans / bekle"
    assert "referans" not in (result.get("final_action_label") or "").lower()


def test_v6_profit_ui_gates_resell_when_rebuy_off():
    p = get_profile_by_regime_behavior("R3", "PB16", "STD")
    assert p is not None
    bp = v6_profile_to_bot_params(p)
    ui = decision_to_param_assistant_result(
        _v6_decision(
            symbol="SYNUSDT",
            regime_tag="R3",
            selected_profile_name=p.profile_id,
            params=bp,
            telemetry={
                "pool_version": "v6",
                "v6_display": enrich_v6_display(
                    {"rebuy_enabled": False, "normal_buy_enabled": False, "buy_grid_count": 0, "sell_grid_count": 1},
                    deployable=True,
                ),
                "param_pool": {"pool_version": "v6"},
            },
        ),
        budget=500.0,
        symbol="SYNUSDT",
    )
    profit = (ui.get("ui_config") or {}).get("profit") or {}
    assert profit.get("rebuy_enabled") is False
    assert profit.get("resell_enabled") is False
