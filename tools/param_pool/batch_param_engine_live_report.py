#!/usr/bin/env python3
"""Batch-run Dynamic Param Score Engine for USDT pairs and write markdown report."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASELINE_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "ETHUSDT",
    "MANAUSDT",
    "SANDUSDT",
    "TRXUSDT",
    "PONDUSDT",
    "ATOMUSDT",
    "DOGEUSDT",
    "NFPUSDT",
    "ALCXUSDT",
    "AGLDUSDT",
    "JTOUSDT",
    "SCRTUSDT",
    "HMSTRUSDT",
    "AAVEUSDT",
)

RANDOM_POOL_SEED = 20260626
RANDOM_EXCLUDE_STABLE = frozenset(
    {"USDCUSDT", "BUSDUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT"}
)

INDICATOR_KEYS = (
    "price_valid",
    "orderbook_spread_pct",
    "atr14_pct_5m",
    "atr14_pct_1h",
    "adx_1h",
    "rsi14_5m",
    "rsi14_1h",
    "volatility_percentile",
    "return_24h_pct",
    "return_1h_pct",
    "return_4h_pct",
    "drawdown_7d_pct",
    "drawdown_30d_pct",
    "bb_width_5m",
    "z_score_5m",
    "price_in_bb",
    "roc_5m",
    "quote_volume_24h",
    "btc_crash_velocity",
    "crash_velocity",
    "higher_highs",
    "lower_lows",
    "data_freshness_sec",
    "data_gap_sec",
)

SUB_SCORE_KEYS = (
    "trend_score",
    "volatility_score",
    "range_score",
    "liquidity_score",
    "spread_score",
    "momentum_score",
    "mean_reversion_score",
    "drawdown_risk_score",
    "btc_market_risk_score",
    "exposure_safety_score",
    "fee_efficiency_score",
    "data_quality_score",
    "order_reality_score",
)


def _fmt(v: Any, digits: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    if isinstance(v, float):
        if abs(v) >= 1000:
            if digits <= 0:
                return f"{v:,.0f}"
            return f"{v:,.{digits}f}".rstrip("0").rstrip(".")
        if digits <= 0:
            return str(int(round(v)))
        return f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return str(v)


def _fmt_budget_usdt(budget: float) -> str:
    """Human budget label for report headers (50 / 100 / 1,000 USDT)."""
    b = float(budget or 0)
    if b >= 1000:
        return f"{b:,.0f}"
    return str(int(round(b)))


def _pct_list(weights: Optional[List[float]]) -> str:
    if not weights:
        return "—"
    total = sum(weights) or 1.0
    parts = [round(w / total * 100, 1) for w in weights]
    return " / ".join(f"%{p}" for p in parts)


def _grid_ladder(params: Optional[Dict[str, Any]], side: str) -> str:
    if not params:
        return "—"
    ladder = params.get(f"{side}_grid_ladder_pcts") or []
    dist = params.get(f"{side}_qty_distribution") or []
    spacing = params.get(f"{side}_grid_spacing_pct")
    n = int(params.get(f"{side}_grid_count") or 0)
    if not ladder and n > 0 and spacing:
        ladder = [round(float(spacing) * (i + 1), 4) for i in range(n)]
    rows = []
    for i, pct in enumerate(ladder):
        qty = ""
        if dist and i < len(dist):
            if len(dist) == 1:
                qty = f" · miktar {_pct_list([dist[i]])}"
            else:
                qty = f" · miktar %{round(float(dist[i]) / (sum(dist) or 1) * 100, 1)}"
        sign = "+" if side == "sell" else "-"
        rows.append(f"#{i + 1}: {sign}{_fmt(pct, 2)}%{qty}")
    return "; ".join(rows) if rows else "—"


async def fetch_tradable_usdt_symbols() -> List[str]:
    from app.services.binance_rest_log import rest_source
    from app.services.binance_spot import public_get_json

    with rest_source("batch_param_engine_live_report"):
        info = await public_get_json("/api/v3/exchangeInfo", {}, testnet=False)
    out: List[str] = []
    for s in (info or {}).get("symbols") or []:
        if not isinstance(s, dict):
            continue
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        if not s.get("isSpotTradingAllowed", True):
            continue
        sym = str(s.get("symbol") or "").upper()
        if sym and sym not in RANDOM_EXCLUDE_STABLE:
            out.append(sym)
    return sorted(set(out))


def pick_random_symbols(
    n: int,
    pool: Sequence[str],
    *,
    exclude: Set[str],
    seed: int,
) -> List[str]:
    candidates = [s for s in pool if s not in exclude]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return sorted(candidates[:n])


async def _enrich_market_from_binance(market: Any, symbol: str) -> Any:
    if market.ticker_price and market.ticker_price > 0 and (market.quote_volume_24h or 0) > 0:
        return market
    try:
        from app.services.binance_rest_log import rest_source
        from app.services.binance_spot import public_get_json

        with rest_source("batch_param_engine_live_report"):
            ticker = await public_get_json(
                "/api/v3/ticker/24hr",
                {"symbol": symbol.upper()},
                testnet=False,
            )
        if isinstance(ticker, dict):
            price = float(ticker.get("lastPrice") or ticker.get("weightedAvgPrice") or 0)
            qvol = float(ticker.get("quoteVolume") or 0)
            if price > 0:
                market.ticker_price = price
            if qvol > 0:
                market.quote_volume_24h = qvol
                market.volume_24h = float(ticker.get("volume") or 0)
    except Exception:
        pass
    if (not market.ticker_price or market.ticker_price <= 0) and market.candles_5m:
        market.ticker_price = float(market.candles_5m[-1].c)
    return market


async def run_symbol(symbol: str, budget: float) -> Dict[str, Any]:
    from app.services.dynamic_param_score import get_engine
    from app.services.dynamic_param_score.adapters import decision_to_param_assistant_result
    from app.services.dynamic_param_score.data_collector import (
        collect_market_data,
        default_exchange_constraints,
        portfolio_from_budget,
    )
    from app.services.dynamic_param_score.models import BotContext

    sym = symbol.upper().strip()
    if not sym.endswith("USDT"):
        sym += "USDT"
    market = await collect_market_data(sym)
    market = await _enrich_market_from_binance(market, sym)
    portfolio = portfolio_from_budget(budget, market.ticker_price)
    constraints = default_exchange_constraints(sym)
    ctx = BotContext(
        run_source="param_assistant_batch",
        budget_usdt=budget,
        is_first_start=True,
        allow_live=True,
        allow_no_trade=True,
    )

    def _calc():
        return get_engine().calculate_decision(
            symbol=sym,
            market_data=market,
            portfolio_state=portfolio,
            exchange_constraints=constraints,
            bot_context=ctx,
        )

    loop = asyncio.get_running_loop()
    decision = await loop.run_in_executor(None, _calc)
    result = decision_to_param_assistant_result(decision, budget, sym)
    return {
        "symbol": sym,
        "budget": budget,
        "price": market.ticker_price,
        "result": result,
    }


def _selection_row(result: Dict[str, Any]) -> Dict[str, Any]:
    tel = result.get("selection_telemetry") or {}
    ctx = tel.get("selection_context") or {}
    return {
        "route_key": tel.get("route_key") or ctx.get("route_key"),
        "fallback_route": tel.get("fallback_route") or ctx.get("fallback_route"),
        "exact": tel.get("exact_route_candidate_count") or ctx.get("exact_route_candidate_count"),
        "fallback": tel.get("fallback_candidate_count") or ctx.get("fallback_candidate_count"),
        "scored": tel.get("scored_candidate_count") or ctx.get("scored_candidate_count"),
        "profile_score": tel.get("selected_profile_score") or ctx.get("selected_profile_score"),
        "runtime_safe": tel.get("runtime_safe_profile_generated") or ctx.get("runtime_safe_profile_generated"),
        "pool_version": tel.get("pool_version"),
        "template": tel.get("selected_template_key"),
        "selection_reason": tel.get("selection_reason") or ctx.get("reason"),
        "coverage_gap": tel.get("coverage_gap") or ctx.get("coverage_gap"),
    }


def _aggregate_metrics(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cross-run metrics for executive summary."""
    runtime = 0
    deployable_flag = 0
    exact_gt0 = 0
    no_trade = 0
    result_types: Dict[str, int] = defaultdict(int)
    worst_breach_deploy = 0
    two_grid_5050 = 0
    blocking: Dict[str, int] = defaultdict(int)

    for p in payloads:
        r = p["result"]
        sel = _selection_row(r)
        rt = str(r.get("result_type") or "unknown")
        result_types[rt] += 1
        if r.get("deployable"):
            deployable_flag += 1
        if sel.get("runtime_safe") in (True, "evet"):
            runtime += 1
        if int(sel.get("exact") or 0) > 0:
            exact_gt0 += 1
        if r.get("final_action") == "NO_TRADE":
            no_trade += 1
        for b in r.get("blocking_reasons") or []:
            blocking[str(b)] += 1

        tel = r.get("telemetry") or {}
        params = r.get("params") or {}
        worst = tel.get("worst_case_base_exposure_frac")
        max_exp = params.get("max_base_exposure_frac")
        if worst is not None and max_exp is not None:
            if float(worst) > float(max_exp) + 0.005 and r.get("deployable"):
                worst_breach_deploy += 1

        buy_n = int(params.get("buy_grid_count") or 0)
        dist = params.get("buy_qty_distribution") or []
        if buy_n == 2 and len(dist) >= 2:
            from app.services.dynamic_param_score.param_generator.grid_distribution import (
                is_defensive_distribution_valid,
            )

            risk = str(
                (r.get("telemetry") or {}).get("requested_risk_class")
                or (r.get("params") or {}).get("risk_class")
                or ""
            ).upper()
            defensive = risk in ("DEFENSIVE", "CAUTION") or r.get("final_action") in (
                "ACTIVE_DEFENSIVE_GRID",
                "DEFENSIVE_GRID",
            )
            if defensive and not is_defensive_distribution_valid(dist, grid_count=2):
                two_grid_5050 += 1
            elif not defensive:
                pcts = [round(float(w) / (sum(dist) or 1) * 100, 1) for w in dist[:2]]
                if abs(pcts[0] - 50) < 3 and abs(pcts[1] - 50) < 3:
                    two_grid_5050 += 1

    return {
        "total": len(payloads),
        "deployable_flag": deployable_flag,
        "result_types": dict(result_types),
        "runtime": runtime,
        "exact_gt0": exact_gt0,
        "no_trade": no_trade,
        "worst_breach_deploy": worst_breach_deploy,
        "two_grid_5050": two_grid_5050,
        "blocking_top": sorted(blocking.items(), key=lambda x: -x[1])[:8],
    }


