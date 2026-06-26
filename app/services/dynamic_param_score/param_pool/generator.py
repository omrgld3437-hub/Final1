"""Deterministic param template pool generator — scales to 50k+ templates."""

from __future__ import annotations

from itertools import product
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from app.services.dynamic_param_score.models import FinalAction, RegimeTag
from app.services.dynamic_param_score.param_pool import defaults as D
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
    VolatilityTier,
)

POOL_TARGET_V1 = 50_000

PROFILE_TARGETS: Dict[str, int] = {
    ProfileFamily.NO_TRADE.value: 2_000,
    ProfileFamily.WAIT.value: 3_000,
    ProfileFamily.SELL_MANAGEMENT_ONLY.value: 5_000,
    ProfileFamily.RECOVERY_SELL.value: 3_000,
    ProfileFamily.ULTRA_DEFENSIVE_GRID.value: 3_000,
    ProfileFamily.DEFENSIVE_GRID.value: 5_000,
    ProfileFamily.CAUTIOUS_BALANCED_GRID.value: 6_000,
    ProfileFamily.BALANCED_GRID.value: 6_000,
    ProfileFamily.LOW_FEE_WIDE_GRID.value: 5_000,
    ProfileFamily.ACTIVE_RANGE_GRID.value: 4_000,
    ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value: 1_500,
    ProfileFamily.TREND_TRAILING.value: 2_500,
    ProfileFamily.BREAKOUT_PROTECTION.value: 1_500,
    ProfileFamily.HIGH_VOL_PROTECTION.value: 1_500,
    ProfileFamily.LOW_LIQUIDITY_WAIT.value: 1_000,
    ProfileFamily.INITIAL_ENTRY.value: 1_500,
    ProfileFamily.SMALL_BUDGET_SAFE.value: 2_000,
    ProfileFamily.MICRO_BUDGET_WAIT.value: 1_000,
    ProfileFamily.OVEREXPOSED_REDUCTION.value: 1_000,
}

_ALL_LIQ = [t.value for t in LiquidityTier]
_ALL_VOL = [t.value for t in VolatilityTier]
_ALL_BTC = [t.value for t in BtcRiskTier]
_ALL_ORDER = [t.value for t in OrderRealityTier]

