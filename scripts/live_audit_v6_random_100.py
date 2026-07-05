#!/usr/bin/env python3
"""Live Dynamic Param V6 random USDT audit.

This script is an audit tool, not a trading recommender. It checks whether V6
outputs match live market data, budget feasibility, liquidity, and display
semantics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.data_collector import collect_market_data
from app.services.dynamic_param_score.indicators import compute_indicators
from app.services.dynamic_param_score.models import ExchangeConstraints
from app.services.dynamic_param_score.models import BtcReferenceData, Candle, MarketDataBundle
from app.services.dynamic_param_score.v6.engine import V6Engine
from app.services.dynamic_param_score.v6.v6_botparams_adapter import (
    v6_final_to_bot_params,
    v6_final_to_telemetry_extras,
)
from app.services.dynamic_param_score.v6.v6_indicator_adapter import build_v6_input_contract
from app.services.dynamic_param_score.v6.v6_pa_display import enrich_v6_display
from app.services.dynamic_param_score.v6.domain.types import V6InputContract
from app.services.binance_spot import get_cached_symbol_filters, get_cached_trading_symbols


AUDIT_TITLE = "V6 Random 100 x 3 Budget Audit"
STABLE_OR_FIAT_USDT = {
    "USDCUSDT",
    "FDUSDUSDT",
    "TUSDUSDT",
    "BUSDUSDT",
    "USDPUSDT",
    "EURUSDT",
    "TRYUSDT",
}
TEST_ACCOUNT_BUCKET_ORDER = (
    "high_liquidity",
    "mid_liquidity",
    "low_liquidity",
    "high_volatility",
    "high_spread",
)
BUCKET_TARGETS = {
    "high_liquidity": 20,
    "mid_liquidity": 25,
    "low_liquidity": 25,
    "high_volatility": 15,
    "high_spread": 15,
}
REQUIRED_ARTIFACTS = [
    "live_audit_raw_results.json",
    "live_audit_summary.md",
    "live_audit_failures.md",
    "live_audit_by_budget.md",
    "live_audit_by_regime.md",
    "live_audit_by_liquidity_bucket.md",
    "live_audit_selected_symbols.txt",
    "live_audit_replay_snapshots.jsonl",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def pct(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def return_pct(candles: Sequence[Candle], n: int) -> Optional[float]:
    if len(candles) < n + 1:
        return None
    a = float(candles[-n - 1].c or 0)
    b = float(candles[-1].c or 0)
    if a <= 0:
        return None
    return (b - a) / a * 100.0


def dec_floor(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    v = Decimal(str(max(value, 0.0)))
    s = Decimal(str(step))
    return float((v / s).to_integral_value(rounding=ROUND_DOWN) * s)


def constraints_from_filters(filters: Optional[Dict[str, Any]]) -> ExchangeConstraints:
    filters = filters or {}
    return ExchangeConstraints(
        min_notional=float(filters.get("min_notional") or 10.0),
        step_size=float(filters.get("step_size") or 0.00001),
        tick_size=float(filters.get("tick_size") or 0.01),
        min_qty=float(filters.get("min_qty") or 0.00001),
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )


def active_usdt_universe(symbols: Iterable[str], market: str = "USDT") -> List[str]:
    out: List[str] = []
    suffix = market.upper()
    for raw in symbols:
        sym = str(raw or "").upper().strip()
        if not sym.endswith(suffix):
            continue
        if sym in STABLE_OR_FIAT_USDT:
            continue
        if any(sym.endswith(x) for x in ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")):
            continue
        out.append(sym)
    return sorted(set(out))


def liquidity_level(ind: Dict[str, Any], fragility: str = "") -> str:
    spread = pct(ind.get("orderbook_spread_pct"))
    volume = pct(ind.get("quote_volume_24h"))
    consistency = pct(ind.get("volume_consistency"), 0.5)
    zero = pct(ind.get("zero_volume_ratio"))
    frag = str(fragility or "").upper()
    strong = (
        spread >= 0.50
        or (spread >= 0.10 and volume < 1_000_000)
        or (consistency < 0.25 and zero > 0.01)
        or (frag == "F3" and volume < 1_000_000)
    )
    if strong:
        return "L3_NO_DEPLOY"
    if spread >= 0.10 or volume < 1_000_000 or consistency < 0.35:
        return "L2_RESTRICTED"
    if spread >= 0.03 or volume < 10_000_000 or consistency < 0.55:
        return "L1_CAUTION"
    return "L0_NORMAL"


def selection_bucket(ind: Dict[str, Any], fragility: str = "") -> str:
    spread = pct(ind.get("orderbook_spread_pct"))
    volume = pct(ind.get("quote_volume_24h"))
    consistency = pct(ind.get("volume_consistency"), 0.5)
    zero = pct(ind.get("zero_volume_ratio"))
    volp = pct(ind.get("volatility_percentile"))
    atr = pct(ind.get("atr14_pct_1h"))
    frag = str(fragility or "").upper()
    if spread >= 0.10 or consistency < 0.25 or zero > 0.01 or (frag == "F3" and volume < 1_000_000):
        return "high_spread"
    if volp >= 70 or atr >= 3.0:
        return "high_volatility"
    if volume >= 50_000_000 and spread <= 0.03:
        return "high_liquidity"
    if volume >= 5_000_000:
        return "mid_liquidity"
    return "low_liquidity"


def snapshot_is_usable(market: Any, ind: Dict[str, Any], filters: Dict[str, Any]) -> Tuple[bool, str]:
    counts = {
        "5m": len(market.candles_5m or []),
        "15m": len(market.candles_15m or []),
        "1h": len(market.candles_1h or []),
    }
    if counts["5m"] < 2016 or counts["15m"] < 672 or counts["1h"] < 240:
        return False, f"insufficient_candles:{counts}"
    if pct(market.ticker_price) <= 0:
        return False, "price_invalid"
    if not filters or pct(filters.get("min_notional")) <= 0:
        return False, "missing_exchange_filters"
    if pct(ind.get("zero_volume_ratio")) > 0.50:
        return False, "zero_volume_too_high"
    return True, "ok"


def snapshot_payload(symbol: str, market: Any, ind: Any, filters: Dict[str, Any], contract: Any) -> Dict[str, Any]:
    ind_dict = ind.to_dict()
    ob = market.orderbook_top or {}
    return {
        "symbol": symbol,
        "fetch_timestamp_utc": utc_now_iso(),
        "price": market.ticker_price,
        "spread_pct": ind_dict.get("orderbook_spread_pct"),
        "volume_24h": ind_dict.get("quote_volume_24h"),
        "volume_consistency": ind_dict.get("volume_consistency"),
        "zero_volume_ratio": ind_dict.get("zero_volume_ratio"),
        "candle_counts": {
            "5m": len(market.candles_5m or []),
            "15m": len(market.candles_15m or []),
            "1h": len(market.candles_1h or []),
            "4h": len(market.candles_4h or []),
            "1m": len(market.candles_1m or []),
        },
        "data_freshness_seconds": ind_dict.get("data_freshness_sec"),
        "exchange_filters": filters,
        "orderbook_top": ob,
        "all_46_indicators": ind_dict,
        "btc_context_snapshot": {
            "btc_return_1h": ind_dict.get("btc_return_1h"),
            "btc_return_4h": ind_dict.get("btc_return_4h"),
            "btc_return_24h": ind_dict.get("btc_return_24h"),
            "btc_below_ema200": ind_dict.get("btc_below_ema200"),
            "btc_crash_velocity": ind_dict.get("btc_crash_velocity"),
        },
        "asset_fragility_class": getattr(contract, "asset_fragility_class", ""),
    }


def indicator_dict_from_contract(inp: V6InputContract) -> Dict[str, Any]:
    return {
        "adx_1h": inp.adx_1h,
        "rsi14_5m": inp.rsi_5m,
        "rsi14_1h": inp.rsi_1h,
        "ema20_slope_5m": inp.ema20_slope,
        "ema50_slope_5m": inp.ema50_slope,
        "ema20_5m": inp.ema20_5m,
        "ema50_5m": inp.ema50_5m,
        "ema200_1h": inp.ema200_1h,
        "price_vs_ema200_pct": inp.price_vs_ema200_pct,
        "roc_5m": inp.roc_5m,
        "higher_highs": inp.higher_highs,
        "lower_lows": inp.lower_lows,
        "atr14_pct_5m": inp.atr_5m_pct,
        "atr14_pct_1h": inp.atr_1h_pct,
        "realized_vol_24h": inp.vol_24h,
        "realized_vol_7d": inp.vol_7d,
        "volatility_percentile": inp.volatility_percentile,
        "bb_width_5m": inp.bb_width,
        "price_in_bb": inp.bb_position,
        "z_score_5m": inp.z_score,
        "mean_reversion_ratio": inp.mean_reversion_score,
        "range_stability": inp.range_stability,
        "high_low_range_pct": inp.hl_range_pct,
        "return_1h_pct": inp.return_1h_pct,
        "return_4h_pct": inp.return_4h_pct,
        "return_24h_pct": inp.return_24h_pct,
        "drawdown_7d_pct": inp.drawdown_7d_pct,
        "drawdown_30d_pct": inp.drawdown_30d_pct,
        "crash_velocity": inp.crash_velocity,
        "consecutive_red_pressure": inp.red_pressure,
        "orderbook_spread_pct": inp.spread_pct,
        "quote_volume_24h": inp.volume_24h,
        "volume_consistency": inp.volume_consistency,
        "volume_spike_abnormality": inp.volume_spike,
        "zero_volume_ratio": 0.05 if inp.zero_volume_flag else 0.0,
        "btc_return_1h": inp.btc_return_1h_pct,
        "btc_return_4h": inp.btc_return_4h_pct,
        "btc_return_24h": inp.btc_return_24h_pct,
        "btc_below_ema200": inp.btc_ema200_below,
        "btc_crash_velocity": inp.btc_crash_velocity,
        "data_freshness_sec": inp.data_freshness_sec,
        "data_gap_sec": inp.data_gap_sec,
        "candle_count_5m": inp.candles_5m,
        "candle_count_15m": inp.candles_15m,
        "candle_count_1h": inp.candles_1h,
        "price_valid": inp.price_valid,
        "support_distance_pct": inp.support_distance_pct,
        "resistance_distance_pct": inp.resistance_distance_pct,
        "support_strength_score": inp.support_strength_score,
        "resistance_strength_score": inp.resistance_strength_score,
        "pump_score": inp.pump_score,
        "dump_score": inp.dump_score,
        "fake_bounce_score": inp.fake_bounce_score,
        "fake_breakout_score": inp.fake_breakout_score,
    }


def _test_account_base_contract(symbol: str, index: int, bucket: str) -> V6InputContract:
    price = round(0.25 + (index % 37) * 2.73, 4)
    common: Dict[str, Any] = {
        "symbol": symbol,
        "bot_budget_usdt": 100.0,
        "current_price": price,
        "min_notional": 5.0,
        "tick_size": 0.0001 if price < 1 else 0.01,
        "step_size": 0.1 if price < 1 else 0.001,
        "price_precision": 8,
        "quantity_precision": 8,
        "price_valid": True,
        "candles_5m": 2016,
        "candles_15m": 672,
        "candles_1h": 240,
        "data_freshness_sec": 15.0,
        "data_gap_sec": 0.0,
        "btc_return_1h_pct": 0.2,
        "btc_return_4h_pct": 0.7,
        "btc_return_24h_pct": 1.8,
        "btc_crash_velocity": -0.25,
        "btc_ema200_below": False,
        "volume_spike": 1.4,
        "zero_volume_flag": 0,
    }
    flavor = index % 10
    if bucket == "high_liquidity":
        common.update(
            adx_1h=34.0 + flavor,
            rsi_5m=62.0,
            rsi_1h=64.0,
            ema20_slope=0.48,
            ema50_slope=0.31,
            price_vs_ema200_pct=4.5 + flavor * 0.3,
            roc_5m=0.9,
            higher_highs=True,
            lower_lows=False,
            atr_5m_pct=0.45,
            atr_1h_pct=1.1,
            vol_24h=0.8,
            vol_7d=1.2,
            volatility_percentile=42.0,
            bb_width=2.0,
            bb_position=0.68,
            z_score=0.8,
            mean_reversion_score=0.28,
            range_stability=0.55,
            hl_range_pct=0.45,
            return_1h_pct=0.8,
            return_4h_pct=2.2,
            return_24h_pct=5.5,
            drawdown_7d_pct=1.5,
            drawdown_30d_pct=4.0,
            crash_velocity=-0.25,
            red_pressure=0.0,
            spread_pct=0.01,
            volume_24h=250_000_000.0 + index * 1_000_000,
            volume_consistency=0.92,
            asset_fragility_class="F0",
        )
    elif bucket == "mid_liquidity":
        common.update(
            adx_1h=18.0,
            rsi_5m=51.0,
            rsi_1h=52.0,
            ema20_slope=0.05,
            ema50_slope=0.02,
            price_vs_ema200_pct=0.8,
            roc_5m=0.12,
            higher_highs=False,
            lower_lows=False,
            atr_5m_pct=0.28,
            atr_1h_pct=0.75,
            vol_24h=0.45,
            vol_7d=0.7,
            volatility_percentile=24.0,
            bb_width=0.9,
            bb_position=0.52,
            z_score=0.12,
            mean_reversion_score=0.62,
            range_stability=0.76,
            hl_range_pct=0.18,
            return_1h_pct=0.08,
            return_4h_pct=0.25,
            return_24h_pct=0.9,
            drawdown_7d_pct=2.2,
            drawdown_30d_pct=3.8,
            crash_velocity=-0.18,
            red_pressure=0.1,
            spread_pct=0.02,
            volume_24h=18_000_000.0 + index * 100_000,
            volume_consistency=0.74,
            asset_fragility_class="F1",
        )
    elif bucket == "low_liquidity":
        common.update(
            adx_1h=19.0,
            rsi_5m=49.0,
            rsi_1h=50.0,
            ema20_slope=-0.03,
            ema50_slope=0.01,
            price_vs_ema200_pct=-0.5,
            roc_5m=-0.08,
            higher_highs=False,
            lower_lows=False,
            atr_5m_pct=0.65,
            atr_1h_pct=1.4,
            vol_24h=0.9,
            vol_7d=1.5,
            volatility_percentile=36.0,
            bb_width=2.2,
            bb_position=0.47,
            z_score=-0.18,
            mean_reversion_score=0.48,
            range_stability=0.52,
            hl_range_pct=0.55,
            return_1h_pct=-0.1,
            return_4h_pct=-0.4,
            return_24h_pct=-1.0,
            drawdown_7d_pct=5.0,
            drawdown_30d_pct=8.0,
            crash_velocity=-0.45,
            red_pressure=0.2,
            spread_pct=0.04,
            volume_24h=2_200_000.0 + index * 10_000,
            volume_consistency=0.52,
            asset_fragility_class="F1",
        )
    elif bucket == "high_volatility":
        if flavor < 5:
            common.update(
                adx_1h=38.0,
                rsi_5m=68.0,
                rsi_1h=70.0,
                ema20_slope=0.95,
                ema50_slope=0.58,
                price_vs_ema200_pct=12.0,
                roc_5m=2.4,
                higher_highs=True,
                lower_lows=False,
                atr_5m_pct=1.8,
                atr_1h_pct=3.4,
                vol_24h=2.8,
                vol_7d=3.2,
                volatility_percentile=84.0,
                bb_width=5.5,
                bb_position=0.78,
                z_score=1.35,
                mean_reversion_score=0.2,
                range_stability=0.33,
                hl_range_pct=1.8,
                return_1h_pct=1.9,
                return_4h_pct=5.5,
                return_24h_pct=14.0,
                drawdown_7d_pct=3.0,
                drawdown_30d_pct=6.0,
                crash_velocity=-0.9,
                red_pressure=0.0,
                spread_pct=0.035,
                volume_24h=32_000_000.0 + index * 50_000,
                volume_consistency=0.70,
                asset_fragility_class="F1",
                pump_score=35.0,
            )
        else:
            common.update(
                adx_1h=23.0,
                rsi_5m=54.0,
                rsi_1h=55.0,
                ema20_slope=0.08,
                ema50_slope=-0.03,
                price_vs_ema200_pct=1.5,
                roc_5m=0.2,
                higher_highs=False,
                lower_lows=True,
                atr_5m_pct=2.0,
                atr_1h_pct=3.8,
                vol_24h=3.2,
                vol_7d=3.6,
                volatility_percentile=82.0,
                bb_width=6.2,
                bb_position=0.42,
                z_score=0.1,
                mean_reversion_score=0.35,
                range_stability=0.25,
                hl_range_pct=2.1,
                return_1h_pct=-0.4,
                return_4h_pct=0.3,
                return_24h_pct=1.5,
                drawdown_7d_pct=7.5,
                drawdown_30d_pct=11.0,
                crash_velocity=-1.0,
                red_pressure=0.3,
                spread_pct=0.04,
                volume_24h=26_000_000.0 + index * 50_000,
                volume_consistency=0.66,
                asset_fragility_class="F1",
            )
    else:
        common.update(
            adx_1h=21.0,
            rsi_5m=47.0,
            rsi_1h=48.0,
            ema20_slope=-0.08,
            ema50_slope=-0.03,
            price_vs_ema200_pct=-1.8,
            roc_5m=-0.3,
            higher_highs=False,
            lower_lows=True,
            atr_5m_pct=1.4,
            atr_1h_pct=2.2,
            vol_24h=1.8,
            vol_7d=2.4,
            volatility_percentile=62.0,
            bb_width=4.0,
            bb_position=0.35,
            z_score=-0.6,
            mean_reversion_score=0.3,
            range_stability=0.18,
            hl_range_pct=1.4,
            return_1h_pct=-0.6,
            return_4h_pct=-1.8,
            return_24h_pct=-4.0,
            drawdown_7d_pct=12.0,
            drawdown_30d_pct=18.0,
            crash_velocity=-1.4,
            red_pressure=0.5,
            spread_pct=0.18,
            volume_24h=550_000.0 + index * 1_000,
            volume_consistency=0.20,
            zero_volume_flag=1,
            asset_fragility_class="F3",
        )
    return V6InputContract(**common)


def test_account_snapshot(symbol: str, index: int, bucket: str) -> Dict[str, Any]:
    contract = _test_account_base_contract(symbol, index, bucket)
    filters = {
        "min_notional": contract.min_notional,
        "step_size": contract.step_size,
        "tick_size": contract.tick_size,
        "min_qty": contract.step_size,
        "max_qty": 1_000_000.0,
        "lot_size": contract.step_size,
    }
    ind = indicator_dict_from_contract(contract)
    spread = float(contract.spread_pct or 0.0)
    bid = contract.current_price * (1 - spread / 200.0)
    ask = contract.current_price * (1 + spread / 200.0)
    return {
        "symbol": symbol,
        "data_source": "test-account",
        "fetch_timestamp_utc": utc_now_iso(),
        "price": contract.current_price,
        "spread_pct": contract.spread_pct,
        "volume_24h": contract.volume_24h,
        "volume_consistency": contract.volume_consistency,
        "zero_volume_ratio": ind["zero_volume_ratio"],
        "candle_counts": {"5m": 2016, "15m": 672, "1h": 240, "4h": 240, "1m": 0},
        "data_freshness_seconds": contract.data_freshness_sec,
        "exchange_filters": filters,
        "orderbook_top": {"bid": round(bid, 8), "ask": round(ask, 8)},
        "all_46_indicators": ind,
        "btc_context_snapshot": {
            "btc_return_1h": contract.btc_return_1h_pct,
            "btc_return_4h": contract.btc_return_4h_pct,
            "btc_return_24h": contract.btc_return_24h_pct,
            "btc_below_ema200": contract.btc_ema200_below,
            "btc_crash_velocity": contract.btc_crash_velocity,
        },
        "asset_fragility_class": contract.asset_fragility_class,
        "selection_bucket": bucket,
        "_filters": filters,
        "_indicator_dict": ind,
        "_v6_contract": contract,
    }


def replay_snapshot_for_audit(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    snap = dict(snapshot)
    ind = dict(snap.get("all_46_indicators") or {})
    filters = dict(snap.get("exchange_filters") or {})
    contract = V6InputContract(
        symbol=str(snap.get("symbol") or "").upper(),
        bot_budget_usdt=100.0,
        current_price=float(snap.get("price") or 0),
        min_notional=float(filters.get("min_notional") or 10.0),
        tick_size=float(filters.get("tick_size") or 0.01),
        step_size=float(filters.get("step_size") or 0.00001),
        price_precision=8,
        quantity_precision=8,
        adx_1h=ind.get("adx_1h"),
        rsi_5m=ind.get("rsi14_5m"),
        rsi_1h=ind.get("rsi14_1h"),
        ema20_slope=ind.get("ema20_slope_5m"),
        ema50_slope=ind.get("ema50_slope_5m"),
        ema20_5m=ind.get("ema20_5m"),
        ema50_5m=ind.get("ema50_5m"),
        ema200_1h=ind.get("ema200_1h"),
        price_vs_ema200_pct=ind.get("price_vs_ema200_pct"),
        roc_5m=ind.get("roc_5m"),
        higher_highs=ind.get("higher_highs"),
        lower_lows=ind.get("lower_lows"),
        atr_5m_pct=ind.get("atr14_pct_5m"),
        atr_1h_pct=ind.get("atr14_pct_1h"),
        vol_24h=ind.get("realized_vol_24h"),
        vol_7d=ind.get("realized_vol_7d"),
        volatility_percentile=ind.get("volatility_percentile"),
        bb_width=ind.get("bb_width_5m"),
        bb_position=ind.get("price_in_bb"),
        z_score=ind.get("z_score_5m"),
        mean_reversion_score=ind.get("mean_reversion_ratio"),
        range_stability=ind.get("range_stability"),
        hl_range_pct=ind.get("high_low_range_pct"),
        return_1h_pct=ind.get("return_1h_pct"),
        return_4h_pct=ind.get("return_4h_pct"),
        return_24h_pct=ind.get("return_24h_pct"),
        drawdown_7d_pct=ind.get("drawdown_7d_pct"),
        drawdown_30d_pct=ind.get("drawdown_30d_pct"),
        crash_velocity=ind.get("crash_velocity"),
        red_pressure=ind.get("consecutive_red_pressure"),
        spread_pct=ind.get("orderbook_spread_pct"),
        volume_24h=ind.get("quote_volume_24h"),
        volume_consistency=ind.get("volume_consistency"),
        volume_spike=ind.get("volume_spike_abnormality"),
        zero_volume_flag=1 if float(ind.get("zero_volume_ratio") or 0) > 0 else 0,
        btc_ema200_below=ind.get("btc_below_ema200"),
        btc_crash_velocity=ind.get("btc_crash_velocity"),
        btc_return_1h_pct=ind.get("btc_return_1h"),
        btc_return_4h_pct=ind.get("btc_return_4h"),
        btc_return_24h_pct=ind.get("btc_return_24h"),
        data_freshness_sec=ind.get("data_freshness_sec") or snap.get("data_freshness_seconds"),
        data_gap_sec=ind.get("data_gap_sec"),
        candles_5m=int((snap.get("candle_counts") or {}).get("5m") or ind.get("candle_count_5m") or 0),
        candles_15m=int((snap.get("candle_counts") or {}).get("15m") or ind.get("candle_count_15m") or 0),
        candles_1h=int((snap.get("candle_counts") or {}).get("1h") or ind.get("candle_count_1h") or 0),
        price_valid=bool(ind.get("price_valid", True)),
        support_distance_pct=ind.get("support_distance_pct"),
        resistance_distance_pct=ind.get("resistance_distance_pct"),
        support_strength_score=ind.get("support_strength_score"),
        resistance_strength_score=ind.get("resistance_strength_score"),
        pump_score=float(ind.get("pump_score") or 0),
        dump_score=float(ind.get("dump_score") or 0),
        fake_bounce_score=float(ind.get("fake_bounce_score") or 0),
        fake_breakout_score=float(ind.get("fake_breakout_score") or 0),
        asset_fragility_class=str(snap.get("asset_fragility_class") or "F1"),
    )
    snap["_filters"] = filters
    snap["_indicator_dict"] = ind
    snap["_v6_contract"] = contract
    return snap


async def select_test_account_symbols(
    *,
    seed: int,
    symbol_count: int,
    market: str,
) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    rng = random.Random(seed)
    buckets: Dict[str, List[str]] = {k: [] for k in BUCKET_TARGETS}
    snapshots: Dict[str, Dict[str, Any]] = {}
    selected: List[str] = []
    index = 0
    for bucket in TEST_ACCOUNT_BUCKET_ORDER:
        for n in range(BUCKET_TARGETS[bucket]):
            index += 1
            stem = {
                "high_liquidity": "TAH",
                "mid_liquidity": "TAM",
                "low_liquidity": "TAL",
                "high_volatility": "TAV",
                "high_spread": "TAS",
            }[bucket]
            sym = f"{stem}{n + 1:03d}{market.upper()}"
            selected.append(sym)
            buckets[bucket].append(sym)
            snapshots[sym] = test_account_snapshot(sym, index, bucket)
    rng.shuffle(selected)
    selected = selected[:symbol_count]
    return selected, {s: snapshots[s] for s in selected}, buckets


async def fetch_symbol_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    filters = await get_cached_symbol_filters(symbol)
    constraints = constraints_from_filters(filters)
    market = await collect_market_data(symbol)
    # Indicators are market-only for this audit; use a neutral 100 USDT portfolio.
    from app.services.dynamic_param_score.data_collector import portfolio_from_budget

    ind = compute_indicators(market, portfolio_from_budget(100.0, market.ticker_price))
    contract = build_v6_input_contract(
        symbol=symbol,
        bot_budget_usdt=100.0,
        current_price=float(market.ticker_price or 0),
        ind=ind,
        market=market,
        exchange=constraints,
    )
    ok, reason = snapshot_is_usable(market, ind.to_dict(), filters or {})
    if not ok:
        return {"symbol": symbol, "skip_reason": reason}
    payload = snapshot_payload(symbol, market, ind, filters or {}, contract)
    payload["_market"] = market
    payload["_filters"] = filters or {}
    payload["_indicator_dict"] = ind.to_dict()
    return payload


class NodeBinancePublicClient:
    def __init__(self) -> None:
        self._next_id = 0
        self._proc = subprocess.Popen(
            ["node", str(ROOT / "scripts" / "binance_public_fetch_node.js")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if self._proc.poll() is not None:
            raise RuntimeError("node_binance_fetcher_exited")
        self._next_id += 1
        payload = {"id": self._next_id, "path": path, "params": params or {}}
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            err = ""
            if self._proc.stderr is not None:
                err = self._proc.stderr.read()
            raise RuntimeError(f"node_binance_fetcher_no_response:{err[:300]}")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(f"node_binance_fetch_failed:{path}:{response.get('status')}:{response.get('error')}")
        return response.get("data")


def _filters_from_exchange_symbol(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for f in item.get("filters") or []:
        ftype = f.get("filterType")
        if ftype in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            out.setdefault("step_size", float(f.get("stepSize") or 0.00001))
            out.setdefault("min_qty", float(f.get("minQty") or 0.00001))
            out.setdefault("max_qty", float(f.get("maxQty") or 0))
            out.setdefault("lot_size", float(f.get("stepSize") or 0.00001))
        elif ftype == "PRICE_FILTER":
            out["tick_size"] = float(f.get("tickSize") or 0.01)
        elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
            out["min_notional"] = float(f.get("minNotional") or f.get("notional") or 10.0)
    out.setdefault("min_notional", 10.0)
    out.setdefault("step_size", 0.00001)
    out.setdefault("tick_size", 0.01)
    out.setdefault("min_qty", out["step_size"])
    return out


def _candles_from_klines(raw: Sequence[Any]) -> List[Candle]:
    out: List[Candle] = []
    for c in raw or []:
        try:
            out.append(Candle(t=int(c[0]), o=float(c[1]), h=float(c[2]), l=float(c[3]), c=float(c[4]), v=float(c[5])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def _node_fetch_klines(client: NodeBinancePublicClient, symbol: str, interval: str, limit: int) -> List[Candle]:
    remaining = int(limit)
    end_time: Optional[int] = None
    batches: List[Candle] = []
    while remaining > 0:
        batch_size = min(remaining, 1000)
        params: Dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": batch_size}
        if end_time is not None:
            params["endTime"] = end_time
        chunk = _candles_from_klines(client.get("/api/v3/klines", params))
        if not chunk:
            break
        batches = chunk + batches
        remaining -= len(chunk)
        if len(chunk) < batch_size:
            break
        end_time = chunk[0].t - 1
    seen: set = set()
    out: List[Candle] = []
    for c in batches:
        if c.t in seen:
            continue
        seen.add(c.t)
        out.append(c)
    out.sort(key=lambda x: x.t)
    return out[-limit:]


def _node_btc_reference(client: NodeBinancePublicClient) -> BtcReferenceData:
    from app.botengine.dynamic import indicators as dyn_ind

    c1h = _node_fetch_klines(client, "BTCUSDT", "1h", 240)
    c4h = _node_fetch_klines(client, "BTCUSDT", "4h", 240)
    closes = [c.c for c in c1h]
    price = closes[-1] if closes else None
    ema200 = dyn_ind.ema_last(closes, 200) if len(closes) >= 200 else None
    crash = None
    if len(closes) >= 7:
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(-6, 0) if closes[i - 1] > 0]
        crash = min(rets) if rets else None
    return BtcReferenceData(
        candles_1h=c1h,
        candles_4h=c4h,
        return_1h_pct=return_pct(c1h, 1),
        return_4h_pct=return_pct(c1h, 4),
        return_24h_pct=return_pct(c1h, 24),
        price=price,
        ema200_1h=ema200,
        crash_velocity=crash,
    )


def _volume_from_1h(candles: Sequence[Candle]) -> Tuple[float, float]:
    seg = list(candles)[-24:]
    base = sum(float(c.v or 0.0) for c in seg)
    quote = sum(float(c.v or 0.0) * float(c.c or 0.0) for c in seg)
    return base, quote


def fetch_symbol_snapshot_node(
    symbol: str,
    *,
    client: NodeBinancePublicClient,
    filters_by_symbol: Dict[str, Dict[str, Any]],
    btc_reference: BtcReferenceData,
) -> Optional[Dict[str, Any]]:
    filters = filters_by_symbol.get(symbol) or {}
    c5 = _node_fetch_klines(client, symbol, "5m", 2016)
    c15 = _node_fetch_klines(client, symbol, "15m", 672)
    c1h = _node_fetch_klines(client, symbol, "1h", 240)
    if not c5 or not c15 or not c1h:
        return {"symbol": symbol, "skip_reason": "missing_klines"}
    book = client.get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    bid = float(book.get("bidPrice") or 0)
    ask = float(book.get("askPrice") or 0)
    orderbook = {"bid": bid, "ask": ask} if bid > 0 and ask > bid else None
    base_vol, quote_vol = _volume_from_1h(c1h)
    market = MarketDataBundle(
        symbol=symbol,
        base_asset=symbol[:-4],
        quote_asset="USDT",
        ticker_price=float(c5[-1].c),
        volume_24h=base_vol,
        quote_volume_24h=quote_vol,
        market_timestamp=int(time.time() * 1000),
        candles_5m=c5,
        candles_15m=c15,
        candles_1h=c1h,
        candles_4h=[],
        candles_1m=[],
        orderbook_top=orderbook,
        btc_reference_data=btc_reference,
        data_window={"source": "node-live", "test_account_mode": True},
    )
    constraints = constraints_from_filters(filters)
    from app.services.dynamic_param_score.data_collector import portfolio_from_budget

    ind = compute_indicators(market, portfolio_from_budget(100.0, market.ticker_price))
    contract = build_v6_input_contract(
        symbol=symbol,
        bot_budget_usdt=100.0,
        current_price=float(market.ticker_price or 0),
        ind=ind,
        market=market,
        exchange=constraints,
    )
    ok, reason = snapshot_is_usable(market, ind.to_dict(), filters)
    if not ok:
        return {"symbol": symbol, "skip_reason": reason}
    payload = snapshot_payload(symbol, market, ind, filters, contract)
    payload["data_source"] = "node-live-test-account"
    payload["_market"] = market
    payload["_filters"] = filters
    payload["_indicator_dict"] = ind.to_dict()
    payload["_v6_contract"] = contract
    return payload


async def select_node_live_symbols(
    *,
    seed: int,
    symbol_count: int,
    market: str,
) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    client = NodeBinancePublicClient()
    try:
        exchange_info = client.get("/api/v3/exchangeInfo")
        filters_by_symbol: Dict[str, Dict[str, Any]] = {}
        raw_symbols: List[str] = []
        for item in exchange_info.get("symbols") or []:
            sym = str(item.get("symbol") or "").upper()
            if item.get("status") != "TRADING":
                continue
            if item.get("quoteAsset") != market.upper():
                continue
            raw_symbols.append(sym)
            filters_by_symbol[sym] = _filters_from_exchange_symbol(item)
        universe = active_usdt_universe(raw_symbols, market)
        rng = random.Random(seed)
        rng.shuffle(universe)
        btc_reference = _node_btc_reference(client)
        selected: List[str] = []
        snapshots: Dict[str, Dict[str, Any]] = {}
        buckets: Dict[str, List[str]] = {k: [] for k in BUCKET_TARGETS}
        fallback: List[Tuple[str, Dict[str, Any], str]] = []
        rejects: Dict[str, List[str]] = defaultdict(list)

        for sym in universe:
            if len(selected) + len(fallback) >= symbol_count:
                break
            snap = fetch_symbol_snapshot_node(
                sym,
                client=client,
                filters_by_symbol=filters_by_symbol,
                btc_reference=btc_reference,
            )
            if not snap or snap.get("skip_reason"):
                rejects[str(snap.get("skip_reason") if snap else "fetch_failed")].append(sym)
                continue
            ind = snap.get("_indicator_dict") or snap.get("all_46_indicators") or {}
            bucket = selection_bucket(ind, str(snap.get("asset_fragility_class") or ""))
            if len(buckets.get(bucket, [])) < BUCKET_TARGETS.get(bucket, 0):
                selected.append(sym)
                snapshots[sym] = snap
                buckets[bucket].append(sym)
            else:
                fallback.append((sym, snap, bucket))

        for sym, snap, bucket in fallback:
            if len(selected) >= symbol_count:
                break
            selected.append(sym)
            snapshots[sym] = snap
            buckets[bucket].append(sym)

        if len(selected) < symbol_count:
            raise RuntimeError(f"selected {len(selected)} usable symbols, need {symbol_count}; rejects={dict(rejects)}")
        return selected[:symbol_count], {s: snapshots[s] for s in selected[:symbol_count]}, buckets
    finally:
        client.close()


async def select_live_symbols(
    *,
    seed: int,
    symbol_count: int,
    market: str,
    snapshot_fetcher: Callable[[str], Any] = fetch_symbol_snapshot,
) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    universe = active_usdt_universe(await get_cached_trading_symbols(force_refresh=True), market)
    rng = random.Random(seed)
    rng.shuffle(universe)
    selected: List[str] = []
    snapshots: Dict[str, Dict[str, Any]] = {}
    buckets: Dict[str, List[str]] = {k: [] for k in BUCKET_TARGETS}
    rejects: Dict[str, List[str]] = defaultdict(list)

    for sym in universe:
        if len(selected) >= symbol_count:
            break
        snap = await snapshot_fetcher(sym)
        if not snap or snap.get("skip_reason"):
            rejects[str(snap.get("skip_reason") if snap else "fetch_failed")].append(sym)
            continue
        ind = snap.get("_indicator_dict") or snap.get("all_46_indicators") or {}
        bucket = selection_bucket(ind, str(snap.get("asset_fragility_class") or ""))
        if len(buckets.get(bucket, [])) >= BUCKET_TARGETS.get(bucket, 0):
            # Later fallback may use it if exact targets cannot be filled.
            continue
        selected.append(sym)
        snapshots[sym] = snap
        buckets[bucket].append(sym)

    if len(selected) < symbol_count:
        for sym in universe:
            if len(selected) >= symbol_count:
                break
            if sym in snapshots:
                continue
            snap = await snapshot_fetcher(sym)
            if not snap or snap.get("skip_reason"):
                continue
            selected.append(sym)
            snapshots[sym] = snap
            ind = snap.get("_indicator_dict") or snap.get("all_46_indicators") or {}
            buckets[selection_bucket(ind, str(snap.get("asset_fragility_class") or ""))].append(sym)

    if len(selected) < symbol_count:
        raise RuntimeError(f"selected {len(selected)} usable symbols, need {symbol_count}; rejects={dict(rejects)}")
    return selected[:symbol_count], {s: snapshots[s] for s in selected[:symbol_count]}, buckets


def run_v6_case(symbol: str, budget: float, snapshot: Dict[str, Any]) -> Tuple[Any, Any, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    if snapshot.get("_v6_contract") is not None:
        base_contract = snapshot["_v6_contract"]
        contract_data = dict(base_contract.__dict__)
        contract_data["bot_budget_usdt"] = budget
        contract = V6InputContract(**contract_data)
        result = V6Engine().run(contract)
        params = v6_final_to_bot_params(result, bot_budget_usdt=budget)
        trace = result.telemetry.get("adjuster_trace") or []
        notes = result.telemetry.get("opportunity_notes") or {}
        display = enrich_v6_display(
            v6_final_to_telemetry_extras(result, bot_budget_usdt=budget, adjuster_trace=trace),
            adjuster_trace=trace,
            deployable=result.deployable,
            deploy_block_reason=result.deploy_block_reason,
            opportunity_notes=notes,
        )
        return result, params, display, notes, result.telemetry.get("scenario") or {}

    market = snapshot["_market"]
    filters = snapshot["_filters"]
    constraints = constraints_from_filters(filters)
    from app.services.dynamic_param_score.data_collector import portfolio_from_budget

    portfolio = portfolio_from_budget(budget, market.ticker_price)
    ind = compute_indicators(market, portfolio)
    contract = build_v6_input_contract(
        symbol=symbol,
        bot_budget_usdt=budget,
        current_price=float(market.ticker_price or 0),
        ind=ind,
        market=market,
        exchange=constraints,
    )
    result = V6Engine().run(contract)
    params = v6_final_to_bot_params(result, bot_budget_usdt=budget)
    trace = result.telemetry.get("adjuster_trace") or []
    notes = result.telemetry.get("opportunity_notes") or {}
    display = enrich_v6_display(
        v6_final_to_telemetry_extras(result, bot_budget_usdt=budget, adjuster_trace=trace),
        adjuster_trace=trace,
        deployable=result.deployable,
        deploy_block_reason=result.deploy_block_reason,
        opportunity_notes=notes,
    )
    return result, params, display, notes, result.telemetry.get("scenario") or {}


def order_feasibility(
    *,
    budget: float,
    price: float,
    base_pct: int,
    quote_pct: int,
    buy_distances: Sequence[int],
    sell_distances: Sequence[int],
    buy_amounts: Sequence[int],
    sell_amounts: Sequence[int],
    filters: Dict[str, Any],
) -> Dict[str, Any]:
    min_notional = pct(filters.get("min_notional"), 10.0)
    step = pct(filters.get("step_size"), 0.00001)
    tick = pct(filters.get("tick_size"), 0.01)
    min_qty = pct(filters.get("min_qty"), step)
    base_usdt = budget * base_pct / 100.0
    quote_usdt = budget * quote_pct / 100.0
    failures: List[str] = []
    orders: List[Dict[str, Any]] = []

    def check(side: str, pool_usdt: float, dist: int, amount: int) -> None:
        raw_order_notional = pool_usdt * amount / 100.0
        level_price = price * (1 - abs(dist) / 100.0) if side == "BUY" else price * (1 + abs(dist) / 100.0)
        rounded_price = dec_floor(level_price, tick)
        qty = raw_order_notional / rounded_price if rounded_price > 0 else 0.0
        rounded_qty = dec_floor(qty, step)
        rounded_notional = rounded_qty * rounded_price
        code = f"{side}_{dist}_{amount}"
        if rounded_price <= 0:
            failures.append(f"{code}:tick_price_invalid")
        if rounded_qty < min_qty:
            failures.append(f"{code}:min_qty")
        if rounded_notional + 1e-9 < min_notional:
            failures.append(f"{code}:min_notional:{rounded_notional:.4f}<{min_notional:.4f}")
        orders.append(
            {
                "side": side,
                "distance_pct": dist,
                "amount_pct": amount,
                "raw_notional": round(raw_order_notional, 6),
                "rounded_price": rounded_price,
                "rounded_qty": rounded_qty,
                "rounded_notional": round(rounded_notional, 6),
            }
        )

    for d, a in zip(buy_distances, buy_amounts):
        check("BUY", quote_usdt, int(d), int(a))
    for d, a in zip(sell_distances, sell_amounts):
        check("SELL", base_usdt, int(d), int(a))
    return {
        "base_usdt_value": round(base_usdt, 4),
        "quote_usdt_value": round(quote_usdt, 4),
        "min_notional_pass": not any("min_notional" in f for f in failures),
        "lot_size_pass": not any("min_qty" in f for f in failures),
        "tick_size_pass": not any("tick" in f for f in failures),
        "order_failures": failures,
        "orders": orders,
    }


def display_verdict(display_blob: str, row: Dict[str, Any]) -> Tuple[str, List[str]]:
    blob = display_blob.lower()
    failures: List[str] = []
    base = int(row.get("base_pct") or 0)
    regime = str(row.get("regime") or "")
    semantic = str(row.get("semantic_role") or "")
    if base <= 50 and ("coin payı artır" in blob or "coin tabanı tercih edildi" in blob):
        failures.append("DISPLAY_BASE_LOW_COIN_INCREASE")
    if regime == "R5" and semantic not in ("RECOVERY", "RECOVERY_BREAKOUT", "R6_RECOVERY_BREAKOUT") and (
        "toparlan" in blob or "recovery" in blob
    ):
        failures.append("DISPLAY_R5_FALSE_RECOVERY")
    if row.get("restricted") and "normal iki yönlü grid aktif" in blob:
        failures.append("DISPLAY_RESTRICTED_NORMAL_ACTIVE")
    if row.get("buy_grid_count", 0) == 0 and ("alış grid açık" in blob or "alış gridleri açık" in blob):
        failures.append("DISPLAY_BUY_DISABLED_OPEN")
    if regime == "R8" and "normal aktif alış" in blob:
        failures.append("DISPLAY_R8_ACTIVE_BUY")
    if row.get("deployable") is False and "uygulanabilir savunmacı profil" in blob:
        failures.append("DISPLAY_FALSE_DEPLOYABLE")
    if failures:
        return "DISPLAY_CRITICAL_FAIL", failures
    if "restricted" in blob and not row.get("restricted"):
        return "DISPLAY_MINOR_WARNING", ["DISPLAY_RESTRICTED_WORD_ON_DEPLOYABLE"]
    return "DISPLAY_OK", []


def score_case(row: Dict[str, Any], ind: Dict[str, Any], display_failures: List[str], criticals: List[str]) -> Dict[str, int]:
    regime = row["regime"]
    reason_codes = set(row.get("reason_codes") or [])
    hard_block_no_trade = (
        not row.get("deployable")
        and (
            "R8_HARD_BLOCK" in reason_codes
            or "HARD_BLOCK" in reason_codes
            or "NO_TRADE" in reason_codes
        )
    )
    spread = pct(ind.get("orderbook_spread_pct"))
    volume = pct(ind.get("quote_volume_24h"))
    atr = pct(ind.get("atr14_pct_1h"))
    volp = pct(ind.get("volatility_percentile"))
    base = int(row.get("base_pct") or 0)
    first_buy = min(row.get("buy_distances") or [99])
    first_sell = min(row.get("sell_distances") or [99])
    regime_fit = 85
    if regime == "R3" and (atr > 2.5 or volp > 55):
        regime_fit -= 35
    if regime == "R8" and pct(ind.get("return_24h_pct")) > -8 and pct(ind.get("drawdown_7d_pct")) < 15:
        regime_fit -= 40
    if regime == "R5" and spread >= 0.10 and volume < 1_000_000 and row.get("deployable"):
        regime_fit -= 50
    base_fit = 85
    if row["liquidity_bucket"] in ("L0_NORMAL", "L1_CAUTION") and base <= 15 and regime not in ("R7", "R8"):
        base_fit -= 50
    if row["liquidity_bucket"] in ("L3_NO_DEPLOY",) and base > 15:
        base_fit -= 40
    grid_fit = 85
    if regime == "R3" and first_buy > 3:
        grid_fit -= 45
    if regime == "R4" and first_buy < 2:
        grid_fit -= 25
    if spread >= 0.10 and (row.get("profit_sell_trigger") or 0) < 2.5:
        grid_fit -= 30
    profit_fit = 85
    if not row.get("profit_buyback_trigger") or not row.get("profit_sell_trigger"):
        profit_fit -= 45
    if (row.get("profit_sell_trigger") or 0) <= spread:
        profit_fit -= 45
    budget_fit = 100 if row["min_notional_pass"] and row["lot_size_pass"] and row["tick_size_pass"] else 45
    liquidity_fit = 90
    if row["liquidity_bucket"] in ("L2_RESTRICTED", "L3_NO_DEPLOY") and row.get("deployable"):
        liquidity_fit -= 55
    if hard_block_no_trade:
        regime_fit = max(regime_fit, 90)
        base_fit = max(base_fit, 90)
        grid_fit = max(grid_fit, 90)
        profit_fit = max(profit_fit, 90)
        liquidity_fit = max(liquidity_fit, 90)
        budget_fit = max(budget_fit, 90)
    risk_reward = max(0, min(100, int(50 + pct(row.get("risk_reward_score")))))
    display_score = 100 if not display_failures else 25
    scores = {
        "regime_fit_score": max(0, min(100, regime_fit)),
        "shelf_fit_score": 85,
        "base_fit_score": max(0, min(100, base_fit)),
        "grid_fit_score": max(0, min(100, grid_fit)),
        "profit_loop_fit_score": max(0, min(100, profit_fit)),
        "budget_feasibility_score": budget_fit,
        "liquidity_safety_score": max(0, min(100, liquidity_fit)),
        "risk_reward_score_100": risk_reward,
        "display_consistency_score": display_score,
    }
    overall = (
        0.18 * scores["regime_fit_score"]
        + 0.12 * scores["shelf_fit_score"]
        + 0.13 * scores["base_fit_score"]
        + 0.15 * scores["grid_fit_score"]
        + 0.12 * scores["profit_loop_fit_score"]
        + 0.12 * scores["budget_feasibility_score"]
        + 0.08 * scores["liquidity_safety_score"]
        + 0.06 * scores["risk_reward_score_100"]
        + 0.04 * scores["display_consistency_score"]
    )
    if criticals:
        overall = min(overall, 55)
    scores["overall_live_audit_score"] = int(round(overall))
    return scores


def audit_case(symbol: str, budget: float, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    result, params, display, notes, scenario = run_v6_case(symbol, budget, snapshot)
    profile = result.profile
    ind = snapshot["_indicator_dict"]
    filters = snapshot["_filters"]
    buy_dist = list(params.buy_grid_ladder_pcts or [])
    sell_dist = list(params.sell_grid_ladder_pcts or [])
    buy_amt = [int(round(x * 100)) for x in (params.buy_qty_distribution or [])]
    sell_amt = [int(round(x * 100)) for x in (params.sell_qty_distribution or [])]
    feasibility = order_feasibility(
        budget=budget,
        price=float(snapshot.get("price") or 0),
        base_pct=int(profile.base_allocation_pct),
        quote_pct=int(profile.quote_allocation_pct),
        buy_distances=buy_dist if profile.normal_buy_enabled else [],
        sell_distances=sell_dist,
        buy_amounts=buy_amt if profile.normal_buy_enabled else [],
        sell_amounts=sell_amt,
        filters=filters,
    )
    rr = notes.get("risk_reward") or {}
    row: Dict[str, Any] = {
        "symbol": symbol,
        "budget": budget,
        "price": snapshot.get("price"),
        "regime": scenario.get("regime_id"),
        "regime_title": display.get("regime_headline"),
        "semantic_role": notes.get("semantic_role") or profile.modules.get("semantic_role") or "",
        "scenario_id": scenario.get("sub_id"),
        "micro_scenario_id": scenario.get("micro_id"),
        "tactical_behavior_id": scenario.get("behavior_id"),
        "exact_shelf_id": result.catalog_profile_id,
        "final_profile_id": result.final_profile_id,
        "severity": scenario.get("severity"),
        "score": 70,
        "base_pct": profile.base_allocation_pct,
        "quote_pct": profile.quote_allocation_pct,
        "buy_grid_count": params.buy_grid_count,
        "sell_grid_count": params.sell_grid_count,
        "buy_distances": buy_dist,
        "sell_distances": sell_dist,
        "buy_amounts": buy_amt,
        "sell_amounts": sell_amt,
        "profit_buyback_trigger": params.rebuy_trigger_pct,
        "profit_buyback_trailing": params.rebuy_trail_pct,
        "profit_sell_trigger": params.resell_trigger_pct,
        "profit_sell_trailing": params.resell_trail_pct,
        "deployable": result.deployable,
        "restricted": bool(result.deploy_block_reason or notes.get("deployable") is False),
        "controlled_grid": bool(notes.get("controlled_grid")),
        "new_buys_status": profile.modules.get("new_buys_status"),
        "params_valid": bool(notes.get("params_valid")),
        "display_title": display.get("regime_headline"),
        "display_subtitle": display.get("market_status_plain"),
        "display_description": display.get("regime_strategy_why"),
        "reason_codes": notes.get("reason_codes") or [],
        "risk_score": rr.get("risk_score"),
        "reward_score": rr.get("reward_score"),
        "risk_reward_score": rr.get("risk_reward_score"),
        "liquidity_bucket": liquidity_level(ind, snapshot.get("asset_fragility_class")),
        **{k: feasibility[k] for k in ("base_usdt_value", "quote_usdt_value", "min_notional_pass", "lot_size_pass", "tick_size_pass")},
    }
    display_blob = " ".join(str(row.get(k) or "") for k in ("display_title", "display_subtitle", "display_description"))
    display_status, display_failures = display_verdict(display_blob, row)
    criticals: List[str] = []
    warnings: List[str] = []
    failures: List[str] = []
    if not row["params_valid"]:
        criticals.append("PARAMS_VALID_FALSE")
    if result.profile is None or params is None:
        criticals.append("PARAMS_NONE")
    if row["deployable"] and feasibility["order_failures"]:
        criticals.append("DEPLOYABLE_ORDER_FEASIBILITY_FAIL")
    if row["liquidity_bucket"] in ("L2_RESTRICTED", "L3_NO_DEPLOY") and row["deployable"]:
        criticals.append("LOW_LIQ_WRONG_DEPLOYABLE")
    if display_status == "DISPLAY_CRITICAL_FAIL":
        criticals.extend(display_failures)
    if row["regime"] == "R3" and buy_dist and min(buy_dist) > 3:
        failures.append("DEAD_GRID_R3_LOW_VOL")
    if row["regime"] == "R4" and buy_dist and min(buy_dist) > 8:
        failures.append("DEAD_GRID_R4")
    if row["deployable"] is False and row["budget"] >= 1000 and row["liquidity_bucket"] == "L0_NORMAL" and row["regime"] not in ("R8",):
        warnings.append("POSSIBLY_TOO_PASSIVE_1000")
    scores = score_case(row, ind, display_failures, criticals)
    row.update(scores)
    if criticals:
        verdict = "critical_fail"
    elif failures or row["overall_live_audit_score"] < 70:
        verdict = "fail"
    elif warnings or display_status == "DISPLAY_MINOR_WARNING":
        verdict = "warning"
    else:
        verdict = "pass"
    row.update(
        {
            "display_semantic_verdict": display_status,
            "audit_verdict": verdict,
            "audit_warnings": warnings,
            "audit_failures": failures,
            "audit_critical_failures": criticals,
            "order_feasibility": feasibility,
            "estimated_trigger_probability_buy_1": max(0, min(100, 100 - (buy_dist[0] if buy_dist else 100) * 12)),
            "estimated_trigger_probability_sell_1": max(0, min(100, 100 - (sell_dist[0] if sell_dist else 100) * 12)),
            "estimated_trigger_probability_full_ladder": max(0, min(100, 100 - (max(buy_dist + sell_dist) if (buy_dist + sell_dist) else 100) * 5)),
            "expected_loop_profit_pct": row.get("profit_sell_trigger"),
            "spread_cost_pct": ind.get("orderbook_spread_pct"),
            "volatility_adjusted_grid_score": scores["grid_fit_score"],
            "dead_grid_risk": max(0, 100 - scores["grid_fit_score"]),
            "overtrading_risk": max(0, 100 - scores["profit_loop_fit_score"]),
            "suggested_fix": suggest_fix(row),
        }
    )
    return row


def suggest_fix(row: Dict[str, Any]) -> str:
    if row.get("audit_critical_failures"):
        if "DEPLOYABLE_ORDER_FEASIBILITY_FAIL" in row["audit_critical_failures"]:
            return "Budget-aware grid compaction or restricted deploy gate"
        if "LOW_LIQ_WRONG_DEPLOYABLE" in row["audit_critical_failures"]:
            return "Strengthen low-liq deploy gate and display role"
        return "Inspect critical validator path"
    if row.get("overall_live_audit_score", 100) < 70:
        return "Tune regime/base/grid/profit validator thresholds for this market state"
    if row.get("audit_warnings"):
        return "Review cautious/passive profile balance"
    return "No fix needed"


def aggregate(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    verdicts = Counter(r["audit_verdict"] for r in rows)
    def avg(values: Iterable[Any]) -> float:
        nums = [float(v) for v in values if v is not None]
        return round(statistics.mean(nums), 2) if nums else 0.0
    by_budget: Dict[str, Any] = {}
    for budget, items in group_by(rows, "budget").items():
        by_budget[str(budget)] = summarize_group(items)
        by_budget[str(budget)].update(
            {
                "restricted": sum(1 for r in items if r["restricted"]),
                "deployable_false": sum(1 for r in items if not r["deployable"]),
                "min_notional_fail": sum(1 for r in items if not r["min_notional_pass"]),
                "params_valid_true": sum(1 for r in items if r["params_valid"]),
            }
        )
    return {
        "total_cases": len(rows),
        "pass": verdicts.get("pass", 0),
        "warning": verdicts.get("warning", 0),
        "fail": verdicts.get("fail", 0),
        "critical_fail": verdicts.get("critical_fail", 0),
        "average_score": avg(r.get("overall_live_audit_score") for r in rows),
        "by_budget": by_budget,
        "by_regime": {str(k): summarize_group(v) for k, v in group_by(rows, "regime").items()},
        "by_liquidity_bucket": {str(k): summarize_group(v) for k, v in group_by(rows, "liquidity_bucket").items()},
        "failure_types": Counter(x for r in rows for x in (r.get("audit_failures") or []) + (r.get("audit_critical_failures") or [])).most_common(),
        "worst_20": sorted(rows, key=lambda r: r.get("overall_live_audit_score", 0))[:20],
        "best_20": sorted(rows, key=lambda r: r.get("overall_live_audit_score", 0), reverse=True)[:20],
    }


def group_by(rows: Sequence[Dict[str, Any]], key: str) -> Dict[Any, List[Dict[str, Any]]]:
    out: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[r.get(key)].append(r)
    return dict(out)


def summarize_group(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    verdicts = Counter(r["audit_verdict"] for r in items)
    avg_score = round(statistics.mean([r.get("overall_live_audit_score", 0) for r in items]), 2) if items else 0.0
    return {
        "cases": len(items),
        "pass": verdicts.get("pass", 0),
        "warning": verdicts.get("warning", 0),
        "fail": verdicts.get("fail", 0),
        "critical_fail": verdicts.get("critical_fail", 0),
        "average_score": avg_score,
    }


def md_table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> str:
    lines = ["|" + "|".join(headers) + "|", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(str(x).replace("\n", " ") for x in row) + "|")
    return "\n".join(lines)


def write_reports(
    output_dir: Path,
    selected: Sequence[str],
    snapshots: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
    *,
    data_source: str = "live",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw_snapshots"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for sym, snap in snapshots.items():
        public_snap = {k: v for k, v in snap.items() if not k.startswith("_")}
        (raw_dir / f"{sym}.json").write_text(json.dumps(public_snap, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = aggregate(rows)
    raw = {
        "generated_at_utc": utc_now_iso(),
        "data_source": data_source,
        "selected_symbols": list(selected),
        "summary": summary,
        "cases": list(rows),
    }
    (output_dir / "live_audit_raw_results.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "live_audit_selected_symbols.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")
    with (output_dir / "live_audit_replay_snapshots.jsonl").open("w", encoding="utf-8") as fh:
        for sym in selected:
            public_snap = {k: v for k, v in snapshots[sym].items() if not k.startswith("_")}
            fh.write(json.dumps(public_snap, ensure_ascii=False) + "\n")

    write_markdown_reports(output_dir, summary, selected, rows, data_source=data_source)
    return summary


def write_markdown_reports(
    output_dir: Path,
    summary: Dict[str, Any],
    selected: Sequence[str],
    rows: Sequence[Dict[str, Any]],
    *,
    data_source: str = "live",
) -> None:
    budget_rows = [[k, v["cases"], v["pass"], v["warning"], v["fail"], v["critical_fail"], v["average_score"]] for k, v in summary["by_budget"].items()]
    regime_rows = [[k, v["cases"], v["pass"], v["warning"], v["fail"], v["critical_fail"], v["average_score"]] for k, v in sorted(summary["by_regime"].items())]
    liq_rows = [[k, v["cases"], v["pass"], v["warning"], v["fail"], v["critical_fail"], v["average_score"]] for k, v in sorted(summary["by_liquidity_bucket"].items())]
    worst_rows = [[r["symbol"], r["budget"], r["regime"], r["overall_live_audit_score"], ",".join(r.get("audit_critical_failures") or r.get("audit_failures") or []), r["suggested_fix"]] for r in summary["worst_20"]]
    best_rows = [[r["symbol"], r["budget"], r["regime"], r["overall_live_audit_score"], "risk/reward, display, budget checks passed" if r["audit_verdict"] == "pass" else r["audit_verdict"]] for r in summary["best_20"]]
    fail_type_rows = [[k, v] for k, v in summary["failure_types"]]

    summary_md = f"""# {AUDIT_TITLE}

