"""V5 route key and shelf ID generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from app.services.dynamic_param_score.v5.domain.dimensions import (
    DIMENSION_LABELS,
)


def compact_dimension_code(value: str) -> str:
    """A1_BTC_CORE -> A1, R3_LOW_VOL_SQUEEZE -> R3."""
    first = value.split("_")[0]
    if not first:
        raise ValueError(f"Invalid dimension value: {value}")
    return first


@dataclass(frozen=True)
class V5RouteParts:
    asset: str
    regime: str
    direction: str
    structure: str
    volatility: str
    risk: str
    liquidity: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "asset": self.asset,
            "regime": self.regime,
            "direction": self.direction,
            "structure": self.structure,
            "volatility": self.volatility,
            "risk": self.risk,
            "liquidity": self.liquidity,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "V5RouteParts":
        return cls(
            asset=d["asset"],
            regime=d["regime"],
            direction=d["direction"],
            structure=d["structure"],
            volatility=d["volatility"],
            risk=d["risk"],
            liquidity=d["liquidity"],
        )


def make_route_key(parts: V5RouteParts) -> str:
    return "|".join(
        [
            compact_dimension_code(parts.asset),
            compact_dimension_code(parts.regime),
            compact_dimension_code(parts.direction),
            compact_dimension_code(parts.structure),
            compact_dimension_code(parts.volatility),
            compact_dimension_code(parts.risk),
            compact_dimension_code(parts.liquidity),
        ]
    )


def make_shelf_id(parts: V5RouteParts) -> str:
    codes = [
        compact_dimension_code(parts.asset),
        compact_dimension_code(parts.regime),
        compact_dimension_code(parts.direction),
        compact_dimension_code(parts.structure),
        compact_dimension_code(parts.volatility),
        compact_dimension_code(parts.risk),
        compact_dimension_code(parts.liquidity),
    ]
    return f"DPLV5_{'_'.join(codes)}"


def make_scenario_title(parts: V5RouteParts) -> str:
    labels = [
        DIMENSION_LABELS.get(parts.asset, parts.asset),
        DIMENSION_LABELS.get(parts.regime, parts.regime),
        DIMENSION_LABELS.get(parts.direction, parts.direction),
        DIMENSION_LABELS.get(parts.structure, parts.structure),
        DIMENSION_LABELS.get(parts.volatility, parts.volatility),
        DIMENSION_LABELS.get(parts.risk, parts.risk),
        DIMENSION_LABELS.get(parts.liquidity, parts.liquidity),
    ]
    return " · ".join(labels)


def parse_route_key(route_key: str) -> V5RouteParts:
    """Parse A1|R3|D2|S2|V2|K1|L1 into V5RouteParts using dimension lookup."""
    from app.services.dynamic_param_score.v5.domain.dimensions import (
        ASSET_CLASSES,
        DIRECTIONS,
        LIQUIDITY_COSTS,
        REGIMES,
        RISK_POSTURES,
        STRUCTURES,
        VOLATILITIES,
    )

    parts = route_key.split("|")
    if len(parts) != 7:
        raise ValueError(f"Invalid route key: {route_key}")

    def _find(pool: tuple, code: str) -> str:
        for item in pool:
            if item.startswith(code + "_"):
                return item
        raise ValueError(f"Unknown code {code} in route {route_key}")

    return V5RouteParts(
        asset=_find(ASSET_CLASSES, parts[0]),
        regime=_find(REGIMES, parts[1]),
        direction=_find(DIRECTIONS, parts[2]),
        structure=_find(STRUCTURES, parts[3]),
        volatility=_find(VOLATILITIES, parts[4]),
        risk=_find(RISK_POSTURES, parts[5]),
        liquidity=_find(LIQUIDITY_COSTS, parts[6]),
    )
