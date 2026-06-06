"""
FILE: worker_v2.py
VERSION: v1
DATE: 2026-01-21
CHANGE: Bot V2 Worker/Scheduler - Background task runner for running bots
"""
import asyncio
import logging
from typing import Dict, Set, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.bot.models_v2 import BotV2
from app.bot.engine_v2 import BotEngineV2

logger = logging.getLogger(__name__)


class BotWorkerV2:
    """Background worker for running Bot V2 instances"""

    def __init__(self):
        self.running_bots: Dict[int, BotEngineV2] = {}
        self.bot_locks: Dict[int, asyncio.Lock] = {}
        self.is_running = False
        self.tasks: Dict[int, asyncio.Task] = {}

    async def start(self):
        """Start the worker"""
        if self.is_running:
            return
        self.is_running = True
        logger.info("BotWorkerV2 started")

        # Load and start all RUNNING bots from DB
        db = SessionLocal()
        try:
            running_bots = db.query(BotV2).filter(BotV2.status == "RUNNING").all()
            for bot in running_bots:
                await self.start_bot(bot.id, db)
        finally:
            db.close()

    async def stop(self):
        """Stop the worker"""
        self.is_running = False
        # Cancel all tasks
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        self.running_bots.clear()
        logger.info("BotWorkerV2 stopped")

    async def start_bot(self, bot_id: int, db: Optional[Session] = None):
        """Start a bot (create engine and task)"""
        if bot_id in self.running_bots:
            return

        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
            if not bot or bot.status != "RUNNING":
                return

            # Create engine
            engine = BotEngineV2(bot_id, db)
            engine.load()

            # Create lock
            if bot_id not in self.bot_locks:
                self.bot_locks[bot_id] = asyncio.Lock()

            # Create task
            task = asyncio.create_task(self._run_bot_loop(bot_id, engine))
            self.tasks[bot_id] = task
            self.running_bots[bot_id] = engine

            logger.info(f"Bot {bot_id} started")
        finally:
            if close_db:
                db.close()

    async def stop_bot(self, bot_id: int):
        """Stop a bot"""
        if bot_id not in self.running_bots:
            return

        # Cancel task
        if bot_id in self.tasks:
            self.tasks[bot_id].cancel()
            try:
                await self.tasks[bot_id]
            except asyncio.CancelledError:
                pass
            del self.tasks[bot_id]

        # Remove engine
        del self.running_bots[bot_id]

        # Update DB status
        db = SessionLocal()
        try:
            bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
            if bot:
                bot.status = "STOPPED"
                bot.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

        logger.info(f"Bot {bot_id} stopped")

    async def pause_bot(self, bot_id: int):
        """Pause a bot (keep engine but stop ticking)"""
        if bot_id not in self.running_bots:
            return

        # Cancel task but keep engine
        if bot_id in self.tasks:
            self.tasks[bot_id].cancel()
            try:
                await self.tasks[bot_id]
            except asyncio.CancelledError:
                pass
            del self.tasks[bot_id]

        # Update DB
        db = SessionLocal()
        try:
            bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
            if bot:
                bot.status = "PAUSED"
                bot.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

        logger.info(f"Bot {bot_id} paused")

    async def resume_bot(self, bot_id: int):
        """Resume a paused bot"""
        db = SessionLocal()
        try:
            bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
            if not bot or bot.status != "PAUSED":
                return

            bot.status = "RUNNING"
            db.commit()
        finally:
            db.close()

        # Start bot (will reload engine)
        await self.start_bot(bot_id)

    async def _run_bot_loop(self, bot_id: int, engine: BotEngineV2):
        """Main loop for a single bot"""
        lock = self.bot_locks.get(bot_id)
        if not lock:
            return

        db = SessionLocal()
        try:
            bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
            if not bot:
                return

            poll_interval = bot.polling_interval_ms / 1000.0  # Convert to seconds

            while self.is_running:
                try:
                    # Check status
                    bot = db.query(BotV2).filter(BotV2.id == bot_id).first()
                    if not bot or bot.status != "RUNNING":
                        break

                    # Reload engine (fresh DB session)
                    engine.db = db
                    engine.load()

                    # Execute tick (with lock to prevent concurrent ticks)
                    async with lock:
                        engine.tick()

                    # Wait for next tick
                    await asyncio.sleep(poll_interval)

                except Exception as e:
                    logger.error(f"Error in bot {bot_id} loop: {e}", exc_info=True)
                    await asyncio.sleep(poll_interval)
        finally:
            db.close()
            # Cleanup
            if bot_id in self.running_bots:
                del self.running_bots[bot_id]
            if bot_id in self.tasks:
                del self.tasks[bot_id]


# Global worker instance
_worker: Optional[BotWorkerV2] = None


def get_worker() -> BotWorkerV2:
    """Get global worker instance"""
    global _worker
    if _worker is None:
        _worker = BotWorkerV2()
    return _worker


async def init_worker():
    """Initialize and start worker (called on app startup)"""
    worker = get_worker()
    await worker.start()


async def shutdown_worker():
    """Shutdown worker (called on app shutdown)"""
    worker = get_worker()
    await worker.stop()

