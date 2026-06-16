"""
Dynamic Mode Risk Engine — final clamp / sanity filter before any suggestion is
allowed to influence the cycle.

Hard rules:
  * Every numeric value MUST land inside a system-defined hard bound. Anything
    outside is clamped to the boundary (NOT rejected silently) and a `clamps`
    entry is logged so the operator can see it.
  * NaN / Inf / negative / None for fields that must be positive → fallback to
    the corresponding manual value (base_cfg). This guarantees that even a
    catastrophically broken suggestion lands at "as if dynamic mode was off".
  * Rate-of-change limiter: across cycles, scalar params may move at most
    MAX_RELATIVE_CHANGE × prev_value. Sudden 5x jumps are clipped.
  * Risk engine NEVER lifts or relaxes max_buy_levels, daily_loss_limit_usd,
    stop-loss, or emergency close. Those fields are read-only from here.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.botengine.dynamic.strategy_engine import ParamSuggestion


# ---- Hard bounds (system-defined; NOT user-tunable) ------------------------

BOUNDS = {
    "base_alloc_pct": (10.0, 80.0),
    "quote_alloc_pct": (20.0, 90.0),
    "grid_step_pct": (0.10, 8.0),  # individual sell_grid_pct / buy_grid_pct
    "grid_qty_pct": (1.0, 100.0),  # individual qty distribution
    "trailing_pct": (0.15, 5.0),
    "profit_exit_rise_pct": (0.30, 15.0),
    "profit_exit_drop_pct": (0.10, 5.0),
    "profit_reentry_drop_pct": (0.30, 15.0),
    "profit_reentry_rise_pct": (0.10, 5.0),
}

# Rate-of-change: a scalar parameter cannot move more than 60% in one cycle.
MAX_RELATIVE_CHANGE = 0.6

# Distribution growth hard cap (anti-martingale)
GRID_GROWTH_R_MAX = 1.5


@dataclass
class ClampedParams:
    base_alloc_pct: float
    quote_alloc_pct: float
    sell_grids: List[Dict[str, float]]
    buy_grids: List[Dict[str, float]]
    sell_trigger_trailing_pct: float
    buy_trigger_trailing_pct: float
    profit_exit_rise_pct: float
    profit_exit_drop_pct: float
    profit_reentry_drop_pct: float
    profit_reentry_rise_pct: float
    clamps: List[str] = field(default_factory=list)
    fallbacks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_alloc_pct": self.base_alloc_pct,
            "quote_alloc_pct": self.quote_alloc_pct,
            "sell_grids": self.sell_grids,
            "buy_grids": self.buy_grids,
            "sell_trigger_trailing_pct": self.sell_trigger_trailing_pct,
            "buy_trigger_trailing_pct": self.buy_trigger_trailing_pct,
            "profit_exit_rise_pct": self.profit_exit_rise_pct,
            "profit_exit_drop_pct": self.profit_exit_drop_pct,
            "profit_reentry_drop_pct": self.profit_reentry_drop_pct,
            "profit_reentry_rise_pct": self.profit_reentry_rise_pct,
            "clamps": list(self.clamps),
            "fallbacks": list(self.fallbacks),
        }


# ---- helpers ---------------------------------------------------------------


def _finite(v: Any) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _clamp_scalar(
    value: Any,
    bound_key: str,
    fallback: float,
    clamps: List[str],
    fallbacks: List[str],
    field_name: str,
) -> float:
    lo, hi = BOUNDS[bound_key]
    if not _finite(value) or float(value) <= 0:
        fallbacks.append(f"{field_name}: invalid ({value!r}) → fallback={fallback}")
        value = fallback
    v = float(value)
    if v < lo:
        clamps.append(f"{field_name}: {v} < {lo} → {lo}")
        v = lo
    elif v > hi:
        clamps.append(f"{field_name}: {v} > {hi} → {hi}")
        v = hi
    return round(v, 4)


def _apply_rate_limit(
    name: str,
    new_v: float,
    prev_v: Optional[float],
    clamps: List[str],
) -> float:
    if prev_v is None or not _finite(prev_v) or float(prev_v) <= 0:
        return new_v
    p = float(prev_v)
    max_delta = MAX_RELATIVE_CHANGE * p
    if abs(new_v - p) > max_delta:
        capped = p + (max_delta if new_v > p else -max_delta)
        clamps.append(
            f"{name}: rate-limited from {p:.4f}→{new_v:.4f} clipped to {capped:.4f}"
        )
        return round(capped, 4)
    return new_v


def _clamp_grids(
    grids: List[Dict[str, float]],
    fallback: List[Dict[str, Any]],
    pct_key: str,
    qty_key: str,
    clamps: List[str],
    fallbacks: List[str],
    side: str,
) -> List[Dict[str, float]]:
    if not grids:
        fallbacks.append(f"{side}_grids: empty → using manual fallback")
        return [dict(g) for g in (fallback or [])]
    out: List[Dict[str, float]] = []
    for i, g in enumerate(grids):
        pct = g.get(pct_key)
        qty = g.get(qty_key)
        pct_clamped = _clamp_scalar(
            pct, "grid_step_pct", 1.0, clamps, fallbacks, f"{side}_grids[{i}].{pct_key}"
        )
        qty_clamped = _clamp_scalar(
            qty, "grid_qty_pct", 10.0, clamps, fallbacks, f"{side}_grids[{i}].{qty_key}"
        )
        out.append({pct_key: pct_clamped, qty_key: qty_clamped})
    # Enforce monotone non-decreasing trigger %: level i+1 ≥ level i
    for i in range(1, len(out)):
        if out[i][pct_key] < out[i - 1][pct_key]:
            new_v = out[i - 1][pct_key]
            clamps.append(
                f"{side}_grids[{i}].{pct_key} non-monotone → bumped to {new_v}"
            )
            out[i][pct_key] = new_v
    # Anti-martingale: ratio cap on qty distribution (consecutive)
    for i in range(1, len(out)):
        prev_qty = out[i - 1][qty_key]
        cur_qty = out[i][qty_key]
        if prev_qty > 0 and cur_qty / prev_qty > GRID_GROWTH_R_MAX:
            capped = round(prev_qty * GRID_GROWTH_R_MAX, 4)
            clamps.append(
                f"{side}_grids[{i}].{qty_key} growth ratio {cur_qty / prev_qty:.2f}>cap "
                f"{GRID_GROWTH_R_MAX} → {capped}"
            )
            out[i][qty_key] = capped
    return out


# ---- main entry ------------------------------------------------------------


def apply_safety(
    suggestion: ParamSuggestion,
    base_cfg: Dict[str, Any],
    prev_applied: Optional[Dict[str, Any]] = None,
) -> ClampedParams:
    """
    Run the full safety pipeline on a suggestion.

    Pipeline order:
      1. NaN / invalid → fallback to base_cfg value
      2. Hard bound clamp (system-defined)
      3. Rate-of-change limiter vs prev_applied
      4. Allocation normalize (base+quote==100)
      5. Grid monotonicity & anti-martingale
    """
    clamps: List[str] = []
    fallbacks: List[str] = []

    # ---- Allocation pair ----
    base = _clamp_scalar(
        suggestion.base_alloc_pct,
        "base_alloc_pct",
        float(base_cfg.get("base_alloc_pct") or 50.0),
        clamps,
        fallbacks,
        "base_alloc_pct",
    )
    base = _apply_rate_limit(
        "base_alloc_pct",
        base,
        (prev_applied or {}).get("base_alloc_pct"),
        clamps,
    )
    base = max(BOUNDS["base_alloc_pct"][0], min(BOUNDS["base_alloc_pct"][1], base))
    quote = round(100.0 - base, 4)
    # Sanity: also ensure quote within its own bound (typically true given base bound)
    if quote < BOUNDS["quote_alloc_pct"][0]:
        clamps.append(
            f"quote_alloc_pct {quote} < {BOUNDS['quote_alloc_pct'][0]} → adjusted"
        )
        quote = BOUNDS["quote_alloc_pct"][0]
        base = round(100.0 - quote, 4)

    # ---- Trailing ----
    sell_trail = _clamp_scalar(
        suggestion.sell_trigger_trailing_pct,
        "trailing_pct",
        float(base_cfg.get("sell_trigger_trailing_pct") or 0.3),
        clamps,
        fallbacks,
        "sell_trigger_trailing_pct",
    )
    sell_trail = _apply_rate_limit(
        "sell_trigger_trailing_pct",
        sell_trail,
        (prev_applied or {}).get("sell_trigger_trailing_pct"),
        clamps,
    )
    buy_trail = _clamp_scalar(
        suggestion.buy_trigger_trailing_pct,
        "trailing_pct",
        float(base_cfg.get("buy_trigger_trailing_pct") or 0.3),
        clamps,
        fallbacks,
        "buy_trigger_trailing_pct",
    )
    buy_trail = _apply_rate_limit(
        "buy_trigger_trailing_pct",
        buy_trail,
        (prev_applied or {}).get("buy_trigger_trailing_pct"),
        clamps,
    )

    # ---- TP / re-entry ----
    pe_rise = _clamp_scalar(
        suggestion.profit_exit_rise_pct,
        "profit_exit_rise_pct",
        float(base_cfg.get("profit_exit_rise_pct") or 1.0),
        clamps,
        fallbacks,
        "profit_exit_rise_pct",
    )
    pe_rise = _apply_rate_limit(
        "profit_exit_rise_pct",
        pe_rise,
        (prev_applied or {}).get("profit_exit_rise_pct"),
        clamps,
    )
    pe_drop = _clamp_scalar(
        suggestion.profit_exit_drop_pct,
        "profit_exit_drop_pct",
        float(base_cfg.get("profit_exit_drop_pct") or 0.3),
        clamps,
        fallbacks,
        "profit_exit_drop_pct",
    )
    pe_drop = _apply_rate_limit(
        "profit_exit_drop_pct",
        pe_drop,
        (prev_applied or {}).get("profit_exit_drop_pct"),
        clamps,
    )
    pr_drop = _clamp_scalar(
        suggestion.profit_reentry_drop_pct,
        "profit_reentry_drop_pct",
        float(base_cfg.get("profit_reentry_drop_pct") or 1.0),
        clamps,
        fallbacks,
        "profit_reentry_drop_pct",
    )
    pr_drop = _apply_rate_limit(
        "profit_reentry_drop_pct",
        pr_drop,
        (prev_applied or {}).get("profit_reentry_drop_pct"),
        clamps,
    )
    pr_rise = _clamp_scalar(
        suggestion.profit_reentry_rise_pct,
        "profit_reentry_rise_pct",
        float(base_cfg.get("profit_reentry_rise_pct") or 0.3),
        clamps,
        fallbacks,
        "profit_reentry_rise_pct",
    )
    pr_rise = _apply_rate_limit(
        "profit_reentry_rise_pct",
        pr_rise,
        (prev_applied or {}).get("profit_reentry_rise_pct"),
        clamps,
    )

    # ---- Grids ----
    sell_grids = _clamp_grids(
        suggestion.sell_grids,
        base_cfg.get("sell_grids") or [],
        "sell_grid_pct",
        "sell_qty_pct_of_base",
        clamps,
        fallbacks,
        "sell",
    )
    buy_grids = _clamp_grids(
        suggestion.buy_grids,
        base_cfg.get("buy_grids") or [],
        "buy_grid_pct",
        "buy_qty_pct_of_quote",
        clamps,
        fallbacks,
        "buy",
    )

    return ClampedParams(
        base_alloc_pct=base,
        quote_alloc_pct=quote,
        sell_grids=sell_grids,
        buy_grids=buy_grids,
        sell_trigger_trailing_pct=sell_trail,
        buy_trigger_trailing_pct=buy_trail,
        profit_exit_rise_pct=pe_rise,
        profit_exit_drop_pct=pe_drop,
        profit_reentry_drop_pct=pr_drop,
        profit_reentry_rise_pct=pr_rise,
        clamps=clamps,
        fallbacks=fallbacks,
    )
