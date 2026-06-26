"""Normalize ParamTemplate → audit profile dict (v3 pool compatible)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.param_generator.feature_bins import regime_class_from_tag
from app.services.dynamic_param_score.param_generator.amount_distribution import (
    geometric_distribution,
    select_distribution_mode,
)
from app.services.dynamic_param_score.param_generator.grid_math import (
    ASSET_MIN_GRID,
    apply_side_structure_multiplier,
    compute_grid_ladder,
    compute_trailing_pct,
    enforce_grid_spacing_minimums,
)
from app.services.dynamic_param_score.param_pool.models import ParamTemplate

_BUDGET_TIER_TO_CLASS = {
    "NANO": "10_25",
    "MICRO": "25_50",
    "SMALL": "50_100",
    "STANDARD": "100_250",
    "MEDIUM": "250_500",
    "LARGE": "500_1000",
    "WHALE": "1000_PLUS",
}

_FEE_TIER_TO_CLASS = {
    "FEE_BAD": "fee_bad",
    "FEE_WEAK": "high_fee",
    "FEE_OK": "normal_fee",
    "FEE_GOOD": "low_fee",
    "FEE_EXCELLENT": "low_fee",
}

_VOL_TIER_TO_BIN = {
    "VOL_TOO_LOW": "0_10",
    "VOL_LOW": "10_25",
    "VOL_MID": "25_50",
    "VOL_NORMAL": "25_50",
    "VOL_HIGH": "50_75",
    "VOL_EXTREME": "75_90",
}

_STRUCTURE_SHORT = {
    "HI": "higher_highs_only",
    "LO": "lower_lows_only",
    "BO": "both",
    "NE": "neither",
}


def _parse_structure_from_key(template_key: str) -> Optional[str]:
    parts = (template_key or "").upper().split("_")
    for p in parts:
        if p in _STRUCTURE_SHORT:
            return _STRUCTURE_SHORT[p]
    return None


def _approved_distribution(
    n: int,
    *,
    fee_class: str,
    structure: str,
    risk: str,
    variant: int,
) -> List[int]:
    if n <= 0:
        return []
    mode = select_distribution_mode(risk_level=risk, fee_class=fee_class, structure=structure)
    modes: list = ["normal", "defensive", "aggressive"]
    pick = modes[(modes.index(mode) + variant) % len(modes)]
    return [int(round(x * 100)) for x in geometric_distribution(n, pick)]  # type: ignore[arg-type]


_DEFAULT_ATR_PCT = 1.5


def _pct_list(weights: List[float]) -> List[int]:
    if not weights:
        return []
    total = sum(weights)
    if abs(total - 1.0) < 0.05:
        return [int(round(w * 100)) for w in weights]
    if abs(total - 100.0) < 1.0:
        return [int(round(w)) for w in weights]
    return [int(round(w * 100 / max(total, 0.01))) for w in weights]


def _variant_idx(template_key: str) -> int:
    m = re.search(r"_p(\d+)$", template_key or "")
    return int(m.group(1)) if m else 0


def _first_budget_class(t: ParamTemplate) -> str:
    if t.budget_tiers:
        return _BUDGET_TIER_TO_CLASS.get(t.budget_tiers[0], "50_100")
    return "50_100"


def _first_fee_class(t: ParamTemplate) -> str:
    if t.fee_tiers:
        return _FEE_TIER_TO_CLASS.get(t.fee_tiers[0], "normal_fee")
    return "normal_fee"


def _first_vol_bin(t: ParamTemplate) -> str:
    if t.volatility_tiers:
        return _VOL_TIER_TO_BIN.get(t.volatility_tiers[0], "25_50")
    return "25_50"


def _first_regime(t: ParamTemplate) -> str:
    if t.supported_regimes:
        return regime_class_from_tag(t.supported_regimes[0])
    return "BALANCED_RANGE"


def _resolve_spacing_pct(p: Dict[str, Any], side: str, asset_class: str) -> float:
    asset_min = ASSET_MIN_GRID.get(asset_class, 1.80)
    atr_mult = float(p.get(f"{side}_spacing_atr_mult") or 0.9)
    min_pct = float(p.get(f"{side}_spacing_min_pct") or 0.45)
    atr = _DEFAULT_ATR_PCT
    spacing = max(min_pct, atr * atr_mult, asset_min * 0.85)
    return round(max(spacing, asset_min), 4)


def _build_side_grids(
    p: Dict[str, Any],
    dp: Dict[str, Any],
    side: str,
    grid_count: int,
    asset_class: str,
    fee_class: str,
    variant: int,
) -> List[float]:
    ladder_key = f"{side}_grid_pcts"
    existing = dp.get(ladder_key) or p.get(f"{side}_grid_ladder_pcts")
    if isinstance(existing, list) and existing:
        return [float(x) for x in existing[:grid_count]]

    if grid_count <= 0:
        return []

    first = _resolve_spacing_pct(p, side, asset_class)
    first = round(first * (1.0 + 0.025 * (variant % 17)), 4)
    if fee_class == "fee_bad":
        first = round(first * 1.12, 4)
    grids = compute_grid_ladder(first, grid_count, variant_idx=variant)
    grids = apply_side_structure_multiplier(
        grids, side=side, structure=p.get("structure") or "neither", fee_class=fee_class
    )
    return enforce_grid_spacing_minimums(grids, asset_class)


def template_to_audit_profile(t: ParamTemplate) -> Dict[str, Any]:
    """Normalize ParamTemplate → audit schema dict."""
    p = dict(t.params or {})
    dp = dict(p.get("dps_profile") or {})
    variant = _variant_idx(t.template_key)

    asset = dp.get("asset_class") or p.get("asset_class") or "MID_CAP"
    budget_class = dp.get("budget_class") or _first_budget_class(t)
    regime = dp.get("regime") or _first_regime(t)
    fee_class = dp.get("fee_class") or _first_fee_class(t)
    vol_bin = dp.get("volatility_bin") or _first_vol_bin(t)

    buy_n = int(dp.get("buy_grid_count") or p.get("buy_grid_count") or 0)
    sell_n = int(dp.get("sell_grid_count") or p.get("sell_grid_count") or 0)

    buy_grids = _build_side_grids(p, dp, "buy", buy_n, asset, fee_class, variant)
    sell_grids = _build_side_grids(p, dp, "sell", sell_n, asset, fee_class, variant + 1)

    if buy_n > 0 and not buy_grids:
        buy_grids = compute_grid_ladder(ASSET_MIN_GRID.get(asset, 1.8), buy_n, variant_idx=variant)
    if sell_n > 0 and not sell_grids:
        sell_grids = compute_grid_ladder(ASSET_MIN_GRID.get(asset, 1.8), sell_n, variant_idx=variant + 1)

    buy_n = len(buy_grids) if buy_grids else buy_n
    sell_n = len(sell_grids) if sell_grids else sell_n

    first_grid = buy_grids[0] if buy_grids else (sell_grids[0] if sell_grids else 1.5)
    trail = float(
        p.get("min_trailing_pct")
        or dp.get("buy_trailing_pct")
        or compute_trailing_pct(first_grid, asset, fee_class=fee_class)
    )

    structure = dp.get("structure") or _parse_structure_from_key(t.template_key) or "neither"
    risk = dp.get("risk_level") or (t.allowed_risk_states[0] if t.allowed_risk_states else "NORMAL")

    buy_dist = dp.get("buy_distribution")
    sell_dist = dp.get("sell_distribution")
    if buy_n > 0 and (not buy_dist or len(buy_dist) != buy_n):
        buy_dist = _approved_distribution(
            buy_n, fee_class=fee_class, structure=structure, risk=str(risk), variant=variant
        )
    else:
        buy_dist = buy_dist or _pct_list(p.get("buy_qty_distribution") or [])
    if sell_n > 0 and (not sell_dist or len(sell_dist) != sell_n):
        sell_dist = _approved_distribution(
            sell_n, fee_class=fee_class, structure=structure, risk=str(risk), variant=variant + 1
        )
    else:
        sell_dist = sell_dist or _pct_list(p.get("sell_qty_distribution") or [])

    score_prior = float(
        dp.get("score_prior")
        or p.get("score_prior")
        or t.validation_quality_score
        or (t.score_min + t.score_max) / 2
    )

    return {
        "profile_id": dp.get("profile_id") or t.template_key,
        "template_key": t.template_key,
        "asset_class": asset,
        "budget_class": budget_class,
        "regime": regime,
        "risk_level": risk,
        "volatility_bin": vol_bin,
        "atr_1h_bin": dp.get("atr_1h_bin") or vol_bin,
        "adx_bin": dp.get("adx_bin") or "15_25",
        "rsi_state": dp.get("rsi_state") or "neutral",
        "bb_position": dp.get("bb_position") or "mid",
        "structure": structure,
        "fee_class": fee_class,
        "spread_class": dp.get("spread_class") or "tight",
        "data_quality": dp.get("data_quality") or "good",
        "buy_grid_count": buy_n,
        "sell_grid_count": sell_n,
        "buy_grid_pcts": buy_grids,
        "sell_grid_pcts": sell_grids,
        "buy_distribution": buy_dist,
        "sell_distribution": sell_dist,
        "buy_trailing_pct": float(dp.get("buy_trailing_pct") or trail),
        "sell_trailing_pct": float(dp.get("sell_trailing_pct") or trail),
        "rebuy_trigger_pct": float(p.get("rebuy_trigger_pct") or dp.get("rebuy_trigger_pct") or 0),
        "rebuy_trail_pct": float(p.get("rebuy_trail_pct") or dp.get("rebuy_trail_pct") or trail),
        "resell_trigger_pct": float(p.get("resell_trigger_pct") or dp.get("resell_trigger_pct") or 0),
        "resell_trail_pct": float(p.get("resell_trail_pct") or dp.get("resell_trail_pct") or trail),
        "min_budget_required": float(dp.get("min_budget_required") or t.min_equity_usdt or 25),
        "max_budget_recommended": float(dp.get("max_budget_recommended") or t.max_equity_usdt or 10000),
        "score_prior": score_prior,
        "safety_level": dp.get("safety_level") or (
            "WAIT" if t.final_action in ("WAIT", "NO_TRADE", "SAFE_WAIT") else "ACTIVE"
        ),
        "version": dp.get("version") or p.get("dps_engine_version") or t.version,
        "final_action": t.final_action,
        "profile_family": t.profile_family,
        "deployable": t.deployable,
        "template_key_raw": t.template_key,
        "has_dps_profile": bool(dp),
    }


def behavior_fingerprint(profile: Dict[str, Any]) -> str:
    """Hash behavior-relevant fields for duplicate / delta audit."""
    import hashlib
    import json

    core = {
        "asset_class": profile.get("asset_class"),
        "budget_class": profile.get("budget_class"),
        "regime": profile.get("regime"),
        "risk_level": profile.get("risk_level"),
        "buy_grid_pcts": profile.get("buy_grid_pcts"),
        "sell_grid_pcts": profile.get("sell_grid_pcts"),
        "buy_distribution": profile.get("buy_distribution"),
        "sell_distribution": profile.get("sell_distribution"),
        "buy_trailing_pct": profile.get("buy_trailing_pct"),
        "sell_trailing_pct": profile.get("sell_trailing_pct"),
        "rebuy_trigger_pct": profile.get("rebuy_trigger_pct"),
        "resell_trigger_pct": profile.get("resell_trigger_pct"),
        "fee_class": profile.get("fee_class"),
        "spread_class": profile.get("spread_class"),
        "min_budget_required": profile.get("min_budget_required"),
    }
    raw = json.dumps(core, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]
