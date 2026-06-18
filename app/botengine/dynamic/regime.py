"""
Market regime classifier with hysteresis.

Outputs one of:
    LOW_VOL_RANGING      - sakin, ideal grid ortamı
    HIGH_VOL_RANGING     - chop / tuzaklı yatay (yüksek vol, düşük trend)
    TRENDING_UP          - güçlü yukarı trend
    TRENDING_DOWN        - güçlü aşağı trend (DCA'in en tehlikeli rejimi)
    SQUEEZE              - tarihi dar BBW, breakout beklentisi
    BREAKOUT             - BBW patlaması + hacim spike
    DUMP_RISK            - flash crash / panik proxy

Hysteresis rule:
  * A different regime is only accepted if the new regime has been "winning"
    for at least MIN_DWELL_TICKS consecutive calls. This prevents one-shot
    flip-flop between e.g. RANGING/TRENDING when ADX hovers around 25.

Why this matters: regime drives the suggestion engine. Flipping regimes per
tick = parameter spam = order spam. We must NOT flip on noise.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.botengine.dynamic.features import MarketFeatures


# Regime constants — string enum-like
LOW_VOL_RANGING = "LOW_VOL_RANGING"
HIGH_VOL_RANGING = "HIGH_VOL_RANGING"
TRENDING_UP = "TRENDING_UP"
TRENDING_DOWN = "TRENDING_DOWN"
SQUEEZE = "SQUEEZE"
BREAKOUT = "BREAKOUT"
DUMP_RISK = "DUMP_RISK"
UNKNOWN = "UNKNOWN"

ALL_REGIMES = (
    LOW_VOL_RANGING,
    HIGH_VOL_RANGING,
    TRENDING_UP,
    TRENDING_DOWN,
    SQUEEZE,
    BREAKOUT,
    DUMP_RISK,
    UNKNOWN,
)

# Hysteresis: a new regime must be the raw classification for at least this
# many cycle-starts before we switch. Since regime runs at cycle start (not per
# tick), 1 here is already conservative — but we keep the mechanism for cases
# where Dynamic Mode might be evaluated more often.
MIN_DWELL_CYCLES = 1


# ---- Thresholds (system-defined, NOT user-tunable) -------------------------
ADX_TRENDING = 25.0  # ADX above this → trend
ADX_RANGING = 20.0  # ADX below this → ranging
ATR_HIGH_PCT = 1.5  # ATR% above this → "high vol"
ATR_LOW_PCT = 0.4  # ATR% below this → "low vol"
BBW_SQUEEZE = 2.5  # BBW below this on 1h → squeeze
VOLUME_Z_SPIKE = 2.0  # vol z-score above this → volume spike
EMA_TREND_UP = 0.4  # EMA slope% above this → up bias
EMA_TREND_DOWN = -0.4  # EMA slope% below this → down bias
DUMP_DROP_PCT = -2.0  # 1h EMA slope% threshold for (slow) DUMP_RISK
DUMP_FAST_DROP_PCT = -3.0  # last CLOSED 5m bar return% → immediate flash-crash DUMP


@dataclass
class RegimeResult:
    regime: str
    raw_regime: str  # before hysteresis
    confidence: float  # 0..1
    reasons: Dict[str, Any]


def _classify_raw(f: MarketFeatures) -> RegimeResult:
    """Single-shot classification from current features. No memory."""
    reasons: Dict[str, Any] = {}

    # Defensive defaults: missing indicators → low confidence UNKNOWN
    atr = f.atr_pct_5m
    bbw = f.bbw_1h if f.bbw_1h is not None else f.bbw_5m
    adx = f.adx_1h
    slope = f.ema_slope_1h_pct
    vol_z = f.volume_zscore_5m
    ret5 = f.ret_5m_last  # last CLOSED 5m return %

    reasons.update(
        {
            "atr_pct_5m": atr,
            "bbw": bbw,
            "adx_1h": adx,
            "ema_slope_1h_pct": slope,
            "volume_z_5m": vol_z,
            "ret_5m_last": ret5,
        }
    )

    if atr is None and adx is None:
        return RegimeResult(UNKNOWN, UNKNOWN, 0.0, reasons)

    # --- DUMP_RISK: takes precedence ---
    # (a) FAST: a single closed 5m bar dropping >= DUMP_FAST_DROP_PCT is a flash
    #     crash — fire immediately, no volume confirmation (catches the case the
    #     slow 1h-slope path misses). OR
    # (b) SLOW: sustained 1h EMA downtrend AND an elevated volume z-score.
    if ret5 is not None and ret5 <= DUMP_FAST_DROP_PCT:
        reasons["dump_signal"] = f"fast_drop_5m={ret5:.2f}"
        return RegimeResult(DUMP_RISK, DUMP_RISK, 0.85, reasons)
    if (
        slope is not None
        and slope <= DUMP_DROP_PCT
        and vol_z is not None
        and vol_z >= VOLUME_Z_SPIKE
    ):
        reasons["dump_signal"] = "slope+volz"
        return RegimeResult(DUMP_RISK, DUMP_RISK, 0.85, reasons)

    # --- BREAKOUT: BBW expansion + volume spike (DIRECTION-AWARE) ---
    if bbw is not None and vol_z is not None:
        if bbw >= ATR_HIGH_PCT * 4 and vol_z >= VOLUME_Z_SPIKE:
            # A downward volatility expansion is not a bullish breakout — route
            # it to a defensive regime instead of neutral BREAKOUT (base 50%).
            direction = (
                slope if slope is not None else (ret5 if ret5 is not None else 0.0)
            )
            if direction < 0:
                reasons["breakout_signal"] = "bbw+volz(down→defensive)"
                return RegimeResult(TRENDING_DOWN, TRENDING_DOWN, 0.7, reasons)
            reasons["breakout_signal"] = "bbw+volz(up)"
            return RegimeResult(BREAKOUT, BREAKOUT, 0.7, reasons)

    # --- SQUEEZE: very narrow BBW (1h preferred, 5m fallback — symmetric w/ BREAKOUT) ---
    if bbw is not None and bbw <= BBW_SQUEEZE:
        reasons["squeeze_signal"] = bbw
        return RegimeResult(SQUEEZE, SQUEEZE, 0.6, reasons)

    # --- TRENDING vs RANGING via ADX ---
    is_trending = adx is not None and adx >= ADX_TRENDING
    is_ranging = adx is not None and adx <= ADX_RANGING

    if is_trending:
        if slope is not None and slope >= EMA_TREND_UP:
            return RegimeResult(TRENDING_UP, TRENDING_UP, _conf(adx), reasons)
        if slope is not None and slope <= EMA_TREND_DOWN:
            return RegimeResult(TRENDING_DOWN, TRENDING_DOWN, _conf(adx), reasons)
        # Trending but slope unclear → still treat as trend but lean to whichever side slope hints
        if slope is not None and slope > 0:
            return RegimeResult(TRENDING_UP, TRENDING_UP, _conf(adx) * 0.7, reasons)
        if slope is not None and slope < 0:
            return RegimeResult(TRENDING_DOWN, TRENDING_DOWN, _conf(adx) * 0.7, reasons)
        # ADX strong, slope flat — rare but treat as low-vol-ranging
        return RegimeResult(LOW_VOL_RANGING, LOW_VOL_RANGING, 0.4, reasons)

    if is_ranging:
        if atr is not None and atr >= ATR_HIGH_PCT:
            return RegimeResult(HIGH_VOL_RANGING, HIGH_VOL_RANGING, 0.7, reasons)
        if atr is not None and atr <= ATR_LOW_PCT:
            return RegimeResult(LOW_VOL_RANGING, LOW_VOL_RANGING, 0.7, reasons)
        # Mid vol ranging
        return RegimeResult(LOW_VOL_RANGING, LOW_VOL_RANGING, 0.5, reasons)

    # ADX in between 20-25: ambiguous. Lean on ATR.
    if atr is not None and atr >= ATR_HIGH_PCT:
        return RegimeResult(HIGH_VOL_RANGING, HIGH_VOL_RANGING, 0.45, reasons)
    return RegimeResult(LOW_VOL_RANGING, LOW_VOL_RANGING, 0.4, reasons)


def _conf(adx: float) -> float:
    """Map ADX 25..50 → 0.55..0.9 confidence (capped)."""
    if adx is None:
        return 0.5
    if adx >= 50:
        return 0.9
    if adx <= 25:
        return 0.55
    return 0.55 + (adx - 25) / 25.0 * 0.35


def classify(
    f: MarketFeatures, prev_state: Optional[Dict[str, Any]] = None
) -> RegimeResult:
    """
    Hysteresis-aware classification.

    prev_state schema (lives inside dynamic_snapshot.regime_state):
        {
            "current": "TRENDING_UP",
            "candidate": "HIGH_VOL_RANGING",
            "candidate_streak": 0,
        }

    Caller persists the returned regime + updated candidate streak.
    """
    raw = _classify_raw(f)
    if not prev_state:
        return raw

    current = prev_state.get("current") or UNKNOWN
    candidate = prev_state.get("candidate") or current
    streak = int(prev_state.get("candidate_streak") or 0)

    # Same regime → no change needed
    if raw.raw_regime == current:
        return RegimeResult(current, raw.raw_regime, raw.confidence, raw.reasons)

    # Different regime → must accumulate dwell before switching
    if raw.raw_regime == candidate:
        streak += 1
    else:
        candidate = raw.raw_regime
        streak = 1

    if streak >= MIN_DWELL_CYCLES:
        return RegimeResult(raw.raw_regime, raw.raw_regime, raw.confidence, raw.reasons)

    # Not enough dwell yet — keep current regime but report the raw classification
    return RegimeResult(current, raw.raw_regime, raw.confidence * 0.5, raw.reasons)


def update_regime_state(
    prev_state: Optional[Dict[str, Any]], result: RegimeResult
) -> Dict[str, Any]:
    """Return the new regime_state dict after this classification."""
    if not prev_state:
        return {
            "current": result.regime,
            "candidate": result.raw_regime,
            "candidate_streak": 1 if result.regime == result.raw_regime else 0,
        }
    if result.regime == result.raw_regime:
        # Switch happened (or stayed)
        return {
            "current": result.regime,
            "candidate": result.raw_regime,
            "candidate_streak": 0,
        }
    # Stayed in current but candidate is something else
    candidate = prev_state.get("candidate") or result.raw_regime
    streak = int(prev_state.get("candidate_streak") or 0)
    if result.raw_regime == candidate:
        streak += 1
    else:
        candidate = result.raw_regime
        streak = 1
    return {
        "current": result.regime,
        "candidate": candidate,
        "candidate_streak": streak,
    }
