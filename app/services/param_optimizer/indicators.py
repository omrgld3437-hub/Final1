"""
Geçmiş veri indikatör / feature seti (saf Python).

Optimizasyon başına BİR KEZ çalışır (eval başına değil), bu yüzden numpy
gerektirmez. Çıktı, arama uzayını (space.py) akıllıca tohumlamak ve sonuçları
insan-okur gerekçeyle açıklamak için kullanılır.

Tasarım: birden çok zaman penceresi (30g/90g/180g/365g/tüm) için ayrı ayrı
ölçüp, son 1 yıla daha ağır puan veren bir "recency-weighted" özet üretir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Düşük seviye yardımcılar
# ---------------------------------------------------------------------------
def _closes(c: Sequence[Dict[str, Any]]) -> List[float]:
    return [float(x.get("c") or 0.0) for x in c]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _mean(xs: Sequence[float]) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: Sequence[float]) -> float:
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    mu = sum(xs) / len(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def _percentile(xs: Sequence[float], q: float) -> float:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return 0.0
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _returns(closes: Sequence[float]) -> List[float]:
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100.0)
    return out


def _ema(xs: Sequence[float], period: int) -> List[float]:
    if not xs:
        return []
    k = 2.0 / (period + 1)
    out = [xs[0]]
    for x in xs[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out


# ---------------------------------------------------------------------------
# İndikatörler
# ---------------------------------------------------------------------------
def atr_pct(candles: Sequence[Dict[str, Any]], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        if len(candles) < 3:
            return None
        period = max(2, len(candles) - 1)
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i].get("h") or 0.0)
        l = float(candles[i].get("l") or 0.0)
        pc = float(candles[i - 1].get("c") or 0.0)
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if pc > 0:
            trs.append(tr / pc * 100.0)
    if not trs:
        return None
    return _mean(trs[-period:])


def daily_range_pcts(candles: Sequence[Dict[str, Any]]) -> List[float]:
    out = []
    for x in candles:
        h = float(x.get("h") or 0.0)
        l = float(x.get("l") or 0.0)
        c = float(x.get("c") or 0.0)
        if c > 0 and h >= l > 0:
            out.append((h - l) / c * 100.0)
    return out


def rsi(candles: Sequence[Dict[str, Any]], period: int = 14) -> Optional[float]:
    closes = _closes(candles)
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    ag = _mean(gains[-period:])
    al = _mean(losses[-period:])
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def adx(candles: Sequence[Dict[str, Any]], period: int = 14) -> Optional[float]:
    if len(candles) < period * 2:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        h = float(candles[i].get("h") or 0.0)
        l = float(candles[i].get("l") or 0.0)
        ph = float(candles[i - 1].get("h") or 0.0)
        pl = float(candles[i - 1].get("l") or 0.0)
        pc = float(candles[i - 1].get("c") or 0.0)
        up = h - ph
        dn = pl - l
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = _mean(trs[-period:]) or 1e-9
    pdi = 100.0 * _mean(plus_dm[-period:]) / atr
    mdi = 100.0 * _mean(minus_dm[-period:]) / atr
    denom = pdi + mdi
    if denom <= 0:
        return 0.0
    return 100.0 * abs(pdi - mdi) / denom


def bbw_pct(candles: Sequence[Dict[str, Any]], period: int = 20) -> Optional[float]:
    closes = _closes(candles)
    if len(closes) < period:
        return None
    window = closes[-period:]
    mu = _mean(window)
    sd = _std(window)
    if mu <= 0:
        return None
    return (4.0 * sd) / mu * 100.0  # üst-alt bant genişliği (2σ * 2)


def ema_slope_pct(
    candles: Sequence[Dict[str, Any]], period: int, lookback: int
) -> Optional[float]:
    closes = _closes(candles)
    if len(closes) < period + lookback:
        return None
    e = _ema(closes, period)
    if len(e) <= lookback or e[-1 - lookback] <= 0:
        return None
    return (e[-1] - e[-1 - lookback]) / e[-1 - lookback] * 100.0


def range_efficiency(candles: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Net hareket / toplam yol. Düşük => choppy/mean-reverting (grid dostu)."""
    closes = _closes(candles)
    if len(closes) < 3:
        return None
    net = abs(closes[-1] - closes[0])
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path <= 0:
        return None
    return net / path


