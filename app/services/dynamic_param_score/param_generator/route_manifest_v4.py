"""V4 canonical shelf manifest — 10,710 main atmosphere routes (5-part clean keys)."""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, List, Sequence, Set, Tuple

from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    ASSET_SHELVES,
    STRUCTURE_SHELVES,
    VOL_SHELVES,
    clean_route_key,
    normalize_route_key,
)

# Canonical regime codes for shelf manifest (R1–R17; R18/R19 are aliases, not extra shelves).
CANONICAL_REGIME_CODES: Tuple[str, ...] = tuple(f"R{i}" for i in range(1, 18))

REGIME_ALIAS_TO_CANONICAL: Dict[str, str] = {
    "R18": "R7",
    "R19": "R10",
}

CANONICAL_RISK_CODES: Tuple[str, ...] = ("NORMAL", "DEFENSIVE")

ROUTE_MANIFEST_TOTAL = (
    len(ASSET_SHELVES)
    * len(CANONICAL_REGIME_CODES)
    * len(STRUCTURE_SHELVES)
    * len(VOL_SHELVES)
    * len(CANONICAL_RISK_CODES)
)

# User-mandated critical shelves (must never be empty in production pool).
MANDATORY_CRITICAL_ROUTES: Tuple[str, ...] = (
    "A1|R6|S2|V3|DEFENSIVE",
    "A1|R7|S2|V4|DEFENSIVE",
    "A1|R8|S2|V5|DEFENSIVE",
    "A1|R2|S3|V3|DEFENSIVE",
    "A1|R2|S1|V3|DEFENSIVE",
    "A2|R2|S3|V3|DEFENSIVE",
    "A2|R2|S3|V4|DEFENSIVE",
    "A2|R2|S1|V4|DEFENSIVE",
    "A2|R5|S1|V4|DEFENSIVE",
    "A3|R2|S3|V4|DEFENSIVE",
    "A3|R2|S1|V4|DEFENSIVE",
    "A3|R2|S1|V3|DEFENSIVE",
    "A3|R2|S2|V4|DEFENSIVE",
    "A3|R3|S1|V3|DEFENSIVE",
    "A3|R3|S3|V3|DEFENSIVE",
    "A3|R4|S3|V5|DEFENSIVE",
    "A3|R4|S1|V5|DEFENSIVE",
    "A3|R5|S2|V4|DEFENSIVE",
    "A3|R7|S2|V4|DEFENSIVE",
    "A3|R12|S2|V4|DEFENSIVE",
    "A3|R15|S3|V5|DEFENSIVE",
    "A4|R5|S4|V4|DEFENSIVE",
    "A5|R2|S3|V4|DEFENSIVE",
    "A2|R9|S3|V3|NORMAL",
)

# Controlled regime derivation for coverage seeding (never R2 balanced).
REGIME_DERIVATION_SOURCES: Dict[str, Tuple[str, ...]] = {
    "R15": ("R12", "R7", "R6"),
}

MANDATORY_ROUTE_SET: FrozenSet[str] = frozenset(MANDATORY_CRITICAL_ROUTES)

# Tier weights for profile allocation guidance (not equal 28/profile).
SHELF_TIER_WEIGHTS: Dict[str, int] = {
    "critical": 200,
    "high": 80,
    "normal": 35,
    "rare": 8,
    "minimal": 3,
}


def canonical_regime_code(code: str) -> str:
    c = str(code or "R2").upper()
    return REGIME_ALIAS_TO_CANONICAL.get(c, c)


def enumerate_shelf_routes(
    *,
    assets: Sequence[str] | None = None,
    regimes: Sequence[str] | None = None,
    structures: Sequence[str] | None = None,
    vols: Sequence[str] | None = None,
    risks: Sequence[str] | None = None,
) -> List[str]:
    """All 10,710 clean 5-part route keys."""
    a_list = list(assets or ASSET_SHELVES.keys())
    r_list = list(regimes or CANONICAL_REGIME_CODES)
    s_list = list(structures or STRUCTURE_SHELVES.keys())
    v_list = list(vols or VOL_SHELVES.keys())
    risk_list = list(risks or CANONICAL_RISK_CODES)
    out: List[str] = []
    for a in a_list:
        for r in r_list:
            for s in s_list:
                for v in v_list:
                    for risk in risk_list:
                        out.append(clean_route_key(a, r, s, v, risk))
    return out


