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
        time_budget_sec=40,
        n_workers=0,
        tier_key="soft",
        progress_cb=lambda e: stages.append(e.get("stage")),
    )
    assert r["ok"], r
    assert r["rationale"]["lines"]
    assert {"features", "measure", "coarse", "validate", "done"}.issubset(set(stages))
    # bütçe ~40s, makul üst sınır içinde bitmeli
    assert r["elapsed_sec"] < 70
    if r.get("result_type") == "no_deployable_candidate":
        return  # bu sentetik seri için canlıya uygun aday bulunamadı (hard-gate'ler doğru çalışıyor)
    p = r["params"]
    assert p["sell_grids"] and p["buy_grids"]
    assert r["ui_config"]["up"]["grids"]
    assert r["oos"] is not None


def test_optimizer_never_worse_than_prior():
    """Optimizer'ın SEÇİM metriği (combined_score), DEPLOY EDİLEBİLİR adaylar
    arasında en iyisi olmalı.

    Aşama 3 öncesi bu test "kazanan asla merkez prior'dan düşük skorlu olamaz"
    derdi — ama artık motor "en iyi skoru" değil "en iyi CANLIYA UYGUN skoru"
    seçiyor (hard gate'lerden geçemeyen bir aday, skoru ne kadar yüksek olursa
    olsun, ASLA kazanamaz). Merkez aday (space.center()) bile reddedilebilir; bu
    yüzden artık kazananı yalnız DEPLOY EDİLEBİLİR havuzdaki rakipleriyle kıyaslıyoruz.
    """
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(720)

    # Yeterli süre + çoklu işçi: deploy edilebilir bir aday bulma şansını artır.
    r = run_optimization(
        "TESTUSDT",
        500.0,
        daily=daily,
        backtest_candles=bt,
        time_budget_sec=60,
        n_workers=0,
        tier_key="soft",
        final_holdout_days=0.0,
    )
    assert r["ok"], r
    if r.get("result_type") == "no_deployable_candidate":
        pytest.skip("bu sentetik seri için canlıya uygun aday bulunamadı (hard-gate'ler doğru çalışıyor)")
    assert (r.get("stats") or {}).get("deployable_candidates_total", 0) >= 1, r["stats"]
    winner_combined = r["score"].get("combined_score", r["score"]["final_score"])
    # Leaderboard sadece top-12'dir (tüm havuz değil); kazanan orada görünmeyebilir.
    # Görünüyorsa kıyasla — kazanan, leaderboard'daki HİÇBİR deploy edilebilir
    # rakipten düşük skorlu olamaz.
    lb = r.get("leaderboard") or []
    deployable_scores = [e["combined_score"] for e in lb if e.get("deployable")]
    if deployable_scores:
        assert winner_combined >= max(deployable_scores) - 1e-6, (winner_combined, deployable_scores)


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
    assert jobs._resolve_worker_count(TIERS["professional_auto"], 0) == 15  # tier-bağımsız

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
    assert jobs._resolve_worker_count(TIERS["professional_auto"], 0) == 6


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


def test_professional_auto_is_thirty_min_to_six_hour_deep_profile(monkeypatch):
    """Tek profesyonel mod: süreye göre değil kanıt kalitesine göre biter — en az
    30 dk, tavan 6 saat. Kullanıcı seçmez (requires_confirm=False); eski "Yüksek"
    tier'in 1-6 saatlik onay-gerektiren profili artık TEK ve VARSAYILAN moddur."""
    from app.services.param_optimizer.tiers import TIERS, estimate_seconds

    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    tier = TIERS["professional_auto"]

    assert tier.time_budget_sec == 6 * 3600
    assert tier.min_runtime_sec == 1800
    assert tier.requires_confirm is False
    assert tier.walk_forward_folds >= 6
    assert tier.walk_forward_oos_folds >= 8
    assert tier.validate_top >= 96
    assert tier.mc_min_paths_for_deploy >= 600
    est = estimate_seconds(tier, n_workers=14)
    assert est["eta_low_sec"] >= 1800
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
async def test_job_create_reuses_only_same_config(monkeypatch, tmp_path):
    """Veri bütünlüğü: AYNI config (sembol+bütçe+seviye) reuse edilir; FARKLI config
    için eski iş ASLA reuse edilmez (bayat/yanlış sonuç engeli)."""
    from app.services.param_optimizer import jobs

    jobs._JOBS.clear()
    jobs._CANCELLED_JOB_IDS.clear()
    monkeypatch.setattr(jobs, "_JOB_STORE_DIR", tmp_path)

    async def idle_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(jobs, "_run_job", idle_run)
    try:
        first = await jobs.create_job(
            "BTCUSDT", 300.0, analysis_level="soft", n_workers=1,
            time_budget_override=10, owner_key="acc:single",
        )
        # aynı config → reuse (aynı job)
        same = await jobs.create_job(
            "BTCUSDT", 300.0, analysis_level="soft", n_workers=1,
            time_budget_override=10, owner_key="acc:single",
        )
        assert same.id == first.id
        assert first.config_hash == same.config_hash
        # farklı sembol → reuse YOK; config-eşli sorgu eskiyi döndürmez
        assert jobs.get_running_job_for_owner(
            "acc:single",
            config_hash=jobs.request_config_hash("ETHUSDT", 300.0, "soft"),
        ) is None
        # farklı bütçe → farklı config_hash
        assert jobs.request_config_hash("BTCUSDT", 300.0, "soft") != \
            jobs.request_config_hash("BTCUSDT", 400.0, "soft")
    finally:
        jobs._JOBS.clear()
        jobs._CANCELLED_JOB_IDS.clear()


