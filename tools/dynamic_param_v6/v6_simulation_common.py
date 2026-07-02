"""Shared V6 profile simulation, validation, path dry-run, and report helpers.

No trade execution — read-only validation and synthetic path replay only.
"""

from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]

from app.services.dynamic_param_score.v6.constants import (  # noqa: E402
    DEFAULT_COST_FLOOR_PCT,
    MIN_PROFIT_BUFFER_PCT,
    PROFIT_TRIGGER_CODES,
    TRAILING_CODES,
)
from app.services.dynamic_param_score.v6.domain.types import V6CatalogProfile  # noqa: E402
from app.services.dynamic_param_score.v6.v6_botparams_adapter import (  # noqa: E402
    v6_profile_to_bot_params,
)
from app.services.dynamic_param_score.v6.v6_profile_catalog import (  # noqa: E402
    _profile_from_dict,
)
from app.services.dynamic_param_score.v6.v6_profile_validator import validate_profile  # noqa: E402
from app.services.dynamic_param_score.v6.v6_quantizer import (  # noqa: E402
    min_profit_pct_for_trailing,
    profit_pct_from_code,
    trailing_pct_from_code,
)

EXPECTED_PROFILE_COUNT = 2295
REPORT_DIR = ROOT / "reports" / "dynamic_param_v6" / "full_simulation"
CATALOG_FILE = ROOT / "data" / "dynamic_param_v6" / "dplv6_profile_catalog.json"

ALLOWED_TRAILING = frozenset(TRAILING_CODES.values())
ALLOWED_PROFIT_TRIGGERS = frozenset(PROFIT_TRIGGER_CODES.values())

SIM_BUDGETS = (100, 250, 500, 1000, 5000)
REF_PRICE = 100.0
DEFAULT_MIN_NOTIONAL = 10.0

MANDATORY_LIVE_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "ADAUSDT",
    "MANTAUSDT",
    "SYNUSDT",
    "REUSDT",
)

STABLE_EXCLUDE = frozenset(
    {
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "BUSDUSDT",
        "DAIUSDT",
        "USDPUSDT",
        "EURUSDT",
    }
)

LEVERAGED_TOKEN_RE = re.compile(r"(UP|DOWN|BULL|BEAR)$")

SYNTHETIC_PATHS: Dict[str, List[float]] = {
    "PATH_FLAT": [100, 100.2, 99.8, 100.1, 99.9, 100],
    "PATH_RANGE_NORMAL": [100, 97, 103, 98, 104, 100],
    "PATH_RANGE_WIDE": [100, 92, 108, 90, 112, 101],
    "PATH_UP_TREND": [100, 103, 106, 110, 115, 120],
    "PATH_DOWN_TREND": [100, 97, 94, 90, 85, 80],
    "PATH_CRASH": [100, 92, 84, 75, 68, 70],
    "PATH_CRASH_BOUNCE": [100, 88, 76, 82, 90, 84, 92],
    "PATH_PUMP_DUMP": [100, 108, 118, 112, 96, 88],
    "PATH_FAKE_BREAKOUT": [100, 104, 108, 106, 99, 94],
    "PATH_WICKY_VOLATILE": [100, 93, 107, 91, 110, 89, 105],
}

V5_FORBIDDEN_TOKENS = ("fee_efficiency", "dplv5", "v5_shelf", "scenario_alignment")


@dataclass
class Finding:
    code: str
    profile_id: str = ""
    symbol: str = ""
    path: str = ""
    budget: float = 0.0
    detail: str = ""
    severity: str = "error"  # error | warning

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in ("", 0.0)}


@dataclass
class StaticValidationResult:
    profile_id: str
    regime_id: str
    behavior_id: str
    severity: str
    base_pct: int
    quote_pct: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class PathSimulationResult:
    profile_id: str
    path_name: str
    budget: float
    events: Dict[str, Any]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    realized_pnl_pct: float = 0.0
    unrealized_pnl_pct: float = 0.0
    max_drawdown_simulated: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_report_dir() -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR


def load_catalog_profiles() -> List[V6CatalogProfile]:
    if not CATALOG_FILE.is_file():
        raise FileNotFoundError(f"catalog missing: {CATALOG_FILE}")
    with CATALOG_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)
    profiles_raw = raw.get("profiles") if isinstance(raw, dict) else raw
    if not isinstance(profiles_raw, list):
        raise ValueError("catalog profiles must be a list")
    profiles = [_profile_from_dict(item) for item in profiles_raw]
    return profiles


def assert_catalog_count(profiles: Sequence[V6CatalogProfile]) -> None:
    n = len(profiles)
    if n != EXPECTED_PROFILE_COUNT:
        raise AssertionError(f"expected {EXPECTED_PROFILE_COUNT} profiles, got {n}")
    ids = [p.profile_id for p in profiles]
    if len(set(ids)) != n:
        raise AssertionError("duplicate profile_id in catalog")


def _profit_codes_valid(code: str) -> bool:
    return code in PROFIT_TRIGGER_CODES


def _trailing_valid(code: str) -> bool:
    return trailing_pct_from_code(code) in ALLOWED_TRAILING


