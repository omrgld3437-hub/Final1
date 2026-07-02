"""50-coin × 3-budget Param Assistant user-flow E2E — normalize, anomalies, reports."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tools.param_pool.param_assistant_e2e_lib import (
    ParamAssistantHttpClient,
    _first_grid_distance,
    _grid_count_from_config,
    _is_fifty_fifty,
    _pct_distribution,
    build_user_request,
    expand_scenario,
)

# 50 USDT pairs with category labels (user spec + fallbacks)
SYMBOL_CATALOG: Tuple[Tuple[str, str], ...] = (
    ("BTCUSDT", "Majors"),
    ("ETHUSDT", "Majors"),
    ("SOLUSDT", "Majors"),
    ("BNBUSDT", "Majors"),
    ("XRPUSDT", "Majors"),
    ("ADAUSDT", "Major alt"),
    ("AVAXUSDT", "Major alt"),
    ("DOGEUSDT", "Meme"),
    ("LINKUSDT", "Major alt"),
    ("DOTUSDT", "Major alt"),
    ("LTCUSDT", "Majors"),
    ("TRXUSDT", "Major alt"),
    ("MATICUSDT", "Major alt"),
    ("ATOMUSDT", "Major alt"),
    ("NEARUSDT", "Major alt"),
    ("APTUSDT", "Major alt"),
    ("ARBUSDT", "Major alt"),
    ("OPUSDT", "Major alt"),
    ("INJUSDT", "Major alt"),
    ("SUIUSDT", "Major alt"),
    ("SEIUSDT", "Major alt"),
    ("AAVEUSDT", "High volume alt"),
    ("UNIUSDT", "High volume alt"),
    ("COMPUSDT", "High volume alt"),
    ("MKRUSDT", "High volume alt"),
    ("FETUSDT", "AI / narrative coin"),
    ("RNDRUSDT", "AI / narrative coin"),
    ("AIUSDT", "AI / narrative coin"),
    ("WLDUSDT", "AI / narrative coin"),
    ("FILUSDT", "Major alt"),
    ("ICPUSDT", "Major alt"),
    ("GALAUSDT", "Game/metaverse"),
    ("SANDUSDT", "Game/metaverse"),
    ("MANAUSDT", "Game/metaverse"),
    ("AXSUSDT", "Game/metaverse"),
    ("ENJUSDT", "Game/metaverse"),
    ("PEPEUSDT", "Meme"),
    ("FLOKIUSDT", "Meme"),
    ("SHIBUSDT", "Meme"),
    ("BONKUSDT", "Meme"),
    ("JTOUSDT", "Low liquidity / risky alt"),
    ("JUPUSDT", "Major alt"),
    ("TIAUSDT", "Major alt"),
    ("PYTHUSDT", "Major alt"),
    ("TONUSDT", "Major alt"),
    ("ASRUSDT", "Fan token / özel yapı"),
    ("SFPUSDT", "Low liquidity / risky alt"),
    ("RAREUSDT", "Low liquidity / risky alt"),
    ("PONDUSDT", "Low liquidity / risky alt"),
    ("AGLDUSDT", "Game/metaverse"),
)

DEFAULT_BUDGETS: Tuple[float, ...] = (50.0, 100.0, 1000.0)

# Same-category fallback when symbol unavailable on exchange
CATEGORY_FALLBACK: Dict[str, str] = {
    "MATICUSDT": "POLUSDT",
    "RNDRUSDT": "RENDERUSDT",
    "MKRUSDT": "AAVEUSDT",
    "COMPUSDT": "UNIUSDT",
    "AIUSDT": "FETUSDT",
    "ICPUSDT": "FILUSDT",
}

REGIME_ROUTE_HINTS: Dict[str, Tuple[str, ...]] = {
    "R5": ("kırılım öncesi", "sıkışma", "kırılım hazırlığı", "pre-breakout", "compression"),
    "R3": ("düşük vol", "low vol", "squeeze"),
    "R2": ("dengeli aralık", "balanced range"),
    "R8": ("crash", "çöküş"),
    "R15": ("stress", "geçiş"),
}


@dataclass
class Anomaly:
    level: str
    code: str
    message: str
    expected: str = ""

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "expected": self.expected,
        }


def auto50_symbols() -> List[str]:
    return [s for s, _ in SYMBOL_CATALOG]


def symbol_category(symbol: str) -> str:
    for sym, cat in SYMBOL_CATALOG:
        if sym == symbol.upper():
            return cat
    return "unknown"


def build_50coin_request(symbol: str, budget: float, *, mode: str = "test-local") -> Dict[str, Any]:
    spec = expand_scenario("first_start", budget)
    payload = build_user_request(spec, symbol)
    payload["mode"] = mode
    payload["dry_run"] = True
    return payload


def _route_regime_code(route_key: str) -> str:
    if not route_key or "|" not in route_key:
        return ""
    return route_key.split("|")[1].upper()


def _route_risk_code(route_key: str) -> str:
    if not route_key or "|" not in route_key:
        return ""
    parts = route_key.split("|")
    return parts[5].upper() if len(parts) > 5 else ""


def _indicators_from_telemetry(tel: dict) -> dict:
    ind = tel.get("indicators") or {}
    sub = tel.get("sub_scores") or {}
    return {**ind, **{f"sub_{k}": v for k, v in sub.items()}}


def normalize_run(
    *,
    test_id: str,
    symbol: str,
    budget: float,
    mode: str,
    request: dict,
    status: int,
    response: dict,
    category: str,
    symbol_substituted: Optional[str] = None,
) -> Dict[str, Any]:
    """Flatten API response into audit row (section 7 fields)."""
    ok = status == 200 and response.get("ok") is not False
    params = response.get("params") or {}
    tel = response.get("telemetry") or {}
    pool = tel.get("param_pool") or {}
    sel = response.get("selection_telemetry") or {}
    ctx = sel.get("selection_context") or pool.get("selection_context") or {}
    ui_cfg = response.get("ui_config") or response.get("recommendation_config") or {}
    ind = _indicators_from_telemetry(tel)
    sub = tel.get("sub_scores") or response.get("rationale", {}).get("sub_scores") or {}
    rebalance = tel.get("rebalance_plan") or {}
    score_labels = (ui_cfg.get("score_labels") or {}) if isinstance(ui_cfg, dict) else {}
    comps = tel.get("confidence_components") or score_labels

    buy_n = int(params.get("buy_grid_count") or 0) or _grid_count_from_config(ui_cfg, "down")
    sell_n = int(params.get("sell_grid_count") or 0) or _grid_count_from_config(ui_cfg, "up")
    buy_dist = _pct_distribution(params.get("buy_qty_distribution"))
    sell_dist = _pct_distribution(params.get("sell_qty_distribution"))

    route_key = str(sel.get("route_key") or ctx.get("route_key") or ctx.get("v5_route_key") or "")
    shelf_id = str(
        sel.get("selected_template_key")
        or ctx.get("v5_shelf_id")
        or response.get("selected_profile")
        or ""
    )
    worst_frac = tel.get("worst_case_base_exposure_frac")
    max_frac = tel.get("max_base_exposure_frac") or params.get("max_base_exposure_frac")
    worst_pct = round(float(worst_frac) * 100, 2) if worst_frac is not None else None
    max_pct = round(float(max_frac) * 100, 2) if max_frac is not None else None

    alloc = (ui_cfg.get("allocation_display") or {}) if isinstance(ui_cfg, dict) else {}
    active_buy = alloc.get("active_buy_ladder_usdt") or tel.get("buy_ladder_budget_usdt")

    fee_display = response.get("fee_display") or {}
    if not fee_display and isinstance(ui_cfg, dict):
        fee_display = ui_cfg.get("fee_display") or {}

    run = {
        "test_id": test_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "symbol_requested": symbol_substituted or symbol,
        "symbol_substituted": symbol_substituted is not None,
        "category": category,
        "budget_usdt": budget,
        "mode": mode,
        "dry_run": bool(request.get("dry_run", True)),
        "response_success": ok,
        "http_status": status,
        "error": response.get("error") or response.get("detail"),
        "market_regime_text": response.get("display_regime_label") or ui_cfg.get("display_regime_label"),
        "route_key": route_key,
        "shelf_id": shelf_id,
        "engine_version": ctx.get("engine_version") or tel.get("dps_engine_version"),
        "selection_type": ctx.get("selection_type"),
        "exact_hit": ctx.get("exact_route_hit"),
        "fallback_used": pool.get("fallback_used") or sel.get("fallback_used"),
        "runtime_used": bool(ctx.get("runtime_safe_profile_generated")),
        "profile_source": ctx.get("profile_source"),
        "parameter_score": response.get("param_score"),
        "confidence_score": response.get("confidence"),
        "market_confidence": response.get("market_confidence"),
        "execution_confidence": response.get("execution_confidence"),
        "final_start_confidence": response.get("final_start_confidence"),
        "risk_score": response.get("risk_score"),
        "market_suitability_score": _score_val(comps, "market_suitability_score"),
        "execution_safety_score": _score_val(comps, "execution_safety_score"),
        "parameter_validity_score": _score_val(comps, "parameter_validity_score"),
        "final_deploy_confidence": _score_val(comps, "final_deploy_confidence"),
        "ui_risk_label": (ui_cfg.get("display_risk_label") if isinstance(ui_cfg, dict) else None),
        "explanation_risk_label": response.get("effective_risk_state"),
        "route_risk": _route_risk_code(route_key),
        "btc_market_risk": sub.get("btc_market_risk_score"),
        "crash_velocity": ind.get("crash_velocity"),
        "btc_crash_velocity": ind.get("btc_crash_velocity"),
        "dump_risk": "DUMP_RISK" in [str(b).upper() for b in (response.get("blocking_reasons") or [])],
        "price_valid": ind.get("price_valid", True),
        "data_freshness_seconds": ind.get("data_freshness_sec"),
        "spread_pct": ind.get("orderbook_spread_pct"),
        "volume_24h": response.get("volume_24h") or ind.get("quote_volume_24h") or ind.get("volume_24h"),
        "volume_consistency": response.get("volume_consistency") or tel.get("volume_consistency") or ind.get("volume_consistency"),
        "rsi_5m": ind.get("rsi14_5m"),
        "rsi_1h": ind.get("rsi14_1h"),
        "adx_1h": ind.get("adx_1h"),
        "atr_5m": ind.get("atr14_pct_5m"),
        "atr_1h": ind.get("atr14_pct_1h"),
        "volatility_percentile": ind.get("volatility_percentile"),
        "return_24h": ind.get("return_24h_pct"),
        "target_base_pct": ui_cfg.get("base_alloc_pct") if isinstance(ui_cfg, dict) else None,
        "target_quote_pct": ui_cfg.get("quote_alloc_pct") if isinstance(ui_cfg, dict) else None,
        "max_exposure_pct": max_pct,
        "worst_exposure_pct": worst_pct,
        "active_buy_ladder_budget_usdt": active_buy,
        "buy_grid_count": buy_n,
        "sell_grid_count": sell_n,
        "buy_distribution": buy_dist,
        "sell_distribution": sell_dist,
        "first_buy_grid_pct": (
            response.get("first_buy_grid_pct")
            or params.get("buy_grid_spacing_pct")
            or _first_grid_distance(ui_cfg, "down")
        ),
        "first_sell_grid_pct": (
            response.get("first_sell_grid_pct")
            or params.get("sell_grid_spacing_pct")
            or _first_grid_distance(ui_cfg, "up")
        ),
        "result_type": response.get("result_type"),
        "final_action": response.get("final_action"),
        "deployable": bool(response.get("deployable")),
        "controlled_grid": bool(tel.get("controlled_grid")),
        "rebalance_decision": rebalance.get("action") or rebalance.get("decision"),
        "rebalance_reason": rebalance.get("blocked_reason") or rebalance.get("reason"),
        "rebalance_blocked": rebalance.get("blocked"),
        "block_reasons": list(response.get("blocking_reasons") or []),
        "warnings": list(response.get("warnings") or []),
        "top_summary_text": (response.get("explain") or "")[:500],
        "explanation_text": response.get("explain"),
        "safety_result_text": response.get("final_action_label"),
        "controlled_grid_note": response.get("controlled_grid_note"),
        "user_visible_decision": response.get("final_action_label"),
        "can_start_controlled": response.get("can_start_controlled"),
        "full_deployable": response.get("full_deployable"),
        "fee_data_status": (
            fee_display.get("status")
            if isinstance(fee_display.get("status"), str)
            else (
                "live_fee"
                if fee_display.get("fee_data_available") is True
                else "missing_fee"
                if fee_display.get("fee_data_available") is False
                else None
            )
        ),
        "fee_bad": tel.get("fee_bad_rebalance_deferred") or "fee_bad" in str(rebalance.get("blocked_reason") or "").lower(),
        "distribution_invalid": tel.get("distribution_invalid"),
        "exposure_hard_cap_breach": tel.get("exposure_hard_cap_breach"),
        "raw_response": response,
        "request": request,
    }
    run["anomalies"] = [a.to_dict() for a in scan_anomalies(run)]
    run["blocker_count"] = sum(1 for a in run["anomalies"] if a["level"] == "BLOCKER")
    run["warning_count"] = sum(1 for a in run["anomalies"] if a["level"] == "WARNING")
    run["critical_count"] = sum(1 for a in run["anomalies"] if a["level"] == "CRITICAL")
    return run


def _score_val(comps: Any, key: str) -> Optional[int]:
    if isinstance(comps, dict):
        v = comps.get(key)
        if isinstance(v, dict):
            return v.get("value")
        if v is not None:
            return int(v)
    return None


def _market_conditions_good(run: dict) -> bool:
    spread = float(run.get("spread_pct") or 99)
    if spread > 0.05:
        return False
    if run.get("dump_risk"):
        return False
    if run.get("price_valid") is False:
        return False
    fresh = run.get("data_freshness_seconds")
    if fresh is not None and float(fresh) > 300:
        return False
    crash = float(run.get("crash_velocity") or 0)
    if crash < -1.5:
        return False
    rsi5 = float(run.get("rsi_5m") or 50)
    rsi1 = float(run.get("rsi_1h") or 50)
    if rsi5 > 85 or rsi1 > 85 or rsi5 < 10 or rsi1 < 10:
        return False
    vol_pct = float(run.get("volatility_percentile") or 50)
    if vol_pct > 95:
        return False
    return True


def _distribution_context_from_run(run: dict) -> Any:
    from app.services.dynamic_param_score.distribution_policy import DistributionContext

    route = run.get("route_key") or ""
    return DistributionContext(
        risk_state=str(run.get("explanation_risk_label") or "NORMAL"),
        regime_code=_route_regime_code(route),
        liquidity_score=int(run.get("market_suitability_score") or 50),
        spread_score=70,
        btc_market_risk_score=int(run.get("btc_market_risk") or 50),
        rsi_5m=float(run.get("rsi_5m") or 50),
        rsi_1h=float(run.get("rsi_1h") or 50),
        fee_bad=bool(run.get("fee_bad")),
    )


def _min_notional_blocked(run: dict) -> bool:
    blocks = {str(b).upper() for b in (run.get("block_reasons") or [])}
    return "MIN_NOTIONAL_HARD_FAIL" in blocks or "BUDGET_TOO_SMALL" in blocks


def _can_expect_controlled_grid(run: dict) -> bool:
    rt = str(run.get("result_type") or "")
    if rt in (
        "min_notional_limited_grid",
        "first_start_buy_only",
        "single_probe_recommendation",
        "no_trade",
        "recommended_grid",
    ):
        return False
    if _min_notional_blocked(run):
        return False
    market = float(run.get("market_suitability_score") or 0)
    if market < 60:
        return False
    spread = float(run.get("spread_pct") or 99)
    if spread > 0.05:
        return False
    if run.get("dump_risk"):
        return False
    if run.get("price_valid") is False:
        return False
    buy_n = int(run.get("buy_grid_count") or 0)
    if buy_n < 2:
        return False
    return True


def scan_anomalies(run: dict) -> List[Anomaly]:
    """Section 8 anomaly rules."""
    out: List[Anomaly] = []
    conf = run.get("confidence_score")
    deployable = bool(run.get("deployable"))
    buy_n = int(run.get("buy_grid_count") or 0)
    buy_dist = list(run.get("buy_distribution") or [])
    sell_dist = list(run.get("sell_distribution") or [])
    rt = str(run.get("result_type") or "")
    fa = str(run.get("final_action") or "").upper()
    worst = run.get("worst_exposure_pct")
    max_exp = run.get("max_exposure_pct")
    market_good = _market_conditions_good(run)
    market_conf = run.get("market_confidence")
    if market_conf is None:
        market_conf = run.get("market_suitability_score")
    exec_conf = run.get("execution_confidence")
    if exec_conf is None:
        exec_conf = conf

    if market_good and market_conf is not None and float(market_conf) < 20:
        if exec_conf is not None and float(exec_conf) < 25:
            out.append(
                Anomaly(
                    "WARNING",
                    "CONFIDENCE_TOO_LOW_FOR_MARKET_CONDITIONS",
                    "Piyasa uygunluğu ile uygulanabilirlik güveni birlikte düşük.",
                    "market_confidence + execution_confidence",
                )
            )
        elif float(market_conf) < 20:
            out.append(
                Anomaly(
                    "CRITICAL",
                    "CONFIDENCE_TOO_LOW_FOR_MARKET_CONDITIONS",
                    "Piyasa verileri tamamen kötü görünmediği halde piyasa güven skoru aşırı düşük.",
                    "market_suitability ile uyumlu confidence",
                )
            )

    passive_rts = ("no_trade", "management_decision", "WAIT", "WAIT_SAFETY", "NO_TRADE")
    skip_passive = rt in (
        "min_notional_limited_grid",
        "first_start_buy_only",
        "single_probe_recommendation",
        "recommended_grid",
    )
    if market_good and not skip_passive and (rt in passive_rts or fa in passive_rts) and not run.get("controlled_grid"):
        if rt not in ("controlled_grid", "restricted_deployable_grid"):
            out.append(
                Anomaly(
                    "CRITICAL",
                    "OVER_PASSIVE_WAIT_DECISION",
                    "Sistem işlem açılabilecek şartlarda fazla pasif davranmış olabilir.",
                    "controlled_grid veya restricted_deployable_grid",
                )
            )

    if deployable and rt not in ("controlled_grid", "restricted_deployable_grid"):
        checks = [
            (run.get("spread_pct") is not None and float(run.get("spread_pct") or 99) <= 0.1, "spread"),
            (not run.get("dump_risk"), "dump"),
            (buy_n >= 2, "buy_grids"),
            (not run.get("distribution_invalid"), "distribution"),
        ]
        if not all(c[0] for c in checks):
            out.append(
                Anomaly(
                    "BLOCKER",
                    "UNSAFE_DEPLOYABLE_DECISION",
                    "Sistem güvenlik şartları tam sağlanmadan işlem açılabilir sonucu üretmiş.",
                    "deployable=false veya düzeltme",
                )
            )
        if worst is not None and max_exp is not None and float(worst) > float(max_exp) + 0.05:
            out.append(
                Anomaly(
                    "BLOCKER",
                    "EXPOSURE_HARD_CAP_BREACH_DEPLOYABLE",
                    "En kötü maruziyet, maksimum maruziyet sınırını aşmış.",
                    "deployable=false",
                )
            )

    if buy_n < 2 and deployable:
        out.append(
            Anomaly(
                "BLOCKER",
                "ONE_GRID_DEPLOYABLE_FORBIDDEN",
                "1 kademe gerçek grid değildir; otomatik işlem açılabilir olmamalı.",
                "single_probe veya deployable=false",
            )
        )

    if buy_n == 2 and buy_dist and _is_fifty_fifty(buy_dist):
        out.append(
            Anomaly(
                "BLOCKER",
                "BUY_2_GRID_50_50_FORBIDDEN",
                "2 kademeli alış dağılımı 50/50 çıkmış.",
                "40/60 veya 35/65",
            )
        )

    if buy_n == 2 and sell_dist and _is_fifty_fifty(sell_dist):
        out.append(
            Anomaly(
                "WARNING",
                "SELL_2_GRID_50_50",
                "2 kademeli satış dağılımı 50/50 — sell-side equal-2 ayrı değerlendirilmeli.",
                "justified veya back-weighted",
            )
        )

    if buy_n == 3 and buy_dist and len(buy_dist) == 3:
        from app.services.dynamic_param_score.distribution_policy import (
            is_insufficient_back_weight_for_high_momentum,
        )

        dist_ctx = _distribution_context_from_run(run)
        if is_insufficient_back_weight_for_high_momentum(buy_dist, ctx=dist_ctx):
            out.append(
                Anomaly(
                    "BLOCKER",
                    "INSUFFICIENT_BACK_WEIGHT_FOR_HIGH_BTC_RISK",
                    "Yüksek momentum/kırılım bağlamında 3 kademe yeterince arkaya ağırlıklı değil.",
                    "15/30/55 veya 12/28/60",
                )
            )
        elif max(buy_dist) - min(buy_dist) < 30 or buy_dist[-1] < 50 or buy_dist[0] > 18:
            if not dist_ctx.high_momentum_buy_context:
                out.append(
                    Anomaly(
                        "BLOCKER",
                        "THREE_GRID_EQUALISH_DISTRIBUTION",
                        "3 kademeli alış dağılımı risk profiline göre yeterince arkaya ağırlıklı değil.",
                        "back-weighted 15/30/55+",
                    )
                )

    if worst is not None and max_exp is not None and float(worst) > float(max_exp):
        if deployable:
            out.append(
                Anomaly(
                    "BLOCKER",
                    "EXPOSURE_HARD_CAP_BREACH_DEPLOYABLE",
                    "Worst exposure max üstünde ve deployable=true.",
                    "deployable=false",
                )
            )
        elif not run.get("exposure_hard_cap_breach") and "EXPOSURE" not in str(run.get("safety_result_text") or "").upper():
            out.append(
                Anomaly(
                    "WARNING",
                    "EXPOSURE_BREACH_NOT_CLEAR_IN_UI",
                    "Exposure aşımı var ama UI net göstermiyor.",
                    "güvenlik sonucu metninde exposure",
                )
            )

    if run.get("fee_bad") and run.get("rebalance_decision") not in (None, "defer", "deferred", "skip", "blocked"):
        if not run.get("rebalance_blocked"):
            out.append(
                Anomaly(
                    "CRITICAL",
                    "FEE_BAD_REBALANCE_FORBIDDEN",
                    "Fee_bad varken rebalance yapılmış veya yapılacak görünüyor.",
                    "rebalance ertelendi",
                )
            )

    if run.get("fee_bad") and market_good and rt in ("no_trade", "management_decision") and not run.get("controlled_grid"):
        out.append(
            Anomaly(
                "WARNING",
                "FEE_BAD_OVER_BLOCKED_GRID",
                "Fee verisi yok diye rebalance ertelenmesi doğru; ama grid tamamen gereksiz kapatılmış olabilir.",
                "controlled_grid",
            )
        )

    route = run.get("route_key") or ""
    regime_code = _route_regime_code(route)
    explain = str(run.get("explanation_text") or "").lower()
    regime_text = str(run.get("market_regime_text") or "").lower()
    if regime_code in REGIME_ROUTE_HINTS:
        hints = REGIME_ROUTE_HINTS[regime_code]
        forbidden = REGIME_ROUTE_HINTS.get("R2", ()) if regime_code == "R5" else ()
        if regime_code == "R5" and any(x in explain for x in ("dengeli aralık", "balanced range")):
            out.append(
                Anomaly(
                    "CRITICAL",
                    "REGIME_EXPLANATION_MISMATCH",
                    "Route R5 iken açıklama dengeli aralık diyor.",
                    "kırılım öncesi sıkışma / kırılım hazırlığı",
                )
            )
        if not any(h in explain or h in regime_text for h in hints) and regime_code in ("R5", "R3", "R8"):
            out.append(
                Anomaly(
                    "WARNING",
                    "REGIME_EXPLANATION_MISMATCH",
                    "Route ile kullanıcıya yazılan piyasa rejimi açıklaması tutarsız olabilir.",
                    f"hints: {hints}",
                )
            )

    ui_risk = str(run.get("ui_risk_label") or "").lower()
    route_risk = str(run.get("route_risk") or "")
    if route_risk.startswith("K1") and "normal" in ui_risk and "savun" not in ui_risk:
        out.append(
            Anomaly(
                "WARNING",
                "RISK_LABEL_MISMATCH",
                "UI risk label route K1 ile uyumsuz.",
                "Savunmacı / K1",
            )
        )
    if route_risk.startswith("K2") and "savun" in ui_risk:
        out.append(
            Anomaly(
                "WARNING",
                "RISK_LABEL_MISMATCH",
                "K2 route savunmacı UI gösteriyor.",
                "Normal kontrollü",
            )
        )

    if market_good and conf is not None and float(conf) < 35 and not run.get("controlled_grid"):
        if rt not in ("controlled_grid", "restricted_deployable_grid") and fa not in ("CONTROLLED_GRID",):
            if _can_expect_controlled_grid(run):
                out.append(
                    Anomaly(
                        "CRITICAL",
                        "MISSING_CONTROLLED_GRID_OPTION",
                        "Piyasa tamamen kötü değilken kontrollü grid seçeneği üretilmemiş.",
                        "controlled_grid",
                    )
                )
            elif _min_notional_blocked(run) and rt == "min_notional_limited_grid":
                out.append(
                    Anomaly(
                        "INFO",
                        "MIN_NOTIONAL_LIMITED_EXPECTED",
                        "Piyasa tamamen kötü değil; bütçe/min-notional nedeniyle kontrollü grid beklenmiyor.",
                        "min_notional_limited_grid",
                    )
                )

    budget = float(run.get("budget_usdt") or 0)
    active_buy = float(run.get("active_buy_ladder_budget_usdt") or 0)
    if budget >= 500 and active_buy > 0 and active_buy < budget * 0.02:
        if not run.get("controlled_grid_note") and "kontrollü" not in str(run.get("safety_result_text") or "").lower():
            out.append(
                Anomaly(
                    "WARNING",
                    "ACTIVE_BUY_BUDGET_UNEXPLAINED_LOW",
                    "Aktif alış bütçesi çok düşük tutulmuş ama kullanıcıya nedeni açıklanmamış.",
                    "düşük güven / exposure / fee_bad açıklaması",
                )
            )

    if not deployable and conf is not None and float(conf) < 40:
        if rt == "recommended_grid" and "referans" not in str(run.get("safety_result_text") or "").lower():
            out.append(
                Anomaly(
                    "WARNING",
                    "UI_MAKES_REFERENCE_LOOK_DEPLOYABLE",
                    "Kullanıcı işlem açılmaması gereken sonucu işlem yapılabilir gibi anlayabilir.",
                    "kontrollü / referans / bekle",
                )
            )

    if rt == "controlled_grid" and worst is not None and max_exp is not None and float(worst) > float(max_exp):
        out.append(
            Anomaly(
                "BLOCKER",
                "CONTROLLED_GRID_WITH_EXPOSURE_BREACH",
                "controlled_grid sonucunda worst exposure max üstünde.",
                "exposure trim veya recommended_grid",
            )
        )

    uvd = str(run.get("user_visible_decision") or run.get("safety_result_text") or "").lower()
    if rt == "controlled_grid" and ("bekle" in uvd or "referans" in uvd) and "kontrollü" not in uvd:
        out.append(
            Anomaly(
                "CRITICAL",
                "CONTROLLED_GRID_UI_SAYS_WAIT",
                "result_type controlled_grid ama kullanıcıya bekle/referans gösteriliyor.",
                "Kontrollü grid etiketi",
            )
        )

    if rt == "controlled_grid" and not deployable and run.get("can_start_controlled") is not False:
        if run.get("can_start_controlled") is None or run.get("can_start_controlled") is True:
            out.append(
                Anomaly(
                    "CRITICAL",
                    "CONTROLLED_GRID_DEPLOYABLE_FALSE_AMBIGUOUS",
                    "controlled_grid ama başlatılabilirlik belirsiz (deployable=false).",
                    "can_start_controlled=false veya recommended_grid",
                )
            )

    if buy_n >= 2 and not run.get("first_buy_grid_pct"):
        explain = str(run.get("explanation_text") or run.get("top_summary_text") or "").lower()
        if rt == "no_trade":
            if "grid aralığı" in explain:
                out.append(
                    Anomaly(
                        "WARNING",
                        "NO_TRADE_GRID_TEXT_MISMATCH",
                        "no_trade sonucunda grid aralığı metni var ama first_buy_grid_pct null.",
                        "metinden kaldır veya grid_reference_only doldur",
                    )
                )
        elif "grid aralığı" in explain:
            out.append(
                Anomaly(
                    "CRITICAL",
                    "GRID_TEXT_EXISTS_BUT_FIRST_GRID_NULL",
                    "Açıklamada grid aralığı var ama first_buy_grid_pct null.",
                    "params.buy_grid_spacing_pct",
                )
            )

    fds = run.get("fee_data_status")
    if isinstance(fds, bool):
        out.append(
            Anomaly(
                "WARNING",
                "FEE_STATUS_BOOLEAN_INVALID",
                "fee_data_status boolean; enum bekleniyor (live_fee / missing_fee).",
                "fee_display.status",
            )
        )

    if run.get("volume_24h") is None:
        out.append(
            Anomaly(
                "WARNING",
                "VOLUME_DATA_MISSING",
                "volume_24h null — atmosfer hacim bileşeni eksik.",
                "quote_volume_24h",
            )
        )

    return out


def run_single_analysis(
    client: ParamAssistantHttpClient,
    symbol: str,
    budget: float,
    *,
    mode: str = "test-local",
    category: str = "",
) -> Dict[str, Any]:
    test_id = str(uuid.uuid4())[:12]
    cat = category or symbol_category(symbol)
    req = build_50coin_request(symbol, budget, mode=mode)
    status, body = client.post_calculate(req)
    if status != 200:
        fb = CATEGORY_FALLBACK.get(symbol.upper())
        if fb:
            req2 = build_50coin_request(fb, budget, mode=mode)
            status2, body2 = client.post_calculate(req2)
            if status2 == 200:
                row = normalize_run(
                    test_id=test_id,
                    symbol=fb,
                    budget=budget,
                    mode=mode,
                    request=req2,
                    status=status2,
                    response=body2,
                    category=cat,
                    symbol_substituted=symbol,
                )
                row["symbol_unavailable"] = symbol
                row["symbol_fallback"] = fb
                return row
        return normalize_run(
            test_id=test_id,
            symbol=symbol,
            budget=budget,
            mode=mode,
            request=req,
            status=status,
            response=body if isinstance(body, dict) else {"error": body},
            category=cat,
        )
    return normalize_run(
        test_id=test_id,
        symbol=symbol,
        budget=budget,
        mode=mode,
        request=req,
        status=status,
        response=body,
        category=cat,
    )


def run_50coin_matrix(
    client: ParamAssistantHttpClient,
    symbols: Sequence[str],
    budgets: Sequence[float],
    *,
    mode: str = "test-local",
    progress: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    total = len(symbols) * len(budgets)
    n = 0
    for sym in symbols:
        cat = symbol_category(sym)
        for budget in budgets:
            n += 1
            if progress:
                progress(f"[{n}/{total}] {sym} @ {budget} USDT")
            runs.append(run_single_analysis(client, sym, float(budget), mode=mode, category=cat))
    return runs


def summarize_runs(runs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    s: Dict[str, Any] = {
        "total_runs": len(runs),
        "successful": sum(1 for r in runs if r.get("response_success")),
        "failed": sum(1 for r in runs if not r.get("response_success")),
        "deployable_grid": 0,
        "controlled_grid": 0,
        "restricted_deployable_grid": 0,
        "recommended_grid": 0,
        "no_trade": 0,
        "management_decision": 0,
        "single_probe": 0,
        "min_notional_limited_grid": 0,
        "first_start_buy_only": 0,
        "exact_v5_hit": 0,
        "fallback_used": 0,
        "runtime_used": 0,
        "blocker_count": 0,
        "warning_count": 0,
        "critical_count": 0,
        "symbol_substitutions": 0,
    }
    anomaly_counts: Dict[str, int] = {}
    for r in runs:
        rt = str(r.get("result_type") or "")
        if rt == "deployable_grid":
            s["deployable_grid"] += 1
        elif rt in ("controlled_grid",):
            s["controlled_grid"] += 1
        elif rt == "restricted_deployable_grid":
            s["restricted_deployable_grid"] += 1
        elif rt == "recommended_grid":
            s["recommended_grid"] += 1
        elif rt == "no_trade":
            s["no_trade"] += 1
        elif rt == "management_decision":
            s["management_decision"] += 1
        elif rt == "single_probe_recommendation":
            s["single_probe"] += 1
        elif rt == "min_notional_limited_grid":
            s["min_notional_limited_grid"] += 1
        elif rt == "first_start_buy_only":
            s["first_start_buy_only"] += 1
        if r.get("exact_hit"):
            s["exact_v5_hit"] += 1
        if r.get("fallback_used"):
            s["fallback_used"] += 1
        if r.get("runtime_used"):
            s["runtime_used"] += 1
        if r.get("symbol_substituted"):
            s["symbol_substitutions"] += 1
        s["blocker_count"] += int(r.get("blocker_count") or 0)
        s["warning_count"] += int(r.get("warning_count") or 0)
        s["critical_count"] += int(r.get("critical_count") or 0)
        for a in r.get("anomalies") or []:
            code = a.get("code") or "UNKNOWN"
            anomaly_counts[code] = anomaly_counts.get(code, 0) + 1
    s["anomaly_counts"] = anomaly_counts
    return s


def _worst_runs(runs: Sequence[dict], n: int = 20) -> List[dict]:
    def score(r: dict) -> Tuple[int, int]:
        blockers = int(r.get("blocker_count") or 0)
        crit = int(r.get("critical_count") or 0)
        return (blockers * 10 + crit, len(r.get("anomalies") or []))

    return sorted(runs, key=score, reverse=True)[:n]


def _best_runs(runs: Sequence[dict], n: int = 20) -> List[dict]:
    def score(r: dict) -> Tuple[int, float]:
        issues = len(r.get("anomalies") or [])
        conf = float(r.get("confidence_score") or 0)
        return (-issues, conf)

    good = [r for r in runs if r.get("response_success")]
    return sorted(good, key=score, reverse=True)[:n]


def render_conclusion(summary: dict) -> str:
    blockers = int(summary.get("blocker_count") or 0)
    critical = int(summary.get("critical_count") or 0)
    total = int(summary.get("total_runs") or 0)
    ac = summary.get("anomaly_counts") or {}
    vol_missing = int(ac.get("VOLUME_DATA_MISSING") or 0)
    if blockers == 0 and critical == 0 and vol_missing == 0 and not ac.get("BUY_2_GRID_50_50_FORBIDDEN"):
        return (
            f"Bu testte {total} kullanıcı akışı çalıştırıldı. Blocker ve kritik anomaly yok. "
            "V5 karar mantığı ve veri tamlığı hedefleri karşılandı."
        )
    if blockers == 0 and not ac.get("BUY_2_GRID_50_50_FORBIDDEN"):
        parts = [f"Blocker yok; ancak {critical} kritik anomaly"]
        if vol_missing:
            parts.append(f"{vol_missing} koşuda volume_24h eksik")
        if ac.get("OVER_PASSIVE_WAIT_DECISION"):
            parts.append("aşırı bekleme")
        if ac.get("MISSING_CONTROLLED_GRID_OPTION"):
            parts.append("controlled_grid eksikliği")
        return (
            f"Bu testte {total} kullanıcı akışı çalıştırıldı. "
            + "; ".join(parts)
            + ". Güvenlik kapısı geçti; karar kalitesi henüz final değil."
        )
    parts = []
    if ac.get("BUY_2_GRID_50_50_FORBIDDEN"):
        parts.append("2-grid buy 50/50")
    if ac.get("CONFIDENCE_TOO_LOW_FOR_MARKET_CONDITIONS"):
        parts.append("confidence/piyasa çelişkisi")
    if ac.get("EXPOSURE_HARD_CAP_BREACH_DEPLOYABLE"):
        parts.append("exposure hard-cap")
    if ac.get("OVER_PASSIVE_WAIT_DECISION") or ac.get("MISSING_CONTROLLED_GRID_OPTION"):
        parts.append("aşırı bekleme / controlled_grid eksikliği")
    detail = ", ".join(parts) or "çeşitli anomaly kodları"
    return (
        f"Bu testte {total} kullanıcı akışı çalıştırıldı. Sistem V5 exact raf bulma tarafında "
        f"çalışıyor; ancak karar mantığı tarafında şu sorunlar görüldü: {detail}. "
        "Bu hatalar düzeltilmeden Parametre Asistanı V5 final kabul edilmemelidir."
    )


def render_markdown_50coin(runs: Sequence[dict], summary: dict, *, mode: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Parametre Asistanı 50 Coin Kullanıcı Akışı Audit Raporu",
        "",
        f"**Tarih:** {ts}",
        f"**Test modu:** {mode}",
        f"**Toplam coin:** {len({r['symbol'] for r in runs})}",
        f"**Bütçe senaryoları:** 50 / 100 / 1000 USDT",
        f"**Toplam analiz:** {summary.get('total_runs')}",
        f"**Başarılı analiz:** {summary.get('successful')}",
        f"**Hatalı analiz:** {summary.get('failed')}",
        "",
        "## Genel özet",
        "",
        "| Metrik | Değer |",
        "|--------|------:|",
    ]
    for k in (
        "deployable_grid",
        "controlled_grid",
        "restricted_deployable_grid",
        "recommended_grid",
        "no_trade",
        "management_decision",
        "single_probe",
        "min_notional_limited_grid",
        "first_start_buy_only",
        "exact_v5_hit",
        "fallback_used",
        "runtime_used",
        "symbol_substitutions",
        "blocker_count",
        "critical_count",
        "warning_count",
    ):
        lines.append(f"| {k} | {summary.get(k, 0)} |")

    lines.extend(["", "## Kritik hata özeti", "", "| Hata | Sayı |", "|------|-----:|"])
    for code, cnt in sorted((summary.get("anomaly_counts") or {}).items(), key=lambda x: -x[1]):
        lines.append(f"| {code} | {cnt} |")

    lines.extend(["", "## En kötü 20 sonuç", "", "| Sıra | Coin | Bütçe | Final | Güven | Hata | En büyük hata |", "|-----:|------|------:|-------|------:|-----:|---------------|"])
    for i, r in enumerate(_worst_runs(runs), 1):
        top = (r.get("anomalies") or [{}])[0].get("code", "—")
        lines.append(
            f"| {i} | {r.get('symbol')} | {r.get('budget_usdt')} | {r.get('result_type')} | "
            f"{r.get('confidence_score')} | {len(r.get('anomalies') or [])} | {top} |"
        )

    lines.extend(["", "## En iyi 20 sonuç", "", "| Sıra | Coin | Bütçe | Final | Güven | Neden iyi |", "|-----:|------|------:|-------|------:|-----------|"])
    for i, r in enumerate(_best_runs(runs), 1):
        why = "anomaly yok" if not r.get("anomalies") else f"{len(r['anomalies'])} uyarı"
        lines.append(
            f"| {i} | {r.get('symbol')} | {r.get('budget_usdt')} | {r.get('result_type')} | "
            f"{r.get('confidence_score')} | {why} |"
        )

    for r in runs:
        lines.extend(_render_run_section(r))

    lines.extend(["", "## Sonuç", "", render_conclusion(summary), ""])
    return "\n".join(lines)


def _render_run_section(r: dict) -> List[str]:
    sym = r.get("symbol")
    budget = r.get("budget_usdt")
    sub_note = ""
    if r.get("symbol_substituted"):
        sub_note = f" (istenen: {r.get('symbol_unavailable')}, fallback kullanıldı)"
    lines = [
        "",
        f"## {sym} — {budget} USDT{sub_note}",
        "",
        "### Kullanıcı Akışı",
        "",
        "- Sayfa: Parametre Asistanı",
        f"- Girilen sembol: {r.get('symbol_requested', sym)}",
        f"- Kategori: {r.get('category')}",
        f"- Girilen bütçe: {budget} USDT",
        f"- Analiz durumu: {'Tamamlandı' if r.get('response_success') else 'HATA'}",
        "",
        "### Final Karar",
        "",
        f"- Result type: {r.get('result_type')}",
        f"- Deployable: {'evet' if r.get('deployable') else 'hayır'}",
        f"- Final action: {r.get('final_action')}",
        f"- Güven: {r.get('confidence_score')}/100",
        f"- Parametre skoru: {r.get('parameter_score')}/100",
        f"- Route: `{r.get('route_key') or '—'}`",
        f"- Shelf: `{r.get('shelf_id') or '—'}`",
        "",
        "### Piyasa Özeti",
        "",
        f"- Rejim metni: {r.get('market_regime_text')}",
        f"- Spread: {r.get('spread_pct')}%",
        f"- RSI 5m/1h: {r.get('rsi_5m')} / {r.get('rsi_1h')}",
        f"- BTC risk skoru: {r.get('btc_market_risk')}",
        f"- Vol persentil: {r.get('volatility_percentile')}",
        f"- Crash hızı: {r.get('crash_velocity')}",
        "",
        "### Grid Özeti",
        "",
        f"- Alış: {r.get('buy_grid_count')} kademe · dağılım {r.get('buy_distribution')}",
        f"- Satış: {r.get('sell_grid_count')} kademe · dağılım {r.get('sell_distribution')}",
        f"- Hedef: coin %{r.get('target_base_pct')} · USDT %{r.get('target_quote_pct')}",
        "",
        "### Güvenlik",
        "",
        f"- Max exposure: %{r.get('max_exposure_pct')}",
        f"- Worst exposure: %{r.get('worst_exposure_pct')}",
        f"- Aktif alış bütçesi: {r.get('active_buy_ladder_budget_usdt')} USDT",
        f"- Fee bad: {r.get('fee_bad')}",
        f"- Güvenlik sonucu: {r.get('safety_result_text')}",
        "",
        "### Tespit Edilen Mantık Hataları",
        "",
        "| Seviye | Kod | Açıklama | Beklenen |",
        "|--------|-----|----------|----------|",
    ]
    anomalies = r.get("anomalies") or []
    if not anomalies:
        lines.append("| — | — | anomaly yok | — |")
    else:
        for a in anomalies:
            lines.append(
                f"| {a.get('level')} | {a.get('code')} | {a.get('message')} | {a.get('expected')} |"
            )
    lines.extend(["", "### Ham cevap özeti", "", f"```\n{(r.get('top_summary_text') or '')[:800]}\n```"])
    return lines


def write_anomalies_md(runs: Sequence[dict], path: Path) -> None:
    lines = ["# Param Assistant 50 Coin — Anomaly Digest", ""]
    for r in runs:
        if not r.get("anomalies"):
            continue
        lines.append(f"## {r.get('symbol')} @ {r.get('budget_usdt')} USDT")
        for a in r.get("anomalies") or []:
            lines.append(f"- **{a.get('level')}** `{a.get('code')}`: {a.get('message')}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_jsonl_raw(runs: Sequence[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in runs:
            rec = {
                "test_id": r.get("test_id"),
                "symbol": r.get("symbol"),
                "budget": r.get("budget_usdt"),
                "timestamp": r.get("timestamp"),
                "request": r.get("request"),
                "raw_response": _slim_response(r.get("raw_response") or {}),
                "captured_ui_text": {
                    "safety_result_text": r.get("safety_result_text"),
                    "market_regime_text": r.get("market_regime_text"),
                    "controlled_grid_note": r.get("controlled_grid_note"),
                },
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _slim_response(resp: dict) -> dict:
    out = dict(resp)
    out.pop("telemetry", None)
    if "telemetry" in resp:
        out["telemetry_keys"] = list((resp.get("telemetry") or {}).keys())
    return out


def write_json_report(runs: Sequence[dict], summary: dict, path: Path, *, mode: str) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "dry_run": True,
        "total_symbols": len({r["symbol"] for r in runs}),
        "budgets": list(DEFAULT_BUDGETS),
        "total_runs": len(runs),
        "summary": summary,
        "conclusion": render_conclusion(summary),
        "runs": [
            {k: v for k, v in r.items() if k not in ("raw_response", "request")}
            for r in runs
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_consolidated_report(
    runs: Sequence[dict],
    summary: dict,
    path: Path,
    *,
    mode: str,
    anomalies_md: str = "",
) -> None:
    """Single MD file: summary + per-run detail + anomalies digest + acceptance."""
    body = render_markdown_50coin(runs, summary, mode=mode)
    ac = summary.get("anomaly_counts") or {}
    vol_null = sum(1 for r in runs if r.get("volume_24h") is None)
    grid_null = sum(1 for r in runs if int(r.get("buy_grid_count") or 0) >= 2 and not r.get("first_buy_grid_pct"))
    acceptance = "PASS" if final_acceptance_passes(summary) else "FAIL"
    extra = [
        "",
        "---",
        "",
        "## Run4 veri tamlığı",
        "",
        f"- volume_24h null: {vol_null} / {len(runs)}",
        f"- first_buy_grid_pct null (buy>=2): {grid_null}",
        f"- fee_data_status boolean: {int(ac.get('FEE_STATUS_BOOLEAN_INVALID') or 0)}",
        f"- controlled_grid + exposure breach: {int(ac.get('CONTROLLED_GRID_WITH_EXPOSURE_BREACH') or 0)}",
        f"- FINAL ACCEPTANCE: **{acceptance}**",
        "",
        "## Anomaly digest",
        "",
    ]
    if anomalies_md.strip():
        extra.append(anomalies_md.strip())
    else:
        for code, cnt in sorted(ac.items(), key=lambda x: -x[1]):
            extra.append(f"- {code}: {cnt}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "\n".join(extra) + "\n", encoding="utf-8")


def final_acceptance_passes(summary: dict) -> bool:
    ac = summary.get("anomaly_counts") or {}
    must_zero = (
        "ONE_GRID_DEPLOYABLE_FORBIDDEN",
        "BUY_2_GRID_50_50_FORBIDDEN",
        "THREE_GRID_EQUALISH_DISTRIBUTION",
        "INSUFFICIENT_BACK_WEIGHT_FOR_HIGH_BTC_RISK",
        "EXPOSURE_HARD_CAP_BREACH_DEPLOYABLE",
        "UNSAFE_DEPLOYABLE_DECISION",
        "UNSAFE_CONTROLLED_GRID_CONDITIONS",
        "FEE_BAD_REBALANCE_FORBIDDEN",
        "CONTROLLED_GRID_WITH_EXPOSURE_BREACH",
        "CONTROLLED_GRID_UI_SAYS_WAIT",
        "GRID_TEXT_EXISTS_BUT_FIRST_GRID_NULL",
    )
    if not all(int(ac.get(k) or 0) == 0 for k in must_zero):
        return False
    critical = int(summary.get("critical_count") or 0)
    vol_missing = int(ac.get("VOLUME_DATA_MISSING") or 0)
    total = int(summary.get("total_runs") or 1)
    if critical > max(5, total // 20):
        return False
    if vol_missing > total // 10:
        return False
    return True


def solusdt_regression_checks(runs: Sequence[dict]) -> List[Anomaly]:
    """Section 15 — SOLUSDT @ 1000 USDT special regression."""
    sol = next(
        (r for r in runs if r.get("symbol") == "SOLUSDT" and float(r.get("budget_usdt") or 0) == 1000.0),
        None,
    )
    if not sol:
        return [Anomaly("CRITICAL", "SOL_REGRESSION_MISSING", "SOLUSDT 1000 USDT senaryosu çalıştırılmadı.")]
    return [Anomaly(**a) for a in sol.get("anomalies") or []]