_EXTRA_PROFILE_CONFIG: Dict[str, dict] = {
    ProfileFamily.INITIAL_ENTRY.value: {
        "regimes": [RegimeTag.BALANCED_RANGE.value, RegimeTag.RANGE_LOW_VOL.value, RegimeTag.TRENDING_UP.value],
        "budgets": [BudgetTier.SMALL.value, BudgetTier.STANDARD.value, BudgetTier.MEDIUM.value],
        "exposures": [ExposureTier.NO_BASE.value, ExposureTier.LOW_BASE.value],
        "headrooms": [HeadroomTier.MEDIUM_HEADROOM.value, HeadroomTier.GOOD_HEADROOM.value],
        "fees": [FeeTier.FEE_OK.value, FeeTier.FEE_GOOD.value, FeeTier.FEE_EXCELLENT.value],
        "score_ranges": [(55, 79), (60, 74)],
        "risks": ["NORMAL", "SAFE", "CAUTION"],
        "action": FinalAction.BALANCED_GRID.value,
        "params_fn": lambda b: {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.20,
            "base_alloc_max": 0.35,
            "buy_grid_count": 2 if b == BudgetTier.SMALL.value else 3,
            "sell_grid_count": 2,
            "buy_spacing_atr_mult": 0.95,
            "sell_spacing_atr_mult": 0.85,
            "buy_spacing_min_pct": 0.50,
            "sell_spacing_min_pct": 0.45,
            "max_quote_to_spend_per_buy_frac": 0.25,
            "max_base_exposure_extra": 0.08,
            "max_base_exposure_cap": 0.45,
            "rebuy_enabled": True,
            "resell_enabled": True,
        },
    },
    ProfileFamily.SMALL_BUDGET_SAFE.value: {
        "regimes": [RegimeTag.BALANCED_RANGE.value, RegimeTag.RANGE_LOW_VOL.value],
        "budgets": [BudgetTier.SMALL.value, BudgetTier.MICRO.value],
        "exposures": [ExposureTier.NO_BASE.value, ExposureTier.LOW_BASE.value, ExposureTier.TARGET_BASE.value],
        "headrooms": [HeadroomTier.MEDIUM_HEADROOM.value, HeadroomTier.GOOD_HEADROOM.value],
        "fees": [FeeTier.FEE_OK.value, FeeTier.FEE_GOOD.value],
        "score_ranges": [(50, 69), (55, 74)],
        "risks": ["CAUTION", "NORMAL", "SAFE"],
        "action": FinalAction.BALANCED_GRID.value,
        "params_fn": lambda b: {
            "base_alloc_mode": "scale",
            "base_alloc_min": 0.28,
            "base_alloc_max": 0.42,
            "buy_grid_count": 2,
            "sell_grid_count": 2,
            "buy_spacing_atr_mult": 1.0,
            "sell_spacing_atr_mult": 0.90,
            "buy_spacing_min_pct": 0.50,
            "sell_spacing_min_pct": 0.45,
            "max_quote_to_spend_per_buy_frac": 0.22,
            "max_base_exposure_extra": 0.06,
            "max_base_exposure_cap": 0.50,
            "rebuy_enabled": True,
            "resell_enabled": True,
        },
    },
    ProfileFamily.MICRO_BUDGET_WAIT.value: {
        "regimes": [RegimeTag.BALANCED_RANGE.value, RegimeTag.RANGE_LOW_VOL.value, RegimeTag.HIGH_VOL_UNSTABLE.value],
        "budgets": [BudgetTier.NANO.value, BudgetTier.MICRO.value],
        "exposures": [e.value for e in ExposureTier],
        "headrooms": [h.value for h in HeadroomTier],
        "fees": [f.value for f in FeeTier],
        "score_ranges": [(20, 59), (40, 69)],
        "risks": ["BLOCKED", "DEFENSIVE", "CAUTION", "NORMAL"],
        "action": FinalAction.WAIT.value,
        "params_fn": lambda b: {
            "buy_grid_count": 0,
            "sell_grid_count": 0,
            "cancel_existing_buy_orders": True,
            "cancel_existing_sell_orders": False,
        },
    },
    ProfileFamily.OVEREXPOSED_REDUCTION.value: {
        "regimes": [
            RegimeTag.BALANCED_RANGE.value,
            RegimeTag.RANGE_HIGH_VOL.value,
            RegimeTag.TRENDING_DOWN.value,
        ],
        "budgets": [b.value for b in BudgetTier if b != BudgetTier.NANO],
        "exposures": [ExposureTier.OVEREXPOSED.value, ExposureTier.HIGH_BASE.value],
        "headrooms": [h.value for h in HeadroomTier],
        "fees": [f.value for f in FeeTier],
        "score_ranges": [(30, 100), (40, 80)],
        "risks": ["DEFENSIVE", "CAUTION", "NORMAL"],
        "action": FinalAction.SELL_MANAGEMENT_ONLY.value,
        "params_fn": lambda b: {
            "base_alloc_mode": "current_aware",
            "base_alloc_frac": 0.75,
            "buy_grid_count": 0,
            "sell_grid_count": 3 if b in (BudgetTier.SMALL.value, BudgetTier.MICRO.value) else 4,
            "sell_spacing_atr_mult": 0.85,
            "sell_spacing_min_pct": 0.50,
            "rebuy_enabled": False,
            "resell_enabled": True,
            "buy_disabled": True,
            "sell_only_mode": True,
            "cancel_existing_buy_orders": True,
        },
    },
}