def validate_profile_static(profile: V6CatalogProfile) -> StaticValidationResult:
    """Stage A — static invariant checks per profile."""
    scen = profile.scenario
    res = StaticValidationResult(
        profile_id=profile.profile_id,
        regime_id=scen.regime_id,
        behavior_id=scen.behavior_id,
        severity=str(scen.severity),
        base_pct=profile.base_allocation_pct,
        quote_pct=profile.quote_allocation_pct,
    )

    if not profile.profile_id.startswith("DPLV6_"):
        res.errors.append("ERROR_PROFILE_ID_PREFIX")
    if scen.regime_id not in {f"R{i}" for i in range(1, 9)}:
        res.errors.append("ERROR_REGIME_OUT_OF_RANGE")
    if not re.match(r"^PB\d{2,3}$", scen.behavior_id or ""):
        res.errors.append("ERROR_BEHAVIOR_FORMAT")
    if str(scen.severity) not in ("DEF", "STD", "ACT"):
        res.errors.append("ERROR_SEVERITY_INVALID")
    if profile.base_allocation_pct % 5 != 0:
        res.errors.append("ERROR_BASE_NOT_5_STEP")
    if profile.quote_allocation_pct != 100 - profile.base_allocation_pct:
        res.errors.append("ERROR_QUOTE_MISMATCH")
    if profile.base_allocation_pct < 0 or profile.base_allocation_pct > 95:
        res.errors.append("ERROR_BASE_OUT_OF_RANGE")
    if profile.quote_allocation_pct < 5 or profile.quote_allocation_pct > 100:
        res.errors.append("ERROR_QUOTE_OUT_OF_RANGE")

    if not profile.normal_buy_enabled and profile.buy_grids:
        res.errors.append("ERROR_NORMAL_BUY_CLOSED_BUT_BUY_GRIDS_PRESENT")
    if profile.normal_buy_enabled and not profile.buy_grids:
        res.errors.append("ERROR_NORMAL_BUY_OPEN_BUT_NO_BUY_GRIDS")
    if profile.normal_buy_enabled:
        n = len(profile.buy_grids)
        if n < 1 or n > 5:
            res.errors.append("ERROR_BUY_GRID_COUNT")
    if profile.sell_grids:
        n = len(profile.sell_grids)
        if n < 1 or n > 5:
            res.errors.append("ERROR_SELL_GRID_COUNT")
    elif profile.modules.get("sell_grid"):
        res.errors.append("ERROR_SELL_ENABLED_BUT_NO_SELL_GRIDS")

    for g in profile.buy_grids:
        if g.distance_pct >= 0:
            res.errors.append("ERROR_BUY_GRID_POSITIVE")
        if int(g.distance_pct) != float(g.distance_pct):
            res.errors.append("ERROR_BUY_GRID_NOT_INT")
        if g.amount_pct % 5 != 0:
            res.errors.append("ERROR_GRID_AMOUNT_NOT_5_STEP")
    for g in profile.sell_grids:
        if g.distance_pct <= 0:
            res.errors.append("ERROR_SELL_GRID_NEGATIVE")
        if int(g.distance_pct) != float(g.distance_pct):
            res.errors.append("ERROR_SELL_GRID_NOT_INT")
        if g.amount_pct % 5 != 0:
            res.errors.append("ERROR_GRID_AMOUNT_NOT_5_STEP")

    if profile.buy_grids:
        if sum(g.amount_pct for g in profile.buy_grids) != 100:
            res.errors.append("ERROR_GRID_AMOUNT_SUM_NOT_100")
    if profile.sell_grids:
        if sum(g.amount_pct for g in profile.sell_grids) != 100:
            res.errors.append("ERROR_GRID_AMOUNT_SUM_NOT_100")

    for code_key, err in (
        ("sell_trailing_code", "ERROR_TRAILING_NOT_IN_LATTICE"),
        ("buy_trailing_code", "ERROR_TRAILING_NOT_IN_LATTICE"),
        ("buyback_trailing_code", "ERROR_TRAILING_NOT_IN_LATTICE"),
        ("profit_sell_trailing_code", "ERROR_TRAILING_NOT_IN_LATTICE"),
    ):
        code = getattr(profile, code_key, "T2")
        if not _trailing_valid(code):
            res.errors.append(err)

    for code_key in ("buyback_trigger_code", "profit_sell_trigger_code"):
        code = getattr(profile, code_key, "K10")
        pct = profit_pct_from_code(code)
        if pct not in ALLOWED_PROFIT_TRIGGERS:
            res.errors.append("ERROR_PROFIT_TRIGGER_NOT_IN_LATTICE")

    sell_trail = trailing_pct_from_code(profile.sell_trailing_code)
    for code_key, enabled_attr in (
        ("buyback_trigger_code", "buyback_after_sell_enabled"),
        ("profit_sell_trigger_code", "profit_sell_after_buyback_enabled"),
    ):
        if getattr(profile, enabled_attr):
            trail = trailing_pct_from_code(
                profile.buyback_trailing_code
                if "buyback" in code_key
                else profile.profit_sell_trailing_code
            )
            trigger = profit_pct_from_code(getattr(profile, code_key))
            floor = min_profit_pct_for_trailing(trail)
            if trigger < floor - 0.01:
                res.errors.append("ERROR_MIN_PROFIT_FLOOR_BREACH")
                res.errors.append("ERROR_PROFIT_BELOW_COST_FLOOR")

    if profile.buyback_after_sell_enabled and not profile.sell_grids:
        res.errors.append("ERROR_REBUY_ENABLED_WITHOUT_SELL_GRID")
    if profile.profit_sell_after_buyback_enabled and not profile.buyback_after_sell_enabled:
        res.errors.append("ERROR_PROFIT_SELL_ENABLED_WITHOUT_REBUY")

  # reuse internal validator
    for internal in validate_profile(profile):
        mapping = {
            "base_not_5_step": "ERROR_BASE_NOT_5_STEP",
            "quote_mismatch": "ERROR_QUOTE_MISMATCH",
            "fractional_lattice_violation": "ERROR_FRACTIONAL_LATTICE",
            "buy_grids_when_normal_buy_disabled": "ERROR_NORMAL_BUY_CLOSED_BUT_BUY_GRIDS_PRESENT",
            "buy_grid_count_out_of_range": "ERROR_BUY_GRID_COUNT",
            "sell_grid_count_out_of_range": "ERROR_SELL_GRID_COUNT",
            "buy_qty_sum_not_100": "ERROR_GRID_AMOUNT_SUM_NOT_100",
            "sell_qty_sum_not_100": "ERROR_GRID_AMOUNT_SUM_NOT_100",
            "buyback_below_cost_floor": "ERROR_PROFIT_BELOW_COST_FLOOR",
            "profit_sell_missing_after_buyback": "ERROR_PROFIT_SELL_ENABLED_WITHOUT_REBUY",
            "buyback_missing_before_profit_sell": "ERROR_REBUY_ENABLED_WITHOUT_SELL_GRID",
        }
        res.errors.append(mapping.get(internal, f"ERROR_{internal.upper()}"))

    _apply_behavior_regime_rules(profile, res)
    return res


def _apply_behavior_regime_rules(profile: V6CatalogProfile, res: StaticValidationResult) -> None:
    scen = profile.scenario
    bid = scen.behavior_id

    if bid == "PB11":
        if not profile.sell_grids:
            res.errors.append("ERROR_PB11_LOOP_BROKEN")
        if not profile.buyback_after_sell_enabled or not profile.profit_sell_after_buyback_enabled:
            res.errors.append("ERROR_PB11_LOOP_BROKEN")
        if not profile.sell_grids and profile.buyback_after_sell_enabled:
            res.errors.append("ERROR_PB11_REBUY_DISABLED")
        if profile.sell_grids and not profile.profit_sell_after_buyback_enabled:
            res.errors.append("ERROR_PB11_PROFIT_SELL_DISABLED")
        buy_n = len(profile.buy_grids) if profile.normal_buy_enabled else 0
        sell_n = len(profile.sell_grids)
        operational = (
            profile.base_allocation_pct > 0 and sell_n >= 1
        ) or (
            profile.normal_buy_enabled and buy_n >= 1
        )
        if not operational:
            res.errors.append("ERROR_PB11_NON_OPERATIONAL")

    buy_n = len(profile.buy_grids) if profile.normal_buy_enabled else 0
    sell_n = len(profile.sell_grids)
    if profile.base_allocation_pct == 0 and buy_n == 0 and sell_n == 0:
        res.errors.append("ERROR_NON_OPERATIONAL_PARAMS")

    if scen.regime_id == "R8":
        if str(scen.severity) == "DEF" and profile.base_allocation_pct > 15:
            res.warnings.append("WARN_R8_DEF_BASE_TOO_HIGH")
        if profile.buy_grids and profile.buy_grids[0].distance_pct > -7:
            res.errors.append("ERROR_R8_BUY_GRID_TOO_CLOSE")
        if profile.base_allocation_pct > 25:
            res.errors.append("ERROR_R8_BASE_TOO_HIGH")

    if scen.regime_id == "R6" and not profile.sell_grids:
        res.errors.append("ERROR_R6_SELL_DISABLED")

    if scen.regime_id == "R2" and bid in ("PB01", "V1") and profile.buy_grids:
        if profile.buy_grids[0].distance_pct < -8:
            res.warnings.append("WARN_R2_V1_BUY_TOO_WIDE")
    if scen.regime_id == "R2" and bid in ("PB01", "V1") and profile.sell_grids:
        if profile.sell_grids[0].distance_pct > 6:
            res.warnings.append("WARN_R2_V1_SELL_TOO_WIDE")