def shelf_tier(route_key: str) -> str:
    """Classify shelf priority for weighted profile allocation."""
    parts = normalize_route_key(route_key).split("|")
    if len(parts) != 5:
        return "rare"
    a, r, s, v, risk = parts
    r = canonical_regime_code(r)

    if route_key in MANDATORY_CRITICAL_ROUTES:
        return "critical"

    if a in ("A1", "A2", "A3") and r in ("R6", "R7", "R8", "R12", "R15") and s == "S2":
        if risk == "DEFENSIVE" and v in ("V3", "V4", "V5"):
            return "critical"
        return "high"

    if a in ("A1", "A2") and r in ("R9", "R10") and s == "S3" and v in ("V3", "V4"):
        return "high"

    if a in ("A4", "A5") and r in ("R4", "R5") and v in ("V4", "V5"):
        return "high"

    if a == "A7" and r == "R1" and v == "V5":
        return "minimal"

    if a == "A6" and r in ("R16", "R17"):
        return "rare"

    if risk == "DEFENSIVE" and r in ("R6", "R7", "R8", "R12"):
        return "high"

    return "normal"


# Extended coverage audit uses this manifest (seed + acceptance single source).
EXTENDED_COVERAGE_MIN_COUNT = 100
MIN_PROFILES_PER_SHELF = 3


def extended_coverage_manifest(min_count: int = EXTENDED_COVERAGE_MIN_COUNT) -> List[str]:
    """Canonical extended route list for coverage debt / strict mode."""
    return enumerate_critical_routes(min_count=min_count)


def enumerate_critical_routes(min_count: int = 100) -> List[str]:
    """Expand mandatory + tier-critical routes to at least *min_count* shelves."""
    down_structures = frozenset({"S2", "S6", "S8"})
    up_structures = frozenset({"S3", "S7", "S9"})
    chop_structures = frozenset({"S4", "S5"})

    def _viable(route_key: str) -> bool:
        parts = route_key.split("|")
        if len(parts) != 5:
            return False
        _a, r, s, _v, _risk = parts
        if r in ("R6", "R7", "R8", "R12", "R15") and s not in down_structures:
            return False
        if r in ("R9", "R10") and s not in up_structures:
            return False
        if r in ("R4", "R5") and s not in (chop_structures | {"S1", "S4"}):
            return False
        return True

    seen: Set[str] = set(MANDATORY_CRITICAL_ROUTES)
    ordered: List[str] = list(MANDATORY_CRITICAL_ROUTES)
    for rk in enumerate_shelf_routes():
        if not _viable(rk):
            continue
        if shelf_tier(rk) in ("critical", "high") and rk not in seen:
            seen.add(rk)
            ordered.append(rk)
        if len(ordered) >= min_count:
            break
    return ordered


def route_has_budget_or_fee(route_key: str) -> bool:
    parts = (route_key or "").split("|")
    for p in parts:
        if p.startswith("B") and len(p) <= 3:
            return True
        if p.startswith("F") and len(p) <= 3:
            return True
    return False


def validate_clean_route_key(route_key: str) -> Tuple[bool, List[str]]:
    """Return (ok, error_codes)."""
    errs: List[str] = []
    raw = str(route_key or "")
    norm = normalize_route_key(raw)
    parts = norm.split("|")
    if len(parts) != 5:
        errs.append("route_key_parts_not_5")
    if route_has_budget_or_fee(raw) or route_has_budget_or_fee(norm):
        if any(p.startswith("B") for p in parts):
            errs.append("budget_in_route")
        if any(p.startswith("F") for p in parts):
            errs.append("fee_in_route")
    if len(parts) == 5:
        a, r, s, v, risk = parts
        if a not in ASSET_SHELVES:
            errs.append("invalid_asset")
        if canonical_regime_code(r) not in CANONICAL_REGIME_CODES:
            errs.append("invalid_regime")
        if s not in STRUCTURE_SHELVES:
            errs.append("invalid_structure")
        if v not in VOL_SHELVES:
            errs.append("invalid_vol")
        if risk not in CANONICAL_RISK_CODES:
            errs.append("invalid_risk")
    return (len(errs) == 0, errs)


