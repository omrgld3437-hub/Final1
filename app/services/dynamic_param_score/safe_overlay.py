"""Safe overlay builders for WAIT / NO_TRADE / stale-data management modes."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.dynamic_param_score.models import DynamicParamDecision, FinalAction


def management_mode_from_action(final_action: str) -> str:
    fa = str(final_action or "").upper()
    mapping = {
        FinalAction.WAIT.value: "SAFE_WAIT",
        FinalAction.WAIT_SAFETY.value: "WAIT_SAFETY",
        FinalAction.NO_TRADE.value: "NO_TRADE",
        FinalAction.SELL_MANAGEMENT_ONLY.value: "SELL_MANAGEMENT_ONLY",
        FinalAction.ACTIVE_DEFENSIVE_GRID.value: "ACTIVE_DEFENSIVE_GRID",
        "SAFE_WAIT": "SAFE_WAIT",
        "DATA_STALE_SAFE_WAIT": "DATA_STALE_SAFE_WAIT",
        "RECOVERY_SELL": "RECOVERY_SELL",
        "LOW_FEE_WIDE_GRID": "LOW_FEE_WIDE_GRID",
        "INITIAL_ENTRY": "INITIAL_ENTRY",
    }
    return mapping.get(fa, fa or "SAFE_WAIT")


def apply_policy_from_decision(final_action: str, *, deployable: bool) -> str:
    fa = str(final_action or "").upper()
    if deployable:
        return "allow"
    if fa == FinalAction.NO_TRADE.value:
        return "no_trade"
    if fa in (FinalAction.WAIT.value, FinalAction.WAIT_SAFETY.value, "SAFE_WAIT", "DATA_STALE_SAFE_WAIT"):
        return "safe_wait"
    if fa == FinalAction.SELL_MANAGEMENT_ONLY.value:
        return "sell_management"
    if fa in (
        FinalAction.ACTIVE_DEFENSIVE_GRID.value,
        FinalAction.DEFENSIVE_GRID.value,
        FinalAction.LOW_FEE_WIDE_GRID.value,
    ):
        return "reference_grid"
    return "safe_wait"


def ui_severity_from_decision(final_action: str, *, ok: bool = True) -> str:
    if not ok:
        return "error"
    fa = str(final_action or "").upper()
    if fa == FinalAction.NO_TRADE.value:
        return "info"
    if fa in (FinalAction.WAIT.value, FinalAction.WAIT_SAFETY.value, "SAFE_WAIT", "DATA_STALE_SAFE_WAIT"):
        return "info"
    if fa == FinalAction.SELL_MANAGEMENT_ONLY.value:
        return "success"
    return "info"


def _base_overlay_fields(
    *,
    final_action: str,
    management_mode: str,
    selected_template_key: Optional[str] = None,
    pool_version: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "selected_template_key": selected_template_key,
        "pool_version": pool_version,
        "final_action": final_action,
        "management_mode": management_mode,
    }


def build_safe_wait_overlay(
    decision: DynamicParamDecision,
    base_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Overlay that clears buy side and cancels stale buy orders — no new trades."""
    _ = base_cfg
    tel = decision.telemetry or {}
    pool = tel.get("param_pool") or {}
    mm = management_mode_from_action(decision.final_action)
    if decision.final_action in (FinalAction.WAIT.value, FinalAction.WAIT_SAFETY.value):
        mm = "SAFE_WAIT" if decision.final_action == FinalAction.WAIT.value else "WAIT_SAFETY"
    return {
        "buy_grids": [],
        "sell_grids": [],
        "max_buy_levels": 0,
        "buy_trigger_trailing_pct": 0.0,
        "profit_reentry_drop_pct": 0.0,
        "profit_reentry_rise_pct": 0.0,
        "rebuy_enabled": False,
        "resell_enabled": False,
        "buy_disabled": True,
        "sell_only_mode": False,
        "cancel_existing_buy_orders": True,
        "cancel_existing_sell_orders": False,
        **_base_overlay_fields(
            final_action=decision.final_action,
            management_mode=mm,
            selected_template_key=pool.get("selected_template_key"),
            pool_version=pool.get("pool_version"),
        ),
    }


def build_no_trade_overlay(
    decision: DynamicParamDecision,
    base_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full trade abstain overlay — both sides cleared."""
    _ = base_cfg
    tel = decision.telemetry or {}
    pool = tel.get("param_pool") or {}
    return {
        "buy_grids": [],
        "sell_grids": [],
        "max_buy_levels": 0,
        "rebuy_enabled": False,
        "resell_enabled": False,
        "buy_disabled": True,
        "sell_only_mode": False,
        "cancel_existing_buy_orders": True,
        "cancel_existing_sell_orders": True,
        **_base_overlay_fields(
            final_action=FinalAction.NO_TRADE.value,
            management_mode="NO_TRADE",
            selected_template_key=pool.get("selected_template_key"),
            pool_version=pool.get("pool_version"),
        ),
    }


def build_data_stale_overlay(base_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stale data path — never restore manual buy grids."""
    base = dict(base_cfg or {})
    sell_grids = list(base.get("sell_grids") or [])
    return {
        "buy_grids": [],
        "max_buy_levels": 0,
        "buy_trigger_trailing_pct": 0.0,
        "profit_reentry_drop_pct": 0.0,
        "profit_reentry_rise_pct": 0.0,
        "rebuy_enabled": False,
        "buy_disabled": True,
        "sell_only_mode": False,
        "cancel_existing_buy_orders": True,
        "cancel_existing_sell_orders": False,
        "sell_grids": sell_grids,
        "final_action": "WAIT",
        "management_mode": "DATA_STALE_SAFE_WAIT",
    }


def build_safe_overlay_for_decision(
    decision: DynamicParamDecision,
    base_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    fa = str(decision.final_action or "").upper()
    if fa == FinalAction.NO_TRADE.value:
        return build_no_trade_overlay(decision, base_cfg)
    return build_safe_wait_overlay(decision, base_cfg)
