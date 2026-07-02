"""BTCUSDT low-vol defensive regression — A1|R3|S1|V3|DEFENSIVE must not raw-present NORMAL."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.dynamic_param_score.models import (
    ExchangeConstraints,
    IndicatorSnapshot,
    PortfolioState,
    RegimeTag,
    RiskState,
    SubScores,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    market_signature_v4_from_live,
)
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.param_pool.sqlite_store import (
    DEFAULT_V4_SELECTION_INDEX_PATH,
    DEFAULT_V4_SQLITE_PATH,
)

V4_SQLITE = Path(DEFAULT_V4_SQLITE_PATH)
V4_INDEX = Path(DEFAULT_V4_SELECTION_INDEX_PATH)
HAS_V4_POOL = V4_SQLITE.exists() and V4_INDEX.exists()

TARGET_ROUTE = "A1|R3|S1|V3|DEFENSIVE"
NORMAL_SIBLING = "A1|R3|S1|V3|NORMAL"


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 pool not on disk")
def test_btc_low_vol_defensive_route_classification():
    sig = market_signature_v4_from_live(
        symbol="BTCUSDT",
        budget=500.0,
        regime=RegimeTag.RANGE_LOW_VOL.value,
        risk_level="DEFENSIVE",
        volatility_percentile=35.0,
        lower_lows=False,
        higher_highs=False,
        fee_efficiency_score=55,
        atr_1h_pct=0.8,
        spread_pct=0.02,
    )
    rk = str(sig.get("route_key") or "")
    assert "DEFENSIVE" in rk or sig.get("risk_class") == "DEFENSIVE"


@pytest.mark.skipif(not HAS_V4_POOL, reason="V4 pool not on disk")
def test_defensive_low_vol_not_raw_normal_without_overlay():
    """Regression: exact DEFENSIVE empty → must not present NORMAL as full-score defensive."""
    import json

    index = json.loads(V4_INDEX.read_text(encoding="utf-8"))
    by_route = index.get("index_by_route_key") or index.get("route_index") or {}
    exact_def = len(by_route.get(TARGET_ROUTE) or [])
    normal_sib = len(by_route.get(NORMAL_SIBLING) or [])

    sig = market_signature_v4_from_live(
        symbol="BTCUSDT",
        budget=500.0,
        regime=RegimeTag.RANGE_LOW_VOL.value,
        risk_level="DEFENSIVE",
        volatility_percentile=35.0,
        lower_lows=False,
        higher_highs=False,
        fee_efficiency_score=55,
        atr_1h_pct=0.8,
        spread_pct=0.02,
    )
    sig["route_key"] = TARGET_ROUTE
    sig["risk_class"] = "DEFENSIVE"

    sub = SubScores(
        trend_score=50,
        volatility_score=35,
        range_score=55,
        liquidity_score=85,
        spread_score=75,
        fee_efficiency_score=55,
        exposure_safety_score=60,
        data_quality_score=85,
        btc_market_risk_score=50,
        drawdown_risk_score=45,
        mean_reversion_score=50,
    )
    ind = IndicatorSnapshot(
        orderbook_spread_pct=0.02,
        atr14_pct_1h=0.8,
        lower_lows=False,
        higher_highs=False,
    )
    portfolio = PortfolioState(
        total_equity_usdt=500.0,
        quote_balance=300.0,
        quote_value_usdt=300.0,
        base_balance=0.01,
        base_value_usdt=200.0,
        current_base_exposure_frac=0.40,
    )
    constraints = ExchangeConstraints(
        min_notional=5.0,
        step_size=0.00001,
        tick_size=0.01,
        min_qty=0.00001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )

    sel = select_template(
        param_score=55,
        regime=RegimeTag.RANGE_LOW_VOL,
        risk_state=RiskState.DEFENSIVE.value,
        sub=sub,
        ind=ind,
        portfolio=portfolio,
        constraints=constraints,
        budget_usdt=500.0,
        min_notional=5.0,
        symbol="BTCUSDT",
    )
    ctx = sel.selection_context or {}

    if exact_def == 0 and normal_sib > 0:
        assert ctx.get("defensive_fallback_overlay") is True, (
            "DEFENSIVE shelf empty but overlay not applied"
        )
        assert ctx.get("selection_type") in ("CLAMPED_FALLBACK", "SAFE_FALLBACK", "EXACT")
        suit = ctx.get("route_suitability_score")
        if suit is not None:
            assert float(suit) <= 0.65, f"route suitability too high for clamped fallback: {suit}"
        prof_score = ctx.get("selected_profile_score")
        if suit is not None and prof_score is not None:
            assert float(suit) <= float(prof_score) + 0.01 or float(suit) < 0.70
    else:
        assert int(ctx.get("exact_route_candidate_count") or 0) > 0 or sel.template is not None
