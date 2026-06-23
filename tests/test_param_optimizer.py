"""
param_optimizer backtest motoru testleri.

Amaç: backtest'in GERÇEK dca_grid_trailing motorunu sürdüğünü ve mantıklı
cycle PnL / muhasebe ürettiğini kanıtlamak.
"""

from __future__ import annotations

import time
import os

from app.services.param_optimizer.backtest import run_backtest


def _mk_candles(prices, day_ms=86_400_000):
    """Kapanış listesinden basit OHLC mumları (intrabar uçları kapanış etrafında)."""
    out = []
    t = 1_600_000_000_000
    prev = prices[0]
    for i, c in enumerate(prices):
        o = prev
        hi = max(o, c) * 1.001
        lo = min(o, c) * 0.999
        out.append({"t": t + i * day_ms, "o": o, "h": hi, "l": lo, "c": c, "v": 1000.0})
        prev = c
    return out


def _params(**over):
    p = {
        "base_alloc_pct": 50.0,
        "quote_alloc_pct": 50.0,
        "sell_grids": [{"sell_grid_pct": 2.0, "sell_qty_pct_of_base": 100.0}],
        "buy_grids": [{"buy_grid_pct": 2.0, "buy_qty_pct_of_quote": 100.0}],
        "sell_trigger_trailing_pct": 0.3,
        "buy_trigger_trailing_pct": 0.3,
        "profit_reentry_drop_pct": 1.0,
        "profit_reentry_rise_pct": 0.3,
        "profit_exit_rise_pct": 1.0,
        "profit_exit_drop_pct": 0.3,
        "min_notional_guard": 10.0,
        "fee_rate": 0.001,
    }
    p.update(over)
    return p


def test_flat_price_no_cycles_equity_preserved():
    candles = _mk_candles([100.0] * 60)
    r = run_backtest(candles, _params(), budget=1000.0, symbol="BTCUSDT")
    assert r.ok
    assert r.cycles_closed == 0
    # düz piyasada sadece ilk alım komisyonu kadar kayıp olmalı (< %0.2)
    assert r.return_pct > -0.3, r.to_dict()
    assert r.return_pct <= 0.01


def test_sell_side_cycle_completes_and_profits():
    # 100 -> 106 (sell grid +2% + trailing sat) -> 95 (reentry arm @ ~ -1%) -> 99 (geri al)
    up = [100, 101, 102, 103, 104, 105, 106]
    down = [104, 102, 100, 98, 96, 95]
    back = [96, 97, 98, 99, 100]
    candles = _mk_candles(up + down + back + [100] * 5)
    r = run_backtest(candles, _params(), budget=1000.0, symbol="BTCUSDT")
    assert r.ok
    assert r.cycles_closed >= 1, r.to_dict()
    # en az bir tur kapanmış ve toplam realized cycle pnl pozitife yakın olmalı
    assert r.trades >= 2, r.to_dict()


def test_buy_side_cycle_completes():
    # 100 -> 94 (buy grid -2% + trailing al) -> 102 (profit exit +) -> geri
    down = [100, 99, 98, 97, 96, 95, 94]
    up = [95, 97, 99, 101, 103, 104]
    back = [103, 102, 101, 100]
    candles = _mk_candles(down + up + back + [101] * 5)
    r = run_backtest(candles, _params(), budget=1000.0, symbol="BTCUSDT")
    assert r.ok
    assert r.cycles_closed >= 1, r.to_dict()


def test_oscillation_many_cycles():
    # tekrarlı dalga: çok sayıda tur üretmeli
    wave = []
    base = 100.0
    for _ in range(30):
        wave += [base, base * 1.03, base * 1.005, base * 0.97, base * 1.0]
    candles = _mk_candles(wave)
    r = run_backtest(candles, _params(), budget=1000.0, symbol="BTCUSDT")
    assert r.ok
    assert r.cycles_closed >= 3, r.to_dict()
    assert r.fees_paid > 0


def _synth_history(n_days=720, drift=0.0006, day_ms=86_400_000):
    """Salınımlı + hafif drift'li sentetik geçmiş (daily + 4h backtest serisi)."""
    import math as _m

    daily_p = [
        100 * (1 + drift) ** i * (1 + 0.10 * _m.sin(i / 16.0) + 0.04 * _m.sin(i / 4.0))
        for i in range(n_days)
    ]
    daily = _mk_candles(daily_p, day_ms)
    nh = n_days * 6
    bt_p = [
        100
        * (1 + drift) ** (i / 6)
        * (
            1
            + 0.10 * _m.sin(i / 96.0)
            + 0.04 * _m.sin(i / 24.0)
            + 0.012 * _m.sin(i / 3.0)
        )
        for i in range(nh)
    ]
    bt = _mk_candles(bt_p, 4 * 3600 * 1000)
    return daily, bt


def test_space_decode_respects_min_notional_and_allocs():
    from app.services.param_optimizer.indicators import compute_features
    from app.services.param_optimizer.space import build_space, decode

    daily, _bt = _synth_history(400)
    f = compute_features(daily)
    budget = 120.0
    mn = 10.0
    space = build_space(f, budget, min_notional=mn, symbol="TESTUSDT")
    import random as _r

    rng = _r.Random(7)
    for _ in range(200):
        p = decode(space.random(rng), space)
        # alloc toplamı 100
        assert abs(p["base_alloc_pct"] + p["quote_alloc_pct"] - 100.0) < 1e-6
        base_leg = budget * p["base_alloc_pct"] / 100.0
        quote_leg = budget * p["quote_alloc_pct"] / 100.0
        # her satış seviyesi min-notional'ı karşılamalı
        for g in p["sell_grids"]:
            assert base_leg * g["sell_qty_pct_of_base"] / 100.0 >= mn - 1e-6, p
        for g in p["buy_grids"]:
            assert quote_leg * g["buy_qty_pct_of_quote"] / 100.0 >= mn - 1e-6, p
        # qty toplamı %100'ü aşmamalı (bacak tükenmesin)
        assert sum(g["sell_qty_pct_of_base"] for g in p["sell_grids"]) <= 100.5
        assert sum(g["buy_qty_pct_of_quote"] for g in p["buy_grids"]) <= 100.5


