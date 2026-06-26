"""DPS Engine V2 — parameter factory, validation, and index builders."""

from app.services.dynamic_param_score.param_generator.grid_math import (
    compute_grid_ladder,
    compute_first_grid_pct,
)
from app.services.dynamic_param_score.param_generator.amount_distribution import (
    geometric_distribution,
)
from app.services.dynamic_param_score.param_generator.param_library_builder import (
    DPS_ENGINE_V2,
    POOL_TARGET_V3,
    POOL_VERSION_V3,
    build_dps_v2_pool,
)
from app.services.dynamic_param_score.param_generator.param_index_builder import (
    build_selection_index,
    index_key_for_signature,
)

__all__ = [
    "DPS_ENGINE_V2",
    "POOL_TARGET_V3",
    "POOL_VERSION_V3",
    "build_dps_v2_pool",
    "build_selection_index",
    "compute_first_grid_pct",
    "compute_grid_ladder",
    "geometric_distribution",
    "index_key_for_signature",
]
