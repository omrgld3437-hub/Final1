"""
Dynamic Mode Safety Gate.

A bot may only operate in Dynamic Mode while ALL FOUR safety layers are present:

  1. max_buy_levels      (DCA hard cap; already in project)
  2. daily_loss_limit_usd (max drawdown proxy; already in project)
  3. stop_loss_pct        (cycle-level protective PAUSE; INJECTED by Dynamic Mode)
  4. emergency_close_pct  (portfolio-level protective PAUSE; INJECTED)

Layers 3 and 4 are not user-tunable: when dynamic_mode is True they are AUTO
applied with system defaults that the user cannot disable from the UI. This
matches the design rule that Dynamic Mode does not relax safety — it can only
make it stricter or leave it alone.

IMPORTANT — what "emergency" does (and does NOT) do:
  These thresholds are *circuit breakers*: when hit, the bot is PAUSED
  (status=paused_error) and the operator is alerted. The position is RETAINED —
  nothing is auto-liquidated. This is intentional and matches every other risk
  event in the project (daily_loss_limit, missing API keys, … all pause; only an
  explicit bot *delete* flattens the position). For a DCA / grid mean-reversion
  strategy this is the correct behaviour: force-selling base at a drawdown low
  would lock in the maximum loss and destroy the recovery path the strategy is
  built on. "STOP_LOSS"/"EMERGENCY_CLOSE" are kept as stable internal action
  keys (error codes DYN_STOP_LOSS / DYN_EMERGENCY_CLOSE) — they mean "halt
  trading", not "sell the position".

The gate runs:
  * at config save (update-config / create) — refused if invalid
  * at orchestrator hook (every cycle start) — if a violation slips in, dynamic
    mode is SILENTLY DEACTIVATED for that cycle and the bot falls back to
    manual cfg (never crashes).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


# System-defaults injected by Dynamic Mode when active.
# These are CEILINGS — they cap how bad a single cycle / portfolio can get.
DYN_STOP_LOSS_PCT = 8.0  # cycle equity stop: -8% from cycle start equity
DYN_EMERGENCY_CLOSE_PCT = 15.0  # portfolio drop circuit breaker: -15% from initial

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

    # Layer 2: daily_loss_limit_usd must be > 0
    dll = cfg_dict.get("daily_loss_limit_usd")
    try:
        dll_f = float(dll or 0.0)
    except (TypeError, ValueError):
        dll_f = 0.0
    if dll_f <= 0:
        violations.append(
            "daily_loss_limit_usd is missing or <=0 — required as max-drawdown proxy"
        )

    # Layers 3 & 4 are injected automatically — they always 'pass' since we
    # supply them. We just report what we'll inject for transparency.
    injected = {
        "stop_loss_pct": DYN_STOP_LOSS_PCT,
        "emergency_close_pct": DYN_EMERGENCY_CLOSE_PCT,
    }

    return GateResult(
        ok=(not violations),
        violations=violations,
        injected_defaults=injected,
    )


def is_dynamic_mode_active(cfg_dict: Dict[str, Any]) -> bool:
    """
    Final gate consulted by the orchestrator: dynamic_mode flag PLUS
    prerequisites still met. If the flag is True but a prerequisite was
    removed (e.g. daily_loss_limit_usd zeroed out via update-config), we
    treat the bot as if dynamic_mode were False — safe degradation.
    """
    if not bool(cfg_dict.get("dynamic_mode")):
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

    Both non-NONE actions mean the SAME thing operationally: PAUSE the bot
    (circuit breaker) and alert the operator. Neither liquidates the position —
    see the module docstring. The two actions differ only in WHAT tripped:
    STOP_LOSS = single-cycle equity drop, EMERGENCY_CLOSE = portfolio-level drop
    from initial capital (catches a slow bleed across many cycles).

    DCA-DEPTH GUARD (critical): the breaker must let the bot execute its FULL
    configured DCA plan. While price is still within the deepest buy grid (plus
    DYN_GRID_DEPTH_BUFFER_PCT) of the cycle reference, this returns NONE no
    matter how far equity has dropped — otherwise the breaker could halt the bot
    before its own -X% buy grid ever fires, contradicting the strategy. The
    equity/portfolio thresholds below only apply once price is BEYOND the plan.
    (`price` is the current price; when omitted the guard is skipped and the
    legacy equity-only behaviour applies — kept for unit tests / safety.)

    The user-set daily_loss_limit_usd is a SEPARATE, ungated capital floor
    (checked by the orchestrator), so capital protection still exists even while
    this breaker is held back inside the grid plan.

    These checks ONLY trigger when dynamic_mode is active (caller responsibility
    to gate the call). The thresholds are system defaults; we don't reach into
    user config for them. This means the bot still gets protection even if the
    user forgot to set them in manual mode — but ONLY while dynamic_mode is on.
    """
    out = {"action": "NONE", "reason": "", "metrics": {}}
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
