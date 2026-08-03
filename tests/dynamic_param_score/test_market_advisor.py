import inspect
import re

from app.services.dynamic_param_score import market_advisor
from app.services.dynamic_param_score.market_advisor import build_market_advice
from app.services.dynamic_param_score.v6 import v6_regime_behavior_spec
from app.services.dynamic_param_score.v6 import v6_scenario_classifier


def _result(
    regime: str,
    *,
    hint: str = "",
    name: str = "",
    status: str = "",
    data_quality: str = "Veri kalitesi yeterli",
) -> dict:
    return {
        "symbol": "TESTUSDT",
        "budget": 1000,
        "decision_id": "decision-1",
        "regime_tag": regime,
        "market_status_plain": status,
        "risk_display_label": "Normal",
        "risk_score": 30,
        "confidence": 82,
        "confidence_display_pct": "%82",
        "data_quality_display": data_quality,
        "selection_telemetry": {
            "v6_display": {
                "scenario_identity": {
                    "regime_id": regime,
                    "sub_profile_hint": hint,
                    "name": name,
                }
            }
        },
    }


def test_all_v6_regimes_have_distinct_recommendation_contracts():
    for regime in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"):
        advice = build_market_advice(_result(regime))
        recommendation = advice["recommendation"]
        assert recommendation["scenario_code"] == regime
        assert recommendation["title"]
        assert recommendation["summary"]
        assert recommendation["action"]
        assert recommendation["allocation"]
        assert recommendation["sell_grid"]
        assert recommendation["buy_grid"]
        assert advice["mode"] == "recommendation_only"
        assert advice["deployable"] is False
        assert advice["ui_config"] is None
        assert advice["recommendation_config"] is None


def test_severe_drop_is_risk_first_and_matches_required_grid_shape():
    advice = build_market_advice(
        _result("R8", hint="R8_DEF_PANIC", name="Panic crash")
    )
    recommendation = advice["recommendation"]
    assert recommendation["tone"] == "critical"
    assert "SERT DÜŞÜŞ" in recommendation["title"]
    assert "işlem yapılmaması" in recommendation["summary"].lower()
    assert "sert düşüş profili" in recommendation["allocation"]
    assert "yakına" in recommendation["sell_grid"]
    assert "büyük miktardan" in recommendation["sell_grid"]
    assert "uzağa" in recommendation["buy_grid"]
    assert "küçük miktardan" in recommendation["buy_grid"]


def test_low_liquidity_veto_overrides_positive_regime():
    advice = build_market_advice(
        _result(
            "R1",
            hint="LOW_LIQUIDITY_RESTRICTED",
            status="Likidite/spread riski yüksek; restricted teknik profil",
        )
    )
    recommendation = advice["recommendation"]
    assert recommendation["scenario_code"] == "LOW_LIQUIDITY"
    assert recommendation["tone"] == "critical"
    assert "yeni bot açılmaması" in recommendation["action"].lower()


def test_parabolic_veto_overrides_breakout_optimism():
    advice = build_market_advice(
        _result(
            "R5",
            hint="R5_DEF_PARABOLIC_OVEREXTENDED",
            name="Parabolik pump / aşırı uzamış momentum",
        )
    )
    recommendation = advice["recommendation"]
    assert recommendation["scenario_code"] == "R5_DEF_PARABOLIC_OVEREXTENDED"
    assert recommendation["tone"] == "critical"
    assert "Normal yeni alım yapılmaması" in recommendation["action"]


def test_weak_data_veto_has_highest_priority():
    advice = build_market_advice(
        _result(
            "R1",
            data_quality="Veri kalitesi zayıf · savunmacı filtre aktif",
        )
    )
    recommendation = advice["recommendation"]
    assert recommendation["scenario_code"] == "DATA_BLOCKED"
    assert "VERİ YETERSİZ" in recommendation["title"]
    assert "analizin yenilenmesi" in recommendation["action"]


