"""V6 live selection chain integrity: returns, scores, R8 priority, headlines, mapping."""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import List, Optional

import pytest

from app.services.dynamic_param_score.indicators import (
    _returns_pct,
    _valid_closes,
    compute_indicators,
)
from app.services.dynamic_param_score.models import (
    Candle,
    ExchangeConstraints,
    MarketDataBundle,
    PortfolioState,
)
from app.services.dynamic_param_score.move_scores import (
    SCORE_HIGH,
    compute_dump_score,
    compute_fake_breakout_score,
    compute_move_scores,
    compute_pump_score,
    resolve_pump_dump_conflict,
)
from app.services.dynamic_param_score.v6.engine import V6Engine
from app.services.dynamic_param_score.v6.net_profile_library import (
    HEURISTIC_ONLY_PROFILE_KEYS,
    PROFILE_COPY,
    PROFILE_VALUES,
    _HINT_MAP,
    build_classification_trace,
    canonical_headline_for_key,
    select_profile_key,
)
from app.services.dynamic_param_score.v6.v6_indicator_adapter import build_v6_input_contract
from app.services.dynamic_param_score.v6.v6_pa_display import enrich_v6_display
from app.services.dynamic_param_score.v6.v6_scenario_classifier import (
    PRODUCED_SUB_PROFILE_HINTS,
    ClassifiedScenario,
    classify_scenario,
)
from app.services.dynamic_param_score.v6.domain.types import V6InputContract


def _closes_series(values: List[float]) -> List[float]:
    return list(values)


# ---------------------------------------------------------------------------
# 13.1 Indicator unit tests
# ---------------------------------------------------------------------------


def test_returns_pct_roc_is_one_bar_and_1h_is_twelve():
    closes = [100.0 + i * 0.0 for i in range(13)]
    closes[-1] = 101.0  # +1% last bar
    closes[-2] = 100.0
    closes[0] = 100.0
    assert _returns_pct(closes, 1) == pytest.approx(1.0)
    # 12-bar change from closes[-13]=closes[0]=100 to 101
    assert _returns_pct(closes, 12) == pytest.approx(1.0)


def test_roc_and_1h_independent_when_paths_differ():
    # Strong last-bar move, flat hour overall
    closes = [100.0] * 13
    closes[-2] = 100.0
    closes[-1] = 103.0  # +3% last bar
    # hour start also 100 → +3% hour; adjust start so hour is small
    closes[0] = 102.5  # hour ≈ (103-102.5)/102.5 ≈ 0.49%
    roc = _returns_pct(closes, 1)
    ret1 = _returns_pct(closes, 12)
    assert roc is not None and ret1 is not None
    assert roc != ret1
    assert roc > 2.5
    assert abs(ret1) < 1.0

    # Tiny last bar, strong hour
    closes2 = [100.0] * 13
    closes2[0] = 100.0
    closes2[-2] = 109.8
    closes2[-1] = 110.0  # +~0.18% last bar, +10% hour
    roc2 = _returns_pct(closes2, 1)
    ret12 = _returns_pct(closes2, 12)
    assert roc2 is not None and ret12 is not None
    assert roc2 != ret12
    assert abs(roc2) < 0.5
    assert ret12 > 8.0


@pytest.mark.parametrize(
    "closes,n,expected",
    [
        ([100.0, 101.0], 1, 1.0),
        ([100.0, 99.0], 1, -1.0),
        ([100.0, 100.0], 1, 0.0),
    ],
)
def test_returns_pct_signed_moves(closes, n, expected):
    assert _returns_pct(closes, n) == pytest.approx(expected)


def test_returns_pct_insufficient_and_invalid():
    assert _returns_pct([100.0], 1) is None
    assert _returns_pct([100.0] * 12, 12) is None  # needs 13
    assert _returns_pct([0.0, 101.0], 1) is None
    assert _returns_pct([-1.0, 101.0], 1) is None
    assert _returns_pct([100.0, float("nan")], 1) is None
    assert _returns_pct([100.0, float("inf")], 1) is None


def test_valid_closes_filters_bad_values():
    assert _valid_closes([100.0, 0.0, -2.0, float("nan"), 101.0]) == [100.0, 101.0]