def test_route_rejects_reuse_for_different_config(monkeypatch):
    """Route: farklı config'li bir analiz sürerken yeni istek → busy_other_config
    (eski iş mevcut isteğe BAĞLANMAZ); aynı config sürerse reuse edilir."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import param_assistant_routes as par
    from app.api import auth as auth_mod

    class _FakeJob:
        id = "deadbeef"
        symbol = "BTCUSDT"
        budget = 300.0
        tier = "professional_auto"
        tier_label = "Profesyonel Otomatik Analiz"
        cores = 4
        time_budget_sec = 60.0
        eta_total_sec = 120.0
        status = "running"
        config_hash = par.opt_jobs.request_config_hash("BTCUSDT", 300.0, "professional_auto")

    app.dependency_overrides[auth_mod.require_auth] = lambda: {"account_id": "acc:t"}
    monkeypatch.setattr(par.opt_jobs, "get_running_job_for_owner", lambda owner: _FakeJob())
    monkeypatch.setattr(par.opt_jobs, "running_count", lambda: 1)
    try:
        client = TestClient(app)
        # farklı sembol → reuse reddi (analysis_level eski "high" gönderse bile
        # backend tek moda eşler — geriye uyumluluk testi de buna dahil).
        r = client.post("/api/param-assistant/optimize",
                        json={"symbol": "ETHUSDT", "budget": 300.0, "analysis_level": "high"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["busy_other_config"] is True and body["reused"] is False
        assert body["running"]["symbol"] == "BTCUSDT"
        # aynı sembol+bütçe (seviye fark etmez, tek mod) → mevcut işe reuse
        r2 = client.post("/api/param-assistant/optimize",
                         json={"symbol": "BTCUSDT", "budget": 300.0, "analysis_level": "high"})
        b2 = r2.json()
        assert b2.get("reused") is True and b2["job_id"] == "deadbeef"
        assert b2["result_schema_version"] == par.opt_jobs.RESULT_SCHEMA_VERSION
    finally:
        app.dependency_overrides.pop(auth_mod.require_auth, None)


def test_engine_result_carries_schema_and_hashes(monkeypatch):
    """engine sonucu config_hash + market_data_hash + result_schema_version taşır;
    aynı config aynı hash'i üretir (UI bayat-sonuç karşılaştırması bunlara dayanır)."""
    from app.services.param_optimizer.engine import (
        run_optimization, config_hash, market_data_hash, RESULT_SCHEMA_VERSION,
    )
    daily, bt = _synth_history(540)
    r = run_optimization(
        "TESTUSDT", 300.0, daily=daily, backtest_candles=bt,
        time_budget_sec=8, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    assert r["result_schema_version"] == RESULT_SCHEMA_VERSION
    # eski "soft" isteği de tek moda (professional_auto) eşlenir; gerçek hash o tier.key'i kullanır.
    assert r["config_hash"] == config_hash("TESTUSDT", 300.0, "professional_auto")
    assert r["market_data_hash"] == market_data_hash(bt)
    # bütçe değişince config_hash değişir
    assert r["config_hash"] != config_hash("TESTUSDT", 400.0, "professional_auto")


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
    assert j.tier == "professional_auto"  # eski "soft" isteği de tek moda eşlenir
    if j.result.get("result_type") != "no_deployable_candidate":
        ui = j.result["ui_config"]
        assert ui["up"]["grids"] and ui["down"]["grids"]
        assert j.result["oos"] is not None


def test_montecarlo_forecast_in_optimization():
    """Monte Carlo gelecek simülasyonu açıkken sonuç forecast içerir + sağlam seçer."""
    from app.services.param_optimizer.engine import run_optimization
    from app.services.param_optimizer.tiers import AnalysisTier

    daily, bt = _synth_history(720)
    tier = AnalysisTier(
        key="test_mc",
        label="test",
        time_budget_sec=60,
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
        time_budget_sec=60,
        n_workers=0,
        tier=tier,
        progress_cb=lambda e: stages.append(e.get("stage")),
    )
    assert r["ok"], r
    if r.get("result_type") == "no_deployable_candidate":
        pytest.skip("bu sentetik seri için canlıya uygun aday bulunamadı (hard-gate'ler doğru çalışıyor)")
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
        qtys = _qtys(count)
        assert len(qtys) == count
        assert abs(sum(qtys) - 100.0) < 0.01, (count, sum(qtys), qtys)
        assert all(q >= 0 for q in qtys)


def test_p0_7_dead_reserve_field_removed():
    """P0-7: kullanılmayan 'reserve' alanı kaldırıldı, yanıltıcı varyant adı düzeltildi.

    Varyantlar zaten step/base_shift/growth/asymmetric ile GERÇEKTEN farklılaşır;
    sahte 'reserve' boyutu çıkarıldı (qty her zaman %100 dağıtılır)."""
    import dataclasses
    from app.services.param_optimizer.robust_engine import (
        StructuralVariant, _structural_variants, _qtys,
    )

    field_names = {f.name for f in dataclasses.fields(StructuralVariant)}
    assert "reserve" not in field_names, field_names
    names = [v.name for v in _structural_variants()]
    assert "defensive_wide_reserve" not in names, names
    assert "defensive_wide" in names, names
    # _qtys artık tek argümanlı ve toplam %100.
    q = _qtys(4)
    assert abs(sum(q) - 100.0) < 0.01, q


def test_optimization_result_grids_sum_to_100():
    """Uçtan uca: run_optimization sonucu best_params grid'leri toplam %100."""
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(420)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=5, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    # Hard-gate'lerden hiçbir aday geçemezse best_params=None olur; %100 değişmezi
    # bu durumda REDDEDİLEN en iyi adayın parametrelerinde doğrulanır (aynı
    # decode/_normalize_grid_qty_100 yolundan geçtiler — invariant deployability'den
    # bağımsızdır).
    bp = r["params"] or (r.get("rejected_best_candidate") or {}).get("params")
    assert bp is not None, r
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
    # (Asıl regresyon kontrolü budur — deploy edilebilir aday bulunup
    # bulunamamasından bağımsız olarak deadline ASLA aşılmamalı.)
    assert dt < budget_sec + 20.0, f"deadline MC'yi sınırlamadı: {dt:.1f}s"
    if r.get("result_type") == "no_deployable_candidate":
        return  # dar bütçe + yapay yavaşlatma; deploy edilebilir aday bulunamadı (beklenebilir)
    # Sınırlamaya rağmen kazananın forecast'i olmalı (taban-yol garantisi).
    fc = r.get("forecast")
    assert fc is not None and fc.get("n_paths", 0) > 0, fc


def test_p0_1_stats_report_real_worker_count_not_literal_one(monkeypatch):
    """P0-1: stats.workers literal 1 DEĞİL; gerçek resolve_workers değerini yansıtır.

    Gerçek process pool açmadan (serial shim) resolver'ı 3 döndürtüp stats'in buna
    bağlı olduğunu deterministik kanıtlar."""
    from app.services.param_optimizer import robust_engine as RE
    from app.services.param_optimizer.engine import run_optimization

    monkeypatch.setattr(RE.parallel, "resolve_workers", lambda *a, **k: 3)

    def _serial_pmap(fn, items, *, workers, init=None, init_args=(), **kw):
        if init is not None:
            init(*init_args)
        return [fn(it) for it in items]

    monkeypatch.setattr(RE.parallel, "pmap", _serial_pmap)

    daily, bt = _synth_history(720)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=0, tier_key="soft",
    )
    assert r["ok"], r
    st = r["stats"]
    # Gerçek worker sayısı raporlanır (eski kod literal 1 yazıyordu).
    assert st["workers_used"] == 3, st
    assert st["workers"] == 3, st


