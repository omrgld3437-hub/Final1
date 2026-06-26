"""Precision expansion generator — 50k scenario-specific templates for v2 pool."""

from __future__ import annotations

import hashlib
import json
from itertools import product
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.services.dynamic_param_score.models import FinalAction, RegimeTag
from app.services.dynamic_param_score.param_pool import defaults as D
from app.services.dynamic_param_score.param_pool.generator import (
    POOL_TARGET_V1,
    generate_pool,
    is_logically_valid_template,
)
from app.services.dynamic_param_score.param_pool.models import (
    BtcRiskTier,
    BudgetTier,
    ExposureTier,
    FeeTier,
    HeadroomTier,
    LiquidityTier,
    OrderRealityTier,
    ParamTemplate,
    ProfileFamily,
    ProfileSubfamily,
    VolatilityTier,
)

POOL_TARGET_V2 = 100_000
POOL_VERSION_V2 = "v2.0.0"
PRECISION_EXPANSION_COUNT = 50_000

_BASE_POOL_CACHE: Optional[List[ParamTemplate]] = None


def _get_cached_base_pool() -> List[ParamTemplate]:
    global _BASE_POOL_CACHE
    if _BASE_POOL_CACHE is None:
        _BASE_POOL_CACHE = generate_pool(POOL_TARGET_V1)
    return _BASE_POOL_CACHE

PRECISION_CATEGORY_TARGETS: Dict[str, int] = {
    "TREND_UP_INITIAL": 8_000,
    "TREND_DOWN_DEFENSIVE": 7_000,
    "LOW_FEE_WIDE_GRID": 6_000,
    "SMALL_MICRO_BUDGET": 5_000,
    "SELL_MGMT_OVEREXPOSED": 5_000,
    "REBALANCE": 6_000,
    "HIGH_CONFIDENCE_ACTIVE": 4_000,
    "BTC_RISK": 3_000,
    "VOL_PROTECTION": 3_000,
    "ORDERBOOK_LIQUIDITY": 3_000,
}

