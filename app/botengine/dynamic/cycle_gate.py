"""
Dynamic Mode — Cycle-Entry Risk Gate ("yeni turu riskte beklet").

When a NEW cycle (tur) is about to begin under Dynamic Mode (cycle_id >= 2),
this gate decides whether to ENTER (let the bot deploy / accumulate normally) or
HOLD (defer pushing FRESH quote into the market until near-term downside risk
subsides — "don't open a fresh tur into a falling knife").

What it does / does NOT do
--------------------------
* HOLD only withholds NEW buy deployment at the cycle boundary
  (`initial_allocation`, `trail_buy_grid`). It NEVER liquidates, NEVER blocks
  de-risking (sells / profit-exit) and NEVER blocks a cycle-closing re-entry
  buy. Worst case it makes the bot sit in its current position a bit longer —
  it fails toward *inaction*, never toward a forced bad trade.
* It respects the immutable-snapshot principle (DYNAMIC_MODE_TECHNICAL §4.2):
  the gate arms ONLY before the cycle has engaged any fresh buy. Once a buy goes
  through (cycle ENGAGED) the DCA plan runs to completion without re-holding;
  the gate re-arms at the NEXT cycle boundary.
* Hysteresis: a hold STARTS at `HOLD_ON` risk and RELEASES only when risk falls
  to `HOLD_OFF` and stays there for `RELEASE_CONFIRM` consecutive checks
  (anti-flap). A `MAX_HOLD_SEC` ceiling guarantees the bot never freezes forever
  — after the ceiling it releases defensively with a logged reason.
* Fail-safe: any error / stale data / missing features → NOT holding (the bot
  behaves exactly as if the gate were off).

Risk model (0..1, higher = more near-term downside danger)
----------------------------------------------------------
A weighted blend of normalized sub-signals. Direction-agnostic volatility/flow
signals are gated by a soft `bearish` factor so a calm range or an up-trend with
high churn does NOT trigger a hold — only *downside* danger does.

    s_fast    last CLOSED 5m bar drop      (falling knife)         w=0.30
    s_regime  regime defensiveness         (DUMP / TRENDING_DOWN)  w=0.24
    s_mom     bearish momentum             (RSI low AND slope<0)   w=0.14
    s_dvol    realized vol (×bearish)      (chaotic tape)          w=0.12
    s_volz    volume z-score (×bearish)    (capitulation/panic)    w=0.08
    s_spread  spread blow-out              (liquidity stress)      w=0.07
    s_wick    lower-wick/body (×bearish)   (instability)           w=0.05

Everything here is a pure function of features + the persisted hold state; the
caller owns persistence and the (cheap, cached) feature fetch.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.botengine.dynamic import regime as reg

logger = logging.getLogger(__name__)


# ---- Tunables (system-defined; env-overridable for ops, NOT per-user) -------

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("cycle_gate: invalid %s=%r — using %s", name, raw, default)
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# Master switch. ON by default (operator asked for risk-based cycle holding).
HOLD_ENABLED = _env_flag("DYN_CYCLE_HOLD_ENABLED", True)

# Hysteresis band on the 0..1 risk score.
HOLD_ON = _env_float("DYN_CYCLE_HOLD_ON", 0.62)   # start holding at/above this
HOLD_OFF = _env_float("DYN_CYCLE_HOLD_OFF", 0.42)  # eligible to release at/below
# Consecutive low-risk checks required before actually releasing (anti-flap).
RELEASE_CONFIRM = int(_env_float("DYN_CYCLE_HOLD_RELEASE_CONFIRM", 2))
# Never freeze forever: release defensively after this many seconds held.
MAX_HOLD_SEC = _env_float("DYN_CYCLE_HOLD_MAX_SEC", 86400.0)  # 24h
# While holding, re-check this often (orchestrator clamps next_wake to this).
RECHECK_SEC = _env_float("DYN_CYCLE_HOLD_RECHECK_SEC", 30.0)

# Sub-signal scale anchors (denominators chosen so a "textbook" bad reading ≈1).
FAST_DROP_FULL_PCT = 4.0     # a -4% closed 5m bar → s_fast = 1.0
RV_BASE_PCT = 0.8            # realized vol below this contributes ~0
RV_SPAN_PCT = 2.2           # realized vol RV_BASE+SPAN → 1.0
VOLZ_BASE = 1.0             # z below this contributes ~0
VOLZ_SPAN = 3.0            # z = base+span → 1.0
SPREAD_BASE_PCT = 0.05      # 5 bps → 0
SPREAD_SPAN_PCT = 0.45     # 50 bps → 1.0
WICK_BASE = 1.0            # wick/body ratio below this → 0
WICK_SPAN = 3.0           # ratio base+span → 1.0
RSI_BEARISH_REF = 45.0     # RSI below this (with slope<0) starts to count

# Weights (sum = 1.0).
W_FAST = 0.30
W_REGIME = 0.24
W_MOM = 0.14
W_DVOL = 0.12
W_VOLZ = 0.08
W_SPREAD = 0.07
W_WICK = 0.05

# Per-regime structural defensiveness (s_regime base before confidence scaling).
_REGIME_RISK = {
    reg.DUMP_RISK: 1.0,
    reg.TRENDING_DOWN: 0.85,
    reg.HIGH_VOL_RANGING: 0.35,
    reg.BREAKOUT: 0.25,
    reg.SQUEEZE: 0.15,
    reg.LOW_VOL_RANGING: 0.0,
    reg.TRENDING_UP: 0.0,
    reg.UNKNOWN: 0.2,
}

FIRST_DYNAMIC_CYCLE_ID = 2  # mirrors cycle_manager; hold only on dynamic cycles


def _clamp01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _f(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


@dataclass
class CycleGateVerdict:
    """Result of one gate evaluation."""

    holding: bool
    risk_score: float
    regime: str
    reasons: List[str] = field(default_factory=list)
    breakdown: Dict[str, float] = field(default_factory=dict)
    clear_hint: str = ""
    released_reason: str = ""  # set on the eval where a hold transitions off

    def to_dict(self) -> Dict[str, Any]:
        return {
            "holding": self.holding,
            "risk_score": round(self.risk_score, 4),
            "regime": self.regime,
            "reasons": list(self.reasons),
            "breakdown": {k: round(v, 4) for k, v in self.breakdown.items()},
            "clear_hint": self.clear_hint,
            "released_reason": self.released_reason,
        }


def _bearish_factor(
    slope: Optional[float], ret5: Optional[float], regime: str
) -> float:
    """Soft 0..1 indicator that the tape is bearish — used to gate
    direction-agnostic volatility/flow signals so churn in an up-trend or calm
    range does NOT manufacture a hold."""
    b = 0.0
    if slope is not None and slope < 0:
        b += 0.45 * _clamp01(-slope / 1.0)  # -1%/bar 1h slope saturates
    if ret5 is not None and ret5 < 0:
        b += 0.30 * _clamp01(-ret5 / 2.0)   # -2% 5m bar saturates
    if regime in (reg.DUMP_RISK, reg.TRENDING_DOWN):
        b += 0.35
    elif regime == reg.HIGH_VOL_RANGING:
        b += 0.15
    return _clamp01(b)


def compute_risk(
    features: Dict[str, Any],
    regime: str,
    regime_confidence: float = 0.6,
) -> CycleGateVerdict:
    """Pure near-term downside-risk score from a MarketFeatures dict.

    Returns a verdict with `holding=False` (caller's state machine decides the
    actual hold transition); only the risk_score / breakdown / reasons are
    authoritative here.
    """
    atr = _f(features.get("atr_pct_5m"))
    rv = _f(features.get("realized_vol_5m"))
    ret5 = _f(features.get("ret_5m_last"))
    rsi5 = _f(features.get("rsi_5m"))
    rsi1h = _f(features.get("rsi_1h"))
    slope = _f(features.get("ema_slope_1h_pct"))
    volz = _f(features.get("volume_zscore_5m"))
    spread = _f(features.get("spread_pct"))
    wick = _f(features.get("wick_body_ratio_5m"))

    bearish = _bearish_factor(slope, ret5, regime)

    # --- sub-signals (each 0..1) ---
    s_fast = _clamp01(-(ret5 or 0.0) / FAST_DROP_FULL_PCT) if ret5 is not None else 0.0

    s_regime = _REGIME_RISK.get(regime, 0.2)
    if regime in (reg.TRENDING_DOWN, reg.DUMP_RISK):
        # scale by how confident we are it's really a downtrend
        s_regime *= 0.6 + 0.4 * _clamp01(regime_confidence)

    # bearish momentum: RSI pressing low WHILE 1h slope is negative. An oversold
    # print that is bouncing (ret5>0) is discounted — that's a recovery, not a knife.
    rsi_min = min([r for r in (rsi5, rsi1h) if r is not None], default=None)
    s_mom = 0.0
    if rsi_min is not None and slope is not None and slope < 0:
        s_mom = _clamp01((RSI_BEARISH_REF - rsi_min) / RSI_BEARISH_REF)
        if ret5 is not None and ret5 > 0:
            s_mom *= 0.5  # already bouncing → halve

    s_dvol = (
        _clamp01((rv - RV_BASE_PCT) / RV_SPAN_PCT) * bearish if rv is not None else 0.0
    )
    s_volz = (
        _clamp01((volz - VOLZ_BASE) / VOLZ_SPAN) * bearish
        if volz is not None
        else 0.0
    )
    s_spread = (
        _clamp01((spread - SPREAD_BASE_PCT) / SPREAD_SPAN_PCT)
        if spread is not None
        else 0.0
    )
    s_wick = (
        _clamp01((wick - WICK_BASE) / WICK_SPAN) * bearish if wick is not None else 0.0
    )

    risk = (
        W_FAST * s_fast
        + W_REGIME * s_regime
        + W_MOM * s_mom
        + W_DVOL * s_dvol
        + W_VOLZ * s_volz
        + W_SPREAD * s_spread
        + W_WICK * s_wick
    )
    risk = _clamp01(risk)

    breakdown = {
        "s_fast": s_fast,
        "s_regime": s_regime,
        "s_mom": s_mom,
        "s_dvol": s_dvol,
        "s_volz": s_volz,
        "s_spread": s_spread,
        "s_wick": s_wick,
        "bearish": bearish,
        "atr_pct_5m": atr if atr is not None else 0.0,
    }

    reasons: List[str] = []
    if s_fast >= 0.5:
        reasons.append(f"hızlı 5m düşüş ret5m={ret5:.2f}%")
    if regime in (reg.DUMP_RISK, reg.TRENDING_DOWN):
        reasons.append(f"savunmacı rejim={regime}")
    if s_mom >= 0.4:
        reasons.append(f"zayıf momentum rsi={rsi_min:.0f} slope={slope:.2f}")
    if s_volz >= 0.4:
        reasons.append(f"hacim paniği z={volz:.1f}")
    if s_spread >= 0.4:
        reasons.append(f"likidite stresi spread={spread:.3f}%")

    # what would have to improve to clear
    clear_bits = []
    if s_fast >= 0.4 or (ret5 is not None and ret5 < 0):
        clear_bits.append("fiyat sabitlenmeli")
    if regime in (reg.DUMP_RISK, reg.TRENDING_DOWN):
        clear_bits.append("rejim savunmadan çıkmalı")
    if s_volz >= 0.4:
        clear_bits.append("panik hacmi geçmeli")
    clear_hint = ", ".join(clear_bits) or "risk skoru düşmeli"

    return CycleGateVerdict(
        holding=False,
        risk_score=risk,
        regime=regime,
        reasons=reasons,
        breakdown=breakdown,
        clear_hint=clear_hint,
    )


# ---- Hold state machine -----------------------------------------------------


def _has_fresh_buy_capacity(state: Dict[str, Any], cfg_dict: Dict[str, Any]) -> bool:
    """Is there anything to actually withhold? (buy grids exist AND the DCA cap
    is not already exhausted AND there is quote to deploy). If not, a hold would
    be pointless — we skip it so the gate never blocks a cycle it can't help."""
    buy_grids = cfg_dict.get("buy_grids") or []
    if not buy_grids:
        return False
    try:
        mbl = int(cfg_dict.get("max_buy_levels") or 1)
    except (TypeError, ValueError):
        mbl = 1
    fired = sum(1 for x in (state.get("buy_grid_fired") or []) if x)
    if fired >= mbl:
        return False
    quote = _f(state.get("quote_balance"))
    if quote is not None and quote <= 0:
        # cycle 1 hasn't allocated yet → quote_balance may be 0 in state; allow.
        if state.get("initial_allocation_done"):
            return False
    return True