def render_executive_summary(
    all_payloads: List[Dict[str, Any]],
    baseline_50: List[Dict[str, Any]],
    random_payloads: List[Dict[str, Any]],
    random_budgets: List[float],
) -> str:
    from app.services.dynamic_param_score.param_pool.versioning import production_pool_status

    agg = _aggregate_metrics(all_payloads)
    pool = production_pool_status()
    rt = agg["result_types"]
    deploy_grid = rt.get("deployable_grid", 0)
    recommended = rt.get("recommended_grid", 0)
    management = rt.get("management_decision", 0)

    lines = [
        "## Genel özet",
        "",
        f"- **Toplam koşu:** {agg['total']}",
        f"- **Production pool yüklü:** {_fmt(pool.get('production_pool_loaded'))} · "
        f"route index profil: **{pool.get('route_index_profile_count', 0):,}** · "
        f"mandatory raflar OK: {_fmt(pool.get('mandatory_shelves_ok'))}",
        f"- **result_type `deployable_grid`:** {deploy_grid}/{agg['total']}",
        f"- **result_type `recommended_grid`:** {recommended}/{agg['total']}",
        f"- **result_type `management_decision`:** {management}/{agg['total']}",
        f"- **deployable bayrağı (true):** {agg['deployable_flag']}/{agg['total']}",
        f"- **Exact route aday > 0:** {agg['exact_gt0']}/{agg['total']}",
        f"- **Runtime safe:** {agg['runtime']}/{agg['total']}",
        f"- **NO_TRADE final_action:** {agg['no_trade']}/{agg['total']}",
        f"- **Worst-case > max + deployable:** {agg['worst_breach_deploy']} (hedef: 0)",
        f"- **2-grid alış ~%50/%50:** {agg['two_grid_5050']} (hedef: 0)",
        "",
    ]
    if agg["blocking_top"]:
        lines.append("**Ana bloklayıcılar:** " + ", ".join(f"{k} ({v})" for k, v in agg["blocking_top"]))
        lines.append("")

    st_b = _stats(baseline_50)
    lines += [
        "### Bütçe kırılımı (rastgele 30)",
        "",
        "| Bütçe | Deployable | Runtime | NO_TRADE | exact=0 |",
        "|-------|------------|---------|----------|---------|",
    ]
    grouped: Dict[float, List[Dict[str, Any]]] = defaultdict(list)
    for p in random_payloads:
        grouped[float(p["budget"])].append(p)
    for budget in sorted(random_budgets):
        st = _stats(grouped[float(budget)])
        lines.append(
            f"| {int(budget)} USDT | {st['deploy']}/{st['total']} | {st['runtime']}/{st['total']} | "
            f"{st['no_trade']}/{st['total']} | {st['exact_zero']}/{st['total']} |"
        )
    lines += [
        "",
        f"### Sabit 18 @ 50 USDT: deployable **{st_b['deploy']}/18** · runtime **{st_b['runtime']}/18** · exact>0 **{18 - st_b['exact_zero']}/18**",
        "",
    ]
    return "\n".join(lines)