def _synth_candles(closes: List[float], *, vol: float = 1000.0, start_t: int = 1_700_000_000_000) -> List[Candle]:
    out: List[Candle] = []
    for i, c in enumerate(closes):
        out.append(
            Candle(
                t=start_t + i * 300_000,
                o=c * 0.999,
                h=c * 1.002,
                l=c * 0.998,
                c=c,
                v=vol,
            )
        )
    return out


def _portfolio() -> PortfolioState:
    return PortfolioState(
        base_balance=0,
        quote_balance=100,
        base_value_usdt=0,
        quote_value_usdt=100,
        total_equity_usdt=100,
        current_base_exposure_frac=0,
    )


def _exchange() -> ExchangeConstraints:
    return ExchangeConstraints(
        min_notional=5,
        step_size=0.001,
        tick_size=0.01,
        min_qty=0.001,
        taker_fee_pct=0.1,
        maker_fee_pct=0.1,
        estimated_slippage_pct=0.05,
    )


def test_compute_indicators_roc_and_1h_not_same_helper_window():
    closes = [100.0] * 40
    closes[-2] = 100.0
    closes[-1] = 104.0
    closes[-13] = 103.5
    c5 = _synth_candles(closes)
    market = MarketDataBundle(
        symbol="TESTUSDT",
        base_asset="TEST",
        quote_asset="USDT",
        ticker_price=closes[-1],
        volume_24h=5_000_000,
        quote_volume_24h=5_000_000,
        market_timestamp=c5[-1].t,
        candles_5m=c5,
        candles_15m=_synth_candles(closes[::3] or closes[:20]),
        candles_1h=_synth_candles(closes[::12] or closes[:20], start_t=1_700_000_000_000),
        orderbook_top={"bid": 103.9, "ask": 104.1},
    )
    snap = compute_indicators(market, _portfolio())
    assert snap.roc_5m is not None
    assert snap.return_1h_pct is not None
    assert snap.roc_5m != snap.return_1h_pct
    assert snap.roc_5m == pytest.approx(4.0, abs=0.05)


# ---------------------------------------------------------------------------
# 13.2 Pump / dump / fake-breakout
# ---------------------------------------------------------------------------


def test_pump_score_stronger_than_mild_uptrend():
    strong = compute_pump_score(
        roc_5m=3.5,
        return_1h_pct=4.0,
        volume_spike=4.0,
        rsi_5m=78,
        z_score=2.0,
        bb_position=0.92,
        ema20_slope=0.35,
    )
    mild = compute_pump_score(
        roc_5m=0.4,
        return_1h_pct=0.6,
        volume_spike=1.2,
        rsi_5m=55,
        z_score=0.3,
        bb_position=0.55,
        ema20_slope=0.05,
    )
    assert strong is not None and mild is not None
    assert strong > mild
    assert strong >= SCORE_HIGH


def test_dump_score_stronger_than_mild_downtrend():
    strong = compute_dump_score(
        roc_5m=-3.5,
        return_1h_pct=-4.0,
        volume_spike=4.0,
        rsi_5m=22,
        z_score=-2.0,
        bb_position=0.08,
        ema20_slope=-0.35,
    )
    mild = compute_dump_score(
        roc_5m=-0.4,
        return_1h_pct=-0.6,
        volume_spike=1.2,
        rsi_5m=45,
        z_score=-0.3,
        bb_position=0.45,
        ema20_slope=-0.05,
    )
    assert strong is not None and mild is not None
    assert strong > mild


def test_pump_dump_conflict_resolution():
    p, d = resolve_pump_dump_conflict(80.0, 75.0)
    assert p == 80.0
    assert d is not None and d < 75.0