def test_p0_1_honest_candidate_and_backtest_counts(monkeypatch):
    """P0-1: 'kombinasyon' yanılgısı yerine benzersiz aday + gerçek backtest sayısı."""
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(720)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    st = r["stats"]
    for k in (
        "search_method", "workers_used", "raw_candidates_total",
        "unique_candidates_total", "validated_candidates_total",
        "candidate_backtests_total", "mc_candidates_total",
        "mc_paths_requested", "mc_paths_effective", "mc_backtests_total",
    ):
        assert k in st, (k, st)
    assert st["search_method"] in ("structural_variants", "hybrid_structural_plus_space"), st["search_method"]
    assert st["unique_candidates_total"] >= 1
    assert st["validated_candidates_total"] >= 1
    # Her doğrulanan aday en az 1 backtest → toplam >= doğrulanan aday sayısı.
    assert st["candidate_backtests_total"] >= st["validated_candidates_total"]
    # Tek mod (professional_auto): MC her zaman HEDEFLENİR (eski "soft tier MC
    # kapalı" yok). Ama deploy edilebilir aday yoksa MC hiç ÇALIŞMAZ (madde 5:
    # pasifi yenemeyen sete MC pazarlaması yapılmaz) — sayaçlar bu durumda 0
    # olmalı; çalıştıysa kendi içinde tutarlı (efektif yol/backtest > 0) olmalı.
    assert st["mc_paths_requested"] > 0, st
    if st["mc_candidates_total"] == 0:
        assert st["mc_paths_effective"] == 0 and st["mc_backtests_total"] == 0, st
    else:
        assert st["mc_paths_effective"] > 0 and st["mc_backtests_total"] > 0, st
    # Rationale dürüst: eski yanıltıcı 'farklı kombinasyon' cümlesi yok.
    joined = " ".join(r["rationale"]["lines"])
    assert "farklı kombinasyon" not in joined, joined
    # Deploy edilebilir aday varsa rationale 'yapısal aday' diye dürüst sayar;
    # yoksa (no_deployable_candidate) tamamen farklı, kısa-devre bir mesaj basılır.
    if r.get("result_type") != "no_deployable_candidate":
        assert "yapısal aday" in joined, joined


def test_p0_2_walk_forward_uses_train_only_not_full_series(monkeypatch):
    """P0-2: çapraz-dönem walk-forward TÜM seride değil, yalnız train'de koşmalı
    (oos/validation + final_holdout seçim verisidir, yeniden test edilmemeli)."""
    from app.services.param_optimizer import engine as E

    captured = {}
    orig = E._walk_forward_eval

    def _spy(best_params, candles, *a, **k):
        captured["bars"] = len(candles)
        return orig(best_params, candles, *a, **k)

    monkeypatch.setattr(E, "_walk_forward_eval", _spy)

    daily, bt = _synth_history(720)
    r = E.run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=60, n_workers=0, tier_key="soft",
    )
    assert r["ok"], r
    if r.get("result_type") == "no_deployable_candidate":
        pytest.skip("bu sentetik seri için canlıya uygun aday bulunamadı; walk-forward best_params'sız çalışmaz")
    # walk-forward çağrıldı ve tüm seriden KESİN daha az bar üzerinde.
    assert captured.get("bars", 0) > 0, captured
    assert captured["bars"] < len(bt), (captured["bars"], len(bt))
    assert r.get("walk_forward_scope") == "train_only", r.get("walk_forward_scope")


def test_p0_2_missing_final_holdout_caps_confidence():
    """P0-2: bağımsız final_holdout ayrılamazsa güven 55 ile tavanlanır + uyarı."""
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(720)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
        final_holdout_days=1_000_000,  # holdout ayrılamaz → None
    )
    assert r["ok"], r
    assert r["final_holdout"] is None
    assert r["confidence"] <= 55, r["confidence"]
    assert "final_holdout_missing_confidence_capped" in r["confidence_warnings"], r["confidence_warnings"]