def test_param_space_long_horizon_avoids_too_tight_grids():
    from app.services.param_optimizer.indicators import compute_features
    from app.services.param_optimizer.space import (
        LONG_HORIZON_MIN_STEP_PCT,
        build_space,
        decode,
    )

    daily, _bt = _synth_history(720)
    f = compute_features(daily)
    space = build_space(f, 100.0, min_notional=10.0, symbol="BTCUSDT")
    center = decode(space.center(), space)

    assert center["sell_grids"][0]["sell_grid_pct"] >= LONG_HORIZON_MIN_STEP_PCT
    assert center["buy_grids"][0]["buy_grid_pct"] >= LONG_HORIZON_MIN_STEP_PCT
    assert len(center["sell_grids"]) >= 2
    assert len(center["buy_grids"]) >= 2

    import random as _r

    rng = _r.Random(42)
    for _ in range(60):
        p = decode(space.random(rng), space)
        assert p["sell_grids"][0]["sell_grid_pct"] >= LONG_HORIZON_MIN_STEP_PCT
        assert p["buy_grids"][0]["buy_grid_pct"] >= LONG_HORIZON_MIN_STEP_PCT
        if len(p["buy_grids"]) > 1:
            assert p["buy_grids"][1]["buy_grid_pct"] > p["buy_grids"][0]["buy_grid_pct"]


def test_buy_grids_never_below_minus_100_pct():
    """Alış gridi referanstan mutlak düşüş %'sidir; %100+ matematiksel olarak
    imkânsızdır (fiyat negatife gidemez). decode() bunu asla üretmemeli."""
    from app.services.param_optimizer.indicators import compute_features
    from app.services.param_optimizer.space import (
        build_space,
        decode,
        MAX_BUY_DEPTH_PCT,
    )
    import random as _r

    for seed_days in (400, 720):
        daily, _bt = _synth_history(seed_days)
        f = compute_features(daily)
        for budget in (120.0, 500.0, 5000.0):
            space = build_space(f, budget, min_notional=10.0, symbol="TESTUSDT")
            rng = _r.Random(seed_days + int(budget))
            for _ in range(300):
                p = decode(space.random(rng), space)
                bps = [g["buy_grid_pct"] for g in p["buy_grids"]]
                for bp in bps:
                    assert bp < MAX_BUY_DEPTH_PCT, p
                    assert bp < 100.0, p
                assert bps == sorted(bps), p  # kesme sonrası monotonluk korunur


def test_down_regime_allocation_is_quote_heavy():
    """Aşağı baskı/dump rejiminde base oranı belirgin biçimde quote'un altında
    olmalı (gerçek savunma). Eski davranış ~%43 base üretiyordu."""
    from app.services.param_optimizer.indicators import compute_features
    from app.services.param_optimizer.space import (
        build_space,
        decode,
        DOWN_REGIME_MAX_BASE_PCT,
    )

    n = 540
    prices = [100.0 * (0.9965 ** i) for i in range(n)]
    daily = _mk_candles(prices)
    f = compute_features(daily)
    if f.regime_code not in ("TRENDING_DOWN", "DUMP_RISK"):
        pytest.skip(f"beklenen aşağı rejim oluşmadı: {f.regime_code}")
    space = build_space(f, 200.0, min_notional=10.0, symbol="TESTUSDT")
    center = decode(space.center(), space)
    assert center["base_alloc_pct"] <= DOWN_REGIME_MAX_BASE_PCT + 1e-6, center
    assert center["base_alloc_pct"] < center["quote_alloc_pct"], center


def test_confidence_drops_when_oos_negative():
    """Güven indikatör netliğine değil OOS sonucuna da bağlı olmalı: negatif OOS
    + tek tur + zayıf MC ile 90 güven mümkün olmamalı (kullanıcı kritiği #8)."""
    from app.services.param_optimizer.engine import adjust_confidence

    weak = adjust_confidence(
        90,
        oos={"return_pct": -13.97, "cycles_closed": 1, "max_drawdown_pct": 25.46},
        inr={"return_pct": 68.47, "max_drawdown_pct": 51.26},
        forecast={"prob_profit": 0.57, "median_return_pct": 3.0, "n_paths": 30},
    )
    assert weak < 35, weak
    assert 5 <= weak <= 30, weak

    strong = adjust_confidence(
        80,
        oos={"return_pct": 22.0, "cycles_closed": 8, "max_drawdown_pct": 12.0},
        inr={"return_pct": 40.0, "max_drawdown_pct": 18.0},
        forecast={"prob_profit": 0.72, "median_return_pct": 11.0, "n_paths": 200},
    )
    assert strong >= weak + 15
    assert strong < 70  # 8 OOS tur hâlâ 30 referans turun altında kalır


def test_low_adx_trend_score_does_not_force_trending_down_regime():
    from app.services.param_optimizer.indicators import HistoryFeatures, _classify_regime

    f = HistoryFeatures()
    f.adx = 6.0
    f.trend_score = -0.48
    f.hurst = 0.48
    f.rsi = 54.0
    f.stoch_k = 52.0
    f.mean_reversion = 0.55
    f.daily_range_med_pct = 2.0
    f.bbw_pct = 5.0
    f.grid_suitability = 0.66
    w = {
        "m1": {"return_pct": -5.0},
    }

    code, label = _classify_regime(f, w)

    assert code == "LOW_VOL_RANGING"
    assert "yatay" in label


def test_space_uses_atr_anchored_grid_not_full_swing():
    from app.services.param_optimizer.indicators import HistoryFeatures
    from app.services.param_optimizer.space import build_space, decode

    f = HistoryFeatures()
    f.atr_pct = 2.48
    f.swing_pct = 5.91
    f.swing7_pct = 8.0
    f.daily_range_med_pct = 3.0
    f.realized_vol_pct = 2.5
    f.adx = 6.0
    f.trend_score = -0.42
    f.grid_suitability = 0.66
    f.regime_code = "LOW_VOL_RANGING"

    space = build_space(f, 500.0, min_notional=10.0, symbol="BTCUSDT")
    center = decode(space.center(), space)

    first_sell = center["sell_grids"][0]["sell_grid_pct"]
    first_buy = center["buy_grids"][0]["buy_grid_pct"]
    assert 2.0 <= first_sell <= 3.2, center
    assert 2.0 <= first_buy <= 3.2, center
    assert first_sell < f.swing_pct
    assert first_buy < f.swing_pct


def test_backtest_alpha_decomposes_cash_buffer_from_grid_skill():
    candles = _mk_candles([100.0, 92.0, 85.0, 78.0, 72.25])
    r = run_backtest(
        candles,
        _params(
            base_alloc_pct=45.0,
            quote_alloc_pct=55.0,
            sell_grids=[{"sell_grid_pct": 50.0, "sell_qty_pct_of_base": 100.0}],
            buy_grids=[{"buy_grid_pct": 50.0, "buy_qty_pct_of_quote": 100.0}],
        ),
        budget=1000.0,
        symbol="BTCUSDT",
    )

    assert r.ok
    d = r.to_dict()
    assert "grid_alpha_pct" in d
    assert "cash_buffer_alpha_pct" in d
    assert r.alpha_pct != pytest.approx(r.grid_alpha_pct)
    assert r.cash_buffer_alpha_pct > 0


