#!/usr/bin/env python3
"""Generate scenario_tree, behavior_catalog, parameter_rulebook for V6 (765 terminals → 2295 profiles)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "dynamic_param_v6"

REGIME_COUNT = 8
SUB_COUNT = 63
MICRO_COUNT = 231
TERMINAL_COUNT = 765

REGIME_META = {
    "R1": ("Güçlü yükseliş trendi", ["uptrend", "momentum"]),
    "R2": ("Dengeli aralık", ["range", "balanced"]),
    "R3": ("Zayıf / gürültülü aralık", ["noise", "chop"]),
    "R4": ("Volatil aralık", ["volatile", "wide_range"]),
    "R5": ("Toparlanma", ["recovery", "bounce"]),
    "R6": ("Tepe / dağılım / zayıflama", ["distribution", "weakness"]),
    "R7": ("Düşüş trendi", ["downtrend", "defensive"]),
    "R8": ("Crash / sert düşüş", ["crash", "breakdown"]),
}

BEHAVIOR_FAMILIES: List[Dict[str, Any]] = [
    {"behavior_id": "PB01", "name": "CONTROLLED_TWO_WAY_RANGE_GRID", "regimes": ["R2", "R3"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB02", "name": "VOLATILE_TWO_WAY_WIDE_GRID", "regimes": ["R4"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB03", "name": "SUPPORT_NEAR_BUY_WEIGHTED_GRID", "regimes": ["R2", "R5"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB04", "name": "RESISTANCE_NEAR_SELL_WEIGHTED_GRID", "regimes": ["R6"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB05", "name": "BREAKOUT_FOLLOW", "regimes": ["R1", "R5"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB06", "name": "FAKE_BREAKOUT_PROTECT", "regimes": ["R4", "R6"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB07", "name": "CLEAN_RECOVERY", "regimes": ["R5"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB08", "name": "DEEP_DIP_RECOVERY_BUY", "regimes": ["R5", "R7"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB09", "name": "PUMP_PULLBACK_MANAGE", "regimes": ["R1", "R6"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB10", "name": "DOWNTREND_DEFENSIVE_GRID", "regimes": ["R7"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB11", "name": "CRASH_SELL_GRID_WITH_POST_SELL_BUYBACK", "regimes": ["R8"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB12", "name": "CRASH_DEEP_CATCH", "regimes": ["R8"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB13", "name": "BREAKDOWN_BASE_PROTECT", "regimes": ["R7", "R8"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB14", "name": "DUMP_BOUNCE_SELL", "regimes": ["R8"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": True, "profit_sell_after_buyback": True}},
    {"behavior_id": "PB15", "name": "LOW_LIQUIDITY_FRAGILE_PROTECT", "regimes": ["R3", "R4"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": False, "profit_sell_after_buyback": False}},
    {"behavior_id": "PB16", "name": "DATA_QUALITY_SAFE_PROFILE", "regimes": ["R2", "R3", "R4", "R7", "R8"], "modules": {"initial_base_allocation": True, "normal_buy_grid": True, "sell_grid": True, "profit_buyback_after_sell": False, "profit_sell_after_buyback": False}},
]


def _distribute_extra(total: int, buckets: int, base: int) -> List[int]:
    counts = [base] * buckets
    rem = total - base * buckets
    for i in range(rem):
        counts[i % buckets] += 1
    return counts


def _behavior_rules() -> Dict[str, Dict[str, Dict[str, Any]]]:
    def two_buy(d, s, b, bt, st, kbb, kps):
        return {
            "normal_buy_enabled": True,
            "buy_grids": [{"distance_pct": d[0], "amount_pct": b[0]}, {"distance_pct": d[1], "amount_pct": b[1]}],
            "sell_grids": [{"distance_pct": s[0], "amount_pct": b[2]}, {"distance_pct": s[1], "amount_pct": b[3]}],
            "buy_trailing_code": bt,
            "sell_trailing_code": st,
            "buyback_after_sell_enabled": True,
            "buyback_trigger_code": kbb,
            "buyback_trailing_code": bt,
            "profit_sell_after_buyback_enabled": True,
            "profit_sell_trigger_code": kps,
            "profit_sell_trailing_code": st,
        }

    def sell_only(dist, st, kbb, kps, base, buy_dist):
        return {
            "normal_buy_enabled": True,
            "buy_grids": [{"distance_pct": -abs(buy_dist), "amount_pct": 100}],
            "sell_grids": [{"distance_pct": dist, "amount_pct": 100}],
            "buy_trailing_code": "T2",
            "sell_trailing_code": st,
            "buyback_after_sell_enabled": True,
            "buyback_trigger_code": kbb,
            "buyback_trailing_code": "T2",
            "profit_sell_after_buyback_enabled": True,
            "profit_sell_trigger_code": kps,
            "profit_sell_trailing_code": st,
            "base_allocation_pct": base,
        }

    def safe_sell(base, dist, st, buy_dist):
        return {
            "normal_base_allocation": True,
            "normal_buy_enabled": True,
            "buy_grids": [{"distance_pct": -abs(buy_dist), "amount_pct": 100}],
            "sell_grids": [{"distance_pct": dist, "amount_pct": 100}],
            "buy_trailing_code": "T2",
            "sell_trailing_code": st,
            "buyback_after_sell_enabled": False,
            "profit_sell_after_buyback_enabled": False,
            "base_allocation_pct": base,
        }

    rules: Dict[str, Dict[str, Dict[str, Any]]] = {}
    rules["PB01"] = {
        "DEF": {"base_allocation_pct": 25, **two_buy([-8, -12], [5, 9], [40, 60, 60, 40], "T3", "T4", "K12", "K12")},
        "STD": {"base_allocation_pct": 30, **two_buy([-7, -10], [5, 9], [40, 60, 60, 40], "T3", "T4", "K11", "K11")},
        "ACT": {"base_allocation_pct": 40, **two_buy([-6, -9], [4, 7], [30, 70, 60, 40], "T2", "T3", "K10", "K10")},
    }
    rules["PB02"] = {
        "DEF": {"base_allocation_pct": 20, **two_buy([-8, -14], [6, 13], [40, 60, 60, 40], "T3", "T3", "K12", "K12")},
        "STD": {"base_allocation_pct": 25, **two_buy([-8, -14], [6, 13], [40, 60, 60, 40], "T2", "T3", "K11", "K11")},
        "ACT": {"base_allocation_pct": 35, **two_buy([-7, -12], [5, 10], [30, 70, 60, 40], "T2", "T2", "K10", "K10")},
    }
    rules["PB03"] = {
        "DEF": {"base_allocation_pct": 30, **two_buy([-6, -10], [5, 8], [60, 40, 40, 60], "T3", "T4", "K11", "K11")},
        "STD": {"base_allocation_pct": 35, **two_buy([-5, -9], [4, 7], [60, 40, 40, 60], "T2", "T3", "K10", "K10")},
        "ACT": {"base_allocation_pct": 45, **two_buy([-4, -8], [4, 6], [70, 30, 40, 60], "T2", "T2", "K09", "K09")},
    }
    rules["PB04"] = {
        "DEF": {"base_allocation_pct": 20, **two_buy([-9, -14], [4, 8], [40, 60, 70, 30], "T3", "T3", "K12", "K12")},
        "STD": {"base_allocation_pct": 25, **two_buy([-8, -12], [4, 7], [40, 60, 60, 40], "T2", "T3", "K11", "K11")},
        "ACT": {"base_allocation_pct": 30, **two_buy([-7, -11], [3, 6], [30, 70, 60, 40], "T2", "T2", "K10", "K10")},
    }
    rules["PB05"] = {
        "DEF": {"base_allocation_pct": 25, **two_buy([-7, -11], [6, 11], [40, 60, 60, 40], "T3", "T3", "K11", "K11")},
        "STD": {"base_allocation_pct": 35, **two_buy([-6, -10], [5, 9], [40, 60, 60, 40], "T2", "T3", "K10", "K10")},
        "ACT": {"base_allocation_pct": 45, **two_buy([-5, -8], [4, 7], [30, 70, 60, 40], "T2", "T2", "K09", "K09")},
    }
    rules["PB06"] = {
        "DEF": sell_only(9, "T3", "K12", "K12", 15, 18),
        "STD": sell_only(8, "T2", "K11", "K11", 20, 16),
        "ACT": sell_only(7, "T2", "K10", "K10", 25, 14),
    }
    rules["PB07"] = {
        "DEF": {"base_allocation_pct": 25, **two_buy([-7, -11], [5, 9], [40, 60, 60, 40], "T3", "T3", "K11", "K11")},
        "STD": {"base_allocation_pct": 30, **two_buy([-6, -10], [4, 8], [40, 60, 60, 40], "T2", "T3", "K10", "K10")},
        "ACT": {"base_allocation_pct": 40, **two_buy([-5, -9], [4, 7], [30, 70, 60, 40], "T2", "T2", "K09", "K09")},
    }
    rules["PB08"] = {
        "DEF": {"base_allocation_pct": 20, **two_buy([-10, -18], [5, 9], [40, 60, 60, 40], "T4", "T4", "K12", "K12")},
        "STD": {"base_allocation_pct": 25, **two_buy([-9, -16], [5, 10], [40, 60, 60, 40], "T3", "T3", "K11", "K11")},
        "ACT": {"base_allocation_pct": 30, **two_buy([-8, -14], [4, 9], [30, 70, 60, 40], "T3", "T2", "K10", "K10")},
    }
    rules["PB09"] = {
        "DEF": sell_only(8, "T3", "K11", "K11", 15, 22),
        "STD": sell_only(7, "T2", "K10", "K10", 20, 20),
        "ACT": sell_only(6, "T2", "K09", "K09", 25, 18),
    }
    rules["PB10"] = {
        "DEF": {"base_allocation_pct": 15, **two_buy([-9, -15], [5, 9], [40, 60, 70, 30], "T4", "T4", "K12", "K12")},
        "STD": {"base_allocation_pct": 20, **two_buy([-8, -13], [4, 8], [40, 60, 60, 40], "T3", "T3", "K11", "K11")},
        "ACT": {"base_allocation_pct": 25, **two_buy([-7, -12], [4, 7], [30, 70, 60, 40], "T3", "T2", "K10", "K10")},
    }
    rules["PB11"] = {
        "DEF": sell_only(9, "T3", "K10", "K10", 5, 35),
        "STD": sell_only(8, "T2", "K09", "K10", 10, 32),
        "ACT": sell_only(7, "T2", "K08", "K09", 15, 28),
    }
    rules["PB12"] = {
        "DEF": {"base_allocation_pct": 10, **two_buy([-12, -20], [6, 12], [40, 60, 60, 40], "T4", "T4", "K12", "K12")},
        "STD": {"base_allocation_pct": 15, **two_buy([-11, -18], [5, 10], [40, 60, 60, 40], "T3", "T3", "K11", "K11")},
        "ACT": {"base_allocation_pct": 20, **two_buy([-10, -16], [4, 9], [30, 70, 60, 40], "T3", "T2", "K10", "K10")},
    }
    rules["PB13"] = {
        "DEF": sell_only(7, "T3", "K11", "K11", 10, 28),
        "STD": sell_only(6, "T2", "K10", "K10", 15, 24),
        "ACT": sell_only(5, "T2", "K09", "K09", 20, 20),
    }
    rules["PB14"] = {
        "DEF": sell_only(6, "T3", "K10", "K10", 10, 30),
        "STD": sell_only(5, "T2", "K09", "K10", 15, 26),
        "ACT": sell_only(4, "T2", "K08", "K09", 20, 22),
    }
    rules["PB15"] = {
        "DEF": safe_sell(10, 10, "T4", 25),
        "STD": safe_sell(15, 9, "T3", 22),
        "ACT": safe_sell(20, 8, "T3", 18),
    }
    rules["PB16"] = {
        "DEF": safe_sell(5, 12, "T4", 30),
        "STD": safe_sell(10, 10, "T3", 25),
        "ACT": safe_sell(15, 9, "T3", 20),
    }
    return rules


def _pick_behavior(regime_id: str, terminal_idx: int) -> str:
    candidates = [b["behavior_id"] for b in BEHAVIOR_FAMILIES if regime_id in b["regimes"]]
    if not candidates:
        candidates = ["PB01"]
    return candidates[terminal_idx % len(candidates)]


def build_scenario_tree() -> Dict[str, Any]:
    subs_per_regime = _distribute_extra(SUB_COUNT, REGIME_COUNT, SUB_COUNT // REGIME_COUNT)
    micros_per_sub = _distribute_extra(MICRO_COUNT, SUB_COUNT, MICRO_COUNT // SUB_COUNT)
    terminals_per_micro = _distribute_extra(TERMINAL_COUNT, MICRO_COUNT, TERMINAL_COUNT // MICRO_COUNT)

    terminals: List[Dict[str, Any]] = []
    sub_global = 0
    micro_global = 0
    terminal_idx = 0

    for ri, regime_id in enumerate([f"R{i}" for i in range(1, REGIME_COUNT + 1)]):
        n_subs = subs_per_regime[ri]
        for _ in range(n_subs):
            sub_global += 1
            sub_id = f"{sub_global:02d}"
            n_micros = micros_per_sub[sub_global - 1]
            for _ in range(n_micros):
                micro_global += 1
                micro_id = f"{micro_global:03d}"
                n_terms = terminals_per_micro[micro_global - 1]
                for _ in range(n_terms):
                    terminal_idx += 1
                    tid = f"T{terminal_idx:03d}"
                    behavior_id = _pick_behavior(regime_id, terminal_idx)
                    rname, tags = REGIME_META[regime_id]
                    terminals.append({
                        "regime_id": regime_id,
                        "sub_id": sub_id,
                        "micro_id": micro_id,
                        "terminal_id": tid,
                        "default_behavior_id": behavior_id,
                        "name": f"{rname} / alt-{sub_id} / mikro-{micro_id} / {tid}",
                        "description": f"{rname} terminal {tid}; behavior {behavior_id}.",
                        "classifier_tags": tags + [behavior_id.lower()],
                    })

    assert len(terminals) == TERMINAL_COUNT, len(terminals)
    return {
        "version": "v6.0.0",
        "counts": {"regimes": REGIME_COUNT, "subs": SUB_COUNT, "micros": MICRO_COUNT, "terminals": TERMINAL_COUNT},
        "terminals": terminals,
    }


def build_behavior_catalog() -> Dict[str, Any]:
    return {
        "version": "v6.0.0",
        "behaviors": [
            {
                "behavior_id": b["behavior_id"],
                "name": b["name"],
                "modules": b["modules"],
                "intent": f"Behavior family {b['behavior_id']} for regimes {','.join(b['regimes'])}",
            }
            for b in BEHAVIOR_FAMILIES
        ],
    }


def build_rulebook() -> Dict[str, Any]:
    rules = _behavior_rules()
    entries = []
    for b in BEHAVIOR_FAMILIES:
        bid = b["behavior_id"]
        for sev in ("DEF", "STD", "ACT"):
            rule = dict(rules[bid][sev])
            rule["behavior_id"] = bid
            rule["severity"] = sev
            rule["modules"] = b["modules"]
            rule["initial_base_allocation"] = True
            entries.append(rule)
    return {"version": "v6.0.0", "rules": entries}


def validate_tree(tree: Dict[str, Any]) -> None:
    terms = tree["terminals"]
    assert len(terms) == TERMINAL_COUNT
    assert len({t["terminal_id"] for t in terms}) == TERMINAL_COUNT
    assert len({t["regime_id"] for t in terms}) == REGIME_COUNT
    assert len({(t["regime_id"], t["sub_id"]) for t in terms}) == SUB_COUNT
    assert len({(t["regime_id"], t["sub_id"], t["micro_id"]) for t in terms}) == MICRO_COUNT


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tree = build_scenario_tree()
    validate_tree(tree)
    behaviors = build_behavior_catalog()
    rulebook = build_rulebook()
    (OUT / "scenario_tree_v6.json").write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "behavior_catalog_v6.json").write_text(json.dumps(behaviors, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "parameter_rulebook_v6.json").write_text(json.dumps(rulebook, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"scenario_tree: {len(tree['terminals'])} terminals")
    print(f"behavior_catalog: {len(behaviors['behaviors'])} behaviors")
    print(f"rulebook: {len(rulebook['rules'])} rules")


if __name__ == "__main__":
    main()