def is_logically_valid_template(template: ParamTemplate) -> bool:
    buy_n = int(template.params.get("buy_grid_count") or 0)
    sell_n = int(template.params.get("sell_grid_count") or 0)
    fee_bad = FeeTier.FEE_BAD.value in template.fee_tiers and len(template.fee_tiers) == 1
    fee_weak_only = template.fee_tiers == [FeeTier.FEE_WEAK.value]

    active_profiles = {
        ProfileFamily.ACTIVE_RANGE_GRID.value,
        ProfileFamily.HIGH_CONFIDENCE_ACTIVE_GRID.value,
    }

    if template.profile_family in active_profiles:
        if fee_bad or fee_weak_only:
            return False
        if not any(f in template.fee_tiers for f in (FeeTier.FEE_GOOD.value, FeeTier.FEE_EXCELLENT.value)):
            return False

    if HeadroomTier.NO_HEADROOM.value in template.headroom_tiers and len(template.headroom_tiers) == 1:
        if buy_n > 0:
            return False

    if ExposureTier.OVEREXPOSED.value in template.exposure_tiers and len(template.exposure_tiers) == 1:
        if buy_n > 0 and template.profile_family not in (
            ProfileFamily.RECOVERY_SELL.value,
            ProfileFamily.OVEREXPOSED_REDUCTION.value,
        ):
            return False

    if RegimeTag.DUMP_RISK.value in template.supported_regimes:
        if buy_n > 0 or sell_n > 0:
            if template.final_action not in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
                return False

    if RegimeTag.LOW_LIQUIDITY.value in template.supported_regimes:
        if template.profile_family in active_profiles:
            return False

    if template.final_action in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value):
        if buy_n > 0 or sell_n > 0:
            return False

    if fee_bad and template.final_action in (
        FinalAction.WAIT.value,
        FinalAction.SAFE_WAIT.value,
    ):
        return False

    if template.final_action == FinalAction.SELL_MANAGEMENT_ONLY.value:
        if buy_n > 0:
            return False
        if template.params.get("rebuy_enabled") is True:
            return False

    if fee_bad and buy_n > 0 and template.profile_family not in (
        ProfileFamily.LOW_FEE_WIDE_GRID.value,
        ProfileFamily.ACTIVE_DEFENSIVE_GRID.value,
    ):
        spacing_min = float(template.params.get("buy_spacing_min_pct") or 0)
        if spacing_min < 1.0 and template.profile_family not in (
            ProfileFamily.LOW_FEE_WIDE_GRID.value,
            ProfileFamily.ACTIVE_DEFENSIVE_GRID.value,
        ):
            return False

    if BudgetTier.NANO.value in template.budget_tiers and len(template.budget_tiers) == 1:
        if buy_n > 1:
            return False
        if template.final_action in (FinalAction.ACTIVE_GRID.value, FinalAction.BALANCED_GRID.value):
            if buy_n > 0:
                return False

    return True


def _tier_variants(values: Sequence[str], idx: int, span: int = 3) -> List[str]:
    if not values:
        return []
    if len(values) <= span:
        return [values[idx % len(values)]]
    start = idx % len(values)
    picked = [values[start]]
    if start + 1 < len(values):
        picked.append(values[start + 1])
    return picked


