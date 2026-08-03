from __future__ import annotations

import asyncio
import copy
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.botengine.dynamic.regime_multiplier import (
    REGIME_POLICIES,
    build_regime_multiplier_overlay,
    direction_scores,
)
from app.services.dynamic_param_score.models import (
    DynamicParamDecision,
    ExchangeConstraints,
    FinalAction,
)
from tests.dynamic_param_score.factories import make_bot_params


def _baseline() -> dict:
    return {
        "symbol": "SOLUSDT",
        "initial_capital_usdt": 1000.0,
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "sell_grids": [
            {"sell_grid_pct": 1.5, "sell_qty_pct_of_base": 25.0},
            {"sell_grid_pct": 3.0, "sell_qty_pct_of_base": 25.0},
            {"sell_grid_pct": 5.0, "sell_qty_pct_of_base": 25.0},
            {"sell_grid_pct": 8.0, "sell_qty_pct_of_base": 25.0},
        ],
        "buy_grids": [
            {"buy_grid_pct": 1.5, "buy_qty_pct_of_quote": 25.0},
            {"buy_grid_pct": 3.0, "buy_qty_pct_of_quote": 25.0},
            {"buy_grid_pct": 5.0, "buy_qty_pct_of_quote": 25.0},
            {"buy_grid_pct": 8.0, "buy_qty_pct_of_quote": 25.0},
        ],
        "sell_trigger_trailing_pct": 0.4,
        "buy_trigger_trailing_pct": 0.4,
        "profit_exit_rise_pct": 1.5,
        "profit_exit_drop_pct": 0.4,
        "profit_reentry_drop_pct": 1.5,
        "profit_reentry_rise_pct": 0.4,
        "max_base_exposure_frac": 0.80,
        "max_buy_levels": 4,
        "min_net_profit_rate": 0.001,
        "rebuy_enabled": True,
        "resell_enabled": True,
    }


def _constraints(min_notional: float = 10.0) -> ExchangeConstraints:
    return ExchangeConstraints(
        min_notional=min_notional,
        step_size=0.0001,
        tick_size=0.01,
        min_qty=0.0001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )


def _indicators(direction: str = "neutral", volatility: float = 50.0) -> dict:
    sign = 1.0 if direction == "up" else (-1.0 if direction == "down" else 0.0)
    return {
        "return_1h_pct": 2.2 * sign,
        "return_4h_pct": 4.5 * sign,
        "return_24h_pct": 8.0 * sign,
        "ema20_slope_5m": 0.65 * sign,
        "ema50_slope_5m": 0.45 * sign,
        "price_vs_ema200_pct": 5.5 * sign,
        "adx_1h": 30.0,
        "higher_highs": direction == "up",
        "lower_lows": direction == "down",
        "volatility_percentile": volatility,
        "price_in_bb": 0.8 if direction == "up" else (0.2 if direction == "down" else 0.5),
        "rsi14_5m": 62.0 if direction == "up" else (38.0 if direction == "down" else 50.0),
        "rsi14_1h": 60.0 if direction == "up" else (40.0 if direction == "down" else 50.0),
        "roc_5m": 1.5 * sign,
        "crash_velocity": -2.0 if direction == "down" else 0.0,
        "consecutive_red_pressure": 0.75 if direction == "down" else 0.0,
    }


def _decision(
    regime: str,
    *,
    direction: str = "neutral",
    volatility: float = 50.0,
    confidence: int = 85,
    final_action: str = "BALANCED_GRID",
    hint: str = "",
):
    return SimpleNamespace(
        regime_tag=regime,
        confidence_score=confidence,
        final_action=final_action,
        deployable=True,
        selected_profile_name=hint,
        params=SimpleNamespace(
            emergency_no_buy=False,
            buy_disabled=False,
            sell_only_mode=False,
            cancel_existing_buy_orders=False,
            cancel_existing_sell_orders=False,
            rebuy_enabled=True,
            resell_enabled=True,
            management_mode="CONTROLLED_GRID",
            selected_template_key=hint or regime,
            pool_version="v6",
        ),
        telemetry={
            "indicators": _indicators(direction, volatility),
            "sub_scores": {"data_quality_score": 90},
            "v6_display": {
                "scenario_identity": {
                    "regime_id": regime,
                    "sub_profile_hint": hint,
                }
            },
        },
    )


def _build(regime: str, **kwargs):
    return build_regime_multiplier_overlay(
        _baseline(),
        _decision(regime, **kwargs),
        constraints=_constraints(),
        portfolio=SimpleNamespace(total_equity_usdt=1000.0),
    )


