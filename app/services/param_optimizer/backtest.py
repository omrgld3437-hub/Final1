"""
Sadık backtest motoru
=====================

GERÇEK ``dca_grid_trailing`` strateji kodunu geçmiş mum verisi üzerinde sürer.
Heuristik bir yaklaşım DEĞİL — botun canlıda kullandığı tick fonksiyonunun,
fill muhasebesinin ve cycle reset mantığının birebir aynısını çağırır. Tek fark
canlı altyapı (DB, emir gönderimi, retry/idempotency) yerine ekonomik fill
katmanının taklit edilmesidir.

Mum içi fiyat yolu (sub-tick): her mum (o,h,l,c) için yön bazlı 4 nokta üretilir
    yeşil (c>=o): o -> l -> h -> c
    kırmızı(c<o): o -> h -> l -> c
Bu, trailing tepe/dip takibinin mum içindeki uç hareketleri yakalamasını sağlar.
Çözünürlük arttıkça (ör. son 1 yıl 15m) sadakat artar.

MALİYET MODELİ (dürüstlük notları):
  * Bu strateji TRAILING tetikle çalışır: grid seviyesine değince kurulur, geri
    çekilmede (trail%) dolar. Yani fill'ler piyasa (TAKER) emirleridir — dinlenen
    limit (maker) DEĞİL. Bu yüzden maker/taker ayrımı bu strateji için anlamsızdır;
    tüm fill'lere taker komisyonu + slipaj uygulanır (komisyon tabanı space.py'de
    taker round-trip'e göre kurulur).
  * SPOT cüzdan modeli (base + quote bakiyesi); perp pozisyonu yoktur => FUNDING
    UYGULANMAZ. Funding eklemek spot backtest'te yanlış olur.
  * Slipaj + impact: trailing fill'leri hızlı geri çekilmede daha kötü dolabilir;
    `slippage_bps` temel slipaj, `taker_extra_bps` ise kuyruk/etki payıdır.
  * BİLİNEN SINIR: kısmi/garantisiz limit doldurma kuyruğu modellenmez (trailing
    market mantığı bunu kısmen telafi eder; sub-tick yolu da pesimisttir). Maliyet
    sürtünmesi `cost_drag_pct` ile raporlanır — dar gridlerde getirinin ne kadarını
    yediğini açıkça gösterir.
"""

from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from app.botengine.models import DcaGridTrailingConfig
from app.botengine.strategies.dca_grid_trailing import (
    tick_dca_grid_trailing,
    apply_fill_to_state,
    cycle_reset_after_fill,
)
from app.botengine.cycle_ledger import (
    ensure_cycle_ledger,
    cycle_ledger_add_fill,
    build_cycle_ledger_empty,
    CYCLE_FILL_REASONS,
)

logger = logging.getLogger(__name__)

# Strateji modülü tick başına INFO log basar; backtest'te on milyonlarca tick
# olacağı için yalnız backtest çalışırken bu logger'ları susturuyoruz.
# ÖNEMLİ: global/kalıcı değiştirmiyoruz — aynı süreçte çalışan canlı botların
# logları etkilenmesin (set/restore bracket).
_QUIET_LOGGERS = (
    "app.botengine.strategies.dca_grid_trailing",
    "app.botengine.cycle_ledger",
    "app.botengine.strategies.grid_outage_recovery",
)


@contextmanager
def _quiet_strategy_logs():
    saved = []
    for name in _QUIET_LOGGERS:
        lg = logging.getLogger(name)
        saved.append((lg, lg.level))
        if lg.level < logging.ERROR:
            lg.setLevel(logging.ERROR)
    try:
        yield
    finally:
        for lg, lvl in saved:
            lg.setLevel(lvl)


_CLOSE_REASONS = ("trail_reentry_buy", "trail_profit_sell")