def is_holding(state: Dict[str, Any]) -> bool:
    h = state.get("_dynamic_cycle_hold")
    return bool(isinstance(h, dict) and h.get("active"))


def cycle_engaged(state: Dict[str, Any]) -> bool:
    return bool(state.get("_dynamic_cycle_engaged"))


def mark_engaged(state: Dict[str, Any]) -> None:
    """Called once a fresh buy is allowed through: the cycle is now committed to
    its DCA plan; do not re-hold until the next cycle boundary."""
    state["_dynamic_cycle_engaged"] = True
    h = state.get("_dynamic_cycle_hold")
    if isinstance(h, dict) and h.get("active"):
        h["active"] = False
        h["released_reason"] = "cycle_engaged"


def reset_for_new_cycle(state: Dict[str, Any]) -> None:
    """Called from cycle_reset_after_fill: a brand-new tur is unengaged."""
    state.pop("_dynamic_cycle_engaged", None)


def evaluate(
    features: Dict[str, Any],
    regime: str,
    regime_confidence: float,
    state: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    now_ms: Optional[int] = None,
) -> CycleGateVerdict:
    """Advance the hold state machine for one evaluation and persist it into
    `state['_dynamic_cycle_hold']`. Returns the verdict (with `holding` set to
    the post-transition state). Pure aside from writing that one state key.

    Caller contract: only call at/while a cycle is UNENGAGED (cycle boundary).
    Once engaged, the orchestrator stops calling this for the cycle.
    """
    now_ms = now_ms or int(time.time() * 1000)
    cycle_id = int(state.get("cycle_id") or 1)
    prev = state.get("_dynamic_cycle_hold") if isinstance(
        state.get("_dynamic_cycle_hold"), dict
    ) else None

    v = compute_risk(features, regime, regime_confidence)

    # Global disable / not a dynamic cycle / nothing to protect → never hold.
    if (
        not HOLD_ENABLED
        or cycle_id < FIRST_DYNAMIC_CYCLE_ID
        or cycle_engaged(state)
        or not _has_fresh_buy_capacity(state, cfg_dict)
    ):
        if prev and prev.get("active"):
            v.released_reason = "not_applicable"
        state["_dynamic_cycle_hold"] = {
            "active": False,
            "risk_score": v.risk_score,
            "regime": regime,
            "last_eval_ms": now_ms,
        }
        v.holding = False
        return v

    was_active = bool(prev and prev.get("active"))

    if was_active:
        since_ms = int(prev.get("since_ms") or now_ms)
        held_sec = max(0.0, (now_ms - since_ms) / 1000.0)
        release_streak = int(prev.get("release_streak") or 0)

        if held_sec >= MAX_HOLD_SEC:
            v.holding = False
            v.released_reason = "max_hold_reached"
            v.reasons.append(
                f"maksimum bekleme süresi aşıldı ({held_sec / 3600.0:.1f}sa) — "
                f"savunmacı girişe izin veriliyor"
            )
            state["_dynamic_cycle_hold"] = {
                "active": False,
                "risk_score": v.risk_score,
                "regime": regime,
                "since_ms": since_ms,
                "released_reason": "max_hold_reached",
                "last_eval_ms": now_ms,
            }
            return v

        if v.risk_score <= HOLD_OFF:
            release_streak += 1
            if release_streak >= RELEASE_CONFIRM:
                v.holding = False
                v.released_reason = "risk_cleared"
                v.reasons.append("risk geçti — yeni tur serbest")
                state["_dynamic_cycle_hold"] = {
                    "active": False,
                    "risk_score": v.risk_score,
                    "regime": regime,
                    "since_ms": since_ms,
                    "released_reason": "risk_cleared",
                    "last_eval_ms": now_ms,
                }
                return v
        else:
            release_streak = 0

        # stay held
        v.holding = True
        state["_dynamic_cycle_hold"] = {
            "active": True,
            "since_ms": since_ms,
            "started_cycle": int(prev.get("started_cycle") or cycle_id),
            "risk_score": v.risk_score,
            "regime": regime,
            "reasons": v.reasons[:6],
            "breakdown": v.to_dict()["breakdown"],
            "clear_hint": v.clear_hint,
            "release_streak": release_streak,
            "held_sec": round(held_sec, 1),
            "last_eval_ms": now_ms,
        }
        return v

    # not currently holding → start only if risk is clearly high
    if v.risk_score >= HOLD_ON:
        v.holding = True
        state["_dynamic_cycle_hold"] = {
            "active": True,
            "since_ms": now_ms,
            "started_cycle": cycle_id,
            "risk_score": v.risk_score,
            "regime": regime,
            "reasons": v.reasons[:6],
            "breakdown": v.to_dict()["breakdown"],
            "clear_hint": v.clear_hint,
            "release_streak": 0,
            "held_sec": 0.0,
            "last_eval_ms": now_ms,
        }
        v.reasons.insert(0, f"YENİ TUR BEKLETİLİYOR (risk={v.risk_score:.2f})")
        return v

    # not holding, risk below threshold
    state["_dynamic_cycle_hold"] = {
        "active": False,
        "risk_score": v.risk_score,
        "regime": regime,
        "last_eval_ms": now_ms,
    }
    v.holding = False
    return v


