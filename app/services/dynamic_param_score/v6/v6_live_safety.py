"""Post-seal live safety overrides for V6.

Operator 4+4 ladders stay sealed for PA reference display. This module only
forces live gates (automatic_apply / reference_plan_only / deployable reasons)
so narrative like "alışlar soğuma teyidiyle" matches Dynamic Mode execution.
"""

from __future__ import annotations

from typing import Any, Dict, Set, Tuple

from app.services.dynamic_param_score.v6.domain.types import V6CatalogProfile, V6InputContract

# Hints that keep reference grids but must not open live buys.
_LIVE_BUY_PAUSED_HINTS = frozenset(
    {
        "R5_DEF_PARABOLIC_OVEREXTENDED",
    }
)

_LIVE_BUY_PAUSED_REASONS = frozenset(
    {
        "NEW_BUYS_PAUSED",
        "PARABOLIC_PUMP",
        "R5_DEF_PARABOLIC_OVEREXTENDED",
    }
)


def _reason_codes(opportunity_notes: Dict[str, Any]) -> Set[str]:
    return {str(x) for x in (opportunity_notes.get("reason_codes") or []) if x}


def apply_live_safety_overrides(
    adjusted: V6CatalogProfile,
    *,
    classified: Any,
    inp: V6InputContract,
    opportunity_notes: Dict[str, Any],
) -> Tuple[V6CatalogProfile, Dict[str, Any]]:
    """
    After seal_net_profile_shape: keep ladders, close live buys when required.

    Returns (profile, notes_patch).
    """
    notes = dict(opportunity_notes or {})
    hint = str(getattr(classified, "sub_profile_hint", "") or "")
    reasons = _reason_codes(notes)
    mods = dict(adjusted.modules or {})
    patch: Dict[str, Any] = {}

    pause_buys = hint in _LIVE_BUY_PAUSED_HINTS or bool(reasons & _LIVE_BUY_PAUSED_REASONS)

    # R7 Koşullu: weak liquidity + high vol → treat as Kapalı for live deploy.
    regime = str(getattr(classified, "regime_id", "") or "").upper()
    apply_label = str(mods.get("automatic_apply_label") or mods.get("apply_policy") or "")
    vol = float(getattr(inp, "volatility_percentile", 0) or 0)
    spread = float(getattr(inp, "spread_pct", 0) or 0)
    vol_consistency = float(
        getattr(inp, "volume_consistency", 0.5)
        if getattr(inp, "volume_consistency", None) is not None
        else 0.5
    )
    liquidity_weak = spread >= 0.10 or vol_consistency < 0.35
    conditional_label = "koşullu" in apply_label.lower()
    conditional_to_closed = (
        regime == "R7"
        and conditional_label
        and liquidity_weak
        and vol >= 70
    )

    if pause_buys or conditional_to_closed:
        mods["automatic_apply"] = False
        mods["reference_plan_only"] = True
        mods["reference_display_only"] = True
        mods["live_buys_paused"] = True
        if pause_buys:
            mods["live_safety_reason"] = "parabolic_new_buys_paused"
            # Keep operator label readable; clarify live stance.
            if not str(mods.get("automatic_apply_label") or "").startswith("Kapalı"):
                mods["automatic_apply_label"] = (
                    "Kapalı — referans plan; alışlar soğuma teyidine kadar"
                )
            reasons.update(_LIVE_BUY_PAUSED_REASONS)
            reasons.add("LIVE_BUYS_PAUSED")
            notes["deployable"] = False
            notes["live_buys_paused"] = True
            notes["reference_display_only"] = True
            patch["live_safety"] = "parabolic_new_buys_paused"
        if conditional_to_closed:
            mods["live_safety_reason"] = "r7_conditional_weak_liq_high_vol"
            mods["automatic_apply_label"] = "Kapalı — koşullu risk (zayıf likidite + yüksek vol)"
            reasons.add("R7_CONDITIONAL_CLOSED")
            reasons.add("LIVE_BUYS_PAUSED")
            notes["deployable"] = False
            notes["live_buys_paused"] = True
            patch["live_safety"] = "r7_conditional_weak_liq_high_vol"
        notes["reason_codes"] = sorted(reasons)
        adjusted.modules = mods

    return adjusted, {**notes, **patch}