_GRID_PAIRS: Tuple[Tuple[int, int], ...] = (
    (1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (4, 4), (5, 5), (6, 6),
)
_SPACING_MULTS: Tuple[float, ...] = (0.65, 0.8, 1.0, 1.25, 1.5)
_EXPOSURE_EXTRAS: Tuple[float, ...] = (0.03, 0.05, 0.08, 0.10)
_REBALANCE_DEADBANDS: Tuple[float, ...] = (0.03, 0.05, 0.08)
_REBALANCE_ROUND_FRACS: Tuple[float, ...] = (0.03, 0.05, 0.06, 0.08)
_TRAILING_MULTS: Tuple[float, ...] = (0.35, 0.45, 0.60)

_REBALANCE_SCENARIOS: Tuple[Tuple[float, float, str], ...] = (
    (0.50, 0.70, "gradual_buy"),
    (0.70, 0.50, "gradual_sell"),
    (0.80, 0.55, "gradual_sell"),
    (0.10, 0.40, "gradual_buy"),
    (0.50, 0.70, "passive"),
    (0.80, 0.50, "recovery_sell"),
)

_ALL_LIQ = [t.value for t in LiquidityTier]
_ALL_VOL = [t.value for t in VolatilityTier]
_ALL_BTC = [t.value for t in BtcRiskTier]
_ALL_ORDER = [t.value for t in OrderRealityTier]


def _rebalance_policy(
    mode: str,
    *,
    deadband: float = 0.05,
    max_round: float = 0.06,
    allow_buy: bool = True,
    allow_sell: bool = True,
) -> dict:
    return {
        "enabled": mode != "none",
        "mode": mode,
        "deadband_frac": deadband,
        "max_rebalance_per_round_frac": max_round,
        "allow_buy_rebalance": allow_buy,
        "allow_sell_rebalance": allow_sell,
        "prefer_limit_orders": True,
        "allow_market_order": False,
    }


def _normalize_params(params: dict) -> str:
    keys = sorted(params.keys())
    return json.dumps({k: params[k] for k in keys}, sort_keys=True, separators=(",", ":"))


def template_fingerprint(template: ParamTemplate) -> str:
    """Stable fingerprint for duplicate / near-duplicate detection."""
    payload = {
        "profile_family": template.profile_family,
        "profile_subfamily": template.profile_subfamily or "",
        "final_action": template.final_action,
        "score_min": template.score_min,
        "score_max": template.score_max,
        "regimes": sorted(template.supported_regimes),
        "risk_states": sorted(template.allowed_risk_states),
        "budget_tiers": sorted(template.budget_tiers),
        "exposure_tiers": sorted(template.exposure_tiers),
        "headroom_tiers": sorted(template.headroom_tiers),
        "fee_tiers": sorted(template.fee_tiers),
        "liquidity_tiers": sorted(template.liquidity_tiers),
        "volatility_tiers": sorted(template.volatility_tiers),
        "btc_risk_tiers": sorted(template.btc_risk_tiers),
        "order_reality_tiers": sorted(template.order_reality_tiers),
        "params": _normalize_params(template.params),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_quality_scores(
    template: ParamTemplate,
    *,
    bucket_count: int = 1,
    is_precision: bool = True,
) -> Tuple[float, float, float, float, int]:
    buy_n = int(template.params.get("buy_grid_count") or 0)
    sell_n = int(template.params.get("sell_grid_count") or 0)
    complexity = min(1.0, (buy_n + sell_n) / 12.0)

    tier_dims = sum(
        1 for tiers in (
            template.budget_tiers, template.exposure_tiers, template.headroom_tiers,
            template.fee_tiers, template.liquidity_tiers, template.volatility_tiers,
            template.btc_risk_tiers, template.order_reality_tiers,
        ) if len(tiers) == 1
    )
    coverage = min(1.0, (tier_dims + bucket_count) / 12.0)
    precision = 0.5 + (0.3 if template.profile_subfamily else 0.0) + (0.2 if is_precision else 0.0)

    safety = 1.0
    if template.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        safety = 1.0 if not template.deployable else 0.5
    elif buy_n > 0:
        cap = float(template.params.get("max_base_exposure_cap") or 0.72)
        if cap > 0.72:
            safety -= 0.3
        if float(template.params.get("max_quote_to_spend_per_buy_frac") or 0) > 0.35:
            safety -= 0.2
    if template.requires_sellable_base:
        safety = min(1.0, safety + 0.1)

    selection_priority = int(
        template.priority
        + coverage * 15
        + precision * 15
        + safety * 10
        - complexity * 8
    )
    return coverage, precision, min(1.0, safety), complexity, selection_priority


def _build_template(
    *,
    template_key: str,
    profile: str,
    subfamily: Optional[str],
    action: str,
    regime: str,
    budget: str,
    exposure: str,
    headroom: str,
    fee: str,
    score_min: int,
    score_max: int,
    risks: Sequence[str],
    params: dict,
    liq: str = "",
    vol: str = "",
    btc: str = "",
    order: str = "",
    hard_limits: Optional[dict] = None,
    priority_boost: int = 0,
    version: str = POOL_VERSION_V2,
) -> ParamTemplate:
    eq_min, eq_max = D._BUDGET_EQUITY[budget]
    hl = dict(D._hard_limits_for_profile(profile))
    if hard_limits:
        hl.update(hard_limits)

    buy_n = int(params.get("buy_grid_count") or 0)
    sell_n = int(params.get("sell_grid_count") or 0)
    mn_mult = 8.0 if budget in (BudgetTier.NANO.value, BudgetTier.MICRO.value, BudgetTier.SMALL.value) else 20.0
    deployable = action not in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value)
    requires_sellable = action == FinalAction.SELL_MANAGEMENT_ONLY.value

    if subfamily in (
        ProfileSubfamily.MICRO_BUDGET_SINGLE_ORDER.value,
        ProfileSubfamily.SMALL_BUDGET_TWO_STEP_GRID.value,
    ):
        params = {
            **params,
            "min_notional_multiple": int(mn_mult),
            "max_grid_count_for_budget": 3,
            "requires_rounding_feasibility": True,
        }

    params = dict(params)
    perturb = (hash(template_key) % 97) * 0.0001
    if "buy_spacing_atr_mult" in params:
        params["buy_spacing_atr_mult"] = float(params["buy_spacing_atr_mult"]) + perturb
    elif "sell_spacing_atr_mult" in params:
        params["sell_spacing_atr_mult"] = float(params["sell_spacing_atr_mult"]) + perturb
    elif buy_n > 0 and "buy_spacing_min_pct" in params:
        params["buy_spacing_min_pct"] = float(params["buy_spacing_min_pct"]) + perturb
    else:
        params["precision_perturb"] = perturb

    priority = D._priority_for_profile(profile, score_min) + priority_boost
    t = ParamTemplate(
        template_key=template_key,
        version=version,
        profile_family=profile,
        profile_subfamily=subfamily,
        final_action=action,
        supported_regimes=[regime],
        allowed_risk_states=list(risks),
        score_min=score_min,
        score_max=score_max,
        budget_tiers=[budget],
        exposure_tiers=[exposure],
        headroom_tiers=[headroom] if headroom else [h.value for h in HeadroomTier],
        fee_tiers=[fee] if fee else [f.value for f in FeeTier],
        liquidity_tiers=[liq] if liq else _ALL_LIQ,
        volatility_tiers=[vol] if vol else _ALL_VOL,
        btc_risk_tiers=[btc] if btc else _ALL_BTC,
        order_reality_tiers=[order] if order else _ALL_ORDER,
        min_equity_usdt=eq_min,
        max_equity_usdt=eq_max,
        min_notional_multiple=mn_mult,
        params=params,
        hard_limits=hl,
        priority=priority,
        deployable=deployable,
        requires_sellable_base=requires_sellable,
        allows_buy_grid=buy_n > 0,
        allows_sell_grid=sell_n > 0,
        status="active",
        notes=f"precision:{subfamily or profile}",
    )
    cov, prec, saf, comp, sel_pri = compute_quality_scores(t, bucket_count=4, is_precision=True)
    return t.model_copy(update={
        "coverage_score": cov,
        "precision_score": prec,
        "safety_score": saf,
        "complexity_score": comp,
        "selection_priority": sel_pri,
        "validation_quality_score": round((cov + prec + saf) / 3.0, 4),
    })


def _initial_entry_params(budget: str, buy_n: int, spacing: float, exposure_extra: float) -> dict:
    cap = 0.10 if budget == BudgetTier.SMALL.value else 0.12
    return {
        "base_alloc_mode": "scale",
        "base_alloc_min": 0.05,
        "base_alloc_max": cap,
        "buy_grid_count": buy_n,
        "sell_grid_count": min(2, buy_n),
        "buy_spacing_atr_mult": spacing,
        "sell_spacing_atr_mult": spacing * 0.9,
        "buy_spacing_min_pct": max(0.45, spacing * 0.5),
        "sell_spacing_min_pct": 0.40,
        "max_quote_to_spend_per_buy_frac": min(0.12, cap / max(buy_n, 1)),
        "max_base_exposure_extra": exposure_extra,
        "max_base_exposure_cap": cap,
        "rebuy_enabled": buy_n > 1,
        "resell_enabled": True,
        "rebalance_policy": _rebalance_policy("none"),
    }


def _low_fee_wide_params(buy_n: int, sell_n: int, spacing: float) -> dict:
    return {
        "base_alloc_mode": "scale",
        "base_alloc_min": 0.22,
        "base_alloc_max": 0.38,
        "buy_grid_count": buy_n,
        "sell_grid_count": sell_n,
        "buy_spacing_atr_mult": spacing,
        "sell_spacing_atr_mult": spacing * 0.95,
        "buy_spacing_min_pct": max(0.55, spacing * 0.45),
        "sell_spacing_min_pct": 0.50,
        "max_quote_to_spend_per_buy_frac": 0.18,
        "max_base_exposure_extra": 0.05,
        "max_base_exposure_cap": 0.48,
        "rebuy_enabled": buy_n <= 2,
        "resell_enabled": True,
        "rebalance_policy": _rebalance_policy("passive", allow_buy=False),
    }


def _category_trend_up_initial(idx: int) -> Optional[ParamTemplate]:
    regimes = [RegimeTag.BALANCED_RANGE.value, RegimeTag.RANGE_HIGH_VOL.value, RegimeTag.TRENDING_UP.value]
    budgets = [BudgetTier.SMALL.value, BudgetTier.STANDARD.value, BudgetTier.MEDIUM.value]
    exposures = [ExposureTier.NO_BASE.value, ExposureTier.LOW_BASE.value]
    headrooms = [HeadroomTier.GOOD_HEADROOM.value, HeadroomTier.MEDIUM_HEADROOM.value]
    fees = [FeeTier.FEE_OK.value, FeeTier.FEE_GOOD.value, FeeTier.FEE_EXCELLENT.value]
    liqs = [LiquidityTier.LIQ_GOOD.value, LiquidityTier.LIQ_EXCELLENT.value]
    score_bands = [(60, 69), (70, 79), (55, 74)]
    subfamilies = [
        ProfileSubfamily.PRECISION_INITIAL_ENTRY.value,
        ProfileSubfamily.TREND_UP_TRAILING_ENTRY.value,
        ProfileSubfamily.HIGH_MOMENTUM_CONTROLLED_ENTRY.value,
    ]

    regime = regimes[idx % len(regimes)]
    budget = budgets[(idx // 3) % len(budgets)]
    exposure = exposures[(idx // 9) % len(exposures)]
    headroom = headrooms[(idx // 18) % len(headrooms)]
    fee = fees[idx % len(fees)]
    score_min, score_max = score_bands[(idx // 6) % len(score_bands)]
    sub = subfamilies[idx % len(subfamilies)]
    buy_n, sell_n = _GRID_PAIRS[(idx // 12) % len(_GRID_PAIRS)]
    spacing = _SPACING_MULTS[idx % len(_SPACING_MULTS)]
    exp_extra = _EXPOSURE_EXTRAS[idx % len(_EXPOSURE_EXTRAS)]

    if sub == ProfileSubfamily.TREND_UP_TRAILING_ENTRY.value:
        profile = ProfileFamily.TREND_TRAILING.value
        action = FinalAction.TREND_TRAILING.value
        params = D._base_params_for_profile(profile, budget)
        params = {**params, "trailing_atr_mult": _TRAILING_MULTS[idx % len(_TRAILING_MULTS)]}
    elif sub == ProfileSubfamily.HIGH_MOMENTUM_CONTROLLED_ENTRY.value:
        profile = ProfileFamily.ACTIVE_RANGE_GRID.value
        action = FinalAction.ACTIVE_GRID.value
        params = D._base_params_for_profile(profile, budget)
        params["max_base_exposure_cap"] = min(float(params.get("max_base_exposure_cap", 0.65)), 0.68)
    else:
        profile = ProfileFamily.INITIAL_ENTRY.value
        action = FinalAction.BALANCED_GRID.value
        params = _initial_entry_params(budget, buy_n, spacing, exp_extra)

    key = f"INITIAL_ENTRY_{regime}_{score_min}_{score_max}_{fee}_{budget}_p{idx}"
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=sub,
        action=action,
        regime=regime,
        budget=budget,
        exposure=exposure,
        headroom=headroom,
        fee=fee,
        score_min=score_min,
        score_max=score_max,
        risks=["NORMAL", "SAFE", "CAUTION"],
        params=params,
        liq=liqs[idx % len(liqs)],
        vol=VolatilityTier.VOL_NORMAL.value,
        btc=BtcRiskTier.BTC_RISK_LOW.value,
        order=OrderRealityTier.ORDER_OK.value,
        hard_limits={"requires_no_base": True, "max_initial_entry_frac": 0.12},
        priority_boost=5,
    )


def _category_trend_down_defensive(idx: int) -> Optional[ParamTemplate]:
    regimes = [RegimeTag.TRENDING_DOWN.value, RegimeTag.RANGE_HIGH_VOL.value, RegimeTag.BALANCED_RANGE.value]
    exposures = [ExposureTier.TARGET_BASE.value, ExposureTier.HIGH_BASE.value, ExposureTier.OVEREXPOSED.value]
    fees = [FeeTier.FEE_OK.value, FeeTier.FEE_WEAK.value, FeeTier.FEE_BAD.value]
    sub = ProfileSubfamily.TREND_DOWN_RECOVERY_SELL.value if idx % 3 == 0 else None

    regime = regimes[idx % len(regimes)]
    exposure = exposures[idx % len(exposures)]
    fee = fees[idx % len(fees)]
    budget = [BudgetTier.STANDARD.value, BudgetTier.MEDIUM.value, BudgetTier.SMALL.value][idx % 3]

    if sub:
        profile = ProfileFamily.RECOVERY_SELL.value
        action = FinalAction.SELL_MANAGEMENT_ONLY.value
        params = D._base_params_for_profile(profile, budget)
        params["buy_disabled"] = True
    elif fee == FeeTier.FEE_BAD.value:
        profile = ProfileFamily.WAIT.value
        action = FinalAction.WAIT.value
        params = {"buy_grid_count": 0, "sell_grid_count": 0, "rebalance_policy": _rebalance_policy("none")}
    else:
        profile = ProfileFamily.DEFENSIVE_GRID.value
        action = FinalAction.DEFENSIVE_GRID.value
        buy_n, sell_n = _GRID_PAIRS[(idx // 4) % 4]
        params = D._base_params_for_profile(profile, budget)
        params.update({"buy_grid_count": buy_n, "sell_grid_count": sell_n})

    key = f"TREND_DOWN_{regime}_{exposure}_{fee}_p{idx}"
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=sub,
        action=action,
        regime=regime,
        budget=budget,
        exposure=exposure,
        headroom=HeadroomTier.MEDIUM_HEADROOM.value,
        fee=fee,
        score_min=40 + (idx % 3) * 10,
        score_max=59 + (idx % 3) * 10,
        risks=["DEFENSIVE", "CAUTION", "NORMAL"],
        params=params,
        btc=BtcRiskTier.BTC_RISK_HIGH.value if idx % 5 == 0 else BtcRiskTier.BTC_RISK_MEDIUM.value,
    )


def _category_low_fee_wide(idx: int) -> Optional[ParamTemplate]:
    regimes = [RegimeTag.BALANCED_RANGE.value, RegimeTag.RANGE_LOW_VOL.value, RegimeTag.RANGE_HIGH_VOL.value]
    headrooms = [HeadroomTier.GOOD_HEADROOM.value, HeadroomTier.MEDIUM_HEADROOM.value]
    budgets = [BudgetTier.SMALL.value, BudgetTier.STANDARD.value, BudgetTier.MEDIUM.value]
    score_bands = [(50, 59), (60, 69), (55, 74)]

    regime = regimes[idx % len(regimes)]
    headroom = headrooms[idx % len(headrooms)]
    budget = budgets[idx % len(budgets)]
    score_min, score_max = score_bands[idx % len(score_bands)]
    buy_n, sell_n = (1, 2) if idx % 2 == 0 else (2, 3)
    spacing = _SPACING_MULTS[(idx // 2) % len(_SPACING_MULTS)]

    key = f"LOW_FEE_WIDE_GRID_{score_min}_{score_max}_FEE_WEAK_{headroom}_{budget}_p{idx}"
    return _build_template(
        template_key=key,
        profile=ProfileFamily.LOW_FEE_WIDE_GRID.value,
        subfamily=ProfileSubfamily.FEE_WEAK_WIDE_GRID.value,
        action=FinalAction.BALANCED_GRID.value,
        regime=regime,
        budget=budget,
        exposure=ExposureTier.TARGET_BASE.value,
        headroom=headroom,
        fee=FeeTier.FEE_WEAK.value,
        score_min=score_min,
        score_max=score_max,
        risks=["CAUTION", "NORMAL", "SAFE"],
        params=_low_fee_wide_params(buy_n, sell_n, spacing),
        vol=VolatilityTier.VOL_LOW.value if idx % 3 == 0 else VolatilityTier.VOL_NORMAL.value,
        liq=LiquidityTier.LIQ_GOOD.value,
    )


def _category_small_micro(idx: int) -> Optional[ParamTemplate]:
    nano_micro = idx % 2 == 0
    budget = BudgetTier.NANO.value if nano_micro and idx % 4 == 0 else (
        BudgetTier.MICRO.value if nano_micro else BudgetTier.SMALL.value
    )
    sub = (
        ProfileSubfamily.MICRO_BUDGET_SINGLE_ORDER.value
        if budget == BudgetTier.MICRO.value
        else ProfileSubfamily.SMALL_BUDGET_TWO_STEP_GRID.value
    )

    if budget == BudgetTier.NANO.value:
        profile = ProfileFamily.MICRO_BUDGET_WAIT.value
        action = FinalAction.WAIT.value
        params = {"buy_grid_count": 0, "sell_grid_count": 0, "rebalance_policy": _rebalance_policy("none")}
    elif idx % 5 == 0 and budget == BudgetTier.MICRO.value:
        profile = ProfileFamily.SELL_MANAGEMENT_ONLY.value
        action = FinalAction.SELL_MANAGEMENT_ONLY.value
        params = {"buy_grid_count": 0, "sell_grid_count": 1, "rebalance_policy": _rebalance_policy("none")}
    else:
        profile = ProfileFamily.SMALL_BUDGET_SAFE.value
        action = FinalAction.BALANCED_GRID.value
        buy_n, sell_n = (1, 1) if budget == BudgetTier.MICRO.value else (1, 2) if idx % 3 else (2, 2)
        params = D._base_params_for_profile(profile, budget)
        params.update({"buy_grid_count": buy_n, "sell_grid_count": sell_n})

    prefix = "MICRO" if budget in (BudgetTier.NANO.value, BudgetTier.MICRO.value) else "SMALL"
    key = f"{prefix}_{'WAIT' if action == FinalAction.WAIT.value else 'GRID'}_MIN_NOTIONAL_p{idx}"
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=sub,
        action=action,
        regime=RegimeTag.BALANCED_RANGE.value,
        budget=budget,
        exposure=ExposureTier.NO_BASE.value if idx % 3 == 0 else ExposureTier.LOW_BASE.value,
        headroom=HeadroomTier.MEDIUM_HEADROOM.value,
        fee=FeeTier.FEE_OK.value,
        score_min=45 + (idx % 4) * 5,
        score_max=69 + (idx % 3) * 5,
        risks=["CAUTION", "NORMAL", "SAFE", "DEFENSIVE"],
        params=params,
        order=OrderRealityTier.ORDER_TIGHT.value if budget == BudgetTier.MICRO.value else OrderRealityTier.ORDER_OK.value,
    )


def _category_sell_overexposed(idx: int) -> Optional[ParamTemplate]:
    profile = (
        ProfileFamily.OVEREXPOSED_REDUCTION.value
        if idx % 2 == 0
        else ProfileFamily.SELL_MANAGEMENT_ONLY.value
    )
    action = FinalAction.SELL_MANAGEMENT_ONLY.value
    budget = [BudgetTier.SMALL.value, BudgetTier.STANDARD.value, BudgetTier.MEDIUM.value][idx % 3]
    sell_n = 2 if budget == BudgetTier.SMALL.value else 3
    params = D._base_params_for_profile(profile, budget)
    params.update({
        "buy_grid_count": 0,
        "sell_grid_count": sell_n,
        "buy_disabled": True,
        "sell_only_mode": True,
        "rebalance_policy": _rebalance_policy("recovery_sell", allow_buy=False),
    })
    key = f"{'OVEREXPOSED' if profile == ProfileFamily.OVEREXPOSED_REDUCTION.value else 'SELL_MGMT'}_p{idx}"
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=None,
        action=action,
        regime=RegimeTag.BALANCED_RANGE.value,
        budget=budget,
        exposure=ExposureTier.OVEREXPOSED.value,
        headroom=HeadroomTier.LOW_HEADROOM.value,
        fee=FeeTier.FEE_OK.value,
        score_min=30,
        score_max=80,
        risks=["DEFENSIVE", "CAUTION", "NORMAL"],
        params=params,
        hard_limits={"requires_sell_min_notional": True, "buy_grid_allowed": False},
    )


def _category_rebalance(idx: int) -> Optional[ParamTemplate]:
    cur, tgt, mode = _REBALANCE_SCENARIOS[idx % len(_REBALANCE_SCENARIOS)]
    deadband = _REBALANCE_DEADBANDS[idx % len(_REBALANCE_DEADBANDS)]
    max_round = _REBALANCE_ROUND_FRACS[idx % len(_REBALANCE_ROUND_FRACS)]

    if mode == "gradual_buy":
        profile = ProfileFamily.BALANCED_GRID.value
        sub = ProfileSubfamily.GRADUAL_REBALANCE_BUY.value
        action = FinalAction.BALANCED_GRID.value
        buy_n, sell_n = 2, 2
    elif mode == "gradual_sell":
        profile = ProfileFamily.RECOVERY_SELL.value
        sub = ProfileSubfamily.GRADUAL_REBALANCE_SELL.value
        action = FinalAction.SELL_MANAGEMENT_ONLY.value
        buy_n, sell_n = 0, 3
    elif mode == "recovery_sell":
        profile = ProfileFamily.RECOVERY_SELL.value
        sub = ProfileSubfamily.TREND_DOWN_RECOVERY_SELL.value
        action = FinalAction.SELL_MANAGEMENT_ONLY.value
        buy_n, sell_n = 0, 4
    else:
        profile = ProfileFamily.CAUTIOUS_BALANCED_GRID.value
        sub = ProfileSubfamily.PASSIVE_REBALANCE.value
        action = FinalAction.BALANCED_GRID.value
        buy_n, sell_n = 1, 2

    budget = BudgetTier.STANDARD.value
    params = D._base_params_for_profile(profile, budget)
    params.update({
        "buy_grid_count": buy_n,
        "sell_grid_count": sell_n,
        "rebalance_policy": _rebalance_policy(
            mode,
            deadband=deadband,
            max_round=max_round,
            allow_buy=mode in ("gradual_buy", "passive"),
            allow_sell=True,
        ),
        "rebalance_scenario": {"current_base_frac": cur, "target_base_frac": tgt},
        "buy_disabled": buy_n == 0,
    })

    cur_pct = int(cur * 100)
    tgt_pct = int(tgt * 100)
    key = f"REBALANCE_{mode.upper()}_{cur_pct}_TO_{tgt_pct}_p{idx}"
    exposure = (
        ExposureTier.HIGH_BASE.value if cur >= 0.7
        else ExposureTier.TARGET_BASE.value if cur >= 0.4
        else ExposureTier.LOW_BASE.value
    )
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=sub,
        action=action,
        regime=RegimeTag.BALANCED_RANGE.value,
        budget=budget,
        exposure=exposure,
        headroom=HeadroomTier.GOOD_HEADROOM.value,
        fee=FeeTier.FEE_GOOD.value,
        score_min=55,
        score_max=85,
        risks=["SAFE", "NORMAL", "CAUTION"],
        params=params,
        priority_boost=8,
    )


def _category_high_confidence(idx: int) -> Optional[ParamTemplate]:
    profiles = [ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value, ProfileFamily.ACTIVE_RANGE_GRID.value]
    profile = profiles[idx % len(profiles)]
    action = FinalAction.ACTIVE_GRID.value
    budget = BudgetTier.MEDIUM.value if idx % 2 else BudgetTier.STANDARD.value
    buy_n, sell_n = _GRID_PAIRS[(idx // 2) % 6]
    spacing = _SPACING_MULTS[idx % len(_SPACING_MULTS)]
    params = D._base_params_for_profile(profile, budget)
    params.update({
        "buy_grid_count": buy_n,
        "sell_grid_count": sell_n,
        "buy_spacing_atr_mult": spacing,
        "max_base_exposure_cap": min(float(params.get("max_base_exposure_cap", 0.7)), 0.72),
        "max_rebalance_per_round_frac": 0.08,
    })
    score_min = 75 + (idx % 2) * 5
    score_max = score_min + 9
    key = f"PRECISION_ACTIVE_{score_min}_{score_max}_FEE_EXCELLENT_p{idx}"
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=ProfileSubfamily.ORDERBOOK_GOOD_ACTIVE.value,
        action=action,
        regime=RegimeTag.RANGE_HIGH_VOL.value if idx % 2 else RegimeTag.BALANCED_RANGE.value,
        budget=budget,
        exposure=ExposureTier.LOW_BASE.value if idx % 3 == 0 else ExposureTier.TARGET_BASE.value,
        headroom=HeadroomTier.GOOD_HEADROOM.value,
        fee=FeeTier.FEE_EXCELLENT.value,
        score_min=score_min,
        score_max=score_max,
        risks=["NORMAL", "SAFE"],
        params=params,
        liq=LiquidityTier.LIQ_EXCELLENT.value,
        btc=BtcRiskTier.BTC_RISK_SUPPORTIVE.value if idx % 4 == 0 else BtcRiskTier.BTC_RISK_LOW.value,
        order=OrderRealityTier.ORDER_COMFORTABLE.value,
        hard_limits={"max_base_exposure_cap": 0.72},
        priority_boost=10,
    )


def _category_btc_risk(idx: int) -> Optional[ParamTemplate]:
    supportive = idx % 2 == 0
    if supportive:
        profile = ProfileFamily.ACTIVE_RANGE_GRID.value
        sub = ProfileSubfamily.BTC_SUPPORTIVE_ACTIVE.value
        action = FinalAction.ACTIVE_GRID.value
        btc = BtcRiskTier.BTC_RISK_SUPPORTIVE.value
        fee = FeeTier.FEE_GOOD.value
        params = D._base_params_for_profile(profile, BudgetTier.STANDARD.value)
    else:
        profile = ProfileFamily.DEFENSIVE_GRID.value
        sub = ProfileSubfamily.BTC_PRESSURE_DEFENSIVE.value
        action = FinalAction.DEFENSIVE_GRID.value if idx % 3 else FinalAction.WAIT.value
        btc = BtcRiskTier.BTC_RISK_HIGH.value
        fee = FeeTier.FEE_OK.value
        if action == FinalAction.WAIT.value:
            params = {"buy_grid_count": 0, "sell_grid_count": 0, "rebalance_policy": _rebalance_policy("none")}
        else:
            params = D._base_params_for_profile(profile, BudgetTier.STANDARD.value)
            params["buy_grid_count"] = 2

    key = f"BTC_{'SUPPORTIVE' if supportive else 'PRESSURE'}_p{idx}"
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=sub,
        action=action,
        regime=RegimeTag.BALANCED_RANGE.value,
        budget=BudgetTier.STANDARD.value,
        exposure=ExposureTier.TARGET_BASE.value,
        headroom=HeadroomTier.GOOD_HEADROOM.value,
        fee=fee,
        score_min=70 if supportive else 50,
        score_max=89 if supportive else 79,
        risks=["NORMAL", "SAFE"] if supportive else ["DEFENSIVE", "CAUTION"],
        params=params,
        btc=btc,
        liq=LiquidityTier.LIQ_GOOD.value,
    )


def _category_vol_protection(idx: int) -> Optional[ParamTemplate]:
    extreme = idx % 2 == 0
    sub = (
        ProfileSubfamily.VOL_EXTREME_SAFE_WAIT.value
        if extreme
        else ProfileSubfamily.BREAKOUT_RISK_PASSIVE.value
    )
    if extreme:
        profile = ProfileFamily.HIGH_VOL_PROTECTION.value
        action = FinalAction.WAIT.value
        params = {"buy_grid_count": 0, "sell_grid_count": 0, "rebalance_policy": _rebalance_policy("none")}
        vol = VolatilityTier.VOL_EXTREME.value
        regime = RegimeTag.HIGH_VOL_UNSTABLE.value
    else:
        profile = ProfileFamily.BREAKOUT_PROTECTION.value
        action = FinalAction.DEFENSIVE_GRID.value
        params = D._base_params_for_profile(profile, BudgetTier.STANDARD.value)
        params["buy_grid_count"] = 1
        vol = VolatilityTier.VOL_HIGH.value
        regime = RegimeTag.BREAKOUT_RISK.value

    key = f"VOL_{'EXTREME' if extreme else 'BREAKOUT'}_p{idx}"
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=sub,
        action=action,
        regime=regime,
        budget=BudgetTier.STANDARD.value,
        exposure=ExposureTier.TARGET_BASE.value,
        headroom=HeadroomTier.MEDIUM_HEADROOM.value,
        fee=FeeTier.FEE_OK.value,
        score_min=40,
        score_max=75,
        risks=["CAUTION", "DEFENSIVE", "NORMAL"],
        params=params,
        vol=vol,
    )


def _category_orderbook(idx: int) -> Optional[ParamTemplate]:
    tiers = [
        (OrderRealityTier.ORDER_TIGHT.value, ProfileSubfamily.ORDERBOOK_TIGHT_WAIT.value, FinalAction.WAIT.value),
        (OrderRealityTier.ORDER_TIGHT.value, None, FinalAction.SELL_MANAGEMENT_ONLY.value),
        (OrderRealityTier.ORDER_OK.value, None, FinalAction.BALANCED_GRID.value),
        (OrderRealityTier.ORDER_COMFORTABLE.value, ProfileSubfamily.ORDERBOOK_GOOD_ACTIVE.value, FinalAction.ACTIVE_GRID.value),
        (OrderRealityTier.ORDER_IMPOSSIBLE.value, ProfileSubfamily.ORDERBOOK_TIGHT_WAIT.value, FinalAction.NO_TRADE.value),
    ]
    order, sub, action = tiers[idx % len(tiers)]
    fee = FeeTier.FEE_WEAK.value if idx % 4 == 0 else FeeTier.FEE_OK.value
    budget = BudgetTier.SMALL.value if idx % 3 == 0 else BudgetTier.STANDARD.value

    if action == FinalAction.WAIT.value or action == FinalAction.NO_TRADE.value:
        profile = ProfileFamily.WAIT.value if action == FinalAction.WAIT.value else ProfileFamily.NO_TRADE.value
        params = {"buy_grid_count": 0, "sell_grid_count": 0, "rebalance_policy": _rebalance_policy("none")}
    elif action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        profile = ProfileFamily.SELL_MANAGEMENT_ONLY.value
        params = {"buy_grid_count": 0, "sell_grid_count": 2, "rebalance_policy": _rebalance_policy("none")}
    elif action == FinalAction.ACTIVE_GRID.value:
        profile = ProfileFamily.ACTIVE_RANGE_GRID.value
        params = D._base_params_for_profile(profile, budget)
    else:
        profile = ProfileFamily.BALANCED_GRID.value
        params = D._base_params_for_profile(profile, budget)

    key = f"ORDERBOOK_{order}_{action if isinstance(action, str) else action.value}_p{idx}"
    action_str = action if isinstance(action, str) else action.value
    return _build_template(
        template_key=key,
        profile=profile,
        subfamily=sub,
        action=action_str,
        regime=RegimeTag.BALANCED_RANGE.value,
        budget=budget,
        exposure=ExposureTier.TARGET_BASE.value,
        headroom=HeadroomTier.MEDIUM_HEADROOM.value if order == OrderRealityTier.ORDER_TIGHT.value else HeadroomTier.GOOD_HEADROOM.value,
        fee=fee,
        score_min=50 + (idx % 5) * 4,
        score_max=75 + (idx % 3) * 5,
        risks=["CAUTION", "NORMAL", "SAFE"],
        params=params,
        order=order,
        liq=LiquidityTier.LIQ_WEAK.value if order == OrderRealityTier.ORDER_TIGHT.value else LiquidityTier.LIQ_GOOD.value,
    )


_CATEGORY_BUILDERS = {
    "TREND_UP_INITIAL": _category_trend_up_initial,
    "TREND_DOWN_DEFENSIVE": _category_trend_down_defensive,
    "LOW_FEE_WIDE_GRID": _category_low_fee_wide,
    "SMALL_MICRO_BUDGET": _category_small_micro,
    "SELL_MGMT_OVEREXPOSED": _category_sell_overexposed,
    "REBALANCE": _category_rebalance,
    "HIGH_CONFIDENCE_ACTIVE": _category_high_confidence,
    "BTC_RISK": _category_btc_risk,
    "VOL_PROTECTION": _category_vol_protection,
    "ORDERBOOK_LIQUIDITY": _category_orderbook,
}


def _generate_category(category: str, target: int, existing_fps: Set[str]) -> List[ParamTemplate]:
    builder = _CATEGORY_BUILDERS[category]
    out: List[ParamTemplate] = []
    max_attempts = max(target * 2, target + 64)
    for idx in range(max_attempts):
        if len(out) >= target:
            break
        t = builder(idx)
        if t is None or not is_logically_valid_template(t):
            continue
        if t.template_key in existing_fps:
            continue
        existing_fps.add(t.template_key)
        out.append(t)
    return out


def generate_precision_expansion(
    target_count: int = PRECISION_EXPANSION_COUNT,
    *,
    existing_templates: Optional[Iterable[ParamTemplate]] = None,
) -> List[ParamTemplate]:
    """Generate precision expansion templates with category-based coverage."""
    existing_fps: Set[str] = set()
    if existing_templates:
        for t in existing_templates:
            existing_fps.add(t.template_key)

    pool: List[ParamTemplate] = []
    raw_total = sum(PRECISION_CATEGORY_TARGETS.values())
    scale = target_count / max(raw_total, 1)

    for category, raw_target in PRECISION_CATEGORY_TARGETS.items():
        adjusted = max(int(raw_target * scale), 1)
        batch = _generate_category(category, adjusted, existing_fps)
        pool.extend(batch)

    shortfall = target_count - len(pool)
    if shortfall > 0:
        pool.extend(_fill_precision_shortfall(shortfall, existing_fps))

    return pool[:target_count]


def _fill_precision_shortfall(
    shortfall: int,
    existing_fps: Set[str],
) -> List[ParamTemplate]:
    """Fill remaining precision slots via profile variants with v2 metadata."""
    from app.services.dynamic_param_score.param_pool.generator import generate_profile_variants

    filler_profiles = [
        ProfileFamily.INITIAL_ENTRY.value,
        ProfileFamily.LOW_FEE_WIDE_GRID.value,
        ProfileFamily.TREND_TRAILING.value,
        ProfileFamily.RECOVERY_SELL.value,
        ProfileFamily.SMALL_BUDGET_SAFE.value,
        ProfileFamily.CAUTIOUS_BALANCED_GRID.value,
        ProfileFamily.BALANCED_GRID.value,
        ProfileFamily.DEFENSIVE_GRID.value,
    ]
    out: List[ParamTemplate] = []
    serial = 0
    for profile in filler_profiles:
        need = shortfall - len(out)
        if need <= 0:
            break
        extras = generate_profile_variants(profile, need + 64)
        for t in extras:
            key = f"PREC2_{profile}_{serial}_{t.template_key}"
            serial += 1
            if key in existing_fps:
                continue
            subfamily = (
                ProfileSubfamily.PRECISION_INITIAL_ENTRY.value
                if profile == ProfileFamily.INITIAL_ENTRY.value
                else None
            )
            nt = t.model_copy(update={
                "template_key": key,
                "version": POOL_VERSION_V2,
                "profile_subfamily": subfamily,
                "notes": f"precision_fill:{profile}",
                "params": {**t.params, "precision_perturb": serial * 0.00017},
            })
            if not is_logically_valid_template(nt):
                continue
            fp = template_fingerprint(nt)
            if fp in existing_fps:
                continue
            existing_fps.add(fp)
            existing_fps.add(key)
            cov, prec, saf, comp, sel_pri = compute_quality_scores(nt, bucket_count=2, is_precision=False)
            nt = nt.model_copy(update={
                "coverage_score": cov,
                "precision_score": prec * 0.7,
                "safety_score": saf,
                "complexity_score": comp,
                "selection_priority": sel_pri,
            })
            out.append(nt)
            if len(out) >= shortfall:
                break
    return out[:shortfall]


def load_templates_from_jsonl(path: Path) -> List[ParamTemplate]:
    templates: List[ParamTemplate] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            templates.append(ParamTemplate.model_validate(json.loads(line)))
    return templates


def generate_pool_v2(
    target_count: int = POOL_TARGET_V2,
    *,
    base_templates: Optional[List[ParamTemplate]] = None,
    base_pool_path: Optional[Path] = None,
    expansion_mode: str = "precision_50k",
) -> List[ParamTemplate]:
    """Build v2 pool: base 50k + precision expansion to target_count."""
    if base_templates is None and base_pool_path and base_pool_path.exists():
        base_templates = load_templates_from_jsonl(base_pool_path)
    if base_templates is None:
        if target_count >= POOL_TARGET_V2:
            base_templates = _get_cached_base_pool()
        else:
            base_templates = generate_pool(min(max(target_count // 2, 500), POOL_TARGET_V1))

    for t in base_templates:
        if t.version != POOL_VERSION_V2:
            base_templates = [
                bt.model_copy(update={"version": POOL_VERSION_V2}) if bt.version != POOL_VERSION_V2 else bt
                for bt in base_templates
            ]
            break

    new_count = max(target_count - len(base_templates), 0)
    if expansion_mode == "precision_50k" and new_count > 0:
        precision = generate_precision_expansion(new_count, existing_templates=base_templates)
        pool = list(base_templates) + precision
    else:
        pool = list(base_templates)

    pool = _dedupe_pool(pool, target_count)
    pool = _ensure_unique_fingerprints(pool, target_count)
    pool = _normalize_sell_templates(pool)
    return pool[:target_count]


def _normalize_sell_templates(templates: List[ParamTemplate]) -> List[ParamTemplate]:
    out: List[ParamTemplate] = []
    for t in templates:
        if t.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
            hl = dict(t.hard_limits or {})
            hl.setdefault("requires_sell_min_notional", True)
            hl["requires_has_base"] = True
            t = t.model_copy(update={"requires_sellable_base": True, "hard_limits": hl})
        out.append(t)
    return out


def _ensure_unique_fingerprints(
    templates: List[ParamTemplate],
    target_count: int,
) -> List[ParamTemplate]:
    unique = list(templates)
    existing: Set[str] = {t.template_key for t in unique}
    for _ in range(4):
        by_fp: Dict[str, ParamTemplate] = {}
        for t in unique:
            fp = template_fingerprint(t)
            prev = by_fp.get(fp)
            if prev is None or (t.safety_score, t.selection_priority) > (prev.safety_score, prev.selection_priority):
                by_fp[fp] = t
        unique = list(by_fp.values())
        existing = {t.template_key for t in unique}
        shortfall = target_count - len(unique)
        if shortfall <= 0:
            break
        unique.extend(_fill_precision_shortfall(shortfall, existing))
    unique.sort(key=lambda x: (-x.selection_priority, -x.priority, x.template_key))
    return unique[:target_count]


def _dedupe_pool(templates: List[ParamTemplate], target_count: int) -> List[ParamTemplate]:
    by_key: Dict[str, ParamTemplate] = {}
    for t in templates:
        cur = by_key.get(t.template_key)
        if cur is None or (t.safety_score, t.selection_priority) > (cur.safety_score, cur.selection_priority):
            by_key[t.template_key] = t

    result = list(by_key.values())
    result.sort(key=lambda x: (-x.selection_priority, -x.priority, x.template_key))
    return result[:target_count]
