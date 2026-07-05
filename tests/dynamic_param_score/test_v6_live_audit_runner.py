from __future__ import annotations

import asyncio
from pathlib import Path

from scripts import live_audit_v6_random_100 as audit


def _ind_for(i: int) -> dict:
    if i < 25:
        return {
            "quote_volume_24h": 100_000_000 + i,
            "orderbook_spread_pct": 0.01,
            "volume_consistency": 0.90,
            "zero_volume_ratio": 0.0,
            "volatility_percentile": 30,
            "atr14_pct_1h": 1.0,
        }
    if i < 55:
        return {
            "quote_volume_24h": 12_000_000 + i,
            "orderbook_spread_pct": 0.02,
            "volume_consistency": 0.72,
            "zero_volume_ratio": 0.0,
            "volatility_percentile": 45,
            "atr14_pct_1h": 1.3,
        }
    if i < 80:
        return {
            "quote_volume_24h": 2_000_000 + i,
            "orderbook_spread_pct": 0.04,
            "volume_consistency": 0.52,
            "zero_volume_ratio": 0.0,
            "volatility_percentile": 35,
            "atr14_pct_1h": 1.1,
        }
    if i < 95:
        return {
            "quote_volume_24h": 20_000_000 + i,
            "orderbook_spread_pct": 0.03,
            "volume_consistency": 0.70,
            "zero_volume_ratio": 0.0,
            "volatility_percentile": 85,
            "atr14_pct_1h": 3.5,
        }
    return {
        "quote_volume_24h": 500_000 + i,
        "orderbook_spread_pct": 0.18,
        "volume_consistency": 0.20,
        "zero_volume_ratio": 0.05,
        "volatility_percentile": 60,
        "atr14_pct_1h": 2.0,
    }


def _fake_snapshot(symbol: str, i: int = 0) -> dict:
    ind = _ind_for(i)
    return {
        "symbol": symbol,
        "price": 100.0,
        "asset_fragility_class": "F3" if i >= 95 else "F1",
        "all_46_indicators": ind,
        "_indicator_dict": ind,
        "_filters": {"min_notional": 10.0, "step_size": 0.001, "tick_size": 0.01, "min_qty": 0.001},
    }


def test_live_audit_runner_selects_100_unique_symbols(monkeypatch):
    symbols = [f"COIN{i}USDT" for i in range(130)]
    idx = {s: i % 100 for i, s in enumerate(symbols)}

    async def fake_symbols(force_refresh=False):
        return symbols

    async def fake_fetch(symbol):
        return _fake_snapshot(symbol, idx[symbol])

    monkeypatch.setattr(audit, "get_cached_trading_symbols", fake_symbols)
    selected, snapshots, buckets = asyncio.run(
        audit.select_live_symbols(
            seed=20260702,
            symbol_count=100,
            market="USDT",
            snapshot_fetcher=fake_fetch,
        )
    )
    assert len(selected) == 100
    assert len(set(selected)) == 100
    assert set(selected) == set(snapshots)
    assert sum(len(v) for v in buckets.values()) >= 100


def test_live_audit_runner_runs_3_budgets_per_symbol(monkeypatch):
    calls = []

    def fake_case(symbol, budget, snapshot):
        calls.append((symbol, budget, id(snapshot)))
        return {"symbol": symbol, "budget": budget, "audit_verdict": "pass", "overall_live_audit_score": 90}

    monkeypatch.setattr(audit, "audit_case", fake_case)
    snapshots = {"AAAUSDT": {}, "BBBUSDT": {}}
    rows = [audit.audit_case(sym, budget, snapshots[sym]) for sym in snapshots for budget in (50, 100, 1000)]
    assert len(rows) == 6
    assert [c[1] for c in calls] == [50, 100, 1000, 50, 100, 1000]


def test_live_audit_snapshot_is_reused_across_budgets(monkeypatch):
    seen_ids = []
    snap = {"symbol": "AAAUSDT"}

    def fake_case(symbol, budget, snapshot):
        seen_ids.append(id(snapshot))
        return {"symbol": symbol, "budget": budget}

    monkeypatch.setattr(audit, "audit_case", fake_case)
    for budget in (50, 100, 1000):
        audit.audit_case("AAAUSDT", budget, snap)
    assert len(set(seen_ids)) == 1


def test_live_audit_detects_min_notional_failure():
    feasibility = audit.order_feasibility(
        budget=50,
        price=100,
        base_pct=50,
        quote_pct=50,
        buy_distances=[1, 3, 6],
        sell_distances=[1, 2, 4],
        buy_amounts=[10, 20, 70],
        sell_amounts=[10, 20, 70],
        filters={"min_notional": 10, "step_size": 0.001, "tick_size": 0.01, "min_qty": 0.001},
    )
    assert feasibility["min_notional_pass"] is False
    assert any("min_notional" in f for f in feasibility["order_failures"])


def test_live_audit_detects_display_contradiction():
    row = {
        "base_pct": 40,
        "regime": "R5",
        "semantic_role": "OVEREXTENDED_MOMENTUM",
        "restricted": False,
        "buy_grid_count": 3,
        "deployable": True,
    }
    verdict, failures = audit.display_verdict("coin payı artırılır", row)
    assert verdict == "DISPLAY_CRITICAL_FAIL"
    assert "DISPLAY_BASE_LOW_COIN_INCREASE" in failures


