from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.finance_reports import _bot_initial_usd, _finance_bot_summary_row
from app.db.base import Base
from app.db.models import Bot, PnlSnapshot
from app.services.pnl_service import PnlService


def _memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_pnl_snapshot_if_due_is_throttled():
    db = _memory_session()
    try:
        wrote = PnlService.save_snapshot_if_due(
            db,
            11,
            22,
            {
                "total_usd": 100.0,
                "realized": 1.0,
                "unrealized": 2.0,
                "daily": 3.0,
                "monthly": 4.0,
            },
            min_interval_sec=60,
        )
        skipped = PnlService.save_snapshot_if_due(
            db,
            11,
            22,
            {
                "total_usd": 101.0,
                "realized": 1.0,
                "unrealized": 2.0,
                "daily": 3.0,
                "monthly": 4.0,
            },
            min_interval_sec=60,
        )

        rows = (
            db.query(PnlSnapshot)
            .filter(PnlSnapshot.bot_id == 11, PnlSnapshot.account_id == 22)
            .all()
        )
        assert wrote is True
        assert skipped is False
        assert len(rows) == 1
        assert rows[0].total_usd == 100.0
    finally:
        db.close()


def test_pnl_snapshot_if_due_writes_after_interval():
    db = _memory_session()
    try:
        db.add(
            PnlSnapshot(
                bot_id=11,
                account_id=22,
                ts=datetime.utcnow() - timedelta(seconds=120),
                total_usd=100.0,
                realized=0.0,
                unrealized=0.0,
                daily=0.0,
                monthly=0.0,
            )
        )
        db.commit()

        wrote = PnlService.save_snapshot_if_due(
            db,
            11,
            22,
            {
                "total_usd": 102.0,
                "realized": 1.0,
                "unrealized": 2.0,
                "daily": 3.0,
                "monthly": 4.0,
            },
            min_interval_sec=60,
        )

        assert wrote is True
        assert (
            db.query(PnlSnapshot)
            .filter(PnlSnapshot.bot_id == 11, PnlSnapshot.account_id == 22)
            .count()
            == 2
        )
    finally:
        db.close()


def test_finance_bot_summary_separates_mark_to_market_from_realized_30d():
    bot = Bot(
        id=7,
        account_id=3,
        symbol="ETHUSDT",
        status="running",
        mode="live",
        config_json=json.dumps({"initial_capital_usdt": 50.0}),
    )
    row = _finance_bot_summary_row(
        bot,
        {"pnl": 1.25, "fees": 0.11, "count": 4},
        current_usd=45.6,
        initial_usd=_bot_initial_usd(bot),
    )

    assert row["current_usd"] == 45.6
    assert row["initial_usd"] == 50.0
    assert row["total_pnl_usd"] == -4.4
    assert row["mark_to_market_pnl_usd"] == -4.4
    assert row["realized_30d_pnl_usd"] == 1.25
    assert row["pnl_30d"] == 1.25
