"""
Bot Engine v5 – Event-driven scheduler. 300-bot capable.
Min-heap by next_run_at; wake by events (price threshold, fill, risk). Concurrency limits + backpressure.
"""
from __future__ import annotations
import asyncio
import heapq
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Jitter to avoid herd (ms)
JITTER_MIN_MS = 50
JITTER_MAX_MS = 150

# Concurrency limits (tunable for 300 bots)
DB_SEM_LIMIT = 20
COMPUTE_SEM_LIMIT = 50
BINANCE_SEM_LIMIT = 10

# Backpressure: if p95 bot_run_ms > this, reduce concurrency
BOT_RUN_P95_THRESHOLD_MS = 2000
# Weight near limit => slow scheduling
WEIGHT_SAFE_MODE_THRESHOLD = 0.85  # 85% of limit


class WakeReason(Enum):
    SCHEDULED = "scheduled"
    PRICE_THRESHOLD = "price_threshold"
    FILL = "fill"
    RISK_STATE = "risk_state"
    RECONCILE = "reconcile"


@dataclass(order=True)
class ScheduledBot:
    next_run_at: float
    bot_id: int = field(compare=False)
    priority: int = field(compare=False, default=0)  # lower = higher priority


class BotScheduler:
    """
    Event-driven scheduler: heap of (next_run_at, bot_id), wake_queue for events.
    Concurrency: db_sem, compute_sem, binance_sem. Backpressure when weight near limit or p95 high.
    """

    def __init__(
        self,
        db_sem_limit: int = DB_SEM_LIMIT,
        compute_sem_limit: int = COMPUTE_SEM_LIMIT,
        binance_sem_limit: int = BINANCE_SEM_LIMIT,
        weight_check: Optional[Callable[[], Tuple[float, float]]] = None,
        bot_run_durations: Optional[List[float]] = None,
    ) -> None:
        self._heap: List[ScheduledBot] = []
        self._heap_lock = asyncio.Lock()
        self._wake_queue: asyncio.Queue[Tuple[int, WakeReason, Dict[str, Any]]] = asyncio.Queue()
        self._registered: Set[int] = set()
        self._db_sem = asyncio.Semaphore(db_sem_limit)
        self._compute_sem = asyncio.Semaphore(compute_sem_limit)
        self._binance_sem = asyncio.Semaphore(binance_sem_limit)
        self._weight_check = weight_check  # () -> (used_ratio, limit)
        self._bot_run_durations: List[float] = bot_run_durations or []
        self._max_duration_samples = 100
        self._run_callback: Optional[Callable[[int, str], Any]] = None  # async (bot_id, tick_id) -> next_run_at (float)
        self._stopped = False

    def register_run_callback(self, cb: Callable[[int, str], Any]) -> None:
        """Set callback(bot_id, tick_id) -> next_run_at (monotonic time). Callback is async."""
        self._run_callback = cb

    def register_bot(self, bot_id: int, next_run_at: float) -> None:
        """Add or update bot in heap. next_run_at is monotonic time."""
        self._registered.add(bot_id)
        jitter_ms = random.uniform(JITTER_MIN_MS, JITTER_MAX_MS)
        at = next_run_at + (jitter_ms / 1000.0)
        with self._heap_lock:
            # Heap is min-heap by next_run_at; we don't dedupe bot_id in heap (same bot can be pushed again)
            heapq.heappush(self._heap, ScheduledBot(at, bot_id))

    def unregister_bot(self, bot_id: int) -> None:
        self._registered.discard(bot_id)

    def wake_bot(self, bot_id: int, reason: WakeReason, context: Optional[Dict[str, Any]] = None) -> None:
        """Queue bot for immediate wake (event-driven)."""
        if bot_id not in self._registered:
            return
        self._wake_queue.put_nowait((bot_id, reason, context or {}))

    def record_bot_run_duration_ms(self, duration_ms: float) -> None:
        """For backpressure: track p95 bot run time."""
        self._bot_run_durations.append(duration_ms)
        if len(self._bot_run_durations) > self._max_duration_samples:
            self._bot_run_durations.pop(0)

    def _p95_duration_ms(self) -> float:
        if not self._bot_run_durations:
            return 0.0
        s = sorted(self._bot_run_durations)
        idx = max(0, int(len(s) * 0.95) - 1)
        return s[idx]

    def _weight_near_limit(self) -> bool:
        """True if weight governor says we're near limit (safe mode)."""
        if not self._weight_check:
            return False
        try:
            used_ratio, _ = self._weight_check()
            return used_ratio >= WEIGHT_SAFE_MODE_THRESHOLD
        except Exception:
            return False

    async def acquire_db(self) -> asyncio.Semaphore:
        return self._db_sem

    async def acquire_compute(self) -> asyncio.Semaphore:
        return self._compute_sem

    async def acquire_binance(self) -> asyncio.Semaphore:
        return self._binance_sem

    async def next_bot_to_run(self) -> Optional[Tuple[int, WakeReason, Dict[str, Any]]]:
        """
        Return (bot_id, reason, context) for next bot to run.
        Prefer wake_queue; else heap if next_run_at <= now.
        Backpressure: if weight near limit or p95 high, delay (return None and sleep a bit).
        """
        now = time.monotonic()
        # Backpressure
        if self._weight_near_limit():
            await asyncio.sleep(0.5)
            return None
        if self._p95_duration_ms() > BOT_RUN_P95_THRESHOLD_MS:
            await asyncio.sleep(0.2)
        # Prefer event-driven wake
        try:
            item = self._wake_queue.get_nowait()
            return item
        except asyncio.QueueEmpty:
            pass
        async with self._heap_lock:
            if not self._heap:
                return None
            top = self._heap[0]
            if top.next_run_at > now:
                return None
            heapq.heappop(self._heap)
            if top.bot_id not in self._registered:
                return await self.next_bot_to_run()
            return (top.bot_id, WakeReason.SCHEDULED, {})

    async def schedule_next(self, bot_id: int, next_run_at: float) -> None:
        """After a bot run, re-queue with next_run_at (monotonic)."""
        if bot_id not in self._registered:
            return
        jitter_ms = random.uniform(JITTER_MIN_MS, JITTER_MAX_MS)
        at = next_run_at + (jitter_ms / 1000.0)
        async with self._heap_lock:
            heapq.heappush(self._heap, ScheduledBot(at, bot_id))

    def queue_depth(self) -> int:
        """Scheduler queue depth (heap size + wake_queue size)."""
        return len(self._heap) + self._wake_queue.qsize()

    async def run_loop(self) -> None:
        """Main loop: pop next bot, run via callback, re-schedule. Runs until stopped."""
        self._stopped = False
        logger.info("BOT_SCHEDULER_START db_sem=%s compute_sem=%s binance_sem=%s", self._db_sem._value, self._compute_sem._value, self._binance_sem._value)
        while not self._stopped:
            try:
                item = await self.next_bot_to_run()
                if item is None:
                    await asyncio.sleep(0.05)
                    continue
                bot_id, reason, context = item
                if self._run_callback is None:
                    continue
                tick_id = f"{bot_id}_{int(time.time()*1000)}"
                t0 = time.perf_counter()
                now_mono = time.monotonic()
                next_run_at = now_mono + 60.0  # default 60s if callback fails
                try:
                    result = await self._run_callback(bot_id, tick_id)
                    if isinstance(result, (int, float)):
                        next_run_at = float(result)
                    elif result is not None:
                        next_run_at = float(getattr(result, "next_run_at", now_mono + 60.0))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("BOT_SCHEDULER_RUN_ERROR bot_id=%s reason=%s: %s", bot_id, reason.value, e)
                else:
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    self.record_bot_run_duration_ms(elapsed_ms)
                    await self.schedule_next(bot_id, next_run_at)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("BOT_SCHEDULER_LOOP_ERROR: %s", e)
                await asyncio.sleep(1)
        logger.info("BOT_SCHEDULER_STOPPED")

    def stop(self) -> None:
        self._stopped = True
