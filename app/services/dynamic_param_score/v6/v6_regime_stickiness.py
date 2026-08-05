"""V6 regime stickiness — dampen short-horizon family flips.

PA/DM reclassify every call. 5m ROC/RSI can hop R1↔R3↔R5 within an hour
even when 1h structure is unchanged. This module keeps the previous regime
unless the new candidate persists long enough, or a hard/safety regime wins.

Persistence: ``v6_regime_stickiness_store`` (memory default; file/redis optional).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.services.dynamic_param_score.v6.v6_scenario_classifier import ClassifiedScenario
from app.services.dynamic_param_score.v6.v6_regime_stickiness_store import (
    StickyRecord,
    get_sticky_store,
    reset_sticky_store_for_tests,
)

logger = logging.getLogger(__name__)

# Soft uptrend family: common PA "yukarı" ↔ "sıkışma/kararsız" churn.
UPTREND_FAMILY = frozenset({"R1", "R3", "R5"})
DOWNTREND_FAMILY = frozenset({"R6", "R7"})
BALANCED_FAMILY = frozenset({"R2", "R4"})

try:
    from app.services.dynamic_param_score.v6.constants import (
        REGIME_CROSS_SOFT_CONFIRM_SEC,
        REGIME_SOFT_FAMILY_CONFIRM_SEC,
    )
except Exception:  # pragma: no cover - import cycle fallback
    REGIME_SOFT_FAMILY_CONFIRM_SEC = 30 * 60
    REGIME_CROSS_SOFT_CONFIRM_SEC = 60 * 60

# Candidate must persist this long before a soft flip is accepted.
SOFT_FAMILY_CONFIRM_SEC = int(REGIME_SOFT_FAMILY_CONFIRM_SEC)
# Leaving uptrend family into balanced/range needs stronger persistence.
CROSS_SOFT_CONFIRM_SEC = int(REGIME_CROSS_SOFT_CONFIRM_SEC)


@dataclass
class StickyState:
    locked_regime_id: str
    locked_sub_hint: str
    locked_label: str
    locked_at: float
    candidate_regime_id: str
    candidate_sub_hint: str
    candidate_label: str
    candidate_since: float
    locked_hard_block: bool = False
    locked_hard_block_reasons: Tuple[str, ...] = ()
    locked_matched_gates: Tuple[str, ...] = ()
    locked_sub_id: str = "01"
    locked_micro_id: str = "001"
    locked_behavior_id: str = "STD"

    def to_record(self) -> StickyRecord:
        return StickyRecord(
            locked_regime_id=self.locked_regime_id,
            locked_sub_hint=self.locked_sub_hint,
            locked_label=self.locked_label,
            locked_at=self.locked_at,
            candidate_regime_id=self.candidate_regime_id,
            candidate_sub_hint=self.candidate_sub_hint,
            candidate_label=self.candidate_label,
            candidate_since=self.candidate_since,
            locked_hard_block=self.locked_hard_block,
            locked_hard_block_reasons=tuple(self.locked_hard_block_reasons or ()),
            locked_matched_gates=tuple(self.locked_matched_gates or ()),
            locked_sub_id=self.locked_sub_id,
            locked_micro_id=self.locked_micro_id,
            locked_behavior_id=self.locked_behavior_id,
        )

    @classmethod
    def from_record(cls, rec: StickyRecord) -> "StickyState":
        return cls(
            locked_regime_id=rec.locked_regime_id,
            locked_sub_hint=rec.locked_sub_hint,
            locked_label=rec.locked_label,
            locked_at=rec.locked_at,
            candidate_regime_id=rec.candidate_regime_id,
            candidate_sub_hint=rec.candidate_sub_hint,
            candidate_label=rec.candidate_label,
            candidate_since=rec.candidate_since,
            locked_hard_block=rec.locked_hard_block,
            locked_hard_block_reasons=tuple(rec.locked_hard_block_reasons or ()),
            locked_matched_gates=tuple(rec.locked_matched_gates or ()),
            locked_sub_id=rec.locked_sub_id,
            locked_micro_id=rec.locked_micro_id,
            locked_behavior_id=rec.locked_behavior_id,
        )


def _family(regime_id: str) -> str:
    rid = (regime_id or "").upper()
    if rid in UPTREND_FAMILY:
        return "uptrend"
    if rid in DOWNTREND_FAMILY:
        return "downtrend"
    if rid in BALANCED_FAMILY:
        return "balanced"
    if rid == "R8":
        return "crash"
    return "other"


def _is_hard_escape(classified: ClassifiedScenario) -> bool:
    if bool(getattr(classified, "hard_block", False)):
        return True
    rid = str(getattr(classified, "regime_id", "") or "").upper()
    return rid == "R8"


def _confirm_sec(prev_regime: str, new_regime: str) -> float:
    pf, nf = _family(prev_regime), _family(new_regime)
    if pf == nf == "uptrend" and prev_regime != new_regime:
        return float(SOFT_FAMILY_CONFIRM_SEC)
    if pf == "uptrend" and nf == "balanced":
        return float(CROSS_SOFT_CONFIRM_SEC)
    if pf == "balanced" and nf == "uptrend":
        return float(SOFT_FAMILY_CONFIRM_SEC)
    if pf == nf and prev_regime != new_regime:
        return float(SOFT_FAMILY_CONFIRM_SEC)
    # Different families that aren't hard escapes (e.g. uptrend → R6 recovery)
    if pf != nf:
        return float(CROSS_SOFT_CONFIRM_SEC)
    return 0.0


def _scenario_from_state(state: StickyState) -> ClassifiedScenario:
    return ClassifiedScenario(
        regime_id=state.locked_regime_id,
        sub_id=state.locked_sub_id,
        micro_id=state.locked_micro_id,
        behavior_id=state.locked_behavior_id,
        label=state.locked_label,
        sub_profile_hint=state.locked_sub_hint,
        hard_block=state.locked_hard_block,
        hard_block_reasons=state.locked_hard_block_reasons,
        matched_gates=tuple(state.locked_matched_gates)
        + ("regime_stickiness_hold",),
    )


def _lock_from_classified(classified: ClassifiedScenario, now: float) -> StickyState:
    return StickyState(
        locked_regime_id=str(classified.regime_id or "R3"),
        locked_sub_hint=str(classified.sub_profile_hint or ""),
        locked_label=str(classified.label or ""),
        locked_at=now,
        candidate_regime_id=str(classified.regime_id or "R3"),
        candidate_sub_hint=str(classified.sub_profile_hint or ""),
        candidate_label=str(classified.label or ""),
        candidate_since=now,
        locked_hard_block=bool(classified.hard_block),
        locked_hard_block_reasons=tuple(classified.hard_block_reasons or ()),
        locked_matched_gates=tuple(classified.matched_gates or ()),
        locked_sub_id=str(classified.sub_id or "01"),
        locked_micro_id=str(classified.micro_id or "001"),
        locked_behavior_id=str(classified.behavior_id or "STD"),
    )


def _put(key: str, state: StickyState) -> None:
    store = get_sticky_store()
    store.set(key, state.to_record())


def _get(key: str) -> Optional[StickyState]:
    rec = get_sticky_store().get(key)
    return StickyState.from_record(rec) if rec else None


def clear_stickiness_for_tests() -> None:
    reset_sticky_store_for_tests()


def apply_regime_stickiness(
    classified: ClassifiedScenario,
    *,
    sticky_key: Optional[str] = None,
    prev_regime_id: Optional[str] = None,
    prev_sub_profile_hint: Optional[str] = None,
    prev_regime_label: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Tuple[ClassifiedScenario, Dict[str, Any]]:
    """
    Return (possibly sticky) classification + telemetry meta.

    Soft flips inside/near the uptrend family require the new candidate to
    persist for SOFT/CROSS confirm windows. Hard-block / R8 apply immediately.
    """
    now = float(now_ts if now_ts is not None else time.time())
    store = get_sticky_store()
    meta: Dict[str, Any] = {
        "enabled": bool(sticky_key or prev_regime_id),
        "sticky_key": sticky_key or "",
        "sticky_store": store.backend_name(),
        "held": False,
        "accepted": True,
        "confirm_sec": 0.0,
        "confirm_remaining_sec": 0.0,
        "candidate_age_sec": 0.0,
        "candidate_regime_id": str(classified.regime_id or ""),
        "candidate_sub_profile_hint": str(classified.sub_profile_hint or ""),
        "raw_regime_id": str(classified.regime_id or ""),
        "raw_sub_profile_hint": str(classified.sub_profile_hint or ""),
        "locked_regime_id": str(classified.regime_id or ""),
    }
    if not meta["enabled"]:
        return classified, meta

    key = (sticky_key or "").strip() or f"anon:{(prev_regime_id or 'na')}"
    state = _get(key)
    if state is None and prev_regime_id:
        # Seed from DM previous snapshot (worker restart / first sticky call).
        state = StickyState(
            locked_regime_id=str(prev_regime_id),
            locked_sub_hint=str(prev_sub_profile_hint or ""),
            locked_label=str(prev_regime_label or prev_regime_id),
            locked_at=now,
            candidate_regime_id=str(classified.regime_id or prev_regime_id),
            candidate_sub_hint=str(classified.sub_profile_hint or ""),
            candidate_label=str(classified.label or ""),
            candidate_since=now,
        )
        _put(key, state)

    if state is None:
        _put(key, _lock_from_classified(classified, now))
        meta["locked_regime_id"] = str(classified.regime_id or "")
        meta["seed"] = "first_observation"
        return classified, meta

    if _is_hard_escape(classified):
        _put(key, _lock_from_classified(classified, now))
        meta["escape"] = "hard"
        meta["locked_regime_id"] = str(classified.regime_id or "")
        return classified, meta

    prev = state.locked_regime_id
    new = str(classified.regime_id or "R3")
    # Same regime: adopt fresher sub-hint only after soft confirm if hint family soft-churns.
    same_regime = new == prev
    confirm = 0.0 if same_regime else _confirm_sec(prev, new)
    # Sub-hint churn inside same regime (e.g. R3 compression ↔ overheat).
    if same_regime:
        prev_hint = state.locked_sub_hint
        new_hint = str(classified.sub_profile_hint or "")
        if prev_hint and new_hint and prev_hint != new_hint:
            confirm = float(SOFT_FAMILY_CONFIRM_SEC)
        else:
            _put(key, _lock_from_classified(classified, now))
            meta["locked_regime_id"] = new
            meta["seed"] = "same_regime_refresh"
            return classified, meta

    # Immediate accept: move into downtrend/crash with clear R7 (not soft R6-only noise)
    if prev in UPTREND_FAMILY and new == "R7":
        _put(key, _lock_from_classified(classified, now))
        meta["escape"] = "downtrend"
        meta["locked_regime_id"] = new
        return classified, meta

    identity = (
        new,
        str(classified.sub_profile_hint or ""),
        str(classified.label or ""),
    )
    cand_identity = (
        state.candidate_regime_id,
        state.candidate_sub_hint,
        state.candidate_label,
    )
    if identity != cand_identity:
        state.candidate_regime_id = identity[0]
        state.candidate_sub_hint = identity[1]
        state.candidate_label = identity[2]
        state.candidate_since = now
        _put(key, state)

    age = max(0.0, now - state.candidate_since)
    meta["confirm_sec"] = confirm
    meta["candidate_age_sec"] = age
    meta["candidate_regime_id"] = state.candidate_regime_id
    meta["candidate_sub_profile_hint"] = state.candidate_sub_hint
    meta["confirm_remaining_sec"] = (
        max(0.0, float(confirm) - age) if confirm > 0 else 0.0
    )

    if confirm > 0 and age < confirm:
        held = _scenario_from_state(state)
        meta["held"] = True
        meta["accepted"] = False
        meta["locked_regime_id"] = held.regime_id
        logger.info(
            "V6 regime stickiness hold key=%s locked=%s candidate=%s age=%.0fs need=%.0fs remaining=%.0fs store=%s",
            key,
            held.regime_id,
            new,
            age,
            confirm,
            meta["confirm_remaining_sec"],
            store.backend_name(),
        )
        return held, meta

    _put(key, _lock_from_classified(classified, now))
    meta["locked_regime_id"] = new
    meta["accepted"] = True
    meta["confirm_remaining_sec"] = 0.0
    return classified, meta
