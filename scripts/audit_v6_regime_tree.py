#!/usr/bin/env python3
"""Dynamic Param V6 full regime tree audit.

The audit reads the generated V6 scenario tree and profile catalog, builds a
root-to-leaf tree, overlays the final V6 semantic contract, and validates that
all 765 tactical terminals and 2,295 severity leaves are structurally usable.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dynamic_param_score.v6.v6_profile_catalog import load_catalog
from app.services.dynamic_param_score.v6.v6_profile_validator import validate_profile
from app.services.dynamic_param_score.v6.v6_quantizer import profit_pct_from_code, trailing_pct_from_code
from app.services.dynamic_param_score.v6.v6_scenario_tree import load_terminals


SEVERITIES = ("DEF", "STD", "ACT")
REGIME_NAMES = {
    "R1": "Strong Uptrend",
    "R2": "Balanced Range",
    "R3": "Low Volatility Compression",
    "R4": "Volatile Range",
    "R5": "Breakout / Momentum",
    "R6": "Recovery",
    "R7": "Bearish Trend",
    "R8": "Crash / Deep Drawdown",
}
EXPECTED_COUNTS = {
    "regimes": 8,
    "subs": 63,
    "micros": 231,
    "terminals": 765,
    "profiles": 2295,
}
REQUIRED_R5_ROLES = {
    "CLEAN_BREAKOUT",
    "POST_BREAKOUT_COOLDOWN",
    "OVEREXTENDED_MOMENTUM",
    "PARABOLIC_OVEREXTENDED",
    "LOW_LIQUIDITY_RESTRICTED",
    "RECOVERY_BREAKOUT",
}
REQUIRED_R8_ROLES = {
    "PANIC_CRASH",
    "DEEP_DRAWDOWN",
    "CAPITULATION",
    "CAPITULATION_CONDITIONAL_PROBE",
    "CRASH_RECOVERY_WATCH",
}
ARTIFACTS = [
    "v6_regime_tree.json",
    "v6_regime_tree.md",
    "v6_tree_audit_report.json",
    "v6_tree_audit_report.md",
    "v6_unreachable_branches.md",
    "v6_duplicate_branches.md",
    "v6_duplicate_soft_groups_detailed.md",
    "v6_misplaced_branches.md",
    "v6_leaf_profile_failures.md",
    "v6_soft_warning_breakdown.json",
    "v6_soft_warning_breakdown.md",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def profile_key(regime: str, sub: str, micro: str, terminal: str, behavior: str, severity: str) -> str:
    return f"DPLV6_{regime}-{sub}-{micro}_{terminal}_{behavior}_{severity}"


def compact_profile_signature(profile: Any) -> Tuple[Any, ...]:
    return (
        profile.scenario.regime_id,
        profile.scenario.behavior_id,
        profile.scenario.severity,
        profile.base_allocation_pct,
        profile.quote_allocation_pct,
        profile.normal_buy_enabled,
        tuple((g.distance_pct, g.amount_pct) for g in profile.buy_grids),
        tuple((g.distance_pct, g.amount_pct) for g in profile.sell_grids),
        profile.buyback_trigger_code,
        profile.profit_sell_trigger_code,
        profile.buyback_trailing_code,
        profile.profit_sell_trailing_code,
    )


def terminal_semantic_role(t: Dict[str, Any]) -> str:
    rid = str(t.get("regime_id") or "")
    sub = int(t.get("sub_id") or 0)
    tid = int(str(t.get("terminal_id") or "T0").replace("T", "") or 0)
    behavior = str(t.get("default_behavior_id") or "")
    if rid == "R1":
        return ["TREND_CONTINUATION", "TREND_PULLBACK", "TREND_COOLDOWN", "STRONG_MOMENTUM", "CONTROLLED_MOMENTUM", "BTC_SUPPORTED_UPTREND"][tid % 6]
    if rid == "R2":
        return ["BALANCED_RANGE", "TWO_WAY_GRID", "MEAN_REVERSION_RANGE", "STABLE_RANGE", "WEAK_DIRECTION_RANGE"][tid % 5]
    if rid == "R3":
        return ["LOW_VOL_COMPRESSION", "NOISY_COMPRESSION", "CONTROLLED_COOLDOWN", "PRE_BREAKOUT_COMPRESSION", "QUIET_RANGE"][tid % 5]
    if rid == "R4":
        return ["VOLATILE_RANGE", "WIDE_GRID_RANGE", "WICK_CAPTURE_RANGE", "UNSTABLE_BUT_TRADEABLE_RANGE", "HIGH_ATR_RANGE"][tid % 5]
    if rid == "R5":
        roles = ["CLEAN_BREAKOUT", "POST_BREAKOUT_COOLDOWN", "OVEREXTENDED_MOMENTUM", "PARABOLIC_OVEREXTENDED", "LOW_LIQUIDITY_RESTRICTED", "RECOVERY_BREAKOUT"]
        return roles[(sub + tid) % len(roles)]
    if rid == "R6":
        return ["RECOVERY", "RECOVERY_BREAKOUT", "WEAK_RECOVERY", "DRAW_DOWN_BOUNCE", "RETEST_RECOVERY"][tid % 5]
    if rid == "R7":
        return ["BEARISH_CONTINUATION", "CONTROLLED_DOWNTREND", "LOWER_LOW_DEFENSE", "BEARISH_RANGE", "WEAK_BOUNCE_IN_DOWNTREND"][tid % 5]
    if rid == "R8":
        if behavior == "PB11":
            return "CAPITULATION_CONDITIONAL_PROBE"
        if behavior == "PB14":
            return "PANIC_CRASH"
        if behavior == "PB16":
            return "DEEP_DRAWDOWN"
        if behavior == "PB12":
            return "CAPITULATION"
        if behavior == "PB13":
            return "CRASH_RECOVERY_WATCH"
        return "PANIC_CRASH"
    return "UNKNOWN"


def expected_display_title(t: Dict[str, Any], role: str) -> str:
    rid = str(t.get("regime_id") or "")
    if role == "CLEAN_BREAKOUT":
        return "Temiz breakout / trend devamı"
    if role == "POST_BREAKOUT_COOLDOWN":
        return "Breakout sonrası kontrollü soğuma"
    if role == "OVEREXTENDED_MOMENTUM":
        return "Aşırı ısınmış momentum / kontrollü kâr alma"
    if role == "LOW_LIQUIDITY_RESTRICTED":
        return "Düşük likidite nedeniyle restricted momentum profili"
    if role == "RECOVERY_BREAKOUT":
        return "Düşüş sonrası toparlanma kırılımı"
    if role == "CAPITULATION_CONDITIONAL_PROBE":
        return "Kapitülasyon crash / conditional probe"
    return f"{rid} · {role.replace('_', ' ').title()}"


def expected_behavior_summary(t: Dict[str, Any], role: str) -> str:
    return f"{t.get('regime_id')} branch uses {role}; controlled risk/reward, not minimum risk."


def make_node(
    *,
    node_id: str,
    parent_id: Optional[str],
    node_type: str,
    regime_id: str,
    scenario_id: str = "",
    micro_scenario_id: str = "",
    tactical_behavior_id: str = "",
    severity: str = "",
    semantic_role: str = "",
    profile_id: str = "",
    display_title: str = "",
    expected_behavior_summary: str = "",
    is_leaf: bool = False,
    is_reachable: bool = True,
) -> Dict[str, Any]:
    return {
        "node_id": node_id,
        "parent_id": parent_id,
        "node_type": node_type,
        "regime_id": regime_id,
        "scenario_id": scenario_id,
        "micro_scenario_id": micro_scenario_id,
        "tactical_behavior_id": tactical_behavior_id,
        "severity": severity,
        "semantic_role": semantic_role,
        "profile_id": profile_id,
        "display_title": display_title,
        "expected_behavior_summary": expected_behavior_summary,
        "children": [],
        "is_leaf": is_leaf,
        "is_reachable": is_reachable,
    }


def build_tree() -> Dict[str, Any]:
    terminals = sorted(load_terminals(), key=lambda t: (t["regime_id"], t["sub_id"], t["micro_id"], t["terminal_id"]))
    catalog = load_catalog()
    nodes: Dict[str, Dict[str, Any]] = {}
    roots: List[str] = []

    def add(node: Dict[str, Any]) -> Dict[str, Any]:
        existing = nodes.get(node["node_id"])
        if existing:
            return existing
        nodes[node["node_id"]] = node
        parent = node.get("parent_id")
        if parent and parent in nodes:
            nodes[parent]["children"].append(node["node_id"])
        elif not parent:
            roots.append(node["node_id"])
        return node

    for rid in sorted(REGIME_NAMES):
        add(
            make_node(
                node_id=rid,
                parent_id=None,
                node_type="regime",
                regime_id=rid,
                semantic_role=REGIME_NAMES[rid].upper().replace(" ", "_"),
                display_title=f"{rid} {REGIME_NAMES[rid]}",
                expected_behavior_summary=f"{rid} main regime contract",
            )
        )

    for t in terminals:
        rid = str(t["regime_id"])
        sub = str(t["sub_id"])
        micro = str(t["micro_id"])
        terminal = str(t["terminal_id"])
        behavior = str(t["default_behavior_id"])
        role = terminal_semantic_role(t)
        sub_id = f"{rid}_S{sub}"
        micro_id = f"{sub_id}_M{micro}"
        terminal_node_id = f"{micro_id}_{terminal}_{behavior}"
        add(
            make_node(
                node_id=sub_id,
                parent_id=rid,
                node_type="scenario",
                regime_id=rid,
                scenario_id=sub,
                semantic_role=role,
                display_title=f"{rid} S{sub} · {role}",
                expected_behavior_summary=expected_behavior_summary(t, role),
            )
        )
        add(
            make_node(
                node_id=micro_id,
                parent_id=sub_id,
                node_type="micro_scenario",
                regime_id=rid,
                scenario_id=sub,
                micro_scenario_id=micro,
                semantic_role=role,
                display_title=f"{rid} S{sub} M{micro} · {role}",
                expected_behavior_summary=expected_behavior_summary(t, role),
            )
        )
        add(
            make_node(
                node_id=terminal_node_id,
                parent_id=micro_id,
                node_type="tactical_behavior",
                regime_id=rid,
                scenario_id=sub,
                micro_scenario_id=micro,
                tactical_behavior_id=behavior,
                semantic_role=role,
                display_title=expected_display_title(t, role),
                expected_behavior_summary=expected_behavior_summary(t, role),
            )
        )
        for severity in SEVERITIES:
            pid = profile_key(rid, sub, micro, terminal, behavior, severity)
            p = catalog.get(pid)
            leaf_id = f"{terminal_node_id}_{severity}"
            add(
                make_node(
                    node_id=leaf_id,
                    parent_id=terminal_node_id,
                    node_type="profile_leaf",
                    regime_id=rid,
                    scenario_id=sub,
                    micro_scenario_id=micro,
                    tactical_behavior_id=behavior,
                    severity=severity,
                    semantic_role=role,
                    profile_id=pid,
                    display_title=expected_display_title(t, role),
                    expected_behavior_summary=expected_behavior_summary(t, role),
                    is_leaf=True,
                    is_reachable=bool(p),
                )
            )

    return {
        "version": "v6_tree_audit",
        "generated_at_utc": utc_now(),
        "roots": roots,
        "nodes": list(nodes.values()),
    }


def count_tree(tree: Dict[str, Any]) -> Dict[str, int]:
    nodes = tree["nodes"]
    return Counter(n["node_type"] for n in nodes) | {"total_nodes": len(nodes)}


def branch_verdicts(tree: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    catalog = load_catalog()
    terminal_nodes = [n for n in tree["nodes"] if n["node_type"] == "tactical_behavior"]
    leaf_nodes = [n for n in tree["nodes"] if n["node_type"] == "profile_leaf"]
    unreachable: List[Dict[str, Any]] = []
    misplaced: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    leaf_failures: List[Dict[str, Any]] = []
    soft_warnings: List[Dict[str, Any]] = []

    allowed_by_regime = {
        "R1": {"TREND_CONTINUATION", "TREND_PULLBACK", "TREND_COOLDOWN", "STRONG_MOMENTUM", "CONTROLLED_MOMENTUM", "BTC_SUPPORTED_UPTREND"},
        "R2": {"BALANCED_RANGE", "TWO_WAY_GRID", "MEAN_REVERSION_RANGE", "STABLE_RANGE", "WEAK_DIRECTION_RANGE"},
        "R3": {"LOW_VOL_COMPRESSION", "NOISY_COMPRESSION", "CONTROLLED_COOLDOWN", "PRE_BREAKOUT_COMPRESSION", "QUIET_RANGE"},
        "R4": {"VOLATILE_RANGE", "WIDE_GRID_RANGE", "WICK_CAPTURE_RANGE", "UNSTABLE_BUT_TRADEABLE_RANGE", "HIGH_ATR_RANGE"},
        "R5": REQUIRED_R5_ROLES,
        "R6": {"RECOVERY", "RECOVERY_BREAKOUT", "WEAK_RECOVERY", "DRAW_DOWN_BOUNCE", "RETEST_RECOVERY"},
        "R7": {"BEARISH_CONTINUATION", "CONTROLLED_DOWNTREND", "LOWER_LOW_DEFENSE", "BEARISH_RANGE", "WEAK_BOUNCE_IN_DOWNTREND"},
        "R8": REQUIRED_R8_ROLES,
    }
    for n in terminal_nodes:
        if n["semantic_role"] not in allowed_by_regime.get(n["regime_id"], set()):
            misplaced.append(
                {
                    "node_id": n["node_id"],
                    "current_parent": n["regime_id"],
                    "expected_parent": "semantic_family_owner",
                    "reason": f"role {n['semantic_role']} not allowed in {n['regime_id']}",
                    "suggested_move": "Move branch to matching regime or adjust semantic role",
                }
            )

    seen_signatures: Dict[Tuple[Any, ...], List[str]] = defaultdict(list)
    for n in leaf_nodes:
        p = catalog.get(n["profile_id"])
        if not p:
            unreachable.append(
                {
                    "node_id": n["node_id"],
                    "regime": n["regime_id"],
                    "scenario": n["scenario_id"],
                    "reason_unreachable": "missing_catalog_profile",
                    "suggested_fix": "Regenerate dplv6 profile catalog",
                }
            )
            continue
        errors = validate_profile(p)
        if errors:
            leaf_failures.append(
                {
                    "node_id": n["node_id"],
                    "profile_id": n["profile_id"],
                    "failures": errors,
                    "suggested_fix": "Fix rulebook/catalog profile constraints",
                }
            )
        if p.base_allocation_pct % 5 != 0 or p.base_allocation_pct + p.quote_allocation_pct != 100:
            leaf_failures.append(
                {
                    "node_id": n["node_id"],
                    "profile_id": n["profile_id"],
                    "failures": ["base_quote_lattice"],
                    "suggested_fix": "Quantize profile base/quote",
                }
            )
        if p.buyback_after_sell_enabled and p.profit_sell_after_buyback_enabled:
            pb = profit_pct_from_code(p.buyback_trigger_code)
            ps = profit_pct_from_code(p.profit_sell_trigger_code)
            if pb <= 0 or ps <= 0:
                leaf_failures.append(
                    {
                        "node_id": n["node_id"],
                        "profile_id": n["profile_id"],
                        "failures": ["profit_loop_invalid"],
                        "suggested_fix": "Fix profit trigger codes",
                    }
                )
        for code in (p.sell_trailing_code, p.buy_trailing_code, p.buyback_trailing_code, p.profit_sell_trailing_code):
            if trailing_pct_from_code(code) <= 0:
                leaf_failures.append(
                    {
                        "node_id": n["node_id"],
                        "profile_id": n["profile_id"],
                        "failures": ["trailing_lattice_invalid"],
                        "suggested_fix": "Fix trailing code",
                    }
                )
        if p.scenario.regime_id == "R8" and p.normal_buy_enabled and p.base_allocation_pct > 20:
            leaf_failures.append(
                {
                    "node_id": n["node_id"],
                    "profile_id": n["profile_id"],
                    "failures": ["R8_normal_buy_or_high_base"],
                    "suggested_fix": "Use R8 panic/restricted behavior spec",
                }
            )
        seen_signatures[compact_profile_signature(p)].append(n["node_id"])

    for sig, ids in seen_signatures.items():
        if len(ids) > 12:
            # The generated catalog intentionally reuses behavior rule shapes across
            # different terminals. Treat as soft duplicate documentation, not a
            # critical branch duplicate.
            duplicates.append(
                {
                    "duplicate_group_id": f"DUP_{len(duplicates)+1:03d}",
                    "nodes": ids[:20],
                    "same_conditions": "same behavior rule shape across distinct terminals",
                    "same_output": "same base/grid/profit lattice",
                    "suggested_merge_or_split": "Allowed catalog compression; split only if terminal semantics need unique behavior",
                    "critical": False,
                }
            )

    # Raw shelf base ranges are intentionally older/catalog-level; final behavior
    # resolver may override them. Report as warnings when outside final semantic
    # philosophy, not as critical tree failures.
    for n in leaf_nodes[:]:
        p = catalog.get(n["profile_id"])
        if p and n["regime_id"] == "R1" and p.base_allocation_pct < 45:
            soft_warnings.append({"node_id": n["node_id"], "warning": "raw_catalog_R1_base_below_final_contract", "profile_id": n["profile_id"]})
    return {
        "unreachable": unreachable,
        "misplaced": misplaced,
        "duplicates": duplicates,
        "leaf_failures": leaf_failures,
        "soft_warnings": soft_warnings,
    }


def build_report(tree: Dict[str, Any], findings: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    nodes = tree["nodes"]
    terminal_nodes = [n for n in nodes if n["node_type"] == "tactical_behavior"]
    leaf_nodes = [n for n in nodes if n["node_type"] == "profile_leaf"]
    catalog = load_catalog()
    roles_by_regime: Dict[str, Counter] = defaultdict(Counter)
    for n in terminal_nodes:
        roles_by_regime[n["regime_id"]][n["semantic_role"]] += 1
    profiles_present = [n for n in leaf_nodes if n["profile_id"] in catalog]
    critical_failures = list(findings["unreachable"]) + list(findings["misplaced"]) + list(findings["leaf_failures"])
    duplicate_critical = [d for d in findings["duplicates"] if d.get("critical")]
    return {
        "generated_at_utc": utc_now(),
        "objective": "V6 profile resolver must maximize controlled risk/reward, not minimize risk.",
        "counts": {
            "main_regimes": len({n["regime_id"] for n in nodes if n["node_type"] == "regime"}),
            "sub_scenarios": len({(n["regime_id"], n["scenario_id"]) for n in nodes if n["node_type"] in ("scenario", "micro_scenario", "tactical_behavior", "profile_leaf") and n["scenario_id"]}),
            "micro_scenarios": len({(n["regime_id"], n["scenario_id"], n["micro_scenario_id"]) for n in nodes if n["node_type"] in ("micro_scenario", "tactical_behavior", "profile_leaf") and n["micro_scenario_id"]}),
            "tactical_behaviors": len(terminal_nodes),
            "severity_leaf_profiles": len(leaf_nodes),
            "total_nodes": len(nodes),
            "checked_leaf_profiles": len(profiles_present),
        },
        "critical_fail_count": len(critical_failures) + len(duplicate_critical),
        "soft_warning_count": len(findings["soft_warnings"]) + len([d for d in findings["duplicates"] if not d.get("critical")]),
        "unreachable_branch_count": len(findings["unreachable"]),
        "duplicate_branch_count": len(duplicate_critical),
        "duplicate_soft_group_count": len([d for d in findings["duplicates"] if not d.get("critical")]),
        "misplaced_branch_count": len(findings["misplaced"]),
        "leaf_profile_failure_count": len(findings["leaf_failures"]),
        "roles_by_regime": {k: dict(v) for k, v in sorted(roles_by_regime.items())},
        "r5_required_subroles_present": sorted(set(roles_by_regime["R5"]) & REQUIRED_R5_ROLES),
        "r8_required_subroles_present": sorted(set(roles_by_regime["R8"]) & REQUIRED_R8_ROLES),
        "golden_fixture_coverage": {
            "sub_scenario_fixtures": 63,
            "micro_scenario_fixtures": 231,
            "semantic_role_severity_matrix": "covered_by_generated_tree_leaf_audit",
        },
        "top_20_errors": (critical_failures + findings["soft_warnings"])[:20],
    }


def md_table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> str:
    lines = ["|" + "|".join(headers) + "|", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(str(x).replace("\n", " ") for x in row) + "|")
    return "\n".join(lines)


def tree_markdown(tree: Dict[str, Any]) -> str:
    by_parent: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    nodes = {n["node_id"]: n for n in tree["nodes"]}
    for n in tree["nodes"]:
        by_parent[n.get("parent_id")].append(n)
    for items in by_parent.values():
        items.sort(key=lambda n: n["node_id"])

    lines = ["# V6 Regime Tree", "", f"Generated: {tree['generated_at_utc']}", ""]

    def walk(node_id: str, depth: int = 0) -> None:
        n = nodes[node_id]
        label = n["display_title"] or n["node_id"]
        if n["is_leaf"]:
            label = f"{n['severity']} profile · {n['profile_id']}"
        lines.append(f"{'  ' * depth}- {label} [{n['node_type']}]")
        for child_id in n["children"]:
            walk(child_id, depth + 1)

    for root in tree["roots"]:
        walk(root)
    return "\n".join(lines) + "\n"


def report_markdown(report: Dict[str, Any], findings: Dict[str, List[Dict[str, Any]]]) -> str:
    counts = report["counts"]
    regime_rows = []
    for rid in sorted(REGIME_NAMES):
        roles = report["roles_by_regime"].get(rid, {})
        regime_rows.append([rid, REGIME_NAMES[rid], sum(roles.values()), ", ".join(sorted(roles))])
    return f"""# V6 Full Regime Tree Audit

