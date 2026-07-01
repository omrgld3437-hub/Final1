"""Adjuster pipeline — deterministic deltas on catalog profile."""

from __future__ import annotations

from app.services.dynamic_param_score.v6.v6_adjuster_trace import run_adjusters_with_trace
from app.services.dynamic_param_score.v6.domain.types import AdjusterDelta, V6InputContract


def run_adjusters(inp: V6InputContract) -> tuple[AdjusterDelta, int]:
    total, data_quality_risk, _ = run_adjusters_with_trace(inp)
    return total, data_quality_risk
