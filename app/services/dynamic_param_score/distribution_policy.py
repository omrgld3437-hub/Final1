"""Risk- and market-aware grid quantity distribution policy for DPS V4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Canonical weight tuples (percent, sum=100).
TWO_GRID_NORMAL = (40, 60)
TWO_GRID_CAUTION = (35, 65)
TWO_GRID_DEFENSIVE = (30, 70)
TWO_GRID_EXTREME = (25, 75)

THREE_GRID_NORMAL = (15, 30, 55)
THREE_GRID_DEFENSIVE = (12, 28, 60)
THREE_GRID_SEVERE = (10, 25, 65)
THREE_GRID_EXTREME = (8, 22, 70)

MIN_SPREAD_TWO_GRID = 20  # forbid near-equal halves (50/50)
MIN_SPREAD_THREE_GRID = 30


@dataclass(frozen=True)
class DistributionContext:
    """Inputs for choosing and validating ladder weight distributions."""

    risk_state: str = "NORMAL"
    regime_code: str = ""
    vol_code: str = "V3"
    structure_code: str = "S2"
    liquidity_score: int = 50
    spread_score: int = 50
    btc_market_risk_score: int = 50
    fee_efficiency_score: int = 50
    volatility_score: int = 50
    drawdown_risk_score: int = 50
    lower_lows: bool = False
    higher_highs: bool = False
    regime_tag: str = "BALANCED_RANGE"
    rsi_5m: Optional[float] = None
    rsi_1h: Optional[float] = None
    fee_bad: bool = False

    @property
    def high_momentum_buy_context(self) -> bool:
        """Late momentum / breakout continuation — tighten 3-grid back-weight."""
        rc = str(self.regime_code or "").upper()
        breakout_family = rc in ("R3", "R6", "R7", "R12", "R16")
        rsi_hi = float(self.rsi_5m or 50) >= 65 or float(self.rsi_1h or 50) >= 60
        return bool(breakout_family and rsi_hi and (self.fee_bad or int(self.btc_market_risk_score or 50) >= 55))

    @property
    def liquidity_good(self) -> bool:
        return int(self.liquidity_score or 0) >= 55

    @property
    def spread_good(self) -> bool:
        return int(self.spread_score or 0) >= 55

    @property
    def btc_pressure(self) -> bool:
        return int(self.btc_market_risk_score or 50) < 45

    @property
    def moderate_defensive(self) -> bool:
        return str(self.risk_state or "").upper() in ("CAUTION", "DEFENSIVE")

    @property
    def severe_defensive(self) -> bool:
        rs = str(self.risk_state or "").upper()
        return rs == "DEFENSIVE" and (
            self.lower_lows
            or self.btc_pressure
            or str(self.vol_code or "").upper() in ("V4", "V5")
            or int(self.drawdown_risk_score or 50) < 45
        )

    @property
    def extreme_risk(self) -> bool:
        vol = str(self.vol_code or "").upper()
        return (
            vol == "V5"
            or (
                vol == "V4"
                and (
                    self.higher_highs
                    or int(self.volatility_score or 50) >= 75
                    or str(self.regime_tag or "").upper() in ("BREAKOUT_RISK", "HIGH_VOL_UNSTABLE")
                )
            )
            or int(self.liquidity_score or 50) < 40
            or int(self.spread_score or 50) < 40
        )

    @property
    def normal_range_ok(self) -> bool:
        return (
            str(self.risk_state or "").upper() == "NORMAL"
            and self.liquidity_good
            and self.spread_good
            and not self.extreme_risk
            and not self.severe_defensive
            and int(self.volatility_score or 50) < 70
        )


def distribution_context_from_mapping(data: Optional[Dict[str, Any]]) -> DistributionContext:
    if not data:
        return DistributionContext()
    return DistributionContext(
        risk_state=str(data.get("risk_state") or data.get("risk_class") or "NORMAL"),
        regime_code=str(data.get("regime_code") or ""),
        vol_code=str(data.get("vol_code") or "V3"),
        structure_code=str(data.get("structure_code") or "S2"),
        liquidity_score=int(data.get("liquidity_score") or 50),
        spread_score=int(data.get("spread_score") or 50),
        btc_market_risk_score=int(data.get("btc_market_risk_score") or 50),
        fee_efficiency_score=int(data.get("fee_efficiency_score") or 50),
        volatility_score=int(data.get("volatility_score") or 50),
        drawdown_risk_score=int(data.get("drawdown_risk_score") or 50),
        lower_lows=bool(data.get("lower_lows")),
        higher_highs=bool(data.get("higher_highs")),
        regime_tag=str(data.get("regime_tag") or data.get("regime") or "BALANCED_RANGE"),
        rsi_5m=data.get("rsi_5m"),
        rsi_1h=data.get("rsi_1h"),
        fee_bad=bool(data.get("fee_bad")),
    )


def is_insufficient_back_weight_for_high_momentum(
    buy_dist: list,
    *,
    ctx: Optional[DistributionContext] = None,
) -> bool:
    """Context-aware 3-grid check — not a blanket ban on 20/30/50."""
    if not ctx or not buy_dist or len(buy_dist) != 3:
        return False
    if not ctx.high_momentum_buy_context:
        return False
    d = _to_percent_ints(list(buy_dist)[:3])
    return d[-1] < 55 or d[0] > 15


def resolve_two_grid_weights(ctx: DistributionContext) -> Tuple[int, int]:
    """Pick 2-grid buy/sell weights for current market context. 50/50 never returned."""
    rc = str(ctx.regime_code or "").upper()
    if rc in ("R8", "R13", "R15") or int(ctx.btc_market_risk_score or 50) < 35:
        return TWO_GRID_EXTREME
    if ctx.extreme_risk:
        return TWO_GRID_EXTREME
    if ctx.severe_defensive:
        return TWO_GRID_DEFENSIVE
    if ctx.moderate_defensive:
        if ctx.lower_lows or ctx.btc_pressure or str(ctx.vol_code or "").upper() == "V4":
            return TWO_GRID_DEFENSIVE
        return TWO_GRID_CAUTION
    if rc in ("R5", "R7"):
        return TWO_GRID_DEFENSIVE if ctx.btc_pressure else TWO_GRID_NORMAL
    if int(ctx.btc_market_risk_score or 50) < 55:
        return TWO_GRID_DEFENSIVE
    if ctx.normal_range_ok:
        return TWO_GRID_NORMAL
    if str(ctx.risk_state or "").upper() in ("CAUTION", "DEFENSIVE"):
        return TWO_GRID_CAUTION
    if int(ctx.liquidity_score or 50) < 45 or int(ctx.spread_score or 50) < 45:
        return TWO_GRID_CAUTION
    return TWO_GRID_NORMAL


def resolve_three_grid_weights(ctx: DistributionContext) -> Tuple[int, int, int]:
    """Pick 3-grid back-weighted distribution."""
    if ctx.high_momentum_buy_context:
        if ctx.severe_defensive or ctx.extreme_risk:
            return THREE_GRID_SEVERE
        return THREE_GRID_DEFENSIVE if ctx.fee_bad else THREE_GRID_NORMAL
    rc = str(ctx.regime_code or "").upper()
    if rc in ("R8", "R13", "R15"):
        return THREE_GRID_SEVERE
    if ctx.extreme_risk:
        return THREE_GRID_EXTREME
    if ctx.severe_defensive:
        return THREE_GRID_SEVERE
    if ctx.moderate_defensive:
        return THREE_GRID_DEFENSIVE
    if rc in ("R5", "R7"):
        return THREE_GRID_NORMAL
    if int(ctx.btc_market_risk_score or 50) < 55:
        return THREE_GRID_DEFENSIVE
    return THREE_GRID_NORMAL


def resolve_side_distribution(
    grid_count: int,
    ctx: DistributionContext,
) -> List[int]:
    if grid_count <= 0:
        return []
    if grid_count == 1:
        return [100]
    if grid_count == 2:
        return list(resolve_two_grid_weights(ctx))
    if grid_count == 3:
        return list(resolve_three_grid_weights(ctx))
    base = 100 // grid_count
    out = [base] * grid_count
    out[-1] += 100 - sum(out)
    return out


def _to_percent_ints(dist: List) -> List[int]:
    if not dist:
        return []
    vals = [float(x) for x in dist]
    if max(vals) <= 1.0 + 1e-9:
        vals = [v * 100.0 for v in vals]
    total = sum(vals) or 100.0
    if abs(total - 100.0) > 1.0 and total > 0:
        vals = [v * 100.0 / total for v in vals]
    scaled = [int(round(v)) for v in vals]
    drift = 100 - sum(scaled)
    if drift and scaled:
        idx = max(range(len(scaled)), key=lambda i: scaled[i])
        scaled[idx] += drift
    return scaled


def is_two_grid_distribution_valid(dist: List, *, ctx: Optional[DistributionContext] = None) -> bool:
    d = _to_percent_ints(list(dist)[:2])
    if len(d) != 2:
        return False
    if abs(d[0] - 50) < 5 and abs(d[1] - 50) < 5:
        return False
    if abs(d[0] - d[1]) < MIN_SPREAD_TWO_GRID:
        return False
    if d[1] < 60:
        return False
    if d[0] > 40:
        return False
    return True


def is_three_grid_distribution_valid(dist: List, *, ctx: Optional[DistributionContext] = None) -> bool:
    d = _to_percent_ints(list(dist)[:3])
    if len(d) != 3:
        return False
    if max(d) - min(d) < MIN_SPREAD_THREE_GRID:
        return False
    # defensive / caution back-weight rules
    rs = str(ctx.risk_state or "").upper() if ctx else "DEFENSIVE"
    if rs in ("DEFENSIVE", "CAUTION"):
        if d[0] > 18:
            return False
        if d[1] > 35:
            return False
        if d[-1] < 50:
            return False
    elif d[-1] < 50:
        return False
    return True


def is_buy_distribution_valid(
    dist: List,
    *,
    grid_count: int,
    ctx: Optional[DistributionContext] = None,
) -> Tuple[bool, str]:
    if grid_count <= 0 or not dist:
        return True, ""
    if grid_count == 2:
        ok = is_two_grid_distribution_valid(dist, ctx=ctx)
        return ok, "" if ok else "INVALID_TWO_GRID_DISTRIBUTION"
    if grid_count == 3:
        ok = is_three_grid_distribution_valid(dist, ctx=ctx)
        return ok, "" if ok else "INVALID_THREE_GRID_DISTRIBUTION"
    return True, ""


def normalize_distribution_for_context(
    dist: List,
    grid_count: int,
    ctx: DistributionContext,
) -> Tuple[List[int], bool]:
    """Return policy-compliant integer percents for *grid_count* grids."""
    target = resolve_side_distribution(grid_count, ctx)
    if not dist:
        return target, True
    d = _to_percent_ints(list(dist)[:grid_count])
    if len(d) != grid_count:
        return target, True
    if grid_count == 2 and not is_two_grid_distribution_valid(d, ctx=ctx):
        return list(resolve_two_grid_weights(ctx)), True
    if grid_count == 3 and not is_three_grid_distribution_valid(d, ctx=ctx):
        return list(resolve_three_grid_weights(ctx)), True
    if abs(d[0] - 50) < 5 and grid_count == 2:
        return list(resolve_two_grid_weights(ctx)), True
    return d, False


def trim_side_distribution_for_context(
    dist: List,
    n: int,
    ctx: DistributionContext,
) -> List[int]:
    """Trim to *n* grids then re-resolve weights from market context (never slice+normalize to 50/50)."""
    if n <= 0:
        return []
    if not dist or len(_to_percent_ints(list(dist))) > n:
        return resolve_side_distribution(n, ctx)
    d = _to_percent_ints(list(dist)[:n])
    fixed, _ = normalize_distribution_for_context(d, n, ctx)
    return fixed
