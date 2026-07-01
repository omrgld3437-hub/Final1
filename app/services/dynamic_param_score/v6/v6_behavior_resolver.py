"""Resolve tactical behavior from scenario tree node."""

from __future__ import annotations

from typing import Optional

from app.services.dynamic_param_score.v6.v6_scenario_classifier import ClassifiedScenario
from app.services.dynamic_param_score.v6.v6_scenario_tree import find_terminal_for_classifier


def resolve_behavior(classified: ClassifiedScenario) -> str:
    node = find_terminal_for_classifier(
        classified.regime_id,
        classified.sub_id,
        classified.micro_id,
        classified.behavior_id,
    )
    if node and node.get("default_behavior_id"):
        return str(node["default_behavior_id"])
    return classified.behavior_id