def test_live_audit_detects_low_liq_wrong_deployable():
    ind = {
        "orderbook_spread_pct": 0.20,
        "quote_volume_24h": 400_000,
        "volume_consistency": 0.20,
        "zero_volume_ratio": 0.03,
    }
    row = {
        "regime": "R4",
        "base_pct": 40,
        "liquidity_bucket": audit.liquidity_level(ind, "F3"),
        "deployable": True,
        "profit_sell_trigger": 1.5,
        "min_notional_pass": True,
        "lot_size_pass": True,
        "tick_size_pass": True,
    }
    scores = audit.score_case(row, ind, [], [])
    assert row["liquidity_bucket"] == "L3_NO_DEPLOY"
    assert scores["liquidity_safety_score"] < 50


def test_live_audit_detects_dead_grid():
    row = {
        "regime": "R3",
        "base_pct": 40,
        "buy_distances": [6, 12, 20],
        "sell_distances": [2, 4, 7],
        "liquidity_bucket": "L0_NORMAL",
        "deployable": True,
        "profit_sell_trigger": 1.5,
        "min_notional_pass": True,
        "lot_size_pass": True,
        "tick_size_pass": True,
        "risk_reward_score": 10,
    }
    scores = audit.score_case(row, {"atr14_pct_1h": 0.5, "volatility_percentile": 20}, [], [])
    assert scores["grid_fit_score"] < 60


def test_live_audit_scores_r8_hard_block_no_trade_as_valid():
    row = {
        "regime": "R8",
        "base_pct": 0,
        "buy_distances": [],
        "sell_distances": [],
        "liquidity_bucket": "L3_NO_DEPLOY",
        "deployable": False,
        "profit_sell_trigger": None,
        "min_notional_pass": True,
        "lot_size_pass": True,
        "tick_size_pass": True,
        "risk_reward_score": -35,
        "reason_codes": ["R8_HARD_BLOCK", "HARD_BLOCK", "NO_TRADE"],
    }
    scores = audit.score_case(
        row,
        {"atr14_pct_1h": 4.0, "volatility_percentile": 90, "return_24h_pct": -12, "drawdown_7d_pct": 20},
        [],
        [],
    )
    assert scores["grid_fit_score"] >= 90
    assert scores["profit_loop_fit_score"] >= 90
    assert scores["overall_live_audit_score"] >= 70


def test_live_audit_reports_budget_breakdown():
    rows = [
        {"budget": 50, "regime": "R3", "liquidity_bucket": "L0_NORMAL", "audit_verdict": "pass", "overall_live_audit_score": 90, "restricted": False, "deployable": True, "min_notional_pass": True, "params_valid": True},
        {"budget": 100, "regime": "R4", "liquidity_bucket": "L1_CAUTION", "audit_verdict": "warning", "overall_live_audit_score": 75, "restricted": True, "deployable": False, "min_notional_pass": False, "params_valid": True},
        {"budget": 1000, "regime": "R5", "liquidity_bucket": "L0_NORMAL", "audit_verdict": "pass", "overall_live_audit_score": 92, "restricted": False, "deployable": True, "min_notional_pass": True, "params_valid": True},
    ]
    summary = audit.aggregate(rows)
    assert set(summary["by_budget"]) == {"50", "100", "1000"}
    assert summary["by_budget"]["100"]["restricted"] == 1


def test_live_audit_writes_required_artifacts(tmp_path: Path):
    snap = _fake_snapshot("AAAUSDT")
    rows = [
        {
            "symbol": "AAAUSDT",
            "budget": 50,
            "regime": "R3",
            "liquidity_bucket": "L0_NORMAL",
            "audit_verdict": "pass",
            "overall_live_audit_score": 90,
            "audit_failures": [],
            "audit_critical_failures": [],
            "suggested_fix": "No fix needed",
            "restricted": False,
            "deployable": True,
            "min_notional_pass": True,
            "params_valid": True,
        }
    ]
    audit.write_reports(tmp_path, ["AAAUSDT"], {"AAAUSDT": snap}, rows)
    for name in audit.REQUIRED_ARTIFACTS:
        assert (tmp_path / name).exists(), name
    assert (tmp_path / "raw_snapshots" / "AAAUSDT.json").exists()


def test_live_audit_test_account_source_selects_100_symbols():
    selected, snapshots, buckets = asyncio.run(
        audit.select_test_account_symbols(seed=20260702, symbol_count=100, market="USDT")
    )
    assert len(selected) == 100
    assert len(set(selected)) == 100
    assert set(selected) == set(snapshots)
    assert snapshots[selected[0]]["data_source"] == "test-account"
    assert {k: len(v) for k, v in buckets.items()} == audit.BUCKET_TARGETS


def test_live_audit_test_account_budget_compacts_min_notional():
    snap = audit.test_account_snapshot("TAH001USDT", 1, "high_liquidity")
    row = audit.audit_case("TAH001USDT", 50, snap)
    assert row["params_valid"] is True
    assert row["audit_verdict"] != "critical_fail"
    assert "DEPLOYABLE_ORDER_FEASIBILITY_FAIL" not in row["audit_critical_failures"]
