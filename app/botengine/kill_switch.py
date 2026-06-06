"""
Bot Engine v5 – Global kill switch. When enabled, no new order submits.
"""
from __future__ import annotations
import os
import threading

_KILL_SWITCH_ENABLED = False
_KILL_SWITCH_LOCK = threading.Lock()


def is_kill_switch_enabled() -> bool:
    """True => deny new submits; reconcile still allowed."""
    with _KILL_SWITCH_LOCK:
        if os.environ.get("BOT_ENGINE_KILL_SWITCH") == "1":
            return True
        return _KILL_SWITCH_ENABLED


def set_kill_switch(enabled: bool) -> None:
    """Enable or disable global kill switch (in-process)."""
    global _KILL_SWITCH_ENABLED
    with _KILL_SWITCH_LOCK:
        _KILL_SWITCH_ENABLED = bool(enabled)


def check_kill_switch() -> None:
    """Raise if kill switch enabled. Call before any order submit."""
    from app.botengine.errors import KillSwitchError
    if is_kill_switch_enabled():
        raise KillSwitchError("Global kill switch is enabled; new submits denied")
