"""Runtime factory and lightweight safety check used by the orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from app.utils.parse_utils import parse_bool

from .config import DynamicV2Config
from .service import DynamicModeV2


_ENGINES: Dict[tuple, DynamicModeV2] = {}


def get_engine(raw_config: Mapping[str, Any]) -> DynamicModeV2:
    shadow = (
        parse_bool(raw_config.get("dynamic_mode_v2_shadow"))
        if "dynamic_mode_v2_shadow" in raw_config
        else True
    )
    key = (shadow,)
    if key not in _ENGINES:
        _ENGINES[key] = DynamicModeV2(
            DynamicV2Config(enabled=True, shadow_mode=shadow)
        )
    return _ENGINES[key]


KILL_SWITCH_KEY = "_dynamic_v2_kill_switch"
# Geçici bir çalışma hatası V2'yi kalıcı kapatmasın: latch bu süre sonunda
# kendiliğinden düşer ve tam analiz yeniden denenir.
RUNTIME_TRIP_COOLDOWN_SEC = 900


def trip_kill_switch(
    state: Dict[str, Any], reasons: list, *, detail: str | None = None
) -> None:
    """Kill switch'i düşür ve ne zaman düştüğünü kaydet.

    ``tripped_at`` olmadan latch'in ne kadar süredir aktif olduğu bilinemez ve
    kendiliğinden açılamaz.
    """
    entry: Dict[str, Any] = {
        "active": True,
        "reasons": list(reasons),
        "tripped_at": datetime.now(timezone.utc).isoformat(),
    }
    if detail:
        entry["detail"] = detail[:300]
    state[KILL_SWITCH_KEY] = entry


def kill_switch_active(state: Mapping[str, Any]) -> bool:
    """Kill switch hâlâ geçerli mi?

    Sağlık kontrolünün düşürdüğü latch, koşul düzelene kadar geçerlidir
    (micro_risk_check onu temizler). Çalışma hatasıyla düşen latch ise
    RUNTIME_TRIP_COOLDOWN_SEC sonunda zaman aşımına uğrar; aksi halde tek bir
    geçici ağ hatası Dynamic Mode V2'yi o bot için sessizce ve kalıcı olarak
    kapatır ve elle DB düzenlemeden başka çıkış yolu kalmaz.
    """
    entry = state.get(KILL_SWITCH_KEY) or {}
    if not entry.get("active"):
        return False
    if "RUNTIME_EXCEPTION" not in (entry.get("reasons") or []):
        return True
    tripped_at = entry.get("tripped_at")
    if not tripped_at:
        # Eski kayıtlar (zaman damgası yok) süresiz kilitli kalmasın.
        return False
    try:
        when = datetime.fromisoformat(str(tripped_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - when).total_seconds()
    return age < RUNTIME_TRIP_COOLDOWN_SEC


def micro_risk_check(state: Dict[str, Any]) -> Dict[str, Any]:
    """No parameter production: only freeze/kill-switch signals."""
    connected = not bool(state.get("last_error_code"))
    uncertain_order = bool(state.get("_reconciliation_unknown"))
    balance_mismatch = bool(state.get("_balance_drift_detected"))
    reasons = []
    if not connected:
        reasons.append("EXCHANGE_CONNECTION")
    if uncertain_order:
        reasons.append("ORDER_STATUS_UNCERTAIN")
    if balance_mismatch:
        reasons.append("BALANCE_MISMATCH")
    result = {"healthy": not reasons, "reasons": reasons}
    if reasons:
        trip_kill_switch(state, reasons)
    elif (state.get(KILL_SWITCH_KEY) or {}).get("active"):
        # Sağlık geri döndü: latch açılır. Önceden temizlenmediği için bir kez
        # düşen kill switch sonsuza kadar aktif kalıyordu.
        state[KILL_SWITCH_KEY] = {
            "active": False,
            "reasons": [],
            "cleared_at": datetime.now(timezone.utc).isoformat(),
        }
    return result