# ---------------------------------------------------------------------------
# Sonuç DTO
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    """Bir parametre setinin geçmiş üzerindeki davranış özeti."""

    final_equity: float = 0.0
    start_equity: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    # buy&hold karşılaştırması (aynı bütçe ilk fiyattan tamamen base'e girseydi)
    buy_hold_return_pct: float = 0.0
    alpha_pct: float = 0.0  # return_pct - buy_hold_return_pct
    static_exposure_return_pct: float = 0.0  # ortalama base maruziyetine eş statik portföy
    grid_alpha_pct: float = 0.0  # return_pct - static_exposure_return_pct
    cash_buffer_alpha_pct: float = 0.0  # static_exposure_return_pct - buy_hold_return_pct
    alpha_cash_share: float = 0.0  # raporlanan alpha içinde nakit tamponu payı
    # MARUZİYET KAYMASI: simetrik grid düşüşte base biriktirip NİYET edilen
    # tahsisin ÜSTÜNE çıkabilir (gizli long). grid_alpha_pct yukarıda GERÇEKLEŞEN
    # (kaymış) maruziyete göre ölçülür ve bu kaymayı örtebilir; aşağıdakiler
    # NİYET edilen tahsise göre ölçer ve kaymanın kendisini açığa çıkarır.
    intended_base_frac: float = 0.0  # config.base_alloc_pct/100 (kurmak istenen)
    exposure_drift: float = 0.0  # exposure_frac - intended_base_frac (>0 => long'a kaydı)
    intended_static_return_pct: float = 0.0  # niyet edilen tahsisin statik getirisi
    grid_alpha_vs_intended_pct: float = 0.0  # return_pct - intended_static_return_pct
    cycles_closed: int = 0
    realized_cycle_pnl: float = 0.0
    trades: int = 0  # grid + cycle-close fill sayısı (init hariç)
    fills_buy: int = 0
    fills_sell: int = 0
    fees_paid: float = 0.0
    slippage_cost: float = 0.0  # toplam slipaj/impact maliyeti (USDT)
    cost_drag_pct: float = 0.0  # (komisyon + slipaj) / bütçe * 100 — getiriden düşen sürtünme
    max_drawdown_pct: float = 0.0
    # ek teşhis
    days: float = 0.0
    cycles_per_month: float = 0.0
    trades_per_month: float = 0.0
    avg_cycle_pnl: float = 0.0
    win_cycles: int = 0
    loss_cycles: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    # BEKLENTİ: win-rate tek başına yanıltıcı (yüksek win-rate + büyük seyrek
    # kayıp = negatif beklenti). payoff başabaş eşiğini AŞMALI.
    avg_win: float = 0.0  # ortalama kazançlı tur PnL (USDT)
    avg_loss: float = 0.0  # ortalama kayıplı tur |PnL| (USDT, pozitif)
    payoff: float = 0.0  # avg_win / avg_loss
    breakeven_payoff: float = 0.0  # (1-p)/p ; payoff bunu aşmazsa beklenti negatif
    expectancy_per_cycle: float = 0.0  # p*avg_win - (1-p)*avg_loss (USDT)
    exposure_frac: float = 0.0  # ortalama base ağırlığı (0..1)
    time_armed_frac: float = 0.0  # grid/trail aktif zaman oranı
    # Aşama 2: envanter tavanı (max_base_exposure_frac) kaç BUY fill'ini kıstı/iptal
    # etti — tavanın gerçekten devreye girdiğini kanıtlamak için teşhis sayacı.
    exposure_cap_hits: int = 0
    # Aşama 2: düşüş-barı throttle'ı (downtrend_buy_throttle) kaç BUY fill'ini kıstı.
    downtrend_throttle_hits: int = 0
    ok: bool = True
    note: str = ""
    cycle_pnls: List[float] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        # ağır alanları dışa verirken kısalt
        d.pop("equity_curve", None)
        d["cycle_pnls"] = [round(x, 4) for x in self.cycle_pnls[:200]]
        for k, v in list(d.items()):
            if isinstance(v, float):
                d[k] = round(v, 6)
        return d


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def _grid_list(grids: Sequence[Dict[str, Any]], side: str) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for g in grids or []:
        if side == "sell":
            trig = g.get("sell_grid_pct", g.get("trigger_pct"))
            qty = g.get("sell_qty_pct_of_base", g.get("qty_pct"))
            out.append(
                {
                    "sell_grid_pct": float(trig or 0.0),
                    "sell_qty_pct_of_base": float(qty or 0.0),
                }
            )
        else:
            trig = g.get("buy_grid_pct", g.get("trigger_pct"))
            qty = g.get("buy_qty_pct_of_quote", g.get("qty_pct"))
            out.append(
                {
                    "buy_grid_pct": float(trig or 0.0),
                    "buy_qty_pct_of_quote": float(qty or 0.0),
                }
            )
    return out