def audit_route_manifest() -> Dict[str, object]:
    routes = enumerate_shelf_routes()
    invalid = 0
    budget_hits = 0
    fee_hits = 0
    for rk in routes:
        ok, errs = validate_clean_route_key(rk)
        if not ok:
            invalid += 1
        if "budget_in_route" in errs:
            budget_hits += 1
        if "fee_in_route" in errs:
            fee_hits += 1
    return {
        "route_manifest_total": len(routes),
        "route_key_parts": 5,
        "budget_in_route": budget_hits,
        "fee_in_route": fee_hits,
        "invalid_route_key": invalid,
        "expected_total": ROUTE_MANIFEST_TOTAL,
        "pass": (
            len(routes) == ROUTE_MANIFEST_TOTAL
            and invalid == 0
            and budget_hits == 0
            and fee_hits == 0
        ),
    }


def sibling_normal_route(defensive_route: str) -> str:
    """Map DEFENSIVE shelf to same-atmosphere NORMAL shelf for seeding."""
    parts = normalize_route_key(defensive_route).split("|")
    if len(parts) != 5:
        return defensive_route
    return "|".join([parts[0], parts[1], parts[2], parts[3], "NORMAL"])


def is_mandatory_route(route_key: str) -> bool:
    return normalize_route_key(route_key) in MANDATORY_ROUTE_SET


def derive_source_route_candidates(target_route: str) -> List[str]:
    """
    Ordered source shelves for seeding *target_route*.
    R15 uses R12/R7/R6 on same asset/structure/vol — never R2.
    """
    parts = normalize_route_key(target_route).split("|")
    if len(parts) != 5:
        return []
    asset, regime, structure, vol, risk = parts
    candidates: List[str] = []
    seen: Set[str] = set()

    def _add(route: str) -> None:
        rk = normalize_route_key(route)
        if rk and rk not in seen:
            seen.add(rk)
            candidates.append(rk)

    _add(sibling_normal_route(target_route))
    _add(target_route.replace(f"|{risk}|", "|NORMAL|") if risk != "NORMAL" else target_route)

    for src_regime in REGIME_DERIVATION_SOURCES.get(regime, ()):
        _add(f"{asset}|{src_regime}|{structure}|{vol}|{risk}")
        _add(f"{asset}|{src_regime}|{structure}|{vol}|NORMAL")

    for src_regime in REGIME_DERIVATION_SOURCES.get(regime, ()):
        prefix = f"{asset}|{src_regime}|{structure}|"
        for alt_vol in VOL_SHELVES:
            _add(f"{prefix}{alt_vol}|{risk}")
            _add(f"{prefix}{alt_vol}|NORMAL")

    prefix = f"{asset}|{regime}|{structure}|"
    for alt_vol in VOL_SHELVES:
        _add(f"{prefix}{alt_vol}|{risk}")
        _add(f"{prefix}{alt_vol}|NORMAL")

    return [c for c in candidates if c != normalize_route_key(target_route)]


def profiles_per_shelf_target(route_key: str, pool_total: int = 300_000) -> int:
    """Weighted target profile count for a shelf (guidance, not hard cap)."""
    tier = shelf_tier(route_key)
    weight = SHELF_TIER_WEIGHTS.get(tier, 35)
    total_weight = sum(
        SHELF_TIER_WEIGHTS.get(shelf_tier(rk), 35) for rk in enumerate_shelf_routes()
    )
    return max(1, int(pool_total * weight / max(total_weight, 1)))
