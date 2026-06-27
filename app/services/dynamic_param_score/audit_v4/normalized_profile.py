"""Normalized V4 profile audit record — single schema for pool scan."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.services.dynamic_param_score.audit_v4.auditor import _profile_dict
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import normalize_route_key
from app.services.dynamic_param_score.param_pool.models import ParamTemplate

SOURCE_SQLITE = "data/param_pool/v4/param_pool_v4.sqlite"


@dataclass
class AuditViolation:
    severity: str
    code: str
    message: str = ""
    route_key: str = ""
    profile_id: str = ""
    source_file: str = SOURCE_SQLITE
    expected: Any = None
    actual: Any = None
    fix_applied: bool = False
    fix_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedParamProfileAuditRecord:
    profile_id: str
    source_file: str
    asset_key: str
    regime_key: str
    structure_key: str
    volatility_key: str
    risk_key: str
    route_key: str
    declared_route_key: str = ""
    indexed_route_key: str = ""
    source_type: str = "exact"
    fallback_source_route: str = ""
    derived_from_profile_id: str = ""
    grid_count_sell: int = 0
    grid_count_buy: int = 0
    sell_grid_levels_pct: List[float] = field(default_factory=list)
    buy_grid_levels_pct: List[float] = field(default_factory=list)
    sell_distribution_pct: List[float] = field(default_factory=list)
    buy_distribution_pct: List[float] = field(default_factory=list)
    target_base_pct: Optional[float] = None
    target_quote_pct: Optional[float] = None
    max_base_exposure_pct: Optional[float] = None
    sell_trailing_pct: Optional[float] = None
    buy_trailing_pct: Optional[float] = None
    min_order_usdt: Optional[float] = None
    validity: str = "valid"
    violations: List[AuditViolation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["violations"] = [v.to_dict() if isinstance(v, AuditViolation) else v for v in self.violations]
        return d


def normalize_template(
    template: ParamTemplate,
    *,
    source_file: str = SOURCE_SQLITE,
) -> NormalizedParamProfileAuditRecord:
    p = _profile_dict(template)
    rk = normalize_route_key(str(p.get("route_key") or ""))
    parts = rk.split("|") if rk else ["", "", "", "", ""]
    while len(parts) < 5:
        parts.append("")

    method = str(p.get("derivation_regime") or p.get("seed_derivation") or "")
    source_type = "exact"
    if "derive" in method.lower() or "clone" in method.lower():
        source_type = "derived"
    elif "generated" in method.lower():
        source_type = "generated"

    base = float(p.get("base_alloc_frac") or 0.5)
    return NormalizedParamProfileAuditRecord(
        profile_id=str(p.get("profile_id") or template.template_key),
        source_file=source_file,
        asset_key=parts[0],
        regime_key=parts[1],
        structure_key=parts[2],
        volatility_key=parts[3],
        risk_key=parts[4],
        route_key=rk,
        declared_route_key=rk,
        source_type=source_type,
        derived_from_profile_id=str(p.get("derived_from_template_key") or ""),
        grid_count_buy=int(p.get("buy_grid_count") or 0),
        grid_count_sell=int(p.get("sell_grid_count") or 0),
        buy_grid_levels_pct=[float(x) for x in (p.get("buy_grid_ladder_pcts") or p.get("buy_grid_pcts") or [])],
        sell_grid_levels_pct=[float(x) for x in (p.get("sell_grid_ladder_pcts") or p.get("sell_grid_pcts") or [])],
        buy_distribution_pct=[float(x) for x in (p.get("buy_distribution") or [])],
        sell_distribution_pct=[float(x) for x in (p.get("sell_distribution") or [])],
        target_base_pct=round(base * 100, 2),
        target_quote_pct=round((1.0 - base) * 100, 2),
        max_base_exposure_pct=(
            round(float(p.get("max_base_exposure_frac")) * 100, 2)
            if p.get("max_base_exposure_frac") is not None
            else None
        ),
        buy_trailing_pct=float(p.get("buy_trailing_pct") or p.get("trailing_pct") or 0) or None,
        sell_trailing_pct=float(p.get("sell_trailing_pct") or 0) or None,
    )


def profile_id_route_mismatch(record: NormalizedParamProfileAuditRecord) -> Optional[AuditViolation]:
    """Detect profile_id vs route_key metadata mismatch."""
    pid = record.profile_id.upper()
    rk = record.route_key.upper()
    if not rk or not pid.startswith("DPLV4_"):
        return None
    for token in (record.asset_key, record.regime_key, record.structure_key, record.volatility_key):
        if token and token not in pid:
            return AuditViolation(
                severity="MAJOR",
                code="profile_id_route_mismatch",
                message=f"profile_id missing route token {token}",
                route_key=record.route_key,
                profile_id=record.profile_id,
            )
    if record.risk_key and record.risk_key not in pid and "DEFENSIVE" not in pid and record.risk_key == "DEFENSIVE":
        return AuditViolation(
            severity="MAJOR",
            code="profile_id_risk_mismatch",
            message="DEFENSIVE route but profile_id lacks DEFENSIVE",
            route_key=record.route_key,
            profile_id=record.profile_id,
        )
    return None