def test_uptrend_cooldown_is_not_rendered_as_full_strength_bullish():
    advice = build_market_advice(
        _result(
            "R1",
            hint="R1_STD_PULLBACK",
            status="Ana trend yukarı; kısa vadede pullback/cooldown sinyali var",
        )
    )
    recommendation = advice["recommendation"]
    assert recommendation["scenario_code"] == "R1_STD_PULLBACK"
    assert recommendation["tone"] == "caution"
    assert "geri çekilme" in recommendation["buy_grid"].lower()


def test_real_plan_is_explained_without_grid_direction_contradiction():
    result = _result(
        "R4",
        name="Volatil aralık",
        status="Dalgalı aralık; gridler orta-geniş tutuldu",
    )
    result["ui_config"] = {
        "base_alloc_pct": 30,
        "quote_alloc_pct": 70,
        "down": {
            "trail_pct": 1.1,
            "grids": [
                {"trigger_pct": 2, "qty_pct": 5},
                {"trigger_pct": 5, "qty_pct": 10},
                {"trigger_pct": 9, "qty_pct": 20},
            ],
        },
        "up": {
            "trail_pct": 1.1,
            "grids": [
                {"trigger_pct": 3, "qty_pct": 10},
                {"trigger_pct": 6, "qty_pct": 15},
                {"trigger_pct": 10, "qty_pct": 20},
            ],
        },
        "profit": {
            "rebuy_trigger_pct": 3,
            "rebuy_trail_pct": 1.1,
            "resell_trigger_pct": 2.5,
            "resell_trail_pct": 1.1,
        },
    }
    result["telemetry"] = {
        "indicators": {
            "adx_1h": 19.8,
            "price_vs_ema200_pct": 0.5,
            "volatility_percentile": 98.7,
            "rsi14_5m": 51.8,
            "rsi14_1h": 51.4,
            "return_24h_pct": -0.5,
            "drawdown_7d_pct": 2.8,
            "orderbook_spread_pct": 0.001,
            "quote_volume_24h": 498_000_000,
        },
        "v6_final": {
            "scenario": {
                "regime_id": "R4",
                "label": "Volatil aralık",
                "sub_profile_hint": "R4_STD_LIQUID",
            }
        },
    }

    recommendation = build_market_advice(result)["recommendation"]
    plan = recommendation["engine_plan"]
    assert recommendation["scenario_code"] == "R4_STD_LIQUID"
    assert plan["allocation"] == "Coin %30,0 · USDT %70,0"
    assert "+%3,0 seviyede miktar %10,0" in plan["sell_ladder"]
    assert "yükseldikçe satış miktarını artırır" in plan["sell_ladder"]
    assert "-%2,0 seviyede miktar %5,0" in plan["buy_ladder"]
    assert "fiyat düştükçe alım miktarını artırır" in plan["buy_ladder"]
    evidence = " ".join(recommendation["market_evidence"])
    assert "ADX 19,8" in evidence
    assert "Volatilite yüzdeliği %98,7" in evidence
    assert "momentum nötr" in evidence
    assert "spread ve hacim yeterli" in evidence


def test_every_regime_has_prebuilt_interpretation_and_exit_rule():
    for regime in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"):
        recommendation = build_market_advice(_result(regime))["recommendation"]
        assert recommendation["interpretation"]
        assert recommendation["risk_control"]
        assert recommendation["invalidation"]
        assert recommendation["engine_plan"]


def _config_from_template(template) -> dict:
    return {
        "base_alloc_pct": template.initial_base_pct,
        "quote_alloc_pct": template.initial_quote_pct,
        "down": {
            "trail_pct": template.trailing_buyback_pct,
            "grids": [
                {"trigger_pct": distance, "qty_pct": amount}
                for distance, amount in zip(
                    template.buy_distances_pct,
                    template.buy_amounts_pct,
                )
            ],
        },
        "up": {
            "trail_pct": template.trailing_sell_pct,
            "grids": [
                {"trigger_pct": distance, "qty_pct": amount}
                for distance, amount in zip(
                    template.sell_distances_pct,
                    template.sell_amounts_pct,
                )
            ],
        },
        "profit": {
            "rebuy_trigger_pct": template.profit_buyback_trigger_pct,
            "rebuy_trail_pct": template.trailing_buyback_pct,
            "resell_trigger_pct": template.profit_sell_trigger_pct,
            "resell_trail_pct": template.trailing_sell_pct,
        },
    }


