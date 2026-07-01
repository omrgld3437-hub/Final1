"""Build and validate V6 input contract — fee fields excluded."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.dynamic_param_score.v6.domain.types import V6InputContract

REQUIRED_BOT_FIELDS = ("symbol", "bot_budget_usdt", "current_price")


def validate_input_contract(inp: V6InputContract) -> List[str]:
    errors: List[str] = []
    if not inp.symbol:
        errors.append("symbol_required")
    if inp.bot_budget_usdt <= 0:
        errors.append("bot_budget_usdt_invalid")
    if inp.current_price <= 0:
        errors.append("current_price_invalid")
    if inp.min_notional <= 0:
        errors.append("min_notional_invalid")
    if not inp.price_valid:
        errors.append("price_valid_false")
    return errors


def input_contract_from_dict(data: Dict[str, Any]) -> V6InputContract:
    """Hydrate from plain dict (API / telemetry). Fee keys are ignored if present."""
    skip_fee = {
        "total_fee", "maker_fee", "taker_fee", "fee_efficiency",
        "fee_missing", "fee_unreadable", "fee_based_rejection",
    }
    clean = {k: v for k, v in data.items() if k not in skip_fee}
    fields = V6InputContract.__dataclass_fields__
    kwargs = {k: clean[k] for k in fields if k in clean}
    return V6InputContract(**kwargs)
