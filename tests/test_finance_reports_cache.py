from app.api.finance_reports import _deposit_withdraw_cache_key


def test_deposit_withdraw_cache_key_buckets_moving_end_time():
    first = _deposit_withdraw_cache_key(
        account_id=691363,
        start_ms=1_770_000_000_123,
        end_ms=1_770_000_120_456,
        symbol_filter=None,
    )
    second = _deposit_withdraw_cache_key(
        account_id=691363,
        start_ms=1_770_000_000_999,
        end_ms=1_770_000_179_999,
        symbol_filter=None,
    )

    assert first == second


def test_deposit_withdraw_cache_key_keeps_symbol_filter():
    base = _deposit_withdraw_cache_key(1, 1_770_000_000_000, 1_770_000_120_000, None)
    eth = _deposit_withdraw_cache_key(1, 1_770_000_000_000, 1_770_000_120_000, "ETH")

    assert base != eth
