"""Dynamic Param V5 — 192,780 exact shelf library."""

from app.services.dynamic_param_score.v5.domain.dimensions import EXPECTED_V5_SHELF_COUNT
from app.services.dynamic_param_score.v5.generator.generate_shelves import generate_all_v5_shelves
from app.services.dynamic_param_score.v5.index.route_lookup import (
    build_v5_route_index,
    lookup_exact_v5_shelf,
)
from app.services.dynamic_param_score.v5.resolver.resolve_dynamic_param_v5 import resolve_dynamic_param_v5
from app.services.dynamic_param_score.v5.validator.shelf_validator import validate_shelf

__all__ = [
    "EXPECTED_V5_SHELF_COUNT",
    "generate_all_v5_shelves",
    "build_v5_route_index",
    "lookup_exact_v5_shelf",
    "resolve_dynamic_param_v5",
    "validate_shelf",
]
