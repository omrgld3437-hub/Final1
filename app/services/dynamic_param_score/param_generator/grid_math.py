"""Grid distance math for DPS Engine V2."""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.services.dynamic_param_score.param_generator.feature_bins import AssetClass

# Global minimum grid rules per asset class (V4 shelf A1–A7)
ASSET_MIN_GRID: dict[str, float] = {
    "BTC_ETH_MAJOR": 1.20,
    "LARGE_CAP_LIQUID": 1.40,
    "MID_CAP": 1.70,
    "MID_CAP_NORMAL": 1.70,
    "HIGH_VOL_ALT": 2.20,
    "MEME_HIGH_RISK": 2.80,
    "LOW_LIQUIDITY": 3.20,
    "NEW_LISTING_OR_ABNORMAL": 3.50,
}

MIN_GRID_SPACING: dict[str, float] = {
    "BTC_ETH_MAJOR": 1.20,
    "LARGE_CAP_LIQUID": 1.20,
    "MID_CAP": 1.50,
    "HIGH_VOL_ALT": 1.50,
    "MEME_HIGH_RISK": 2.00,
    "LOW_LIQUIDITY": 2.00,
}

MIN_NET_ROOM: dict[str, float] = {
    "BTC_ETH_MAJOR": 1.00,
    "LARGE_CAP_LIQUID": 1.10,
    "MID_CAP": 1.20,
    "MID_CAP_NORMAL": 1.20,
    "HIGH_VOL_ALT": 1.50,
    "MEME_HIGH_RISK": 1.80,
    "LOW_LIQUIDITY": 2.00,
    "NEW_LISTING_OR_ABNORMAL": 2.20,
}

MAX_TRAILING_FRAC: dict[str, float] = {
    "BTC_ETH_MAJOR": 0.30,
    "LARGE_CAP_LIQUID": 0.30,
    "MID_CAP": 0.28,
    "HIGH_VOL_ALT": 0.28,
    "MEME_HIGH_RISK": 0.25,
    "LOW_LIQUIDITY": 0.25,
}

REGIME_MULTIPLIER: dict[str, float] = {
    "CALM_RANGE": 1.2,
    "BALANCED_RANGE": 1.4,
    "VOLATILE_RANGE": 1.8,
    "CHOPPY_RANGE": 2.2,
    "WEAK_DOWNTREND_RANGE": 1.8,
    "STRONG_DOWNTREND_RISK": 1.8,
    "WEAK_UPTREND_RANGE": 1.5,
    "STRONG_UPTREND_RISK": 1.5,
    "BREAKOUT_RISK": 2.0,
    "CRASH_RISK": 2.8,
    "RECOVERY_RANGE": 1.6,
    "LIQUIDITY_THIN_RANGE": 2.2,
}

GRID_MULTIPLIER_RANGES: dict[int, Tuple[Tuple[float, float], ...]] = {
    2: ((1.0, 1.0), (2.3, 2.8)),
    3: ((1.0, 1.0), (2.2, 2.6), (4.5, 5.5)),
    4: ((1.0, 1.0), (2.0, 2.4), (4.0, 5.0), (7.0, 9.0)),
}


def _asset_min(asset_class: str) -> float:
    return ASSET_MIN_GRID.get(asset_class, 1.80)


def compute_first_grid_pct(
    *,
    asset_class: str,
    regime: str,
    atr_1h_pct: float,
    trailing_pct: float,
    total_cost_pct: float,
    bb_width_factor: float = 0.0,
    drawdown_factor: float = 0.0,
    volatility_percentile_factor: float = 0.0,
    atr_5m_micro_adj: float = 0.0,
) -> float:
    """Primary grid distance from ATR 1h and market structure."""
    asset_min = _asset_min(asset_class)
    regime_mult = REGIME_MULTIPLIER.get(regime, 1.4)
    atr_component = max(float(atr_1h_pct or 0.0), 0.1) * regime_mult
    trailing_component = max(float(trailing_pct or 0.0), 0.1) * 3.5
    cost_component = max(float(total_cost_pct or 0.0), 0.0) * 6.0

    first = max(
        asset_min,
        atr_component,
        trailing_component,
        cost_component,
        float(bb_width_factor or 0.0),
        float(drawdown_factor or 0.0),
        float(volatility_percentile_factor or 0.0),
    )
    if atr_5m_micro_adj:
        first *= 1.0 + max(-0.05, min(0.08, float(atr_5m_micro_adj)))
    return round(max(first, 1.0), 4)


def compute_grid_ladder(
    first_grid: float,
    grid_count: int,
    *,
    variant_idx: int = 0,
) -> List[float]:
    """Build geometric grid ladder from first grid distance."""
    n = max(1, min(4, int(grid_count)))
    ranges = GRID_MULTIPLIER_RANGES.get(n, GRID_MULTIPLIER_RANGES[3])
    out: List[float] = []
    for i, (lo, hi) in enumerate(ranges):
        if i == 0:
            out.append(round(max(first_grid, 1.0), 4))
            continue
        span = hi - lo
        t = (variant_idx % 7) / 6.0 if span > 0 else 0.5
        mult = lo + span * t
        out.append(round(max(first_grid * mult, out[-1] + 0.5), 4))
    return out


def apply_side_structure_multiplier(
    grids: List[float],
    *,
    side: str,
    structure: str,
    fee_class: str = "normal_fee",
) -> List[float]:
    """Widen buy/sell grids based on market structure and fee class."""
    mult = 1.0
    if structure == "lower_lows_only" and side == "buy":
        mult += 0.25
    elif structure == "higher_highs_only" and side == "sell":
        mult += 0.25
    elif structure == "both":
        mult += 0.18
    if fee_class == "fee_bad":
        mult += 0.12
    return [round(g * mult, 4) for g in grids]


def compute_trailing_pct(
    first_grid: float,
    asset_class: str,
    *,
    fee_class: str = "normal_fee",
) -> float:
    max_frac = MAX_TRAILING_FRAC.get(asset_class, 0.28)
    base = first_grid * (0.22 if fee_class == "fee_bad" else 0.26)
    return round(min(base, first_grid * max_frac), 4)


def enforce_grid_spacing_minimums(grids: List[float], asset_class: str) -> List[float]:
    """Ensure inter-grid spacing meets asset-class minimums."""
    if not grids:
        return grids
    min_spacing = MIN_GRID_SPACING.get(asset_class, 1.50)
    out = [max(grids[0], _asset_min(asset_class))]
    for g in grids[1:]:
        out.append(max(g, out[-1] + min_spacing))
    return [round(x, 4) for x in out]
