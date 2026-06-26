"""Scenario coverage matrix for DPS Engine V2 parameter generation."""

from __future__ import annotations

from itertools import product
from typing import Any, Dict, Iterator, List

from app.services.dynamic_param_score.param_generator.feature_bins import (
    ASSET_CLASSES,
    BUDGET_CLASSES,
    FEE_CLASSES,
    REGIME_CLASSES,
    STRUCTURES,
    VOLATILITY_BINS,
)

# Primary coverage dimensions — ensures no scenario gaps
PRIMARY_DIMS = (
    ASSET_CLASSES,
    BUDGET_CLASSES,
    REGIME_CLASSES,
    VOLATILITY_BINS,
    STRUCTURES,
    FEE_CLASSES,
)


def scenario_cells() -> Iterator[Dict[str, str]]:
    """Yield all primary scenario combinations for coverage map."""
    for asset, budget, regime, vol, structure, fee in product(*PRIMARY_DIMS):
        yield {
            "asset_class": asset,
            "budget_class": budget,
            "regime": regime,
            "volatility_bin": vol,
            "structure": structure,
            "fee_class": fee,
        }


def scenario_key(cell: Dict[str, str]) -> str:
    return "|".join(
        cell.get(k, "")
        for k in (
            "asset_class",
            "budget_class",
            "regime",
            "volatility_bin",
            "structure",
            "fee_class",
        )
    )


def expand_cells_with_variants(
    cells: List[Dict[str, str]],
    variants_per_cell: int = 2,
) -> List[Dict[str, Any]]:
    """Attach variant index for grid/distribution diversity within each cell."""
    out: List[Dict[str, Any]] = []
    for cell in cells:
        for v in range(variants_per_cell):
            out.append({**cell, "variant_idx": v})
    return out


def total_primary_combinations() -> int:
    n = 1
    for dim in PRIMARY_DIMS:
        n *= len(dim)
    return n
