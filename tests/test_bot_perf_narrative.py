from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.services.bot_perf_narrative import (
    build_month_narrative,
    enumerate_month_keys_from_start,
    load_bot_completed_cycles_merged,
    month_key_to_label,
    _format_usd,
)
from app.services.bot_perf_narrative_templates import pool_size


def test_month_key_to_label():
    assert month_key_to_label("2026-06") == "Haziran 2026"


def test_enumerate_months_from_start():
    keys = enumerate_month_keys_from_start("2026-05")
    assert keys[0] == "2026-05"
    assert keys[-1] >= "2026-05"


# ---------------------------------------------------------------------------
# Permanent template pool
# ---------------------------------------------------------------------------


def test_template_pool_has_chatgpt_style_expansion_pack():
    assert pool_size() >= 690


def _sample_cycles():
    return [
        {
            "cycle_id": 1,
            "cycle_type": "CASH",
            "completed_reason": "trail_profit_sell",
            "cash_pnl_usdt": 0.55,
            "cash_fees_usdt": 0.03,
            "inventory_coin_adv_qty": 0,
            "inventory_fees_usdt": 0,
            "close_price_quote_per_base": 140.0,
            "completed_at": "2026-06-10T12:00:00+00:00",
            "started_at": "2026-06-10T08:00:00+00:00",
        }
    ]


def test_build_month_narrative_with_cycles():
    out = build_month_narrative(
        month_key="2026-06",
        cycles=_sample_cycles(),
        symbol="SOLUSDT",
        initial_capital=50.0,
        session_alpha_pct=3.16,
    )
    assert out["metrics"]["total_cycles"] == 1
    assert out["metrics"]["net_cash_usdt"] == 0.52
    assert len(out["sections"]) >= 6

    cycle_sec = next(s for s in out["sections"] if s["id"] == "cycles")
    assert len(cycle_sec["items"]) == 1
    narrative = cycle_sec["items"][0]["narrative"]
    # Invariants guaranteed regardless of which template variant is chosen:
    assert narrative.startswith("Tur #1")
    assert "+$0.52" in narrative  # net figure is always carried
    assert "+$0.55" in narrative  # gross figure is always carried


def test_narrative_is_deterministic():
    """Same month/symbol → identical report (stable, doesn't flicker on refresh)."""
    a = build_month_narrative(
        month_key="2026-06", cycles=_sample_cycles(), symbol="SOLUSDT",
        initial_capital=50.0, session_alpha_pct=3.16,
    )
    b = build_month_narrative(
        month_key="2026-06", cycles=_sample_cycles(), symbol="SOLUSDT",
        initial_capital=50.0, session_alpha_pct=3.16,
    )
    assert a == b


def test_month_narrative_explains_negative_alpha_with_positive_cash():
    cycles = [
        {
            "cycle_id": 1, "cycle_type": "CASH", "completed_reason": "trail_profit_sell",
            "cash_pnl_usdt": 1.58, "cash_fees_usdt": 0.10,
            "inventory_coin_adv_qty": 0, "inventory_fees_usdt": 0,
            "close_price_quote_per_base": 67.23,
            "completed_at": "2026-06-10T12:00:00+00:00", "started_at": "2026-06-10T08:00:00+00:00",
        },
        {
            "cycle_id": 2, "cycle_type": "CASH", "completed_reason": "trail_profit_sell",
            "cash_pnl_usdt": 0.55, "cash_fees_usdt": 0.03,
            "inventory_coin_adv_qty": 0, "inventory_fees_usdt": 0,
            "close_price_quote_per_base": 68.09,
            "completed_at": "2026-06-12T12:00:00+00:00", "started_at": "2026-06-11T08:00:00+00:00",
        },
    ]
    out = build_month_narrative(
        month_key="2026-06", cycles=cycles, symbol="SOLUSDT",
        initial_capital=50.0, session_alpha_pct=-5.23,
    )
    net = out["metrics"]["net_cash_usdt"]
    assert net > 0  # realize cash is positive
    # Headline always carries the net figure.
    assert _format_usd(net) in out["headline"]

    summary = next(s for s in out["sections"] if s["id"] == "summary")
    joined = " ".join(summary["paragraphs"]).lower()
    # Alpha is always explained in the summary, framed as opportunity cost.
    assert "alpha" in joined
    assert ("fırsat maliyeti" in joined) or ("benchmark" in joined) or ("al-tut" in joined)

    fees = next(s for s in out["sections"] if s["id"] == "fees")
    assert any("komisyon" in p.lower() for p in fees["paragraphs"])


def test_inventory_leg_reads_in_coin_units():
    cycles = [
        {
            "cycle_id": 7, "cycle_type": "INVENTORY", "completed_reason": "trail_reentry_buy",
            "cash_pnl_usdt": 0, "cash_fees_usdt": 0,
            "inventory_coin_adv_qty": 0.0123, "inventory_fees_usdt": 0.02,
            "close_price_quote_per_base": 140.0,
            "completed_at": "2026-06-15T12:00:00+00:00", "started_at": "2026-06-15T06:00:00+00:00",
        }
    ]
    out = build_month_narrative(
        month_key="2026-06", cycles=cycles, symbol="SOLUSDT", initial_capital=50.0,
    )
    cyc = next(s for s in out["sections"] if s["id"] == "cycles")["items"][0]
    assert cyc["side"] == "SELL"
    assert cyc["narrative"].startswith("Tur #7")
    assert "SOL" in cyc["narrative"]  # coin-unit framing