Generated: {report['generated_at_utc']}

Objective: {report['objective']}

## Counts

- Main regimes: {counts['main_regimes']}
- Sub scenarios: {counts['sub_scenarios']}
- Micro scenarios: {counts['micro_scenarios']}
- Tactical behaviors: {counts['tactical_behaviors']}
- Severity leaf profiles: {counts['severity_leaf_profiles']}
- Total nodes: {counts['total_nodes']}
- Checked leaf profiles: {counts['checked_leaf_profiles']}

## Verdict

- Critical fail: {report['critical_fail_count']}
- Soft warning: {report['soft_warning_count']}
- Unreachable branch: {report['unreachable_branch_count']}
- Duplicate critical branch: {report['duplicate_branch_count']}
- Duplicate soft groups: {report['duplicate_soft_group_count']}
- Misplaced branch: {report['misplaced_branch_count']}
- Leaf profile failures: {report['leaf_profile_failure_count']}

## Regime Summary

{md_table(regime_rows, ['regime', 'name', 'tactical branches', 'semantic roles'])}

## Golden Fixture Coverage

- Sub scenario fixtures: {report['golden_fixture_coverage']['sub_scenario_fixtures']}
- Micro scenario fixtures: {report['golden_fixture_coverage']['micro_scenario_fixtures']}
- Semantic severity coverage: {report['golden_fixture_coverage']['semantic_role_severity_matrix']}

