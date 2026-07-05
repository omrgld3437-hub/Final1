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
        assert r["apply_policy"] in ("allow", "deployable")


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


def test_create_bot_symbol_input_not_password_autofill_target():
    html = (ROOT / "ui" / "dashboard.html").read_text(encoding="utf-8")
    js = (UI_MODULES / "dashboard-create-modal.js").read_text(encoding="utf-8")
    assert 'id="fSymbol"' in html
    assert 'type="search"' in html
    assert 'name="search_crypto_pair"' in html
    assert 'autocomplete="new-password"' in html
    assert 'data-chrome-autofill-guard="true"' in html
    assert 'readonly' in html
    assert 'data-lpignore="true"' in html
    assert 'data-1p-ignore="true"' in html
    assert 'data-form-type="other"' in html
    assert 'data-protonpass-ignore="true"' in html
    assert '20260705-pa-apply-exact8' in html
    assert 'dashboard.css?v=pa-ai-apply4' in html
    assert "function dmCreateModalHardenSymbolAutofill" in js
    assert "function dmCreateModalArmSymbolReadonlyGuard" in js
    assert 'fSymbol.setAttribute("autocomplete", "new-password")' in js
    assert "fSymbol.readOnly = true" in js
    assert "fSymbol.readOnly = false" in js


def test_param_assistant_apply_forces_exact_grid_values():
    path = UI_MODULES / "dashboard-create-modal.js"
    text = path.read_text(encoding="utf-8")
    assert "function dmParamAssistantApplyRecommendationExactValues" in text
    assert "function dmParamAssistantNormalizeApplyRec" in text
    assert "rec._applyLocked === true" in text
    assert "_applyLocked: true" in text
    assert "preserveExistingValues: false" in text
    assert "dmParamAssistantApplyRecommendationExactValues(rec);" in text
    assert "rec._applySignature = dmParamAssistantApplySignature(rec);\n    dmParamAssistantApplyRecommendationExactValues(rec);" not in text
    assert "function dmParamAssistantBuildGridRowsForTyping" in text
    assert "dmParamAssistantBuildGridRowsForTyping('upGridRows', rec.upGrids.length, 'up')" in text
    assert "dmParamAssistantBuildGridRowsForTyping('downGridRows', rec.downGrids.length, 'down')" in text
    assert "DM_PARAM_ASSISTANT_FIELD_MIN_MS" in text
    assert "task.minActiveMs != null ? task.minActiveMs : DM_PARAM_ASSISTANT_FIELD_MIN_MS" in text
    assert "function dmParamAssistantVerifyAppliedRecommendation" in text
    assert "dmParamAssistantDisplayedGridLists" in text
    assert "function dmCreateModalParseDecimal" in text
    assert "dmCreateModalParseDecimal(el.value, 0)" in text
    assert "const upTrail = dmCreateModalParseDecimal" in text
    assert "apply signature mismatch" in text
    assert "classList.add('dm-ai-input-done')" not in text
    assert "DM_PARAM_ASSISTANT_INPUT_MS = (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.inputMs) || 18" in text
    assert "DM_PARAM_ASSISTANT_FIELD_PAUSE_MS = (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.fieldPauseMs) || 45" in text
    assert "DM_PARAM_ASSISTANT_FIELD_MIN_MS = (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.fieldMinMs) || (AI_ASSISTANT_SPEC.timing && AI_ASSISTANT_SPEC.timing.gridFieldMinMs) || 190" in text
    assert "return document.hidden ? 6 : 3" in text
    assert "var step = Math.min(stepMs != null ? stepMs : 32, document.hidden ? 8 : 14)" in text
    assert "var chunkMult = opts.fast ? 10 : 1" in text
    assert "now - lastScrollAt > 220" in text
    assert "dmParamAssistantBuildGridRowsExact('downGridRows', downGrids.length, 'down', downGrids)" in text
    assert "rec.rebuyEnabled === true || dmParamAssistantIsFiniteValue(rec.rebuyTrigger)" in text
    assert "function dmParamAssistantApplyFailed" in text
    assert "Öneri henüz hazır değil" in text
    assert "sell_grid_pct" in text
    assert "buy_qty_pct_of_quote" in text
    assert "dmParamAssistantShouldSuppressLastCreateParams" in text
    assert "dmParamAssistantSuppressLastCreateParams(600000)" in text
    css = (ROOT / "ui" / "assets" / "dashboard.css").read_text(encoding="utf-8")
    assert "dmAiInputSweep" in css
    assert "background-image: linear-gradient" in css
    assert ".page-dashboard #dmModal .grid-row input.dm-ai-input-writing" not in css
    assert "outline: 2px solid rgba(6, 255, 165, 0.55)" in css


def test_bot_detail_cycle_trades_render_is_row_safe():
    text = (ROOT / "ui" / "bot.html").read_text(encoding="utf-8")
    assert "function escapeHtml(s) { return String(s == null ? '' : s)" in text
    assert "console.warn('cycle trade row render'" in text
    assert "İşlem satırı okunamadı; ham kayıt korundu." in text


def test_dynamic_mode_params_view_exists():
    path = UI_UTILS / "dynamicModeParamsView.js"
    assert path.exists()