def render_runtime_route_gap_summary(payloads: List[Dict[str, Any]]) -> str:
    """Group live routes by gap pattern for runtime / coverage diagnosis."""
    from collections import defaultdict as dd

    groups: Dict[str, Dict[str, Any]] = dd(
        lambda: {
            "count": 0,
            "exact": 0,
            "fallback": 0,
            "scored": 0,
            "runtime": 0,
            "blockers": dd(int),
            "gap_reasons": dd(int),
        }
    )
    for p in payloads:
        r = p["result"]
        sel = _selection_row(r)
        rk = str(sel.get("route_key") or "—")
        g = groups[rk]
        g["count"] += 1
        g["exact"] += int(sel.get("exact") or 0)
        g["fallback"] += int(sel.get("fallback") or 0)
        g["scored"] += int(sel.get("scored") or 0)
        if sel.get("runtime_safe") in (True, "evet"):
            g["runtime"] += 1
        for b in r.get("blocking_reasons") or []:
            g["blockers"][str(b)] += 1
        ctx = (r.get("selection_telemetry") or {}).get("selection_context") or {}
        gap = ctx.get("route_gap_reason") or ctx.get("exact_reject_summary")
        if isinstance(gap, dict) and gap:
            top = max(gap.items(), key=lambda x: x[1])[0]
            g["gap_reasons"][top] += 1
        elif gap:
            g["gap_reasons"][str(gap)] += 1

    priority = {
        "A3|R2|S1|V4|DEFENSIVE",
        "A2|R2|S1|V4|DEFENSIVE",
        "A3|R2|S1|V3|DEFENSIVE",
        "A3|R3|S3|V3|DEFENSIVE",
        "A3|R5|S2|V4|DEFENSIVE",
        "A3|R15|S3|V5|DEFENSIVE",
        "A3|R4|S1|V5|DEFENSIVE",
        "A5|R2|S3|V4|DEFENSIVE",
    }

    def sort_key(item: tuple) -> tuple:
        rk, g = item
        return (-g["runtime"], -g["count"], rk not in priority, rk)

    lines = [
        "## Runtime route gap özeti",
        "",
        "| route_key | count | exactΣ | fallbackΣ | scoredΣ | runtime | top_blockers | gap_reason |",
        "|-----------|------:|-------:|----------:|--------:|--------:|--------------|------------|",
    ]
    for rk, g in sorted(groups.items(), key=sort_key)[:40]:
        blockers = sorted(g["blockers"].items(), key=lambda x: -x[1])[:2]
        blk = ", ".join(f"{k}({v})" for k, v in blockers) or "—"
        gaps = sorted(g["gap_reasons"].items(), key=lambda x: -x[1])[:1]
        gap = gaps[0][0] if gaps else ("runtime_used" if g["runtime"] else "—")
        lines.append(
            f"| `{rk}` | {g['count']} | {g['exact']} | {g['fallback']} | {g['scored']} | "
            f"{g['runtime']} | {blk[:40]} | {gap[:28]} |"
        )
    lines.append("")
    return "\n".join(lines)


