"""Test paper cüzdan: Toplam qty fiyat oynaklığından etkilenmemeli."""

import pytest
from unittest.mock import MagicMock, patch

from app.services.test_account import TEST_PAPER_BALANCE_USDT
from app.services.wallet_display import apply_test_wallet_equity_totals


def test_test_wallet_usdt_total_uses_budget_not_equity():
    db = MagicMock()
    wallet = {
        "assets": [
            {
                "asset": "USDT",
                "free": TEST_PAPER_BALANCE_USDT,
                "locked": 0.0,
            }
        ],
        "total_usd": TEST_PAPER_BALANCE_USDT,
    }
    allocated = 2500.0
    with (
        patch("app.services.test_account.is_test_account", return_value=True),
        patch(
            "app.botengine.virtual_wallet.get_bot_locked_balances_for_account",
            return_value={"USDT": 0.0},
        ),
        patch(
            "app.services.wallet_display.wallet_prices_map_from_datahub",
            return_value={"ETHUSDT": 3000.0},
        ),
        patch(
            "app.services.wallet_display._test_running_bots_usdt_budget",
            return_value=allocated,
        ),
        patch(
            "app.services.wallet_display.get_running_bots_equity_usd",
            return_value=allocated,
        ),
    ):
        apply_test_wallet_equity_totals(wallet, db, account_id=2)

    usdt = next(a for a in wallet["assets"] if a["asset"] == "USDT")
    assert usdt["total"] == 7500.0
    assert wallet["available_usd"] == 7500.0
    assert wallet["bot_locked_usd"] == allocated
    assert wallet["total_usd"] == TEST_PAPER_BALANCE_USDT


def test_test_wallet_eth_total_from_bot_locked_when_snapshot_qty_zero():
    """Eski snapshot ETH total=0 iken bot_locked miktarı tabloda Toplam olmalı."""
    db = MagicMock()
    wallet = {
        "assets": [
            {"asset": "USDT", "free": 7500.0, "locked": 0.0, "total": 7500.0},
            {
                "asset": "ETH",
                "free": 0.0,
                "locked": 0.0,
                "total": 0.0,
                "total_usd": 2500.0,
                "bot_locked": 1.23850666,
            },
        ],
        "total_usd": TEST_PAPER_BALANCE_USDT,
    }
    allocated = 5000.0
    with (
        patch("app.services.test_account.is_test_account", return_value=True),
        patch(
            "app.botengine.virtual_wallet.get_bot_locked_balances_for_account",
            return_value={"USDT": 2500.0, "ETH": 1.2385066582},
        ),
        patch(
            "app.services.wallet_display.wallet_prices_map_from_datahub",
            return_value={"ETHUSDT": 2018.56},
        ),
        patch(
            "app.services.wallet_display._test_running_bots_usdt_budget",
            return_value=allocated,
        ),
        patch(
            "app.services.wallet_display.get_running_bots_equity_usd",
            return_value=allocated,
        ),
    ):
        apply_test_wallet_equity_totals(wallet, db, account_id=2)

    eth = next(a for a in wallet["assets"] if a["asset"] == "ETH")
    assert eth["total"] == pytest.approx(1.23850666, rel=1e-4)
    assert eth["bot_locked"] == pytest.approx(1.23850666, rel=1e-4)
