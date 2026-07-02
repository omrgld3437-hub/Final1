"""Binance commission normalization."""

from app.botengine.fee_utils import (
    commission_to_usdt,
    parse_fill_commission,
    symbol_base_asset,
)


def test_symbol_base_asset_ethusdt():
    assert symbol_base_asset("ETHUSDT") == "ETH"


def test_buy_commission_in_base_coin():
    fills = [{"commission": "0.000015", "commissionAsset": "ETH"}]
    raw, asset, usdt = parse_fill_commission(fills, "ETHUSDT", 2100.0)
    assert asset == "ETH"
    assert raw == 0.000015
    assert abs(usdt - 0.0315) < 1e-6


def test_sell_commission_in_usdt():
    fills = [{"commission": "0.03", "commissionAsset": "USDT"}]
    raw, asset, usdt = parse_fill_commission(fills, "ETHUSDT", 2100.0)
    assert asset == "USDT"
    assert usdt == 0.03


def test_commission_to_usdt_direct():
    assert commission_to_usdt(0.00001, "ETH", "ETHUSDT", 2000.0) == 0.02
