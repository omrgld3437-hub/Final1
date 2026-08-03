"""Formula based, spot-only Dynamic Mode V2.

The package is deliberately independent from the legacy regime/profile engine.
It produces one validated parameter package from an immutable turn reference
and never mutates a triggered grid.
"""

from .config import DynamicV2Config, FormulaCoefficients
from .models import (
    ContinuousMarketState,
    DynamicParameterCandidate,
    GridRuntimeState,
    TurnReferenceParameters,
)
from .service import DynamicModeV2

__all__ = [
    "ContinuousMarketState",
    "DynamicModeV2",
    "DynamicParameterCandidate",
    "DynamicV2Config",
    "FormulaCoefficients",
    "GridRuntimeState",
    "TurnReferenceParameters",
]
