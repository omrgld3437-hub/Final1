"""
DCA grid trailing: preflight validation (budget × grid % vs min notional).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.botengine.models import DcaGridTrailingConfig, config_from_ui_payload

# UI / Binance güvenli alt sınır: grid başına tahmini emir tutarı (USDT)
MIN_GRID_NOTIONAL_USDT = 10.0


def _num(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _grid_qty_fraction(raw: Any, default: float = 10.0) -> float:
    """qty_pct / sell_qty_pct: 40 => 0.40 (strategy ile aynı: /100)."""
    v = _num(raw, default)
    if v <= 0:
        return 0.0
    return v / 100.0


def _notional_floor(
    cfg: DcaGridTrailingConfig, min_usdt: Optional[float] = None
) -> float:
    floor = max(MIN_GRID_NOTIONAL_USDT, _num(min_usdt, MIN_GRID_NOTIONAL_USDT))
    return max(floor, _num(getattr(cfg, "min_notional_guard", 5.0), 5.0))


def _buffer_factor(cfg: DcaGridTrailingConfig) -> float:
    return max(0.0, 1.0 - _num(cfg.available_quote_buffer_pct, 0.005))


def _min_budget_for_leg(
    side_alloc_pct: float, qty_pct: float, buffer: float, floor: float
) -> Optional[float]:
    side_frac = _num(side_alloc_pct) / 100.0
    qty_frac = _grid_qty_fraction(qty_pct, 0)
    denom = side_frac * qty_frac * buffer
    if denom <= 0:
        return None
    return math.ceil((floor + 0.001) / denom * 100.0) / 100.0


def compute_min_budget_usdt(
    cfg: DcaGridTrailingConfig, min_usdt: Optional[float] = None
) -> Optional[float]:
    floor = _notional_floor(cfg, min_usdt)
    buffer = _buffer_factor(cfg)
    candidates: List[float] = []
    for g in cfg.sell_grids or []:
        qty_pct = g.get("sell_qty_pct_of_base") or g.get("qty_pct")
        leg_min = _min_budget_for_leg(cfg.base_alloc_pct, qty_pct, buffer, floor)
        if leg_min is not None:
            candidates.append(leg_min)
    for g in cfg.buy_grids or []:
        qty_pct = g.get("buy_qty_pct_of_quote") or g.get("qty_pct")
        leg_min = _min_budget_for_leg(cfg.quote_alloc_pct, qty_pct, buffer, floor)
        if leg_min is not None:
            candidates.append(leg_min)
    if not candidates:
        return None
    return max(candidates)


def estimate_dca_grid_notionals(cfg: DcaGridTrailingConfig) -> List[Dict[str, Any]]:
    """
    Tahmini grid emir tutarları (USDT). Initial allocation sonrası referans ≈ bütçe × alloc.
    available_quote_buffer_pct düşülür (muhafazakâr).
    """
    budget = max(0.0, _num(cfg.initial_capital_usdt))
    base_usd = budget * _num(cfg.base_alloc_pct, 50.0) / 100.0
    quote_usd = budget * _num(cfg.quote_alloc_pct, 50.0) / 100.0
    buffer = _buffer_factor(cfg)
    base_usd *= buffer
    quote_usd *= buffer
    out: List[Dict[str, Any]] = []
    for i, g in enumerate(cfg.sell_grids or []):
        frac = _grid_qty_fraction(g.get("sell_qty_pct_of_base") or g.get("qty_pct"))
        if frac <= 0:
            continue
        out.append(
            {
                "side": "sell",
                "index": i,
                "notional_usdt": round(base_usd * frac, 4),
                "qty_pct": round(frac * 100.0, 2),
            }
        )
    for j, g in enumerate(cfg.buy_grids or []):
        frac = _grid_qty_fraction(g.get("buy_qty_pct_of_quote") or g.get("qty_pct"))
        if frac <= 0:
            continue
        out.append(
            {
                "side": "buy",
                "index": j,
                "notional_usdt": round(quote_usd * frac, 4),
                "qty_pct": round(frac * 100.0, 2),
            }
        )
    return out


def validate_dca_grid_notionals(
    cfg: DcaGridTrailingConfig,
    min_usdt: Optional[float] = None,
) -> Tuple[bool, str, List[Dict[str, Any]], Optional[float]]:
    """
    Her grid emri min_usdt üzerinde olmalı (> min, eşitlik dahil red).
    Returns (ok, turkish_message, violations, min_budget_usdt).
    """
    floor = _notional_floor(cfg, min_usdt)
    violations: List[Dict[str, Any]] = []
    for row in estimate_dca_grid_notionals(cfg):
        if row["notional_usdt"] <= floor:
            violations.append({**row, "min_required_usdt": floor})
    if not violations:
        return True, "", [], None
    min_budget = compute_min_budget_usdt(cfg, min_usdt)
    msg = format_grid_notional_error(
        violations, floor, min_budget, _num(cfg.initial_capital_usdt)
    )
    return False, msg, violations, min_budget


def format_grid_notional_error(
    violations: List[Dict[str, Any]],
    min_usdt: float,
    min_budget_usdt: Optional[float] = None,
    current_budget_usdt: Optional[float] = None,
) -> str:
    parts = [
        "Bot oluşturulamaz: en az bir grid emri 10 USDT altında kalıyor (Binance limiti).",
    ]
    for v in violations:
        label = "Satış" if v.get("side") == "sell" else "Alım"
        idx = int(v.get("index", 0)) + 1
        n = _num(v.get("notional_usdt"))
        pct = _num(v.get("qty_pct"))
        parts.append(
            f"{label} grid #{idx}: tahmini {n:.2f} USDT (grid başına en az {min_usdt:.0f} USDT gerekir, miktar %{pct:.0f})."
        )
    if min_budget_usdt is not None and min_budget_usdt > 0:
        cur = _num(current_budget_usdt)
        parts.append(
            f"Bu parametrelerle bot için minimum bütçe: {min_budget_usdt:.2f} USDT"
            + (f" (girdiğiniz: {cur:.2f} USDT)." if cur > 0 else ".")
        )
    else:
        parts.append(
            "Bütçeyi artırın, grid sayısını azaltın veya grid miktar yüzdelerini yükseltin."
        )
    return " ".join(parts)


def validate_dca_payload(
    payload: Dict[str, Any],
) -> Tuple[bool, str, List[Dict[str, Any]], Optional[float]]:
    """UI/API ham payload → DcaGridTrailingConfig → grid notional kontrolü."""
    try:
        cfg = config_from_ui_payload(payload or {})
    except Exception as exc:
        return False, str(exc), [], None
    return validate_dca_grid_notionals(cfg)
