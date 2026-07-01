"""Build dplv6_profile_catalog.json — 765 terminals × 3 severities = 2295 profiles."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.services.dynamic_param_score.v6.constants import (
    PROFIT_TRIGGER_CODES,
    TRAILING_CODES,
)
from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile
from app.services.dynamic_param_score.v6.v6_profile_validator import validate_profile
from app.services.dynamic_param_score.v6.v6_quantizer import quantize_profile

_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "dynamic_param_v6"
_TREE_FILE = _DATA_DIR / "scenario_tree_v6.json"
_RULEBOOK_FILE = _DATA_DIR / "parameter_rulebook_v6.json"
_CATALOG_OUT = _DATA_DIR / "dplv6_profile_catalog.json"

EXPECTED_PROFILE_COUNT = 2295


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _rulebook_index(book: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rule in book.get("rules") or []:
        key = (str(rule["behavior_id"]), str(rule["severity"]))
        out[key] = rule
    return out


def _profile_from_terminal(
    terminal: Dict[str, Any],
    rule: Dict[str, Any],
    severity: str,
) -> V6CatalogProfile:
    regime = str(terminal["regime_id"])
    sub = str(terminal["sub_id"])
    micro = str(terminal["micro_id"])
    tid = str(terminal["terminal_id"])
    behavior = str(rule.get("behavior_id", terminal["default_behavior_id"]))

    def grids(key: str) -> List[GridLevel]:
        return [
            GridLevel(int(g["distance_pct"]), int(g["amount_pct"]))
            for g in (rule.get(key) or [])
        ]

    base = int(rule.get("base_allocation_pct", 30))
    profile_id = f"DPLV6_{regime}-{sub}-{micro}_{tid}_{behavior}_{severity}"
    scenario = ScenarioIdentity(
        regime_id=regime,
        sub_id=sub,
        micro_id=micro,
        behavior_id=behavior,
        severity=severity,  # type: ignore[arg-type]
        terminal_id=tid,
        name=str(terminal.get("name", "")),
    )
    return V6CatalogProfile(
        profile_id=profile_id,
        scenario=scenario,
        base_allocation_pct=base,
        quote_allocation_pct=100 - base,
        initial_base_allocation=bool(rule.get("initial_base_allocation", True)),
        normal_buy_enabled=bool(rule.get("normal_buy_enabled", True)),
        buy_grids=grids("buy_grids"),
        sell_grids=grids("sell_grids"),
        sell_trailing_code=str(rule.get("sell_trailing_code", "T2")),
        buy_trailing_code=str(rule.get("buy_trailing_code", "T2")),
        buyback_after_sell_enabled=bool(rule.get("buyback_after_sell_enabled", False)),
        buyback_trigger_code=str(rule.get("buyback_trigger_code", "K10")),
        buyback_trailing_code=str(rule.get("buyback_trailing_code", "T2")),
        profit_sell_after_buyback_enabled=bool(rule.get("profit_sell_after_buyback_enabled", False)),
        profit_sell_trigger_code=str(rule.get("profit_sell_trigger_code", "K10")),
        profit_sell_trailing_code=str(rule.get("profit_sell_trailing_code", "T3")),
        modules=dict(rule.get("modules") or {}),
    )


def build_catalog() -> Dict[str, Any]:
    if not _TREE_FILE.is_file():
        raise FileNotFoundError(str(_TREE_FILE))
    if not _RULEBOOK_FILE.is_file():
        raise FileNotFoundError(str(_RULEBOOK_FILE))
    tree = _load_json(_TREE_FILE)
    rule_index = _rulebook_index(_load_json(_RULEBOOK_FILE))
    terminals = tree.get("terminals") or []

    profiles: List[Dict[str, Any]] = []
    errors: List[str] = []

    for terminal in terminals:
        behavior_id = str(terminal.get("default_behavior_id", "PB01"))
        for severity in ("DEF", "STD", "ACT"):
            rule = rule_index.get((behavior_id, severity))
            if not rule:
                errors.append(f"missing_rule:{behavior_id}:{severity}")
                continue
            p = quantize_profile(_profile_from_terminal(terminal, rule, severity))
            verr = validate_profile(p)
            if verr:
                errors.append(f"{p.profile_id}:{','.join(verr)}")
                continue
            profiles.append(_profile_to_json(p))

    return {
        "version": "v6.0.0",
        "profile_count": len(profiles),
        "validation_errors": errors,
        "profiles": profiles,
    }


def _profile_to_json(p: V6CatalogProfile) -> Dict[str, Any]:
    return {
        "profile_id": p.profile_id,
        "scenario": {
            "regime_id": p.scenario.regime_id,
            "sub_id": p.scenario.sub_id,
            "micro_id": p.scenario.micro_id,
            "terminal_id": p.scenario.terminal_id,
            "behavior_id": p.scenario.behavior_id,
            "severity": p.scenario.severity,
            "name": p.scenario.name,
        },
        "base_allocation_pct": p.base_allocation_pct,
        "quote_allocation_pct": p.quote_allocation_pct,
        "normal_buy_enabled": p.normal_buy_enabled,
        "buy_grids": [{"distance_pct": g.distance_pct, "amount_pct": g.amount_pct} for g in p.buy_grids],
        "sell_grids": [{"distance_pct": g.distance_pct, "amount_pct": g.amount_pct} for g in p.sell_grids],
        "sell_trailing_code": p.sell_trailing_code,
        "buy_trailing_code": p.buy_trailing_code,
        "buyback_after_sell_enabled": p.buyback_after_sell_enabled,
        "buyback_trigger_code": p.buyback_trigger_code,
        "buyback_trailing_code": p.buyback_trailing_code,
        "profit_sell_after_buyback_enabled": p.profit_sell_after_buyback_enabled,
        "profit_sell_trigger_code": p.profit_sell_trigger_code,
        "profit_sell_trailing_code": p.profit_sell_trailing_code,
        "modules": p.modules,
    }


def assert_catalog_valid(catalog: Dict[str, Any]) -> None:
    profiles = catalog.get("profiles") or []
    if catalog.get("validation_errors"):
        raise AssertionError(f"validation_errors={len(catalog['validation_errors'])}")
    if len(profiles) != EXPECTED_PROFILE_COUNT:
        raise AssertionError(f"profile_count={len(profiles)} expected {EXPECTED_PROFILE_COUNT}")
    ids = [p["profile_id"] for p in profiles]
    if len(set(ids)) != len(ids):
        raise AssertionError("duplicate profile_id")
    for p in profiles:
        base = int(p["base_allocation_pct"])
        if base % 5 != 0:
            raise AssertionError(f"base not 5-step: {p['profile_id']}")
        if int(p["quote_allocation_pct"]) != 100 - base:
            raise AssertionError(f"quote mismatch: {p['profile_id']}")
        for side in ("buy_grids", "sell_grids"):
            grids = p.get(side) or []
            if side == "buy_grids" and not p.get("normal_buy_enabled") and grids:
                raise AssertionError(f"buy grids when disabled: {p['profile_id']}")
            total = sum(int(g["amount_pct"]) for g in grids)
            if grids and total != 100:
                raise AssertionError(f"grid sum: {p['profile_id']} {side}")
            for g in grids:
                if int(g["amount_pct"]) % 5 != 0:
                    raise AssertionError(f"amount step: {p['profile_id']}")
        for code_key in ("sell_trailing_code", "buy_trailing_code", "buyback_trailing_code", "profit_sell_trailing_code"):
            code = p.get(code_key)
            if code and code not in TRAILING_CODES:
                raise AssertionError(f"bad trailing {code_key}: {p['profile_id']}")
        for pk in ("buyback_trigger_code", "profit_sell_trigger_code"):
            code = p.get(pk)
            if code and code not in PROFIT_TRIGGER_CODES:
                raise AssertionError(f"bad profit code {pk}: {p['profile_id']}")
        if "fee" in json.dumps(p).lower():
            raise AssertionError(f"fee field in profile: {p['profile_id']}")


def main() -> None:
    catalog = build_catalog()
    assert_catalog_valid(catalog)
    _CATALOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with _CATALOG_OUT.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"Generated profiles: {catalog['profile_count']}")
    print("Validation: OK")
    print(f"Output: {_CATALOG_OUT}")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"Validation: FAILED — {e}", file=sys.stderr)
        sys.exit(1)
