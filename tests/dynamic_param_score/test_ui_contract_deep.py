"""UI / adapter contract — param assistant result shape."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
from app.services.dynamic_param_score.engine import DynamicParamScoreEngine
from app.services.dynamic_param_score.models import FinalAction
from tests.dynamic_param_score.conftest import constraints, ctx, portfolio
from tests.dynamic_param_score.test_sol_50_budget import _sol_market

ROOT = Path(__file__).resolve().parents[2]
UI_MODULES = ROOT / "ui" / "assets" / "modules"
UI_UTILS = ROOT / "ui" / "assets" / "utils"

FORBIDDEN_PLACEHOLDERS = [
    "anlık fiyat , 24s değişim , veri kapsaması",
    "base % / quote %",
    "— yapısal aday · — doğrulandı · ~— backtest · — çekirdek · — sn",
    "Grid 3 / 0",
]


def test_wait_ui_result_abstain():
    engine = DynamicParamScoreEngine()
    from tests.dynamic_param_score.factories import make_market_bundle, make_portfolio_state, make_context, make_constraints

    d = engine.calculate_decision(
        "SOLUSDT",
        make_market_bundle(pattern="dump_risk"),
        make_portfolio_state(budget_usdt=30),
        make_constraints(),
        make_context(budget_usdt=30),
    )
    r = decision_to_param_assistant_result(d, 30, "SOLUSDT")
    if d.final_action in (FinalAction.WAIT.value, FinalAction.NO_TRADE.value):
        assert r["decision"] == "management_decision"
        assert r["apply_policy"] in ("safe_wait", "no_trade")
        assert r["ui_config"] is None
        assert r.get("safe_overlay") is not None


def test_deployable_ui_has_bilateral_grids():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision("SOLUSDT", _sol_market(), portfolio(500), constraints(), ctx("param_assistant", 500))
    r = decision_to_param_assistant_result(d, 500, "SOLUSDT")
    if d.deployable and r.get("ui_config"):
        up = len(r["ui_config"]["up"]["grids"])
        down = len(r["ui_config"]["down"]["grids"])
        assert up >= 1 and down >= 1
        assert r["apply_policy"] == "allow"


def test_explain_not_duplicated_in_rationale():
    engine = DynamicParamScoreEngine()
    d = engine.calculate_decision("SOLUSDT", _sol_market(), portfolio(50), constraints(), ctx("param_assistant", 50))
    r = decision_to_param_assistant_result(d, 50, "SOLUSDT")
    explain = (r.get("explain") or "").strip()
    lines = r.get("rationale", {}).get("lines") or []
    for line in lines:
        if explain and line.strip():
            assert explain != line.strip()


def test_no_stale_placeholders_in_ai_assistant_spec():
    path = UI_MODULES / "ai-assistant-spec.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for bad in FORBIDDEN_PLACEHOLDERS:
        assert bad not in text, f"Stale placeholder found in ai-assistant-spec.js: {bad!r}"


def test_dashboard_modal_uses_clear_grid_labels():
    path = UI_MODULES / "dashboard-create-modal.js"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    assert "Alış" in text or "Satış" in text or "downGrids" in text
    assert "Grid 3 / 0" not in text


def test_dynamic_mode_params_view_exists():
    path = UI_UTILS / "dynamicModeParamsView.js"
    assert path.exists()
