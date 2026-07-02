from app.api import spot_routes


def test_klines_stale_fallback_respects_backfill_end_time():
    spot_routes.KLINES_CACHE.clear()
    spot_routes.KLINES_CACHE[("BTCUSDT", "1d", 3, "latest")] = (
        [
            {"t": 3000, "c": 3.0},
            {"t": 4000, "c": 4.0},
            {"t": 5000, "c": 5.0},
        ],
        100.0,
    )
    spot_routes.KLINES_CACHE[("BTCUSDT", "1d", 3, 2999)] = (
        [
            {"t": 1000, "c": 1.0},
            {"t": 2000, "c": 2.0},
        ],
        90.0,
    )

    candles = spot_routes._klines_stale_fallback("BTCUSDT", "1d", 3, end_time=2999)

    assert [c["t"] for c in candles] == [1000, 2000]
    assert all(c["t"] <= 2999 for c in candles)


def test_klines_stale_fallback_does_not_use_latest_for_older_page():
    spot_routes.KLINES_CACHE.clear()
    spot_routes.KLINES_CACHE[("BTCUSDT", "1d", 3, "latest")] = (
        [
            {"t": 3000, "c": 3.0},
            {"t": 4000, "c": 4.0},
            {"t": 5000, "c": 5.0},
        ],
        100.0,
    )

    assert spot_routes._klines_stale_fallback("BTCUSDT", "1d", 3, end_time=2999) == []