Generated: {utc_now_iso()}
Data source: {data_source}

This is a technical audit only. It does not produce buy/sell advice.

## Overall

- Total coin count: {len(selected)}
- Total test cases: {summary['total_cases']}
- Pass: {summary['pass']}
- Warning: {summary['warning']}
- Fail: {summary['fail']}
- Critical fail: {summary['critical_fail']}
- Average score: {summary['average_score']}

## Selected Symbols

{", ".join(selected)}

## Budget Breakdown

{md_table(budget_rows, ["budget", "cases", "pass", "warning", "fail", "critical", "avg"])}

## Regime Breakdown

{md_table(regime_rows, ["regime", "cases", "pass", "warning", "fail", "critical", "avg"])}

## Liquidity Bucket Breakdown

{md_table(liq_rows, ["bucket", "cases", "pass", "warning", "fail", "critical", "avg"])}

## Worst 20

{md_table(worst_rows, ["symbol", "budget", "regime", "score", "failure reason", "suggested fix"])}

## Best 20

{md_table(best_rows, ["symbol", "budget", "regime", "score", "why successful"])}

## Repeated Failure Types

{md_table(fail_type_rows, ["failure", "count"])}

## Root Cause Analysis

Root causes are derived from critical/fail validators. If critical failures are non-zero, inspect minNotional feasibility, low-liq deploy gates, and display contradictions first.

