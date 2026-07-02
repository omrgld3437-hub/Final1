"""V6 scenario classifier — coin-native R1..R8 (BTC does not alone set regime)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.dynamic_param_score.utils import clamp, normalize_score
from app.services.dynamic_param_score.v6.domain.types import ScenarioIdentity, V6InputContract


@dataclass
class ClassifiedScenario:
    regime_id: str
    sub_id: str
    micro_id: str
    behavior_id: str
    label: str
    sub_profile_hint: str = ""


def _crash_like(inp: V6InputContract) -> bool:
    if _r8_crash_veto(inp):
        return False

    cv = inp.crash_velocity
    dd7 = inp.drawdown_7d_pct or 0
    dd30 = inp.drawdown_30d_pct or 0
    ret1 = inp.return_1h_pct or 0
    ret4 = inp.return_4h_pct or 0
    ret24 = inp.return_24h_pct or 0
    pve = inp.price_vs_ema200_pct

    votes = 0
    if ret1 <= 0:
        votes += 1
    if ret4 < 0:
        votes += 1
    if ret24 < 0:
        votes += 1
    if pve is not None and pve < 0:
        votes += 1
    if (inp.ema20_slope or 0) < 0:
        votes += 1
    if (inp.ema50_slope or 0) < 0:
        votes += 1
    if inp.higher_highs is False:
        votes += 1
    if inp.lower_lows is True:
        votes += 1
    if (inp.rsi_1h or 100) < 45:
        votes += 1
    if dd7 >= 15 or dd30 >= 25:
        votes += 1
    if _trend_strength(inp) <= 35:
        votes += 1

    fast_crash = cv is not None and cv < -1.5 and votes >= 4
    deep_drawdown = (dd7 >= 15 or dd30 >= 25) and votes >= 5
    broad_negative = ret24 <= -8 and ret4 < 0 and votes >= 5
    severe_combo = cv is not None and cv < -2.0 and dd7 >= 15 and ret24 <= -8
    capitulation_probe = _r8_capitulation_probe(inp)
    return fast_crash or deep_drawdown or broad_negative or severe_combo or capitulation_probe


def _r8_crash_veto(inp: V6InputContract) -> bool:
    if _parabolic_overextended_pump(inp):
        return True

    blockers = 0
    if (inp.return_1h_pct or 0) > 5:
        blockers += 1
    if (inp.return_4h_pct or 0) > 15:
        blockers += 1
    if (inp.return_24h_pct or 0) > 30:
        blockers += 1
    if (inp.adx_1h or 0) > 35:
        blockers += 1
    if (inp.ema20_slope or 0) > 0:
        blockers += 1
    if (inp.ema50_slope or 0) > 0:
        blockers += 1
    if (inp.price_vs_ema200_pct or 0) > 20:
        blockers += 1
    if inp.higher_highs is True:
        blockers += 1
    if inp.lower_lows is False:
        blockers += 1
    if (inp.rsi_1h or 0) > 60:
        blockers += 1
    return blockers >= 5


def _downtrend(inp: V6InputContract) -> bool:
    if inp.lower_lows and (inp.return_24h_pct or 0) < -3:
        return True
    pve = inp.price_vs_ema200_pct
    return pve is not None and pve < -5 and (inp.adx_1h or 0) >= 18


def _volatile_vol_ok(inp: V6InputContract) -> bool:
    vp = inp.volatility_percentile or 0
    atr = inp.atr_1h_pct or 0
    return vp >= 60 or atr >= 1.2


def _range_score(inp: V6InputContract) -> int:
    score = 50.0
    if inp.bb_width is not None:
        score += normalize_score(inp.bb_width, 1.0, 6.0) * 0.25 - 12.5
    if inp.range_stability is not None:
        score += inp.range_stability * 25
    if inp.mean_reversion_score is not None:
        score += normalize_score(inp.mean_reversion_score, 0.1, 0.5) * 0.2 - 10
    if inp.adx_1h is not None and inp.adx_1h < 20:
        score += 10
    return int(clamp(score, 0, 100))


def _trend_strength(inp: V6InputContract) -> int:
    """Directional trend strength 0–100 (high = strong uptrend)."""
    score = 50.0
    pve = inp.price_vs_ema200_pct
    if pve is not None:
        score += normalize_score(pve, -5, 8) * 0.35 - 17.5
    if inp.ema20_slope is not None:
        score += normalize_score(inp.ema20_slope, -1.5, 1.5) * 0.25 - 12.5
    if inp.ema50_slope is not None:
        score += normalize_score(inp.ema50_slope, -1.0, 1.0) * 0.2 - 10
    if inp.adx_1h is not None:
        score += normalize_score(inp.adx_1h, 15, 40) * 0.2 - 10
    if inp.higher_highs:
        score += 10
    if inp.lower_lows:
        score -= 15
    return int(clamp(score, 0, 100))


def _directional_momentum(inp: V6InputContract) -> int:
    """High = strong directional momentum (not grid-neutral)."""
    score = 50.0
    rsi1 = inp.rsi_1h
    if rsi1 is not None:
        score += normalize_score(rsi1, 45, 80) * 0.35 - 17.5
    rsi5 = inp.rsi_5m
    if rsi5 is not None:
        score += normalize_score(rsi5, 45, 82) * 0.2 - 10
    if inp.roc_5m is not None:
        score += normalize_score(inp.roc_5m, 0, 4) * 0.2 - 10
    ret24 = inp.return_24h_pct or 0
    if ret24 > 4:
        score += 15
    elif ret24 > 2:
        score += 8
    elif ret24 < -4:
        score -= 15
    return int(clamp(score, 0, 100))


def _volume_quality(inp: V6InputContract) -> float:
    return float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)


def _liquid_coin(inp: V6InputContract) -> bool:
    spread = float(inp.spread_pct if inp.spread_pct is not None else 1.0)
    vq = _volume_quality(inp)
    return spread <= 0.03 and vq >= 0.45 and float(inp.volume_24h or 0) >= 1_000_000


def _clear_strong_trend(inp: V6InputContract, *, trend: int, momentum: int) -> bool:
    adx = inp.adx_1h or 0
    pve = inp.price_vs_ema200_pct or 0
    ret24 = inp.return_24h_pct or 0
    rsi1 = inp.rsi_1h or 0
    if trend >= 70:
        return True
    if momentum >= 75 and _raw_act_momentum_confirmed(inp):
        return True
    if adx >= 28 and pve >= 3 and ret24 >= 4:
        return True
    if rsi1 >= 68 and inp.higher_highs and not inp.lower_lows:
        return True
    if pve >= 3 and ret24 >= 4 and (inp.ema20_slope or 0) > 0:
        return True
    return False


def _clear_breakout(inp: V6InputContract) -> bool:
    if inp.fake_breakout_score >= 70:
        return True
    ret24 = inp.return_24h_pct or 0
    if ret24 >= 4 and inp.higher_highs and (inp.rsi_1h or 0) >= 65:
        return True
    if (inp.bb_position or 0) >= 0.75 and (inp.z_score or 0) >= 1.0 and ret24 > 2:
        return True
    return False


def _overextended(inp: V6InputContract) -> bool:
    return (
        (inp.rsi_1h or 0) >= 68
        and (inp.bb_position or 0) >= 0.70
        and (inp.z_score or 0) >= 1.0
    )


def _raw_act_momentum_confirmed(inp: V6InputContract) -> bool:
    return (
        (inp.roc_5m or 0) >= 0.5
        or (inp.return_1h_pct or 0) >= 0.7
        or (inp.return_4h_pct or 0) >= 1.5
        or (inp.ema20_slope or 0) >= 0.15
        or (inp.ema50_slope or 0) >= 0.10
    )


def _recovery_semantics_confirmed(inp: V6InputContract) -> bool:
    ret24 = inp.return_24h_pct or 0
    ret4 = inp.return_4h_pct or 0
    dd7 = inp.drawdown_7d_pct or 0
    pve = inp.price_vs_ema200_pct or 0
    previous_downtrend = (
        inp.lower_lows is True
        or ret24 <= 0
        or dd7 >= 5
        or pve <= 0.5
    )
    recovery_now = (
        ret4 > 0
        or (inp.return_1h_pct or 0) > 0
        or inp.higher_highs is True
        or (inp.ema20_slope or 0) > 0
    )
    explicit_not_recovery = (
        ret24 > 2
        and dd7 < 2
        and pve > 2
        and inp.higher_highs is True
        and inp.lower_lows is False
    )
    return previous_downtrend and recovery_now and not explicit_not_recovery


def _recovery_breakout(inp: V6InputContract) -> bool:
    return (
        (inp.return_24h_pct or 0) < -5
        and (inp.drawdown_7d_pct or 0) >= 10
        and ((inp.return_4h_pct or 0) > 1 or (inp.return_1h_pct or 0) > 0)
        and (inp.ema20_slope or 0) > 0
        and (inp.ema50_slope or 0) > 0
        and inp.higher_highs is True
        and inp.lower_lows is False
    )


def _r8_capitulation_probe(inp: V6InputContract) -> bool:
    return (
        (inp.return_24h_pct or 0) <= -40
        and (inp.drawdown_7d_pct or 0) >= 50
        and (inp.return_4h_pct or 0) > 0
        and (inp.red_pressure or 0) < 0.6
        and float(inp.spread_pct or 0) < 0.30
        and float(inp.volume_24h or 0) >= 1_000_000
    )


def _trend_cooldown(inp: V6InputContract, *, trend: int, momentum: int) -> bool:
    if not inp.higher_highs or inp.lower_lows:
        return False
    if not _liquid_coin(inp):
        return False
    if (inp.price_vs_ema200_pct or 0) < 1.5:
        return False
    if (inp.return_24h_pct or 0) < 1.5:
        return False
    if (inp.rsi_1h or 0) >= 70:
        return False
    if (inp.bb_position or 0) >= 0.75:
        return False
    if (inp.z_score or 0) >= 1.0:
        return False
    if _raw_act_momentum_confirmed(inp):
        return False
    return trend >= 62 and momentum <= 65


def _top_distribution(inp: V6InputContract) -> bool:
    top_votes = 0
    if (inp.rsi_1h or 0) >= 70:
        top_votes += 1
    if (inp.bb_position or 0) >= 0.75:
        top_votes += 1
    if (inp.z_score or 0) >= 1.0:
        top_votes += 1
    if (inp.price_vs_ema200_pct or 0) >= 6:
        top_votes += 1
    if (inp.return_24h_pct or 0) >= 5:
        top_votes += 1
    if (inp.return_4h_pct or 0) >= 2 and not _raw_act_momentum_confirmed(inp):
        top_votes += 1
    if top_votes == 0:
        return False

    confirmation = 0
    if (inp.roc_5m or 0) < 0:
        confirmation += 1
    if (inp.ema20_slope or 0) < 0:
        confirmation += 1
    if inp.higher_highs is False:
        confirmation += 1
    if (inp.volume_spike or 0) >= 2.5:
        confirmation += 1
    if (inp.mean_reversion_score or 0) >= 0.5:
        confirmation += 1
    return confirmation >= 1


def _parabolic_overextended_pump(inp: V6InputContract) -> bool:
    ret1 = inp.return_1h_pct or 0
    ret4 = inp.return_4h_pct or 0
    ret24 = inp.return_24h_pct or 0
    if ret24 < 30 or ret4 < 15 or ret1 < 5:
        return False

    votes = 0
    if (inp.price_vs_ema200_pct or 0) >= 20:
        votes += 1
    if (inp.adx_1h or 0) >= 35:
        votes += 1
    if inp.higher_highs is True:
        votes += 1
    if inp.lower_lows is False:
        votes += 1
    if (inp.atr_1h_pct or 0) >= 3:
        votes += 1
    if (inp.bb_position or 0) >= 0.80:
        votes += 1
    if (inp.z_score or 0) >= 1.2:
        votes += 1
    if (inp.rsi_1h or 0) >= 65:
        votes += 1
    if (inp.ema20_slope or 0) > 0 and (inp.ema50_slope or 0) > 0:
        votes += 1
    return votes >= 5


def _strong_trend_breakout_gate(inp: V6InputContract, *, trend: int, momentum: int) -> bool:
    adx = inp.adx_1h or 0
    pve = inp.price_vs_ema200_pct or 0
    ret4 = inp.return_4h_pct or 0
    ret24 = inp.return_24h_pct or 0
    if _clear_strong_trend(inp, trend=trend, momentum=momentum):
        return True
    if (
        adx >= 28
        and (inp.ema20_slope or 0) > 0
        and (inp.ema50_slope or 0) > 0
        and pve > 2
        and ret24 > 3
        and inp.higher_highs
        and not inp.lower_lows
    ):
        return True
    if ret4 > 1 and ret24 > 3 and trend >= 65:
        return True
    return False


def _post_breakout_cooldown(inp: V6InputContract) -> bool:
    return (
        (inp.adx_1h or 0) >= 28
        and (inp.price_vs_ema200_pct or 0) >= 3
        and (inp.return_24h_pct or 0) > 2
        and (inp.bb_position or 0) < 0.80
        and (inp.z_score or 0) < 1.20
        and ((inp.higher_highs is not True) or (inp.roc_5m or 0) < 0.5)
        and inp.lower_lows is not True
    )


def _true_volatile_range(inp: V6InputContract, *, range_sc: int) -> bool:
    if not _volatile_vol_ok(inp):
        return False
    rstab = inp.range_stability or 0
    if range_sc < 45 or rstab < 0.30:
        return False
    trend = _trend_strength(inp)
    momentum = _directional_momentum(inp)
    if _clear_strong_trend(inp, trend=trend, momentum=momentum):
        return False
    if _clear_breakout(inp):
        return False
    if inp.lower_lows and (inp.return_24h_pct or 0) < -3:
        return False
    return True


def _low_liquidity_unstable(inp: V6InputContract, *, range_sc: int) -> bool:
    spread = float(inp.spread_pct or 0)
    vq = _volume_quality(inp)
    rstab = inp.range_stability or 0
    if range_sc < 40 or rstab < 0.20:
        return True
    if spread >= 0.10 and vq < 0.40:
        return True
    if inp.zero_volume_flag and spread >= 0.15:
        return True
    return False


def _recovery_gate(inp: V6InputContract) -> bool:
    ret24 = inp.return_24h_pct or 0
    ret1 = inp.return_1h_pct or 0
    ret4 = inp.return_4h_pct or 0
    dd = inp.drawdown_7d_pct or 0
    rp = inp.red_pressure or 0
    if dd <= 3 and ret24 >= 0:
        return False
    if ret24 < -2 or dd >= 5:
        if ret1 > 0 or ret4 > 0:
            if inp.higher_highs and not inp.lower_lows and rp < 0.6:
                return True
    if ret24 > 0 and dd > 5 and (inp.rsi_1h or 50) < 72:
        return True
    return False


def _r8_recovery_restricted(inp: V6InputContract) -> bool:
    if not _crash_like(inp):
        return False
    ret24 = inp.return_24h_pct or 0
    ret1 = inp.return_1h_pct or 0
    ret4 = inp.return_4h_pct or 0
    if ret24 >= -3:
        return False
    if (ret1 > 0 or ret4 > 0) and inp.higher_highs and not inp.lower_lows:
        return (inp.red_pressure or 0) < 0.6
    return False


def _strong_uptrend(inp: V6InputContract) -> bool:
    if inp.higher_highs and (inp.return_24h_pct or 0) > 3:
        return True
    pve = inp.price_vs_ema200_pct
    return pve is not None and pve > 3 and (inp.adx_1h or 0) >= 22


def _strong_uptrend_pullback(inp: V6InputContract) -> bool:
    """Strong higher-timeframe trend, but short-term structure is pulling back."""
    if (inp.price_vs_ema200_pct or 0) < 3:
        return False
    if (inp.adx_1h or 0) < 25:
        return False
    if (inp.return_24h_pct or 0) <= 2:
        return False
    pullback_votes = 0
    if (inp.ema20_slope or 0) < 0:
        pullback_votes += 1
    if (inp.ema50_slope or 0) < 0:
        pullback_votes += 1
    if (inp.roc_5m or 0) < 0:
        pullback_votes += 1
    if inp.lower_lows:
        pullback_votes += 1
    if inp.higher_highs is False:
        pullback_votes += 1
    if (inp.bb_position or 0.5) <= 0.25:
        pullback_votes += 1
    if (inp.z_score or 0) <= -1.0:
        pullback_votes += 1
    if (inp.rsi_5m or 50) < 45:
        pullback_votes += 1
    return pullback_votes >= 4


def _upper_band_boundary(inp: V6InputContract) -> bool:
    vp = inp.volatility_percentile if inp.volatility_percentile is not None else 100
    atr = inp.atr_1h_pct or 0
    bb = inp.bb_position or 0
    z = inp.z_score or 0
    return vp < 40 and atr < 1.5 and bb > 0.80 and z > 1.3


def _uptrend_compression(inp: V6InputContract) -> bool:
    """R3 squeeze with upward bias — above EMA200, positive drift, no dump structure."""
    pve = inp.price_vs_ema200_pct
    if pve is None or pve < 0.5:
        return False
    if (inp.return_24h_pct or 0) <= 0:
        return False
    if inp.lower_lows is True:
        return False
    if (inp.ema20_slope or 0) < -0.05 or (inp.ema50_slope or 0) < -0.05:
        return False
    return not _downtrend(inp)


def _controlled_compression(inp: V6InputContract) -> bool:
    return (
        (inp.bb_width or 99) <= 1.0
        and (inp.volatility_percentile or 0) < 35
        and (inp.range_stability or 0) >= 0.30
        and inp.lower_lows is not True
        and (inp.ema20_slope or 0) >= -0.05
        and (inp.ema50_slope or 0) >= -0.05
    )


def classify_scenario(inp: V6InputContract) -> ClassifiedScenario:
    """Priority cascade: crash → downtrend → trend/breakout → recovery → true range → …"""
    range_sc = _range_score(inp)
    trend = _trend_strength(inp)
    momentum = _directional_momentum(inp)
    sub_profile_hint = ""

    if _parabolic_overextended_pump(inp):
        regime, sub, micro, behavior = "R5", "01", "002", "PB07"
        label = "Parabolik pump / aşırı uzamış momentum"
        sub_profile_hint = "R5_DEF_PARABOLIC_OVEREXTENDED"
    elif _crash_like(inp):
        if _r8_capitulation_probe(inp):
            regime, sub, micro, behavior = "R8", "02", "003", "PB11"
            label = "Kapitülasyon crash / conditional probe"
            sub_profile_hint = "R8_CAPITULATION_CONDITIONAL_PROBE"
        elif _r8_recovery_restricted(inp):
            regime, sub, micro, behavior = "R8", "02", "002", "PB11"
            label = "Crash sonrası kontrollü toparlanma"
            sub_profile_hint = "R8_RECOVERY_RESTRICTED"
        else:
            regime, sub, micro, behavior = "R8", "01", "001", "PB11"
            label = "Crash / sert düşüş"
            sub_profile_hint = "R8_DEF_PANIC"
    elif _downtrend(inp):
        regime, sub, micro, behavior = "R7", "01", "001", "PB10"
        label = "Düşüş trendi"
    elif _recovery_breakout(inp):
        regime, sub, micro, behavior = "R6", "02", "003", "PB06"
        label = "Düşüş sonrası recovery breakout"
        sub_profile_hint = "R6_RECOVERY_BREAKOUT"
    elif _strong_trend_breakout_gate(inp, trend=trend, momentum=momentum):
        if _strong_uptrend_pullback(inp):
            regime, sub, micro, behavior = "R1", "01", "001", "PB05"
            label = "Güçlü yükseliş trendi içinde geri çekilme"
            sub_profile_hint = "R1_STD_PULLBACK"
        elif _overextended(inp) or _top_distribution(inp):
            regime, sub, micro, behavior = "R5", "01", "001", "PB07"
            label = "Yukarı breakout / aşırı ısınmış momentum"
            sub_profile_hint = "R5_DEF_OVEREXTENDED"
        elif _post_breakout_cooldown(inp):
            regime, sub, micro, behavior = "R5", "01", "001", "PB07"
            label = "Breakout sonrası kontrollü soğuma"
            sub_profile_hint = "R5_STD_POST_BREAKOUT_COOLDOWN"
        elif _clear_breakout(inp):
            regime, sub, micro, behavior = "R5", "01", "001", "PB07"
            label = "Temiz breakout / trend devamı"
            sub_profile_hint = "R5_ACT_CLEAN_BREAKOUT"
        else:
            regime, sub, micro, behavior = "R1", "01", "001", "PB05"
            label = "Güçlü yükseliş trendi"
    elif _trend_cooldown(inp, trend=trend, momentum=momentum):
        regime, sub, micro, behavior = "R1", "01", "001", "PB05"
        label = "Yükseliş trendi / kontrollü soğuma"
        sub_profile_hint = "R1_STD_TREND_COOLDOWN"
    elif _recovery_gate(inp) and _recovery_semantics_confirmed(inp):
        regime, sub, micro, behavior = "R6", "02", "002", "PB06"
        label = "Toparlanma / kontrollü geri dönüş"
        sub_profile_hint = "R6_RECOVERY_ACT"
    elif _true_volatile_range(inp, range_sc=range_sc):
        regime, sub, micro, behavior = "R4", "01", "001", "PB02"
        label = "Volatil aralık"
        if _overextended(inp):
            sub_profile_hint = "R4_DEF_OVERHEATED"
        elif _low_liquidity_unstable(inp, range_sc=range_sc):
            sub_profile_hint = "R4_RESTRICTED_UNSTABLE"
        elif not _liquid_coin(inp) and (float(inp.spread_pct or 0) >= 0.10 or _volume_quality(inp) < 0.40):
            sub_profile_hint = "R4_DEF_LOW_LIQUIDITY"
        elif (inp.bb_position or 0.5) <= 0.25 and (inp.rsi_1h or 50) < 62:
            sub_profile_hint = "R4_ACT_LOWER_BAND_BOUNCE"
        else:
            sub_profile_hint = "R4_STD_LIQUID"
    elif _volatile_vol_ok(inp):
        # High vol but failed true-range gate — restricted or recovery path
        if _low_liquidity_unstable(inp, range_sc=range_sc):
            regime, sub, micro, behavior = "R4", "03", "004", "PB02"
            label = "Düşük likidite / dengesiz aralık"
            sub_profile_hint = "R4_RESTRICTED_UNSTABLE"
        elif _trend_cooldown(inp, trend=trend, momentum=momentum):
            regime, sub, micro, behavior = "R1", "01", "001", "PB05"
            label = "Yükseliş trendi / kontrollü soğuma"
            sub_profile_hint = "R1_STD_TREND_COOLDOWN"
        elif _clear_strong_trend(inp, trend=trend, momentum=momentum):
            regime, sub, micro, behavior = "R5", "01", "001", "PB07"
            if _overextended(inp) or _top_distribution(inp):
                label = "Yüksek volatilite + aşırı momentum"
                sub_profile_hint = "R5_DEF_OVEREXTENDED"
            else:
                label = "Yüksek volatilite + temiz momentum"
                sub_profile_hint = "R5_ACT_CLEAN_BREAKOUT"
        elif range_sc < 40:
            regime, sub, micro, behavior = "R7", "02", "002", "PB10"
            label = "Dengesiz volatilite / düşüş riski"
        else:
            regime, sub, micro, behavior = "R4", "01", "001", "PB02"
            label = "Volatil aralık"
            sub_profile_hint = "R4_STD_LIQUID"
    elif _strong_uptrend(inp):
        regime, sub, micro, behavior = "R1", "01", "001", "PB05"
        if _strong_uptrend_pullback(inp):
            label = "Güçlü yükseliş trendi içinde geri çekilme"
            sub_profile_hint = "R1_STD_PULLBACK"
        else:
            label = "Güçlü yükseliş trendi"
    elif (inp.range_stability or 0) >= 0.55 and (inp.volatility_percentile or 50) < 45:
        regime, sub, micro, behavior = "R2", "01", "001", "PB01"
        label = "Dengeli aralık"
    elif (inp.volatility_percentile or 0) < 35:
        regime, sub, micro, behavior = "R3", "01", "001", "PB01"
        if _uptrend_compression(inp):
            label = "Yukarı eğilimli sıkışma / kontrollü soğuma"
            sub_profile_hint = "R3_STD_UPTREND_COMPRESSION"
        elif _controlled_compression(inp):
            label = "Düşük volatilite sıkışması"
            sub_profile_hint = "R3_STD_CONTROLLED_COMPRESSION"
        else:
            label = "Zayıf / gürültülü aralık"
    elif (inp.return_24h_pct or 0) > 0 and (inp.drawdown_7d_pct or 0) > 5:
        regime, sub, micro, behavior = "R5", "01", "001", "PB07"
        label = "Toparlanma"
    elif _upper_band_boundary(inp) and not _strong_uptrend(inp):
        regime, sub, micro, behavior = "R4", "01", "001", "PB02"
        label = "Üst bant / kontrollü volatil aralık"
        sub_profile_hint = "R4_DEF_OVERHEATED"
    else:
        regime, sub, micro, behavior = "R3", "01", "001", "PB01"
        if _uptrend_compression(inp):
            label = "Yukarı eğilimli sıkışma / kontrollü soğuma"
            sub_profile_hint = "R3_STD_UPTREND_COMPRESSION"
        else:
            label = "Yönsüz sıkışma / kontrollü soğuma"

    # Fake breakout / pump micro overrides
    if inp.fake_breakout_score >= 70 and regime not in ("R8", "R7"):
        micro, behavior = "003", "PB06"
        if regime == "R4":
            sub_profile_hint = "R4_DEF_OVERHEATED"
    elif inp.pump_score >= 70 and regime not in ("R8", "R7"):
        micro, behavior = "002", "PB09"

    return ClassifiedScenario(
        regime_id=regime,
        sub_id=sub,
        micro_id=micro,
        behavior_id=behavior,
        label=label,
        sub_profile_hint=sub_profile_hint,
    )


def to_scenario_identity(
    classified: ClassifiedScenario,
    severity: str,
) -> ScenarioIdentity:
    return ScenarioIdentity(
        regime_id=classified.regime_id,
        sub_id=classified.sub_id,
        micro_id=classified.micro_id,
        behavior_id=classified.behavior_id,
        severity=severity,  # type: ignore[arg-type]
        name=classified.label,
    )
