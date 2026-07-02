"""Test hesabı paper simülasyon: komisyon, kayma, fill yapısı."""

import pytest

from app.botengine.fee_utils import parse_fill_commission
from app.services.test_simulation import (
    TEST_TAKER_FEE_RATE,
    build_paper_market_fill,
    paper_buy_from_quote,
    paper_sell_from_base,
    slippage_fill_price,
)


def test_slippage_buy_above_mid():
    px = slippage_fill_price("BUY", 100.0, slippage_bps=10)
    assert px == pytest.approx(100.1, rel=1e-6)


def test_paper_buy_deducts_base_fee():
    net, quote, fill_px, fee_usdt = paper_buy_from_quote(
        100.0, 2000.0, symbol="ETHUSDT"
    )
    assert quote == pytest.approx(100.0, rel=1e-6)
    assert net < 100.0 / fill_px
    assert fee_usdt > 0
    fill = build_paper_market_fill("ETHUSDT", "BUY", quote_qty=100.0, mid_price=2000.0)
    _, asset, fee = parse_fill_commission(
        fill["fills"], "ETHUSDT", float(fill["fills"][0]["price"])
    )
    assert asset == "ETH"
    assert fee == pytest.approx(fee_usdt, rel=1e-4)


def test_paper_sell_deducts_usdt_fee():
    sold, net_quote, fill_px, fee_usdt = paper_sell_from_base(
        0.5, 2000.0, symbol="ETHUSDT"
    )
    assert sold == pytest.approx(0.5, rel=1e-6)
    gross = sold * fill_px
    assert net_quote == pytest.approx(gross * (1 - TEST_TAKER_FEE_RATE), rel=1e-4)
    assert fee_usdt > 0