def _stats(payloads: List[Dict[str, Any]]) -> Dict[str, int]:
    runtime = 0
    deploy = 0
    no_trade = 0
    exact_zero = 0
    scored_zero_fb = 0
    for p in payloads:
        r = p["result"]
        sel = _selection_row(r)
        if r.get("deployable"):
            deploy += 1
        if sel.get("runtime_safe") in (True, "evet"):
            runtime += 1
        if r.get("final_action") == "NO_TRADE":
            no_trade += 1
        if int(sel.get("exact") or 0) == 0:
            exact_zero += 1
        if int(sel.get("fallback") or 0) > 0 and int(sel.get("scored") or 0) == 0:
            scored_zero_fb += 1
    return {
        "total": len(payloads),
        "deploy": deploy,
        "runtime": runtime,
        "no_trade": no_trade,
        "exact_zero": exact_zero,
        "scored_zero_fb": scored_zero_fb,
    }


def render_summary_table(rows: List[Dict[str, Any]], *, show_budget: bool = False) -> str:
    budget_col = " | Bütçe" if show_budget else ""
    hdr = (
        "| # | Coin"
        + budget_col
        + " | Skor | Karar | Rejim | Route | Exact | FB | Scored | Runtime | Alış dist | Max exp |"
    )
    sep = "|---|------" + ("|---" if show_budget else "") + "|------|-------|-------|-------|-------|----|--------|---------|-----------|---------|"
    body: List[str] = [hdr, sep]
    for i, p in enumerate(rows, 1):
        r = p["result"]
        sel = _selection_row(r)
        params = r.get("params") or {}
        buy_dist = _pct_list(params.get("buy_qty_distribution"))
        max_exp = (
            f"%{_fmt(round(float(params.get('max_base_exposure_frac', 0)) * 100, 0))}"
            if params
            else "—"
        )
        bud = f" | {_fmt(p.get('budget'), 0)}" if show_budget else ""
        body.append(
            f"| {i} | {p['symbol'].replace('USDT', '')}{bud} | "
            f"{_fmt(r.get('param_score'), 0)} | `{r.get('final_action')}` | "
            f"{(r.get('display_regime_label') or r.get('regime_tag') or '—')[:28]} | "
            f"`{(sel.get('route_key') or '—')[:24]}` | "
            f"{_fmt(sel.get('exact'))} | {_fmt(sel.get('fallback'))} | {_fmt(sel.get('scored'))} | "
            f"{_fmt(sel.get('runtime_safe'))} | {buy_dist[:22]} | {max_exp} |"
        )
    return "\n".join(body)