def test_p0_2_independent_final_holdout_is_present():
    """P0-2: yeterli veri varken final_holdout bağımsız backtest sonucu döner."""
    from app.services.param_optimizer.engine import run_optimization

    daily, bt = _synth_history(720)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    assert "final_holdout" in r and "confidence_warnings" in r
    fh = r["final_holdout"]
    # holdout ayrıldıysa: sonuç bir backtest dict'i; negatif/None ise güven tavanlı.
    if fh is None or float(fh.get("return_pct") or 0.0) < 0:
        assert r["confidence"] <= 55, r["confidence"]
        assert r["confidence_warnings"], r["confidence_warnings"]
    else:
        assert "return_pct" in fh


def test_p0_3_space_decode_is_used_in_production(monkeypatch):
    """P0-3: space.decode() artık ÖLÜ KOD değil — üretim arama yolunda çağrılır
    (hybrid: yapısal varyant + space adayları)."""
    from app.services.param_optimizer import robust_engine as RE
    from app.services.param_optimizer.engine import run_optimization

    calls = {"n": 0}
    orig = RE.sp_decode

    def _spy(vec, space, **k):
        calls["n"] += 1
        return orig(vec, space, **k)

    monkeypatch.setattr(RE, "sp_decode", _spy)

    daily, bt = _synth_history(720)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    assert calls["n"] >= 1, "space.decode() üretim yolunda HİÇ çağrılmadı (hâlâ ölü kod)"
    st = r["stats"]
    assert st["search_method"] == "hybrid_structural_plus_space", st["search_method"]
    assert st.get("space_candidates_total", 0) >= 1, st
    assert st.get("structural_candidates_total", 0) >= 1, st
    # Kazanan (ya da hiç deploy edilebilir aday yoksa REDDEDİLEN en iyi) space
    # adayı olsa bile grid qty %100 değişmezi korunur.
    bp = r["params"] or (r.get("rejected_best_candidate") or {}).get("params")
    assert bp is not None, r
    assert abs(sum(g["sell_qty_pct_of_base"] for g in bp["sell_grids"]) - 100.0) < 0.05
    assert abs(sum(g["buy_qty_pct_of_quote"] for g in bp["buy_grids"]) - 100.0) < 0.05


def test_p0_8_abstain_disables_apply_policy(monkeypatch):
    """P0-8: decision=abstain ise ui_config.apply_policy.allowed False olmalı."""
    from app.services.param_optimizer import engine as E
    from app.services.param_optimizer import decision as D

    monkeypatch.setattr(D, "evaluate_decision", lambda *a, **k: {
        "decision": "abstain", "deployable": False,
        "headline": "ÖNERİLMİYOR — çekil.", "honest_benchmark": {},
        "deploy_probability": 0.1, "probability_detail": {}, "red_flags": [],
        "severe_flag_count": 0, "precision": "coarse", "reasons": [], "confidence": 10,
    })
    daily, bt = _synth_history(720)
    r = E.run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    ap = r["ui_config"]["apply_policy"]
    assert ap["allowed"] is False, ap
    assert ap["decision"] == "abstain", ap


def test_p0_8_watch_only_recommends_paper(monkeypatch):
    """P0-8: decision=watch_only → uygulanabilir ama paper-mode önerilir."""
    from app.services.param_optimizer import engine as E
    from app.services.param_optimizer import decision as D

    monkeypatch.setattr(D, "evaluate_decision", lambda *a, **k: {
        "decision": "watch_only", "deployable": False,
        "headline": "İZLEME/KÂĞIT MODU.", "honest_benchmark": {},
        "deploy_probability": 0.4, "probability_detail": {}, "red_flags": [],
        "severe_flag_count": 0, "precision": "coarse", "reasons": [], "confidence": 50,
    })
    daily, bt = _synth_history(720)
    r = E.run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    ap = r["ui_config"]["apply_policy"]
    assert ap["allowed"] is True, ap
    assert ap["recommended_mode"] == "paper", ap


def test_p0_8_deploy_allows_live_apply(monkeypatch):
    """P0-8: decision=deploy → uygulama açık, live önerilir."""
    from app.services.param_optimizer import engine as E
    from app.services.param_optimizer import decision as D

    monkeypatch.setattr(D, "evaluate_decision", lambda *a, **k: {
        "decision": "deploy", "deployable": True,
        "headline": "DAĞITIMA UYGUN.", "honest_benchmark": {},
        "deploy_probability": 0.7, "probability_detail": {}, "red_flags": [],
        "severe_flag_count": 0, "precision": "full", "reasons": [], "confidence": 70,
    })
    # build_final_recommendation'ın sert kapıları (stress_ok/mc_underpowered/
    # final_holdout_present) gerçek MC yol sayısına bağlıdır, o da time_budget_sec
    # içinde KAÇ yol koşabildiğine (duvar-saatine, dolayısıyla CPU yüküne) bağlıdır —
    # RNG sabit olsa da CPU yükü altında daha az yol koşulup "deploy" gerçek pipeline'da
    # "watch_only"ya düşebilir (bkz. test_p0_6_* — kapı mantığı zaten orada sabit
    # girdilerle test ediliyor). Bu test SADECE engine→ui_config kablolamasını
    # doğruladığından nihai kararı da sabitliyoruz.
    monkeypatch.setattr(D, "build_final_recommendation", lambda *a, **k: {
        "decision": "deploy", "deployable": True, "confidence": 70,
        "probability": 0.7, "precision": "full", "headline": "DAĞITIMA UYGUN.",
        "blocking_reasons": [], "warnings": [],
        "evidence": {}, "debug_audit": {},
    })
    daily, bt = _synth_history(720)
    r = E.run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    ap = r["ui_config"]["apply_policy"]
    assert ap["allowed"] is True and ap["recommended_mode"] == "live", ap