def test_r1_expands_upside_and_shifts_allocation_to_base():
    overlay, meta = _build("R1", direction="up")
    assert overlay["base_alloc_pct"] > 50.0
    assert meta["multipliers"]["sell_distance"] > 1.0
    assert meta["multipliers"]["buy_distance"] < 1.0
    assert overlay["sell_grids"][-1]["sell_qty_pct_of_base"] > overlay["sell_grids"][0][
        "sell_qty_pct_of_base"
    ]


def test_r7_is_defensive_with_deeper_buys_and_earlier_sells():
    overlay, meta = _build("R7", direction="down", volatility=70.0)
    assert overlay["base_alloc_pct"] < 50.0
    assert meta["multipliers"]["buy_distance"] > 1.0
    assert meta["multipliers"]["sell_distance"] < 1.0
    assert overlay["buy_grids"][-1]["buy_qty_pct_of_quote"] > overlay["buy_grids"][0][
        "buy_qty_pct_of_quote"
    ]
    assert overlay["sell_grids"][0]["sell_qty_pct_of_base"] > overlay["sell_grids"][-1][
        "sell_qty_pct_of_base"
    ]


def test_r3_contracts_and_r4_expands_both_sides():
    r3, r3_meta = _build("R3", volatility=12.0)
    r4, r4_meta = _build("R4", volatility=82.0)
    assert r3_meta["multipliers"]["buy_distance"] < 1.0
    assert r3_meta["multipliers"]["sell_distance"] < 1.0
    assert r4_meta["multipliers"]["buy_distance"] > 1.0
    assert r4_meta["multipliers"]["sell_distance"] > 1.0
    assert r3["profit_exit_rise_pct"] >= r3_meta["cost_floor_pct"]
    assert r4["profit_reentry_drop_pct"] >= r4_meta["cost_floor_pct"]


def test_r5_overextended_subprofile_switches_to_defensive_factors():
    clean, clean_meta = _build("R5", direction="up", hint="R5_ACT_CLEAN_BREAKOUT")
    hot, hot_meta = _build(
        "R5",
        direction="up",
        hint="R5_DEF_PARABOLIC_OVEREXTENDED",
    )
    assert hot["base_alloc_pct"] < clean["base_alloc_pct"]
    assert hot_meta["multipliers"]["buy_distance"] > clean_meta["multipliers"]["buy_distance"]
    assert "R5_OVEREXTENDED_DEFENSIVE_OVERRIDE" in hot_meta["guards"]


@pytest.mark.parametrize("regime", sorted(REGIME_POLICIES))
def test_every_regime_preserves_grid_counts_and_percentage_totals(regime: str):
    overlay, meta = _build(
        regime,
        direction="down" if regime in {"R7", "R8"} else "up" if regime in {"R1", "R5"} else "neutral",
    )
    assert len(overlay["buy_grids"]) == 4
    assert len(overlay["sell_grids"]) == 4
    assert overlay["max_buy_levels"] == 4
    assert meta["grid_count_invariant"]["preserved"] is True
    assert overlay["base_alloc_pct"] + overlay["quote_alloc_pct"] == pytest.approx(100.0)
    assert sum(g["buy_qty_pct_of_quote"] for g in overlay["buy_grids"]) == pytest.approx(100.0)
    assert sum(g["sell_qty_pct_of_base"] for g in overlay["sell_grids"]) == pytest.approx(100.0)


def test_r8_pauses_buying_without_deleting_ladder_when_safety_blocks():
    overlay, meta = _build(
        "R8",
        direction="down",
        volatility=95.0,
        final_action="NO_TRADE",
    )
    assert overlay["buy_disabled"] is True
    assert overlay["cancel_existing_buy_orders"] is True
    assert len(overlay["buy_grids"]) == 4
    assert len(overlay["sell_grids"]) == 4
    assert meta["multipliers"]["max_exposure"] < 1.0


def test_same_reference_and_signal_is_deterministic_and_does_not_mutate_reference():
    baseline = _baseline()
    original = copy.deepcopy(baseline)
    decision = _decision("R4", volatility=75.0)
    first, _ = build_regime_multiplier_overlay(
        baseline,
        decision,
        constraints=_constraints(),
        portfolio=SimpleNamespace(total_equity_usdt=1000.0),
    )
    second, _ = build_regime_multiplier_overlay(
        baseline,
        decision,
        constraints=_constraints(),
        portfolio=SimpleNamespace(total_equity_usdt=1000.0),
    )
    assert first == second
    assert baseline == original


def test_up_and_down_scores_can_both_be_high_for_conflicting_horizons():
    decision = _decision("R4")
    ind = decision.telemetry["indicators"]
    ind.update(
        {
            "return_1h_pct": 3.0,
            "return_4h_pct": -6.0,
            "return_24h_pct": 12.0,
            "ema20_slope_5m": -0.8,
            "ema50_slope_5m": 0.6,
            "higher_highs": True,
            "lower_lows": True,
        }
    )
    scores = direction_scores(decision)
    assert scores["up"] > 0.35
    assert scores["down"] > 0.25


