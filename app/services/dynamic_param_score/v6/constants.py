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

# Net profile library trailing lattice.  The operator profiles are the source of
# truth, so every common trailing value in that list has an exact code.
TRAILING_CODES: Dict[str, float] = {
    "T035": 0.35, "T040": 0.40, "T045": 0.45, "T050": 0.50,
    "T055": 0.55, "T060": 0.60, "T065": 0.65, "T070": 0.70,
    "T075": 0.75, "T080": 0.80, "T085": 0.85, "T090": 0.90,
    "T095": 0.95, "T100": 1.00, "T105": 1.05, "T110": 1.10,
    "T120": 1.20, "T125": 1.25, "T130": 1.30, "T140": 1.40,
    "T150": 1.50, "T160": 1.60, "T170": 1.70, "T175": 1.75, "T180": 1.80,
    "T200": 2.00, "T230": 2.30, "T250": 2.50,
}
TRAILING_PCT_TO_CODE: Dict[float, str] = {v: k for k, v in TRAILING_CODES.items()}

# Profit trigger K01..K16 (% · 0.5 lattice)
PROFIT_TRIGGER_CODES: Dict[str, float] = {
    "K100": 1.0, "K150": 1.5, "K200": 2.0, "K220": 2.2,
    "K240": 2.4, "K250": 2.5, "K280": 2.8, "K300": 3.0,
    "K320": 3.2, "K350": 3.5, "K400": 4.0, "K450": 4.5,
    "K500": 5.0, "K550": 5.5, "K600": 6.0, "K650": 6.5,
    "K700": 7.0, "K750": 7.5, "K800": 8.0, "K900": 9.0,
    "K1000": 10.0,
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

# When a buy ladder must be shortened, keep the larger share on the deeper
# remaining level.  This preserves the existing exchange-safety behaviour
# while the net profile library supplies the new distances and trailing.
SAFE_BUY_TRIM_TEMPLATES: Dict[int, Tuple[int, ...]] = {
    1: (100,),
    2: (30, 70),
    3: (10, 30, 60),
    4: (10, 20, 30, 40),
    5: (10, 15, 20, 25, 30),
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