def _fr_decision(decision_val, conf=70):
    return {
        "decision": decision_val, "confidence": conf, "headline": "H",
        "deploy_probability": 0.7, "honest_benchmark": {}, "red_flags": [],
    }


def test_p0_6_hard_blocker_demotes_deploy_to_watch_only():
    """P0-6: deploy_gate sert bloklayıcısı (stres) varken deploy → watch_only."""
    from app.services.param_optimizer.decision import build_final_recommendation
    gate = {"deploy": False, "checks": {
        "stress_ok": False, "pbo_ok": True, "deflated_sharpe_ok": True,
        "forecast_skill_positive": True,
    }}
    fr = build_final_recommendation(
        decision=_fr_decision("deploy"), deploy_gate=gate,
        oos={"return_pct": 5.0}, final_holdout_present=True,
        forecast={"prob_profit": 0.7, "n_paths": 500},
    )
    assert fr["decision"] == "watch_only", fr
    assert fr["deployable"] is False
    assert "stress_failed" in fr["blocking_reasons"], fr


def test_p0_6_oos_negative_blocks_deploy():
    """P0-6: OOS<0 sert bloklayıcı → deploy mümkün değil."""
    from app.services.param_optimizer.decision import build_final_recommendation
    gate = {"checks": {"stress_ok": True, "pbo_ok": True, "deflated_sharpe_ok": True}}
    fr = build_final_recommendation(
        decision=_fr_decision("deploy"), deploy_gate=gate,
        oos={"return_pct": -3.0}, final_holdout_present=True,
        forecast={"prob_profit": 0.7, "n_paths": 500},
    )
    assert fr["decision"] == "watch_only"
    assert "oos_not_positive" in fr["blocking_reasons"]


def test_p0_6_clean_deploy_stays_deploy():
    """P0-6: tüm sert kontroller geçerken + güçlü kanıt → deploy korunur."""
    from app.services.param_optimizer.decision import build_final_recommendation
    gate = {"deploy": True, "checks": {
        "stress_ok": True, "pbo_ok": True, "deflated_sharpe_ok": True,
        "forecast_skill_positive": True,
    }}
    fr = build_final_recommendation(
        decision=_fr_decision("deploy", conf=70), deploy_gate=gate,
        oos={"return_pct": 6.0}, final_holdout_present=True,
        # Tek mod (professional_auto) MC tabanı 600'e çıktı (eskiden 300); bu
        # senaryo "yeterli örneklem" göstermeli — tabanın ÜZERİNDE olmalı.
        forecast={"prob_profit": 0.7, "n_paths": 700},
    )
    assert fr["decision"] == "deploy", fr
    assert fr["deployable"] is True
    assert fr["precision"] == "full"
    assert not fr["blocking_reasons"]


def test_p0_6_mc_underpowered_or_missing_holdout_demotes():
    """P0-6: MC zayıf (n<300) ya da bağımsız holdout yoksa deploy → watch_only + uyarı."""
    from app.services.param_optimizer.decision import build_final_recommendation
    gate = {"checks": {"stress_ok": True, "pbo_ok": True, "deflated_sharpe_ok": True}}
    fr1 = build_final_recommendation(
        decision=_fr_decision("deploy"), deploy_gate=gate,
        oos={"return_pct": 5.0}, final_holdout_present=True,
        forecast={"prob_profit": 0.7, "n_paths": 20},  # zayıf MC
    )
    assert fr1["decision"] == "watch_only"
    assert "mc_underpowered" in fr1["warnings"]
    fr2 = build_final_recommendation(
        decision=_fr_decision("deploy"), deploy_gate=gate,
        oos={"return_pct": 5.0}, final_holdout_present=False,  # holdout yok
        forecast={"prob_profit": 0.7, "n_paths": 500},
    )
    assert fr2["decision"] == "watch_only"
    assert "final_holdout_missing" in fr2["warnings"]


def test_p0_6_abstain_stays_abstain():
    """P0-6: decision=abstain her durumda abstain kalır."""
    from app.services.param_optimizer.decision import build_final_recommendation
    fr = build_final_recommendation(
        decision=_fr_decision("abstain"),
        deploy_gate={"checks": {"stress_ok": True, "pbo_ok": True, "deflated_sharpe_ok": True}},
        oos={"return_pct": 5.0}, final_holdout_present=True,
        forecast={"prob_profit": 0.7, "n_paths": 500},
    )
    assert fr["decision"] == "abstain"
    assert fr["deployable"] is False