## Code Points To Review

- `app/services/dynamic_param_score/v6/v6_exchange_validator.py`
- `app/services/dynamic_param_score/v6/engine.py`
- `app/services/dynamic_param_score/v6/v6_pa_display.py`
- `app/services/dynamic_param_score/v6/v6_regime_behavior_spec.py`

## Produced Artifacts

{chr(10).join(f"- {p}" for p in REQUIRED_ARTIFACTS)}
"""
    (output_dir / "live_audit_summary.md").write_text(summary_md, encoding="utf-8")
    (output_dir / "live_audit_failures.md").write_text(
        "# Failures\n\n" + md_table(worst_rows, ["symbol", "budget", "regime", "score", "failure reason", "suggested fix"]) + "\n",
        encoding="utf-8",
    )
    (output_dir / "live_audit_by_budget.md").write_text("# By Budget\n\n" + md_table(budget_rows, ["budget", "cases", "pass", "warning", "fail", "critical", "avg"]) + "\n", encoding="utf-8")
    (output_dir / "live_audit_by_regime.md").write_text("# By Regime\n\n" + md_table(regime_rows, ["regime", "cases", "pass", "warning", "fail", "critical", "avg"]) + "\n", encoding="utf-8")
    (output_dir / "live_audit_by_liquidity_bucket.md").write_text("# By Liquidity Bucket\n\n" + md_table(liq_rows, ["bucket", "cases", "pass", "warning", "fail", "critical", "avg"]) + "\n", encoding="utf-8")


def write_blocked_reports(output_dir: Path, error: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw_snapshots").mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at_utc": utc_now_iso(),
        "status": "LIVE_FETCH_BLOCKED",
        "error": error,
        "selected_symbols": [],
        "summary": {
            "total_cases": 0,
            "pass": 0,
            "warning": 0,
            "fail": 0,
            "critical_fail": 1,
            "average_score": 0,
        },
        "cases": [],
    }
    (output_dir / "live_audit_raw_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "live_audit_selected_symbols.txt").write_text("", encoding="utf-8")
    (output_dir / "live_audit_replay_snapshots.jsonl").write_text("", encoding="utf-8")
    blocked_md = f"""# {AUDIT_TITLE}

