"""Geometric amount distribution for grid levels."""

from __future__ import annotations

from typing import List, Literal

DistributionMode = Literal["normal", "defensive", "aggressive"]

# Spec-compliant geometric distributions (percent, sum=100)
DISTRIBUTIONS: dict[int, dict[DistributionMode, List[int]]] = {
    2: {
        "normal": [35, 65],
        "defensive": [30, 70],
        "aggressive": [40, 60],
    },
    3: {
        "normal": [15, 30, 55],
        "defensive": [12, 28, 60],
        "aggressive": [20, 30, 50],
    },
    4: {
        "normal": [10, 20, 30, 40],
        "defensive": [8, 17, 30, 45],
        "aggressive": [12, 23, 30, 35],
    },
    5: {
        "normal": [7, 13, 20, 25, 35],
        "defensive": [6, 12, 18, 24, 40],
        "aggressive": [9, 15, 22, 26, 28],
    },
}


def select_distribution_mode(
    *,
    risk_level: str = "NORMAL",
    volatility_percentile: float = 50.0,
    fee_class: str = "normal_fee",
    structure: str = "neither",
) -> DistributionMode:
    if risk_level in ("DEFENSIVE", "CAUTION") or fee_class == "fee_bad":
        return "defensive"
    if risk_level == "SAFE" or volatility_percentile < 20:
        return "defensive"
    if risk_level in ("ACTIVE", "HIGH_CONFIDENCE") and volatility_percentile > 60:
        return "aggressive"
    if structure in ("both", "lower_lows_only", "higher_highs_only"):
        return "defensive"
    return "normal"


def geometric_distribution(
    grid_count: int,
    mode: DistributionMode = "normal",
) -> List[float]:
    """Return fractional weights summing to 1.0."""
    n = max(1, min(5, int(grid_count)))
    if n == 1:
        return [1.0]
    pct = DISTRIBUTIONS.get(n, DISTRIBUTIONS[3]).get(mode, DISTRIBUTIONS[n]["normal"])
    total = float(sum(pct))
    return [round(p / total, 4) for p in pct]