def test_debug_audit_decision_trace_is_traceable():
    """§8: final_recommendation.debug_audit, kararı satır satır İZLENEBİLİR yapar.

    Negatif OOS + pasif tutmayı yenmeme → trace bu etkileri açıkça gösterir;
    performance_trace formül + gerçek değer ikilisini taşır (sayıyı kanıtlar, metni değil).
    """
    from app.services.param_optimizer.decision import (
        evaluate_decision, build_final_recommendation,
    )
    oos = {
        "return_pct": -4.5, "max_drawdown_pct": 14.2, "cycles_closed": 3,
        "buy_hold_return_pct": 6.0, "alpha_pct": -10.5,
        "intended_base_frac": 0.40, "intended_static_return_pct": 2.4,
        "grid_alpha_vs_intended_pct": -6.9, "exposure_frac": 0.58,
        "exposure_drift": 0.18, "cost_drag_pct": 1.3,
    }
    res = {
        "oos_result": oos,
        "in_sample_result": {"return_pct": 12.0, "profit_factor": 14.0},
        "forecast": {"prob_profit": 0.88, "n_paths": 96},
        "deploy_gate": {"checks": {"oos_positive": False, "pbo_ok": False,
                                   "deflated_sharpe_ok": True, "stress_ok": True}},
    }
    dec = evaluate_decision(res, confidence=22, has_oos=True)
    fr = build_final_recommendation(
        decision=dec, deploy_gate=res["deploy_gate"], forecast=res["forecast"],
        oos=oos, final_holdout_present=False,
    )
    audit = fr["debug_audit"]
    steps = {t["step"]: t for t in audit["decision_trace"]}
    # negatif OOS sert blok olarak iz bırakmalı
    assert steps["oos_return_pct"]["value"] == -4.5
    assert "oos_not_positive" in steps["oos_return_pct"]["effect"]
    # honest_alpha negatif → deploy blocked izi
    assert steps["honest_alpha_pct"]["value"] == -6.9
    assert "deploy_blocked" in steps["honest_alpha_pct"]["effect"]
    # düşük güven → abstain izi
    assert "abstain" in steps["confidence"]["effect"]
    # MC zayıf → watch_only izi
    assert steps["mc_paths"]["value"] == 96
    # son satır nihai kararı taşır
    assert steps["final_decision"]["value"] == fr["decision"] == "abstain"
    # performance_trace: formül + gerçek değer
    pt = audit["performance_trace"]
    assert pt["values"]["honest_alpha_pct"] == -6.9
    assert pt["values"]["return_pct"] == -4.5
    assert "intended_static_return_pct" in pt["formulas"]["honest_alpha_pct"]


def test_p0_6_run_optimization_single_consistent_recommendation():
    """P0-6: çıktıda tek final_recommendation; apply_policy ve deployable onunla TUTARLI."""
    from app.services.param_optimizer.engine import run_optimization
    daily, bt = _synth_history(720)
    r = run_optimization(
        "TESTUSDT", 500.0, daily=daily, backtest_candles=bt,
        time_budget_sec=10, n_workers=1, tier_key="soft",
    )
    assert r["ok"], r
    fr = r["final_recommendation"]
    assert fr["decision"] in ("deploy", "watch_only", "abstain"), fr
    # deployable yalnız final=deploy iken True (çelişki yok).
    assert fr["deployable"] == (fr["decision"] == "deploy")
    # apply_policy NİHAİ kararla birebir tutarlı.
    ap = r["ui_config"]["apply_policy"]
    assert ap["decision"] == fr["decision"]
    assert ap["allowed"] == (fr["decision"] != "abstain")


def test_stage2_fee_floor_enforced_after_step_multipliers():
    """Aşama 2 madde 1: step_mult/asimetri/düşüş çarpanlarından SONRA da step,
    ücret tabanının (FEE_FLOOR_STEP_PCT) altına inmemeli — özellikle step_mult<1
    olan squeeze_tight_reduced ve yukarı-trend sell-side sıkışması (0.95x) için."""
    from app.services.param_optimizer.robust_engine import _params_from_policy, _structural_variants
    from app.services.param_optimizer.space import FEE_FLOOR_STEP_PCT

    state = {"grid_step_pct": 0.65, "base_alloc_pct": 50.0, "trailing_pct": 0.3}
    for variant in _structural_variants():
        for trend_score in (-0.5, 0.0, 0.5):
            params = _params_from_policy(
                state, variant, budget=1000.0, min_notional=10.0, trend_score=trend_score,
            )
            sell0 = params["sell_grids"][0]["sell_grid_pct"]
            buy0 = params["buy_grids"][0]["buy_grid_pct"]
            assert sell0 >= FEE_FLOOR_STEP_PCT - 1e-9, (variant.name, trend_score, sell0)
            assert buy0 >= FEE_FLOOR_STEP_PCT - 1e-9, (variant.name, trend_score, buy0)


def test_stage2_inventory_cap_limits_exposure_during_downtrend():
    """Aşama 2 madde 2: max_base_exposure_frac devredeyken backtest simülasyonu
    BUY fill'lerini sertçe kısmalı — ortalama exposure_frac tavansız çalışmaya göre
    belirgin düşmeli ve tavan en az bir kez devreye girmeli (exposure_cap_hits>0)."""
    wave = []
    px = 100.0
    for _ in range(8):
        wave += [px, px * 0.95, px * 0.962]
        px *= 0.95
    candles = _mk_candles(wave)
    params = _params(
        base_alloc_pct=30.0, quote_alloc_pct=70.0,
        sell_grids=[{"sell_grid_pct": 50.0, "sell_qty_pct_of_base": 100.0}],
        buy_grids=[
            {"buy_grid_pct": 3.0, "buy_qty_pct_of_quote": 40.0},
            {"buy_grid_pct": 6.0, "buy_qty_pct_of_quote": 40.0},
        ],
        buy_trigger_trailing_pct=0.2,
    )
    r_uncapped = run_backtest(candles, params, budget=3000.0, symbol="BTCUSDT")
    assert r_uncapped.ok
    assert r_uncapped.exposure_cap_hits == 0
    # bu senaryoda tavansız çalışma niyetin (0.30) ÜSTÜNE sürükleniyor (gizli long)
    assert r_uncapped.exposure_frac > 0.45, r_uncapped.to_dict()

    r_capped = run_backtest(
        candles, {**params, "max_base_exposure_frac": 0.45}, budget=3000.0, symbol="BTCUSDT",
    )
    assert r_capped.ok
    assert r_capped.exposure_cap_hits > 0
    assert r_capped.exposure_frac < r_uncapped.exposure_frac