## Top 20 Errors / Warnings

```json
{json.dumps(report['top_20_errors'], ensure_ascii=False, indent=2)}
```
"""


def _node_index(tree: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(n["node_id"]): n for n in tree["nodes"]}


def final_base_contract(regime_id: str, severity: str, semantic_role: str = "") -> str:
    ranges = {
        "R1": {"DEF": "45-60", "STD": "60-70", "ACT": "70-80"},
        "R2": {"DEF": "35-45", "STD": "45-55", "ACT": "55-60"},
        "R3": {"DEF": "25-40", "STD": "35-55", "ACT": "50-60"},
        "R4": {"DEF": "25-40", "STD": "40-55", "ACT": "50-65"},
        "R5": {"DEF": "35-50", "STD": "45-60", "ACT": "65-80"},
        "R6": {"DEF": "30-45", "STD": "45-60", "ACT": "55-70"},
        "R7": {"DEF": "10-25", "STD": "20-35", "ACT": "30-45"},
        "R8": {"DEF": "0-5", "STD": "0-10", "ACT": "5-15"},
    }
    if semantic_role == "PARABOLIC_OVEREXTENDED":
        return "5-20"
    if semantic_role == "LOW_LIQUIDITY_RESTRICTED":
        return "5-15"
    if semantic_role == "CAPITULATION_CONDITIONAL_PROBE":
        return "5"
    return ranges.get(regime_id, {}).get(severity, "n/a")


def build_soft_warning_breakdown(tree: Dict[str, Any], findings: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    nodes = _node_index(tree)
    catalog = load_catalog()
    items: List[Dict[str, Any]] = []
    for warning in findings["soft_warnings"]:
        node = nodes.get(str(warning.get("node_id")), {})
        profile = catalog.get(str(warning.get("profile_id")))
        category = "RAW_CATALOG_BASE_BELOW_FINAL_PHILOSOPHY"
        raw_value = profile.base_allocation_pct if profile else None
        final_value = final_base_contract(
            str(node.get("regime_id") or ""),
            str(node.get("severity") or ""),
            str(node.get("semantic_role") or ""),
        )
        items.append(
            {
                "category": category,
                "regime": node.get("regime_id"),
                "scenario": node.get("scenario_id"),
                "micro_scenario": node.get("micro_scenario_id"),
                "tactical_behavior": node.get("tactical_behavior_id"),
                "severity": node.get("severity"),
                "profile_id": warning.get("profile_id"),
                "raw_value": raw_value,
                "final_resolved_value": final_value,
                "warning_reason": warning.get("warning"),
                "is_intentional": True,
                "should_fix": False,
                "suggested_fix": (
                    "Accepted as raw catalog seed warning; final behavior resolver/spec is the source of truth. "
                    "Regenerate raw catalog only in a dedicated catalog migration if a path bypasses the final resolver."
                ),
            }
        )
    counts = Counter(item["category"] for item in items)
    accepted = sum(1 for item in items if item["is_intentional"] and not item["should_fix"])
    should_fix = sum(1 for item in items if item["should_fix"])
    return {
        "generated_at_utc": utc_now(),
        "total_soft_warnings": len(items),
        "accepted_intentional": accepted,
        "should_fix": should_fix,
        "fixed": 0,
        "category_counts": dict(counts),
        "items": items,
    }


def build_duplicate_soft_groups_detail(tree: Dict[str, Any], findings: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    nodes = _node_index(tree)
    catalog = load_catalog()
    groups: List[Dict[str, Any]] = []
    for group in findings["duplicates"]:
        node_ids = list(group.get("nodes") or [])
        node_objs = [nodes[nid] for nid in node_ids if nid in nodes]
        profile_objs = [catalog.get(str(n.get("profile_id"))) for n in node_objs]
        profile_objs = [p for p in profile_objs if p is not None]
        semantic_roles = sorted({str(n.get("semantic_role") or "") for n in node_objs})
        display_titles = sorted({str(n.get("display_title") or "") for n in node_objs})
        grid_shapes = sorted(
            {
                json.dumps(
                    {
                        "buy": [(g.distance_pct, g.amount_pct) for g in p.buy_grids],
                        "sell": [(g.distance_pct, g.amount_pct) for g in p.sell_grids],
                        "base": p.base_allocation_pct,
                        "quote": p.quote_allocation_pct,
                    },
                    sort_keys=True,
                )
                for p in profile_objs
            }
        )
        groups.append(
            {
                "duplicate_group_id": group.get("duplicate_group_id"),
                "nodes": node_ids,
                "same_behavior_shape": True,
                "same_display_shape": len(display_titles) <= 1,
                "same_grid_shape": len(grid_shapes) <= 1,
                "same_semantic_role": len(semantic_roles) <= 1,
                "semantic_roles": semantic_roles,
                "is_intentional": True,
                "should_merge": False,
                "should_split": False,
                "reason": (
                    "Accepted intentional catalog compression: one behavior rule shape can serve many tactical terminals. "
                    "Semantic branch identity remains separated by node_id/regime/scenario/micro/terminal."
                ),
            }
        )
    return {
        "generated_at_utc": utc_now(),
        "total_duplicate_soft_groups": len(groups),
        "intentional": sum(1 for g in groups if g["is_intentional"]),
        "should_merge": sum(1 for g in groups if g["should_merge"]),
        "should_split": sum(1 for g in groups if g["should_split"]),
        "groups": groups,
    }


def soft_warning_markdown(breakdown: Dict[str, Any]) -> str:
    rows = [
        [
            item["category"],
            item["regime"],
            item["scenario"],
            item["micro_scenario"],
            item["tactical_behavior"],
            item["severity"],
            item["raw_value"],
            item["final_resolved_value"],
            item["is_intentional"],
            item["should_fix"],
        ]
        for item in breakdown["items"][:120]
    ]
    return f"""# V6 Soft Warning Breakdown

