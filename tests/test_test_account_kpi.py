"""Test hesabı admin/dashboard spot KPI hizalaması."""

import pytest
from unittest.mock import MagicMock, patch

from app.services.test_account_kpi import (
    compute_test_account_spot_strip_total_usd,
    get_or_set_test_daily_spot_ref_usd,
)


def test_daily_ref_sticky_within_tr_day(tmp_path):
    from app.services.test_account_kpi import set_test_daily_spot_ref_usd

    with (
        patch("app.services.test_account_kpi._REF_ROOT", tmp_path),
        patch("app.utils.tz_utils.turkey_today_date_str", return_value="2026-05-29"),
    ):
        set_test_daily_spot_ref_usd(2, 10000.0, "2026-05-29")
        ref2 = get_or_set_test_daily_spot_ref_usd(2, 9987.01)
    assert ref2 == 10000.0


def test_spot_strip_total_sums_avail_bot_locked():
    wallet = {
        "available_usd": 7500.0,
        "bot_locked_usd": 2487.01,
        "locked_usd": 0.0,
        "assets": [
            {"asset": "USDT", "available": 7500.0, "locked": 0, "bot_locked": 0},
        ],
    }
    db = MagicMock()
    with (
        patch(
            "app.services.wallet_display.get_running_bots_equity_usd",
            return_value=2487.01,
        ),
        patch(
            "app.services.wallet_display.wallet_prices_map_from_datahub",
            return_value={},
        ),
    ):
        total, avail, bot, locked = compute_test_account_spot_strip_total_usd(
            wallet, db, 2
        )
    assert avail == 7500.0
    assert bot == 2487.01
    assert locked == 0.0
    assert total == pytest.approx(9987.01, rel=1e-4)