def test_all_24_base_regime_severity_profiles_use_exact_called_parameters():
    for regime, severity_templates in (
        v6_regime_behavior_spec.REGIME_BEHAVIOR_TEMPLATES.items()
    ):
        for severity, template in severity_templates.items():
            result = _result(regime, name=f"{regime}-{severity}")
            result["deployable"] = True
            result["ui_config"] = _config_from_template(template)
            recommendation = build_market_advice(result)["recommendation"]
            plan = recommendation["engine_plan"]

            assert (
                recommendation["allocation"]
                == f"Motorun bu analiz için kesin referansı: {plan['allocation']}."
            )
            assert recommendation["buy_grid"] == plan["buy_ladder"]
            assert recommendation["sell_grid"] == plan["sell_ladder"]
            assert "yaklaşık" not in recommendation["allocation"].lower()
            assert "yaklaşık" not in recommendation["buy_grid"].lower()
            assert "yaklaşık" not in recommendation["sell_grid"].lower()


def test_every_classifier_sub_scenario_has_prebuilt_library_entry():
    source = inspect.getsource(v6_scenario_classifier)
    classifier_hints = set(
        re.findall(r'sub_profile_hint\s*=\s*"([^"]+)"', source)
    )
    assert len(classifier_hints) == 21
    assert classifier_hints <= set(
        market_advisor._SUB_SCENARIO_OVERRIDES
    )


def test_low_liquidity_semantic_role_vetoes_even_without_display_label():
    result = _result("R5", hint="R5_ACT_CLEAN_BREAKOUT")
    result["telemetry"] = {
        "v6_final": {
            "scenario": {
                "regime_id": "R5",
                "sub_profile_hint": "R5_ACT_CLEAN_BREAKOUT",
            },
            "opportunity_notes": {
                "semantic_role": "OVEREXTENDED_LOW_LIQUIDITY",
                "reason_codes": ["LOW_LIQUIDITY_RESTRICTED"],
            },
        }
    }
    recommendation = build_market_advice(result)["recommendation"]
    assert recommendation["scenario_code"] == "LOW_LIQUIDITY"
    assert recommendation["tone"] == "critical"


def test_limited_data_is_cautious_but_does_not_hide_crash_or_liquidity():
    limited = build_market_advice(
        _result("R2", data_quality="Veri kapsaması sınırlı")
    )["recommendation"]
    assert limited["scenario_code"] == "DATA_LIMITED"
    assert limited["tone"] == "caution"
    assert "korumacı referanstır" in limited["engine_plan"]["status"]

    crash = build_market_advice(
        _result("R8", data_quality="Veri kapsaması sınırlı")
    )["recommendation"]
    assert crash["scenario_code"] == "R8"
    assert crash["tone"] == "critical"
    assert "koruma/probe referansıdır" in crash["engine_plan"]["status"]


def test_parabolic_and_crash_text_distinguish_normal_buy_from_deep_probe():
    parabolic = build_market_advice(
        _result("R5", hint="R5_DEF_PARABOLIC_OVEREXTENDED")
    )["recommendation"]
    assert "Normal yeni alım" in parabolic["action"]
    assert "koruma/probe" in parabolic["buy_grid"]

    crash = build_market_advice(
        _result("R8", hint="R8_DEF_PANIC")
    )["recommendation"]
    assert "Normal ve yakın yeni alımlar" in crash["risk_control"]
    assert "koruma/probe" in crash["risk_control"]