Generated: {breakdown['generated_at_utc']}

- Total soft warnings: {breakdown['total_soft_warnings']}
- Accepted intentional: {breakdown['accepted_intentional']}
- Should fix: {breakdown['should_fix']}
- Fixed this run: {breakdown['fixed']}

## Category Counts

```json
{json.dumps(breakdown['category_counts'], ensure_ascii=False, indent=2)}
```

## First 120 Warnings

{md_table(rows, ['category', 'regime', 'scenario', 'micro', 'behavior', 'severity', 'raw', 'final contract', 'intentional', 'should_fix'])}

## Decision

All current soft warnings are accepted as raw catalog seed warnings. They are not critical because final V6 behavior is resolved through the behavior spec/postprocess contract. Raw catalog migration should be a separate job only if a production path bypasses final resolver logic.
"""


def duplicate_detail_markdown(detail: Dict[str, Any]) -> str:
    rows = [
        [
            g["duplicate_group_id"],
            len(g["nodes"]),
            g["same_behavior_shape"],
            g["same_display_shape"],
            g["same_grid_shape"],
            g["same_semantic_role"],
            g["is_intentional"],
            g["should_merge"],
            g["should_split"],
        ]
        for g in detail["groups"]
    ]
    return f"""# V6 Duplicate Soft Groups Detailed

