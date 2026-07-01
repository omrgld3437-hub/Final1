"""Load scenario_tree_v6.json terminals."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "dynamic_param_v6"
_TREE_FILE = _DATA_DIR / "scenario_tree_v6.json"


@lru_cache(maxsize=1)
def load_scenario_tree() -> Dict[str, Any]:
    if not _TREE_FILE.is_file():
        return {"terminals": []}
    with _TREE_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def load_terminals() -> List[Dict[str, Any]]:
    return list(load_scenario_tree().get("terminals") or [])


def find_terminal(
    regime_id: str,
    sub_id: str,
    micro_id: str,
    terminal_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    for node in load_terminals():
        if node.get("regime_id") != regime_id:
            continue
        if node.get("sub_id") != sub_id:
            continue
        if node.get("micro_id") != micro_id:
            continue
        if terminal_id and node.get("terminal_id") != terminal_id:
            continue
        return node
    return None


def find_terminal_for_classifier(
    regime_id: str,
    sub_id: str,
    micro_id: str,
    behavior_id: str,
) -> Optional[Dict[str, Any]]:
    matches = [
        t for t in load_terminals()
        if t.get("regime_id") == regime_id
        and t.get("sub_id") == sub_id
        and t.get("micro_id") == micro_id
        and t.get("default_behavior_id") == behavior_id
    ]
    if matches:
        return matches[0]
    matches = [
        t for t in load_terminals()
        if t.get("regime_id") == regime_id
        and t.get("default_behavior_id") == behavior_id
    ]
    return matches[0] if matches else None


# Backward-compatible alias
find_tree_node = find_terminal
