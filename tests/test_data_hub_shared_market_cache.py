import time

from app.services.data_hub import DataHub


def _hub(snapshot_path) -> DataHub:
    hub = DataHub()
    hub._shared_market_snapshot_path = str(snapshot_path)
    hub._shared_market_snapshot_mtime = 0.0
    return hub


def test_market_catalogue_is_shared_between_web_workers(tmp_path):
    snapshot_path = tmp_path / "datahub_market_snapshot.json"
    now = time.time()
    leader = _hub(snapshot_path)
    leader.coin_list = [
        {
            "symbol": "SOLUSDT",
            "price": 150.0,
            "change24h": 2.5,
            "volume24h": 10.0,
            "quoteVolume24h": 1500.0,
        }
    ]
    leader.coin_list_ts = now
    leader.all_symbols = ["AVAXUSDT", "SOLUSDT", "SOLETH"]
    leader.all_symbols_ts = now

    assert leader._persist_shared_market_snapshot() is True

    follower = _hub(snapshot_path)
    assert [coin["symbol"] for coin in follower.get_coin_list()] == ["SOLUSDT"]
    assert follower.get_symbols_for_scope("all") == [
        "AVAXUSDT",
        "SOLETH",
        "SOLUSDT",
    ]
    assert follower.get_symbols_for_scope("usdt") == ["AVAXUSDT", "SOLUSDT"]


def test_live_prices_keep_favorites_available_without_shared_catalogue(tmp_path):
    hub = _hub(tmp_path / "missing.json")
    hub.prices = {
        "SOLUSDT": {
            "price": 150.0,
            "change24h": 1.25,
            "volume24h": 20.0,
        },
        "AVAXUSDT": {
            "price": 25.0,
            "change24h": -0.5,
            "volume24h": 100.0,
        },
        "SOLETH": {
            "price": 0.05,
            "change24h": 0.2,
            "volume24h": 50.0,
        },
    }

    coins = hub.get_coin_list()
    assert [coin["symbol"] for coin in coins] == ["SOLUSDT", "AVAXUSDT"]
    assert hub.get_symbols_for_scope("all") == ["AVAXUSDT", "SOLETH", "SOLUSDT"]


def test_stale_in_memory_catalogue_uses_newer_shared_snapshot(tmp_path):
    snapshot_path = tmp_path / "datahub_market_snapshot.json"
    now = time.time()
    leader = _hub(snapshot_path)
    leader.coin_list = [{"symbol": "SOLUSDT"}]
    leader.coin_list_ts = now
    leader.all_symbols = ["SOLUSDT"]
    leader.all_symbols_ts = now
    assert leader._persist_shared_market_snapshot() is True

    follower = _hub(snapshot_path)
    follower.coin_list = [{"symbol": "OLDUSDT"}]
    follower.coin_list_ts = now - follower.COIN_LIST_TTL - 1
    follower.all_symbols = ["OLDUSDT"]
    follower.all_symbols_ts = now - follower.ALL_SYMBOLS_TTL - 1

    assert [coin["symbol"] for coin in follower.get_coin_list()] == ["SOLUSDT"]
    assert follower.get_symbols_for_scope("all") == ["SOLUSDT"]
