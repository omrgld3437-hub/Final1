"""Param Template Pool — versioned template selection for Dynamic Param Score."""

from app.services.dynamic_param_score.param_pool.models import (
    BudgetTier,
    ExposureTier,
    FeeTier,
    HeadroomTier,
    ParamPoolVersion,
    ParamTemplate,
    ProfileFamily,
    TemplateRejectReason,
    TemplateSelectionResult,
)
from app.services.dynamic_param_score.param_pool.registry import get_active_pool, load_pool
from app.services.dynamic_param_score.param_pool.selector import select_template
from app.services.dynamic_param_score.param_pool.renderer import render_template
from app.services.dynamic_param_score.param_pool.diagnostics import (
    build_selection_diagnostics,
    build_reject_summary,
)

__all__ = [
    "BudgetTier",
    "ExposureTier",
    "FeeTier",
    "HeadroomTier",
    "ParamPoolVersion",
    "ParamTemplate",
    "ProfileFamily",
    "TemplateSelectionResult",
    "TemplateRejectReason",
    "get_active_pool",
    "load_pool",
    "select_template",
    "render_template",
    "build_selection_diagnostics",
    "build_reject_summary",
]
