"""start_log_brief — soğuk başlatma meta özeti."""

from app.botengine.start_log_brief import build_cold_start_brief_meta


def test_cold_start_brief_dynamic_mode_off():
    meta = build_cold_start_brief_meta({"dynamic_mode": False, "max_buy_levels": 2})
    assert meta["dynamic_mode_enabled"] is False
    assert meta["dynamic_mode_ok"] is False
    assert "dynamic_mode_block_reason" not in meta


def test_cold_start_brief_dynamic_mode_ok():
    meta = build_cold_start_brief_meta({"dynamic_mode": True, "max_buy_levels": 2})
    assert meta["dynamic_mode_enabled"] is True
    assert meta["dynamic_mode_ok"] is True


def test_cold_start_brief_dynamic_mode_blocked():
    meta = build_cold_start_brief_meta({"dynamic_mode": True, "max_buy_levels": 0})
    assert meta["dynamic_mode_enabled"] is True
    assert meta["dynamic_mode_ok"] is False
    assert "max alım seviyesi" in meta["dynamic_mode_block_reason"]