async def maintain(
    state: Dict[str, Any],
    cfg_dict: Dict[str, Any],
    price: float,
) -> CycleGateVerdict:
    """Tick-time maintenance while a hold may be active and the cycle is not yet
    engaged: collect (cached) features, re-classify regime, advance the state
    machine. Fail-safe: on any error returns a non-holding verdict and clears
    the hold so the bot proceeds normally.
    """
    try:
        from app.botengine.dynamic.features import collect_features

        symbol = (cfg_dict.get("symbol") or "").upper()
        feats = await collect_features(symbol, float(price or 0.0))
        if not feats.data_fresh:
            # stale data must never strand the bot in a hold
            if is_holding(state):
                logger.info(
                    "DYN_CYCLE_HOLD_STALE bot_id=%s — stale features, releasing hold",
                    state.get("bot_id"),
                )
            state["_dynamic_cycle_hold"] = {
                "active": False,
                "risk_score": 0.0,
                "regime": reg.UNKNOWN,
                "released_reason": "stale_data",
                "last_eval_ms": int(time.time() * 1000),
            }
            return CycleGateVerdict(
                holding=False, risk_score=0.0, regime=reg.UNKNOWN,
                released_reason="stale_data",
            )
        prev_regime_state = (state.get("dynamic_snapshot") or {}).get("regime_state")
        rr = reg.classify(feats, prev_regime_state)
        return evaluate(
            feats.to_dict(), rr.regime, rr.confidence, state, cfg_dict
        )
    except Exception as e:  # pragma: no cover - safety net
        logger.warning(
            "DYN_CYCLE_HOLD_MAINTAIN_EXC bot_id=%s err=%s — releasing hold",
            state.get("bot_id"),
            e,
        )
        state.pop("_dynamic_cycle_hold", None)
        return CycleGateVerdict(holding=False, risk_score=0.0, regime=reg.UNKNOWN)


# Actions that DEPLOY fresh quote into the market (what a hold withholds).
_FRESH_BUY_REASONS = ("initial_allocation", "trail_buy_grid")


def filter_actions(
    state: Dict[str, Any], actions: List[Dict[str, Any]]
) -> tuple:
    """If holding & unengaged, drop fresh-buy deployments; keep everything else
    (sells, profit-exit, cycle-closing re-entry). Returns (kept_actions,
    blocked_count). If not holding, marks the cycle ENGAGED the moment a fresh
    buy is allowed through so we never re-hold mid-cycle.
    """
    if not actions:
        return actions, 0
    if is_holding(state) and not cycle_engaged(state):
        kept = [a for a in actions if a.get("reason") not in _FRESH_BUY_REASONS]
        blocked = len(actions) - len(kept)
        return kept, blocked
    # not holding: a fresh buy going out commits the cycle
    if not cycle_engaged(state) and any(
        a.get("reason") in _FRESH_BUY_REASONS for a in actions
    ):
        mark_engaged(state)
    return actions, 0