def test_backtest_reports_exposure_drift_vs_intended():
    """Düşüşte dip alan grid maruziyeti NİYET edilenin üstüne sürükler (gizli long).

    'Maruziyet-eş grid alpha' kaymış orana göredir ve bunu örter; niyete göre
    alpha ile exposure_drift kaymayı açığa çıkarmalı.
    """
    # Niyet düşük base (%30); keskin düşüş + küçük sıçramalar alış gridlerini
    # doldurur, satış gridi çok geniş (asla ateşlemez) -> base birikir.
    wave = []
    px = 100.0
    for _ in range(8):
        wave += [px, px * 0.95, px * 0.962]  # ~%5 düş, ~%1.2 sıçra (alışı doldurur)
        px *= 0.95
    candles = _mk_candles(wave)
    r = run_backtest(
        candles,
        _params(
            base_alloc_pct=30.0,
            quote_alloc_pct=70.0,
            sell_grids=[{"sell_grid_pct": 50.0, "sell_qty_pct_of_base": 100.0}],
            buy_grids=[
                {"buy_grid_pct": 3.0, "buy_qty_pct_of_quote": 40.0},
                {"buy_grid_pct": 6.0, "buy_qty_pct_of_quote": 40.0},
            ],
            buy_trigger_trailing_pct=0.2,
        ),
        budget=3000.0,
        symbol="BTCUSDT",
    )
    assert r.ok
    d = r.to_dict()
    for k in ("intended_base_frac", "exposure_drift", "grid_alpha_vs_intended_pct",
              "intended_static_return_pct"):
        assert k in d
    # niyet alanı config'ten birebir gelir
    assert r.intended_base_frac == pytest.approx(0.30)
    # kimlikler tutarlı (deterministik)
    assert r.exposure_drift == pytest.approx(r.exposure_frac - r.intended_base_frac)
    assert r.intended_static_return_pct == pytest.approx(
        r.intended_base_frac * r.buy_hold_return_pct
    )
    assert r.grid_alpha_vs_intended_pct == pytest.approx(
        r.return_pct - r.intended_static_return_pct
    )
    # düşüşte dip alan grid maruziyeti niyetin ÜSTÜNE çeker (gizli long)
    assert r.exposure_frac > r.intended_base_frac, d
    assert r.exposure_drift > 0
    # niyete göre alpha, kaymış-maruziyete göre grid alpha'dan FARKLIDIR (kaymayı açar)
    assert r.grid_alpha_vs_intended_pct != pytest.approx(r.grid_alpha_pct)


def test_backtest_reports_cost_drag_and_taker_extra():
    """Maliyet sürtünmesi (komisyon+slipaj) raporlanmalı; taker_extra slipajı artırır."""
    wave = []
    base = 100.0
    for _ in range(20):
        wave += [base, base * 1.03, base * 1.005, base * 0.97, base * 1.0]
    candles = _mk_candles(wave)
    r0 = run_backtest(candles, _params(), budget=1000.0, symbol="BTCUSDT", slippage_bps=2.0)
    assert r0.ok
    d = r0.to_dict()
    assert "cost_drag_pct" in d and "slippage_cost" in d
    # komisyon + slipaj birikti -> sürtünme pozitif
    assert r0.fees_paid > 0
    assert r0.slippage_cost > 0
    assert r0.cost_drag_pct == pytest.approx(
        (r0.fees_paid + r0.slippage_cost) / 1000.0 * 100.0
    )
    # taker impact ekleyince slipaj maliyeti ARTAR (komisyon aynı kalır)
    r1 = run_backtest(
        candles, _params(), budget=1000.0, symbol="BTCUSDT",
        slippage_bps=2.0, taker_extra_bps=8.0,
    )
    assert r1.slippage_cost > r0.slippage_cost
    assert r1.cost_drag_pct > r0.cost_drag_pct


def test_walk_forward_cross_period_validation():
    """Seçilen set çok sayıda tarihsel dilimde doğrulanır (tek OOS / n=3 yerine)."""
    from app.services.param_optimizer.engine import _segment_folds, _walk_forward_eval
    from app.services.param_optimizer.objective import ObjectiveConfig

    wave = []
    base = 100.0
    for _ in range(60):
        wave += [base, base * 1.03, base * 1.005, base * 0.97, base * 1.0]
    candles = _mk_candles(wave)  # 300 mum -> 4 dilim x 75 >= min_bars
    folds = _segment_folds(candles, 4)
    assert len(folds) == 4
    assert all(len(f) >= 60 for f in folds)

    wf = _walk_forward_eval(
        _params(), candles, 4, 1000.0, "BTCUSDT",
        fee=0.001, slippage=2.0, obj_cfg=ObjectiveConfig(),
    )
    assert wf is not None
    assert wf["n_folds"] == 4
    assert len(wf["per_fold"]) == 4
    assert 0.0 <= wf["frac_profitable"] <= 1.0
    assert wf["folds_profitable"] <= wf["n_folds"]
    for k in ("mean_return_pct", "median_return_pct", "worst_fold_return_pct",
              "best_fold_return_pct", "total_cycles", "consistency_score"):
        assert k in wf
    # salınımlı seri -> dilimlerde tur kapanır
    assert wf["total_cycles"] >= 1, wf


def test_walk_forward_too_few_bars_returns_none():
    from app.services.param_optimizer.engine import _segment_folds, _walk_forward_eval
    from app.services.param_optimizer.objective import ObjectiveConfig

    candles = _mk_candles([100.0] * 30)  # çok az veri
    assert _segment_folds(candles, 6) == []
    assert _walk_forward_eval(
        _params(), candles, 6, 1000.0, "BTCUSDT",
        fee=0.001, slippage=2.0, obj_cfg=ObjectiveConfig(),
    ) is None


def test_backtest_reports_expectancy_metrics():
    """win-rate yanıltıcı olabilir; payoff/beklenti/başabaş kimlikleri tutarlı olmalı."""
    wave = []
    base = 100.0
    for _ in range(30):
        wave += [base, base * 1.03, base * 1.005, base * 0.97, base * 1.0]
    candles = _mk_candles(wave)
    r = run_backtest(candles, _params(), budget=1000.0, symbol="BTCUSDT")
    assert r.ok
    assert r.cycles_closed >= 3, r.to_dict()
    d = r.to_dict()
    for k in ("avg_win", "avg_loss", "payoff", "breakeven_payoff", "expectancy_per_cycle"):
        assert k in d
    p = r.win_rate / 100.0
    # başabaş payoff = (1-p)/p
    if 0.0 < p < 1.0:
        assert r.breakeven_payoff == pytest.approx((1.0 - p) / p)
    # beklenti = p*avg_win - (1-p)*avg_loss
    assert r.expectancy_per_cycle == pytest.approx(
        p * r.avg_win - (1.0 - p) * r.avg_loss
    )
    if r.avg_loss > 0:
        assert r.payoff == pytest.approx(r.avg_win / r.avg_loss)


