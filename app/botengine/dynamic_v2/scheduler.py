"""UTC scheduler decisions for full analysis, retry and micro safety checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from .config import DynamicV2Config


@dataclass(frozen=True)
class ScheduleDecision:
    run_full_analysis: bool
    run_micro_check: bool
    next_full_analysis_at: datetime
    next_micro_check_at: datetime
    reason: str


class DynamicModeScheduler:
    def __init__(self, config: DynamicV2Config):
        self.config = config

    def decide(
        self,
        runtime: Mapping[str, Any],
        *,
        now: Optional[datetime] = None,
        start_blocked: bool = False,
    ) -> ScheduleDecision:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        last_full = self._parse(runtime.get("last_analysis_at"))
        last_micro = self._parse(runtime.get("last_micro_check_at"))
        if start_blocked:
            due_full = (
                last_full
                + timedelta(seconds=self.config.blocked_retry_seconds)
                if last_full
                else now
            )
            run_full = now >= due_full
            next_full = (
                now + timedelta(seconds=self.config.blocked_retry_seconds)
                if run_full
                else due_full
            )
            reason = "BLOCKED_RETRY"
        else:
            hour = now.replace(minute=0, second=0, microsecond=0)
            current_slot = hour + timedelta(
                seconds=self.config.full_analysis_offset_seconds
            )
            run_full = (
                now >= current_slot
                and (last_full is None or last_full < current_slot)
            )
            next_full = (
                current_slot
                if now < current_slot
                else current_slot + timedelta(hours=1)
            )
            if last_full:
                next_full = max(
                    next_full,
                    last_full
                    + timedelta(
                        seconds=self.config.minimum_full_analysis_seconds
                    ),
                )
            reason = "HOURLY_CANDLE_CLOSE"
        micro_due = (
            last_micro + timedelta(seconds=self.config.micro_check_seconds)
            if last_micro
            else now
        )
        run_micro = now >= micro_due
        next_micro = (
            now + timedelta(seconds=self.config.micro_check_seconds)
            if run_micro
            else micro_due
        )
        return ScheduleDecision(
            run_full_analysis=run_full,
            run_micro_check=run_micro,
            next_full_analysis_at=next_full,
            next_micro_check_at=next_micro,
            reason=reason,
        )

    @staticmethod
    def _parse(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
        except (TypeError, ValueError):
            return None
