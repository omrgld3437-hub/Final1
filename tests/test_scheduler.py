import time

import pytest

from app.botengine.scheduler import BotScheduler, WakeReason


@pytest.mark.asyncio
async def test_scheduler_register_bot_queues_without_event_loop_lock_error():
    scheduler = BotScheduler()
    scheduler.register_bot(42, time.monotonic() - 1)

    item = await scheduler.next_bot_to_run()

    assert item is not None
    bot_id, reason, context = item
    assert bot_id == 42
    assert reason == WakeReason.SCHEDULED
    assert context == {}