def render_budget_compare_table(
    symbols: List[str],
    by_key: Dict[Tuple[str, float], Dict[str, Any]],
    budgets: List[float],
) -> str:
    hdr = "| Coin | " + " | ".join(f"{int(b)} USDT skor/karar" for b in budgets) + " |"
    sep = "|------|" + "|".join(["---"] * len(budgets)) + "|"
    lines = [hdr, sep]
    for sym in symbols:
        cells = []
        for b in budgets:
            p = by_key.get((sym, b))
            if not p:
                cells.append("—")
                continue
            r = p["result"]
            cells.append(f"{_fmt(r.get('param_score'), 0)} / `{r.get('final_action')}`")
        lines.append(f"| {sym.replace('USDT', '')} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_coin_section(payload: Dict[str, Any]) -> str:
    r = payload["result"]
    tel = r.get("telemetry") or {}
    ind = tel.get("indicators") or {}
    sub = tel.get("sub_scores") or (r.get("rationale") or {}).get("sub_scores") or {}
    sig = tel.get("market_signature") or {}
    params = r.get("params") or {}
    ui = r.get("ui_config") or {}
    sel = _selection_row(r)
    lines: List[str] = []

    lines.append(f"### {payload['symbol']} · {_fmt_budget_usdt(float(payload.get('budget') or 0))} USDT")
    lines.append("")
    lines.append(f"- **Fiyat:** {_fmt(payload.get('price'), 6)} USDT")
    lines.append(f"- **Karar:** `{r.get('final_action')}` · deployable: **{_fmt(r.get('deployable'))}**")
    lines.append(
        f"- **Parametre skoru:** {_fmt(r.get('param_score'), 0)}/100 · "
        f"Güven: {_fmt(r.get('confidence'), 0)}/100 · Risk: `{r.get('effective_risk_state') or r.get('risk_state')}`"
    )
    lines.append(f"- **Rejim:** `{r.get('regime_tag')}` · UI: {r.get('display_regime_label') or '—'}")
    lines.append(
        f"- **Route:** `{sel.get('route_key') or '—'}`"
        + (f" · fallback `{sel.get('fallback_route')}`" if sel.get("fallback_route") else "")
    )
    lines.append(
        f"- **Seçim:** exact={_fmt(sel.get('exact'))} · fallback={_fmt(sel.get('fallback'))} · "
        f"scored={_fmt(sel.get('scored'))} · profil={_fmt(sel.get('profile_score'), 1)} · "
        f"runtime={_fmt(sel.get('runtime_safe'))}"
    )
    lines.append(f"- **Profil:** `{r.get('selected_profile') or sel.get('template') or '—'}`")
    if r.get("explain"):
        lines.append(f"- **Özet:** {r.get('explain')}")
    if r.get("blocking_reasons"):
        lines.append(f"- **Bloklar:** {', '.join(r['blocking_reasons'])}")
    if r.get("warnings"):
        lines.append(f"- **Uyarılar:** {', '.join(r['warnings'][:8])}")

    lines.append("")
    lines.append("#### Göstergeler")
    lines.append("")
    lines.append("| Gösterge | Değer |")
    lines.append("|----------|-------|")
    for k in INDICATOR_KEYS:
        if k in ind:
            lines.append(f"| {k} | {_fmt(ind[k])} |")
    for k in ("regime_code", "structure_code", "vol_code", "risk_class", "asset_code", "grid_bias"):
        if sig.get(k) is not None:
            lines.append(f"| route.{k} | {_fmt(sig.get(k))} |")

    lines.append("")
    lines.append("#### Alt skorlar")
    lines.append("")
    lines.append("| Skor | Değer |")
    lines.append("|------|-------|")
    for k in SUB_SCORE_KEYS:
        if k in sub:
            lines.append(f"| {k} | {_fmt(sub[k], 0)}/100 |")

    if params:
        lines.append("")
        lines.append("#### Parametreler")
        lines.append("")
        lines.append(
            f"- **Dağılım:** base %{_fmt(round(float(params.get('base_alloc_frac', 0)) * 100, 1))} · "
            f"quote %{_fmt(round(float(params.get('quote_alloc_frac', 0)) * 100, 1))}"
        )
        lines.append(f"- **Max exposure:** %{_fmt(round(float(params.get('max_base_exposure_frac', 0)) * 100, 1))}")
        wc = tel.get("worst_case_base_exposure_frac")
        if wc is not None:
            lines.append(f"- **Worst-case exposure:** %{_fmt(round(float(wc) * 100, 1))}")
        lines.append(f"- **Satış ({_fmt(params.get('sell_grid_count'), 0)}):** {_grid_ladder(params, 'sell')}")
        lines.append(f"- **Alış ({_fmt(params.get('buy_grid_count'), 0)}):** {_grid_ladder(params, 'buy')}")
        lines.append(
            f"- **Spacing:** satış %{_fmt(params.get('sell_grid_spacing_pct'), 2)} · "
            f"alış %{_fmt(params.get('buy_grid_spacing_pct'), 2)} · "
            f"alış dist {_pct_list(params.get('buy_qty_distribution'))} · "
            f"satış dist {_pct_list(params.get('sell_qty_distribution'))}"
        )
    if ui:
        alloc = ui.get("allocation_display") or {}
        st = (alloc.get("strategic_target") or {})
        if st:
            lines.append(
                f"- **UI:** coin %{_fmt(st.get('base_pct'))} · USDT %{_fmt(st.get('quote_pct'))} · "
                f"aktif alış ${_fmt(alloc.get('active_buy_ladder_usdt'), 2)}"
            )
    lines.append("")
    return "\n".join(lines)


def build_full_report(
    baseline_50: List[Dict[str, Any]],
    random_payloads: List[Dict[str, Any]],
    random_symbols: List[str],
    random_budgets: List[float],
    errors: List[str],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_key = {(p["symbol"], float(p["budget"])): p for p in random_payloads}
    grouped: Dict[float, List[Dict[str, Any]]] = defaultdict(list)
    for p in random_payloads:
        grouped[float(p["budget"])].append(p)

    lines = [
        "# Parametre Motoru — Canlı USDT Batch Raporu",
        "",
        f"**Üretim:** {now}  ",
        "**Motor:** Dynamic Param Score Engine (V4)  ",
        f"**Kaynak:** `tools/param_pool/batch_param_engine_live_report.py`",
        "",
        "## Kapsam",
        "",
        f"- **Sabit set (18 coin):** {len(BASELINE_SYMBOLS)} parite · **50 USDT**",
        f"- **Rastgele set:** {len(random_symbols)} parite · **50 / 100 / 1000 USDT**",
        f"- **Toplam koşu:** {len(baseline_50) + len(random_payloads)}",
        f"- **Rastgele seed:** `{RANDOM_POOL_SEED}` (tekrarlanabilir seçim)",
        "",
        "### Rastgele 30 parite listesi",
        "",
        ", ".join(f"`{s.replace('USDT', '')}`" for s in random_symbols),
        "",
        render_executive_summary(
            baseline_50 + random_payloads,
            baseline_50,
            random_payloads,
            random_budgets,
        ),
        "",
        render_runtime_route_gap_summary(baseline_50 + random_payloads),
    ]

    # Baseline section
    st_b = _stats(baseline_50)
    lines += [
        "---",
        "",
        "## Bölüm A — Sabit 18 coin @ 50 USDT",
        "",
        f"- Deployable: **{st_b['deploy']}/{st_b['total']}**",
        f"- Runtime safe: **{st_b['runtime']}/{st_b['total']}**",
        f"- NO_TRADE: **{st_b['no_trade']}**",
        f"- Exact route aday 0: **{st_b['exact_zero']}**",
        f"- Fallback>0 ama scored=0: **{st_b['scored_zero_fb']}**",
        "",
        render_summary_table(baseline_50),
        "",
        "### Detaylar (sabit set)",
        "",
    ]
    for p in baseline_50:
        lines.append(render_coin_section(p))

    # Random sections per budget
    lines += ["---", "", "## Bölüm B — Rastgele 30 coin (çoklu bütçe)", ""]
    lines += [
        "### Bütçe karşılaştırma özeti",
        "",
        render_budget_compare_table(random_symbols, by_key, random_budgets),
        "",
    ]

    for budget in sorted(random_budgets):
        rows = sorted(grouped.get(float(budget), []), key=lambda x: x["symbol"])
        st = _stats(rows)
        lines += [
            f"### Rastgele set @ {_fmt_budget_usdt(float(budget))} USDT",
            "",
            f"- Deployable: **{st['deploy']}/{st['total']}** · Runtime: **{st['runtime']}** · "
            f"NO_TRADE: **{st['no_trade']}** · exact=0: **{st['exact_zero']}**",
            "",
            render_summary_table(rows),
            "",
        ]

    lines += ["### Detaylar (rastgele set — tüm bütçeler)", ""]
    for p in sorted(random_payloads, key=lambda x: (x["symbol"], float(x["budget"]))):
        lines.append(render_coin_section(p))

    if errors:
        lines += ["---", "", "## Hatalar", ""] + [f"- {e}" for e in errors] + [""]

    lines += ["---", "", "*Rapor otomatik üretildi; canlı piyasa anına bağlıdır.*"]
    return "\n".join(lines)


async def main_async(
    *,
    random_count: int,
    budgets_random: List[float],
    output: Path,
    run_baseline: bool,
) -> None:
    os.environ.setdefault("PARAM_POOL_VERSION", "v4.0.0")
    from app.services.dynamic_param_score.param_pool.versioning import clear_pool_cache

    clear_pool_cache()
    errors: List[str] = []

    print("Fetching tradable USDT symbols...", flush=True)
    pool = await fetch_tradable_usdt_symbols()
    random_symbols = pick_random_symbols(
        random_count,
        pool,
        exclude=set(BASELINE_SYMBOLS),
        seed=RANDOM_POOL_SEED,
    )
    print(f"Random picks ({len(random_symbols)}): {', '.join(random_symbols)}", flush=True)

    baseline_50: List[Dict[str, Any]] = []
    if run_baseline:
        for sym in BASELINE_SYMBOLS:
            try:
                print(f"[baseline 50] {sym}...", flush=True)
                baseline_50.append(await run_symbol(sym, 50.0))
            except Exception as exc:
                errors.append(f"baseline {sym}@50: {exc}")
                print(f"  ERROR {exc}", flush=True)

    random_payloads: List[Dict[str, Any]] = []
    for budget in budgets_random:
        for sym in random_symbols:
            try:
                print(f"[random {int(budget)}] {sym}...", flush=True)
                random_payloads.append(await run_symbol(sym, float(budget)))
            except Exception as exc:
                errors.append(f"random {sym}@{budget}: {exc}")
                print(f"  ERROR {exc}", flush=True)

    report = build_full_report(
        baseline_50,
        random_payloads,
        random_symbols,
        budgets_random,
        errors,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    json_path = output.with_suffix(".json")
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "random_seed": RANDOM_POOL_SEED,
                "random_symbols": random_symbols,
                "baseline_symbols": list(BASELINE_SYMBOLS),
                "budgets_random": budgets_random,
                "baseline_50": [
                    {"symbol": p["symbol"], "budget": p["budget"], "price": p["price"], "result": p["result"]}
                    for p in baseline_50
                ],
                "random_runs": [
                    {"symbol": p["symbol"], "budget": p["budget"], "price": p["price"], "result": p["result"]}
                    for p in random_payloads
                ],
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {output}")
    print(f"Wrote {json_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Batch DPS live report")
    p.add_argument("--random-count", type=int, default=30)
    p.add_argument("--budgets-random", type=str, default="50,100,1000")
    p.add_argument("--no-baseline", action="store_true")
    p.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "docs" / "PARAM_ENGINE_LIVE_BATCH_REPORT.md"),
    )
    args = p.parse_args()
    budgets = [float(x.strip()) for x in args.budgets_random.split(",") if x.strip()]
    asyncio.run(
        main_async(
            random_count=args.random_count,
            budgets_random=budgets,
            output=Path(args.output),
            run_baseline=not args.no_baseline,
        )
    )


if __name__ == "__main__":
    main()
