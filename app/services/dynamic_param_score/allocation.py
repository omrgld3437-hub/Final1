"""Target Allocation Layer — hedef portföy oranı ve drift (emir üretmez)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.services.dynamic_param_score.models import BotParams, PortfolioState
from app.services.dynamic_param_score.rebalance import calculate_allocation_drift


@dataclass
class TargetAllocation:
    target_base_frac: float
    target_quote_frac: float
    current_base_frac: float
    current_quote_frac: float
    allocation_drift_frac: float
    allocation_drift_abs_frac: float
    required_quote_usdt: float
    required_base_usdt: float

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_target_allocation(
    params: BotParams,
    portfolio: PortfolioState,
) -> TargetAllocation:
    """Template/renderer çıktısından hedef oran; mevcut portföyle drift."""
    target_base = max(float(params.base_alloc_frac or 0.0), 0.0)
    target_quote = max(float(params.quote_alloc_frac or 0.0), 0.0)
    if target_base + target_quote <= 0:
        target_base = 0.5
        target_quote = 0.5
    else:
        total = target_base + target_quote
        target_base /= total
        target_quote /= total

    current_base = max(float(portfolio.current_base_exposure_frac or 0.0), 0.0)
    current_quote = max(1.0 - current_base, 0.0)
    drift = calculate_allocation_drift(
        current_base,
        target_base,
        portfolio.total_equity_usdt,
    )

    return TargetAllocation(
        target_base_frac=round(target_base, 6),
        target_quote_frac=round(target_quote, 6),
        current_base_frac=drift["current_base_frac"],
        current_quote_frac=round(current_quote, 6),
        allocation_drift_frac=drift["drift_frac"],
        allocation_drift_abs_frac=drift["drift_abs_frac"],
        required_quote_usdt=drift["required_quote_usdt"],
        required_base_usdt=drift["required_base_usdt"],
    )
