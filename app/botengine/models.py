"""
Bot Engine – config, state, enums.
DCA + two-way Grid + Trailing; maps to UI form fields.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List

from app.botengine.dca_manager import normalize_max_buy_levels_payload


class BotEngineMode(str, Enum):
    IDLE = "IDLE"
    TRAIL_SELL_GRID = "TRAIL_SELL_GRID"
    TRAIL_BUY_GRID = "TRAIL_BUY_GRID"
    TRAIL_REENTRY_BUY = "TRAIL_REENTRY_BUY"
    TRAIL_PROFIT_SELL = "TRAIL_PROFIT_SELL"


def _list_or_default(v: Any, default: List) -> List:
    if v is None:
        return default
    return list(v) if isinstance(v, (list, tuple)) else default


def _float_or(v: Any, default: float) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int_or(v: Any, default: int) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class DcaGridTrailingConfig:
    """Config from UI / API. base_alloc_pct + quote_alloc_pct = 100."""

    def __init__(self, raw: Dict[str, Any]):
        r = raw or {}
        self.symbol = (r.get("symbol") or "").upper().strip() or "BTCUSDT"
        self.initial_capital_usdt = _float_or(
            r.get("initial_capital_usdt")
            or r.get("budget_usd")
            or r.get("bot_budget_usdt"),
            1000.0,
        )
        self.bot_budget_usdt = (
            self.initial_capital_usdt
        )  # alias for virtual wallet / multibot
        self.base_alloc_pct = _float_or(
            r.get("base_alloc_pct") or (r.get("allocation") or {}).get("base_pct"), 50.0
        )
        self.quote_alloc_pct = _float_or(
            r.get("quote_alloc_pct") or (r.get("allocation") or {}).get("quote_pct"),
            50.0,
        )
        self.fee_rate = _float_or(r.get("fee_rate"), 0.001)
        self.buy_fee_rate = _float_or(r.get("buy_fee_rate") or r.get("fee_rate"), 0.001)
        self.sell_fee_rate = _float_or(
            r.get("sell_fee_rate") or r.get("fee_rate"), 0.001
        )
        self.min_net_profit_rate = _float_or(r.get("min_net_profit_rate"), 0.001)
        self.pnl_mode = (r.get("pnl_mode") or "cycle_only_fee_aware_v1").strip().lower()
        if self.pnl_mode not in ("legacy", "cycle_only_fee_aware_v1"):
            self.pnl_mode = "cycle_only_fee_aware_v1"
        # Bot her zaman canlı modda çalışır; paper mod kullanılmaz.
        self.paper_mode = bool(
            r.get("paper_mode")
            if "paper_mode" in r
            else (r.get("mode", "live") == "paper")
        )

        # Sell grids (up)
        up = r.get("up") or {}
        self.sell_grids_count = _int_or(
            r.get("sell_grids_count") or len(up.get("grids") or []), 0
        )
        self.sell_grids: List[Dict[str, Any]] = _list_or_default(
            r.get("sell_grids") or up.get("grids"), []
        )
        self.sell_trigger_trailing_pct = _float_or(
            r.get("sell_trigger_trailing_pct") or up.get("trail_pct"), 0.3
        )

        # Buy grids (down)
        down = r.get("down") or {}
        self.buy_grids_count = _int_or(
            r.get("buy_grids_count") or len(down.get("grids") or []), 0
        )
        self.buy_grids: List[Dict[str, Any]] = _list_or_default(
            r.get("buy_grids") or down.get("grids"), []
        )
        self.buy_trigger_trailing_pct = _float_or(
            r.get("buy_trigger_trailing_pct") or down.get("trail_pct"), 0.3
        )

        # Cycle / re-entry & profit exit
        profit = r.get("profit") or {}
        self.profit_reentry_drop_pct = _float_or(
            r.get("profit_reentry_drop_pct") or profit.get("rebuy_trigger_pct"), 1.0
        )
        self.profit_reentry_rise_pct = _float_or(
            r.get("profit_reentry_rise_pct") or profit.get("rebuy_trail_pct"), 0.3
        )
        self.profit_exit_rise_pct = _float_or(
            r.get("profit_exit_rise_pct") or profit.get("resell_trigger_pct"), 1.0
        )
        self.profit_exit_drop_pct = _float_or(
            r.get("profit_exit_drop_pct") or profit.get("resell_trail_pct"), 0.3
        )
        self.basis_mode = (
            (r.get("basis_mode") or profit.get("basis_mode") or "grid_only")
            .strip()
            .lower()
        )
        if self.basis_mode not in ("total", "grid_only"):
            self.basis_mode = "grid_only"

        self.tick_interval_ms = _int_or(r.get("tick_interval_ms"), 2000)
        self.trail_fast_tick_ms = _int_or(r.get("trail_fast_tick_ms"), 800)
        self.max_orders_per_minute = _int_or(r.get("max_orders_per_minute"), 12)
        self.max_slippage_pct = _float_or(r.get("max_slippage_pct"), 0.5)
        self.min_notional_guard = _float_or(r.get("min_notional_guard"), 5.0)
        # Fee/rounding buffer for initial allocation: usable = virtual_quote * (1 - initial_fee_buffer_pct)
        self.initial_fee_buffer_pct = _float_or(
            r.get("initial_fee_buffer_pct") or r.get("fee_buffer_pct"), 0.002
        )
        # Virtual/real drift buffer: available_quote_for_orders = free_quote * (1 - available_quote_buffer_pct)
        self.available_quote_buffer_pct = _float_or(
            r.get("available_quote_buffer_pct") or r.get("quote_buffer_pct"), 0.005
        )
        # Günlük kayıp limiti (USDT). 0 veya None = limit yok.
        _dll = r.get("daily_loss_limit_usd")
        self.daily_loss_limit_usd: float = (
            _float_or(_dll, 0.0) if _dll not in (None, "", 0) else 0.0
        )
        # Max buy grid seviyesi hard limiti. Production'da zorunlu ve pozitif.
        _mbl = r.get("max_buy_levels")
        _mbl_val = _int_or(_mbl, 0) if _mbl not in (None, "") else 0
        self.max_buy_levels: int = max(1, _mbl_val)

        # Dynamic Mode: ON/OFF, default False (mevcut manuel mod aynen çalışır).
        # Kullanıcıdan ek parametre ALINMAZ; sistem tüm dinamik değerleri otomatik üretir.
        self.dynamic_mode: bool = bool(r.get("dynamic_mode") or False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "initial_capital_usdt": self.initial_capital_usdt,
            "bot_budget_usdt": self.bot_budget_usdt,
            "base_alloc_pct": self.base_alloc_pct,
            "quote_alloc_pct": self.quote_alloc_pct,
            "fee_rate": self.fee_rate,
            "buy_fee_rate": self.buy_fee_rate,
            "sell_fee_rate": self.sell_fee_rate,
            "min_net_profit_rate": self.min_net_profit_rate,
            "pnl_mode": self.pnl_mode,
            "paper_mode": self.paper_mode,
            "sell_grids": self.sell_grids,
            "sell_trigger_trailing_pct": self.sell_trigger_trailing_pct,
            "buy_grids": self.buy_grids,
            "buy_trigger_trailing_pct": self.buy_trigger_trailing_pct,
            "profit_reentry_drop_pct": self.profit_reentry_drop_pct,
            "profit_reentry_rise_pct": self.profit_reentry_rise_pct,
            "profit_exit_rise_pct": self.profit_exit_rise_pct,
            "profit_exit_drop_pct": self.profit_exit_drop_pct,
            "basis_mode": self.basis_mode,
            "tick_interval_ms": self.tick_interval_ms,
            "trail_fast_tick_ms": self.trail_fast_tick_ms,
            "max_orders_per_minute": self.max_orders_per_minute,
            "max_slippage_pct": self.max_slippage_pct,
            "min_notional_guard": self.min_notional_guard,
            "initial_fee_buffer_pct": self.initial_fee_buffer_pct,
            "available_quote_buffer_pct": self.available_quote_buffer_pct,
            "daily_loss_limit_usd": self.daily_loss_limit_usd,
            "max_buy_levels": self.max_buy_levels,
            "dynamic_mode": self.dynamic_mode,
        }


class MultiAssetRebalanceConfig:
    """Config for multi-asset rebalance strategy. assets: list of {symbol, target_pct}; sum(target_pct)==100."""

    def __init__(self, raw: Dict[str, Any]):
        r = raw or {}
        self.strategy_id = "multi_asset_rebalance"
        assets_raw = r.get("assets") or []
        self.assets: List[Dict[str, Any]] = []
        for a in assets_raw:
            sym = (a.get("symbol") or "").upper().strip()
            if not sym:
                continue
            pct = _float_or(a.get("target_pct"), 0)
            self.assets.append(
                {
                    "symbol": sym if sym.endswith("USDT") else sym + "USDT",
                    "target_pct": pct,
                }
            )
        rebal = r.get("rebalance") or {}
        self.rebalance_mode = (rebal.get("mode") or "threshold").strip().lower()
        if self.rebalance_mode not in ("threshold", "interval", "hybrid"):
            self.rebalance_mode = "threshold"
        self.threshold_pct = _float_or(rebal.get("threshold_pct"), 2.0)
        self.interval_sec = _int_or(rebal.get("interval_sec"), 3600)
        self.min_trade_usdt = _float_or(rebal.get("min_trade_usdt"), 10.0)
        self.fees_buffer_bps = _int_or(rebal.get("fees_buffer_bps"), 20)
        self.max_trades_per_cycle = _int_or(rebal.get("max_trades_per_cycle"), 3)
        self.cooldown_sec = _int_or(rebal.get("cooldown_sec"), 300)
        self.budget_usdt = _float_or(
            r.get("budget_usdt")
            or r.get("budget_usd")
            or r.get("initial_capital_usdt"),
            1000.0,
        )
        self.tick_interval_ms = _int_or(r.get("tick_interval_ms"), 5000)
        self.min_notional_guard = _float_or(rebal.get("min_trade_usdt"), 10.0)
        self.symbol = "MULTI"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "budget_usdt": self.budget_usdt,
            "assets": self.assets,
            "rebalance": {
                "mode": self.rebalance_mode,
                "threshold_pct": self.threshold_pct,
                "interval_sec": self.interval_sec,
                "min_trade_usdt": self.min_trade_usdt,
                "fees_buffer_bps": self.fees_buffer_bps,
                "max_trades_per_cycle": self.max_trades_per_cycle,
                "cooldown_sec": self.cooldown_sec,
            },
            "tick_interval_ms": self.tick_interval_ms,
            "min_notional_guard": self.min_notional_guard,
        }


class TrdcaProConfig:
    """TRDCA PRO+ (Trailing Rebalancing + Trailing DCA/Grid). dca + trb + execution."""

    def __init__(self, raw: Dict[str, Any]):
        r = raw or {}
        self.strategy_id = "trdca_pro"
        self.quote_asset = (r.get("quote_asset") or "USDT").strip().upper() or "USDT"
        self.symbol = "MULTI"
        # Bot bakiye: UI'da "kullanılabilir" gösterimi; paper'da üst sınır. 0 = tam cüzdan.
        self.initial_capital_usdt = _float_or(
            r.get("initial_capital_usdt")
            or r.get("bot_budget_usdt")
            or r.get("bot_bakiye_usdt"),
            0.0,
        )
        self.bot_budget_usdt = self.initial_capital_usdt

        # Execution
        exec_cfg = r.get("execution") or {}
        self.ack_timeout_sec = _int_or(exec_cfg.get("ack_timeout_sec"), 5)
        self.tick_interval_ms = _int_or(r.get("tick_interval_ms"), 1000)

        # DCA
        dca = r.get("dca") or {}
        self.dca_enabled = bool(dca.get("enabled", True))
        coin_weights = dca.get("coin_weights") or {}
        self.dca_coin_weights: Dict[str, float] = {}
        for k, v in coin_weights.items():
            if k and k.strip().upper() != self.quote_asset:
                self.dca_coin_weights[(k.strip().upper())] = _float_or(v, 0)
        if not self.dca_coin_weights:
            self.dca_coin_weights = {"BTC": 0.3, "ETH": 0.3, "SOL": 0.2, "AVAX": 0.2}
        self.dca_grid_up_levels_pct = _list_or_default(
            dca.get("grid_up_levels_pct"), [1.0, 2.0, 3.0]
        )
        self.dca_grid_down_levels_pct = _list_or_default(
            dca.get("grid_down_levels_pct"), [1.0, 2.0, 3.0]
        )
        self.dca_grid_up_notional_usdt = _list_or_default(
            dca.get("grid_up_notional_usdt"), [200, 200, 200]
        )
        self.dca_grid_down_notional_usdt = _list_or_default(
            dca.get("grid_down_notional_usdt"), [200, 200, 200]
        )
        self.dca_grid_up_notional_pct = dca.get(
            "grid_up_notional_pct"
        )  # Opsiyonel: önceden belirlenen yüzde
        self.dca_grid_down_notional_pct = dca.get("grid_down_notional_pct")
        self.dca_sell_trail_back_pct = _float_or(dca.get("sell_trail_back_pct"), 0.8)
        self.dca_buy_trail_up_pct = _float_or(dca.get("buy_trail_up_pct"), 0.8)
        self.dca_buy_buffer_pct = _float_or(dca.get("buy_buffer_pct"), 0.2)
        post_sell = dca.get("post_sell") or {}
        self.dca_post_sell_dip_trigger_pct = _float_or(
            post_sell.get("dip_trigger_pct"), 2.0
        )
        self.dca_post_sell_dip_trail_up_pct = _float_or(
            post_sell.get("dip_trail_up_pct"), 0.8
        )
        self.dca_post_sell_dip_buy_notional_usdt = _float_or(
            post_sell.get("dip_buy_notional_usdt"), 200
        )
        post_buy = dca.get("post_buy") or {}
        self.dca_post_buy_profit_trigger_pct = _float_or(
            post_buy.get("profit_trigger_pct"), 2.0
        )
        self.dca_post_buy_profit_sell_trail_back_pct = _float_or(
            post_buy.get("profit_sell_trail_back_pct"), 0.8
        )
        self.dca_post_buy_profit_sell_notional_usdt = _float_or(
            post_buy.get("profit_sell_notional_usdt"), 200
        )

        # TRB
        trb = r.get("trb") or {}
        self.trb_enabled = bool(trb.get("enabled", True))
        target_all = trb.get("target_weights_all") or {}
        self.trb_target_weights_all: Dict[str, float] = {}
        for k, v in target_all.items():
            if k and str(k).strip():
                self.trb_target_weights_all[str(k).strip().upper()] = _float_or(v, 0)
        if not self.trb_target_weights_all:
            self.trb_target_weights_all = {
                "BTC": 0.3,
                "ETH": 0.3,
                "SOL": 0.2,
                "USDT": 0.2,
            }
        self.trb_small_eps_pct = _float_or(trb.get("small_eps_pct"), 0.8)
        self.trb_min_leg_notional_usdt = _float_or(
            trb.get("min_leg_notional_usdt"), 10.0
        )
        self.trb_gap_arm_pct = _float_or(trb.get("gap_arm_pct"), 3.0)
        self.trb_trail_back_pct = _float_or(trb.get("trail_back_pct"), 0.6)
        self.trb_max_batch_legs = _int_or(trb.get("max_batch_legs"), 8)
        self.trb_sell_first = bool(trb.get("sell_first", True))
        self.trb_step_mode = (trb.get("step_mode") or "SELL_ONLY_THEN_BUY").strip()
        self.trb_batch_atomicity = (trb.get("batch_atomicity") or "SOFT").strip()
        self.trb_partial_fill_behavior = (
            trb.get("partial_fill_behavior") or "SAFE_STOP"
        ).strip()
        self.trb_max_exec_delay_sec = _int_or(trb.get("max_exec_delay_sec"), 15)
        self.trb_ts_bucket_sec = _int_or(trb.get("ts_bucket_sec"), 5)
        self.trb_gap_peak_bucket_dp = _int_or(trb.get("gap_peak_bucket_dp"), 2)
        self.min_notional_guard = _float_or(
            trb.get("min_leg_notional_usdt") or r.get("min_notional_guard"), 10.0
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "quote_asset": self.quote_asset,
            "initial_capital_usdt": self.initial_capital_usdt,
            "bot_budget_usdt": self.bot_budget_usdt,
            "execution": {"ack_timeout_sec": self.ack_timeout_sec},
            "tick_interval_ms": self.tick_interval_ms,
            "dca": {
                "enabled": self.dca_enabled,
                "coin_weights": self.dca_coin_weights,
                "grid_up_levels_pct": self.dca_grid_up_levels_pct,
                "grid_down_levels_pct": self.dca_grid_down_levels_pct,
                "grid_up_notional_usdt": self.dca_grid_up_notional_usdt,
                "grid_down_notional_usdt": self.dca_grid_down_notional_usdt,
                "grid_up_notional_pct": self.dca_grid_up_notional_pct,
                "grid_down_notional_pct": self.dca_grid_down_notional_pct,
                "sell_trail_back_pct": self.dca_sell_trail_back_pct,
                "buy_trail_up_pct": self.dca_buy_trail_up_pct,
                "buy_buffer_pct": self.dca_buy_buffer_pct,
                "post_sell": {
                    "dip_trigger_pct": self.dca_post_sell_dip_trigger_pct,
                    "dip_trail_up_pct": self.dca_post_sell_dip_trail_up_pct,
                    "dip_buy_notional_usdt": self.dca_post_sell_dip_buy_notional_usdt,
                },
                "post_buy": {
                    "profit_trigger_pct": self.dca_post_buy_profit_trigger_pct,
                    "profit_sell_trail_back_pct": self.dca_post_buy_profit_sell_trail_back_pct,
                    "profit_sell_notional_usdt": self.dca_post_buy_profit_sell_notional_usdt,
                },
            },
            "trb": {
                "enabled": self.trb_enabled,
                "target_weights_all": self.trb_target_weights_all,
                "small_eps_pct": self.trb_small_eps_pct,
                "min_leg_notional_usdt": self.trb_min_leg_notional_usdt,
                "gap_arm_pct": self.trb_gap_arm_pct,
                "trail_back_pct": self.trb_trail_back_pct,
                "max_batch_legs": self.trb_max_batch_legs,
                "sell_first": self.trb_sell_first,
                "step_mode": self.trb_step_mode,
                "batch_atomicity": self.trb_batch_atomicity,
                "partial_fill_behavior": self.trb_partial_fill_behavior,
                "max_exec_delay_sec": self.trb_max_exec_delay_sec,
                "ts_bucket_sec": self.trb_ts_bucket_sec,
                "gap_peak_bucket_dp": self.trb_gap_peak_bucket_dp,
            },
        }


def config_trdca_pro_from_payload(payload: Dict[str, Any]) -> TrdcaProConfig:
    """Map UI/API payload to TrdcaProConfig."""
    return TrdcaProConfig(payload)


def config_multi_asset_from_payload(
    payload: Dict[str, Any],
) -> MultiAssetRebalanceConfig:
    """Map UI wizard payload to MultiAssetRebalanceConfig."""
    return MultiAssetRebalanceConfig(payload)


def config_from_ui_payload(payload: Dict[str, Any]) -> DcaGridTrailingConfig:
    """Map UI create-form payload to DcaGridTrailingConfig."""
    payload = normalize_max_buy_levels_payload(payload or {})
    # UI: up.grids[].trigger_pct, qty_pct; down same.
    sell_grids = []
    for g in (payload.get("up") or {}).get("grids") or []:
        sell_grids.append(
            {
                "sell_grid_pct": _float_or(g.get("trigger_pct"), 0),
                "sell_qty_pct_of_base": _float_or(g.get("qty_pct"), 0),
            }
        )
    buy_grids = []
    for g in (payload.get("down") or {}).get("grids") or []:
        buy_grids.append(
            {
                "buy_grid_pct": _float_or(g.get("trigger_pct"), 0),
                "buy_qty_pct_of_quote": _float_or(g.get("qty_pct"), 0),
            }
        )
    profit = payload.get("profit") or {}
    # Dynamic Mode requires a positive daily_loss_limit_usd as a safety
    # prerequisite. The create modal injects a default (budget×5%), but
    # API-direct create/update payloads may omit it — in that case dynamic mode
    # would silently never activate. Mirror the UI default here so the backend
    # is self-sufficient and the safety gate is always satisfiable.
    dynamic_on = bool(payload.get("dynamic_mode") or False)
    daily_loss = payload.get("daily_loss_limit_usd")
    if dynamic_on and (
        daily_loss in (None, "", 0) or _float_or(daily_loss, 0.0) <= 0
    ):
        budget_for_dll = _float_or(
            payload.get("budget_usd")
            or payload.get("initial_capital_usdt")
            or payload.get("bot_budget_usdt"),
            1000.0,
        )
        daily_loss = max(5.0, round(budget_for_dll * 0.05, 2))
    raw = {
        "symbol": payload.get("symbol"),
        "budget_usd": payload.get("budget_usd"),
        "allocation": payload.get("allocation"),
        "mode": payload.get("mode", "live"),
        "up": {
            "trail_pct": (payload.get("up") or {}).get("trail_pct"),
            "grids": sell_grids,
        },
        "down": {
            "trail_pct": (payload.get("down") or {}).get("trail_pct"),
            "grids": buy_grids,
        },
        "profit": profit,
        "basis_mode": profit.get("basis_mode")
        or payload.get("basis_mode")
        or "grid_only",
        "tick_interval_ms": payload.get("tick_interval_ms", 2000),
        "max_orders_per_minute": payload.get("max_orders_per_minute", 12),
        "max_slippage_pct": payload.get("max_slippage_pct", 0.5),
        "max_buy_levels": payload.get("max_buy_levels"),
        "dynamic_mode": dynamic_on,
        "daily_loss_limit_usd": daily_loss,
    }
    return DcaGridTrailingConfig(raw)


def build_state_skeleton(bot_id: int, account_id: int, symbol: str) -> Dict[str, Any]:
    return {
        "bot_id": bot_id,
        "account_id": account_id,
        "symbol": symbol,
        "status": "running",
        "cycle_id": 1,
        "state_version": 0,
        "reference_price": None,
        "initial_allocation_done": False,
        "base_balance": 0.0,
        "quote_balance": 0.0,
        "avg_sell_price": None,
        "avg_buy_price": None,
        "sell_grid_fired": [],
        "sell_grid_trigger_price": [],
        "sell_grid_peak_price": [],
        "buy_grid_fired": [],
        "buy_grid_trigger_price": [],
        "buy_grid_trough_price": [],
        "mode": BotEngineMode.IDLE.value,
        "trail_anchor_price": None,
        "trail_activation_price": None,
        "last_action_id": None,
        "open_order_ids": [],
        "realized_pnl_usdt_cycle": 0.0,
        "fees_paid_usdt_cycle": 0.0,
        "last_tick_at": None,
        "next_wakeup_at": None,
        "last_error_code": None,
        "last_error_at": None,
        "cycle_pnls": [],
    }


def build_trdca_pro_state_skeleton(
    bot_id: int, account_id: int, quote_asset: str = "USDT"
) -> Dict[str, Any]:
    """State skeleton for TRDCA PRO+ (Trailing Rebalancing DCA). Single source of truth for initial state."""
    return {
        "bot_id": bot_id,
        "account_id": account_id,
        "symbol": "MULTI",
        "status": "running",
        "mode": "RUNNING",
        "last_reason": None,
        "config_hash": None,
        "last_tick_ts": 0,
        "quote_asset": quote_asset,
        "base_pct": 0.0,
        "quote_pct": 0.0,
        "base_invested_done": 0.0,
        "quote_reserve_quote": 0.0,
        "anchor_price": None,
        "anchor_set_ts_bucket": 0,
        "basket_weights_hash": None,
        "anchor_id": None,
        "price_null_strikes": {},
        "pending_quote_committed": 0.0,
        "pending_base_committed": {},
        "dca": {
            "grid_up_consumed": [],
            "grid_down_consumed": [],
            "armed": {
                "type": "NONE",
                "level_idx": None,
                "peak_or_trough": None,
                "started_at_ts": None,
            },
            "vwap_sell": None,
            "vwap_buy": None,
        },
        "trb": {
            "trb_state": "IDLE",
            "gap_peak_pct": 0.0,
            "trb_triggered_at_ts": 0,
            "trb_cycles_count": 0,
            "plan": None,
        },
        "active_intent": None,
        "arb_last": None,
        "arb_win_streak_source": None,
        "arb_win_streak_count": None,
        "execute_ready_since_ms": None,
        "state_version": 0,
        "cycle_id": 1,
        "last_tick_at": None,
        "last_error_code": None,
        "retry_at": None,
    }
