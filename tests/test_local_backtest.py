from pathlib import Path

from backtest import app as lb


def test_symbol_normalization_always_uses_usdt():
    assert lb.normalize_symbol("btc") == "BTCUSDT"
    assert lb.normalize_symbol("SOL/USDT") == "SOLUSDT"
    assert lb.normalize_symbol("bnb-usdt") == "BNBUSDT"


def test_monthly_rows_reports_period_and_initial_comparison():
    rows = lb.monthly_rows(
        [
            {"ts": 1706745600000, "equity": 1100},
            {"ts": 1709251200000, "equity": 1050},
        ],
        1000,
        initial_coin_price=100,
    )
    assert rows[0]["monthly_pnl"] == 100
    assert rows[1]["monthly_pnl"] == -50
    assert rows[1]["pnl_vs_initial"] == 50


def test_monthly_alpha_is_bot_return_minus_coin_return():
    rows = lb.monthly_rows(
        [
            {"ts": 1706745600000, "equity": 1100, "close": 120},
            {"ts": 1709164800000, "equity": 1210, "close": 126},
        ],
        1000,
        initial_coin_price=100,
    )
    assert rows[0]["bot_return_pct"] == 21
    assert rows[0]["coin_return_pct"] == 26
    assert rows[0]["alpha_pct"] == -5
    assert rows[0]["alpha_vs_initial_pct"] == -5


def test_monthly_rows_reports_cycle_directions_profit_and_all_fill_fees():
    cycles = [
        {"month": "2024-02", "direction": "UP", "profit_usdt": 4, "profit_coin": 0.04},
        {"month": "2024-02", "direction": "DOWN", "profit_usdt": 6, "profit_coin": 0.06},
    ]
    events = [
        {"event": "fill", "ts": 1706745600000, "fee": 0.2},
        {"event": "fill", "ts": 1709164800000, "fee": 0.3},
    ]
    rows = lb.monthly_rows(
        [{"ts": 1709164800000, "equity": 1010}],
        1000,
        cycles,
        events,
    )
    assert rows[0]["cycle_count"] == 2
    assert rows[0]["up_cycles"] == 1
    assert rows[0]["down_cycles"] == 1
    assert rows[0]["cycle_profit_usdt"] == 10
    assert rows[0]["cycle_profit_coin"] == 0.1
    assert rows[0]["commission_usdt"] == 0.5


def test_gap_detection_only_returns_missing_tail_when_covered():
    class Coverage(dict):
        pass

    coverage = Coverage(covered_start=0, covered_end=300)
    assert lb._missing_ranges([0, 100, 200], 0, 500, 100, coverage) == [(300, 500)]


def test_ui_file_is_present():
    assert (Path(lb.__file__).parent / "ui.html").is_file()


def test_ui_uses_app_parameter_names_and_only_manual_commission_cost():
    ui = (Path(lb.__file__).parent / "ui.html").read_text(encoding="utf-8")
    assert "Satış trailing" in ui
    assert "Alış trailing" in ui
    assert "Kâr alışı trailing" in ui
    assert "Kâr satışı trailing" in ui
    assert "Komisyon (%)" in ui
    assert 'id="slippage"' not in ui
    assert "Dönüş" not in ui


def test_backtest_ui_has_historical_parameter_assistant_and_dates():
    ui = (Path(lb.__file__).parent / "ui.html").read_text(encoding="utf-8")
    assert 'id="assistant"' in ui
    assert 'id="startDate"' in ui
    assert 'id="endDate"' in ui
    assert 'fetch("/api/parameter-assistant"' in ui
    assert "applyAssistant(data.backtest_config)" in ui


def test_backtest_date_parser_uses_exact_historical_day_boundary():
    assert lb._date_ms("2025-08-02") == 1_754_092_800_000
    assert lb._date_ms("2025-08-02", end_of_day=True) > lb._date_ms("2025-08-02")