def test_overextended_momentum_is_restricted_but_not_misread_as_parabolic():
    template = v6_regime_behavior_spec._R5_DEF_OVEREXTENDED
    result = _result("R5", hint="R5_DEF_OVEREXTENDED")
    result["ui_config"] = _config_from_template(template)

    recommendation = build_market_advice(result)["recommendation"]

    assert recommendation["scenario_code"] == "R5_DEF_OVEREXTENDED"
    assert recommendation["tone"] == "danger"
    assert "tamamen kapalı değildir" in recommendation["action"]
    assert "Coin %45,0 · USDT %55,0" in recommendation["allocation"]
    assert "Normal yeni alım yapılmaması" not in recommendation["action"]


def test_profile_telemetry_is_exact_fallback_when_ui_config_is_absent():
    result = _result("R8", hint="R8_HARD_BLOCK")
    result["telemetry"] = {
        "v6_final": {
            "profile": {
                "base_allocation_pct": 0,
                "quote_allocation_pct": 100,
                "normal_buy_enabled": False,
                "buy_grids": [],
                "sell_grids": [],
            },
            "scenario": {
                "regime_id": "R8",
                "sub_profile_hint": "R8_HARD_BLOCK",
            },
        }
    }

    recommendation = build_market_advice(result)["recommendation"]

    assert recommendation["scenario_code"] == "R8_HARD_BLOCK"
    assert recommendation["allocation"].endswith("Coin %0,0 · USDT %100,0.")
    assert recommendation["buy_grid"] == "Yeni alım gridleri kapalı."
    assert recommendation["sell_grid"] == "Yeni satış gridleri kapalı."


def test_all_21_classifier_scenarios_keep_the_exact_selected_plan():
    specs = [
        ("R1", "R1_STD_PULLBACK", v6_regime_behavior_spec._R1_STD_PULLBACK),
        (
            "R1",
            "R1_STD_TREND_COOLDOWN",
            v6_regime_behavior_spec._R1_STD_TREND_COOLDOWN,
        ),
        (
            "R3",
            "R3_STD_CONTROLLED_COMPRESSION",
            v6_regime_behavior_spec._R3_STD_CONTROLLED_COMPRESSION,
        ),
        (
            "R3",
            "R3_STD_UPTREND_COMPRESSION",
            v6_regime_behavior_spec._R3_STD_CONTROLLED_COMPRESSION,
        ),
        (
            "R3",
            "R3_STD_UPTREND_OVERHEAT_COOLDOWN",
            v6_regime_behavior_spec._R3_STD_UPTREND_OVERHEAT_COOLDOWN,
        ),
        (
            "R3",
            "R3_STD_UPPER_BAND_PROFIT_LOCK",
            v6_regime_behavior_spec._R3_STD_UPPER_BAND_PROFIT_LOCK,
        ),
        ("R4", "R4_STD_LIQUID", v6_regime_behavior_spec._R4_STD_LIQUID),
        (
            "R4",
            "R4_DEF_OVERHEATED",
            v6_regime_behavior_spec._R4_DEF_OVERHEATED,
        ),
        (
            "R4",
            "R4_RESTRICTED_UNSTABLE",
            v6_regime_behavior_spec._R4_RESTRICTED_UNSTABLE,
        ),
        (
            "R4",
            "R4_DEF_LOW_LIQUIDITY",
            v6_regime_behavior_spec._R4_DEF_LOW_LIQUIDITY,
        ),
        (
            "R4",
            "R4_ACT_LOWER_BAND_BOUNCE",
            v6_regime_behavior_spec._R4_ACT_LOWER_BAND_BOUNCE,
        ),
        (
            "R5",
            "R5_ACT_CLEAN_BREAKOUT",
            v6_regime_behavior_spec._R5["ACT"],
        ),
        (
            "R5",
            "R5_STD_POST_BREAKOUT_COOLDOWN",
            v6_regime_behavior_spec._R5_STD_POST_BREAKOUT_COOLDOWN,
        ),
        (
            "R5",
            "R5_DEF_OVEREXTENDED",
            v6_regime_behavior_spec._R5_DEF_OVEREXTENDED,
        ),
        (
            "R5",
            "R5_DEF_PARABOLIC_OVEREXTENDED",
            v6_regime_behavior_spec._R5_DEF_PARABOLIC_OVEREXTENDED,
        ),
        (
            "R6",
            "R6_RECOVERY_BREAKOUT",
            v6_regime_behavior_spec._R6_RECOVERY_BREAKOUT,
        ),
        ("R6", "R6_RECOVERY_ACT", v6_regime_behavior_spec._R6["ACT"]),
        ("R8", "R8_HARD_BLOCK", v6_regime_behavior_spec._R8_HARD_BLOCK),
        (
            "R8",
            "R8_CAPITULATION_CONDITIONAL_PROBE",
            v6_regime_behavior_spec._R8_DEF_PANIC,
        ),
        (
            "R8",
            "R8_RECOVERY_RESTRICTED",
            v6_regime_behavior_spec._R8_RECOVERY_RESTRICTED,
        ),
        ("R8", "R8_DEF_PANIC", v6_regime_behavior_spec._R8_DEF_PANIC),
    ]

    assert len(specs) == 21
    for regime, hint, template in specs:
        result = _result(regime, hint=hint, name=hint)
        result["ui_config"] = _config_from_template(template)
        recommendation = build_market_advice(result)["recommendation"]
        plan = recommendation["engine_plan"]

        expected_code = (
            "LOW_LIQUIDITY"
            if hint == "R4_DEF_LOW_LIQUIDITY"
            else hint
        )
        assert recommendation["scenario_code"] == expected_code
        assert recommendation["allocation"].endswith(
            f"{plan['allocation']}."
        )
        assert recommendation["buy_grid"] == plan["buy_ladder"]
        assert recommendation["sell_grid"] == plan["sell_ladder"]


