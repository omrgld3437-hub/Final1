"""
Dynamic Mode Safety Gate.

Current operator policy:
  * max_buy_levels remains mandatory and structural.
  * daily_loss_limit_usd prerequisite/enforcement is disabled.
  * Dynamic stop-loss %8 and emergency-close %15 circuit breakers are disabled.

The disabled logic is kept below behind flags so it can be restored without a
schema migration. While disabled, Dynamic Mode is allowed as long as
max_buy_levels is valid; emergency_check always returns action=NONE.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


# System-defaults injected by Dynamic Mode when active.
# These are CEILINGS — they cap how bad a single cycle / portfolio can get.
DYN_STOP_LOSS_PCT = 8.0  # cycle equity stop: -8% from cycle start equity
DYN_EMERGENCY_CLOSE_PCT = 15.0  # portfolio drop circuit breaker: -15% from initial

# -----------------------------------------------------------------------------
# RISK-BRAKE TOGGLES — DISABLED by configuration (operator request: run without
# the system stop-loss / emergency-close circuit breaker and without the
# daily-loss prerequisite, in BOTH dynamic and manual mode). The logic below is
# kept intact and inert; flip a flag back to True to restore that protection.
# NOTE: `max_buy_levels` (the DCA hard cap) is NOT a toggle — it is structural
# and always enforced.
# -----------------------------------------------------------------------------
EMERGENCY_CHECKS_ENABLED = False   # stop-loss %8 + emergency-close %15 breaker
DAILY_LOSS_PREREQ_ENABLED = False  # require daily_loss_limit_usd>0 for dynamic mode
DAILY_LOSS_RUNTIME_ENABLED = False  # enforce daily_loss_limit_usd in manual/dynamic mode

# DCA-depth guard: the emergency circuit breaker must never fire while price is
# still inside the user's configured buy-grid range — otherwise it would halt
# the bot BEFORE its own deepest buy grid can execute, which directly
# contradicts the DCA plan. The breaker only engages once price has fallen this
# many extra % BEYOND the deepest configured buy grid (i.e. the market went
# past the entire plan). Example: deepest buy grid at -20% + 5% buffer → the
# breaker can only fire once price is ≤ -25% from the cycle reference.
DYN_GRID_DEPTH_BUFFER_PCT = 5.0


def _deepest_buy_grid_pct(cfg_dict: Dict[str, Any]) -> float:
    """Largest buy_grid_pct (% below reference) across the EFFECTIVE buy grids.

    In dynamic mode cfg_dict already carries the overlaid grids, so this is the
    deepest level the bot will actually buy at THIS cycle. Returns 0.0 if none.
    """
    deepest = 0.0
    for g in cfg_dict.get("buy_grids") or []:
        try:
            v = float(g.get("buy_grid_pct") or g.get("trigger_pct") or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        if v > deepest:
            deepest = v
    return deepest


@dataclass
class GateResult:
    ok: bool
    violations: List[str] = field(default_factory=list)
    injected_defaults: Dict[str, Any] = field(default_factory=dict)


def check_prerequisites(cfg_dict: Dict[str, Any]) -> GateResult:
    """
    Check whether a cfg is allowed to have dynamic_mode=True.

    Returns ok=False with a list of missing layers if not. The caller (API)
    should refuse the toggle change with a clear error.
    """
    violations: List[str] = []
    # Layer 1: max_buy_levels must exist and be >= 1
    mbl = cfg_dict.get("max_buy_levels")
    try:
        mbl_i = int(mbl or 0)
    except (TypeError, ValueError):
        mbl_i = 0
    if mbl_i < 1:
        violations.append("max_buy_levels is missing or <1 — required as DCA hard cap")

    # Layer 2: daily_loss_limit_usd must be > 0 — DISABLED (see toggle above).
    if DAILY_LOSS_PREREQ_ENABLED:
        dll = cfg_dict.get("daily_loss_limit_usd")
        try:
            dll_f = float(dll or 0.0)
        except (TypeError, ValueError):
            dll_f = 0.0
        if dll_f <= 0:
            violations.append(
                "daily_loss_limit_usd is missing or <=0 — required as max-drawdown proxy"
            )

    # Layers 3 & 4 (stop-loss / emergency-close) only exist while the breaker is
    # enabled. When disabled we report nothing injected (honest UI/state).
    injected = (
        {
            "stop_loss_pct": DYN_STOP_LOSS_PCT,
            "emergency_close_pct": DYN_EMERGENCY_CLOSE_PCT,
        }
        if EMERGENCY_CHECKS_ENABLED
        else {}
    )

    return GateResult(
        ok=(not violations),
        violations=violations,
        injected_defaults=injected,
    )


def is_dynamic_mode_active(cfg_dict: Dict[str, Any]) -> bool:
    """
    Final gate consulted by the orchestrator: dynamic_mode flag PLUS active
    prerequisites. Current policy only requires max_buy_levels; daily-loss and
    emergency brakes are disabled behind flags.
    """
    from app.utils.parse_utils import parse_bool

    if not parse_bool(cfg_dict.get("dynamic_mode")):
        return False
    return check_prerequisites(cfg_dict).ok


def emergency_check(
    state: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    equity: float,
    price: float = None,
) -> Dict[str, Any]:
    """
    Run the runtime emergency checks. Returns a dict with:
        {"action": "NONE" | "STOP_LOSS" | "EMERGENCY_CLOSE", "reason": str, "metrics": {...}}

    When EMERGENCY_CHECKS_ENABLED is False, this always returns action=NONE.
    If re-enabled later, both non-NONE actions mean the SAME thing
    operationally: PAUSE the bot and alert the operator; neither liquidates the
    position.

    DCA-DEPTH GUARD (critical): the breaker must let the bot execute its FULL
    configured DCA plan. While price is still within the deepest buy grid (plus
    DYN_GRID_DEPTH_BUFFER_PCT) of the cycle reference, this returns NONE no
    matter how far equity has dropped — otherwise the breaker could halt the bot
    before its own -X% buy grid ever fires, contradicting the strategy. The
    equity/portfolio thresholds below only apply once price is BEYOND the plan.
    (`price` is the current price; when omitted the guard is skipped and the
    legacy equity-only behaviour applies — kept for unit tests / safety.)

    daily_loss_limit_usd enforcement is controlled separately by
    DAILY_LOSS_RUNTIME_ENABLED and is currently disabled for both manual and
    dynamic mode.

    If re-enabled later, these checks ONLY trigger when dynamic_mode is active
    (caller responsibility to gate the call). The thresholds are system
    defaults; we don't reach into user config for them.
    """
    out = {"action": "NONE", "reason": "", "metrics": {}}
    # Circuit breaker disabled by configuration → never halt (logic below kept
    # intact and reversible via EMERGENCY_CHECKS_ENABLED).
    if not EMERGENCY_CHECKS_ENABLED:
        return out
    if not is_dynamic_mode_active(cfg_dict):
        return out

    # ---- DCA-depth guard: never halt while still inside the configured plan ----
    ref_price = float(state.get("reference_price") or 0.0)
    deepest_buy_pct = _deepest_buy_grid_pct(cfg_dict)
    if price is not None and float(price) > 0 and ref_price > 0 and deepest_buy_pct > 0:
        price_drop_pct = (ref_price - float(price)) / ref_price * 100.0
        guard_pct = deepest_buy_pct + DYN_GRID_DEPTH_BUFFER_PCT
        if price_drop_pct < guard_pct:
            out["metrics"] = {
                "within_grid_plan": True,
                "price_drop_pct": round(price_drop_pct, 4),
                "deepest_buy_grid_pct": deepest_buy_pct,
                "guard_pct": round(guard_pct, 4),
            }
            return out

    cycle_start = float(state.get("cycle_start_equity") or 0.0)
    init_capital = float(cfg_dict.get("initial_capital_usdt") or 0.0)

    # ---- Stop-loss (cycle level) ----
    if cycle_start > 0:
        cycle_drop_pct = (cycle_start - equity) / cycle_start * 100.0
        if cycle_drop_pct >= DYN_STOP_LOSS_PCT:
            out["action"] = "STOP_LOSS"
            out["reason"] = (
                f"Risk circuit breaker (cycle): equity dropped "
                f"{cycle_drop_pct:.2f}% ≥ {DYN_STOP_LOSS_PCT}% this cycle — bot "
                f"paused, position retained (operator action required)"
            )
            out["metrics"] = {
                "cycle_drop_pct": round(cycle_drop_pct, 4),
                "threshold_pct": DYN_STOP_LOSS_PCT,
                "cycle_start_equity": cycle_start,
                "equity": equity,
            }
            return out

    # ---- Emergency close (portfolio level) ----
    if init_capital > 0:
        port_drop_pct = (init_capital - equity) / init_capital * 100.0
        if port_drop_pct >= DYN_EMERGENCY_CLOSE_PCT:
            out["action"] = "EMERGENCY_CLOSE"
            out["reason"] = (
                f"Risk circuit breaker (portfolio): equity dropped "
                f"{port_drop_pct:.2f}% ≥ {DYN_EMERGENCY_CLOSE_PCT}% from initial "
                f"capital — bot paused, position retained (operator action required)"
            )
            out["metrics"] = {
                "portfolio_drop_pct": round(port_drop_pct, 4),
                "threshold_pct": DYN_EMERGENCY_CLOSE_PCT,
                "initial_capital": init_capital,
                "equity": equity,
            }
            return out

    return out