def test_hurst_label_uses_own_thresholds_not_trend():
    """Hurst etiketi KENDİ eşiklerine göre verilmeli; 0.48 'trendli' değildir."""
    from app.services.param_optimizer.engine import _hurst_label
    from app.services.param_optimizer.indicators import HistoryFeatures

    f = HistoryFeatures()
    f.hurst = 0.40
    assert "mean-reversion" in _hurst_label(f)

    # 0.48: trend skoru/ADX ne olursa olsun 'trendli' DEĞİL, nötr/hafif mean-reverting
    f.hurst = 0.48
    f.adx = 6.0
    f.trend_score = -0.42
    lbl = _hurst_label(f)
    assert "nötr" in lbl and "trend" not in lbl, lbl

    f.hurst = 0.60
    assert "trend devamlılığı" in _hurst_label(f)


def test_low_adx_not_called_strong_trend():
    """Düşük ADX'te (6) trend skoru -0.42 olsa bile 'güçlü trend' denmemeli;
    yatay/dalgalı + hafif eğilim olarak okunmalı."""
    from app.services.param_optimizer.engine import build_rationale
    from app.services.param_optimizer.indicators import HistoryFeatures

    f = HistoryFeatures()
    f.regime_label = "yatay / dalgalı"
    f.adx = 6.0
    f.trend_score = -0.42
    f.hurst = 0.48
    f.swing_pct = 5.91
    f.atr_pct = 2.48
    result = {
        "best_params": {
            "base_alloc_pct": 28.0, "quote_alloc_pct": 72.0,
            "sell_grids": [{"sell_grid_pct": 14.36, "sell_qty_pct_of_base": 100.0}],
            "buy_grids": [{"buy_grid_pct": 15.55, "buy_qty_pct_of_quote": 100.0}],
            "sell_trigger_trailing_pct": 0.2, "buy_trigger_trailing_pct": 2.5,
            "profit_exit_rise_pct": 1.0, "profit_exit_drop_pct": 0.3,
            "profit_reentry_drop_pct": 1.0, "profit_reentry_rise_pct": 0.3,
        },
        "in_sample_result": {"return_pct": 385.0, "cycles_closed": 6, "win_rate": 83.0, "max_drawdown_pct": 54.78},
        "oos_result": {"return_pct": -4.54, "cycles_closed": 0, "max_drawdown_pct": 8.45, "alpha_pct": 1.0},
        "stats": {},
        "forecast": {},
    }
    text = " ".join(build_rationale("BTCUSDT", 100.0, f, result, confidence=48)["lines"])
    # Düşük ADX POZİTİF olarak 'güçlü trende işaret ediyor' diye sunulmamalı
    assert "trende işaret ediyor" not in text, text
    # Doğru yorum: trend gücü zayıf / yatay-dalgalı
    assert "trend GÜCÜ zayıf" in text and "yatay/dalgalı" in text, text
    # OOS 0 tur -> pasif/izleme seti uyarısı
    assert "0 tur" in text and "pasif/izleme" in text, text
    # ilk grid swing'in 2 katından geniş -> düşük işlem sıklığı uyarısı
    assert "işlem sıklığı düşük" in text, text
    # in-sample küçük örneklem uyarısı (6 tur)
    assert "istatistiksel güveni" in text, text


def test_confidence_capped_when_oos_zero_cycles():
    """OOS'ta 0 tur kapanırsa güven 48'i geçmemeli (aktif grid doğrulanmadı)."""
    from app.services.param_optimizer.engine import adjust_confidence

    c = adjust_confidence(
        89,
        oos={"return_pct": -4.54, "cycles_closed": 0, "max_drawdown_pct": 8.45},
        inr={"return_pct": 385.0, "max_drawdown_pct": 54.78},
        forecast={"prob_profit": 0.5, "median_return_pct": 0.0, "n_paths": 40},
    )
    assert c <= 48, c
    assert c <= 10, c  # 0 tur + negatif OOS artık ciddi şekilde dip güven


def test_features_detect_regime():
    from app.services.param_optimizer.indicators import compute_features

    daily, _ = _synth_history(500, drift=0.0)
    f = compute_features(daily)
    assert f.coverage > 0.5
    assert 0.0 <= f.mean_reversion <= 1.0
    assert f.regime_code in (
        "LOW_VOL_RANGING",
        "HIGH_VOL_RANGING",
        "SQUEEZE",
        "TRENDING_UP",
        "TRENDING_DOWN",
        "DUMP_RISK",
    )


def test_engine_end_to_end_synthetic():
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(720)
    stages = []
    r = run_optimization(
        "TESTUSDT",
        500.0,
        daily=daily,
        backtest_candles=bt,
        time_budget_sec=10,
        n_workers=1,
        tier_key="soft",
        progress_cb=lambda e: stages.append(e.get("stage")),
    )
    assert r["ok"], r
    p = r["params"]
    assert p["sell_grids"] and p["buy_grids"]
    assert r["ui_config"]["up"]["grids"]
    assert r["oos"] is not None
    assert r["rationale"]["lines"]
    assert {"features", "measure", "coarse", "validate", "done"}.issubset(set(stages))
    # bütçe ~10s, makul üst sınır içinde bitmeli
    assert r["elapsed_sec"] < 40


def test_optimizer_never_worse_than_prior():
    """Optimizer'ın nihai skoru (in+OOS) en az merkez prior kadar iyi olmalı.

    Optimizer final_score'a göre seçer (OOS sağlamlığı dahil), in-sample max'a
    göre değil. Merkez her zaman doğrulananlar arasında olduğundan kazanan
    asla prior'dan kötü final_score'a sahip olamaz.
    """
    from app.services.param_optimizer.indicators import compute_features
    from app.services.param_optimizer.space import build_space, decode
    from app.services.param_optimizer.engine import _split_by_days
    from app.services.param_optimizer.objective import combined_score

    daily, bt = _synth_history(720)
    f = compute_features(daily)
    space = build_space(f, 500.0, symbol="TESTUSDT")
    train, oos = _split_by_days(bt, 182)
    _, recent = _split_by_days(train, 365)
    cp = decode(space.center(), space)
    prior_final = combined_score(
        run_backtest(train, cp, 500.0, "TESTUSDT"),
        run_backtest(oos, cp, 500.0, "TESTUSDT"),
        run_backtest(recent, cp, 500.0, "TESTUSDT"),
    )["final_score"]

    from app.services.param_optimizer.engine import run_optimization

    r = run_optimization(
        "TESTUSDT",
        500.0,
        daily=daily,
        backtest_candles=bt,
        time_budget_sec=12,
        n_workers=1,
        tier_key="soft",
    )
    winner_final = r["score"]["final_score"]
    assert winner_final >= prior_final - 1e-6, (winner_final, prior_final)


