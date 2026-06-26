"""Black-box Param Assistant E2E helpers — HTTP user flow, invariants, reporting."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "AAVEUSDT",
    "MANAUSDT",
    "SANDUSDT",
    "PONDUSDT",
    "AGLDUSDT",
    "JTOUSDT",
    "ASRUSDT",
    "SFPUSDT",
    "PROVEUSDT",
    "TONUSDT",
    "ENJUSDT",
    "RAREUSDT",
)

DEFAULT_BUDGETS: Tuple[float, ...] = (50.0, 100.0, 1000.0)

SCENARIO_NAMES: Tuple[str, ...] = (
    "first_start",
    "has_base",
    "only_base",
    "low_budget",
    "normal_budget",
)

UI_TEXT_CONTRACT: Dict[str, Dict[str, str]] = {
    "single_probe_recommendation": {
        "ui_label": "Tek kademe deneme seviyesi",
        "ui_summary": (
            "Bu koşulda gerçek grid kurulamadı. Sistem yalnızca tek kademe deneme seviyesi "
            "hesapladı; otomatik grid deploy kapalı."
        ),
    },
    "recommended_grid": {
        "ui_label": "Parametre üretildi — deploy kapalı",
        "ui_summary": (
            "Parametre üretildi ancak mevcut güvenlik koşulları otomatik deploy için yeterli değil."
        ),
    },
    "deployable_grid": {
        "ui_label": "Deploy edilebilir grid",
        "ui_summary": "Bu set güvenlik kontrollerinden geçti ve otomatik deploy edilebilir.",
    },
    "first_start_buy_only": {
        "ui_label": "İlk tur — yalnızca alış grid",
        "ui_summary": (
            "Base yok; satış grid şu an kurulamaz. İlk tur alış modu açık olduğu için "
            "sadece alış grid kurulabilir."
        ),
    },
    "runtime_synthetic": {
        "ui_summary": (
            "Bu set gerçek profil rafından değil, runtime synthetic güvenlik üreticisinden geldi."
        ),
    },
    "NO_SELLABLE_BASE": {
        "ui_summary": (
            "Base yok; satış grid kurulamaz. Bilateral grid için önce base oluşmalı veya "
            "FIRST_START_BUY_ONLY modu seçilmelidir."
        ),
    },
}


@dataclass
class ScenarioSpec:
    name: str
    budget: Optional[float] = None
    base_alloc_frac: Optional[float] = None
    base_balance_usdt: Optional[float] = None
    quote_balance_usdt: Optional[float] = None
    first_start_buy_only: bool = False


def expand_scenario(name: str, budget: float) -> ScenarioSpec:
    n = (name or "first_start").strip().lower()
    if n == "first_start":
        return ScenarioSpec(name=n, budget=budget)
    if n == "has_base":
        return ScenarioSpec(name=n, budget=budget, base_alloc_frac=0.42)
    if n == "only_base":
        return ScenarioSpec(
            name=n,
            budget=budget,
            base_alloc_frac=0.78,
            quote_balance_usdt=max(25.0, budget * 0.12),
        )
    if n == "low_budget":
        return ScenarioSpec(name=n, budget=50.0)
    if n == "normal_budget":
        return ScenarioSpec(name=n, budget=1000.0)
    return ScenarioSpec(name=n, budget=budget)


def build_user_request(spec: ScenarioSpec, symbol: str) -> Dict[str, Any]:
    """Payload mirroring Param Assistant UI → POST /api/param-assistant/calculate."""
    budget = float(spec.budget or 50.0)
    payload: Dict[str, Any] = {
        "symbol": symbol,
        "budget": budget,
        "analysis_level": "professional_auto",
        "first_start_buy_only": bool(spec.first_start_buy_only),
        "dry_run": True,
    }
    if spec.base_alloc_frac is not None:
        payload["base_alloc_frac"] = spec.base_alloc_frac
    if spec.base_balance_usdt is not None:
        payload["base_balance_usdt"] = spec.base_balance_usdt
    if spec.quote_balance_usdt is not None:
        payload["quote_balance_usdt"] = spec.quote_balance_usdt
    return payload


def _pct_distribution(raw: Optional[Sequence[float]]) -> List[float]:
    if not raw:
        return []
    vals = [float(x) for x in raw]
    total = sum(vals) or 1.0
    if total <= 1.5:
        return [round(v * 100, 2) for v in vals]
    return [round(v, 2) for v in vals]


def _grid_count_from_config(cfg: Optional[Dict[str, Any]], side: str) -> int:
    if not cfg:
        return 0
    block = cfg.get(side) or {}
    grids = block.get("grids") or []
    return len(grids)


def _first_grid_distance(cfg: Optional[Dict[str, Any]], side: str) -> Optional[float]:
    if not cfg:
        return None
    grids = (cfg.get(side) or {}).get("grids") or []
    if not grids:
        return None
    row = grids[0] or {}
    for key in ("buy_grid_pct", "sell_grid_pct", "grid_pct", "pct"):
        if row.get(key) is not None:
            return float(row[key])
    return None


def derive_ui_contract(result_type: str, *, runtime: bool = False) -> Dict[str, str]:
    rt = str(result_type or "")
    out: Dict[str, str] = {}
    spec = UI_TEXT_CONTRACT.get(rt, {})
    out["ui_label"] = spec.get("ui_label", "")
    out["ui_summary"] = spec.get("ui_summary", "")
    if runtime:
        out["ui_runtime_disclosure"] = UI_TEXT_CONTRACT["runtime_synthetic"]["ui_summary"]
    return out


def extract_audit_row(
    response: Dict[str, Any],
    *,
    symbol: str,
    budget: float,
    scenario: str,
    request: Dict[str, Any],
) -> Dict[str, Any]:
    """Flatten API JSON into audit report row (black-box — only response fields)."""
    params = response.get("params") or {}
    tel = response.get("telemetry") or {}
    pool = tel.get("param_pool") or {}
    sel = response.get("selection_telemetry") or {}
    ctx = sel.get("selection_context") or pool.get("selection_context") or {}
    feas_keys = (
        "distribution_invalid",
        "deploy_blocked_reason",
        "exposure_hard_cap_breach",
        "first_start_buy_only",
        "single_probe_only",
        "worst_case_base_exposure_frac",
        "max_base_exposure_frac",
    )
    feas = {k: tel.get(k) for k in feas_keys if tel.get(k) is not None}

    ui_cfg = response.get("ui_config") or response.get("recommendation_config")
    buy_n = int(params.get("buy_grid_count") or 0) or _grid_count_from_config(ui_cfg, "down")
    sell_n = int(params.get("sell_grid_count") or 0) or _grid_count_from_config(ui_cfg, "up")
    buy_dist = _pct_distribution(params.get("buy_qty_distribution"))
    sell_dist = _pct_distribution(params.get("sell_qty_distribution"))

    profile_source = str(ctx.get("profile_source") or "")
    runtime_used = bool(
        ctx.get("runtime_safe_profile_generated")
        or sel.get("runtime_safe_profile_generated")
        or profile_source == "runtime_synthetic"
    )
    if runtime_used:
        profile_source = "runtime_synthetic"

    exact_n = ctx.get("exact_route_candidate_count")
    if exact_n is None:
        exact_n = sel.get("exact_route_candidate_count")
    fb_n = ctx.get("fallback_candidate_count")
    if fb_n is None:
        fb_n = sel.get("fallback_candidate_count")
    scored_n = ctx.get("scored_candidate_count")
    if scored_n is None:
        scored_n = sel.get("scored_candidate_count") or sel.get("candidate_count")

    worst = feas.get("worst_case_base_exposure_frac")
    if worst is None:
        worst = tel.get("worst_case_base_exposure_frac")
    max_exp = feas.get("max_base_exposure_frac")
    if max_exp is None and params:
        max_exp = params.get("max_base_exposure_frac")

    blocking = [str(b) for b in (response.get("blocking_reasons") or [])]
    warnings = [str(w) for w in (response.get("warnings") or [])]
    result_type = str(response.get("result_type") or "")
    ui_contract = derive_ui_contract(result_type, runtime=runtime_used)

    base_bal = request.get("base_balance_usdt")
    if base_bal is None and request.get("base_alloc_frac") is not None:
        base_bal = float(budget) * float(request["base_alloc_frac"])
    elif base_bal is None:
        base_bal = 0.0

    quote_bal = request.get("quote_balance_usdt")
    if quote_bal is None:
        quote_bal = float(budget) - float(base_bal or 0)

    market_sig = ctx.get("market_signature") or tel.get("market_signature") or {}
    explain = str(response.get("explain") or "")
    runtime_disclosure = (
        runtime_used
        and (
            "runtime" in explain.lower()
            or "runtime" in json.dumps(sel, default=str).lower()
            or sel.get("runtime_safe_profile_generated")
        )
    )

    row = {
        "symbol": symbol,
        "budget": budget,
        "scenario": scenario,
        "base_balance": round(float(base_bal or 0), 4),
        "quote_balance": round(float(quote_bal or 0), 4),
        "first_start_buy_only_enabled": bool(request.get("first_start_buy_only")),
        "dry_run": bool(request.get("dry_run", True)),
        "ok": response.get("ok"),
        "http_status": response.get("_http_status", 200),
        "result_type": result_type,
        "final_action": response.get("final_action"),
        "deployable": bool(response.get("deployable")),
        "profile_source": profile_source,
        "selected_profile_id": response.get("selected_profile") or sel.get("selected_template_key"),
        "route_key": sel.get("route_key") or ctx.get("route_key"),
        "exact_candidate_count": exact_n,
        "fallback_candidate_count": fb_n,
        "scored_candidate_count": scored_n,
        "runtime_profile_used": runtime_used,
        "ui_contains_runtime_disclosure": runtime_disclosure,
        "regime": response.get("regime_tag"),
        "structure": market_sig.get("structure") or market_sig.get("structure_code"),
        "volatility_tier": market_sig.get("vol_code") or market_sig.get("volatility_tier"),
        "risk_state": response.get("risk_state") or response.get("effective_risk_state"),
        "buy_grid_count": buy_n,
        "sell_grid_count": sell_n,
        "buy_distribution": buy_dist,
        "sell_distribution": sell_dist,
        "first_buy_distance": _first_grid_distance(ui_cfg, "down"),
        "first_sell_distance": _first_grid_distance(ui_cfg, "up"),
        "max_exposure": max_exp,
        "worst_case_exposure": worst,
        "invalid_distribution": bool(feas.get("distribution_invalid")),
        "spread_unsafe": response.get("regime_tag") == "SPREAD_UNSAFE"
        or "SPREAD_HIGH" in [b.upper() for b in blocking],
        "low_liquidity_block": "LIQUIDITY_LOW" in [b.upper() for b in blocking],
        "dump_risk_block": "DUMP_RISK" in [b.upper() for b in blocking],
        "data_quality_ok": "DATA_QUALITY_LOW" not in [b.upper() for b in blocking],
        "block_reasons": blocking,
        "warnings": warnings,
        "ui_label": ui_contract.get("ui_label"),
        "ui_summary": ui_contract.get("ui_summary"),
        "explain_excerpt": explain[:240] if explain else "",
        "invariant_failures": [],
        "acceptance_flags": {},
    }
    row["invariant_failures"] = check_hard_invariants(row)
    row["ui_contract_failures"] = check_ui_contract(row, response)
    row["invariant_failures"].extend(row["ui_contract_failures"])
    return row


def _fail(code: str, expected: str, got: Any) -> Dict[str, str]:
    return {"code": code, "expected": expected, "got": str(got)}


def _dist_near_equal(dist: Sequence[float], gap: float = 5.0) -> bool:
    if len(dist) < 3:
        return False
    return (max(dist) - min(dist)) < gap


def _is_fifty_fifty(dist: Sequence[float]) -> bool:
    if len(dist) != 2:
        return False
    return abs(dist[0] - dist[1]) < 3.0


def check_hard_invariants(row: Dict[str, Any]) -> List[Dict[str, str]]:
    """Hard invariant suite on flattened audit row."""
    failures: List[Dict[str, str]] = []
    rt = str(row.get("result_type") or "")
    deployable = bool(row.get("deployable"))
    buy_n = int(row.get("buy_grid_count") or 0)
    sell_n = int(row.get("sell_grid_count") or 0)
    buy_dist = list(row.get("buy_distribution") or [])
    risk = str(row.get("risk_state") or "").upper()
    fs_buy = bool(row.get("first_start_buy_only_enabled"))
    base_bal = float(row.get("base_balance") or 0)
    worst = row.get("worst_case_exposure")
    max_exp = row.get("max_exposure")
    blocking = [str(b).upper() for b in (row.get("block_reasons") or [])]

    if rt == "deployable_grid":
        if not deployable:
            failures.append(_fail("deployable_grid_flag", "deployable=true", deployable))
        if buy_n < 2:
            failures.append(_fail("deployable_min_buy_grids", "buy_grid_count>=2", buy_n))
        if sell_n < 2 and not fs_buy:
            failures.append(_fail("deployable_min_sell_grids", "sell_grid_count>=2 or fs_buy", sell_n))
        if row.get("invalid_distribution"):
            failures.append(_fail("deployable_invalid_distribution", "false", True))
        if row.get("spread_unsafe"):
            failures.append(_fail("deployable_spread_unsafe", "false", True))
        if row.get("low_liquidity_block"):
            failures.append(_fail("deployable_low_liquidity", "false", True))
        if row.get("dump_risk_block"):
            failures.append(_fail("deployable_dump_risk", "false", True))
        if row.get("data_quality_ok") is False:
            failures.append(_fail("deployable_data_quality", "true", False))

    if buy_n < 2:
        if rt == "deployable_grid":
            failures.append(_fail("one_grid_deployable", "result_type!=deployable_grid", rt))
        if deployable:
            failures.append(_fail("one_grid_deployable_flag", "deployable=false", deployable))
        if rt not in (
            "recommended_grid",
            "single_probe_recommendation",
            "management_decision",
            "first_start_buy_only",
            "no_trade",
        ):
            failures.append(_fail("one_grid_result_type", "probe/recommended/management", rt))

    if buy_n == 2 and buy_dist:
        if _is_fifty_fifty(buy_dist):
            failures.append(_fail("two_grid_fifty_fifty", "not 50/50", buy_dist))
        if buy_dist[0] > 40.0 + 1e-6:
            failures.append(_fail("two_grid_first_weight", "first<=40", buy_dist[0]))
        if buy_dist[1] < 60.0 - 1e-6:
            failures.append(_fail("two_grid_second_weight", "second>=60", buy_dist[1]))

    if buy_n == 3 and buy_dist and risk in ("DEFENSIVE", "CAUTION"):
        if buy_dist[0] > 18.0 + 1e-6:
            failures.append(_fail("three_grid_first_weight", "first<=18", buy_dist[0]))
        if buy_dist[1] > 35.0 + 1e-6:
            failures.append(_fail("three_grid_second_weight", "second<=35", buy_dist[1]))
        if buy_dist[-1] < 50.0 - 1e-6:
            failures.append(_fail("three_grid_last_weight", "last>=50", buy_dist[-1]))
        if (max(buy_dist) - min(buy_dist)) < 30.0 - 1e-6:
            failures.append(_fail("three_grid_equalish", "max-min>=30", buy_dist))
        if _dist_near_equal(buy_dist, gap=8.0):
            failures.append(_fail("three_grid_near_equal", "not near-equal thirds", buy_dist))

    if worst is not None and max_exp is not None:
        if float(worst) > float(max_exp) + 1e-9:
            if deployable:
                failures.append(_fail("exposure_cap_deployable", "deployable=false", deployable))
            if "EXPOSURE_HARD_CAP_BREACH" not in blocking:
                failures.append(
                    _fail("exposure_cap_reason", "EXPOSURE_HARD_CAP_BREACH in block_reasons", blocking)
                )

    if row.get("runtime_profile_used"):
        if int(row.get("exact_candidate_count") or 0) > 0:
            failures.append(_fail("runtime_exact_conflict", "exact=0", row.get("exact_candidate_count")))
        if int(row.get("fallback_candidate_count") or 0) > 0:
            failures.append(
                _fail("runtime_fallback_conflict", "fallback=0", row.get("fallback_candidate_count"))
            )
        if int(row.get("scored_candidate_count") or 0) > 0:
            failures.append(
                _fail("runtime_scored_conflict", "scored=0", row.get("scored_candidate_count"))
            )
        if str(row.get("profile_source")) != "runtime_synthetic":
            failures.append(_fail("runtime_profile_source", "runtime_synthetic", row.get("profile_source")))
        if not row.get("ui_contains_runtime_disclosure"):
            failures.append(_fail("runtime_ui_disclosure", "runtime disclosure present", False))

    if base_bal <= 0 and not fs_buy:
        if rt == "deployable_grid":
            failures.append(_fail("first_start_bilateral_deploy", "not deployable_grid", rt))
        if rt not in ("recommended_grid", "management_decision", "no_trade", "single_probe_recommendation"):
            if "NO_SELLABLE_BASE" not in blocking:
                failures.append(_fail("no_sellable_base_reason", "NO_SELLABLE_BASE or safe rt", rt))

    if fs_buy:
        if buy_n < 2 and params_has_grids(row):
            failures.append(_fail("fs_buy_min_grids", "buy>=2 when fs_buy", buy_n))
        if rt == "deployable_grid" and sell_n >= 2 and base_bal <= 0:
            failures.append(_fail("fs_buy_sell_deploy", "sell inactive until base", sell_n))

    if row.get("spread_unsafe") or str(row.get("regime")) == "SPREAD_UNSAFE":
        if deployable:
            failures.append(_fail("spread_deployable", "deployable=false", deployable))
        if rt not in ("management_decision", "no_trade"):
            failures.append(_fail("spread_result_type", "management/no_trade", rt))

    if row.get("low_liquidity_block") and deployable:
        failures.append(_fail("liquidity_deployable", "deployable=false", deployable))

    if row.get("dump_risk_block") and deployable:
        failures.append(_fail("dump_deployable", "deployable=false", deployable))

    if row.get("invalid_distribution") and deployable:
        failures.append(_fail("invalid_dist_deployable", "deployable=false", deployable))

    exact_n = int(row.get("exact_candidate_count") or 0)
    if exact_n > 0 and row.get("runtime_profile_used"):
        failures.append(_fail("exact_runtime_mutex", "not both", f"exact={exact_n} runtime=true"))

    return failures


def params_has_grids(row: Dict[str, Any]) -> bool:
    return int(row.get("buy_grid_count") or 0) > 0 or bool(row.get("buy_distribution"))


def check_ui_contract(row: Dict[str, Any], response: Dict[str, Any]) -> List[Dict[str, str]]:
    """UI text / presentation contract (mirrors dashboard-create-modal.js)."""
    failures: List[Dict[str, str]] = []
    rt = str(row.get("result_type") or "")
    deployable = bool(row.get("deployable"))
    buy_n = int(row.get("buy_grid_count") or 0)

    if rt == "single_probe_recommendation" and buy_n != 1:
        failures.append(_fail("ui_single_probe_count", "buy_grid_count=1", buy_n))

    if rt == "recommended_grid" and deployable:
        failures.append(_fail("ui_recommended_not_deployable", "deployable=false", deployable))

    if rt == "deployable_grid" and not deployable:
        failures.append(_fail("ui_deployable_flag", "deployable=true", deployable))

    expected = UI_TEXT_CONTRACT.get(rt, {})
    if expected.get("ui_summary") and rt in ("single_probe_recommendation", "recommended_grid"):
        if row.get("ui_summary") != expected["ui_summary"]:
            failures.append(_fail("ui_summary_mismatch", expected["ui_summary"][:40], row.get("ui_summary")))

    if float(row.get("base_balance") or 0) <= 0 and not row.get("first_start_buy_only_enabled"):
        if "NO_SELLABLE_BASE" in [b.upper() for b in (row.get("block_reasons") or [])]:
            explain = str(response.get("explain") or "").lower()
            if "base" not in explain and "satış" not in explain:
                failures.append(_fail("ui_no_sellable_base_copy", "base/sell explanation", explain[:60]))

    return failures


def compute_acceptance_flags(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    flags = {
        "total": len(rows),
        "deployable_grid": 0,
        "recommended_grid": 0,
        "single_probe": 0,
        "management_decision": 0,
        "runtime": 0,
        "exact_coverage": 0,
        "one_grid_deployable_violation": 0,
        "two_grid_fifty_fifty_violation": 0,
        "three_grid_equalish_violation": 0,
        "worst_gt_max_deployable_violation": 0,
        "invalid_distribution_deployable_violation": 0,
        "exact_and_runtime_violation": 0,
        "runtime_disclosure_violation": 0,
        "recommended_shown_as_deployable_violation": 0,
        "no_sellable_base_copy_violation": 0,
        "first_start_policy_violation": 0,
        "failed_cases": 0,
    }
    codes = {
        "one_grid_deployable": "one_grid_deployable_violation",
        "one_grid_deployable_flag": "one_grid_deployable_violation",
        "two_grid_fifty_fifty": "two_grid_fifty_fifty_violation",
        "three_grid_equalish": "three_grid_equalish_violation",
        "three_grid_near_equal": "three_grid_equalish_violation",
        "exposure_cap_deployable": "worst_gt_max_deployable_violation",
        "invalid_dist_deployable": "invalid_distribution_deployable_violation",
        "exact_runtime_mutex": "exact_and_runtime_violation",
        "runtime_ui_disclosure": "runtime_disclosure_violation",
        "ui_recommended_not_deployable": "recommended_shown_as_deployable_violation",
        "ui_no_sellable_base_copy": "no_sellable_base_copy_violation",
        "first_start_bilateral_deploy": "first_start_policy_violation",
        "fs_buy_sell_deploy": "first_start_policy_violation",
        "no_sellable_base_reason": "first_start_policy_violation",
    }
    for row in rows:
        rt = str(row.get("result_type") or "")
        if rt == "deployable_grid":
            flags["deployable_grid"] += 1
        elif rt == "recommended_grid":
            flags["recommended_grid"] += 1
        elif rt == "single_probe_recommendation":
            flags["single_probe"] += 1
        elif rt == "management_decision":
            flags["management_decision"] += 1
        if row.get("runtime_profile_used"):
            flags["runtime"] += 1
        if int(row.get("exact_candidate_count") or 0) > 0:
            flags["exact_coverage"] += 1
        fails = row.get("invariant_failures") or []
        if fails:
            flags["failed_cases"] += 1
        for f in fails:
            code = f.get("code") or ""
            key = codes.get(code)
            if key:
                flags[key] += 1
        row["acceptance_flags"] = {k: flags.get(k, 0) for k in flags}
    return flags


def acceptance_passes(flags: Dict[str, int]) -> bool:
    must_zero = (
        "one_grid_deployable_violation",
        "two_grid_fifty_fifty_violation",
        "three_grid_equalish_violation",
        "worst_gt_max_deployable_violation",
        "invalid_distribution_deployable_violation",
        "exact_and_runtime_violation",
        "runtime_disclosure_violation",
        "recommended_shown_as_deployable_violation",
        "no_sellable_base_copy_violation",
        "first_start_policy_violation",
    )
    return all(int(flags.get(k) or 0) == 0 for k in must_zero)


class ParamAssistantHttpClient:
    """Black-box client — only HTTP to Param Assistant API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or "").rstrip("/")
        self._test_client = None

    def post_calculate(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if self.base_url:
            return self._post_remote(payload)
        return self._post_inprocess(payload)

    def _post_inprocess(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        from fastapi.testclient import TestClient

        from app.api import auth as auth_mod
        from app.main import app

        if self._test_client is None:
            app.dependency_overrides[auth_mod.require_auth] = lambda: {"account_id": "e2e:test"}
            self._test_client = TestClient(app)
        resp = self._test_client.post("/api/param-assistant/calculate", json=payload)
        body = resp.json() if resp.content else {}
        if isinstance(body, dict):
            body["_http_status"] = resp.status_code
        return resp.status_code, body

    def _post_remote(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        import urllib.error
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/param-assistant/calculate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw) if raw else {}
                if isinstance(body, dict):
                    body["_http_status"] = resp.status
                return int(resp.status), body
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"ok": False, "error": raw}
            if isinstance(body, dict):
                body["_http_status"] = exc.code
            return int(exc.code), body


def run_user_flow_case(
    client: ParamAssistantHttpClient,
    *,
    symbol: str,
    scenario: str,
    budget: float,
    first_start_buy_only: bool = False,
) -> Dict[str, Any]:
    spec = expand_scenario(scenario, budget)
    spec.first_start_buy_only = first_start_buy_only
    req = build_user_request(spec, symbol)
    status, body = client.post_calculate(req)
    if status != 200:
        return {
            "symbol": symbol,
            "budget": budget,
            "scenario": scenario,
            "ok": False,
            "http_status": status,
            "error": body.get("detail") or body,
            "invariant_failures": [_fail("http_error", "200", status)],
        }
    return extract_audit_row(
        body,
        symbol=symbol,
        budget=float(spec.budget or budget),
        scenario=scenario,
        request=req,
    )


def iter_audit_matrix(
    symbols: Sequence[str],
    budgets: Sequence[float],
    scenarios: Sequence[str],
    *,
    first_start_variants: Sequence[bool] = (False,),
) -> List[Tuple[str, float, str, bool]]:
    out: List[Tuple[str, float, str, bool]] = []
    for sym in symbols:
        for budget in budgets:
            for sc in scenarios:
                for fs in first_start_variants:
                    if sc in ("low_budget", "normal_budget"):
                        b = expand_scenario(sc, budget).budget or budget
                        out.append((sym, float(b), sc, fs))
                    else:
                        out.append((sym, float(budget), sc, fs))
    return out


def run_batch_audit(
    client: ParamAssistantHttpClient,
    matrix: Sequence[Tuple[str, float, str, bool]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for symbol, budget, scenario, fs_buy in matrix:
        rows.append(
            run_user_flow_case(
                client,
                symbol=symbol,
                scenario=scenario,
                budget=budget,
                first_start_buy_only=fs_buy,
            )
        )
    compute_acceptance_flags(rows)
    return rows


def render_markdown_report(rows: Sequence[Dict[str, Any]], flags: Dict[str, int]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Param Assistant E2E Audit",
        "",
        f"Generated: {ts}",
        "",
        "## Final acceptance",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
    ]
    for key in (
        "total",
        "deployable_grid",
        "recommended_grid",
        "single_probe",
        "management_decision",
        "runtime",
        "exact_coverage",
        "one_grid_deployable_violation",
        "two_grid_fifty_fifty_violation",
        "three_grid_equalish_violation",
        "worst_gt_max_deployable_violation",
        "invalid_distribution_deployable_violation",
        "exact_and_runtime_violation",
        "runtime_disclosure_violation",
        "recommended_shown_as_deployable_violation",
        "no_sellable_base_copy_violation",
        "first_start_policy_violation",
        "failed_cases",
    ):
        lines.append(f"| {key} | {flags.get(key, 0)} |")
    lines.append("")
    status = "PASS" if acceptance_passes(flags) else "FAIL"
    lines.append(f"**Overall:** {status}")
    lines.append("")
    failures = [r for r in rows if r.get("invariant_failures")]
    if failures:
        lines.append("## Violations (detail)")
        lines.append("")
        for row in failures[:80]:
            lines.append(
                f"### {row.get('symbol')} · {row.get('budget')} USDT · {row.get('scenario')} · "
                f"{row.get('route_key') or '—'}"
            )
            for f in row.get("invariant_failures") or []:
                lines.append(
                    f"- `{f.get('code')}` expected={f.get('expected')} got={f.get('got')}"
                )
            lines.append("")
    lines.append("## Sample rows")
    lines.append("")
    lines.append("| symbol | budget | scenario | result_type | deployable | buy | sell | route | fails |")
    lines.append("|--------|-------:|----------|-------------|------------|----:|-----:|-------|------:|")
    for row in rows[:40]:
        fails_n = len(row.get("invariant_failures") or [])
        lines.append(
            f"| {row.get('symbol')} | {row.get('budget')} | {row.get('scenario')} | "
            f"{row.get('result_type')} | {row.get('deployable')} | {row.get('buy_grid_count')} | "
            f"{row.get('sell_grid_count')} | {row.get('route_key') or '—'} | {fails_n} |"
        )
    return "\n".join(lines) + "\n"


def write_audit_reports(
    rows: Sequence[Dict[str, Any]],
    *,
    md_path: Path,
    json_path: Path,
) -> Dict[str, int]:
    flags = compute_acceptance_flags(rows)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown_report(rows, flags), encoding="utf-8")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "acceptance": flags,
        "pass": acceptance_passes(flags),
        "rows": list(rows),
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return flags