def build_config(
    params: Dict[str, Any], budget: float, symbol: str
) -> DcaGridTrailingConfig:
    """params (asistan/optimizer çıktısı) -> DcaGridTrailingConfig."""
    p = params or {}
    sell_grids = _grid_list(p.get("sell_grids") or [], "sell")
    buy_grids = _grid_list(p.get("buy_grids") or [], "buy")
    fee = float(p.get("fee_rate", 0.001))
    raw = {
        "symbol": symbol,
        "initial_capital_usdt": float(budget),
        "base_alloc_pct": float(p.get("base_alloc_pct", 50.0)),
        "quote_alloc_pct": float(p.get("quote_alloc_pct", 50.0)),
        "fee_rate": fee,
        "buy_fee_rate": float(p.get("buy_fee_rate", fee)),
        "sell_fee_rate": float(p.get("sell_fee_rate", fee)),
        "min_net_profit_rate": float(p.get("min_net_profit_rate", 0.001)),
        "pnl_mode": p.get("pnl_mode", "cycle_only_fee_aware_v1"),
        "sell_grids": sell_grids,
        "buy_grids": buy_grids,
        "sell_trigger_trailing_pct": float(p.get("sell_trigger_trailing_pct", 0.3)),
        "buy_trigger_trailing_pct": float(p.get("buy_trigger_trailing_pct", 0.3)),
        "profit_reentry_drop_pct": float(p.get("profit_reentry_drop_pct", 1.0)),
        "profit_reentry_rise_pct": float(p.get("profit_reentry_rise_pct", 0.3)),
        "profit_exit_rise_pct": float(p.get("profit_exit_rise_pct", 1.0)),
        "profit_exit_drop_pct": float(p.get("profit_exit_drop_pct", 0.3)),
        "basis_mode": p.get("basis_mode", "grid_only"),
        "min_notional_guard": float(p.get("min_notional_guard", 10.0)),
        "max_buy_levels": int(p.get("max_buy_levels", max(1, len(buy_grids)))),
        "available_quote_buffer_pct": float(p.get("available_quote_buffer_pct", 0.005)),
        "initial_fee_buffer_pct": float(p.get("initial_fee_buffer_pct", 0.002)),
        "dynamic_mode": False,
    }
    return DcaGridTrailingConfig(raw)


def _subtick_path(o: float, h: float, l: float, c: float) -> List[float]:
    """Mum içi pesimist fiyat yolu (trailing uç hareketlerini yakalamak için)."""
    if c >= o:
        return [o, l, h, c]
    return [o, h, l, c]