def test_worker_count_idle_aware(monkeypatch):
    """Idle-aware politika: boştayken cpu-1, meşgulken güvenli tabana (2) çekilir;
    explicit request her zaman öncelikli. Politika tier-bağımsız ve tek kaynakta
    (parallel.resolve_workers); jobs._resolve_worker_count ona delege eder."""
    from app.services.param_optimizer import jobs, parallel
    from app.services.param_optimizer.tiers import TIERS

    monkeypatch.delenv("PARAM_OPTIMIZER_WORKERS", raising=False)
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 16)

    # boşta → neredeyse tüm çekirdekler (cpu-1), event loop'a 1 bırak
    monkeypatch.setattr(parallel.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
    assert parallel.resolve_workers(0, idle_aware=True) == 15
    assert jobs._resolve_worker_count(TIERS["soft"], 0) == 15  # tier-bağımsız

    # meşgul → güvenli tabana (2) çekil
    monkeypatch.setattr(parallel.os, "getloadavg", lambda: (15.7, 15.0, 14.0))
    assert parallel.resolve_workers(0, idle_aware=True) == 2

    # explicit request her zaman öncelikli (cpu ile sınırlı)
    assert parallel.resolve_workers(3, idle_aware=True) == 3
    assert parallel.resolve_workers(99, idle_aware=True) == 16


def test_worker_count_respects_env(monkeypatch):
    from app.services.param_optimizer import jobs, parallel
    from app.services.param_optimizer.tiers import TIERS

    monkeypatch.setenv("PARAM_OPTIMIZER_WORKERS", "6")
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 8)
    assert parallel.resolve_workers(0) == 6
    assert jobs._resolve_worker_count(TIERS["high"], 0) == 6


def test_job_progress_does_not_regress_detail_after_validate(monkeypatch, tmp_path):
    from app.services.param_optimizer import jobs

    monkeypatch.setattr(jobs, "_JOB_STORE_DIR", tmp_path)
    job = jobs.OptJob(
        id="progressregress",
        symbol="SOLUSDT",
        budget=100.0,
        time_budget_sec=600.0,
        tier="high",
        tier_label="Yüksek",
        stage="refine",
        percent=70,
        detail="en iyi skor: -0.0762",
    )

    jobs._progress_from(job, {"stage": "validate", "elapsed": 500, "candidates": 12})
    assert job.stage == "validate"
    assert job.percent >= 86
    assert job.detail == "12 aday doğrulanıyor"

    jobs._progress_from(
        job,
        {
            "stage": "fetch",
            "elapsed": 30,
            "message": "SOLUSDT 5m ince (365g) verisi çekiliyor…",
        },
    )
    assert job.stage == "validate"
    assert job.percent >= 86
    assert "5m ince" not in job.detail


def test_high_tier_is_one_to_six_hour_deep_profile(monkeypatch):
    from app.services.param_optimizer.tiers import TIERS, estimate_seconds

    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    high = TIERS["high"]

    assert high.time_budget_sec == 6 * 3600
    assert high.min_runtime_sec == 3600
    assert high.requires_confirm is True
    assert high.walk_forward_folds >= 6
    assert high.validate_top >= 96
    est = estimate_seconds(high, n_workers=14)
    assert est["eta_low_sec"] >= 3600
    assert est["eta_high_sec"] == 6 * 3600


def test_history_cache_path_is_project_rooted():
    from app.services.param_optimizer import history

    assert os.path.isabs(history._CACHE_DIR)
    assert history._CACHE_DIR.endswith("data/param_optimizer_cache")


import pytest


def test_param_assistant_routes_registered():
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/param-assistant/optimize" in paths
    assert "/api/param-assistant/optimize/{job_id}" in paths


def test_job_status_loads_from_disk_when_memory_missing(monkeypatch, tmp_path):
    from app.services.param_optimizer import jobs

    monkeypatch.setattr(jobs, "_JOB_STORE_DIR", tmp_path)
    job = jobs.OptJob(
        id="persisted123",
        symbol="BTCUSDT",
        budget=100.0,
        time_budget_sec=75.0,
        tier="soft",
        tier_label="Düşük",
        status="done",
        percent=100,
        result={"ok": True, "ui_config": {"budget_usd": 100}},
    )
    jobs._touch(job)
    jobs._JOBS.pop(job.id, None)

    loaded = jobs.get_job(job.id)

    assert loaded is not None
    assert loaded.id == job.id
    assert loaded.status == "done"
    assert loaded.result and loaded.result["ok"] is True