def test_fake_breakout_higher_than_continued_breakout():
    # Tight prior range ~100–101, final bar pierces high then closes back inside.
    candles_fake = []
    for i in range(17):
        c = 100.4 + (i % 2) * 0.2
        candles_fake.append({"t": i, "o": c, "h": c + 0.25, "l": c - 0.25, "c": c, "v": 80})
    candles_fake.append({"t": 17, "o": 101.0, "h": 103.2, "l": 100.8, "c": 100.9, "v": 60})
    candles_fake.append({"t": 18, "o": 100.9, "h": 101.1, "l": 100.5, "c": 100.7, "v": 55})
    candles_fake.append({"t": 19, "o": 100.7, "h": 100.9, "l": 100.4, "c": 100.6, "v": 50})

    # Continued breakout: expanding highs with strong closes and volume.
    candles_real = []
    for i in range(20):
        c = 100.0 + i * 0.35
        candles_real.append(
            {"t": i, "o": c - 0.1, "h": c + 0.45, "l": c - 0.15, "c": c + 0.3, "v": 800}
        )

    fake = compute_fake_breakout_score(
        candles_5m=candles_fake,
        volume_spike=1.0,
        roc_5m=-0.5,
        return_1h_pct=0.1,
        bb_position=0.52,
        z_score=0.2,
        range_stability=0.65,
    )
    real = compute_fake_breakout_score(
        candles_5m=candles_real,
        volume_spike=3.8,
        roc_5m=1.5,
        return_1h_pct=3.0,
        bb_position=0.93,
        z_score=1.8,
        range_stability=0.25,
    )
    assert fake is not None and real is not None
    assert fake > real


def test_move_scores_none_when_core_missing():
    out = compute_move_scores(
        candles_5m=[],
        roc_5m=None,
        return_1h_pct=None,
        volume_spike=None,
        rsi_5m=None,
        z_score=None,
        bb_position=None,
        ema20_slope=None,
        range_stability=None,
        lower_lows=None,
    )
    assert out["pump_score"] is None
    assert out["dump_score"] is None


def test_scores_flow_snapshot_to_contract():
    closes = [100.0 + i * 0.5 for i in range(60)]
    closes[-1] = closes[-2] * 1.04
    c5 = _synth_candles(closes, vol=50_000)
    market = MarketDataBundle(
        symbol="SOLUSDT",
        base_asset="SOL",
        quote_asset="USDT",
        ticker_price=closes[-1],
        volume_24h=80_000_000,
        quote_volume_24h=80_000_000,
        market_timestamp=c5[-1].t,
        candles_5m=c5,
        candles_15m=_synth_candles(closes[::3], vol=50_000),
        candles_1h=_synth_candles(closes[::12], vol=50_000),
        orderbook_top={"bid": closes[-1] * 0.999, "ask": closes[-1] * 1.001},
    )
    snap = compute_indicators(market, _portfolio())
    assert snap.pump_score is not None
    assert snap.pump_score > 0
    inp = build_v6_input_contract(
        symbol="SOLUSDT",
        bot_budget_usdt=100,
        current_price=closes[-1],
        ind=snap,
        market=market,
        exchange=_exchange(),
    )
    assert inp.pump_score == snap.pump_score
    assert inp.dump_score == snap.dump_score
    assert inp.fake_breakout_score == snap.fake_breakout_score
    assert inp.roc_5m == snap.roc_5m
    assert inp.return_1h_pct == snap.return_1h_pct


# ---------------------------------------------------------------------------
# Mapping / headline integrity
# ---------------------------------------------------------------------------


def test_hint_map_covers_all_produced_hints():
    assert set(_HINT_MAP.keys()) == set(PRODUCED_SUB_PROFILE_HINTS)
    for hint, profile in _HINT_MAP.items():
        assert profile in PROFILE_VALUES
        assert profile in PROFILE_COPY
        assert canonical_headline_for_key(profile)


def test_all_35_profiles_have_copy_and_values():
    assert len(PROFILE_VALUES) == 35
    assert set(PROFILE_VALUES) == set(PROFILE_COPY)
    for key, (title, why) in PROFILE_COPY.items():
        assert title.strip()
        assert why.strip()


def test_classifier_source_hints_match_produced_set():
    path = Path("app/services/dynamic_param_score/v6/v6_scenario_classifier.py")
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "sub_profile_hint":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        if node.value.value:
                            found.add(node.value.value)
    assert found == set(PRODUCED_SUB_PROFILE_HINTS)


