"""Eligible-grid resolution and atomic in-memory update coordination."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .models import (
    DynamicParameterCandidate,
    GridRuntimeState,
    GridSnapshot,
    ZERO,
    decimal_value,
)


D = Decimal


LEGACY_STATUS_MAP = {
    "WAITING_TRIGGER": GridRuntimeState.WAITING_UNTRIGGERED,
    "WAITING_UNTRIGGERED": GridRuntimeState.WAITING_UNTRIGGERED,
    "TRIGGERED": GridRuntimeState.TRIGGERED,
    "TRAILING": GridRuntimeState.TRAILING_ACTIVE,
    "TRAILING_ACTIVE": GridRuntimeState.TRAILING_ACTIVE,
    "SUBMITTING": GridRuntimeState.ORDER_SUBMITTING,
    "ORDER_SUBMITTING": GridRuntimeState.ORDER_SUBMITTING,
    "SENT": GridRuntimeState.ORDER_OPEN,
    "SUBMITTED": GridRuntimeState.ORDER_OPEN,
    "ORDER_SUBMITTED": GridRuntimeState.ORDER_OPEN,
    "ORDER_OPEN": GridRuntimeState.ORDER_OPEN,
    "PARTIAL": GridRuntimeState.PARTIALLY_FILLED,
    "PARTIALLY_FILLED": GridRuntimeState.PARTIALLY_FILLED,
    "FILLED": GridRuntimeState.FILLED,
    "COMPLETED": GridRuntimeState.COMPLETED,
    "CANCELLED": GridRuntimeState.CANCELED_PENDING_RECONCILIATION,
    "CANCELED": GridRuntimeState.CANCELED_PENDING_RECONCILIATION,
    "UNKNOWN": GridRuntimeState.ERROR_RECONCILIATION,
}


class EligibleGridResolver:
    """Maps the real strategy state to the stricter V2 state vocabulary."""

    @staticmethod
    def _number(value: Any, default: str = "0") -> Decimal:
        try:
            return decimal_value(value)
        except ValueError:
            return D(default)

    def resolve_side(
        self,
        state: Mapping[str, Any],
        grids: Sequence[Mapping[str, Any]],
        side: str,
    ) -> List[GridSnapshot]:
        side_lower = side.lower()
        statuses = list(state.get(f"{side_lower}_grid_status") or [])
        fired = list(state.get(f"{side_lower}_grid_fired") or [])
        trigger_prices = list(
            state.get(f"{side_lower}_grid_trigger_price") or []
        )
        history = list(state.get(f"{side_lower}_history") or [])
        fill_by_index: Dict[int, Decimal] = {}
        for row in history:
            if not isinstance(row, Mapping) or row.get("grid_index") is None:
                continue
            index = int(row["grid_index"])
            qty = self._number(row.get("qty"))
            if side.upper() == "BUY":
                qty *= self._number(row.get("price"))
            fill_by_index[index] = fill_by_index.get(index, ZERO) + qty

        result: List[GridSnapshot] = []
        for index, grid in enumerate(grids):
            raw_status = (
                str(statuses[index]).upper()
                if index < len(statuses) and statuses[index]
                else "WAITING_TRIGGER"
            )
            runtime = LEGACY_STATUS_MAP.get(
                raw_status, GridRuntimeState.ERROR_RECONCILIATION
            )
            is_fired = bool(fired[index]) if index < len(fired) else False
            trigger_set = (
                index < len(trigger_prices)
                and trigger_prices[index] is not None
            )
            if is_fired:
                runtime = GridRuntimeState.COMPLETED
            elif trigger_set or runtime == GridRuntimeState.TRAILING_ACTIVE:
                runtime = GridRuntimeState.TRAILING_ACTIVE
            elif runtime == GridRuntimeState.WAITING_UNTRIGGERED:
                runtime = GridRuntimeState.WAITING_UNTRIGGERED

            trigger_key = (
                "buy_grid_pct" if side.upper() == "BUY" else "sell_grid_pct"
            )
            amount_key = (
                "buy_qty_pct_of_quote"
                if side.upper() == "BUY"
                else "sell_qty_pct_of_base"
            )
            dynamic_amount = grid.get("dynamic_amount")
            if dynamic_amount is not None:
                amount = self._number(dynamic_amount)
            else:
                percentage = self._number(
                    grid.get(amount_key, grid.get("qty_pct", 0))
                ) / D("100")
                reference_balance = self._number(
                    state.get(
                        "grid_reference_quote"
                        if side.upper() == "BUY"
                        else "grid_reference_base"
                    )
                    or state.get(
                        "quote_balance"
                        if side.upper() == "BUY"
                        else "base_balance"
                    )
                )
                amount = reference_balance * percentage
            protected = (
                max(ZERO, amount - fill_by_index.get(index, ZERO))
                if runtime
                not in (
                    GridRuntimeState.WAITING_UNTRIGGERED,
                    GridRuntimeState.COMPLETED,
                    GridRuntimeState.FILLED,
                )
                else ZERO
            )
            result.append(
                GridSnapshot(
                    grid_id=f"{side.upper()}:{index}",
                    side=side.upper(),
                    index=index,
                    status=runtime,
                    trigger_percentage=self._number(
                        grid.get(trigger_key, grid.get("trigger_pct", 0))
                    ),
                    amount=amount,
                    filled_amount=fill_by_index.get(index, ZERO),
                    protected_amount=protected,
                )
            )
        return result

    def resolve(
        self,
        state: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> Tuple[List[GridSnapshot], List[GridSnapshot]]:
        return (
            self.resolve_side(
                state, list(config.get("buy_grids") or []), "BUY"
            ),
            self.resolve_side(
                state, list(config.get("sell_grids") or []), "SELL"
            ),
        )


class ExchangeReconciliationEngine:
    """Fail-closed reconciliation verdict consumed immediately before update."""

    NON_FINAL = {
        "PENDING",
        "PERSISTED",
        "SUBMITTING",
        "SENT",
        "SUBMITTED",
        "ACKED",
        "PARTIAL",
        "PARTIALLY_FILLED",
        "UNKNOWN",
    }

    def check(
        self,
        *,
        exchange_connected: bool,
        unresolved_intents: Sequence[Mapping[str, Any]],
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if not exchange_connected:
            reasons.append("EXCHANGE_DISCONNECTED")
        statuses = {
            str(intent.get("status") or "").upper()
            for intent in unresolved_intents
        }
        if "UNKNOWN" in statuses:
            reasons.append("ORDER_STATUS_UNKNOWN")
        if statuses & self.NON_FINAL:
            reasons.append("ORDER_IN_FLIGHT")
        return not reasons, reasons


class GridUpdateCoordinator:
    """All-or-nothing, state-versioned update for virtual waiting grids."""

    def __init__(self, resolver: Optional[EligibleGridResolver] = None):
        self.resolver = resolver or EligibleGridResolver()

    @staticmethod
    def _apply_side(
        grids: List[Dict[str, Any]],
        snapshots: Sequence[GridSnapshot],
        candidate_triggers: Sequence[Decimal],
        candidate_amounts: Sequence[Decimal],
        *,
        side: str,
    ) -> int:
        trigger_key = "buy_grid_pct" if side == "BUY" else "sell_grid_pct"
        changed = 0
        for snapshot, trigger, amount in zip(
            snapshots, candidate_triggers, candidate_amounts
        ):
            if snapshot.status != GridRuntimeState.WAITING_UNTRIGGERED:
                continue
            row = grids[snapshot.index]
            row[trigger_key] = float(trigger)
            row["dynamic_amount"] = float(amount)
            row["dynamic_amount_unit"] = (
                "QUOTE" if side == "BUY" else "BASE"
            )
            changed += 1
        return changed

    def apply(
        self,
        state: Dict[str, Any],
        current_config: Mapping[str, Any],
        candidate: DynamicParameterCandidate,
        *,
        expected_state_version: int,
        reconciliation_ok: bool,
    ) -> Dict[str, Any]:
        if not candidate.validation_result.valid:
            return {
                "applied": False,
                "reason": "CANDIDATE_INVALID",
                "errors": list(candidate.validation_result.errors),
            }
        if not reconciliation_ok:
            return {"applied": False, "reason": "RECONCILIATION_FAILED"}
        if int(state.get("state_version") or 0) != int(expected_state_version):
            return {"applied": False, "reason": "STATE_VERSION_CHANGED"}
        applied_keys = state.setdefault("_dynamic_v2_idempotency_keys", [])
        if candidate.idempotency_key in applied_keys:
            return {"applied": False, "reason": "IDEMPOTENT_REPLAY"}

        buy_snapshots, sell_snapshots = self.resolver.resolve(
            state, current_config
        )
        new_config = copy.deepcopy(dict(current_config))
        new_buy = copy.deepcopy(list(new_config.get("buy_grids") or []))
        new_sell = copy.deepcopy(list(new_config.get("sell_grids") or []))
        buy_changed = self._apply_side(
            new_buy,
            buy_snapshots,
            candidate.buy_grid_trigger_percentages,
            candidate.buy_grid_amounts,
            side="BUY",
        )
        sell_changed = self._apply_side(
            new_sell,
            sell_snapshots,
            candidate.sell_grid_trigger_percentages,
            candidate.sell_grid_amounts,
            side="SELL",
        )
        new_config.update(
            {
                "base_alloc_pct": float(
                    candidate.target_base_ratio * D("100")
                ),
                "quote_alloc_pct": float(
                    candidate.target_quote_ratio * D("100")
                ),
                "buy_grids": new_buy,
                "sell_grids": new_sell,
                "buy_trigger_trailing_pct": float(
                    candidate.buy_grid_trailing_percentage
                ),
                "sell_trigger_trailing_pct": float(
                    candidate.sell_grid_trailing_percentage
                ),
                "profit_reentry_drop_pct": float(
                    candidate.profit_buy_trigger_percentage
                ),
                "profit_reentry_rise_pct": float(
                    candidate.profit_buy_trailing_percentage
                ),
                "profit_exit_rise_pct": float(
                    candidate.profit_sell_trigger_percentage
                ),
                "profit_exit_drop_pct": float(
                    candidate.profit_sell_trailing_percentage
                ),
            }
        )
        # One dictionary assignment is the local atomic commit point. The outer
        # orchestrator persists the whole state inside its existing transaction.
        state["dynamic_v2_snapshot"] = {
            "candidate": candidate.to_dict(),
            "applied": new_config,
            "eligible_grid_ids": [
                grid.grid_id
                for grid in buy_snapshots + sell_snapshots
                if grid.status == GridRuntimeState.WAITING_UNTRIGGERED
            ],
            "protected_grid_ids": [
                grid.grid_id
                for grid in buy_snapshots + sell_snapshots
                if grid.status != GridRuntimeState.WAITING_UNTRIGGERED
            ],
            "updated_grid_count": buy_changed + sell_changed,
            "formula_version": candidate.formula_version,
            "decision_id": candidate.decision_id,
            "analysis_run_id": candidate.analysis_run_id,
        }
        applied_keys.append(candidate.idempotency_key)
        state["_dynamic_v2_idempotency_keys"] = applied_keys[-100:]
        return {
            "applied": True,
            "updated_grid_count": buy_changed + sell_changed,
            "protected_grid_count": len(
                [
                    grid
                    for grid in buy_snapshots + sell_snapshots
                    if grid.status != GridRuntimeState.WAITING_UNTRIGGERED
                ]
            ),
            "config": new_config,
        }

    @staticmethod
    def apply_overlay(config: Any, state: Mapping[str, Any]) -> Dict[str, Any]:
        snapshot = state.get("dynamic_v2_snapshot") or {}
        applied = snapshot.get("applied") or {}
        diffs: Dict[str, Any] = {}
        for field_name in (
            "base_alloc_pct",
            "quote_alloc_pct",
            "buy_grids",
            "sell_grids",
            "buy_trigger_trailing_pct",
            "sell_trigger_trailing_pct",
            "profit_reentry_drop_pct",
            "profit_reentry_rise_pct",
            "profit_exit_rise_pct",
            "profit_exit_drop_pct",
        ):
            if field_name not in applied:
                continue
            old = getattr(config, field_name, None)
            new = copy.deepcopy(applied[field_name])
            setattr(config, field_name, new)
            if old != new:
                diffs[field_name] = {"old": old, "new": new}
        return diffs
