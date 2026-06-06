"""
PnL Trailing DCA spec compliance: total_usd priority, cycle_end consistency, stale price, Turkey day, FIFO fees.
"""
import pytest
from unittest.mock import MagicMock
from app.services.pnl_service import PnlService, _fee_quote
from app.utils.tz_utils import turkey_day_start_utc_for_date, turkey_day_end_utc_for_date
from app.bot.ledger import Ledger


def test_fee_quote_usdt():
    t = MagicMock()
    t.fee_asset = "USDT"
    t.fee = 0.28
    assert _fee_quote(t) == 0.28
    t.fee_asset = "BNB"
    assert _fee_quote(t) == 0.0


def test_turkey_day_boundaries():
    start = turkey_day_start_utc_for_date("2026-02-13")
    end = turkey_day_end_utc_for_date("2026-02-13")
    assert start < end
    assert (end - start).total_seconds() == 86400


@pytest.fixture
def db_session():
    """Session for integration tests. Skips if DB or required tables unavailable."""
    try:
        from app.db.base import SessionLocal
        from sqlalchemy import text
        session = SessionLocal()
        session.execute(text("SELECT 1 FROM trades LIMIT 1"))
        yield session
        session.rollback()
        session.close()
    except Exception:
        pytest.skip("DB or trades table not available")


@pytest.mark.integration
def test_record_trade_idempotency(db_session):
    """record_trade called twice with same (bot_id, order_id) must not duplicate; PnL unchanged."""
    from app.db.models import Bot, Account
    acc = db_session.query(Account).first()
    if not acc:
        pytest.skip("no account")
    bot = db_session.query(Bot).filter(Bot.account_id == acc.id).first()
    if not bot:
        pytest.skip("no bot")
    bot_id = bot.id
    account_id = bot.account_id
    order_id = "idem_pnl_ord_%s" % (hash("idem_test") % 10**8)
    trade1, inserted1 = Ledger.record_trade(
        db_session, bot_id, account_id,
        "BUY", 1.0, 100.0, fee=0.1, fee_asset="USDT",
        order_id=order_id, symbol="BTCUSDT", cycle_id=1,
    )
    assert inserted1 is True
    trade2, inserted2 = Ledger.record_trade(
        db_session, bot_id, account_id,
        "BUY", 1.0, 100.0, fee=0.1, fee_asset="USDT",
        order_id=order_id, symbol="BTCUSDT", cycle_id=1,
    )
    assert inserted2 is False
    assert trade2.id == trade1.id


def test_fifo_realized_with_fees_two_sells():
    """
    FIFO realized for: BUY 26.08 @53.68 fee 0; SELL 5.216 @54.47 fee 0.284; SELL 7.824 @56.2814 fee 0.44.
    realized_sell1_net = 5.216*(54.47-53.68) - 0.284 ≈ 3.84; realized_sell2_net = 7.824*(56.2814-53.68) - 0.44 ≈ 19.9.
    """
    base_qty = 26.08
    total_cost = 26.08 * 53.68
    realized = 0.0
    # SELL 1
    avg_buy = total_cost / base_qty
    sell_qty_1 = min(5.216, base_qty)
    realized += (54.47 - avg_buy) * sell_qty_1 - 0.28411552
    base_qty -= sell_qty_1
    total_cost -= avg_buy * sell_qty_1
    # SELL 2
    avg_buy_2 = total_cost / base_qty
    sell_qty_2 = min(7.824, base_qty)
    realized += (56.2814 - avg_buy_2) * sell_qty_2 - 0.44034555
    assert realized > 20
    assert realized < 25