def test_final_v6_scenario_wins_over_stale_selection_display():
    result = _result("R1", hint="R1_STD_PULLBACK", name="Eski seçim")
    result["telemetry"] = {
        "v6_final": {
            "scenario": {
                "regime_id": "R7",
                "sub_profile_hint": "",
                "label": "Düşüş trendi",
            }
        }
    }

    recommendation = build_market_advice(result)["recommendation"]

    assert recommendation["scenario_code"] == "R7"
    assert recommendation["title"] == "DÜŞÜŞ EĞİLİMİ"


def test_market_evidence_does_not_invent_adx_direction_or_hide_bad_volume():
    result = _result("R3")
    result["telemetry"] = {
        "indicators": {
            "adx_1h": 31,
            "rsi14_5m": 75,
            "rsi14_1h": 25,
            "orderbook_spread_pct": 0.01,
            "quote_volume_24h": 5_000_000,
            "volume_consistency": 0,
        }
    }

    evidence = " ".join(
        build_market_advice(result)["recommendation"]["market_evidence"]
    )

    assert "yön tek başına ADX'ten çıkarılmıyor" in evidence
    assert "zaman dilimleri sert biçimde ayrışıyor" in evidence
    assert "emir koşulları zayıf veya eksik" in evidence


def test_planned_sell_ladder_is_not_described_as_active_without_base():
    result = _result("R4", hint="R4_STD_LIQUID")
    result["ui_config"] = _config_from_template(
        v6_regime_behavior_spec._R4_STD_LIQUID
    )
    result["ui_config"]["ladder_display"] = {
        "sell_ladder_mode": "planned_inactive"
    }

    recommendation = build_market_advice(result)["recommendation"]

    assert "henüz aktif değildir" in recommendation["sell_grid"]
    assert "satış kademeleri şu anda aktif değildir" in recommendation["action"]
    assert (
        recommendation["engine_plan"]["sell_ladder_state"]
        == "planned_inactive"
    )
