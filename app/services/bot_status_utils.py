"""Bot status helpers — admin/dashboard active count tek kaynak."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Union

BotLike = Union[Any, dict]


def normalize_bot_status(status: Optional[str]) -> str:
    return (status or "").strip().lower()


def _bot_status(bot: BotLike) -> str:
    if isinstance(bot, dict):
        return normalize_bot_status(bot.get("status"))
    return normalize_bot_status(getattr(bot, "status", None))


def is_bot_running(status: Optional[str]) -> bool:
    return normalize_bot_status(status) == "running"


def is_bot_capital_locked(status: Optional[str]) -> bool:
    """Bot sermayesi hâlâ kullanıcıya serbest sayılmamalı mı?"""
    return normalize_bot_status(status) in (
        "running",
        "paused",
        "paused_error",
        "paused_insufficient_balance",
    )


def is_bot_active_for_admin(bot: BotLike) -> bool:
    """Admin AKTİF BOT: çalışan veya duraklatılmış (durdurulmuş değil)."""
    return _bot_status(bot) in ("running", "paused", "paused_error")


def count_running_bots(bots: Iterable[BotLike]) -> int:
    """Dashboard KPI / wallet: yalnızca status=running (case-insensitive)."""
    return sum(1 for b in bots if _bot_status(b) == "running")


def count_admin_active_bots(bots: Iterable[BotLike]) -> int:
    """Admin hesap karosu AKTİF BOT — running + paused."""
    return sum(1 for b in bots if is_bot_active_for_admin(b))