def _make_variant_template(
    profile: str,
    regime: str,
    budget: str,
    exposure: str,
    headroom: str,
    fee: str,
    score_min: int,
    score_max: int,
    risk_states: Sequence[str],
    variant_idx: int,
    *,
    liq: str = "",
    vol: str = "",
    btc: str = "",
    order: str = "",
) -> ParamTemplate:
    if profile in _EXTRA_PROFILE_CONFIG:
        cfg = _EXTRA_PROFILE_CONFIG[profile]
        params = cfg["params_fn"](budget)
        action = cfg["action"]
    else:
        params = D._base_params_for_profile(profile, budget)
        action = D._PROFILE_ACTION[profile]
    if "rebalance_policy" not in params:
        params = {**params, "rebalance_policy": D._default_rebalance_policy(profile)}

    suffix = f"v{variant_idx}"
    key_parts = [
        regime,
        budget,
        f"{score_min}_{score_max}",
        profile.replace("_PROFILE", "").replace("_GRID", ""),
    ]
    if exposure != ExposureTier.TARGET_BASE.value:
        key_parts.append(exposure)
    if headroom:
        key_parts.append(headroom)
    if fee and fee not in (FeeTier.FEE_OK.value,):
        key_parts.append(fee)
    key_parts.append(suffix)
    template_key = "_".join(key_parts)

    eq_min, eq_max = D._BUDGET_EQUITY[budget]
    hard_limits = D._hard_limits_for_profile(profile)
    mn_mult = 10.0 if budget in (BudgetTier.NANO.value, BudgetTier.MICRO.value, BudgetTier.SMALL.value) else 20.0

    deployable = action not in (FinalAction.NO_TRADE.value, FinalAction.WAIT.value)
    allows_buy = int(params.get("buy_grid_count") or 0) > 0
    allows_sell = int(params.get("sell_grid_count") or 0) > 0
    requires_sellable_base = action == FinalAction.SELL_MANAGEMENT_ONLY.value

    quality = D._priority_for_profile(profile, score_min) / 100.0

    return ParamTemplate(
        template_key=template_key,
        version=D.POOL_VERSION_ID,
        profile_family=profile,
        final_action=action,
        supported_regimes=[regime],
        allowed_risk_states=list(risk_states),
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
        min_headroom_multiple=0.0,
        params=params,
        hard_limits=hard_limits,
        priority=D._priority_for_profile(profile, score_min),
        validation_quality_score=quality,
        deployable=deployable,
        requires_sellable_base=requires_sellable_base,
        allows_buy_grid=allows_buy,
        allows_sell_grid=allows_sell,
        status="active",
    )


def _profile_dimensions(profile: str) -> dict:
    if profile in _EXTRA_PROFILE_CONFIG:
        return _EXTRA_PROFILE_CONFIG[profile]
    return {
        "regimes": D._PROFILE_REGIMES.get(profile, [RegimeTag.BALANCED_RANGE.value]),
        "budgets": D._PROFILE_BUDGETS.get(profile, [BudgetTier.STANDARD.value]),
        "exposures": D._PROFILE_EXPOSURE.get(profile, [ExposureTier.TARGET_BASE.value]),
        "headrooms": D._PROFILE_HEADROOM.get(profile, [h.value for h in HeadroomTier]),
        "fees": D._PROFILE_FEE.get(profile, [f.value for f in FeeTier]),
        "score_ranges": D._PROFILE_SCORE_RANGES.get(profile, [(50, 69)]),
        "risks": D._PROFILE_RISK.get(profile, ["CAUTION", "NORMAL", "SAFE", "DEFENSIVE"]),
    }


