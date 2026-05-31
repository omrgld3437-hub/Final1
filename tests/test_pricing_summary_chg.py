"""pricing_summary — ticker 24s / günlük baz % alanları."""
from __future__ import annotations

import app.services.pricing_summary as ps


def test_fx_daily_chg_pct_resets_on_new_day(monkeypatch):
    ps._fx_day_open.clear()
    ps._fx_day_open_date = "2026-05-30"
    assert ps._fx_daily_chg_pct("usdtry", 40.0) == 0.0
    assert ps._fx_daily_chg_pct("usdtry", 41.0) == 2.5
    ps._fx_day_open_date = "2026-05-31"
    assert ps._fx_daily_chg_pct("usdtry", 42.0) == 0.0


def test_resolve_chg_pct_prefers_hub(monkeypatch):
    monkeypatch.setattr(ps, "_ticker_chg_from_hub", lambda *s: 1.25 if s == ("USDTTRY",) else None)
    monkeypatch.setattr(ps, "_fx_daily_chg_pct", lambda f, p: 99.0)
    assert ps._resolve_chg_pct("usdtry", 45.0, ("USDTTRY",)) == 1.25
