"""
Copy Trading: sanitize bot config for leaderboard/public display.
Only strategy params (grid step, trail %, max orders, cooldown, etc.).
Never include: account_id, bot_id, balances, api keys, coin amounts, cost basis, wallet.
"""
import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Whitelist keys for trailing_dca (DCA grid trailing) – strategy config only.
# Bütçe ve sahiplik asla paylaşılmaz: budget/initial_capital dahil etme.
TRAILING_DCA_SAFE_KEYS = frozenset({
    "symbol",
    "allocation", "base_pct", "quote_pct",
    "up", "down", "profit",
    "trail_pct", "grids", "rebuy_trigger_pct", "rebuy_trail_pct",
    "resell_trigger_pct", "resell_trail_pct",
    "strategy_id",
})

# Nested keys we allow to copy as-is. Bütçe/sermaye paylaşılmaz.
TRDCA_SAFE_TOP_KEYS = frozenset({
    "strategy_id", "quote_asset", "tick_interval_ms",
    "execution", "dca", "trb",
})
# Inside dca/trb we allow structure only – no balances, no wallet refs
TRDCA_DCA_SAFE = frozenset({
    "enabled", "coin_weights", "grid_up_levels_pct", "grid_down_levels_pct",
    "grid_up_notional_usdt", "grid_down_notional_usdt",
    "grid_up_notional_pct", "grid_down_notional_pct",
    "sell_trail_back_pct", "buy_trail_up_pct", "buy_buffer_pct",
    "post_sell", "post_buy",
})
TRDCA_TRB_SAFE = frozenset({
    "enabled", "target_weights_all", "small_eps_pct", "min_leg_notional_usdt",
    "gap_arm_pct", "trail_back_pct",
})


def _grid_list(items: Any, trigger_key: str, qty_key: str) -> list:
    rows = []
    for g in items or []:
        if not isinstance(g, dict):
            continue
        rows.append({
            "trigger_pct": g.get(trigger_key) if g.get(trigger_key) is not None else g.get("trigger_pct"),
            "qty_pct": g.get(qty_key) if g.get(qty_key) is not None else g.get("qty_pct"),
        })
    return rows


def _sanitize_trailing_dca(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    alloc = cfg.get("allocation") if isinstance(cfg.get("allocation"), dict) else {}
    base_pct = alloc.get("base_pct") if alloc else cfg.get("base_alloc_pct")
    quote_pct = alloc.get("quote_pct") if alloc else cfg.get("quote_alloc_pct")
    if base_pct is not None or quote_pct is not None:
        out["allocation"] = {"base_pct": base_pct, "quote_pct": quote_pct}
    if base_pct is not None:
        out["base_alloc_pct"] = base_pct
    if quote_pct is not None:
        out["quote_alloc_pct"] = quote_pct

    up = cfg.get("up") if isinstance(cfg.get("up"), dict) else {}
    down = cfg.get("down") if isinstance(cfg.get("down"), dict) else {}
    sell_grids = cfg.get("sell_grids") if isinstance(cfg.get("sell_grids"), list) else None
    buy_grids = cfg.get("buy_grids") if isinstance(cfg.get("buy_grids"), list) else None
    if up:
        out["up"] = {"trail_pct": up.get("trail_pct"), "grids": up.get("grids") or []}
    elif sell_grids:
        out["up"] = {
            "trail_pct": cfg.get("sell_trigger_trailing_pct"),
            "grids": _grid_list(sell_grids, "sell_grid_pct", "sell_qty_pct_of_base"),
        }
    if down:
        out["down"] = {"trail_pct": down.get("trail_pct"), "grids": down.get("grids") or []}
    elif buy_grids:
        out["down"] = {
            "trail_pct": cfg.get("buy_trigger_trailing_pct"),
            "grids": _grid_list(buy_grids, "buy_grid_pct", "buy_qty_pct_of_quote"),
        }
    if sell_grids:
        out["sell_grids"] = sell_grids
        if cfg.get("sell_trigger_trailing_pct") is not None:
            out["sell_trigger_trailing_pct"] = cfg.get("sell_trigger_trailing_pct")
    if buy_grids:
        out["buy_grids"] = buy_grids
        if cfg.get("buy_trigger_trailing_pct") is not None:
            out["buy_trigger_trailing_pct"] = cfg.get("buy_trigger_trailing_pct")

    profit = cfg.get("profit") if isinstance(cfg.get("profit"), dict) else {}
    rebuy_trigger = profit.get("rebuy_trigger_pct") if profit else cfg.get("profit_reentry_drop_pct")
    rebuy_trail = profit.get("rebuy_trail_pct") if profit else cfg.get("profit_reentry_rise_pct")
    resell_trigger = profit.get("resell_trigger_pct") if profit else cfg.get("profit_exit_rise_pct")
    resell_trail = profit.get("resell_trail_pct") if profit else cfg.get("profit_exit_drop_pct")
    if any(v is not None for v in (rebuy_trigger, rebuy_trail, resell_trigger, resell_trail)):
        out["profit"] = {
            "rebuy_trigger_pct": rebuy_trigger,
            "rebuy_trail_pct": rebuy_trail,
            "resell_trigger_pct": resell_trigger,
            "resell_trail_pct": resell_trail,
        }
        if cfg.get("profit_reentry_drop_pct") is not None:
            out["profit_reentry_drop_pct"] = cfg.get("profit_reentry_drop_pct")
        if cfg.get("profit_reentry_rise_pct") is not None:
            out["profit_reentry_rise_pct"] = cfg.get("profit_reentry_rise_pct")
        if cfg.get("profit_exit_rise_pct") is not None:
            out["profit_exit_rise_pct"] = cfg.get("profit_exit_rise_pct")
        if cfg.get("profit_exit_drop_pct") is not None:
            out["profit_exit_drop_pct"] = cfg.get("profit_exit_drop_pct")

    for k in ("symbol", "strategy_id"):
        if k in cfg and cfg[k] is not None:
            out[k] = cfg[k]
    return out


def _sanitize_trdca(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in TRDCA_SAFE_TOP_KEYS:
        if k not in cfg or cfg[k] is None:
            continue
        if k == "dca" and isinstance(cfg[k], dict):
            out["dca"] = {k2: cfg["dca"][k2] for k2 in TRDCA_DCA_SAFE if k2 in cfg["dca"]}
        elif k == "trb" and isinstance(cfg[k], dict):
            out["trb"] = {k2: cfg["trb"][k2] for k2 in TRDCA_TRB_SAFE if k2 in cfg["trb"]}
        elif k in ("execution", "quote_asset", "tick_interval_ms", "strategy_id"):
            out[k] = cfg[k]
    return out


def sanitize_bot_params(bot_row: Any, state_row: Any, cfg_json: str) -> Dict[str, Any]:
    """
    Produce a copy-trading safe param dict from bot config.
    bot_row: DB Bot model (optional; symbol taken from here if not in config).
    state_row: bot state (optional, not used for public params).
    cfg_json: bot.config_json string.
    Returns dict suitable for JSON storage in bot_public_metrics.params_sanitized_json.
    Bütçe/sermaye asla dahil edilmez.
    """
    try:
        cfg = json.loads(cfg_json or "{}")
    except Exception:
        return {}
    strategy_id = (cfg.get("strategy_id") or "").strip().lower()
    if strategy_id == "trdca_pro":
        out = _sanitize_trdca(cfg)
    else:
        out = _sanitize_trailing_dca(cfg)
    if bot_row and getattr(bot_row, "symbol", None) and "symbol" not in out:
        out["symbol"] = (bot_row.symbol or "").strip() or None
    return out
