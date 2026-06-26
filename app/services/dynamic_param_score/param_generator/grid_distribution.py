"""Grid quantity distribution and trailing normalization for V4."""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.services.dynamic_param_score.distribution_policy import (
    DistributionContext,
    distribution_context_from_mapping,
    is_buy_distribution_valid,
    is_three_grid_distribution_valid,
    is_two_grid_distribution_valid,
    normalize_distribution_for_context,
    resolve_side_distribution,
    trim_side_distribution_for_context,
    TWO_GRID_DEFENSIVE,
    TWO_GRID_NORMAL,
    THREE_GRID_DEFENSIVE,
    THREE_GRID_NORMAL,
)

# Backward-compatible aliases
DEFENSIVE_TWO_GRID = TWO_GRID_DEFENSIVE
STANDARD_TWO_GRID = TWO_GRID_NORMAL
DEFENSIVE_THREE_GRID = THREE_GRID_DEFENSIVE
STANDARD_THREE_GRID = THREE_GRID_NORMAL

MAX_TRAILING_FRAC = 0.30

DEFENSIVE_FIRST_GRID_MAX_PCT = 18
DEFENSIVE_LAST_GRID_MIN_PCT = 50
DEFENSIVE_MIN_SPREAD_PCT = 30
DEFENSIVE_TWO_FIRST_MAX_PCT = 35
DEFENSIVE_TWO_SECOND_MIN_PCT = 65


def _ctx_from_defensive(defensive: bool) -> DistributionContext:
    if defensive:
        return DistributionContext(risk_state="DEFENSIVE")
    return DistributionContext(risk_state="NORMAL")


def is_defensive_distribution_valid(
    dist: List,
    *,
    grid_count: int,
    ctx: Optional[DistributionContext] = None,
) -> bool:
    """True when buy/sell weights satisfy policy invariants."""
    if not dist or grid_count <= 0:
        return True
    c = ctx or DistributionContext(risk_state="DEFENSIVE")
    ok, _ = is_buy_distribution_valid(dist, grid_count=grid_count, ctx=c)
    return ok


def trim_side_distribution(
    dist: List,
    n: int,
    *,
    defensive: bool = False,
    ctx: Optional[DistributionContext] = None,
) -> List[int]:
    """Trim ladder weights; uses market context when provided."""
    context = ctx or _ctx_from_defensive(defensive)
    return trim_side_distribution_for_context(dist, n, context)


def normalize_side_distribution(
    dist: List[int],
    *,
    defensive: bool = False,
    ctx: Optional[DistributionContext] = None,
) -> Tuple[List[int], bool]:
    """Fix forbidden splits. Returns (dist, changed)."""
    if not dist:
        return dist, False
    context = ctx or _ctx_from_defensive(defensive)
    n = len(_to_percent_ints(dist))
    fixed, changed = normalize_distribution_for_context(dist, n, context)
    return fixed, changed


def _to_percent_ints(dist: List) -> List[int]:
    if not dist:
        return []
    vals = [float(x) for x in dist]
    if max(vals) <= 1.0 + 1e-9:
        vals = [v * 100.0 for v in vals]
    total = sum(vals) or 100.0
    if abs(total - 100.0) > 1.0 and total > 0:
        vals = [v * 100.0 / total for v in vals]
    scaled = [int(round(v)) for v in vals]
    drift = 100 - sum(scaled)
    if drift and scaled:
        idx = max(range(len(scaled)), key=lambda i: scaled[i])
        scaled[idx] += drift
    return scaled


def cap_trailing_pct(trailing_pct: float, first_grid_pct: float) -> float:
    if first_grid_pct <= 0:
        return 0.0
    cap = first_grid_pct * MAX_TRAILING_FRAC
    return round(min(max(float(trailing_pct or 0.0), 0.0), cap), 4)


def trailing_too_large(trailing_pct: float, first_grid_pct: float) -> bool:
    if first_grid_pct <= 0:
        return False
    return float(trailing_pct or 0.0) > first_grid_pct * MAX_TRAILING_FRAC + 1e-6


__all__ = [
    "DEFENSIVE_TWO_GRID",
    "STANDARD_TWO_GRID",
    "DEFENSIVE_THREE_GRID",
    "STANDARD_THREE_GRID",
    "DistributionContext",
    "distribution_context_from_mapping",
    "is_defensive_distribution_valid",
    "is_two_grid_distribution_valid",
    "is_three_grid_distribution_valid",
    "normalize_side_distribution",
    "trim_side_distribution",
    "resolve_side_distribution",
    "cap_trailing_pct",
    "trailing_too_large",
]