def simulate_profile_path(
    profile: V6CatalogProfile,
    *,
    path_name: str,
    prices: Sequence[float],
    budget: float = 500.0,
    ref_price: float = REF_PRICE,
    min_notional: float = DEFAULT_MIN_NOTIONAL,
) -> PathSimulationResult:
    """Stage B — synthetic price path dry-run (no orders sent)."""
    if not prices:
        prices = [ref_price]
    start_price = float(prices[0] or ref_price)
    base_pct = profile.base_allocation_pct / 100.0
    quote_pct = profile.quote_allocation_pct / 100.0

    base_qty = (budget * base_pct) / start_price if start_price > 0 else 0.0
    quote_cash = budget * quote_pct
    initial_base_notional = base_qty * start_price
    initial_quote_notional = quote_cash

    params = v6_profile_to_bot_params(profile)
    buy_dist = list(params.buy_grid_ladder_pcts or [])
    buy_w = list(params.buy_qty_distribution or [])
    sell_dist = list(params.sell_grid_ladder_pcts or [])
    sell_w = list(params.sell_qty_distribution or [])

    events: Dict[str, Any] = {
        "initial_base_notional": round(initial_base_notional, 4),
        "initial_quote_notional": round(initial_quote_notional, 4),
        "buy_orders_created": len(buy_dist) if profile.normal_buy_enabled else 0,
        "sell_orders_created": len(sell_dist),
        "orders_below_min_notional": 0,
        "buy_fills": 0,
        "sell_fills": 0,
        "rebuy_fills": 0,
        "profit_sell_fills": 0,
        "cycle_count": 0,
        "unclosed_position_count": 0,
        "max_base_exposure_pct": round(base_pct * 100, 2),
        "max_quote_usage_pct": 0.0,
        "average_grid_distance": 0.0,
        "profit_loop_integrity": True,
    }

    errors: List[str] = []
    warnings: List[str] = []

    static = validate_profile_static(profile)
    errors.extend(static.errors)
    warnings.extend(static.warnings)

    filled_buy: Set[int] = set()
    filled_sell: Set[int] = set()
    buy_quote_pool = quote_cash
    initial_base = base_qty

    rebuy_armed = False
    rebuy_peak = 0.0
    rebuy_entry = 0.0
    profit_armed = False
    profit_peak = 0.0

    peak_equity = budget
    max_dd = 0.0
    grid_dists: List[float] = []

    for dist in buy_dist:
        grid_dists.append(abs(dist))
    for dist in sell_dist:
        grid_dists.append(dist)
    if grid_dists:
        events["average_grid_distance"] = round(sum(grid_dists) / len(grid_dists), 2)

    price_path = [start_price] + [float(p) for p in prices[1:]]

    for price in price_path[1:]:
        # Sell grid fills
        for i, (dist, w) in enumerate(zip(sell_dist, sell_w)):
            if i in filled_sell:
                continue
            level = start_price * (1 + dist / 100.0)
            if price >= level and base_qty > 0:
                sell_qty = initial_base * w
                sell_qty = min(sell_qty, base_qty)
                notional = sell_qty * price
                if notional < min_notional:
                    events["orders_below_min_notional"] += 1
                    continue
                base_qty -= sell_qty
                quote_cash += notional
                filled_sell.add(i)
                events["sell_fills"] += 1
                events["cycle_count"] += 1
                if params.rebuy_enabled:
                    rebuy_armed = True
                    rebuy_peak = price
                    profit_armed = False

        # Buy grid fills
        if profile.normal_buy_enabled:
            for i, (dist, w) in enumerate(zip(buy_dist, buy_w)):
                if i in filled_buy:
                    continue
                level = start_price * (1 - dist / 100.0)
                if price <= level and buy_quote_pool > 0:
                    order_quote = quote_cash * w
                    if order_quote < min_notional:
                        events["orders_below_min_notional"] += 1
                        continue
                    buy_qty = order_quote / price
                    quote_cash -= order_quote
                    buy_quote_pool -= order_quote
                    base_qty += buy_qty
                    filled_buy.add(i)
                    events["buy_fills"] += 1

        # Post-sell rebuy (simplified trailing)
        if rebuy_armed and params.rebuy_enabled and params.rebuy_trigger_pct:
            rebuy_peak = max(rebuy_peak, price)
            trigger = rebuy_peak * (1 - float(params.rebuy_trigger_pct) / 100.0)
            if price <= trigger and quote_cash >= min_notional:
                spend = min(quote_cash, budget * 0.25)
                if spend >= min_notional:
                    base_qty += spend / price
                    quote_cash -= spend
                    events["rebuy_fills"] += 1
                    rebuy_armed = False
                    rebuy_entry = price
                    profit_armed = True
                    profit_peak = price
                    events["cycle_count"] += 1

        # Profit sell after rebuy
        if profit_armed and params.resell_enabled and params.resell_trigger_pct and base_qty > 0:
            profit_peak = max(profit_peak, price)
            trigger = rebuy_entry * (1 + float(params.resell_trigger_pct) / 100.0)
            if price >= trigger:
                sell_qty = base_qty * 0.5
                notional = sell_qty * price
                if notional >= min_notional:
                    base_qty -= sell_qty
                    quote_cash += notional
                    events["profit_sell_fills"] += 1
                    profit_armed = False
                    events["cycle_count"] += 1

        equity = base_qty * price + quote_cash
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            dd = (peak_equity - equity) / peak_equity * 100.0
            max_dd = max(max_dd, dd)
        exp_pct = (base_qty * price / equity * 100.0) if equity > 0 else 0
        events["max_base_exposure_pct"] = round(max(events["max_base_exposure_pct"], exp_pct), 2)
        used_quote = budget - quote_cash
        events["max_quote_usage_pct"] = round(max(events["max_quote_usage_pct"], used_quote / budget * 100), 2)

    final_equity = base_qty * price_path[-1] + quote_cash
    realized_pnl_pct = (final_equity - budget) / budget * 100.0 if budget > 0 else 0.0
    events["final_base_notional"] = round(base_qty * price_path[-1], 4)
    events["final_quote_notional"] = round(quote_cash, 4)
    events["unclosed_position_count"] = 1 if base_qty > 1e-12 else 0

    if profile.scenario.behavior_id == "PB11":
        if profile.sell_grids and (
            not profile.buyback_after_sell_enabled or not profile.profit_sell_after_buyback_enabled
        ):
            errors.append("ERROR_PB11_LOOP_BROKEN")
            events["profit_loop_integrity"] = False
        if path_name == "PATH_CRASH_BOUNCE" and events["sell_fills"] > 0 and events["rebuy_fills"] == 0:
            warnings.append("WARN_PB11_NO_REBUY_ON_BOUNCE")

    if profile.scenario.regime_id == "R8":
        initial_exp = profile.base_allocation_pct
        if events["max_base_exposure_pct"] > max(initial_exp + 20, 35):
            warnings.append("WARN_R8_EXPOSURE_DRIFT")
        if path_name in ("PATH_CRASH", "PATH_DOWN_TREND") and events["buy_fills"] > 2:
            warnings.append("WARN_R8_AGGRESSIVE_BUY_FILLS_ON_CRASH")

    total_orders = events["buy_orders_created"] + events["sell_orders_created"]
    if total_orders > 0:
        total_attempts = events["buy_fills"] + events["sell_fills"] + events["rebuy_fills"]
        if total_attempts == 0 and events["orders_below_min_notional"] >= total_orders:
            if budget < 250:
                warnings.append("WARN_MIN_NOTIONAL_TIGHT_BUDGET")
            else:
                errors.append("ERROR_MIN_NOTIONAL_ALL_ORDERS_FAILED")

    _path_volatility_warnings(profile, path_name, events, warnings)

    return PathSimulationResult(
        profile_id=profile.profile_id,
        path_name=path_name,
        budget=budget,
        events=events,
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
        realized_pnl_pct=round(realized_pnl_pct, 4),
        unrealized_pnl_pct=round(realized_pnl_pct, 4),
        max_drawdown_simulated=round(max_dd, 4),
    )