def generate_profile_variants(profile: str, target: int) -> List[ParamTemplate]:
    dims = _profile_dimensions(profile)
    regimes = dims["regimes"]
    budgets = dims["budgets"]
    exposures = dims["exposures"]
    headrooms = dims["headrooms"]
    fees = dims["fees"]
    score_ranges = dims["score_ranges"]
    risks = dims["risks"]

    templates: List[ParamTemplate] = []
    variant_idx = 0
    max_attempts = target * 25

    while len(templates) < target and variant_idx < max_attempts:
        regime = regimes[variant_idx % len(regimes)]
        budget = budgets[(variant_idx // len(regimes)) % len(budgets)]
        score_min, score_max = score_ranges[(variant_idx // (len(regimes) * len(budgets))) % len(score_ranges)]
        exposure = exposures[(variant_idx // max(len(regimes) * len(budgets), 1)) % len(exposures)]
        headroom = headrooms[(variant_idx // max(len(exposures), 1)) % len(headrooms)]
        fee = fees[variant_idx % len(fees)]
        liq = _ALL_LIQ[variant_idx % len(_ALL_LIQ)]
        vol = _ALL_VOL[(variant_idx // 3) % len(_ALL_VOL)]
        btc = _ALL_BTC[(variant_idx // 5) % len(_ALL_BTC)]
        order = _ALL_ORDER[(variant_idx // 7) % len(_ALL_ORDER)]

        t = _make_variant_template(
            profile, regime, budget, exposure, headroom, fee,
            score_min, score_max, risks, variant_idx,
            liq=liq, vol=vol, btc=btc, order=order,
        )
        variant_idx += 1
        if not is_logically_valid_template(t):
            continue
        templates.append(t)

    return templates[:target]


def _dedupe_and_trim(
    templates: Iterable[ParamTemplate],
    target_count: int,
    pinned_keys: Set[str],
) -> List[ParamTemplate]:
    by_key: Dict[str, ParamTemplate] = {}
    pinned: List[ParamTemplate] = []
    rest: List[ParamTemplate] = []

    for t in templates:
        if t.template_key in by_key:
            existing = by_key[t.template_key]
            if t.priority > existing.priority or (
                t.priority == existing.priority
                and t.validation_quality_score > existing.validation_quality_score
            ):
                by_key[t.template_key] = t
            continue
        by_key[t.template_key] = t

    for t in by_key.values():
        if t.template_key in pinned_keys:
            pinned.append(t)
        else:
            rest.append(t)

    rest.sort(
        key=lambda x: (-x.priority, -x.validation_quality_score, x.template_key),
    )
    slots = max(target_count - len(pinned), 0)
    return pinned + rest[:slots]


REQUIRED_COVERAGE_KEYS: Tuple[str, ...] = (
    "BALANCED_RANGE_60_69_FEE_BAD_WAIT",
    "BALANCED_RANGE_60_69_FEE_BAD_SELL_MANAGEMENT",
    "BALANCED_RANGE_60_69_FEE_WEAK_WIDE_GRID",
    "DUMP_RISK_ANY_NO_TRADE",
    "OVEREXPOSED_ANY_RECOVERY_SELL",
    "BALANCED_RANGE_SMALL_60_69_SELL_MANAGEMENT",
    "RANGE_HIGH_VOL_70_89_ACTIVE_GOOD_FEE",
)


def assert_required_coverage(templates: List[ParamTemplate]) -> None:
    keys = {t.template_key for t in templates if t.status == "active"}
    missing = [k for k in REQUIRED_COVERAGE_KEYS if k not in keys]
    if missing:
        raise ValueError(f"Required coverage templates missing: {missing}")


def generate_pool(target_count: int = POOL_TARGET_V1) -> List[ParamTemplate]:
    """Generate full param template pool with pinned coverage + profile variants."""
    pinned = D._pinned_templates()
    pinned_keys = {t.template_key for t in pinned}
    pool: List[ParamTemplate] = list(pinned)

    raw_total = sum(PROFILE_TARGETS.values())
    scale = target_count / max(raw_total, 1)

    for profile, raw_target in PROFILE_TARGETS.items():
        adjusted = max(int(raw_target * scale), 1)
        if profile in {t.profile_family for t in pinned}:
            adjusted = max(adjusted - sum(1 for t in pinned if t.profile_family == profile), 0)
        if adjusted <= 0:
            continue
        variants = generate_profile_variants(profile, adjusted)
        for t in variants:
            if t.template_key not in pinned_keys:
                pool.append(t)
                pinned_keys.add(t.template_key)

    pool = _dedupe_and_trim(pool, target_count, {t.template_key for t in pinned})
    assert_required_coverage(pool)

    existing = {t.template_key for t in pool}
    filler_profiles = [
        ProfileFamily.WAIT.value,
        ProfileFamily.CAUTIOUS_BALANCED_GRID.value,
        ProfileFamily.BALANCED_GRID.value,
        ProfileFamily.DEFENSIVE_GRID.value,
    ]
    fill_idx = 0
    safety = 0
    while len(pool) < target_count and safety < target_count * 3:
        profile = filler_profiles[fill_idx % len(filler_profiles)]
        need = target_count - len(pool)
        extras = generate_profile_variants(profile, need + 100)
        for t in extras:
            if t.template_key in existing:
                t = t.model_copy(update={"template_key": f"{t.template_key}_fill{len(pool)}"})
            pool.append(t)
            existing.add(t.template_key)
            if len(pool) >= target_count:
                break
        fill_idx += 1
        safety += 1

    return pool[:target_count]