# ---------------------------------------------------------------------------
# Ana backtest
# ---------------------------------------------------------------------------
def run_backtest(
    candles: Sequence[Dict[str, Any]],
    params: Dict[str, Any],
    budget: float,
    symbol: str = "BTCUSDT",
    *,
    fee_rate: float = 0.001,
    slippage_bps: float = 2.0,
    taker_extra_bps: float = 0.0,
    intrabar: bool = True,
    record_equity: bool = False,
) -> BacktestResult:
    """
    candles: artan zaman sıralı [{t,o,h,l,c,v}, ...]
    params : strateji parametreleri (alloc, gridler, trailler, cycle eşikleri)
    budget : USDT bütçe (asistanın değiştirmediği girdi)
    Döner: BacktestResult
    """
    res = BacktestResult()
    if not candles or len(candles) < 5:
        res.ok = False
        res.note = "insufficient_candles"
        return res

    if "fee_rate" not in params:
        params = {**params, "fee_rate": fee_rate}
    config = build_config(params, budget, symbol)
    n = len(config.sell_grids)
    m = len(config.buy_grids)

    state: Dict[str, Any] = {
        "bot_id": 0,
        "mode": "IDLE",
        "cycle_id": 1,
        "initial_allocation_done": False,
        "sell_grid_fired": [False] * n,
        "sell_grid_trigger_price": [None] * n,
        "sell_grid_peak_price": [None] * n,
        "sell_grid_fill_price": [None] * n,
        "buy_grid_fired": [False] * m,
        "buy_grid_trigger_price": [None] * m,
        "buy_grid_trough_price": [None] * m,
        "buy_grid_fill_price": [None] * m,
        "sell_history": [],
        "buy_history": [],
    }

    base_balance = 0.0
    quote_balance = float(budget)
    buy_fee = config.buy_fee_rate
    sell_fee = config.sell_fee_rate
    # Trailing fill'leri taker (piyasa) emirleridir: temel slipaj + impact/kuyruk payı.
    slip = max(0.0, slippage_bps + taker_extra_bps) / 1e4
    slip_cost = 0.0

    peak_equity = float(budget)
    max_dd = 0.0
    cycle_pnls: List[float] = []
    fills_buy = 0
    fills_sell = 0
    fees_paid = 0.0
    trades = 0
    exposure_sum = 0.0
    exposure_n = 0
    armed_ticks = 0
    total_ticks = 0
    exposure_cap_hits = 0
    # Aşama 2 madde 2: envanter tavanı — yoksa/1.0 ise bugünkü (sınırsız) davranış
    # birebir korunur (geriye dönük kırılmaz).
    max_exposure_frac = float(params.get("max_base_exposure_frac") or 1.0)

    # Aşama 2 madde 4: düşüş barı kısıtlaması — backtest'e ÖZEL, salt geçmiş
    # kapanışlardan (bu mumun kendi kapanışı HARİÇ) hesaplanan nedensel bir proxy.
    # _rolling_regime_labels'taki gibi tüm-seri percentile KULLANILMAZ (gelecek
    # sızıntısı olurdu) — sabit eşikli, basit, ispatlanabilir nedensel bir ölçü.
    downtrend_buy_throttle = max(0.0, min(0.95, float(params.get("downtrend_buy_throttle") or 0.0)))
    downtrend_throttle_hits = 0
    _DOWNTREND_LOOKBACK = 24
    _DOWNTREND_RET_THRESHOLD_PCT = -3.0
    close_history: List[float] = []
    bar_is_bearish = False

    first_open = float(candles[0].get("o") or candles[0].get("c") or 0.0)
    last_close = float(candles[-1].get("c") or 0.0)

    def _apply(action: Dict[str, Any], price: float) -> None:
        nonlocal base_balance, quote_balance, fills_buy, fills_sell, fees_paid, trades
        nonlocal slip_cost, exposure_cap_hits, downtrend_throttle_hits
        reason = (action.get("reason") or "").strip()
        side = (action.get("side") or "").upper()

        if side == "BUY":
            fp = price * (1.0 + slip)
            qv = action.get("quote_qty")
            if qv is not None:
                Q = min(float(qv), max(0.0, quote_balance))
                # Bootstrap (initial_allocation) ne throttle'dan ne tavandan etkilenir
                # — kasıtlı tek seferlik kuruluş, birikim değil. Diğer tüm BUY
                # fill'leri (trail_buy_grid, trail_reentry_buy) bu kısıtlara tabidir.
                if reason != "initial_allocation":
                    if bar_is_bearish and downtrend_buy_throttle > 0:
                        Q *= (1.0 - downtrend_buy_throttle)
                        downtrend_throttle_hits += 1
                    if max_exposure_frac < 1.0:
                        equity_now = quote_balance + base_balance * price
                        if equity_now > 0:
                            max_added_value = max(
                                0.0, max_exposure_frac * equity_now - base_balance * price
                            )
                            max_Q = max_added_value * (1.0 + buy_fee)
                            if Q > max_Q:
                                Q = max_Q
                                exposure_cap_hits += 1
                if Q <= 0:
                    return
                q = Q / (fp * (1.0 + buy_fee))
                fee = q * fp * buy_fee
            else:
                q = float(action.get("quantity") or 0.0)
                if q <= 0:
                    return
                fee = q * fp * buy_fee
        else:  # SELL
            fp = price * (1.0 - slip)
            q = float(action.get("quantity") or 0.0)
            if q <= 0:
                return
            q = min(q, max(0.0, base_balance))
            if q <= 0:
                return
            fee = q * fp * sell_fee

        apply_fill_to_state(
            state,
            side,
            q,
            fp,
            fee,
            grid_index=action.get("grid_index"),
            reason=reason,
            execution_price=action.get("execution_price"),
        )
        fees_paid += fee
        # Slipaj/impact maliyeti: fill fiyatı ile mid (tetik) arasındaki fark * miktar.
        slip_cost += abs(fp - price) * q

        if reason == "initial_allocation":
            # execution.py bootstrap'ının birebir karşılığı
            C = float(budget)
            cum_quote = q * fp
            state["initial_allocation_done"] = True
            state["reference_price"] = fp
            state["cycle_id"] = 1
            state["initial_alloc_base_qty"] = round(q, 10)
            state["initial_alloc_price"] = round(fp, 10)
            state["initial_alloc_fee_quote"] = round(fee, 8)
            state["quote_balance"] = round(max(0.0, C - cum_quote - fee), 10)
            state["base_balance"] = round(q, 10)
            state["grid_reference_quote"] = state["quote_balance"]
            equity = round(state["quote_balance"] + q * fp, 2)
            state["cycle_start_equity"] = equity
            qa = config.quote_alloc_pct / 100.0
            ba = config.base_alloc_pct / 100.0
            state["target_budgets"] = {
                "equity_usdt": equity,
                "target_quote_usdt": round(equity * qa, 2),
                "target_base_usdt": round(equity * ba, 2),
            }
            state["cycle_opened_at"] = "1970-01-01T00:00:00+00:00"
            state["cycle_ledger_current"] = build_cycle_ledger_empty(
                1, symbol, started_at="1970-01-01T00:00:00+00:00"
            )
            base_balance = state["base_balance"]
            quote_balance = state["quote_balance"]
            return

        # cycle-kapsamlı fill'leri ledger'a yaz (fee-aware trigger mantığı için şart)
        if reason in CYCLE_FILL_REASONS:
            ledger = ensure_cycle_ledger(state, symbol, int(state.get("cycle_id") or 1))
            cycle_ledger_add_fill(
                ledger,
                ts="1970-01-01T00:00:00+00:00",
                order_id=None,
                client_order_id=action.get("client_order_id"),
                side=side,
                qty=q,
                price=fp,
                fee=fee,
                fee_asset="USDT",
                reason=reason,
                slot_id=action.get("grid_index"),
            )
            state["cycle_ledger_current"] = ledger

        if reason == "trail_sell_grid":
            idx = int(action.get("grid_index") or 0)
            if idx < len(state["sell_grid_fired"]):
                state["sell_grid_fired"][idx] = True
            fills_sell += 1
            trades += 1
        elif reason == "trail_buy_grid":
            idx = int(action.get("grid_index") or 0)
            if idx < len(state["buy_grid_fired"]):
                state["buy_grid_fired"][idx] = True
            fills_buy += 1
            trades += 1
        elif side == "BUY":
            fills_buy += 1
            trades += 1
        else:
            fills_sell += 1
            trades += 1

        base_balance = float(state.get("base_balance") or 0.0)
        quote_balance = float(state.get("quote_balance") or 0.0)

        # cycle kapanışı (execution.py:2526 gate'i)
        if state.get("_cycle_complete") or reason in _CLOSE_REASONS:
            cycle_reset_after_fill(state, fp, n, m, symbol=symbol)
            cp = float(state.get("last_cycle_profit_usdt") or 0.0)
            cycle_pnls.append(cp)
            base_balance = float(state.get("base_balance") or 0.0)
            quote_balance = float(state.get("quote_balance") or 0.0)

    # ---- ana döngü (strateji logları yalnız bu blok boyunca susturulur) ----
    with _quiet_strategy_logs():
        for c in candles:
            o = float(c.get("o") or 0.0)
            h = float(c.get("h") or 0.0)
            low = float(c.get("l") or 0.0)
            cl = float(c.get("c") or 0.0)
            if cl <= 0:
                continue
            # NEDENSELLİK: bu mumun kendi kapanışı (cl) henüz close_history'ye
            # eklenmeden bearish bayrağı hesaplanır — intrabar fill'ler bu mumun
            # SONUCUNU bilemez, sadece ÖNCEKİ tamamlanmış mumları görebilir.
            if len(close_history) >= 2:
                lb = close_history[-_DOWNTREND_LOOKBACK:]
                ref = lb[0]
                bar_is_bearish = ref > 0 and (lb[-1] / ref - 1.0) * 100.0 <= _DOWNTREND_RET_THRESHOLD_PCT
            else:
                bar_is_bearish = False
            path = _subtick_path(o, h, low, cl) if intrabar else [cl]
            for px in path:
                if px <= 0:
                    continue
                total_ticks += 1
                mode_before = state.get("mode")
                actions, _ = tick_dca_grid_trailing(
                    state, config, px, base_balance, quote_balance
                )
                if mode_before and mode_before != "IDLE":
                    armed_ticks += 1
                for a in actions:
                    if a.get("type") == "place":
                        _apply(a, px)

            # mum kapanışında equity & drawdown
            eq = quote_balance + base_balance * cl
            if eq > peak_equity:
                peak_equity = eq
            if peak_equity > 0:
                dd = (peak_equity - eq) / peak_equity * 100.0
                if dd > max_dd:
                    max_dd = dd
            if record_equity:
                res.equity_curve.append(round(eq, 4))
            base_val = base_balance * cl
            if eq > 0:
                exposure_sum += base_val / eq
                exposure_n += 1
            close_history.append(cl)
            if len(close_history) > _DOWNTREND_LOOKBACK:
                close_history.pop(0)

    final_equity = quote_balance + base_balance * last_close
    start_equity = float(budget)
    res.final_equity = final_equity
    res.start_equity = start_equity
    res.net_pnl = final_equity - start_equity
    res.return_pct = (res.net_pnl / start_equity * 100.0) if start_equity > 0 else 0.0
    if first_open > 0:
        res.buy_hold_return_pct = (last_close - first_open) / first_open * 100.0
    res.alpha_pct = res.return_pct - res.buy_hold_return_pct

    res.cycles_closed = len(cycle_pnls)
    res.realized_cycle_pnl = float(sum(cycle_pnls))
    res.cycle_pnls = cycle_pnls
    res.trades = trades
    res.fills_buy = fills_buy
    res.fills_sell = fills_sell
    res.fees_paid = fees_paid
    res.slippage_cost = slip_cost
    res.exposure_cap_hits = exposure_cap_hits
    res.downtrend_throttle_hits = downtrend_throttle_hits
    # Maliyet sürtünmesi: dar gridlerde komisyon+slipaj getirinin önemli kısmını yer.
    res.cost_drag_pct = (
        (fees_paid + slip_cost) / start_equity * 100.0 if start_equity > 0 else 0.0
    )
    res.max_drawdown_pct = max_dd

    t0 = float(candles[0].get("t") or 0.0)
    t1 = float(candles[-1].get("t") or 0.0)
    days = (
        max(1e-9, (t1 - t0) / 1000.0 / 86400.0) if t1 > t0 else max(1.0, len(candles))
    )
    res.days = days
    months = days / 30.4375
    res.cycles_per_month = res.cycles_closed / months if months > 0 else 0.0
    res.trades_per_month = trades / months if months > 0 else 0.0
    if cycle_pnls:
        res.avg_cycle_pnl = res.realized_cycle_pnl / len(cycle_pnls)
        wins = [x for x in cycle_pnls if x > 0]
        losses = [x for x in cycle_pnls if x < 0]
        res.win_cycles = len(wins)
        res.loss_cycles = len(losses)
        res.win_rate = len(wins) / len(cycle_pnls) * 100.0
        gain = sum(wins)
        pain = abs(sum(losses))
        # Zarar yoksa profit factor matematiksel olarak sonsuzdur; math.inf JSON'a
        # serileştirilemez (API 500: "Out of range float values"). Sonlu, anlamlı
        # bir "etkin sonsuz" tavanı kullan.
        res.profit_factor = (
            (gain / pain) if pain > 1e-9 else (999.0 if gain > 0 else 0.0)
        )
        # Beklenti: win-rate'i ort. kazanç/kayıp büyüklüğüyle birlikte oku.
        p = res.win_rate / 100.0
        res.avg_win = (gain / len(wins)) if wins else 0.0
        res.avg_loss = (pain / len(losses)) if losses else 0.0
        res.payoff = (res.avg_win / res.avg_loss) if res.avg_loss > 1e-9 else (
            999.0 if res.avg_win > 0 else 0.0
        )
        res.breakeven_payoff = ((1.0 - p) / p) if p > 1e-9 else float("inf")
        res.expectancy_per_cycle = p * res.avg_win - (1.0 - p) * res.avg_loss
    res.exposure_frac = (exposure_sum / exposure_n) if exposure_n else 0.0
    res.static_exposure_return_pct = res.exposure_frac * res.buy_hold_return_pct
    res.grid_alpha_pct = res.return_pct - res.static_exposure_return_pct
    res.cash_buffer_alpha_pct = (
        res.static_exposure_return_pct - res.buy_hold_return_pct
    )
    res.alpha_cash_share = (
        res.cash_buffer_alpha_pct / res.alpha_pct if abs(res.alpha_pct) > 1e-9 else 0.0
    )
    # MARUZİYET KAYMASI: grid_alpha_pct GERÇEKLEŞEN (kaymış) maruziyete göredir ve
    # kaymayı örtebilir. NİYET edilen tahsise göre de ölç ki "set gizlice long'a
    # kaydı mı?" görünsün. quote getirisi 0 kabul edilir (USDT).
    res.intended_base_frac = max(0.0, min(1.0, config.base_alloc_pct / 100.0))
    res.exposure_drift = res.exposure_frac - res.intended_base_frac
    res.intended_static_return_pct = res.intended_base_frac * res.buy_hold_return_pct
    res.grid_alpha_vs_intended_pct = (
        res.return_pct - res.intended_static_return_pct
    )
    res.time_armed_frac = (armed_ticks / total_ticks) if total_ticks else 0.0
    res.ok = True
    return res
