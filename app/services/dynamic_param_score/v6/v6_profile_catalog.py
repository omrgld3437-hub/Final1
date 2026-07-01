"""V6 profile catalog loader."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from app.services.dynamic_param_score.v6.domain.types import GridLevel, ScenarioIdentity, V6CatalogProfile

_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "dynamic_param_v6"
_CATALOG_FILE = _DATA_DIR / "dplv6_profile_catalog.json"


def _profile_from_dict(d: Dict) -> V6CatalogProfile:
    scen = d.get("scenario") or {}
    scenario = ScenarioIdentity(
        regime_id=str(scen.get("regime_id", "R2")),
        sub_id=str(scen.get("sub_id", "01")),
        micro_id=str(scen.get("micro_id", "001")),
        behavior_id=str(scen.get("behavior_id", d.get("behavior_id", "PB01"))),
        severity=str(scen.get("severity", d.get("severity", "STD"))),  # type: ignore[arg-type]
        terminal_id=str(scen.get("terminal_id", "")),
        name=str(scen.get("name", "")),
    )

    def grids(key: str) -> List[GridLevel]:
        return [
            GridLevel(int(g["distance_pct"]), int(g["amount_pct"]))
            for g in (d.get(key) or [])
        ]

    base = int(d.get("base_allocation_pct", 30))
    return V6CatalogProfile(
        profile_id=str(d["profile_id"]),
        scenario=scenario,
        base_allocation_pct=base,
        quote_allocation_pct=int(d.get("quote_allocation_pct", 100 - base)),
        initial_base_allocation=bool(d.get("initial_base_allocation", True)),
        normal_buy_enabled=bool(d.get("normal_buy_enabled", True)),
        buy_grids=grids("buy_grids"),
        sell_grids=grids("sell_grids"),
        sell_trailing_code=str(d.get("sell_trailing_code", "T2")),
        buy_trailing_code=str(d.get("buy_trailing_code", "T2")),
        buyback_after_sell_enabled=bool(d.get("buyback_after_sell_enabled", False)),
        buyback_trigger_code=str(d.get("buyback_trigger_code", "K10")),
        buyback_trailing_code=str(d.get("buyback_trailing_code", "T2")),
        profit_sell_after_buyback_enabled=bool(d.get("profit_sell_after_buyback_enabled", False)),
        profit_sell_trigger_code=str(d.get("profit_sell_trigger_code", "K10")),
        profit_sell_trailing_code=str(d.get("profit_sell_trailing_code", "T2")),
        modules=dict(d.get("modules") or {}),
    )


def catalog_lookup_key(
    regime_id: str,
    sub_id: str,
    micro_id: str,
    terminal_id: str,
    behavior_id: str,
    severity: str,
) -> str:
    if terminal_id:
        return f"DPLV6_{regime_id}-{sub_id}-{micro_id}_{terminal_id}_{behavior_id}_{severity}"
    return f"DPLV6_{regime_id}-{sub_id}-{micro_id}_{behavior_id}_{severity}"


@lru_cache(maxsize=1)
def load_catalog() -> Dict[str, V6CatalogProfile]:
    if not _CATALOG_FILE.is_file():
        return {}
    with _CATALOG_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)
    profiles = raw.get("profiles") if isinstance(raw, dict) else raw
    if not isinstance(profiles, list):
        profiles = []
    out: Dict[str, V6CatalogProfile] = {}
    for item in profiles:
        p = _profile_from_dict(item)
        out[p.profile_id] = p
        keys = [
            catalog_lookup_key(
                p.scenario.regime_id,
                p.scenario.sub_id,
                p.scenario.micro_id,
                p.scenario.terminal_id,
                p.scenario.behavior_id,
                p.scenario.severity,
            ),
            catalog_lookup_key(
                p.scenario.regime_id,
                p.scenario.sub_id,
                p.scenario.micro_id,
                "",
                p.scenario.behavior_id,
                p.scenario.severity,
            ),
        ]
        for key in keys:
            out.setdefault(key, p)
    return out


def get_profile_by_regime_behavior(
    regime_id: str,
    behavior_id: str,
    severity: str,
) -> Optional[V6CatalogProfile]:
    """Fallback: first catalog profile for regime + behavior + severity."""
    cat = load_catalog()
    seen: set[str] = set()
    for profile in cat.values():
        if profile.profile_id in seen:
            continue
        seen.add(profile.profile_id)
        s = profile.scenario
        if s.regime_id == regime_id and s.behavior_id == behavior_id and s.severity == severity:
            return profile.copy()
    return None


def get_profile(
    regime_id: str,
    sub_id: str,
    micro_id: str,
    behavior_id: str,
    severity: str,
    *,
    terminal_id: str = "",
) -> Optional[V6CatalogProfile]:
    cat = load_catalog()
    key = catalog_lookup_key(regime_id, sub_id, micro_id, terminal_id, behavior_id, severity)
    p = cat.get(key)
    if p is None and terminal_id:
        key2 = catalog_lookup_key(regime_id, sub_id, micro_id, "", behavior_id, severity)
        p = cat.get(key2)
    return p.copy() if p else None
