"""
Parametre arama uzayı + decoder.

İndikatör temelli feature'lardan, optimizer'ın içinde gezeceği DÜŞÜK BOYUTLU
(13-dim) ama zengin bir arama uzayı türetir. Gridler seviye-seviye değil,
yapısal olarak parametrize edilir:

    base_alloc_pct, sell_step_pct, buy_step_pct, sell_count, buy_count,
    step_growth, sell_trail_pct, buy_trail_pct, reentry_drop_pct,
    reentry_rise_pct, exit_rise_pct, exit_drop_pct, qty_front_load

decode() bu vektörü tam bot params sözlüğüne çevirir; her grid seviyesinin
min-notional (Binance ~10 USDT) altına düşmemesini garanti eder, gerekirse
seviye sayısını otomatik düşürür.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.services.param_optimizer.indicators import HistoryFeatures

# Fee tabanı: tek yön ~%0.1 + slippage; net kâr için round-trip maliyeti anlamlı aşmalı.
FEE_ROUNDTRIP_PCT = 0.2
FEE_FLOOR_STEP_PCT = 0.60  # yaklaşık 2x round-trip maliyet eşiği
LONG_HORIZON_MIN_STEP_PCT = FEE_FLOOR_STEP_PCT
LONG_HORIZON_MAX_DEPTH_PCT = 18.0

# Alış gridi referans fiyattan MUTLAK düşüş yüzdesidir. Spot piyasada fiyat en
# fazla %100 düşer (sıfıra iner); %100+ bir alış tetiği matematiksel olarak
# imkânsız ve asla dolmayacak ölü bir seviyedir. Bu yüzden alış derinliğine
# fiziksel bir tavan koyuyoruz (fiyat referansın en az ~%8'inde kalsın).
MAX_BUY_DEPTH_PCT = 92.0
# Satış gridi yukarı yön; teknik olarak %100+ mümkün ama absürt-derin (asla
# dolmayacak) seviyeleri de elemek için makul bir üst sınır.
MAX_SELL_RISE_PCT = 300.0
# Aşağı baskı/dump rejiminde base oranı tavanı: savunma gerçek anlamda quote
# ağırlıklı olsun (eldeki coin düşüşte zarar üretir).
DOWN_REGIME_MAX_BASE_PCT = 34.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class Dim:
    lo: float
    hi: float
    center: float
    is_int: bool = False

    def clamp(self, v: float) -> float:
        v = _clamp(v, self.lo, self.hi)
        return float(round(v)) if self.is_int else v


@dataclass
class ParamSpace:
    dims: Dict[str, Dim]
    budget: float
    min_notional: float
    symbol: str

    def names(self) -> List[str]:
        return list(self.dims.keys())

    def center(self) -> Dict[str, float]:
        return {k: d.center for k, d in self.dims.items()}

    def clamp(self, vec: Dict[str, float]) -> Dict[str, float]:
        return {
            k: self.dims[k].clamp(vec.get(k, self.dims[k].center)) for k in self.dims
        }

    def random(self, rng) -> Dict[str, float]:
        out = {}
        for k, d in self.dims.items():
            v = rng.uniform(d.lo, d.hi)
            out[k] = float(round(v)) if d.is_int else v
        return out


def _max_levels(leg_value: float, min_notional: float, hard_cap: int) -> int:
    """Bir bacakta min-notional'ı bozmadan açılabilecek maksimum seviye."""
    if min_notional <= 0:
        return hard_cap
    return max(1, min(hard_cap, int(leg_value // (min_notional * 1.02))))


def _center_levels(leg_value: float, min_notional: float, max_levels: int, realized_vol_pct: float) -> int:
    """Uzun vadeli merkez aday: bütçe izin veriyorsa tek emir yerine 2-3 kademe."""
    if max_levels <= 1 or leg_value < min_notional * 2.1:
        return 1
    if max_levels >= 4 and leg_value >= min_notional * 4.2 and realized_vol_pct >= 3.5:
        return 4
    if max_levels >= 3 and leg_value >= min_notional * 3.15:
        return 3
    return 2


def build_space(
    features: HistoryFeatures,
    budget: float,
    *,
    min_notional: float = 10.0,
    symbol: str = "BTCUSDT",
) -> ParamSpace:
    f = features
    # Grid adımı ATR'ye çapalanır, komisyon tabanı yalnızca alt sınırdır.
    # Swing'in tamamına yaslanmak range piyasada grid'i fazla genişletir ve tur
    # üretimini öldürür; swing yalnızca sert trend/oynaklıkta kontrollü ek tampon olur.
    trend_gate = min(max(f.adx, 0.0) / 25.0, 1.0) * abs(f.trend_score)
    range_bias = max(0.0, min(1.0, getattr(f, "grid_suitability", 0.5)))
    swing_pad = 0.18 * max(0.0, f.swing_pct - f.atr_pct) * trend_gate
    atr_mult = 0.9 + 0.2 * (1.0 - range_bias)
    move = max(
        LONG_HORIZON_MIN_STEP_PCT,
        _clamp(
            f.atr_pct * atr_mult + swing_pad,
            LONG_HORIZON_MIN_STEP_PCT,
            LONG_HORIZON_MAX_DEPTH_PCT,
        ),
    )

    # Trend, alloc merkezini kaydırır (yukarı trend -> daha çok base; aşağı -> savunmaya)
    alloc_center = _clamp(50.0 + f.trend_score * 12.0, 30.0, 65.0)
    down_regime = f.regime_code in ("DUMP_RISK", "TRENDING_DOWN")
    if down_regime:
        # Aşağı baskıda gerçek savunma: base'i belirgin biçimde quote'un altına çek.
        alloc_center = min(alloc_center, DOWN_REGIME_MAX_BASE_PCT)

    # Bacak başına değer ve min-notional'a göre maksimum seviye
    base_leg = budget * alloc_center / 100.0
    quote_leg = budget * (100.0 - alloc_center) / 100.0
    max_sell = _max_levels(base_leg, min_notional, 6)
    max_buy = _max_levels(quote_leg, min_notional, 8)
    sell_count_center = _center_levels(base_leg, min_notional, max_sell, f.realized_vol_pct)
    buy_count_center = _center_levels(quote_leg, min_notional, max_buy, f.realized_vol_pct)

    # Adım merkezi: uzun vadeli bot için tipik hareketin altında kalma; aksi halde
    # düşük volatil dönemde 0.5-0.8% gridler sürekli gürültüye takılır.
    step_center = _clamp(move, LONG_HORIZON_MIN_STEP_PCT, 12.0)
    # Trail: adımın bir kesri (kârı kilitler, erken çıkmaz)
    trail_center = _clamp(step_center * 0.4 + f.atr_pct * 0.06, 0.2, 3.0)

    # Aşağı baskıda base'in yukarı sürüklenmesine izin verme (savunma korunur);
    # normal rejimde optimizer her iki yöne de geniş gezebilir.
    alloc_lo = max(20.0 if down_regime else 25.0, alloc_center - 18)
    alloc_hi = min(
        DOWN_REGIME_MAX_BASE_PCT + 6.0 if down_regime else 70.0,
        alloc_center + (8.0 if down_regime else 18.0),
    )
    dims: Dict[str, Dim] = {
        "base_alloc_pct": Dim(alloc_lo, alloc_hi, alloc_center),
        "sell_step_pct": Dim(
            max(LONG_HORIZON_MIN_STEP_PCT, step_center * 0.75),
            step_center * 2.8,
            step_center,
        ),
        "buy_step_pct": Dim(
            max(LONG_HORIZON_MIN_STEP_PCT, step_center * 0.75),
            step_center * 3.0,
            step_center,
        ),
        "sell_count": Dim(
            1,
            max(1, max_sell),
            sell_count_center,
            is_int=True,
        ),
        "buy_count": Dim(
            1,
            max(1, max_buy),
            buy_count_center,
            is_int=True,
        ),
        "step_growth": Dim(1.08, 1.65, 1.25 if f.regime_code != "DUMP_RISK" else 1.45),
        "sell_trail_pct": Dim(0.2, max(0.3, step_center * 0.9), trail_center),
        "buy_trail_pct": Dim(0.2, max(0.3, step_center * 0.9), trail_center),
        "reentry_drop_pct": Dim(
            max(0.5, step_center * 0.7),
            step_center * 3.0,
            _clamp(step_center * 1.4, 0.5, 8.0),
        ),
        "reentry_rise_pct": Dim(0.2, max(0.3, trail_center * 2.0), trail_center),
        "exit_rise_pct": Dim(
            max(0.5, step_center * 0.7),
            step_center * 3.2,
            _clamp(step_center * 1.6, 0.5, 9.0),
        ),
        "exit_drop_pct": Dim(0.2, max(0.3, trail_center * 2.2), trail_center),
        "qty_front_load": Dim(0.6, 1.6, 1.0),
    }
    return ParamSpace(
        dims=dims, budget=float(budget), min_notional=float(min_notional), symbol=symbol
    )


def _distribute_qty(
    count: int, leg_value: float, min_notional: float, front_load: float
) -> List[float]:
    """count seviyeye qty% dağıt; her seviye >= min-notional, toplam <= ~%100."""
    count = max(1, int(count))
    if leg_value <= 0:
        return [100.0 / count] * count
    min_pct = min(95.0, (min_notional * 1.02) / leg_value * 100.0)
    # front_load>1 => derin seviyelere daha çok ağırlık (back-load); <1 => öne yükle
    weights = [front_load**i for i in range(count)]
    s = sum(weights) or 1.0
    target_total = 100.0
    pcts = [target_total * w / s for w in weights]
    # min_pct zorlaması
    pcts = [max(min_pct, p) for p in pcts]
    total = sum(pcts)
    if total > 100.0:
        scale = 100.0 / total
        pcts = [p * scale for p in pcts]
        # ölçek sonrası min'in altına düşen olursa o seviye taşımaz -> sayıyı kıs
        if min(pcts) < min_pct - 1e-6:
            return (
                _distribute_qty(count - 1, leg_value, min_notional, front_load)
                if count > 1
                else [min(100.0, min_pct)]
            )
    return [round(p, 3) for p in pcts]


def _grid_triggers(step: float, growth: float, count: int, max_pct: float) -> List[float]:
    """Geometrik genişleyen tetik yüzdeleri; fizik/akıl tavanını aşan (asla
    dolmayacak ölü) seviyeleri keser. En az 1 seviye döner, monoton artar."""
    trigs: List[float] = []
    for i in range(max(1, int(count))):
        t = round(step * (growth ** i), 3) if i > 0 else round(step, 3)
        if t >= max_pct:
            break  # bu seviye ve sonrası tavanı aşıyor -> kes
        trigs.append(t)
    if not trigs:
        trigs = [round(min(step, max_pct - 0.5), 3)]
    return trigs


def decode(
    vec: Dict[str, float],
    space: ParamSpace,
    *,
    features: HistoryFeatures = None,
) -> Dict[str, Any]:
    """Arama vektörü -> tam bot params sözlüğü (min-notional güvenli)."""
    v = space.clamp(vec)
    budget = space.budget
    mn = space.min_notional

    base_alloc = _clamp(v["base_alloc_pct"], 20.0, 70.0)
    quote_alloc = 100.0 - base_alloc
    base_leg = budget * base_alloc / 100.0
    quote_leg = budget * quote_alloc / 100.0

    max_sell = _max_levels(base_leg, mn, 6)
    max_buy = _max_levels(quote_leg, mn, 8)
    sell_count = max(1, min(int(v["sell_count"]), max_sell))
    buy_count = max(1, min(int(v["buy_count"]), max_buy))

    growth = _clamp(v["step_growth"], 1.0, 1.8)
    front = _clamp(v["qty_front_load"], 0.5, 1.7)

    sell_step = max(FEE_FLOOR_STEP_PCT, v["sell_step_pct"])
    buy_step = max(FEE_FLOOR_STEP_PCT, v["buy_step_pct"])

    # Tetik yüzdeleri (referanstan mutlak mesafe); fizik/akıl tavanını aşan ölü
    # seviyeler atılır. ÖNEMLİ: alış %100+ olamaz (fiyat negatife gidemez).
    sell_trigs = _grid_triggers(sell_step, growth, sell_count, MAX_SELL_RISE_PCT)
    buy_trigs = _grid_triggers(buy_step, growth, buy_count, MAX_BUY_DEPTH_PCT)
    sell_count = len(sell_trigs)
    buy_count = len(buy_trigs)

    # qty dağıtımı min-notional için sayıyı daha da kısabilir; tetiklerle hizala.
    sell_qty = _distribute_qty(sell_count, base_leg, mn, front)
    buy_qty = _distribute_qty(buy_count, quote_leg, mn, front)
    sell_count = len(sell_qty)
    buy_count = len(buy_qty)

    sell_grids = [
        {"sell_grid_pct": sell_trigs[i], "sell_qty_pct_of_base": sell_qty[i]}
        for i in range(sell_count)
    ]
    buy_grids = [
        {"buy_grid_pct": buy_trigs[j], "buy_qty_pct_of_quote": buy_qty[j]}
        for j in range(buy_count)
    ]

    params = {
        "base_alloc_pct": round(base_alloc, 2),
        "quote_alloc_pct": round(quote_alloc, 2),
        "sell_grids": sell_grids,
        "buy_grids": buy_grids,
        "sell_trigger_trailing_pct": round(
            _clamp(v["sell_trail_pct"], 0.2, sell_step * 0.95), 3
        ),
        "buy_trigger_trailing_pct": round(
            _clamp(v["buy_trail_pct"], 0.2, buy_step * 0.95), 3
        ),
        "profit_reentry_drop_pct": round(max(0.5, v["reentry_drop_pct"]), 3),
        "profit_reentry_rise_pct": round(_clamp(v["reentry_rise_pct"], 0.2, 4.0), 3),
        "profit_exit_rise_pct": round(max(0.5, v["exit_rise_pct"]), 3),
        "profit_exit_drop_pct": round(_clamp(v["exit_drop_pct"], 0.2, 4.5), 3),
        "max_buy_levels": buy_count,
        "min_net_profit_rate": 0.0015,
        "basis_mode": "grid_only",
        "min_notional_guard": mn,
    }
    return params
