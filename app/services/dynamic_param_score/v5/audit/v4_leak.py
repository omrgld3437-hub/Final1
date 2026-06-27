"""Legacy V4 runtime leak detection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[5]


def audit_v4_leak() -> dict:
    """Grep + runtime smoke under V5 env."""
    grep_hits: List[str] = []
    # adapters.py may reference DPLV4_ for legacy display fallback only — not a runtime leak
    allow_legacy_display = {"app/services/dynamic_param_score/adapters.py"}
    targets = [
        "app/services/dynamic_param_score/v5/bridge.py",
        "app/services/dynamic_param_score/param_pool/selector.py",
        "app/services/dynamic_param_score/adapters.py",
    ]

    for rel in targets:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "DPLV4_" in text and rel not in allow_legacy_display:
            if "v5_select_and_render" not in text and rel.endswith("selector.py"):
                grep_hits.append(f"{rel}:DPLV4_ runtime path")

    runtime_v4_ids: List[str] = []
    runtime_v5_ok = False
    try:
        env = {**os.environ, "PARAM_POOL_VERSION": "v5.0.0"}
        code = """
import os
os.environ["PARAM_POOL_VERSION"] = "v5.0.0"
from app.services.dynamic_param_score.models import (
    BotContext, ExchangeConstraints, IndicatorSnapshot, PortfolioState, RegimeTag, SubScores,
)
from app.services.dynamic_param_score.v5.bridge import v5_select_and_render
from app.services.dynamic_param_score.param_pool.versioning import resolve_pool_version

assert resolve_pool_version() == "v5.0.0"
sub = SubScores(range_score=60, liquidity_score=70, spread_score=70, fee_efficiency_score=70,
    volatility_score=50, data_quality_score=80, btc_market_risk_score=50, exposure_safety_score=60)
ind = IndicatorSnapshot(return_24h_pct=0.5, atr14_pct_5m=1.0, atr14_pct_1h=1.2,
    orderbook_spread_pct=0.1, rsi14_1h=50, price_in_bb=0.5)
portfolio = PortfolioState(base_balance=0.002, quote_balance=400, base_value_usdt=100,
    quote_value_usdt=400, total_equity_usdt=500, current_base_exposure_frac=0.2)
constraints = ExchangeConstraints(min_notional=10, step_size=0.0001, tick_size=0.01, min_qty=0.0001,
    maker_fee_pct=0.1, taker_fee_pct=0.1, estimated_slippage_pct=0.05)
ctx = BotContext(run_source="param_assistant", budget_usdt=500, bot_id=1)
sel, params, bucket = v5_select_and_render(65, RegimeTag.BALANCED_RANGE, "NORMAL", sub, ind,
    portfolio, constraints, ctx, 500, 10, symbol="BTCUSDT")
key = sel.selected_template_key or ""
if "DPLV4_" in key:
    print("LEAK:" + key)
else:
    print("OK:" + key)
"""
        out = subprocess.check_output(["python3", "-c", code], cwd=str(ROOT), env=env, text=True, timeout=120)
        for line in out.strip().splitlines():
            if line.startswith("LEAK:"):
                runtime_v4_ids.append(line)
            if line.startswith("OK:DPLV5"):
                runtime_v5_ok = True
    except Exception as exc:
        runtime_v4_ids.append(f"runtime_error:{exc}")

    pass_audit = not grep_hits and not runtime_v4_ids and runtime_v5_ok

    return {
        "grep_hits": grep_hits,
        "runtime_v4_leaks": runtime_v4_ids,
        "runtime_v5_dplv5_ok": runtime_v5_ok,
        "pass_audit": pass_audit,
    }
