"""Market feature trace — source file / function mapping."""

from __future__ import annotations

from typing import Any, Dict, List

FEATURE_TRACE: List[Dict[str, Any]] = [
    {
        "feature": "price",
        "source_file": "app/services/dynamic_param_score/indicators.py",
        "source_function": "compute_indicators",
        "input_data": "market_data.last_price / candles close",
        "lookback": 1,
        "used_in_selection": True,
        "used_in_grid_math": True,
    },
    {
        "feature": "atr_5m_pct",
        "source_file": "app/services/dynamic_param_score/indicators.py",
        "source_function": "compute_indicators",
        "input_data": "5m candles",
        "lookback": 48,
        "used_in_selection": True,
        "used_in_grid_math": True,
    },
    {
        "feature": "atr_1h_pct",
        "source_file": "app/services/dynamic_param_score/indicators.py",
        "source_function": "compute_indicators",
        "input_data": "1h candles",
        "lookback": 168,
        "used_in_selection": True,
        "used_in_grid_math": True,
    },
    {
        "feature": "rsi_1h",
        "source_file": "app/services/dynamic_param_score/indicators.py",
        "source_function": "compute_indicators",
        "input_data": "1h candles",
        "lookback": 14,
        "used_in_selection": True,
        "used_in_grid_math": False,
    },
    {
        "feature": "adx_1h",
        "source_file": "app/services/dynamic_param_score/indicators.py",
        "source_function": "compute_indicators",
        "input_data": "1h candles",
        "lookback": 14,
        "used_in_selection": True,
        "used_in_grid_math": False,
    },
    {
        "feature": "bb_position",
        "source_file": "app/services/dynamic_param_score/indicators.py",
        "source_function": "compute_indicators",
        "input_data": "1h candles Bollinger",
        "lookback": 20,
        "used_in_selection": True,
        "used_in_grid_math": False,
    },
    {
        "feature": "volume_zscore",
        "source_file": "app/services/dynamic_param_score/indicators.py",
        "source_function": "compute_indicators",
        "input_data": "5m volume",
        "lookback": 48,
        "used_in_selection": True,
        "used_in_grid_math": False,
    },
    {
        "feature": "lower_lows_structure",
        "source_file": "app/services/dynamic_param_score/regime.py",
        "source_function": "classify_regime",
        "input_data": "indicator snapshot",
        "lookback": None,
        "used_in_selection": True,
        "used_in_grid_math": True,
    },
    {
        "feature": "btc_crash_velocity",
        "source_file": "app/services/dynamic_param_score/scoring.py",
        "source_function": "compute_sub_scores",
        "input_data": "btc_reference bundle",
        "lookback": 24,
        "used_in_selection": True,
        "used_in_grid_math": False,
    },
    {
        "feature": "roundtrip_fee_pct",
        "source_file": "app/services/dynamic_param_score/feasibility.py",
        "source_function": "estimate_roundtrip_friction_pct",
        "input_data": "exchange_constraints + market_data",
        "lookback": None,
        "used_in_selection": True,
        "used_in_grid_math": True,
    },
    {
        "feature": "spread_pct",
        "source_file": "app/services/dynamic_param_score/models.py",
        "source_function": "MarketDataBundle.spread_pct",
        "input_data": "market bundle / live ticker",
        "lookback": 1,
        "used_in_selection": True,
        "used_in_grid_math": True,
    },
    {
        "feature": "min_notional",
        "source_file": "app/services/dynamic_param_score/feasibility.py",
        "source_function": "apply_exposure_and_notional_feasibility",
        "input_data": "ExchangeConstraints.min_notional_usdt",
        "lookback": None,
        "used_in_selection": True,
        "used_in_grid_math": True,
    },
    {
        "feature": "vol_24h_display",
        "source_file": "ui/assets/modules/dashboard-create-modal.js",
        "source_function": "renderParamAssistantResult",
        "input_data": "API ui_config",
        "lookback": None,
        "used_in_selection": False,
        "used_in_grid_math": False,
        "status": "DISPLAY_ONLY_FIELD",
    },
]


def build_market_feature_trace(*, sample_values: Dict[str, Any] | None = None) -> Dict[str, Any]:
    sample_values = sample_values or {}
    features = []
    display_only = []
    for f in FEATURE_TRACE:
        row = dict(f)
        key = f["feature"]
        if key in sample_values:
            row["last_value_sample"] = sample_values[key]
        if not f.get("used_in_selection") and not f.get("used_in_grid_math"):
            row["status"] = f.get("status") or "DISPLAY_ONLY_FIELD"
            display_only.append(key)
        features.append(row)
    return {
        "features": features,
        "display_only_fields": display_only,
        "selection_pipeline": [
            "market_data → compute_indicators → compute_sub_scores",
            "→ classify_regime / determine_risk_state",
            "→ select_and_render (param_pool/selector.py)",
            "→ apply_safety_gates → feasibility → explain",
        ],
    }


def sample_live_features(symbols: List[str]) -> Dict[str, Any]:
    """Run engine once per symbol to capture live-ish feature samples."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
    from tests.dynamic_param_score.factories import (
        make_constraints,
        make_context,
        make_market_bundle,
        make_portfolio_state,
    )

    engine = DynamicParamScoreEngine()
    out: Dict[str, Any] = {}
    for sym in symbols[:5]:
        m = make_market_bundle(symbol=sym, pattern="balanced_range", price=100)
        d = engine.calculate_decision(
            sym,
            m,
            make_portfolio_state(budget_usdt=100, price=100),
            make_constraints(),
            make_context(run_source="param_assistant", budget_usdt=100),
        )
        ind = (d.telemetry or {}).get("indicators") or {}
        out[sym] = {
            "regime_tag": d.regime_tag,
            "param_score": d.param_score,
            "atr_1h_pct": ind.get("atr_1h_pct"),
            "rsi_1h": ind.get("rsi_1h"),
            "adx_1h": ind.get("adx_1h"),
        }
    flat = {}
    for sym, vals in out.items():
        for k, v in vals.items():
            flat[f"{sym}_{k}"] = v
    return flat