def test_prepare_data_downloads_only_5m_market_series(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class FakeStore:
        pass

    async def fake_series(client, store, symbol, interval, start, end, progress):
        calls.append((symbol, interval))
        step = lb.INTERVAL_MS[interval]
        rows = [
            {"t": start + i * step, "o": 100, "h": 101, "l": 99, "c": 100, "v": 1}
            for i in range(8)
        ]
        rows.append({"t": end - step, "o": 100, "h": 101, "l": 99, "c": 100, "v": 1})
        return rows

    async def fake_constraints(client, symbol, fee_rate):
        return {}

    monkeypatch.setattr(lb, "CandleStore", FakeStore)
    monkeypatch.setattr(lb.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(lb, "ensure_series", fake_series)
    monkeypatch.setattr(lb, "fetch_constraints", fake_constraints)

    import asyncio

    result = asyncio.run(lb.prepare_data("ETHUSDT", 0.001, lambda _: None))
    # Python 3.9'da asyncio.run varsayılan döngüyü kapatır. Bu testten sonra
    # import edilen eski modüller import anında Lock/Semaphore kurduğu için
    # sıradaki testlere açık bir ana döngü bırak.
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert calls == [("ETHUSDT", "5m"), ("BTCUSDT", "5m")]
    assert result["execution"]
    assert result["execution"][0]["t"] >= result["start"]
    assert result["btc1"]
    assert result["btc4"]


def test_ui_and_health_contract_report_5m_execution():
    ui = (Path(lb.__file__).parent / "ui.html").read_text(encoding="utf-8")
    assert "son 1 yıllık 5 dakikalık mumlarda test eder" in ui
    assert "5dk motor" in ui
    assert "1 saatlik mumlarda test eder" not in ui
    assert lb.health()["execution_interval"] == "5m"


def test_dynamic_adapter_only_exposes_closed_resampled_candles():
    coin5 = [
        {"t": i * 300_000, "o": 100, "h": 101 + i, "l": 99, "c": 100 + i, "v": 1}
        for i in range(24)
    ]
    btc1 = lb.resample(coin5, lb.INTERVAL_MS["1h"])
    adapter = lb.HistoricalDynamicAdapter(
        "ETHUSDT",
        1000,
        {},
        coin5,
        btc1,
        lb.resample(btc1, lb.INTERVAL_MS["4h"]),
        lb.default_exchange_constraints("ETHUSDT"),
        [],
        [],
    )

    # Saat 01:05'te 01:00 mumu henüz kapanmamıştır; yalnız 00:00 mumu görünür.
    visible = adapter._slice(adapter.c1h, 3_900_000, 240)
    assert [row["t"] for row in visible] == [0]
    assert adapter.last_cycle == 0


def test_subtick_path_does_not_jump_over_live_gap_guard():
    from app.services.param_optimizer.backtest import _subtick_path

    path = _subtick_path(106.0, 106.1, 103.0, 104.0)
    moves = [abs(b / a - 1) * 100 for a, b in zip(path, path[1:]) if a > 0]
    assert max(moves) <= 0.20001


def test_fast_atr_history_matches_legacy_expanding_calculation():
    from app.botengine.dynamic import indicators as dyn
    from app.services.dynamic_param_score.indicators import _atr_pct_history

    candles = [
        {
            "t": i * 300_000,
            "o": 100 + i * 0.1,
            "h": 101 + i * 0.12,
            "l": 99 + i * 0.08,
            "c": 100.2 + i * 0.1,
            "v": 1000 + i,
        }
        for i in range(80)
    ]
    legacy = [
        dyn.atr_pct(candles[: i + 1], 14)
        for i in range(20, len(candles))
    ]
    fast = _atr_pct_history(candles, period=14, first_index=20)
    assert len(fast) == len(legacy)
    assert max(abs(a - b) for a, b in zip(fast, legacy)) < 1e-12
