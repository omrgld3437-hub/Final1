"""V6 lattice constants and cost policy — no live fee inputs."""

from __future__ import annotations

from typing import Dict, List, Tuple

DEFAULT_COST_FLOOR_PCT = 1.2
MIN_PROFIT_BUFFER_PCT = 1.0

# Base allocation: 5% steps 0..95
BASE_ALLOC_PCT_STEPS: Tuple[int, ...] = tuple(range(0, 100, 5))

# Grid distance: 1% steps (signed)
GRID_DISTANCE_STEP_PCT = 1

# Grid amount: 5% steps
GRID_AMOUNT_STEP_PCT = 5

# Trailing ladder T0..T8
TRAILING_CODES: Dict[str, float] = {
    "T0": 0.5,
    "T1": 0.8,
    "T2": 1.1,
    "T3": 1.4,
    "T4": 1.7,
    "T5": 2.0,
    "T6": 2.3,
    "T7": 2.6,
    "T8": 2.9,
}
TRAILING_PCT_TO_CODE: Dict[float, str] = {v: k for k, v in TRAILING_CODES.items()}

# Profit trigger K05..K12 (%)
PROFIT_TRIGGER_CODES: Dict[str, float] = {
    "K05": 2.5,
    "K06": 3.0,
    "K07": 3.5,
    "K08": 4.0,
    "K09": 4.5,
    "K10": 5.0,
    "K11": 5.5,
    "K12": 6.0,
    "K13": 6.5,
    "K14": 7.0,
    "K15": 7.5,
    "K16": 8.0,
}
PROFIT_PCT_TO_CODE: Dict[float, str] = {v: k for k, v in PROFIT_TRIGGER_CODES.items()}

# Allowed qty templates per grid count (must sum to 100, 5% steps)
QTY_TEMPLATES: Dict[int, List[Tuple[int, ...]]] = {
    1: [(100,)],
    2: [(60, 40), (40, 60), (30, 70), (70, 30)],
    3: [(35, 35, 30), (20, 30, 50), (10, 30, 60), (50, 30, 20), (30, 40, 30)],
    4: [(25, 25, 25, 25), (10, 20, 30, 40), (40, 30, 20, 10), (15, 25, 30, 30)],
    5: [(20, 20, 20, 20, 20), (10, 15, 20, 25, 30), (30, 25, 20, 15, 10), (10, 20, 20, 20, 30)],
}

SEVERITY_MODES = ("DEF", "STD", "ACT")
REGIME_IDS = tuple(f"R{i}" for i in range(1, 9))

# Global delta limits (base steps on 5% lattice)
MAX_BASE_DOWN_STEPS_NORMAL = 2
MAX_BASE_UP_STEPS_NORMAL = 1
MAX_BASE_DOWN_STEPS_EXTREME = 3

MAX_TRAILING_UP_STEPS_NORMAL = 2
MAX_TRAILING_UP_STEPS_EXTREME = 3

MAX_PROFIT_INCREASE_NORMAL = 2.0
MAX_PROFIT_INCREASE_EXTREME = 3.0

MAX_BUY_GRID_WIDEN_NORMAL_PCT = 100
MAX_BUY_GRID_WIDEN_EXTREME_PCT = 150

MIN_GRID_COUNT = 1
MAX_GRID_COUNT = 5

# Scenario-specific minimum profit floors (after cost floor rule)
REGIME_MIN_PROFIT_FLOOR: Dict[str, Tuple[float, float]] = {
    "R4": (4.5, 5.5),
    "R8": (5.0, 7.0),
}

FRAGILITY_MIN_PROFIT_FLOOR: Dict[str, Tuple[float, float]] = {
    "F3": (5.5, 7.0),
}

ENGINE_VERSION = "DPS_ENGINE_V6"
