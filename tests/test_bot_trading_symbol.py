"""Symbol normalization for bot trading pairs."""

from app.botengine.symbols import normalize_bot_trading_symbol


def test_normalize_bot_trading_symbol_base_only():
    assert normalize_bot_trading_symbol("sol") == "SOLUSDT"
    assert normalize_bot_trading_symbol("BTC") == "BTCUSDT"


def test_normalize_bot_trading_symbol_pair_unchanged():
    assert normalize_bot_trading_symbol("ETHUSDT") == "ETHUSDT"
    assert normalize_bot_trading_symbol("MULTI") == "MULTI"