def test_low_confidence_blends_multiplier_closer_to_neutral():
    high = _decision("R4", volatility=90.0, confidence=95)
    low = _decision("R4", volatility=90.0, confidence=5)
    low.telemetry = {"sub_scores": {"data_quality_score": 5}, "indicators": {}}
    _, high_meta = build_regime_multiplier_overlay(_baseline(), high)
    _, low_meta = build_regime_multiplier_overlay(_baseline(), low)
    high_factor = high_meta["multipliers"]["buy_distance"]
    low_factor = low_meta["multipliers"]["buy_distance"]
    assert abs(low_factor - 1.0) < abs(high_factor - 1.0)


def test_min_notional_infeasible_keeps_rows_and_emits_guard():
    overlay, meta = build_regime_multiplier_overlay(
        _baseline(),
        _decision("R7", direction="down"),
        constraints=_constraints(min_notional=10.0),
        portfolio=SimpleNamespace(total_equity_usdt=20.0),
    )
    assert len(overlay["buy_grids"]) == 4
    assert len(overlay["sell_grids"]) == 4
    assert any("MIN_NOTIONAL_INFEASIBLE_GRID_COUNT_PRESERVED" in guard for guard in meta["guards"])


def test_cycle_manager_uses_frozen_reference_and_updates_real_round_budgets():
    from app.botengine.dynamic import cycle_manager as cm

    cfg = _baseline()
    state = {
        "bot_id": 7,
        "cycle_id": 2,
        "quote_balance": 500.0,
        "base_balance": 5.0,
        "initial_allocation_done": True,
        "dynamic_snapshot": {},
    }
    decision = DynamicParamDecision(
        decision_id="multiplier-integration",
        symbol="SOLUSDT",
        timestamp=1,
        run_source="dynamic_round_start",
        final_action=FinalAction.BALANCED_GRID.value,
        deployable=True,
        param_score=80,
        confidence_score=85,
        risk_score=20,
        regime_tag="R1",
        risk_state="NORMAL",
        selected_profile_name="R1_TEST",
        selected_profile_bucket="STD",
        params=make_bot_params(
            buy_grid_count=2,
            sell_grid_count=2,
            buy_qty_distribution=[0.5, 0.5],
            sell_qty_distribution=[0.5, 0.5],
        ),
        safety_gates=[],
        blocking_reasons=[],
        warnings=[],
        explain="integration",
        telemetry={
            "indicators": _indicators("up", 50.0),
            "sub_scores": {"data_quality_score": 90},
            "v6_display": {"scenario_identity": {"regime_id": "R1"}},
        },
    )
    features = SimpleNamespace(data_fresh=True, error=None, to_dict=lambda: {})
    market = SimpleNamespace(ticker_price=100.0)
    portfolio = SimpleNamespace(
        total_equity_usdt=1000.0,
        quote_value_usdt=500.0,
        base_value_usdt=500.0,
        current_base_exposure_frac=0.5,
    )
    engine = MagicMock()
    engine.calculate_decision.return_value = decision

    with patch.object(cm, "collect_features", new=AsyncMock(return_value=features)), patch.object(
        cm, "collect_market_data", new=AsyncMock(return_value=market)
    ), patch.object(cm, "portfolio_from_bot_state", return_value=portfolio), patch.object(
        cm, "get_dps_engine", return_value=engine
    ):
        snapshot = asyncio.run(cm.build_snapshot(state, cfg, price=100.0))

    # Live path uses absolute PA overlay (regime_multiplier no longer applied).
    assert snapshot["applied"].get("plan_source") == "param_assistant_absolute"
    assert snapshot["pa_plan"]["source"] == "param_assistant_absolute"
    assert snapshot["round_pending"] is False
    assert state["target_budgets"]["source"] == "param_assistant_absolute"
    assert state["target_budgets"]["target_base_usdt"] == pytest.approx(
        snapshot["applied"]["base_alloc_pct"] * 10.0,
        abs=0.02,
    )


