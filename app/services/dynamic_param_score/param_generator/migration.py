"""Migrate legacy v2 100k templates to DPS Engine V2 schema."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from app.services.dynamic_param_score.models import FinalAction
from app.services.dynamic_param_score.param_generator.amount_distribution import (
    geometric_distribution,
    select_distribution_mode,
)
from app.services.dynamic_param_score.param_generator.grid_math import (
    ASSET_MIN_GRID,
    compute_grid_ladder,
    enforce_grid_spacing_minimums,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate
from app.services.dynamic_param_score.utils import distribute_weights

DPS_ENGINE_V2 = "DPS_ENGINE_V2"

_LEGACY_ACTION_MAP = {
    "WAIT_FEE_BAD": FinalAction.ACTIVE_DEFENSIVE_GRID.value,
    "FEE_BAD_WAIT": FinalAction.ACTIVE_DEFENSIVE_GRID.value,
    "GRID_TOO_CLOSE": "WIDENED_GRID",
    "BUDGET_TOO_SMALL": "REDUCED_GRID_COUNT",
    "MIN_NOTIONAL_FAIL": "GRID_COUNT_RECALCULATED",
}


def _widen_spacing(val: float, asset_min: float) -> float:
    return round(max(float(val or 0), asset_min, 1.0) * 1.15, 4)


def _fix_equal_distribution(dist: List[float], count: int) -> List[float]:
    if not dist or count <= 0:
        return geometric_distribution(count, "normal")
    if len(dist) != count:
        return geometric_distribution(count, "normal")
    # Detect ~equal split
    if count >= 2 and all(abs(d - 1.0 / count) < 0.05 for d in dist):
        return geometric_distribution(count, "normal")
    if count >= 2 and all(abs(d - 100 / count) < 3 for d in dist):
        return [x * 100 for x in geometric_distribution(count, "normal")]
    return dist


def migrate_template(t: ParamTemplate, *, seq: int = 0) -> Optional[ParamTemplate]:
    """Transform a v2 template into DPS Engine V2 schema."""
    params = copy.deepcopy(t.params)
    asset = "BTC_ETH_MAJOR" if "BTC" in t.template_key or "ETH" in t.template_key else "MID_CAP"
    asset_min = ASSET_MIN_GRID.get(asset, 1.80)

    final_action = t.final_action
    profile_family = t.profile_family
    deployable = t.deployable
    notes_parts = list(t.notes or []) if isinstance(t.notes, list) else ([t.notes] if t.notes else [])

    # Fee bad WAIT → ACTIVE_DEFENSIVE_GRID
    if (
        final_action in (FinalAction.WAIT.value, FinalAction.SAFE_WAIT.value)
        and ("FEE_BAD" in t.template_key or "FEE_WEAK" in t.template_key)
    ):
        final_action = FinalAction.ACTIVE_DEFENSIVE_GRID.value
        profile_family = "ACTIVE_DEFENSIVE_GRID_PROFILE"
        deployable = True
        buy_n = max(int(params.get("buy_grid_count") or 2), 1)
        sell_n = max(int(params.get("sell_grid_count") or 2), 1)
        params["buy_grid_count"] = buy_n
        params["sell_grid_count"] = sell_n
        notes_parts.append("migrated:WAIT_FEE_BAD→ACTIVE_DEFENSIVE_GRID")

    buy_spacing = float(params.get("buy_grid_spacing_pct") or params.get("buy_spacing_pct") or 0)
    sell_spacing = float(params.get("sell_grid_spacing_pct") or params.get("sell_spacing_pct") or 0)

    if buy_spacing > 0 and buy_spacing < asset_min:
        params["buy_grid_spacing_pct"] = _widen_spacing(buy_spacing, asset_min)
        notes_parts.append("legacy_risky:buy_grid_widened")
    if sell_spacing > 0 and sell_spacing < asset_min:
        params["sell_grid_spacing_pct"] = _widen_spacing(sell_spacing, asset_min)
        notes_parts.append("legacy_risky:sell_grid_widened")

    buy_n = int(params.get("buy_grid_count") or 0)
    sell_n = int(params.get("sell_grid_count") or 0)
    if buy_n > 0:
        mode = select_distribution_mode(risk_level="NORMAL", fee_class="normal_fee")
        params["buy_qty_distribution"] = _fix_equal_distribution(
            params.get("buy_qty_distribution") or [], buy_n
        )
        if not params.get("buy_qty_distribution"):
            params["buy_qty_distribution"] = geometric_distribution(buy_n, mode)
    if sell_n > 0:
        mode = select_distribution_mode(risk_level="NORMAL", fee_class="normal_fee")
        params["sell_qty_distribution"] = _fix_equal_distribution(
            params.get("sell_qty_distribution") or [], sell_n
        )
        if not params.get("sell_qty_distribution"):
            params["sell_qty_distribution"] = geometric_distribution(sell_n, mode)

    params["dps_engine_version"] = DPS_ENGINE_V2
    params["asset_class"] = asset
    params["migration_tag"] = _LEGACY_ACTION_MAP.get("FEE_BAD_WAIT", "MIGRATED")

    if final_action in (FinalAction.WAIT.value, FinalAction.NO_TRADE.value):
        if "FEE" not in t.template_key:
            return None  # drop non-fee WAIT templates from active pool

    updates: Dict[str, Any] = {
        "params": params,
        "final_action": final_action,
        "profile_family": profile_family,
        "deployable": deployable,
        "notes": ";".join(notes_parts) if notes_parts else None,
        "version": DPS_ENGINE_V2,
    }
    if t.profile_subfamily:
        updates["profile_subfamily"] = t.profile_subfamily

    return t.model_copy(update=updates)


def migrate_pool(templates: List[ParamTemplate]) -> Tuple[List[ParamTemplate], Dict[str, int]]:
    """Migrate v2 pool; return (migrated, stats)."""
    stats = {
        "input": len(templates),
        "migrated": 0,
        "dropped": 0,
        "fee_bad_converted": 0,
        "grids_widened": 0,
    }
    seen_keys: set[str] = set()
    out: List[ParamTemplate] = []

    for i, t in enumerate(templates):
        m = migrate_template(t, seq=i)
        if m is None:
            stats["dropped"] += 1
            continue
        if m.template_key in seen_keys:
            stats["dropped"] += 1
            continue
        seen_keys.add(m.template_key)
        if "WAIT_FEE_BAD" in str(m.notes or ""):
            stats["fee_bad_converted"] += 1
        if "widened" in str(m.notes or ""):
            stats["grids_widened"] += 1
        out.append(m)
        stats["migrated"] += 1

    return out, stats
