#!/usr/bin/env python3
"""Local simulation: schedule 300 bots, measure scheduler stability (queue depth, run rate). No real DB/trades."""

from __future__ import annotations
import asyncio
import time
import os
import sys

if __name__ == "__main__":
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _root)
    os.chdir(_root)

from app.botengine.scheduler import BotScheduler

NUM_BOTS = 300
RUN_FOR_SEC = 30
COMPUTE_MS = 5  # simulated bot run time


async def fake_run(bot_id: int, tick_id: str):
    await asyncio.sleep(COMPUTE_MS / 1000.0)
    return time.monotonic() + 2.0  # next in 2s


async def main():
    scheduler = BotScheduler(
        db_sem_limit=20, compute_sem_limit=50, binance_sem_limit=10
    )
    now = time.monotonic()
    for i in range(NUM_BOTS):
        scheduler.register_bot(i, now + (i * 0.01))
    scheduler.register_run_callback(fake_run)
    depths = []
    start = time.monotonic()

    async def collect():
        while time.monotonic() - start < RUN_FOR_SEC:
            depths.append(scheduler.queue_depth())
            await asyncio.sleep(0.5)

    task_loop = asyncio.create_task(scheduler.run_loop())
    task_collect = asyncio.create_task(collect())
    await asyncio.sleep(RUN_FOR_SEC)
    scheduler.stop()
    task_collect.cancel()
    try:
        await task_collect
    except asyncio.CancelledError:
        pass
    task_loop.cancel()
    try:
        await task_loop
    except asyncio.CancelledError:
        pass
    if depths:
        print(
            f"queue_depth min={min(depths)} max={max(depths)} avg={sum(depths) / len(depths):.1f} samples={len(depths)}"
        )
    print("perf_300_bots_sim done")


if __name__ == "__main__":
    asyncio.run(main())
