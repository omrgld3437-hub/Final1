from unittest.mock import MagicMock

import pytest

from app.botengine.virtual_wallet import get_bot_locked_balances_for_account
from app.services.bot_status_utils import is_bot_capital_locked


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("running", True),
        ("paused", True),
        ("paused_error", True),
        ("paused_insufficient_balance", True),
        ("stopped", False),
        ("deleted", False),
        ("", False),
    ],
)
def test_bot_capital_locked_statuses(status, expected):
    assert is_bot_capital_locked(status) is expected


def test_paused_error_virtual_wallet_stays_bot_locked():
    db = MagicMock()
    rows = [
        ("SOLUSDT", 0.25, 49.76, "paused_error"),
        ("ETHUSDT", 1.0, 10.0, "running"),
        ("BTCUSDT", 2.0, 20.0, "stopped"),
    ]
    select_result = MagicMock()
    select_result.fetchall.return_value = rows
    db.execute.side_effect = [None, select_result]

    locked = get_bot_locked_balances_for_account(db, account_id=3)

    assert locked["SOL"] == pytest.approx(0.25)
    assert locked["USDT"] == pytest.approx(59.76)
    assert locked["ETH"] == pytest.approx(1.0)
    assert "BTC" not in locked
