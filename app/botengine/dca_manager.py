"""
DCA manager guards.

Single source for max_buy_levels validation/enforcement across API, UI payloads,
engine ticks, execution and DB backfills.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


class MaxBuyLevelsError(ValueError):
    """Raised when max_buy_levels is missing, invalid or exceeded."""


@dataclass(frozen=True)
class MaxBuyLevelsPolicy:
    max_buy_levels: int
    buy_grid_count: int


def _as_int(value: Any, *, field: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise MaxBuyLevelsError(f"{field} zorunlu ve pozitif tam sayı olmalı")
    if out <= 0:
        raise MaxBuyLevelsError(f"{field} zorunlu ve 1 veya daha büyük olmalı")
    return out


def buy_grid_count_from_payload(payload: Dict[str, Any]) -> int:
    down = payload.get("down") or {}
    raw_grids = payload.get("buy_grids") or down.get("grids") or []
    return len(raw_grids if isinstance(raw_grids, list) else [])


def normalize_max_buy_levels_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy with validated max_buy_levels.

    The limit is mandatory for dca_grid_trailing and cannot exceed configured
    buy grid count. This keeps restarts and UI/API payload shapes consistent.
    """
    raw = dict(payload or {})
    strategy_id = (raw.get("strategy_id") or "dca_grid_trailing").strip().lower()
    symbol = (raw.get("symbol") or "").strip().upper()
    if strategy_id in ("trdca_pro", "multi_asset_rebalance") or symbol == "MULTI":
        return raw
    grid_count = buy_grid_count_from_payload(raw)
    limit = _as_int(raw.get("max_buy_levels"), field="max_buy_levels")
    if grid_count <= 0:
        raise MaxBuyLevelsError("max_buy_levels için en az bir alım grid'i tanımlanmalı")
    if limit > grid_count:
        raise MaxBuyLevelsError(
            f"max_buy_levels ({limit}) alım grid sayısını ({grid_count}) aşamaz"
        )
    raw["max_buy_levels"] = limit
    return raw


def max_buy_levels_from_config_json(config_json: Optional[str]) -> int:
    try:
        raw = json.loads(config_json or "{}")
        return int(raw.get("max_buy_levels") or 0)
    except Exception:
        return 0


def derive_max_buy_levels_for_existing_config(config_json: Optional[str]) -> int:
    """Backfill existing bots conservatively with the current buy grid count."""
    try:
        raw = json.loads(config_json or "{}")
    except Exception:
        raw = {}
    existing = raw.get("max_buy_levels")
    grid_count = buy_grid_count_from_payload(raw)
    try:
        val = int(existing)
    except (TypeError, ValueError):
        val = 0
    if val > 0:
        return min(val, grid_count) if grid_count > 0 else val
    return max(1, grid_count)


def fired_buy_levels(state: Dict[str, Any]) -> int:
    return sum(1 for value in (state.get("buy_grid_fired") or []) if value)


def assert_can_open_buy_level(
    *,
    state: Dict[str, Any],
    max_buy_levels: int,
    pending_buy_actions: int = 0,
    reason: str = "trail_buy_grid",
) -> None:
    limit = _as_int(max_buy_levels, field="max_buy_levels")
    fired = fired_buy_levels(state)
    if fired + max(0, int(pending_buy_actions or 0)) >= limit:
        raise MaxBuyLevelsError(
            f"MAX_BUY_LEVELS_EXCEEDED reason={reason} fired={fired} pending={pending_buy_actions} max={limit}"
        )