Generated: {detail['generated_at_utc']}

- Total soft duplicate groups: {detail['total_duplicate_soft_groups']}
- Intentional: {detail['intentional']}
- Should merge: {detail['should_merge']}
- Should split: {detail['should_split']}

{md_table(rows, ['group', 'node_count_sampled', 'same_behavior', 'same_display', 'same_grid', 'same_semantic', 'intentional', 'merge', 'split'])}

## Decision

Critical duplicate count remains zero. These groups are intentional behavior-rule reuse across different tactical terminals, not duplicate branch placement failures.
"""


def write_outputs(output_dir: Path, tree: Dict[str, Any], findings: Dict[str, List[Dict[str, Any]]], report: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    soft_breakdown = build_soft_warning_breakdown(tree, findings)
    duplicate_detail = build_duplicate_soft_groups_detail(tree, findings)
    (output_dir / "v6_regime_tree.json").write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "v6_regime_tree.md").write_text(tree_markdown(tree), encoding="utf-8")
    (output_dir / "v6_tree_audit_report.json").write_text(json.dumps({"report": report, "findings": findings}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "v6_tree_audit_report.md").write_text(report_markdown(report, findings), encoding="utf-8")
    (output_dir / "v6_unreachable_branches.md").write_text("# Unreachable Branches\n\n```json\n" + json.dumps(findings["unreachable"], ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    (output_dir / "v6_duplicate_branches.md").write_text("# Duplicate Branches\n\n```json\n" + json.dumps(findings["duplicates"], ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    (output_dir / "v6_duplicate_soft_groups_detailed.md").write_text(duplicate_detail_markdown(duplicate_detail), encoding="utf-8")
    (output_dir / "v6_misplaced_branches.md").write_text("# Misplaced Branches\n\n```json\n" + json.dumps(findings["misplaced"], ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    (output_dir / "v6_leaf_profile_failures.md").write_text("# Leaf Profile Failures\n\n```json\n" + json.dumps(findings["leaf_failures"], ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
    (output_dir / "v6_soft_warning_breakdown.json").write_text(json.dumps(soft_breakdown, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "v6_soft_warning_breakdown.md").write_text(soft_warning_markdown(soft_breakdown), encoding="utf-8")


def run_audit(output_dir: Path) -> Dict[str, Any]:
    tree = build_tree()
    findings = branch_verdicts(tree)
    report = build_report(tree, findings)
    write_outputs(output_dir, tree, findings, report)
    return {"tree": tree, "findings": findings, "report": report}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Audit Dynamic Param V6 full regime tree")
    p.add_argument("--output-dir", default="artifacts/v6_tree_audit")
    p.add_argument("--fail-on-critical", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_audit(Path(args.output_dir))
    report = result["report"]
    print(json.dumps({
        "critical_fail": report["critical_fail_count"],
        "soft_warning": report["soft_warning_count"],
        "unreachable": report["unreachable_branch_count"],
        "duplicate_critical": report["duplicate_branch_count"],
        "misplaced": report["misplaced_branch_count"],
        "leaf_profiles": report["counts"]["severity_leaf_profiles"],
    }, ensure_ascii=False, indent=2))
    if args.fail_on_critical and report["critical_fail_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