Generated: {utc_now_iso()}

Status: LIVE_FETCH_BLOCKED

The audit runner and offline validators are available, but live Binance market data could not be fetched from this environment.

Error:

```text
{error}
```

No buy/sell advice was produced.
"""
    for name in (
        "live_audit_summary.md",
        "live_audit_failures.md",
        "live_audit_by_budget.md",
        "live_audit_by_regime.md",
        "live_audit_by_liquidity_bucket.md",
    ):
        (output_dir / name).write_text(blocked_md, encoding="utf-8")


async def run_live_audit(args: argparse.Namespace) -> Dict[str, Any]:
    budgets = [float(x) for x in str(args.budgets).split(",") if str(x).strip()]
    output_dir = Path(args.output_dir)
    if args.data_source == "test-account":
        selected, snapshots, buckets = await select_test_account_symbols(
            seed=args.seed,
            symbol_count=args.symbols,
            market=args.market,
        )
    elif args.data_source == "node-live":
        selected, snapshots, buckets = await select_node_live_symbols(
            seed=args.seed,
            symbol_count=args.symbols,
            market=args.market,
        )
    else:
        selected, snapshots, buckets = await select_live_symbols(seed=args.seed, symbol_count=args.symbols, market=args.market)
    rows: List[Dict[str, Any]] = []
    for sym in selected:
        snap = snapshots[sym]
        for budget in budgets:
            rows.append(audit_case(sym, budget, snap))
    summary = write_reports(output_dir, selected, snapshots, rows, data_source=args.data_source)
    summary["selection_buckets"] = {k: v for k, v in buckets.items()}
    print(json.dumps({k: summary[k] for k in ("total_cases", "pass", "warning", "fail", "critical_fail", "average_score")}, ensure_ascii=False, indent=2))
    if args.fail_on_critical and summary.get("critical_fail", 0) > 0:
        raise SystemExit(1)
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dynamic Param V6 live random 100 x 3 budget audit")
    p.add_argument("--seed", type=int, default=20260702)
    p.add_argument("--symbols", type=int, default=100)
    p.add_argument("--budgets", default="50,100,1000")
    p.add_argument("--market", default="USDT")
    p.add_argument("--output-dir", default="artifacts/v6_live_audit")
    p.add_argument("--data-source", choices=("live", "test-account", "node-live"), default="live")
    p.add_argument("--fail-on-critical", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(run_live_audit(args))
        return 0
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as exc:
        try:
            parsed = build_parser().parse_args(argv)
            write_blocked_reports(Path(parsed.output_dir), str(exc))
        except Exception:
            pass
        print(f"live audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