def _path_volatility_warnings(
    profile: V6CatalogProfile,
    path_name: str,
    events: Dict[str, Any],
    warnings: List[str],
) -> None:
    avg_dist = float(events.get("average_grid_distance") or 0)
    if path_name in ("PATH_FLAT", "PATH_RANGE_NORMAL") and avg_dist > 12:
        warnings.append("WARN_GRID_TOO_WIDE_FOR_LOW_VOL")
    if path_name in ("PATH_WICKY_VOLATILE", "PATH_RANGE_WIDE") and avg_dist < 3:
        warnings.append("WARN_GRID_TOO_NARROW_FOR_HIGH_VOL")
    if events.get("cycle_count", 0) > 15 and path_name == "PATH_FLAT":
        warnings.append("WARN_EXCESSIVE_CYCLING_ON_FLAT")


def run_static_validation_all(
    profiles: Sequence[V6CatalogProfile],
) -> Tuple[List[StaticValidationResult], Counter]:
    results = [validate_profile_static(p) for p in profiles]
    err_counter: Counter = Counter()
    for r in results:
        for e in r.errors:
            err_counter[e] += 1
        for w in r.warnings:
            err_counter[w] += 1
    return results, err_counter


def run_path_simulation_all(
    profiles: Sequence[V6CatalogProfile],
    *,
    budgets: Sequence[float] = SIM_BUDGETS,
    paths: Optional[Dict[str, List[float]]] = None,
) -> Tuple[List[PathSimulationResult], Counter]:
    paths = paths or SYNTHETIC_PATHS
    out: List[PathSimulationResult] = []
    err_counter: Counter = Counter()
    for profile in profiles:
        for budget in budgets:
            for path_name, price_list in paths.items():
                row = simulate_profile_path(
                    profile,
                    path_name=path_name,
                    prices=price_list,
                    budget=float(budget),
                )
                out.append(row)
                for e in row.errors:
                    err_counter[e] += 1
                for w in row.warnings:
                    err_counter[w] += 1
    return out, err_counter


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def static_results_to_rows(results: Sequence[StaticValidationResult]) -> List[Dict[str, Any]]:
    rows = []
    for r in results:
        rows.append(
            {
                "profile_id": r.profile_id,
                "regime_id": r.regime_id,
                "behavior_id": r.behavior_id,
                "severity": r.severity,
                "base_pct": r.base_pct,
                "quote_pct": r.quote_pct,
                "error_count": len(r.errors),
                "warning_count": len(r.warnings),
                "errors": ";".join(r.errors),
                "warnings": ";".join(r.warnings),
                "ok": r.ok,
            }
        )
    return rows


def path_results_to_rows(results: Sequence[PathSimulationResult]) -> List[Dict[str, Any]]:
    rows = []
    for r in results:
        row = {
            "profile_id": r.profile_id,
            "path_name": r.path_name,
            "budget": r.budget,
            "error_count": len(r.errors),
            "warning_count": len(r.warnings),
            "errors": ";".join(r.errors),
            "warnings": ";".join(r.warnings),
            "realized_pnl_pct": r.realized_pnl_pct,
            "max_drawdown_simulated": r.max_drawdown_simulated,
            "ok": r.ok,
        }
        row.update({f"evt_{k}": v for k, v in r.events.items()})
        rows.append(row)
    return rows


def load_catalog_simulation_counts(*, require_files: bool = False) -> Dict[str, int]:
    """Read profile/path run counts from on-disk catalog simulation artifacts."""
    static_path = REPORT_DIR / "all_profiles_static_validation.json"
    path_path = REPORT_DIR / "all_profiles_path_simulation.json"
    profiles = 0
    paths = 0
    if static_path.is_file():
        with static_path.open(encoding="utf-8") as f:
            static_data = json.load(f)
        profiles = int(
            static_data.get("profile_count")
            or len(static_data.get("results") or [])
            or 0
        )
    elif require_files:
        raise FileNotFoundError(f"catalog static report missing: {static_path}")
    if path_path.is_file():
        with path_path.open(encoding="utf-8") as f:
            path_data = json.load(f)
        paths = int(path_data.get("runs") or len(path_data.get("results") or []) or 0)
    elif require_files:
        raise FileNotFoundError(f"catalog path report missing: {path_path}")
    return {"profiles_tested": profiles, "path_simulations": paths}


def assert_report_summary_counts(summary: Dict[str, Any], *, context: str = "") -> None:
    """Fail loudly when report summary shows zero catalog runs but artifacts exist."""
    profiles = int(summary.get("profiles_tested") or 0)
    paths = int(summary.get("path_simulations") or 0)
    file_counts = load_catalog_simulation_counts(require_files=False)
    expected_profiles = int(file_counts.get("profiles_tested") or 0)
    expected_paths = int(file_counts.get("path_simulations") or 0)
    if expected_profiles > 0 and profiles == 0:
        raise AssertionError(
            f"ERROR_REPORT_SUMMARY_ZERO_BUG: profiles_tested=0 but catalog has {expected_profiles}"
            + (f" ({context})" if context else "")
        )
    if expected_paths > 0 and paths == 0:
        raise AssertionError(
            f"ERROR_REPORT_SUMMARY_ZERO_BUG: path_simulations=0 but catalog has {expected_paths}"
            + (f" ({context})" if context else "")
        )


