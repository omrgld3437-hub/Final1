from __future__ import annotations

from app.services.perf_chart_state import (
    build_bot_alpha_performance,
    compute_alpha_performance_pct,
)


def test_compute_alpha_performance_pct_zero_when_coin_and_balance_match():
    out = compute_alpha_performance_pct(1000.0, 100.0, 1100.0, 110.0)
    assert out is not None
    assert out["balance_pct"] == 10.0
    assert out["coin_pct"] == 10.0
    assert out["alpha_pct"] == 0.0


def test_compute_alpha_performance_pct_positive_alpha():
    # Coin +5%, balance +10% → alpha +5%
    out = compute_alpha_performance_pct(1000.0, 100.0, 1100.0, 105.0)
    assert out is not None
    assert out["balance_pct"] == 10.0
    assert out["coin_pct"] == 5.0
    assert out["alpha_pct"] == 5.0


def test_compute_alpha_performance_pct_negative_alpha():
    # Coin +10%, balance +5% → alpha -5%
    out = compute_alpha_performance_pct(1000.0, 100.0, 1050.0, 110.0)
    assert out is not None
    assert out["balance_pct"] == 5.0
    assert out["coin_pct"] == 10.0
    assert out["alpha_pct"] == -5.0


def test_build_bot_alpha_performance_from_chart_baseline(monkeypatch):
    class _Bot:
        id = 1
        account_id = 1
        symbol = "ETHUSDT"
        config_json = '{"initial_capital_usdt": 1000}'

    monkeypatch.setattr(
        "app.services.bot_equity.compute_bot_equity_usd",
        lambda *a, **k: 1100.0,
    )
    monkeypatch.setattr(
        "app.services.bot_equity.get_bot_last_price",
        lambda *a, **k: 105.0,
    )

    chart_payload = {
        "baseline": {
            "start_balance_usd": 1000.0,
            "start_coin_price": 100.0,
            "ts0": 1,
        }
    }
    out = build_bot_alpha_performance(
        None,
        _Bot(),
        {},
        current_usd=1100.0,
        current_price=105.0,
        chart_payload=chart_payload,
        pnl_data={},
    )
    assert out is not None
    assert out["alpha_pct"] == 5.0