def test_loss_is_shown_with_minus_sign():
    """A losing cash cycle must never read like a gain (-$X, not $X)."""
    assert _format_usd(-0.35) == "-$0.35"
    assert _format_usd(0.52) == "+$0.52"
    cycles = [
        {
            "cycle_id": 1, "cycle_type": "CASH", "completed_reason": "trail_profit_sell",
            "cash_pnl_usdt": -0.30, "cash_fees_usdt": 0.05,
            "inventory_coin_adv_qty": 0, "inventory_fees_usdt": 0,
            "close_price_quote_per_base": 140.0,
            "completed_at": "2026-06-13T12:00:00+00:00", "started_at": "2026-06-13T06:00:00+00:00",
        }
    ]
    out = build_month_narrative(
        month_key="2026-06", cycles=cycles, symbol="SOLUSDT", initial_capital=50.0,
    )
    assert out["metrics"]["net_cash_usdt"] == -0.35
    assert "-$0.35" in out["sections"][2]["items"][0]["narrative"]


def test_inventory_led_month_is_not_called_breakeven():
    """Cash ~0 but a positive coin gain → headline must lead with the coin
    result, not call it a break-even/zero month."""
    cycles = [
        {
            "cycle_id": 1, "cycle_type": "INVENTORY", "completed_reason": "trail_reentry_buy",
            "cash_pnl_usdt": 0, "cash_fees_usdt": 0,
            "inventory_coin_adv_qty": 0.0123, "inventory_fees_usdt": 0.02,
            "close_price_quote_per_base": 140.0,
            "completed_at": "2026-06-10T12:00:00+00:00", "started_at": "2026-06-10T06:00:00+00:00",
        }
    ]
    out = build_month_narrative(
        month_key="2026-06", cycles=cycles, symbol="SOLUSDT", initial_capital=50.0,
    )
    hl = out["headline"].lower()
    assert ("envanter" in hl) or ("coin" in hl)
    assert "başa baş" not in hl


def test_negative_inventory_is_not_called_advantage():
    """A coin loss must not be phrased as an 'avantaj'."""
    cycles = [
        {
            "cycle_id": 1, "cycle_type": "INVENTORY", "completed_reason": "trail_reentry_buy",
            "cash_pnl_usdt": 0, "cash_fees_usdt": 0,
            "inventory_coin_adv_qty": -0.008, "inventory_fees_usdt": 0.02,
            "close_price_quote_per_base": 140.0,
            "completed_at": "2026-06-10T12:00:00+00:00", "started_at": "2026-06-10T06:00:00+00:00",
        }
    ]
    out = build_month_narrative(
        month_key="2026-06", cycles=cycles, symbol="SOLUSDT", initial_capital=50.0,
    )
    summary = next(s for s in out["sections"] if s["id"] == "summary")
    inv_paras = [p for p in summary["paragraphs"] if "-0.00800000" in p]
    assert inv_paras  # the coin change is reported
    # Framed negatively (loss), never as a positive "avantaj".
    neg_words = ("dezavantaj", "kayıp", "azal", "negatif", "geril", "küçül")
    assert all(any(w in p for w in neg_words) for p in inv_paras)


def test_neutral_cycle_is_not_called_profit():
    """net == 0 cycle must read 'başa baş/nötr', not 'kârla kapandı'."""
    cycles = [
        {
            "cycle_id": 1, "cycle_type": "CASH", "completed_reason": "trail_profit_sell",
            "cash_pnl_usdt": 0.05, "cash_fees_usdt": 0.05,
            "inventory_coin_adv_qty": 0, "inventory_fees_usdt": 0,
            "close_price_quote_per_base": 140.0,
            "completed_at": "2026-06-10T12:00:00+00:00", "started_at": "2026-06-10T06:00:00+00:00",
        }
    ]
    out = build_month_narrative(
        month_key="2026-06", cycles=cycles, symbol="SOLUSDT", initial_capital=50.0,
    )
    narr = out["sections"][2]["items"][0]["narrative"]
    assert "+$0.00" in narr
    assert "kârla kapandı" not in narr


def test_load_cycles_respects_started_at(monkeypatch):
    bot = MagicMock()
    bot.id = 1
    bot.account_id = 3
    bot.symbol = "SOLUSDT"
    bot.started_at = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)

    state = {
        "completed_cycle_dual_pnls": [
            {
                "cycle_id": 1, "cash_pnl_usdt": 1.0, "cash_fees_usdt": 0,
                "inventory_coin_adv_qty": 0, "completed_at": "2026-05-15T12:00:00+00:00",
            },
            {
                "cycle_id": 2, "cash_pnl_usdt": 0.5, "cash_fees_usdt": 0,
                "inventory_coin_adv_qty": 0, "completed_at": "2026-06-15T12:00:00+00:00",
            },
        ]
    }

    monkeypatch.setattr("app.services.bot_perf_narrative.load_state", lambda db, bid: state)
    monkeypatch.setattr(
        "app.services.bot_perf_narrative.reconcile_bot_cycles_file_with_state",
        lambda *a, **k: None, raising=False,
    )
    monkeypatch.setattr("app.services.bot_perf_file_store.list_bot_completed_cycles", lambda bid: [])
    monkeypatch.setattr(
        "app.services.bot_perf_file_store.reconcile_bot_cycles_file_with_state",
        lambda *a, **k: None,
    )

    merged = load_bot_completed_cycles_merged(MagicMock(), bot, state)
    assert len(merged) == 1
    assert merged[0]["cycle_id"] == 2
