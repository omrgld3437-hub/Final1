"""Plain-language regime labels for PA/DM main screen."""

from __future__ import annotations

from app.services.dynamic_param_score.regime_display import (
    build_regime_technical_label,
    format_confidence_pct,
    market_status_plain,
    risk_tone_plain,
)
from app.services.dynamic_param_score.v6.v6_pa_display import contextual_market_status_plain


def test_r6_market_status_plain():
    assert market_status_plain("R6") == "Fiyat tepede, geri çekilme riski var"


def test_r2_market_status_plain():
    assert market_status_plain("R2") == "Fiyat yatay bölgede, iki yönlü fırsat var"


def test_r8_market_status_plain():
    assert market_status_plain("R8") == "Sert düşüş var, yüksek riskli savunmacı mod"


def test_risk_tone_plain_maps_controlled_defensive():
    assert risk_tone_plain("Kontrollü savunmacı") == "Temkinli strateji"


def test_format_confidence_pct():
    assert format_confidence_pct(78) == "%78"
    assert format_confidence_pct(78.4) == "%78"


def test_technical_label_includes_sub_and_micro():
    label = build_regime_technical_label(
        {
            "regime_id": "R6",
            "sub_id": "41",
            "micro_id": "161",
            "terminal_id": "T553",
            "behavior_id": "PB06",
            "name": "Tepe / dağılım / zayıflama / alt-41 / mikro-161 / T553",
        }
    )
    assert "alt-41" in label
    assert "mikro-161" in label
    assert "T553" in label


def test_r3_contextual_market_status_uses_near_buy_grid_language():
    trace = [{"name": "volatility", "class": "V2"}]
    status = contextual_market_status_plain("R3", trace)
    assert "derin alış açık" not in status.lower()
    assert "Yakın alış gridleri açık" in status
    assert "son kademe daha derin destek" in status