@pytest.mark.parametrize("profile_key", sorted(PROFILE_VALUES.keys()))
def test_canonical_headline_matches_profile_copy(profile_key):
    classified = ClassifiedScenario("R3", "01", "001", "PB01", "x", "")
    classified.regime_id = profile_key.split("_", 1)[0]
    # Force selection via hint when available, else direct build
    from app.services.dynamic_param_score.v6.net_profile_library import build_profile

    profile = build_profile(profile_key, classified, "STD")
    assert profile.profile_id == profile_key
    assert profile.scenario.name == PROFILE_COPY[profile_key][0]
    assert profile.modules["canonical_headline"] == PROFILE_COPY[profile_key][0]


def test_unknown_hint_does_not_silently_map_and_logs_fallback(caplog):
    classified = ClassifiedScenario("R1", "01", "001", "PB05", "x", "R1_UNKNOWN_HINT")
    inp = V6InputContract(
        symbol="X",
        bot_budget_usdt=50,
        current_price=1.0,
        min_notional=5,
        tick_size=0.01,
        step_size=0.001,
        price_precision=8,
        quantity_precision=8,
    )
    with caplog.at_level("WARNING"):
        key = select_profile_key(classified, inp)
    assert key == "R1_STRONG_UPTREND"
    assert any("Unknown sub_profile_hint" in r.message for r in caplog.records)


def test_r8_hard_block_beats_liquidity_weak():
    classified = ClassifiedScenario(
        "R8",
        "01",
        "004",
        "PB11",
        "Hard block",
        "R8_HARD_BLOCK",
        hard_block=True,
        hard_block_reasons=("invalid_spread",),
    )
    inp = V6InputContract(
        symbol="X",
        bot_budget_usdt=50,
        current_price=1.0,
        min_notional=5,
        tick_size=0.01,
        step_size=0.001,
        price_precision=8,
        quantity_precision=8,
        spread_pct=0.5,
        volume_consistency=0.1,
        return_24h_pct=-12,
        crash_velocity=-4,
        drawdown_7d_pct=55,
    )
    key = select_profile_key(classified, inp)
    assert key == "R8_HARD_BLOCK"
    assert canonical_headline_for_key(key) == PROFILE_COPY["R8_HARD_BLOCK"][0]


def test_r8_crash_with_liquidity_uses_low_liq_profile():
    classified = ClassifiedScenario("R8", "01", "001", "PB11", "Crash", "R8_DEF_PANIC")
    inp = V6InputContract(
        symbol="X",
        bot_budget_usdt=50,
        current_price=1.0,
        min_notional=5,
        tick_size=0.01,
        step_size=0.001,
        price_precision=8,
        quantity_precision=8,
        spread_pct=0.2,
        volume_consistency=0.2,
    )
    assert select_profile_key(classified, inp) == "R8_LOW_LIQUIDITY_RESTRICTED"


def test_display_does_not_rewrite_canonical_headline():
    from app.services.dynamic_param_score.v6.v6_botparams_adapter import v6_final_to_telemetry_extras

    inp = V6InputContract(
        symbol="ADAUSDT",
        bot_budget_usdt=100,
        current_price=1.0,
        min_notional=5,
        tick_size=0.0001,
        step_size=0.1,
        price_precision=8,
        quantity_precision=8,
        adx_1h=35,
        rsi_1h=70,
        price_vs_ema200_pct=8,
        return_24h_pct=6,
        higher_highs=True,
        lower_lows=False,
        bb_position=0.8,
        z_score=1.2,
        volatility_percentile=50,
        spread_pct=0.02,
        volume_consistency=0.8,
        volume_24h=20_000_000,
        candles_5m=500,
        candles_1h=200,
        price_valid=True,
        ema20_slope=0.2,
        ema50_slope=0.15,
    )
    result = V6Engine().run(inp)
    scenario = result.telemetry.get("scenario") or {}
    display_base = v6_final_to_telemetry_extras(result, bot_budget_usdt=100)
    scen_id = dict(display_base.get("scenario_identity") or {})
    scen_id.update(
        {
            "canonical_headline": scenario.get("canonical_headline"),
            "headline": scenario.get("headline"),
            "selected_profile_key": scenario.get("selected_profile_key")
            or scenario.get("net_profile_key"),
            "name": "Toparlanma",  # misleading label must not drive UI rewrite
        }
    )
    display_base["scenario_identity"] = scen_id
    display = enrich_v6_display(
        display_base,
        opportunity_notes=result.telemetry.get("opportunity_notes") or {},
    )
    key = result.profile.profile_id
    expected = canonical_headline_for_key(key)
    assert display["canonical_headline"] == expected
    assert display["regime_headline"] == f"{key.split('_', 1)[0]} · {expected}"
    assert display["regime_headline"] != "R5 · Breakout / momentum"
    assert "Likidite/spread restricted" not in display["regime_headline"]


