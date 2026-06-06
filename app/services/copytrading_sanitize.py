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


def _sanitize_trailing_dca(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if cfg.get("allocation"):
        out["allocation"] = {
            "base_pct": cfg["allocation"].get("base_pct"),
            "quote_pct": cfg["allocation"].get("quote_pct"),
        }
    if cfg.get("up"):
        u = cfg["up"]
        out["up"] = {"trail_pct": u.get("trail_pct"), "grids": u.get("grids") or []}
    if cfg.get("down"):
        d = cfg["down"]
        out["down"] = {"trail_pct": d.get("trail_pct"), "grids": d.get("grids") or []}
    if cfg.get("profit"):
        p = cfg["profit"]
        out["profit"] = {
            "rebuy_trigger_pct": p.get("rebuy_trigger_pct"),
            "rebuy_trail_pct": p.get("rebuy_trail_pct"),
            "resell_trigger_pct": p.get("resell_trigger_pct"),
            "resell_trail_pct": p.get("resell_trail_pct"),
        }
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