def test_stage2_inventory_cap_absent_or_one_is_unchanged_regression():
    """Parametre yoksa veya 1.0 ise (sınırsız), backtest bugünküyle BİREBİR aynı
    sonucu üretmeli — varsayılan davranış geriye dönük kırılmamalı."""
    candles = _mk_candles([100.0] * 60)
    base = _params(base_alloc_pct=50.0, quote_alloc_pct=50.0)
    r_absent = run_backtest(candles, base, budget=1000.0, symbol="BTCUSDT")
    r_explicit_one = run_backtest(
        candles, {**base, "max_base_exposure_frac": 1.0}, budget=1000.0, symbol="BTCUSDT",
    )
    assert r_absent.ok and r_explicit_one.ok
    assert r_absent.exposure_frac == pytest.approx(r_explicit_one.exposure_frac)
    assert r_absent.return_pct == pytest.approx(r_explicit_one.return_pct)
    assert r_absent.exposure_cap_hits == r_explicit_one.exposure_cap_hits == 0


def test_stage2_initial_allocation_is_never_capped():
    """Bootstrap (initial_allocation) tavandan ASLA etkilenmemeli — kasıtlı tek
    seferlik kuruluş, birikim değil. Düz fiyatta tek BUY olayı initial_allocation
    olduğu için, en agresif tavan bile sonucu değiştirmemeli."""
    candles = _mk_candles([100.0] * 60)
    base = _params(base_alloc_pct=50.0, quote_alloc_pct=50.0)
    r_uncapped = run_backtest(candles, base, budget=1000.0, symbol="BTCUSDT")
    r_capped = run_backtest(
        candles, {**base, "max_base_exposure_frac": 0.05}, budget=1000.0, symbol="BTCUSDT",
    )
    assert r_uncapped.ok and r_capped.ok
    assert r_capped.exposure_frac == pytest.approx(r_uncapped.exposure_frac)
    assert r_capped.return_pct == pytest.approx(r_uncapped.return_pct)
    assert r_capped.exposure_cap_hits == 0


def test_stage2_downtrend_throttle_reduces_buys_in_sustained_decline():
    """Aşama 2 madde 4: backtest içi nedensel ayı-bar proxy'si aktifken
    downtrend_buy_throttle, sürdürülen düşüşte BUY fill büyüklüğünü kısmalı —
    ortalama exposure_frac belirgin düşmeli ve throttle en az bir kez devreye girmeli."""
    wave = []
    px = 100.0
    for _ in range(8):
        wave += [px, px * 0.95, px * 0.962]
        px *= 0.95
    candles = _mk_candles(wave)
    params = _params(
        base_alloc_pct=30.0, quote_alloc_pct=70.0,
        sell_grids=[{"sell_grid_pct": 50.0, "sell_qty_pct_of_base": 100.0}],
        buy_grids=[
            {"buy_grid_pct": 3.0, "buy_qty_pct_of_quote": 40.0},
            {"buy_grid_pct": 6.0, "buy_qty_pct_of_quote": 40.0},
        ],
        buy_trigger_trailing_pct=0.2,
    )
    r0 = run_backtest(candles, params, budget=3000.0, symbol="BTCUSDT")
    assert r0.ok
    assert r0.downtrend_throttle_hits == 0

    r1 = run_backtest(
        candles, {**params, "downtrend_buy_throttle": 0.7}, budget=3000.0, symbol="BTCUSDT",
    )
    assert r1.ok
    assert r1.downtrend_throttle_hits > 0
    assert r1.fills_buy == r0.fills_buy  # fill SAYISI değişmez, fill BÜYÜKLÜĞÜ küçülür
    assert r1.exposure_frac < r0.exposure_frac


def test_stage2_downtrend_throttle_inert_outside_bearish_bars():
    """Genel hafif yukarı driftli, küçük dalgalı bir seride (24-bar pencerede hiçbir
    nokta -3% eşiğini aşmaz) throttle parametresi DEVREDE olsa da hiç tetiklenmemeli
    — fill sayısı/exposure tavansız çalışmayla BİREBİR aynı kalmalı."""
    base_px = 100.0
    wave = []
    for _ in range(40):
        base_px *= 1.001
        wave += [base_px, base_px * 1.012, base_px * 1.003, base_px * 0.989, base_px * 1.0]
    candles = _mk_candles(wave)
    params = _params(
        base_alloc_pct=40.0, quote_alloc_pct=60.0,
        sell_grids=[{"sell_grid_pct": 1.0, "sell_qty_pct_of_base": 100.0}],
        buy_grids=[{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 100.0}],
        sell_trigger_trailing_pct=0.15,
        buy_trigger_trailing_pct=0.15,
    )
    r0 = run_backtest(candles, params, budget=2000.0, symbol="BTCUSDT")
    r1 = run_backtest(
        candles, {**params, "downtrend_buy_throttle": 0.7}, budget=2000.0, symbol="BTCUSDT",
    )
    assert r0.ok and r1.ok
    assert r0.fills_buy > 0  # senaryo gerçekten alım üretiyor (testin anlamlı olması için)
    assert r0.downtrend_throttle_hits == 0
    assert r1.downtrend_throttle_hits == 0
    assert r1.fills_buy == r0.fills_buy
    assert r1.exposure_frac == pytest.approx(r0.exposure_frac)


