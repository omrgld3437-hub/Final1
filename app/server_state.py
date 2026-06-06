"""
Sunucu durumu: lockdown bayrağı ve istek sayacı.
Lockdown açıkken sadece admin sayfası ve admin/auth/boot-id erişilebilir.
Uptime = bu process'in başladığı andan itibaren geçen süre; restart edilirse sıfırlanır.
"""
from __future__ import annotations
import time
import threading
from datetime import datetime, timezone

# Lockdown: True ise sadece whitelist path'ler erişebilir
_lockdown: bool = False
_lock = threading.Lock()

# Uygulama başlangıç zamanı (uptime için). Process her restart'ta sıfırlanır.
_start_time: float = time.monotonic()
_started_at_utc: datetime = datetime.now(timezone.utc)

# Toplam HTTP istek sayısı (middleware ile artırılır)
_request_count: int = 0


def get_lockdown() -> bool:
    with _lock:
        return _lockdown


def set_lockdown(value: bool) -> bool:
    with _lock:
        global _lockdown
        _lockdown = value
        return _lockdown


def get_uptime_seconds() -> float:
    return time.monotonic() - _start_time


def get_started_at_utc() -> datetime:
    """Process başlangıç zamanı (UTC). Restart'ta yenilenir."""
    return _started_at_utc


def increment_request_count() -> int:
    with _lock:
        global _request_count
        _request_count += 1
        return _request_count


def get_request_count() -> int:
    with _lock:
        return _request_count


# Ağ hızı hesabı için son örnek (psutil net_io_counters)
_net_last_time: float = 0.0
_net_last_sent: int = 0
_net_last_recv: int = 0


def update_net_snapshot(sent: int, recv: int) -> None:
    with _lock:
        global _net_last_time, _net_last_sent, _net_last_recv
        _net_last_time = time.monotonic()
        _net_last_sent = sent
        _net_last_recv = recv


def get_net_rate(sent: int, recv: int) -> tuple[float | None, float | None]:
    """Mevcut bytes_sent/recv ile son snapshot'tan mbps (megabit/s) hesapla. (down_mbps, up_mbps)."""
    with _lock:
        global _net_last_time, _net_last_sent, _net_last_recv
        now = time.monotonic()
        if _net_last_time == 0:
            _net_last_time = now
            _net_last_sent = sent
            _net_last_recv = recv
            return None, None
        elapsed = now - _net_last_time
        if elapsed < 0.3:
            return None, None
        down_mbps = (recv - _net_last_recv) / elapsed / 1_000_000 * 8
        up_mbps = (sent - _net_last_sent) / elapsed / 1_000_000 * 8
        _net_last_time = now
        _net_last_sent = sent
        _net_last_recv = recv
        return down_mbps, up_mbps


# Güvenlik ihlali uyarıları (yetkisiz erişim tespiti). Admin panelde büyük uyarı gösterilir.
_breach_events: list = []
_BREACH_MAX = 50


def add_breach_event(
    breach_type: str,
    path: str,
    method: str,
    client_ip: str,
    detail: str,
    session_user_id: int | None = None,
    session_account_id: int | None = None,
    requested_account_id: int | None = None,
) -> None:
    """Yetkisiz erişim tespit edildiğinde çağrılır. Admin'e uyarı için kaydedilir."""
    with _lock:
        global _breach_events
        _breach_events.append({
            "type": breach_type,
            "path": path,
            "method": method,
            "client_ip": client_ip,
            "detail": detail,
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_user_id": session_user_id,
            "session_account_id": session_account_id,
            "requested_account_id": requested_account_id,
        })
        if len(_breach_events) > _BREACH_MAX:
            _breach_events = _breach_events[-_BREACH_MAX:]


def get_and_clear_breach_events() -> list:
    """Admin panelde gösterilmek üzere breach listesini döndürür ve temizler."""
    with _lock:
        global _breach_events
        out = list(_breach_events)
        _breach_events = []
        return out


def get_breach_events() -> list:
    """Temizlemeden breach listesini döndürür."""
    with _lock:
        return list(_breach_events)