def autocorr1(candles: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Günlük getirilerin lag-1 otokorelasyonu. Negatif => mean reversion."""
    r = _returns(_closes(candles))
    if len(r) < 10:
        return None
    a = r[:-1]
    b = r[1:]
    ma, mb = _mean(a), _mean(b)
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(len(a)))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    if da <= 0 or db <= 0:
        return None
    return num / (da * db)


def max_drawdown_pct(candles: Sequence[Dict[str, Any]]) -> float:
    closes = _closes(candles)
    if not closes:
        return 0.0
    peak = closes[0]
    mdd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak > 0:
            dd = (peak - c) / peak * 100.0
            if dd > mdd:
                mdd = dd
    return mdd


def swing_pcts(candles: Sequence[Dict[str, Any]], span: int) -> List[float]:
    """span-mum kayan pencerede (yüksek-düşük)/orta swing genliği %."""
    if len(candles) < span:
        return []
    out = []
    for i in range(len(candles) - span + 1):
        seg = candles[i : i + span]
        hi = max(float(x.get("h") or 0.0) for x in seg)
        lo = min(float(x.get("l") or 0.0) for x in seg if float(x.get("l") or 0.0) > 0)
        mid = (hi + lo) / 2.0
        if mid > 0 and hi >= lo:
            out.append((hi - lo) / mid * 100.0)
    return out


# ---------------------------------------------------------------------------
# Pencere özeti
# ---------------------------------------------------------------------------
def macd_hist_norm(candles: Sequence[Dict[str, Any]]) -> Optional[float]:
    """MACD histogram (close fiyatına normalize, %). Pozitif=yukarı momentum."""
    closes = _closes(candles)
    if len(closes) < 35:
        return None
    e12 = _ema(closes, 12)
    e26 = _ema(closes, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    signal = _ema(macd, 9)
    hist = macd[-1] - signal[-1]
    px = closes[-1] or 1.0
    return hist / px * 100.0


def stochastic_k(
    candles: Sequence[Dict[str, Any]], period: int = 14
) -> Optional[float]:
    """Stochastic %K (0-100). Düşük=aşırı satım, yüksek=aşırı alım."""
    if len(candles) < period:
        return None
    seg = candles[-period:]
    hi = max(float(x.get("h") or 0.0) for x in seg)
    lo = min(float(x.get("l") or 0.0) for x in seg if float(x.get("l") or 0.0) > 0)
    c = float(candles[-1].get("c") or 0.0)
    if hi <= lo:
        return 50.0
    return _clamp((c - lo) / (hi - lo) * 100.0, 0.0, 100.0)


def donchian_width_pct(
    candles: Sequence[Dict[str, Any]], period: int = 20
) -> Optional[float]:
    if len(candles) < period:
        return None
    seg = candles[-period:]
    hi = max(float(x.get("h") or 0.0) for x in seg)
    lo = min(float(x.get("l") or 0.0) for x in seg if float(x.get("l") or 0.0) > 0)
    c = float(candles[-1].get("c") or 0.0)
    if c <= 0 or hi < lo:
        return None
    return (hi - lo) / c * 100.0


def hurst_exponent(
    candles: Sequence[Dict[str, Any]], max_lag: int = 40
) -> Optional[float]:
    """Hurst üssü (lagged-fark std slope). <0.5 mean-reverting (grid dostu), >0.5 trend."""
    closes = _closes(candles)
    if len(closes) < 60:
        return None
    max_lag = min(max_lag, len(closes) // 2)
    lags = list(range(2, max_lag))
    xs, ys = [], []
    for lag in lags:
        diffs = [closes[i + lag] - closes[i] for i in range(len(closes) - lag)]
        sd = _std(diffs)
        if sd > 0:
            xs.append(math.log(lag))
            ys.append(math.log(sd))
    if len(xs) < 4:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den <= 0:
        return None
    return _clamp(num / den, 0.0, 1.0)


def support_resistance_dist(
    candles: Sequence[Dict[str, Any]], lookback: int = 90
) -> Dict[str, Optional[float]]:
    """Son lookback'te destek (min low) ve dirence (max high) uzaklık (%)."""
    seg = list(candles[-lookback:]) if len(candles) > lookback else list(candles)
    if len(seg) < 5:
        return {"support_dist_pct": None, "resistance_dist_pct": None}
    sup = min(float(x.get("l") or 0.0) for x in seg if float(x.get("l") or 0.0) > 0)
    res = max(float(x.get("h") or 0.0) for x in seg)
    c = float(candles[-1].get("c") or 0.0)
    if c <= 0:
        return {"support_dist_pct": None, "resistance_dist_pct": None}
    return {
        "support_dist_pct": (c - sup) / c * 100.0 if sup > 0 else None,
        "resistance_dist_pct": (res - c) / c * 100.0 if res > 0 else None,
    }


def window_metrics(
    daily: Sequence[Dict[str, Any]], days: int, label: str
) -> Dict[str, Any]:
    seg = list(daily[-days:]) if days and len(daily) > days else list(daily)
    closes = _closes(seg)
    rets = _returns(closes)
    ranges = daily_range_pcts(seg)
    cov = _clamp(len(seg) / float(days), 0.0, 1.0) if days else (1.0 if seg else 0.0)
    ret_pct = (
        ((closes[-1] - closes[0]) / closes[0] * 100.0)
        if len(closes) >= 2 and closes[0] > 0
        else None
    )
    return {
        "label": label,
        "bars": len(seg),
        "coverage": cov,
        "return_pct": ret_pct,
        "atr_pct": atr_pct(seg, 14),
        "range_med_pct": _percentile(ranges, 0.5) if ranges else None,
        "range_p70_pct": _percentile(ranges, 0.7) if ranges else None,
        "realized_vol_pct": _std(rets) if rets else None,
        "downside_vol_pct": _std([x for x in rets if x < 0]) if rets else None,
        "max_drawdown_pct": max_drawdown_pct(seg),
        "rsi": rsi(seg, 14),
        "adx": adx(seg, 14),
        "bbw_pct": bbw_pct(seg, 20),
        "ema_slope_pct": ema_slope_pct(
            seg, max(8, min(50, len(seg) // 3 or 8)), max(3, len(seg) // 8 or 3)
        ),
        "efficiency": range_efficiency(seg),
        "autocorr1": autocorr1(seg),
        "swing3_med_pct": _percentile(swing_pcts(seg, 3), 0.5)
        if len(seg) >= 3
        else None,
        "swing7_med_pct": _percentile(swing_pcts(seg, 7), 0.5)
        if len(seg) >= 7
        else None,
    }


# ---------------------------------------------------------------------------
# Recency-weighted özet
# ---------------------------------------------------------------------------
@dataclass
class HistoryFeatures:
    atr_pct: float = 1.0
    swing_pct: float = 2.0  # tipik kısa-vade swing genliği (grid step için ana girdi)
    swing7_pct: float = 4.0
    realized_vol_pct: float = 2.0
    downside_vol_pct: float = 1.5
    daily_range_med_pct: float = 2.0
    daily_range_p70_pct: float = 3.0
    trend_score: float = 0.0  # -1..1
    adx: float = 18.0
    rsi: float = 50.0
    bbw_pct: float = 5.0
    mean_reversion: float = 0.5  # 0..1
    drift_daily_pct: float = 0.0
    max_drawdown_1y_pct: float = 30.0
    max_drawdown_all_pct: float = 50.0
    regime_code: str = "LOW_VOL_RANGING"
    regime_label: str = "yatay / dalgalı"
    grid_suitability: float = 0.5
    regime_decisiveness: float = 0.0
    effective_trend_strength: float = 0.0
    coverage: float = 0.0
    confidence: int = 60
    # genişletilmiş indikatörler (priors + gerekçe)
    hurst: float = 0.5  # <0.5 mean-reverting (grid dostu), >0.5 trend
    macd_hist: float = 0.0  # % (momentum)
    stoch_k: float = 50.0
    donchian_width_pct: float = 0.0
    support_dist_pct: Optional[float] = None
    resistance_dist_pct: Optional[float] = None
    windows: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        for k, v in list(d.items()):
            if isinstance(v, float):
                d[k] = round(v, 4)
        return d


def _wmean(pairs: Sequence[tuple], default: float) -> float:
    num = 0.0
    den = 0.0
    for value, weight in pairs:
        if value is None:
            continue
        num += value * weight
        den += weight
    return (num / den) if den > 0 else default


def _regime_suitability(f: HistoryFeatures) -> Dict[str, float]:
    """Grid uygunluğu: Hurst<0.5 ve düşük ADX grid lehinedir; ADX yön taşımaz."""
    s_hurst = _clamp(0.5 + (0.5 - f.hurst) / 0.20, 0.0, 1.0)
    s_adx = _clamp(1.0 - f.adx / 25.0, 0.0, 1.0)
    s_mr = _clamp(f.mean_reversion, 0.0, 1.0)
    s_osc = 0.5 * (
        _clamp(1.0 - abs(f.rsi - 50.0) / 50.0, 0.0, 1.0)
        + _clamp(1.0 - abs(f.stoch_k - 50.0) / 50.0, 0.0, 1.0)
    )
    weights = (1.0, 1.5, 1.0, 0.5)
    wsum = sum(weights)
    favorable = (
        weights[0] * s_hurst
        + weights[1] * s_adx
        + weights[2] * s_mr
        + weights[3] * s_osc
    ) / wsum
    effective_trend = abs(f.trend_score) * min(f.adx / 25.0, 1.0)
    gsi = _clamp(favorable - 1.2 * effective_trend / wsum, 0.0, 1.0)
    return {
        "gsi": gsi,
        "decisiveness": _clamp(2.0 * abs(gsi - 0.5), 0.0, 1.0),
        "effective_trend": effective_trend,
    }


def compute_features(
    daily: Sequence[Dict[str, Any]],
    hourly: Optional[Sequence[Dict[str, Any]]] = None,
) -> HistoryFeatures:
    """Günlük (zorunlu) + saatlik (opsiyonel) mumlardan recency-weighted feature."""
    f = HistoryFeatures()
    if not daily or len(daily) < 5:
        f.coverage = 0.0
        f.confidence = 40
        return f

    w = {
        "m1": window_metrics(daily, 30, "1 ay"),
        "m3": window_metrics(daily, 90, "3 ay"),
        "m6": window_metrics(daily, 180, "6 ay"),
        "y1": window_metrics(daily, 365, "1 yıl"),
        "all": window_metrics(daily, len(daily), "tüm geçmiş"),
    }
    f.windows = w

    # Recency ağırlıkları: son 1 yıl en etkili (kullanıcı talebi).
    f.atr_pct = _wmean(
        [
            (w["m1"]["atr_pct"], 1.2),
            (w["m3"]["atr_pct"], 1.0),
            (w["m6"]["atr_pct"], 0.8),
            (w["y1"]["atr_pct"], 0.6),
            (atr_pct(hourly, 24) if hourly else None, 0.7),
        ],
        2.0,
    )
    f.swing_pct = _wmean(
        [
            (w["m1"]["swing3_med_pct"], 1.2),
            (w["m3"]["swing3_med_pct"], 1.0),
            (w["m6"]["swing3_med_pct"], 0.7),
            (w["y1"]["swing3_med_pct"], 0.5),
        ],
        2.0,
    )
    f.swing7_pct = _wmean(
        [
            (w["m1"]["swing7_med_pct"], 1.1),
            (w["m3"]["swing7_med_pct"], 1.0),
            (w["m6"]["swing7_med_pct"], 0.7),
            (w["y1"]["swing7_med_pct"], 0.5),
        ],
        4.0,
    )
    f.realized_vol_pct = _wmean(
        [
            (w["m1"]["realized_vol_pct"], 1.2),
            (w["m3"]["realized_vol_pct"], 1.0),
            (w["y1"]["realized_vol_pct"], 0.6),
        ],
        2.0,
    )
    f.downside_vol_pct = _wmean(
        [
            (w["m1"]["downside_vol_pct"], 1.1),
            (w["m3"]["downside_vol_pct"], 0.9),
            (w["y1"]["downside_vol_pct"], 0.5),
        ],
        1.5,
    )
    f.daily_range_med_pct = _wmean(
        [
            (w["m1"]["range_med_pct"], 1.2),
            (w["m3"]["range_med_pct"], 1.0),
            (w["y1"]["range_med_pct"], 0.6),
        ],
        2.0,
    )
    f.daily_range_p70_pct = _wmean(
        [
            (w["m1"]["range_p70_pct"], 1.2),
            (w["m3"]["range_p70_pct"], 1.0),
            (w["y1"]["range_p70_pct"], 0.6),
        ],
        3.0,
    )

    # Trend skoru (-1..1): kısa+orta vade getirisi ve EMA eğimi
    f.trend_score = _clamp(
        _wmean(
            [
                (
                    None
                    if w["m1"]["return_pct"] is None
                    else _clamp(w["m1"]["return_pct"] / 18.0, -1, 1),
                    1.0,
                ),
                (
                    None
                    if w["m3"]["return_pct"] is None
                    else _clamp(w["m3"]["return_pct"] / 32.0, -1, 1),
                    0.85,
                ),
                (
                    None
                    if w["y1"]["return_pct"] is None
                    else _clamp(w["y1"]["return_pct"] / 80.0, -1, 1),
                    0.5,
                ),
                (
                    None
                    if w["m1"]["ema_slope_pct"] is None
                    else _clamp(w["m1"]["ema_slope_pct"] / 4.5, -1, 1),
                    0.8,
                ),
                (
                    None
                    if w["m3"]["ema_slope_pct"] is None
                    else _clamp(w["m3"]["ema_slope_pct"] / 7.5, -1, 1),
                    0.6,
                ),
            ],
            0.0,
        ),
        -1.0,
        1.0,
    )
    f.adx = _wmean(
        [(w["m1"]["adx"], 1.1), (w["m3"]["adx"], 0.9), (w["y1"]["adx"], 0.5)], 18.0
    )
    f.rsi = _wmean([(w["m1"]["rsi"], 1.0), (w["m3"]["rsi"], 0.6)], 50.0)
    f.bbw_pct = _wmean([(w["m1"]["bbw_pct"], 1.0), (w["m3"]["bbw_pct"], 0.7)], 5.0)

    # Mean-reversion skoru: düşük efficiency + negatif autocorr => grid dostu
    eff = _wmean(
        [
            (w["m1"]["efficiency"], 1.1),
            (w["m3"]["efficiency"], 1.0),
            (w["y1"]["efficiency"], 0.6),
        ],
        0.4,
    )
    ac = _wmean([(w["m1"]["autocorr1"], 1.0), (w["m3"]["autocorr1"], 0.8)], 0.0)

    # Genişletilmiş indikatörler (günlük seri üzerinde)
    h = hurst_exponent(daily)
    f.hurst = h if h is not None else 0.5
    mh = macd_hist_norm(daily)
    f.macd_hist = mh if mh is not None else 0.0
    sk = stochastic_k(daily, 14)
    f.stoch_k = sk if sk is not None else 50.0
    dw = donchian_width_pct(daily, 20)
    f.donchian_width_pct = dw if dw is not None else 0.0
    sr = support_resistance_dist(daily, 90)
    f.support_dist_pct = sr["support_dist_pct"]
    f.resistance_dist_pct = sr["resistance_dist_pct"]

    # Mean-reversion skoru: düşük efficiency + negatif autocorr + Hurst<0.5 => grid dostu
    f.mean_reversion = _clamp(
        0.42 * (1.0 - _clamp(eff, 0.0, 1.0))
        + 0.33 * _clamp(0.5 - ac, 0.0, 1.0)
        + 0.25 * _clamp((0.5 - f.hurst) * 2.0 + 0.5, 0.0, 1.0),
        0.0,
        1.0,
    )

    if w["all"]["return_pct"] is not None and w["all"]["bars"] > 1:
        f.drift_daily_pct = w["all"]["return_pct"] / max(1, w["all"]["bars"])
    f.max_drawdown_1y_pct = w["y1"]["max_drawdown_pct"] or 30.0
    f.max_drawdown_all_pct = w["all"]["max_drawdown_pct"] or 50.0

    # Rejim sınıflandırması
    suitability = _regime_suitability(f)
    f.grid_suitability = suitability["gsi"]
    f.regime_decisiveness = suitability["decisiveness"]
    f.effective_trend_strength = suitability["effective_trend"]
    code, label = _classify_regime(f, w)
    f.regime_code = code
    f.regime_label = label

    f.coverage = _wmean(
        [
            (w["m1"]["coverage"], 0.22),
            (w["m3"]["coverage"], 0.24),
            (w["y1"]["coverage"], 0.3),
            (w["all"]["coverage"], 0.24),
        ],
        0.3,
    )
    agreement = _clamp(1.0 - f.effective_trend_strength * 0.55, 0.5, 1.0)
    f.confidence = int(
        _clamp(
            48
            + f.coverage * 30
            + agreement * 14
            + f.mean_reversion * 10
            - (f.max_drawdown_1y_pct / 100.0) * 8,
            45,
            96,
        )
    )
    return f


def _classify_regime(f: HistoryFeatures, w: Dict[str, Any]) -> tuple:
    vol = f.daily_range_med_pct
    if (
        w["m1"]["return_pct"] is not None
        and w["m1"]["return_pct"] <= -18
        and f.max_drawdown_1y_pct >= 40
    ):
        return "DUMP_RISK", "sert düşüş riski"
    if f.adx >= 24 and f.trend_score >= 0.28:
        return "TRENDING_UP", "yukarı trend"
    if f.adx >= 24 and f.trend_score <= -0.28:
        return "TRENDING_DOWN", "aşağı baskı"
    if f.grid_suitability >= 0.60:
        return "LOW_VOL_RANGING", "yatay / dalgalı"
    if (f.bbw_pct is not None and f.bbw_pct <= 2.5) or vol <= 1.2:
        return "SQUEEZE", "sıkışma"
    if vol >= 4.5:
        return "HIGH_VOL_RANGING", "yüksek volatil yatay"
    return "LOW_VOL_RANGING", "yatay / dalgalı"