def test_classification_trace_fields_present():
    classified = ClassifiedScenario(
        "R8",
        "01",
        "004",
        "PB11",
        "Hard block",
        "R8_HARD_BLOCK",
        hard_block=True,
        hard_block_reasons=("market_integrity_failure",),
        matched_gates=("r8_hard_block",),
    )
    inp = V6InputContract(
        symbol="X",
        bot_budget_usdt=50,
        current_price=1.0,
        min_notional=5,
        tick_size=0.01,
        step_size=0.001,
        price_precision=8,
        quantity_precision=8,
        roc_5m=-1.0,
        return_1h_pct=-2.0,
        pump_score=None,
        dump_score=40.0,
        fake_breakout_score=None,
        spread_pct=0.4,
        candles_5m=10,
        price_valid=True,
    )
    key = select_profile_key(classified, inp)
    trace = build_classification_trace(classified, inp, selected_profile_key=key)
    for field in (
        "input_data_quality",
        "roc_5m",
        "return_1h_pct",
        "pump_score",
        "dump_score",
        "fake_breakout_score",
        "hard_block",
        "hard_block_reason",
        "liquidity_weak",
        "matched_gates",
        "selected_regime",
        "selected_hint",
        "selected_profile_key",
        "canonical_headline",
        "fallback_used",
        "confidence",
    ):
        assert field in trace
    assert trace["selected_profile_key"] == "R8_HARD_BLOCK"
    assert "pump_score" in trace["missing_fields"]


def test_cascade_parabolic_beats_hard_block_signals():
    """Existing business rule: parabolic pump is evaluated before hard-block."""
    inp = V6InputContract(
        symbol="PUMPUSDT",
        bot_budget_usdt=100,
        current_price=10,
        min_notional=5,
        tick_size=0.01,
        step_size=0.001,
        price_precision=8,
        quantity_precision=8,
        return_24h_pct=40,
        return_4h_pct=20,
        return_1h_pct=8,
        price_vs_ema200_pct=25,
        adx_1h=40,
        higher_highs=True,
        lower_lows=False,
        rsi_1h=85,
        bb_position=0.95,
        z_score=2.5,
        atr_1h_pct=6,
        drawdown_7d_pct=0,
        crash_velocity=0,
        spread_pct=0.4,  # would contribute to hard-block if reached
        volume_24h=5_000_000,
        volume_consistency=0.7,
        candles_5m=500,
        candles_1h=200,
        price_valid=True,
        ema20_slope=0.5,
        ema50_slope=0.4,
    )
    classified = classify_scenario(inp)
    assert classified.regime_id == "R5"
    assert classified.sub_profile_hint == "R5_DEF_PARABOLIC_OVEREXTENDED"


def test_live_engine_import_does_not_use_v4_selector():
    engine_path = Path("app/services/dynamic_param_score/engine.py")
    src = engine_path.read_text(encoding="utf-8")
    assert "param_pool.selector" not in src
    assert "route_key" not in src or "v6" in src.lower()
    v6_engine = Path("app/services/dynamic_param_score/v6/engine.py").read_text(encoding="utf-8")
    assert "query_route_shelf" not in v6_engine
    assert "select_profile_key" in Path(
        "app/services/dynamic_param_score/v6/net_profile_library.py"
    ).read_text(encoding="utf-8")


def test_heuristic_only_profiles_documented():
    mapped = set(_HINT_MAP.values())
    unreachable = set(PROFILE_VALUES) - mapped - HEURISTIC_ONLY_PROFILE_KEYS
    assert not unreachable, f"Profiles neither mapped nor marked heuristic-only: {unreachable}"