def test_stage2_downtrend_gate_is_causal_no_lookahead():
    """KRİTİK doğruluk testi: bar K'daki al/alma kararı, K'dan SONRA ne olacağına
    asla bağlı olmamalı. Aynı ilk K bar + sonrasında düz devam VEYA çöküş VEYA hiç
    devam etmeme (kırpılmış) — üçünün de bar K'ya kadarki equity_curve'ü BİREBİR
    aynı olmalı; aksi halde sınıflandırıcı gelecek bardan bilgi sızdırıyor demektir."""
    import math

    K = 30
    head = [100.0 * (1 + 0.01 * math.sin(i / 3.0)) for i in range(K)]
    tail_flat = [head[-1]] * 30
    tail_crash = [head[-1] * (0.95 ** i) for i in range(1, 31)]

    candles_flat = _mk_candles(head + tail_flat)
    candles_crash = _mk_candles(head + tail_crash)
    candles_truncated = _mk_candles(head)

    params = _params(
        base_alloc_pct=40.0, quote_alloc_pct=60.0,
        sell_grids=[{"sell_grid_pct": 50.0, "sell_qty_pct_of_base": 100.0}],
        buy_grids=[{"buy_grid_pct": 1.0, "buy_qty_pct_of_quote": 100.0}],
        buy_trigger_trailing_pct=0.2,
        downtrend_buy_throttle=0.7,
    )

    r_flat = run_backtest(candles_flat, params, budget=2000.0, symbol="BTCUSDT", record_equity=True)
    r_crash = run_backtest(candles_crash, params, budget=2000.0, symbol="BTCUSDT", record_equity=True)
    r_trunc = run_backtest(candles_truncated, params, budget=2000.0, symbol="BTCUSDT", record_equity=True)

    assert r_flat.ok and r_crash.ok and r_trunc.ok
    head_flat = r_flat.equity_curve[:K]
    head_crash = r_crash.equity_curve[:K]
    head_trunc = r_trunc.equity_curve[:K]
    assert len(head_flat) == len(head_crash) == len(head_trunc) == K
    assert head_flat == head_crash, "gelecekteki çöküş geçmiş bar kararını değiştirdi (look-ahead bug)"
    assert head_flat == head_trunc, "kırpılmış seri farklı sonuç verdi (look-ahead bug)"


def test_stage2_asymmetric_tilt_proportional_to_variant_strength():
    """Aşama 2 madde 5: yukarı trendde TÜM varyantlar (sadece trend_tilted_asymmetric
    değil) kendi tilt_strength'i kadar orantılı asimetri almalı; daha yüksek
    tilt_strength daha büyük buy/sell ayrışması üretmeli."""
    from app.services.param_optimizer.robust_engine import _params_from_policy, _structural_variants

    state = {"grid_step_pct": 1.0, "base_alloc_pct": 50.0, "trailing_pct": 0.3}
    variants = _structural_variants()
    divergences = {}
    for variant in variants:
        p = _params_from_policy(state, variant, budget=1000.0, min_notional=10.0, trend_score=0.6)
        sell0 = p["sell_grids"][0]["sell_grid_pct"]
        buy0 = p["buy_grids"][0]["buy_grid_pct"]
        base_step = max(0.6, 1.0 * variant.step_mult)
        if variant.tilt_strength > 0:
            assert buy0 > sell0, (variant.name, sell0, buy0)
        else:
            assert buy0 == pytest.approx(sell0), (variant.name, sell0, buy0)
        divergences[variant.name] = (buy0 - sell0) / base_step

    # sıralama tilt_strength ile orantılı olmalı (daha yüksek tilt -> daha büyük ayrışma)
    by_tilt = sorted(variants, key=lambda v: v.tilt_strength)
    divs_in_order = [divergences[v.name] for v in by_tilt]
    assert divs_in_order == sorted(divs_in_order)


def test_stage2_trend_tilted_asymmetric_golden_value_unchanged():
    """trend_tilted_asymmetric (tilt_strength=1.0), herhangi bir trend_score>0'da
    BUGÜNKÜ 0.95/1.15 çarpanlarını bit-bit üretmeli (regresyon yok)."""
    from app.services.param_optimizer.robust_engine import _params_from_policy, _structural_variants

    state = {"grid_step_pct": 1.0, "base_alloc_pct": 50.0, "trailing_pct": 0.3}
    variant = next(v for v in _structural_variants() if v.name == "trend_tilted_asymmetric")
    step = max(0.6, 1.0 * variant.step_mult)
    for trend_score in (0.01, 0.3, 0.7, 1.0):
        p = _params_from_policy(state, variant, budget=1000.0, min_notional=10.0, trend_score=trend_score)
        assert p["sell_grids"][0]["sell_grid_pct"] == pytest.approx(round(step * 0.95, 3))
        assert p["buy_grids"][0]["buy_grid_pct"] == pytest.approx(round(step * 1.15, 3))


def test_stage2_all_variants_symmetric_at_zero_trend_score():
    """trend_score=0'da TÜM varyantlar tam simetrik kalmalı (yeni sürekli formülün
    nötr noktada bugünküyle aynı davranması — regresyon yok)."""
    from app.services.param_optimizer.robust_engine import _params_from_policy, _structural_variants

    state = {"grid_step_pct": 1.0, "base_alloc_pct": 50.0, "trailing_pct": 0.3}
    for variant in _structural_variants():
        p = _params_from_policy(state, variant, budget=1000.0, min_notional=10.0, trend_score=0.0)
        assert p["sell_grids"][0]["sell_grid_pct"] == pytest.approx(p["buy_grids"][0]["buy_grid_pct"])


def test_stage2_downtrend_widening_unscaled_across_variants():
    """Düşüş genişletmesi (trend_score<-0.15 -> buy_step*=1.15) TÜM varyantlarda
    SABİT kalmalı — tilt_strength'e göre ÖLÇEKLENMEMELİ (mevcut düşüş koruması
    zayıflatılmaz; bu kasıtlı bir tasarım kararıdır)."""
    from app.services.param_optimizer.robust_engine import _params_from_policy, _structural_variants

    state = {"grid_step_pct": 1.0, "base_alloc_pct": 50.0, "trailing_pct": 0.3}
    for variant in _structural_variants():
        p = _params_from_policy(state, variant, budget=1000.0, min_notional=10.0, trend_score=-0.5)
        step = max(0.6, 1.0 * variant.step_mult)
        assert p["buy_grids"][0]["buy_grid_pct"] == pytest.approx(round(step * 1.15, 3))