def test_legacy_structural_reference_is_upgraded_without_losing_original_rows():
    from app.botengine.dynamic import cycle_manager as cm

    cfg = _baseline()
    state = {
        "cycle_id": 4,
        "_dynamic_reference": {
            "_source": "param_assistant",
            "_schema_version": 1,
            "base_alloc_pct": 45.0,
            "quote_alloc_pct": 55.0,
            "buy_grids": copy.deepcopy(cfg["buy_grids"]),
            "sell_grids": copy.deepcopy(cfg["sell_grids"]),
        },
    }
    resolved = cm._reference_cfg(state, cfg)
    assert state["_dynamic_reference"]["_schema_version"] == 2
    assert resolved["base_alloc_pct"] == 45.0
    assert resolved["buy_grids"] == cfg["buy_grids"]
    assert resolved["profit_exit_rise_pct"] == cfg["profit_exit_rise_pct"]
    assert resolved["max_base_exposure_frac"] == cfg["max_base_exposure_frac"]


def test_real_v6_telemetry_is_accepted_without_using_its_absolute_grid_shape():
    from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
    from tests.dynamic_param_score.factories import (
        make_constraints,
        make_context,
        make_market_bundle,
        make_portfolio_state,
    )

    constraints = make_constraints()
    portfolio = make_portfolio_state(budget_usdt=1000.0, base_exposure_frac=0.50)
    decision = DynamicParamScoreEngine().calculate_decision(
        "SOLUSDT",
        make_market_bundle(
            symbol="SOLUSDT",
            pattern="trending_up",
        ),
        portfolio,
        constraints,
        make_context(
            run_source="dynamic_round_start",
            budget_usdt=1000.0,
            is_first_start=False,
            current_round_id="2",
        ),
    )
    overlay, meta = build_regime_multiplier_overlay(
        _baseline(),
        decision,
        constraints=constraints,
        portfolio=portfolio,
    )
    assert meta["regime"] in REGIME_POLICIES
    assert meta["confidence"]["indicator_coverage"] > 0.5
    assert len(overlay["buy_grids"]) == len(_baseline()["buy_grids"])
    assert len(overlay["sell_grids"]) == len(_baseline()["sell_grids"])


def test_randomized_baselines_hold_all_numeric_invariants():
    rng = random.Random(20260718)
    regimes = sorted(REGIME_POLICIES)
    for case in range(80):
        buy_n = 1 + case % 7
        sell_n = 1 + (case * 3) % 7
        base_pct = rng.uniform(5.0, 95.0)
        baseline = _baseline()
        baseline["base_alloc_pct"] = base_pct
        baseline["quote_alloc_pct"] = 100.0 - base_pct
        baseline["max_buy_levels"] = buy_n
        baseline["buy_grids"] = [
            {
                "buy_grid_pct": round((i + 1) * rng.uniform(0.5, 2.0), 4),
                "buy_qty_pct_of_quote": rng.uniform(0.1, 100.0),
            }
            for i in range(buy_n)
        ]
        baseline["sell_grids"] = [
            {
                "sell_grid_pct": round((i + 1) * rng.uniform(0.5, 2.0), 4),
                "sell_qty_pct_of_base": rng.uniform(0.1, 100.0),
            }
            for i in range(sell_n)
        ]
        regime = regimes[case % len(regimes)]
        overlay, meta = build_regime_multiplier_overlay(
            baseline,
            _decision(
                regime,
                direction="down" if regime in {"R7", "R8"} else "up",
                volatility=float((case * 17) % 101),
                confidence=20 + case % 76,
            ),
            constraints=_constraints(),
            portfolio=SimpleNamespace(total_equity_usdt=5000.0),
        )

        assert len(overlay["buy_grids"]) == buy_n
        assert len(overlay["sell_grids"]) == sell_n
        assert meta["grid_count_invariant"]["preserved"] is True
        assert overlay["base_alloc_pct"] + overlay["quote_alloc_pct"] == pytest.approx(100.0)
        assert sum(g["buy_qty_pct_of_quote"] for g in overlay["buy_grids"]) == pytest.approx(100.0)
        assert sum(g["sell_qty_pct_of_base"] for g in overlay["sell_grids"]) == pytest.approx(100.0)
        assert [g["buy_grid_pct"] for g in overlay["buy_grids"]] == sorted(
            g["buy_grid_pct"] for g in overlay["buy_grids"]
        )
        assert [g["sell_grid_pct"] for g in overlay["sell_grids"]] == sorted(
            g["sell_grid_pct"] for g in overlay["sell_grids"]
        )
        assert overlay["buy_trigger_trailing_pct"] <= overlay["buy_grids"][0]["buy_grid_pct"] * 0.45 + 1e-4
        assert overlay["sell_trigger_trailing_pct"] <= overlay["sell_grids"][0]["sell_grid_pct"] * 0.45 + 1e-4
        assert overlay["profit_reentry_rise_pct"] <= overlay["profit_reentry_drop_pct"] * 0.45 + 1e-4
        assert overlay["profit_exit_drop_pct"] <= overlay["profit_exit_rise_pct"] * 0.45 + 1e-4