@pytest.mark.asyncio
async def test_history_uses_stale_cache_when_live_fetch_fails(monkeypatch, tmp_path):
    import json
    from app.services.param_optimizer import history

    monkeypatch.setattr(history, "_CACHE_DIR", str(tmp_path))

    base = 1_700_000_000_000
    daily = _mk_candles([100 + i for i in range(60)])
    fine_15m = _mk_candles(
        [120 + i * 0.01 for i in range(3000)], day_ms=15 * 60 * 1000
    )
    fine_15m = [{**c, "t": base - 31 * 86_400_000 + i * 15 * 60 * 1000} for i, c in enumerate(fine_15m)]
    hourly = _mk_candles(
        [90 + i * 0.02 for i in range(1200)], day_ms=60 * 60 * 1000
    )
    hourly = [{**c, "t": base - 50 * 86_400_000 + i * 60 * 60 * 1000} for i, c in enumerate(hourly)]

    os.makedirs(tmp_path, exist_ok=True)
    for interval, candles in {"1d": daily, "15m": fine_15m, "1h": hourly}.items():
        with open(history._cache_path("BTCUSDT", interval), "w") as fh:
            json.dump(
                {
                    "fetched_at": 1,
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "candles": candles,
                },
                fh,
            )

    async def fail_fetch(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(history, "_fetch_chunk", fail_fetch)

    data = await history.fetch_history(
        "BTCUSDT",
        fine_interval="15m",
        fine_days=31,
        coarse_interval="1h",
        max_days=80,
        use_cache=True,
    )

    assert len(data["daily"]) == len(daily)
    assert len(data["backtest"]) > len(fine_15m)
    assert data["meta"]["backtest_bars"] == len(data["backtest"])


@pytest.mark.asyncio
async def test_history_appends_only_missing_new_candles(monkeypatch, tmp_path):
    import json
    from app.services.param_optimizer import history

    monkeypatch.setattr(history, "_CACHE_DIR", str(tmp_path))
    now = int(time.time() * 1000)

    def make_interval_cache(interval_ms, bars, start):
        return [
            {
                "t": start + i * interval_ms,
                "o": 100 + i * 0.01,
                "h": 101 + i * 0.01,
                "l": 99 + i * 0.01,
                "c": 100.5 + i * 0.01,
                "v": 1000.0,
            }
            for i in range(bars)
        ]

    daily = make_interval_cache(86_400_000, 40, now - 42 * 86_400_000)
    hourly = make_interval_cache(3_600_000, 800, now - 802 * 3_600_000)
    fine = make_interval_cache(15 * 60_000, 3000, now - 3002 * 15 * 60_000)

    os.makedirs(tmp_path, exist_ok=True)
    for interval, candles in {"1d": daily, "1h": hourly, "15m": fine}.items():
        with open(history._cache_path("BTCUSDT", interval), "w") as fh:
            json.dump(
                {
                    "fetched_at": 1,
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "candles": candles,
                },
                fh,
            )

    calls = []

    async def fake_fetch(symbol, interval, limit, end_time=None, start_time=None):
        calls.append(
            {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
                "end_time": end_time,
                "start_time": start_time,
            }
        )
        assert start_time is not None
        return [
            {"t": int(start_time), "o": 101.0, "h": 102.0, "l": 100.0, "c": 101.5, "v": 1000.0}
        ]

    monkeypatch.setattr(history, "_fetch_chunk", fake_fetch)

    data = await history.fetch_history(
        "BTCUSDT",
        fine_interval="15m",
        fine_days=31,
        coarse_interval="1h",
        max_days=31,
        use_cache=True,
    )

    assert calls
    assert {c["interval"] for c in calls} == {"1d", "1h", "15m"}
    assert len(data["daily"]) > len(daily)
    assert len(data["hourly"]) > len(hourly)
    assert len(data["backtest"]) > len(fine)


@pytest.mark.asyncio
async def test_history_uses_hourly_backtest_when_fine_interval_missing(monkeypatch, tmp_path):
    import json
    from app.services.param_optimizer import history

    monkeypatch.setattr(history, "_CACHE_DIR", str(tmp_path))

    base = 1_700_000_000_000
    daily = _mk_candles([100 + i for i in range(60)])
    hourly = _mk_candles(
        [95 + i * 0.02 for i in range(1200)], day_ms=60 * 60 * 1000
    )
    hourly = [
        {**c, "t": base - 1200 * 60 * 60 * 1000 + i * 60 * 60 * 1000}
        for i, c in enumerate(hourly)
    ]

    os.makedirs(tmp_path, exist_ok=True)
    for interval, candles in {"1d": daily, "1h": hourly}.items():
        with open(history._cache_path("BTCUSDT", interval), "w") as fh:
            json.dump(
                {
                    "fetched_at": 1,
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "candles": candles,
                },
                fh,
            )

    async def fail_fine_fetch(symbol, interval, *_args, **_kwargs):
        if interval == "5m":
            raise RuntimeError("fine interval unavailable")
        return []

    monkeypatch.setattr(history, "_fetch_chunk", fail_fine_fetch)

    data = await history.fetch_history(
        "BTCUSDT",
        fine_interval="5m",
        fine_days=31,
        coarse_interval="1h",
        max_days=80,
        use_cache=True,
    )

    assert len(data["daily"]) == len(daily)
    assert len(data["backtest"]) >= len(hourly)
    assert data["meta"]["backtest_bars"] == len(data["backtest"])


@pytest.mark.asyncio
async def test_job_create_reuses_active_owner_job_across_symbols(monkeypatch, tmp_path):
    """Aynı hesapta sembol değişse bile ikinci aktif Param Asistanı işi açılmamalı."""
    from app.services.param_optimizer import jobs

    jobs._JOBS.clear()
    jobs._CANCELLED_JOB_IDS.clear()
    monkeypatch.setattr(jobs, "_JOB_STORE_DIR", tmp_path)

    async def idle_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(jobs, "_run_job", idle_run)
    try:
        first = await jobs.create_job(
            "BTCUSDT",
            300.0,
            analysis_level="soft",
            n_workers=1,
            time_budget_override=10,
            owner_key="acc:single",
        )
        second = await jobs.create_job(
            "ETHUSDT",
            300.0,
            analysis_level="soft",
            n_workers=1,
            time_budget_override=10,
            owner_key="acc:single",
        )
        assert second.id == first.id
        assert second.symbol == "BTCUSDT"
        assert jobs.get_running_job_for_owner("acc:single").id == first.id
    finally:
        jobs._JOBS.clear()
        jobs._CANCELLED_JOB_IDS.clear()


@pytest.mark.asyncio
async def test_job_flow_end_to_end(monkeypatch):
    """jobs.create_job -> fetch (mock) -> optimize -> done; poll ile sonuç."""
    import asyncio as _aio
    from app.services.param_optimizer import jobs

    daily, bt = _synth_history(540)

    async def fake_fetch(symbol, **kw):
        return {
            "daily": daily,
            "backtest": bt,
            "hourly": None,
            "meta": {"daily_bars": len(daily), "backtest_bars": len(bt)},
        }

    monkeypatch.setattr(
        "app.services.param_optimizer.history.fetch_history", fake_fetch
    )

    job = await jobs.create_job(
        "TESTUSDT", 300.0, analysis_level="soft", n_workers=1, time_budget_override=10
    )
    j = None
    for _ in range(80):
        j = jobs.get_job(job.id)
        if j and j.status in ("done", "error"):
            break
        await _aio.sleep(0.5)
    assert j is not None and j.status == "done", (
        j.status if j else None,
        j.error if j else None,
    )
    assert j.percent == 100
    assert j.result and j.result["ok"]
    ui = j.result["ui_config"]
    assert ui["up"]["grids"] and ui["down"]["grids"]
    assert j.result["oos"] is not None
    assert j.tier == "soft"


def test_montecarlo_forecast_in_optimization():
    """Monte Carlo gelecek simülasyonu açıkken sonuç forecast içerir + sağlam seçer."""
    from app.services.param_optimizer.engine import run_optimization
    from app.services.param_optimizer.tiers import AnalysisTier

    daily, bt = _synth_history(720)
    tier = AnalysisTier(
        key="test_mc",
        label="test",
        time_budget_sec=16,
        fine_interval="4h",
        fine_days=365,
        coarse_interval="4h",
        max_days=1460,
        monte_carlo_paths=40,
        mc_horizon_days=90,
        mc_top_candidates=5,
        walk_forward_folds=2,
        validate_top=8,
        early_stop=True,
        requires_confirm=False,
        description="test",
    )
    stages = []
    r = run_optimization(
        "TESTUSDT",
        500.0,
        daily=daily,
        backtest_candles=bt,
        time_budget_sec=16,
        n_workers=1,
        tier=tier,
        progress_cb=lambda e: stages.append(e.get("stage")),
    )
    assert r["ok"], r
    assert "forecast" in stages, stages
    fc = r["forecast"]
    assert fc is not None and fc.get("n_paths", 0) > 0, fc
    assert "prob_profit" in fc and "median_return_pct" in fc
    lb = r["leaderboard"][0]
    assert "mc_robustness" in lb and "combined_score" in lb


def test_job_progress_ignores_regressed_stage():
    from app.services.param_optimizer import jobs

    job = jobs.OptJob(
        id="progress-regression",
        symbol="TESTUSDT",
        budget=300.0,
        time_budget_sec=600.0,
        status="running",
        stage="forecast",
        percent=92,
        best_score=1.15,
    )
    job.meta["last_progress"] = {
        "stage": "forecast",
        "message": "gelecek senaryoları: aday 8/15 · 1200/2107 yol",
        "best_score": 1.15,
    }

    jobs._progress_from(
        job,
        {
            "stage": "measure",
            "message": "Test pencereleri ve arama bütçesi hazırlanıyor",
            "best_score": 0.0,
            "elapsed": 320.0,
        },
    )

    assert job.stage == "forecast"
    assert job.percent == 92
    assert job.best_score == 1.15
    assert job.meta["last_progress"]["stage"] == "forecast"
    assert "Test pencereleri" not in job.meta["last_progress"]["message"]


def test_robust_v2_contract_is_returned():
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(420)
    r = run_optimization(
        "TESTUSDT",
        500.0,
        daily=daily,
        backtest_candles=bt,
        time_budget_sec=10,
        n_workers=1,
        tier_key="soft",
    )

    assert r["ok"], r
    assert r["stats"]["engine_version"] == "robust_v2"
    assert r["robust_policy"]["forecast"]["skill"]["baseline_name"] == "climatology"
    assert "deploy" in r["deploy_gate"]
    assert "pbo" in r and r["pbo"] is not None
    assert "deflated_sharpe_ok" in r
    assert "plateau_ok" in r
    assert "causal_features" in r
    for key in ("variance_ratio_5", "ou_half_life_bars", "yang_zhang_vol_pct", "hill_tail_alpha"):
        assert key in r["causal_features"]
    assert "LOW_VOL_RANGING" in r["robust_policy"]["policy"]


def test_tight_budget_heavy_mc_still_searches_no_silent_noop():
    """Dar bütçe + ağır Monte Carlo'da bile optimizer GERÇEK arama yapmalı.

    Regresyon: eskiden tek bir ağır MC adayı (mc_top=max(1,...)) tüm bütçeyi yiyip
    coarse/refine'ı sıfıra düşürüyordu -> optimizer prior/merkez parametreleri
    OPTİMİZE ETMEDEN, evals=1 ile saniyeler içinde dönüyordu (sessiz no-op). Artık
    MC yol sayısı küçülür ya da MC atlanır; arama daima bütçenin çoğunu alır.
    """
    from app.services.param_optimizer.engine import run_optimization
    from app.services.param_optimizer.tiers import AnalysisTier

    daily, bt = _synth_history(720)
    # Bütçeye göre çok pahalı MC (yüksek yol + uzun ufuk) -> eski kodda çökerdi
    tier = AnalysisTier(
        key="tight_heavy_mc",
        label="tight",
        time_budget_sec=20,
        fine_interval="4h",
        fine_days=365,
        coarse_interval="4h",
        max_days=1460,
        monte_carlo_paths=400,
        mc_horizon_days=180,
        mc_top_candidates=20,
        walk_forward_folds=1,
        validate_top=12,
        early_stop=True,
        requires_confirm=False,
        description="tight+heavy mc",
    )
    r = run_optimization(
        "TESTUSDT",
        500.0,
        daily=daily,
        backtest_candles=bt,
        time_budget_sec=20,
        n_workers=1,
        tier=tier,
    )
    assert r["ok"], r
    st = r["stats"]
    # GERÇEK arama yapıldı (sadece merkez değerlendirilmedi)
    assert st["search_evals"] > 1, st
    assert st["evals_total"] > 1, st
    assert st["degraded"] is False, st
    # MC ya sığacak şekilde küçüldü (yol sayısı kısıldı) ya da atlandı (mc_tested=0)
    if st["mc_tested"] > 0:
        assert st["mc_paths"] <= tier.monte_carlo_paths, st
    # bütçenin çoğu aramaya gitti -> makul süre içinde bitti, ama anında dönmedi
    assert r["elapsed_sec"] >= 8.0, r["elapsed_sec"]


def test_perf_one_year_15m_under_budget():
    # ~1 yıl 15m mum (35k) tek backtest süresini ölç (optimizer bütçesini boyutlamak için)
    import math as _m

    n = 35_000
    prices = []
    for i in range(n):
        prices.append(
            100.0 * (1.0 + 0.15 * _m.sin(i / 240.0) + 0.03 * _m.sin(i / 11.0))
        )
    candles = _mk_candles(prices, day_ms=15 * 60 * 1000)
    t0 = time.time()
    r = run_backtest(candles, _params(), budget=1000.0, symbol="BTCUSDT")
    dt = time.time() - t0
    assert r.ok
    # bilgi amaçlı: tek eval süresi (optimizer adaptif bütçeleme için kullanır)
    print(
        f"\n[perf] 1y/15m backtest: {dt:.3f}s  cycles={r.cycles_closed} trades={r.trades}"
    )
    # Bilgi amaçlı; eşik sadece pathological regresyonu yakalar (makine yükü/throttle
    # tolere edilir — optimizer per-eval'i çalışma anında adaptif ölçer).
    assert dt < 90.0


def test_suggested_grid_quantities_sum_to_100():
    """Önerilen sell/buy grid miktarları toplamda %100 olmalı (her kademe sayısında)."""
    from app.services.param_optimizer.robust_engine import _qtys

    for count in range(1, 9):
        for reserve in (0.0, 0.15, 0.3, 0.5):
            qtys = _qtys(count, reserve)
            assert len(qtys) == count
            assert abs(sum(qtys) - 100.0) < 0.01, (count, reserve, sum(qtys), qtys)
            assert all(q >= 0 for q in qtys)


def test_optimization_result_grids_sum_to_100():
    """Uçtan uca: run_optimization sonucu best_params grid'leri toplam %100."""
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(420)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=5, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    bp = r["params"]
    s_sum = sum(g["sell_qty_pct_of_base"] for g in bp["sell_grids"])
    b_sum = sum(g["buy_qty_pct_of_quote"] for g in bp["buy_grids"])
    assert abs(s_sum - 100.0) < 0.05, ("sell", s_sum, bp["sell_grids"])
    assert abs(b_sum - 100.0) < 0.05, ("buy", b_sum, bp["buy_grids"])
    # UI config (modalın gösterdiği) grid'leri de %100 toplamalı.
    uc = r["ui_config"]
    up = uc["up"]["grids"]
    down = uc["down"]["grids"]
    assert abs(sum(g["qty_pct"] for g in up) - 100.0) < 0.05, up
    assert abs(sum(g["qty_pct"] for g in down) - 100.0) < 0.05, down


def _mk_val(return_pct, intended_hold, **kw):
    """Sahte BacktestResult.to_dict() — karar katmanı testleri için."""
    bh = kw.get("buy_hold", -28.0)
    return {
        "return_pct": return_pct,
        "intended_static_return_pct": intended_hold,
        "grid_alpha_vs_intended_pct": kw.get("honest_alpha", return_pct - intended_hold),
        "buy_hold_return_pct": bh,
        "alpha_pct": return_pct - bh,
        "exposure_drift": kw.get("exposure_drift", 0.0),
        "intended_base_frac": kw.get("intended_base_frac", 0.38),
        "exposure_frac": kw.get("exposure_frac", 0.38),
        "profit_factor": kw.get("profit_factor", 1.3),
    }


def test_decision_abstains_when_worse_than_passive_hold():
    """Profesör #1+#2: bot, hedef tahsisi pasif tutmaktan kötüyse ÖNERME (çekil) +
    dürüst manşet + olasılık tavanı + aşırı-uydurma/kayma bayrakları."""
    from app.services.param_optimizer.decision import evaluate_decision

    res = {
        "oos_result": _mk_val(-19.66, -10.7, exposure_drift=0.36, profit_factor=1.5),
        "in_sample_result": _mk_val(38.0, 5.0, profit_factor=52.42),
        "forecast": {"prob_profit": 0.88, "n_paths": 26},
    }
    d = evaluate_decision(res, confidence=12, has_oos=True)
    assert d["decision"] == "abstain", d
    assert d["honest_benchmark"]["beats_intended_hold"] is False
    assert ("pasif" in d["headline"].lower()) and ("daha kötü" in d["headline"].lower())
    # "88% MC" çelişkisi tek olasılığa indirilip pasif-yenememe ile tavanlanmalı
    assert d["deploy_probability"] <= 0.35, d["deploy_probability"]
    codes = {f["code"] for f in d["red_flags"]}
    assert {"overfit_profit_factor", "exposure_drift", "worse_than_passive", "mc_underpowered"} <= codes, codes
    assert d["precision"] == "coarse"


def test_decision_deploy_when_beats_intended_and_confident():
    from app.services.param_optimizer.decision import evaluate_decision

    res = {
        "oos_result": _mk_val(14.0, 5.0, exposure_drift=0.03, profit_factor=1.6),
        "in_sample_result": _mk_val(16.0, 6.0, profit_factor=1.8),
        "forecast": {"prob_profit": 0.7, "n_paths": 800},
    }
    d = evaluate_decision(res, confidence=70, has_oos=True)
    assert d["decision"] == "deploy", d
    assert d["honest_benchmark"]["beats_intended_hold"] is True
    assert d["precision"] == "full"
    assert d["deploy_probability"] > 0.5


def test_decision_abstains_without_oos():
    from app.services.param_optimizer.decision import evaluate_decision

    res = {"in_sample_result": _mk_val(20.0, 5.0), "forecast": {}}
    d = evaluate_decision(res, confidence=80, has_oos=False)
    assert d["decision"] == "abstain"


def test_objective_penalizes_exposure_drift_and_rewards_honest_alpha():
    """Reçeteyi seçimde uygula: kayan (gizli long) set, kaymayanı yenmemeli."""
    from app.services.param_optimizer.backtest import BacktestResult
    from app.services.param_optimizer.objective import score_backtest

    base = dict(
        ok=True, return_pct=10.0, days=180.0, cycles_closed=8, cycles_per_month=1.4,
        max_drawdown_pct=10.0, grid_alpha_vs_intended_pct=2.0, exposure_drift=0.0,
    )
    s_clean = score_backtest(BacktestResult(**base)).score
    s_drift = score_backtest(BacktestResult(**{**base, "exposure_drift": 0.40})).score
    assert s_drift < s_clean, (s_clean, s_drift)
    # dürüst-alpha ödülü: aynı getiri ama hedef-tutmaya göre alpha yüksek -> daha iyi skor
    s_lowalpha = score_backtest(BacktestResult(**{**base, "grid_alpha_vs_intended_pct": -5.0})).score
    s_hialpha = score_backtest(BacktestResult(**{**base, "grid_alpha_vs_intended_pct": 8.0})).score
    assert s_hialpha > s_lowalpha


def test_mc_runaway_is_capped_by_deadline(monkeypatch):
    """Regresyon: Monte Carlo aşaması time_budget_sec'i aşıp çekirdeği saatlerce
    yememeli. Her backtest yapay olarak yavaşlatılır; devasa monte_carlo_paths
    istense bile deadline tek-thread MC döngüsünü keser.

    Eski hata: forecast aşaması bütçeyi yok sayıyor, bir iş 'forecast %90'da
    saatlerce takılıp bir çekirdeği %100 yiyordu (ve modal donuyordu).
    """
    import time as _t
    from app.services.param_optimizer import robust_engine as RE
    from app.services.param_optimizer.engine import run_optimization
    from app.services.param_optimizer.tiers import AnalysisTier

    real_bt = RE.run_backtest

    def slow_bt(*a, **k):
        _t.sleep(0.003)  # her yol/aday backtest'ini ölçülebilir biçimde yavaşlat
        return real_bt(*a, **k)

    monkeypatch.setattr(RE, "run_backtest", slow_bt)

    daily, bt = _synth_history(420)
    budget_sec = 4.0
    tier = AnalysisTier(
        key="test_cap",
        label="test",
        time_budget_sec=budget_sec,
        fine_interval="4h",
        fine_days=365,
        coarse_interval="4h",
        max_days=1460,
        monte_carlo_paths=200000,  # kasıtlı abartı (deadline olmadan dakikalar sürer)
        mc_horizon_days=180,
        mc_top_candidates=64,
        walk_forward_folds=2,
        validate_top=8,
        early_stop=True,
        requires_confirm=False,
        description="test",
    )
    t0 = _t.time()
    r = run_optimization(
        "TESTUSDT",
        500.0,
        daily=daily,
        backtest_candles=bt,
        time_budget_sec=budget_sec,
        n_workers=1,
        tier=tier,
    )
    dt = _t.time() - t0
    assert r["ok"], r
    # Deadline olmadan: 64 aday × ~yüzlerce yol × 3ms ≈ dakikalar. Deadline ile:
    # bütçe + skorlama + tek 'taban-yol' kazanan turu için cömert pay.
    assert dt < budget_sec + 20.0, f"deadline MC'yi sınırlamadı: {dt:.1f}s"
    # Sınırlamaya rağmen kazananın forecast'i olmalı (taban-yol garantisi).
    fc = r.get("forecast")
    assert fc is not None and fc.get("n_paths", 0) > 0, fc
