"""Live-style sample route tests for audit evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.models import (
    BotContext,
    ExchangeConstraints,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    SubScores,
)
from app.services.dynamic_param_score.v5.bridge import v5_select_and_render
from app.services.dynamic_param_score.v5.index.route_lookup import V5RouteIndex
from app.services.dynamic_param_score.v5.live_route_classifier_v5 import classify_live_route_v5
from app.services.dynamic_param_score.v5.validator.shelf_validator import validate_shelf


@dataclass
class LiveSampleSpec:
    name: str
    symbol: str
    regime_tag: str
    risk_state: str
    expected_regime_code: str
    sub_overrides: Dict[str, int]
    ind_overrides: Dict[str, Any]


SAMPLES = [
    LiveSampleSpec(
        "BTCUSDT low-vol squeeze defensive",
        "BTCUSDT",
        RegimeTag.RANGE_LOW_VOL.value,
        "DEFENSIVE",
        "R3",
        {"volatility_score": 22, "liquidity_score": 80, "spread_score": 75, "data_quality_score": 80},
        {
            "return_24h_pct": 0.6,
            "atr14_pct_5m": 0.08,
            "atr14_pct_1h": 0.35,
            "volatility_percentile": 18,
            "price_in_bb": 0.55,
            "higher_highs": False,
            "lower_lows": False,
        },
    ),
    LiveSampleSpec(
        "BTCUSDT crash defensive",
        "BTCUSDT",
        RegimeTag.TRENDING_DOWN.value,
        "DEFENSIVE",
        "R8",
        {"volatility_score": 70, "liquidity_score": 75},
        {"return_24h_pct": -9.0, "atr14_pct_5m": 0.5, "atr14_pct_1h": 2.5, "crash_velocity": -2.0},
    ),
    LiveSampleSpec(
        "ETHUSDT balanced range normal",
        "ETHUSDT",
        RegimeTag.BALANCED_RANGE.value,
        "NORMAL",
        "R2",
        {"volatility_score": 50, "liquidity_score": 78},
        {"return_24h_pct": 0.8, "atr14_pct_5m": 0.2, "atr14_pct_1h": 1.3, "price_in_bb": 0.5, "volatility_percentile": 48},
    ),
    LiveSampleSpec(
        "major alt high-vol defensive",
        "SOLUSDT",
        RegimeTag.RANGE_HIGH_VOL.value,
        "DEFENSIVE",
        "R4",
        {"volatility_score": 78, "liquidity_score": 72},
        {"return_24h_pct": 2.0, "atr14_pct_5m": 0.4, "atr14_pct_1h": 3.2, "price_in_bb": 0.6, "volatility_percentile": 72},
    ),
    LiveSampleSpec(
        "meme coin shock volatility defensive",
        "DOGEUSDT",
        RegimeTag.HIGH_VOL_UNSTABLE.value,
        "DEFENSIVE",
        "R13",
        {"volatility_score": 85, "liquidity_score": 55},
        {
            "return_24h_pct": -3.5,
            "atr14_pct_5m": 0.8,
            "atr14_pct_1h": 5.5,
            "price_in_bb": 0.3,
            "volatility_percentile": 85,
        },
    ),
    LiveSampleSpec(
        "low-liquidity alt L4 execution risky",
        "ACMUSDT",
        RegimeTag.LOW_LIQUIDITY.value,
        "DEFENSIVE",
        "L4",
        {"volatility_score": 60, "liquidity_score": 25, "spread_score": 20},
        {"return_24h_pct": -1.0, "atr14_pct_5m": 0.3, "atr14_pct_1h": 1.8, "orderbook_spread_pct": 0.6},
    ),
    LiveSampleSpec(
        "R15 special stress transition",
        "BTCUSDT",
        RegimeTag.DUMP_RISK.value,
        "DEFENSIVE",
        "R15",
        {"volatility_score": 50, "btc_market_risk_score": 40, "data_quality_score": 80},
        {
            "return_24h_pct": -1.2,
            "btc_crash_velocity": -0.88,
            "crash_velocity": -0.85,
            "drawdown_7d_pct": 6,
            "volatility_percentile": 45,
            "lower_lows": False,
            "higher_highs": False,
        },
    ),
    LiveSampleSpec(
        "R17 data uncertain",
        "ETHUSDT",
        RegimeTag.NO_DATA.value,
        "DEFENSIVE",
        "R17",
        {"data_quality_score": 30, "volatility_score": 50},
        {"return_24h_pct": 0.0, "atr14_pct_5m": 0.15, "atr14_pct_1h": 1.0},
    ),
]


def _make_sub(overrides: Dict[str, int]) -> SubScores:
    base = dict(
        range_score=60,
        liquidity_score=70,
        spread_score=70,
        fee_efficiency_score=70,
        volatility_score=50,
        data_quality_score=80,
        btc_market_risk_score=50,
        exposure_safety_score=60,
    )
    base.update(overrides)
    return SubScores(**base)


def _make_ind(overrides: Dict[str, Any]) -> IndicatorSnapshot:
    ind = IndicatorSnapshot(
        return_24h_pct=overrides.get("return_24h_pct", 0.5),
        atr14_pct_5m=overrides.get("atr14_pct_5m", 1.0),
        atr14_pct_1h=overrides.get("atr14_pct_1h", 1.2),
        orderbook_spread_pct=overrides.get("orderbook_spread_pct", 0.1),
        rsi14_1h=overrides.get("rsi14_1h", 50),
        price_in_bb=overrides.get("price_in_bb", 0.5),
        volatility_percentile=overrides.get("volatility_percentile"),
    )
    for k, v in overrides.items():
        if hasattr(ind, k):
            setattr(ind, k, v)
    return ind


def _route_regime_code(route_key: str) -> str:
    parts = route_key.split("|")
    return parts[1] if len(parts) > 1 else ""


def _route_liquidity_code(route_key: str) -> str:
    parts = route_key.split("|")
    return parts[6] if len(parts) > 6 else ""


def run_live_samples(index: V5RouteIndex) -> dict:
    results: List[dict] = []
    regime_mismatches: List[dict] = []

    for spec in SAMPLES:
        sub = _make_sub(spec.sub_overrides)
        ind = _make_ind(spec.ind_overrides)
        portfolio = PortfolioState(
            base_balance=0.002,
            quote_balance=400,
            base_value_usdt=100,
            quote_value_usdt=400,
            total_equity_usdt=500,
            current_base_exposure_frac=0.2,
        )
        constraints = ExchangeConstraints(
            min_notional=10,
            step_size=0.0001,
            tick_size=0.01,
            min_qty=0.0001,
            maker_fee_pct=0.1,
            taker_fee_pct=0.1,
            estimated_slippage_pct=0.05,
        )
        ctx = BotContext(run_source="param_assistant", budget_usdt=500, bot_id=1)
        regime = RegimeTag(spec.regime_tag) if spec.regime_tag in [e.value for e in RegimeTag] else RegimeTag.BALANCED_RANGE

        classification = classify_live_route_v5(
            symbol=spec.symbol,
            regime_tag=regime.value,
            risk_state=spec.risk_state,
            sub=sub,
            ind=ind,
        )

        sel, params, bucket = v5_select_and_render(
            65,
            regime,
            spec.risk_state,
            sub,
            ind,
            portfolio,
            constraints,
            ctx,
            500,
            10,
            symbol=spec.symbol,
        )
        sc = sel.selection_context or {}
        shelf_id = sel.selected_template_key or ""
        route = sc.get("route_key", "")
        shelf = index.get(route)
        val_ok = True
        if shelf:
            val_ok = validate_shelf(shelf).ok

        actual_regime = _route_regime_code(route)
        expected = spec.expected_regime_code
        ok_regime = actual_regime == expected or (
            expected == "L4" and _route_liquidity_code(route) == "L4"
        )
        if not ok_regime:
            regime_mismatches.append(
                {
                    "name": spec.name,
                    "expected_regime_code": expected,
                    "actual_regime_code": actual_regime,
                    "route_key": route,
                    "classification_reason": classification.classification_reason,
                }
            )

        vol_code = route.split("|")[4] if "|" in route else ""
        if spec.name == "meme coin shock volatility defensive" and vol_code != "V5":
            regime_mismatches.append(
                {
                    "name": spec.name,
                    "expected_vol_code": "V5",
                    "actual_vol_code": vol_code,
                    "route_key": route,
                }
            )
            ok_regime = False

        r15_evidence = None
        if expected == "R15" and shelf:
            r15_evidence = {
                "forbidden_fallbacks": shelf.fallback_policy.forbidden_fallbacks,
                "nearest_safe_dimensions": shelf.fallback_policy.nearest_safe_dimensions,
                "fallback_family": shelf.fallback_policy.fallback_family,
            }

        results.append(
            {
                "name": spec.name,
                "symbol": spec.symbol,
                "expected_regime_code": expected,
                "actual_regime_code": actual_regime,
                "actual_vol_code": vol_code,
                "regime_match": ok_regime,
                "route_key": route,
                "shelf_id": shelf_id,
                "selection_type": sc.get("selection_type"),
                "exact_hit": sc.get("exact_route_hit"),
                "fallback_used": sel.fallback_used,
                "classification_reason": classification.classification_reason,
                "sell_grids": params.sell_grid_ladder_pcts if params else [],
                "buy_grids": params.buy_grid_ladder_pcts if params else [],
                "target_base_pct": round(params.base_alloc_frac * 100, 2) if params else None,
                "target_quote_pct": round(params.quote_alloc_frac * 100, 2) if params else None,
                "max_exposure_pct": round(params.max_base_exposure_frac * 100, 2) if params else None,
                "trailing_pct": params.trailing_callback_pct if params else None,
                "validator_ok": val_ok,
                "reasoning": (shelf.base_template.grid_reasoning.get("reason") if shelf else None),
                "v4_leak": "DPLV4_" in shelf_id,
                "r15_fallback_policy": r15_evidence,
            }
        )

    v4_leaks = [r for r in results if r.get("v4_leak")]
    non_exact = [r for r in results if not r.get("exact_hit")]

    return {
        "samples": results,
        "regime_mismatches": regime_mismatches,
        "v4_leak_count": len(v4_leaks),
        "non_exact_count": len(non_exact),
        "pass_audit": (
            not v4_leaks
            and not non_exact
            and not regime_mismatches
            and all(r["validator_ok"] for r in results)
        ),
    }
