"""Structural validation for param template pool."""

from __future__ import annotations

from typing import List, Tuple

from app.services.dynamic_param_score.models import FinalAction
from app.services.dynamic_param_score.param_pool.models import ParamTemplate, ProfileFamily

_VALID_REGIMES = {
    "NO_DATA",
    "NO_TRADE",
    "DUMP_RISK",
    "TRENDING_DOWN",
    "HIGH_VOL_UNSTABLE",
    "RANGE_LOW_VOL",
    "RANGE_HIGH_VOL",
    "BALANCED_RANGE",
    "TRENDING_UP",
    "BREAKOUT_RISK",
    "LOW_LIQUIDITY",
    "SPREAD_UNSAFE",
}

_VALID_RISK = {"BLOCKED", "DEFENSIVE", "CAUTION", "NORMAL", "SAFE"}

_VALID_ACTIONS = {a.value for a in FinalAction}

_BUY_REQUIRED_ACTIONS = {
    FinalAction.DEFENSIVE_GRID.value,
    FinalAction.BALANCED_GRID.value,
    FinalAction.ACTIVE_GRID.value,
    FinalAction.ACTIVE_DEFENSIVE_GRID.value,
    FinalAction.LOW_FEE_WIDE_GRID.value,
    FinalAction.TREND_TRAILING.value,
}


def validate_template(t: ParamTemplate) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if t.score_min > t.score_max:
        errors.append("score_min > score_max")
    if t.score_min < 0 or t.score_max > 100:
        errors.append("score aralığı 0–100 dışında")
    if not t.supported_regimes:
        errors.append("supported_regimes boş")
    for r in t.supported_regimes:
        if r not in _VALID_REGIMES:
            errors.append(f"geçersiz rejim: {r}")
    for rs in t.allowed_risk_states:
        if rs not in _VALID_RISK:
            errors.append(f"geçersiz risk_state: {rs}")
    if t.final_action not in _VALID_ACTIONS:
        errors.append(f"geçersiz final_action: {t.final_action}")
    if t.profile_family not in {p.value for p in ProfileFamily}:
        errors.append(f"geçersiz profile_family: {t.profile_family}")
    buy_n = int(t.params.get("buy_grid_count", 0) or 0)
    sell_n = int(t.params.get("sell_grid_count", 0) or 0)
    if t.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        if buy_n > 0 or sell_n > 0:
            errors.append("NO_TRADE/WAIT template grid içermemeli")
        if t.deployable:
            errors.append("NO_TRADE/WAIT template deployable=false olmalı")
    if t.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        if buy_n > 0:
            errors.append("SELL_MANAGEMENT_ONLY buy_grid_count=0 olmalı")
        if sell_n < 1:
            errors.append("SELL_MANAGEMENT_ONLY en az 1 sell grid")
        if not t.requires_sellable_base and not t.hard_limits.get("requires_sell_min_notional"):
            errors.append("SELL_MANAGEMENT_ONLY requires_sellable_base veya requires_sell_min_notional olmalı")
    if t.hard_limits.get("buy_grid_allowed") is False and buy_n > 0:
        errors.append("hard_limits buy_grid_allowed=false ama buy_grid_count>0")
    if t.final_action in _BUY_REQUIRED_ACTIONS and buy_n < 1:
        if not t.hard_limits.get("buy_grid_allowed") is False:
            errors.append(f"{t.final_action} en az 1 buy grid bekler")
    return len(errors) == 0, errors


def validate_pool(templates: List[ParamTemplate]) -> Tuple[bool, List[str]]:
    all_errors: List[str] = []
    keys = set()
    for t in templates:
        if t.template_key in keys:
            all_errors.append(f"duplicate key: {t.template_key}")
        keys.add(t.template_key)
        ok, errs = validate_template(t)
        if not ok:
            all_errors.extend(f"{t.template_key}: {e}" for e in errs)
    return len(all_errors) == 0, all_errors
