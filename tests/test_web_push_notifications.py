from app.services.web_push_notifications import format_trade_notification


def test_grid_buy_notification_has_symbol_operation_and_active_cycle():
    message = format_trade_notification(
        "solusdt",
        "trail_buy_grid",
        3,
        grid_index=1,
    )

    assert message == {
        "title": "SOLUSDT · Grid alış gerçekleşti",
        "body": "SOLUSDT için 2. grid alış gerçekleşti. 3. tur devam ediyor.",
    }


def test_grid_sell_notification_has_symbol_operation_and_active_cycle():
    message = format_trade_notification(
        "ethbtc",
        "trail_sell_grid",
        2,
        grid_index=0,
    )

    assert message == {
        "title": "ETHBTC · Grid satış gerçekleşti",
        "body": "ETHBTC için 1. grid satış gerçekleşti. 2. tur devam ediyor.",
    }


def test_profit_buy_notification_announces_cycle_transition():
    message = format_trade_notification(
        "xrpusdt",
        "trail_reentry_buy",
        4,
        new_cycle_id=5,
    )

    assert message == {
        "title": "XRPUSDT · Kâr alımı gerçekleşti",
        "body": "XRPUSDT için kâr alımı gerçekleşti. 4. tur kapandı, 5. tur başladı.",
    }


def test_profit_sell_notification_announces_cycle_transition():
    message = format_trade_notification(
        "btcusdt",
        "trail_profit_sell",
        7,
        new_cycle_id=8,
    )

    assert message == {
        "title": "BTCUSDT · Kâr satışı gerçekleşti",
        "body": "BTCUSDT için kâr satışı gerçekleşti. 7. tur kapandı, 8. tur başladı.",
    }


def test_unrelated_fill_does_not_create_a_push_message():
    assert format_trade_notification("SOLUSDT", "initial_allocation", 1) is None