def merge_report_summary(
    agg: Dict[str, Any],
    *,
    static_results: Optional[Sequence[StaticValidationResult]] = None,
    path_results: Optional[Sequence[PathSimulationResult]] = None,
) -> Dict[str, Any]:
    """Prefer in-memory counts; fall back to catalog JSON artifacts when lists are empty."""
    summary = dict(agg.get("summary") or {})
    if static_results:
        summary["profiles_tested"] = len(static_results)
    elif not summary.get("profiles_tested"):
        summary["profiles_tested"] = load_catalog_simulation_counts().get("profiles_tested", 0)
    if path_results:
        summary["path_simulations"] = len(path_results)
    elif not summary.get("path_simulations"):
        summary["path_simulations"] = load_catalog_simulation_counts().get("path_simulations", 0)
    agg = dict(agg)
    agg["summary"] = summary
    return agg


def aggregate_findings(
    static_results: Sequence[StaticValidationResult],
    path_results: Sequence[PathSimulationResult],
    live_rows: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    critical: Dict[str, Dict[str, Any]] = {}
    warnings_agg: Dict[str, Dict[str, Any]] = {}

    def _bump(bucket: Dict[str, Dict[str, Any]], code: str, example: str, kind: str) -> None:
        if code not in bucket:
            bucket[code] = {"code": code, "count": 0, "examples": [], "kind": kind}
        bucket[code]["count"] += 1
        if example and len(bucket[code]["examples"]) < 8:
            bucket[code]["examples"].append(example)

    for r in static_results:
        for e in r.errors:
            _bump(critical, e, r.profile_id, "static")
        for w in r.warnings:
            _bump(warnings_agg, w, r.profile_id, "static")

    for r in path_results:
        for e in r.errors:
            _bump(critical, e, f"{r.profile_id}:{r.path_name}@{r.budget}", "path")
        for w in r.warnings:
            _bump(warnings_agg, w, f"{r.profile_id}:{r.path_name}", "path")

    for row in live_rows or []:
        sym = str(row.get("symbol") or "")
        for e in str(row.get("errors") or "").split(";"):
            e = e.strip()
            if e:
                _bump(critical, e, sym, "live")
        for w in str(row.get("warnings") or "").split(";"):
            w = w.strip()
            if w:
                _bump(warnings_agg, w, sym, "live")

    crit_list = sorted(critical.values(), key=lambda x: (-x["count"], x["code"]))
    warn_list = sorted(warnings_agg.values(), key=lambda x: (-x["count"], x["code"]))

    return {
        "summary": {
            "profiles_tested": len(static_results),
            "path_simulations": len(path_results),
            "live_symbols_tested": len(live_rows or []),
            "critical_error_count": sum(c["count"] for c in crit_list),
            "warning_count": sum(w["count"] for w in warn_list),
        },
        "critical_errors": crit_list,
        "warnings": warn_list,
    }


def render_logic_errors_report(
    agg: Dict[str, Any],
    *,
    live_rows: Optional[Sequence[Dict[str, Any]]] = None,
    static_results: Optional[Sequence[StaticValidationResult]] = None,
    path_results: Optional[Sequence[PathSimulationResult]] = None,
) -> str:
    agg = merge_report_summary(
        agg,
        static_results=static_results,
        path_results=path_results,
    )
    assert_report_summary_counts(agg.get("summary") or {}, context="logic_errors_report")
    s = agg.get("summary") or {}
    lines = [
        "# Dynamic Param V6 Full Simulation Logic Error Report",
        "",
        f"Generated: {utc_now_iso()}",
        "",
        "## Summary",
        f"- Profiles tested: {s.get('profiles_tested', 0)}",
        f"- Path simulation runs: {s.get('path_simulations', 0)}",
        f"- Live symbols tested: {s.get('live_symbols_tested', 0)}",
        f"- Static profile errors: {sum(1 for c in agg.get('critical_errors', []) if c.get('kind') == 'static')}",
        f"- Path simulation errors: {sum(1 for c in agg.get('critical_errors', []) if c.get('kind') == 'path')}",
        f"- Live critical errors: {sum(1 for c in agg.get('critical_errors', []) if c.get('kind') == 'live')}",
        f"- Live warnings: {s.get('warning_count', 0)}",
        "",
    ]

    def _count_code(prefix: str) -> int:
        return sum(
            c.get("count", 0)
            for c in agg.get("critical_errors", [])
            if str(c.get("code", "")).startswith(prefix)
        )

    lines.extend(
        [
            f"- Safe-wait null params count: {_count_code('ERROR_SAFE_WAIT')}",
            f"- PB11 loop broken count: {_count_code('ERROR_PB11')}",
            f"- Raw trailing display count: {_count_code('ERROR_RAW_TRAILING')}",
            f"- Fee efficiency present count: {_count_code('ERROR_FEE')}",
            f"- Score/class mismatch count: {_count_code('ERROR_FINAL_ID') + _count_code('WARN_DQ')}",
            "",
            "## Critical Errors",
            "",
            "| error_code | count | examples |",
            "|---|---:|---|",
        ]
    )
    for c in agg.get("critical_errors", [])[:40]:
        ex = ", ".join(c.get("examples") or [])[:120]
        lines.append(f"| {c.get('code')} | {c.get('count')} | {ex} |")

    lines.extend(
        [
            "",
            "## Strategy Logic Findings",
            "### R2/V1 low volatility grid width",
            "See WARN_R2_V1_* and WARN_LOW_ACTIVITY_FOR_1WEEK_BOT in warnings.",
            "### R8/PB11 crash loop integrity",
            "See ERROR_PB11_* and ERROR_R8_* codes.",
            "### BTCUSDT double context",
            "See WARN_BTCUSDT_* and ERROR_BTCUSDT_* codes.",
            "### Asset fragility boundary",
            "See WARN_ASSET_FRAGILITY_* codes.",
            "### DQ / volatility score direction mismatch",
            "See WARN_DQ_LABEL_SCORE_MISMATCH and WARN_VOLATILITY_LABEL_SCORE_MISMATCH.",
            "### Fee remnants in V6",
            "See ERROR_FEE_EFFICIENCY_PRESENT_IN_V6.",
            "### Trailing quantization display",
            "See ERROR_RAW_TRAILING_DISPLAYED and ERROR_TRAILING_NOT_IN_LATTICE.",
            "",
            "## Live 50 Symbol Results",
            "",
            "| symbol | regime | behavior | severity | final_profile | base/quote | buy grids | sell grids | rebuy | profit sell | workability | warnings |",
            "|---|---|---|---|---|---|---|---|---|---|---:|---|",
        ]
    )
    for row in (live_rows or [])[:55]:
        lines.append(
            "| {symbol} | {regime} | {behavior_id} | {severity} | {final_profile_id} | {base_pct}/{quote_pct} | "
            "{buy_grids} | {sell_grids} | {rebuy} | {profit_sell} | {workability_score} | {warnings} |".format(
                symbol=row.get("symbol", ""),
                regime=row.get("regime", ""),
                behavior_id=row.get("behavior_id", ""),
                severity=row.get("severity", ""),
                final_profile_id=(str(row.get("final_profile_id") or ""))[:40],
                base_pct=row.get("base_pct", ""),
                quote_pct=row.get("quote_pct", ""),
                buy_grids=row.get("buy_grid_distances", ""),
                sell_grids=row.get("sell_grid_distances", ""),
                rebuy=row.get("rebuy_enabled", ""),
                profit_sell=row.get("profit_sell_enabled", ""),
                workability_score=row.get("workability_score", ""),
                warnings=(str(row.get("warnings") or ""))[:60],
            )
        )

    lines.extend(
        [
            "",
            "## Recommended Fixes by Priority",
            "",
            "### P0",
            "- ERROR_SAFE_WAIT_NULL_PARAMS — V6 must always return params",
            "- ERROR_PB11_LOOP_BROKEN — preserve post-sell rebuy + profit sell on crash profiles",
            "",
            "### P1",
            "- WARN_LOW_ACTIVITY_FOR_1WEEK_BOT — tighten R2/V1 grids for 1-week bots",
            "- ERROR_R8_BUY_GRID_TOO_CLOSE — deepen or disable buys in crash regimes",
            "",
            "### P2",
            "- WARN_BTCUSDT_DOUBLE_CONTEXT — verify btc_context_delta_multiplier 0.5 on BTCUSDT",
            "- ERROR_FEE_EFFICIENCY_PRESENT_IN_V6 — strip V5 fee artifacts from telemetry",
            "",
            "### P3",
            "- WARN_GRID_TOO_WIDE / WARN_GRID_TOO_NARROW — regime-volatility tuning",
            "",
            "## Priority Table",
            "",
            "| Öncelik | Hata | Etki | Örnek | Çözüm |",
            "|---|---|---|---|---|",
            "| P0 | safe_wait params=None | Parametre ekranı bozulur | R8/F3/V5 | V6 always-return params |",
            "| P1 | R2/V1 grid fazla geniş | 1 haftalık bot pasif kalır | AVAXUSDT | grid contraction rule |",
            "| P1 | PB11 loop broken | Crash sonrası kar döngüsü kapanır | PB11 DEF | decouple from normal_buy |",
            "| P2 | BTCUSDT double penalty | Aşırı savunmacı BTC | BTCUSDT | btc_context_delta_multiplier |",
        ]
    )
    return "\n".join(lines) + "\n"


# --- Live simulation helpers ---


def is_leveraged_token_symbol(symbol: str) -> bool:
    base = symbol.upper().replace("USDT", "")
    return bool(LEVERAGED_TOKEN_RE.search(base))


async def fetch_tradable_usdt_symbols() -> List[str]:
    from app.services.binance_rest_log import rest_source
    from app.services.binance_spot import public_get_json

    with rest_source("v6_simulation_live"):
        info = await public_get_json("/api/v3/exchangeInfo", {}, testnet=False)
    out: List[str] = []
    for s in (info or {}).get("symbols") or []:
        if not isinstance(s, dict):
            continue
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        if not s.get("isSpotTradingAllowed", True):
            continue
        sym = str(s.get("symbol") or "").upper()
        if not sym or sym in STABLE_EXCLUDE:
            continue
        if is_leveraged_token_symbol(sym):
            continue
        out.append(sym)
    return sorted(set(out))


def pick_live_symbols(
    pool: Sequence[str],
    *,
    count: int = 50,
    seed: int = 42,
    mandatory: Sequence[str] = MANDATORY_LIVE_SYMBOLS,
) -> List[str]:
    chosen: List[str] = []
    seen: Set[str] = set()
    for sym in mandatory:
        su = sym.upper()
        if su in pool and su not in seen:
            chosen.append(su)
            seen.add(su)
    candidates = [s for s in pool if s not in seen]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    for sym in candidates:
        if len(chosen) >= count:
            break
        chosen.append(sym)
        seen.add(sym)
    return sorted(chosen[:count])


def _trace_class_score(trace: List[Dict[str, Any]], name: str) -> Tuple[Optional[str], Optional[int]]:
    for entry in trace or []:
        if str(entry.get("name") or "") == name:
            return str(entry.get("class") or ""), (
                int(entry.get("score")) if entry.get("score") is not None else None
            )
    return None, None


def _class_score_mismatch(class_label: str, score: Optional[int], adj_name: str) -> bool:
    if score is None or not class_label:
        return False
    if adj_name == "data_quality":
        m = re.match(r"^DQ(\d+)$", class_label)
        if not m:
            return False
        idx = int(m.group(1))
        low = idx * 25
        high = 100 if idx >= 3 else (idx + 1) * 25 - 1
        return not (low <= score <= high)
    if adj_name == "volatility":
        m = re.match(r"^V(\d+)$", class_label)
        if not m:
            return False
        idx = int(m.group(1))
        low = 0 if idx <= 1 else (idx - 1) * 20
        high = 100 if idx >= 5 else idx * 20 - 1
        return not (low <= score <= high)
    if adj_name == "asset_fragility":
        m = re.match(r"^F(\d+)$", class_label)
        if not m:
            return False
        idx = int(m.group(1))
        expected = {0: 10, 1: 25, 2: 55, 3: 85}.get(idx, 25)
        return abs(score - expected) > 20
    return False


def _v6_telemetry_has_fee_artifacts(tel: Dict[str, Any]) -> bool:
    """Scan only user-facing V6 telemetry surfaces for legacy fee fields."""
    surfaces: List[Any] = [
        tel.get("v6_display") or {},
        tel.get("sub_scores") or {},
        tel.get("fee_display") or {},
        tel.get("scenario_alignment") or {},
    ]
    raw = json.dumps(surfaces, ensure_ascii=False).lower()
    banned = (
        "fee_efficiency_score",
        "fee verimi",
        "toplam fee",
        "fee_missing",
        "fee_unreadable",
        "total_friction_pct",
    )
    return any(token in raw for token in banned)


def validate_live_decision(decision: Any, *, symbol: str) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Validate a V6 DynamicParamDecision from live calculate."""
    errors: List[str] = []
    warnings: List[str] = []
    notes: List[str] = []

    tel = decision.telemetry or {}
    if _v6_telemetry_has_fee_artifacts(tel):
        errors.append("ERROR_FEE_EFFICIENCY_PRESENT_IN_V6")
    for token in ("dplv5", "v5_shelf"):
        if token in json.dumps(tel).lower():
            errors.append("ERROR_V5_ARTIFACT_IN_TELEMETRY")

    apply_policy = str(getattr(decision, "apply_policy", "") or tel.get("apply_policy") or "")
    if apply_policy == "safe_wait" and decision.params is None:
        errors.append("ERROR_SAFE_WAIT_NULL_PARAMS")
    if str(tel.get("apply_policy") or "") == "high_risk_controlled" and decision.params is None:
        errors.append("ERROR_SAFE_WAIT_NULL_PARAMS")
    if decision.params is None:
        errors.append("ERROR_NO_PARAMS_FOR_VALID_PROFILE")

    v6d = tel.get("v6_display") or {}
    if not v6d:
        errors.append("ERROR_MISSING_V6_DISPLAY")

    pool_version = getattr(decision.params, "pool_version", None) if decision.params else tel.get("pool_version")
    if pool_version and str(pool_version) != "v6":
        errors.append(f"ERROR_POOL_VERSION:{pool_version}")

    pid = str(v6d.get("profile_id") or decision.selected_profile_name or "")
    if pid and not pid.startswith("DPLV6_"):
        errors.append("ERROR_FINAL_ID_CLASS_SCORE_MISMATCH")

    for trail_key in (
        "buy_trailing_pct",
        "sell_trailing_pct",
        "rebuy_trailing_pct",
        "profit_sell_trailing_pct",
    ):
        tv = v6d.get(trail_key)
        if tv is not None:
            fv = float(tv)
            if fv not in ALLOWED_TRAILING:
                errors.append("ERROR_RAW_TRAILING_DISPLAYED")
                errors.append("ERROR_TRAILING_NOT_IN_LATTICE")

    trace = v6d.get("adjuster_trace") or tel.get("adjuster_trace") or []
    for adj_name in ("data_quality", "volatility", "asset_fragility"):
        cls, score = _trace_class_score(trace, adj_name)
        if _class_score_mismatch(cls or "", score, adj_name):
            errors.append("ERROR_SCORE_CLASS_MISMATCH")
            if adj_name == "data_quality":
                warnings.append("WARN_DQ_LABEL_SCORE_MISMATCH")
            elif adj_name == "volatility":
                warnings.append("WARN_VOLATILITY_LABEL_SCORE_MISMATCH")
            else:
                warnings.append("WARN_ASSET_FRAGILITY_BOUNDARY_DISPLAY")

    if symbol.upper() == "BTCUSDT":
        btc_cls, _ = _trace_class_score(trace, "btc_context")
        if btc_cls in ("B2", "B3"):
            warnings.append("WARN_BTCUSDT_DOUBLE_CONTEXT")
        btc_summary = v6d.get("btc_context") or {}
        mult = btc_summary.get("delta_multiplier")
        if mult is None:
            for entry in trace:
                if entry.get("name") == "btc_context":
                    mult = entry.get("delta_multiplier") or entry.get("btc_context_delta_multiplier")
        if mult is None or float(mult) > 0.55:
            errors.append("ERROR_BTCUSDT_DOUBLE_PENALTY_NOT_GUARDED")

    regime = str((v6d.get("scenario_identity") or {}).get("regime_id") or tel.get("regime_tag") or "")
    behavior = str(v6d.get("behavior_id") or "")
    severity = str(v6d.get("severity") or "")
    base_pct = int(v6d.get("base_allocation_pct") or 0)
    buy_grids = v6d.get("buy_grid_distances_pct") or []
    sell_grids = v6d.get("sell_grid_distances_pct") or []
    buy_n = int(v6d.get("buy_grid_count") or len(buy_grids) or 0)
    sell_n = int(v6d.get("sell_grid_count") or len(sell_grids) or 0)
    normal_buy = bool(v6d.get("normal_buy_enabled"))
    rebuy_on = bool(v6d.get("rebuy_enabled") or v6d.get("post_sell_buyback_enabled"))
    profit_on = bool(v6d.get("profit_sell_enabled") or v6d.get("post_buyback_profit_sell_enabled"))
    vol_cls, _ = _trace_class_score(trace, "volatility")
    liq_cls, _ = _trace_class_score(trace, "liquidity")
    frag_cls, _ = _trace_class_score(trace, "asset_fragility")

    if behavior == "PB11" or regime == "R8":
        if not sell_grids:
            errors.append("ERROR_PB11_LOOP_BROKEN")
        if sell_grids and not rebuy_on:
            errors.append("ERROR_PB11_REBUY_DISABLED")
        if rebuy_on and not profit_on:
            errors.append("ERROR_PB11_PROFIT_SELL_DISABLED")
        operational = (base_pct > 0 and sell_n >= 1) or (normal_buy and buy_n >= 1)
        if not operational:
            errors.append("ERROR_PB11_NON_OPERATIONAL")
        if regime == "R8" and base_pct > 25:
            errors.append("ERROR_R8_BASE_TOO_HIGH")
        if buy_grids and int(buy_grids[0]) > -7:
            errors.append("ERROR_R8_BUY_TOO_CLOSE")

    if base_pct == 0 and buy_n == 0 and sell_n == 0:
        errors.append("ERROR_NON_OPERATIONAL_PARAMS")

    major_symbols = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"}
    if (
        regime == "R6"
        and symbol.upper() in major_symbols
        and frag_cls in ("F0", "F1")
        and vol_cls in ("V1", "V2")
        and liq_cls in ("L0", "L1")
        and (base_pct <= 15 or not buy_grids or len(sell_grids) < 2)
    ):
        warnings.append("WARN_OVER_PROTECTED_R6_MAJOR")

    if (
        regime in ("R2", "R3")
        and vol_cls in ("V1", "V2")
        and frag_cls in ("F0", "F1")
        and liq_cls in ("L0", "L1")
        and buy_grids
        and int(buy_grids[0]) <= -8
    ):
        warnings.append("WARN_R2_V1_LOW_ACTIVITY")

    if (
        regime in ("R2", "R3")
        and vol_cls in ("V1", "V2")
        and frag_cls in ("F0", "F1")
        and liq_cls in ("L0", "L1", None)
        and buy_grids
        and int(buy_grids[0]) <= -8
        and sell_grids
        and int(sell_grids[0]) >= 6
    ):
        warnings.append("WARN_LOW_ACTIVITY_FOR_1WEEK_BOT")
        notes.append("R2/V1: consider tightening grids for 1-week bot")

    if regime in ("R7", "R8") and frag_cls == "F3" and vol_cls in ("V4", "V5"):
        if base_pct > 20 or (buy_grids and int(buy_grids[0]) > -7):
            errors.append("ERROR_HIGH_RISK_TOO_AGGRESSIVE")

    workability = compute_workability_score(
        regime=regime,
        behavior_id=behavior,
        base_pct=base_pct,
        buy_grids=buy_grids,
        sell_grids=sell_grids,
        buy_n=buy_n,
        sell_n=sell_n,
        normal_buy_enabled=normal_buy,
        vol_cls=vol_cls or "",
        rebuy_on=rebuy_on,
        profit_on=profit_on,
        errors=errors,
        warnings=warnings,
        v6d=v6d,
    )
    if (
        base_pct == 0
        and buy_n == 0
        and sell_n == 0
        and workability > 20
    ):
        errors.append("ERROR_WORKABILITY_SCORE_OVERSTATED")

    return errors, warnings, {"workability_score": workability, "logic_notes": "; ".join(notes)}


def compute_workability_score(
    *,
    regime: str,
    behavior_id: str = "",
    base_pct: int,
    buy_grids: Sequence[int],
    sell_grids: Sequence[int],
    buy_n: int = 0,
    sell_n: int = 0,
    normal_buy_enabled: bool = True,
    vol_cls: str,
    rebuy_on: bool,
    profit_on: bool,
    errors: Sequence[str],
    warnings: Sequence[str],
    v6d: Dict[str, Any],
) -> int:
    buy_n = buy_n or (len(buy_grids) if buy_grids else 0)
    sell_n = sell_n or (len(sell_grids) if sell_grids else 0)

    if base_pct == 0 and buy_n == 0 and sell_n == 0:
        return 0
    if not normal_buy_enabled and sell_n == 0:
        return min(20, 0 if errors else 20)
    if buy_n == 0 and sell_n == 0:
        return min(20, 0 if errors else 20)
    if behavior_id == "PB11" and base_pct == 0 and sell_n == 0 and buy_n == 0:
        return 0

    score = 100
    if errors:
        score -= min(60, 15 * len(errors))
    score -= min(25, 5 * len(warnings))

    if buy_grids:
        d1 = abs(int(buy_grids[0]))
        if vol_cls in ("V1", "V2") and d1 > 10:
            score -= 12
        if vol_cls in ("V4", "V5") and d1 < 4:
            score -= 10
    if sell_grids:
        s1 = int(sell_grids[0])
        if vol_cls in ("V1", "V2") and s1 > 8:
            score -= 10
        if vol_cls in ("V4", "V5") and s1 < 3:
            score -= 8

    if regime in ("R7", "R8") and base_pct > 20:
        score -= 15
    if regime in ("R8",) and buy_grids and int(buy_grids[0]) > -7:
        score -= 20
    if rebuy_on and not profit_on:
        score -= 25

    for pk in ("rebuy_trigger_pct", "profit_sell_trigger_pct"):
        tv = v6d.get(pk)
        if tv is not None:
            trail_key = "rebuy_trailing_pct" if "rebuy" in pk else "profit_sell_trailing_pct"
            tr = float(v6d.get(trail_key) or 1.1)
            floor = DEFAULT_COST_FLOOR_PCT + tr + MIN_PROFIT_BUFFER_PCT
            if float(tv) < floor:
                score -= 15

    return max(0, min(100, score))


def decision_to_live_row(decision: Any, *, symbol: str, errors: List[str], warnings: List[str], extras: Dict[str, Any]) -> Dict[str, Any]:
    tel = decision.telemetry or {}
    v6d = tel.get("v6_display") or {}
    scen = v6d.get("scenario_identity") or {}
    trace = v6d.get("adjuster_trace") or []

    def _cls(name: str) -> str:
        c, s = _trace_class_score(trace, name)
        return f"{c}:{s}" if c else ""

    return {
        "symbol": symbol,
        "current_price": tel.get("current_price") or "",
        "regime": scen.get("regime_id") or tel.get("regime_tag") or "",
        "scenario_identity": f"{scen.get('regime_id')}-{scen.get('sub_id')}-{scen.get('micro_id')}",
        "behavior_id": v6d.get("behavior_id") or "",
        "severity": v6d.get("severity") or "",
        "profile_id": v6d.get("profile_id") or decision.selected_profile_name or "",
        "final_profile_id": v6d.get("final_profile_id") or "",
        "apply_policy": tel.get("apply_policy") or getattr(decision, "apply_policy", "") or "",
        "management_mode": tel.get("management_mode") or "",
        "parameter_score": decision.param_score,
        "confidence_score": getattr(decision, "confidence_score", None),
        "base_pct": v6d.get("base_allocation_pct"),
        "quote_pct": v6d.get("quote_allocation_pct"),
        "normal_buy_enabled": v6d.get("normal_buy_enabled"),
        "buy_grid_count": v6d.get("buy_grid_count"),
        "buy_grid_distances": v6d.get("buy_grid_distances_pct"),
        "buy_grid_amounts": v6d.get("buy_grid_amounts_pct"),
        "buy_trailing_pct": v6d.get("buy_trailing_pct"),
        "sell_grid_enabled": v6d.get("sell_grid_enabled"),
        "sell_grid_count": v6d.get("sell_grid_count"),
        "sell_grid_distances": v6d.get("sell_grid_distances_pct"),
        "sell_grid_amounts": v6d.get("sell_grid_amounts_pct"),
        "sell_trailing_pct": v6d.get("sell_trailing_pct"),
        "rebuy_enabled": v6d.get("rebuy_enabled"),
        "rebuy_trigger_pct": v6d.get("rebuy_trigger_pct"),
        "rebuy_trailing_pct": v6d.get("rebuy_trailing_pct"),
        "profit_sell_enabled": v6d.get("profit_sell_enabled"),
        "profit_sell_trigger_pct": v6d.get("profit_sell_trigger_pct"),
        "profit_sell_trailing_pct": v6d.get("profit_sell_trailing_pct"),
        "data_quality_class": _cls("data_quality"),
        "btc_context_class": _cls("btc_context"),
        "asset_fragility_class": _cls("asset_fragility"),
        "volatility_class": _cls("volatility"),
        "liquidity_class": _cls("liquidity"),
        "errors": ";".join(errors),
        "warnings": ";".join(warnings),
        "workability_score": extras.get("workability_score", 0),
        "logic_notes": extras.get("logic_notes", ""),
        "data_fetch_status": "ok",
    }


async def calculate_live_symbol(symbol: str, budget: float = 500.0) -> Any:
    import os

    os.environ["DPS_ENGINE_VERSION"] = "v6"
    from app.services.dynamic_param_score import get_engine
    from app.services.dynamic_param_score.consumer_policy import build_param_assistant_context
    from app.services.dynamic_param_score.data_collector import (
        collect_market_data,
        default_exchange_constraints,
        portfolio_from_budget,
    )

    market = await collect_market_data(symbol)
    price = float(market.ticker_price or 0.0)
    if price <= 0:
        raise RuntimeError(f"{symbol}: invalid price")
    portfolio = portfolio_from_budget(budget, price)
    constraints = default_exchange_constraints(symbol)
    ctx = build_param_assistant_context(
        budget_usdt=budget,
        portfolio=portfolio,
        allow_no_trade=True,
    )
    return get_engine().calculate_decision(
        symbol=symbol,
        market_data=market,
        portfolio_state=portfolio,
        exchange_constraints=constraints,
        bot_context=ctx,
    )
