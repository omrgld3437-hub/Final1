"""V4 exposure and risk limit rules."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.audit_v4.auditor import audit_exposure
from app.services.dynamic_param_score.param_generator.v4_resolvers import apply_live_route_constraints
from app.services.dynamic_param_score.models import RegimeTag


def test_exposure_violation_detected():
    profile = {
        "max_base_exposure_frac": 0.40,
        "worst_case_base_exposure_frac": 0.55,
    }
    assert audit_exposure(profile) == ["exposure_violation"]


def test_exposure_within_limit_passes():
    profile = {
        "max_base_exposure_frac": 0.50,
        "worst_case_base_exposure_frac": 0.45,
    }
    assert audit_exposure(profile) == []


def test_defensive_lower_lows_caps_base_alloc():
    sig = {
        "route_key": "A1|R6|S2|V3|DEFENSIVE",
        "regime_code": "R6",
        "structure_code": "S2",
        "risk_class": "DEFENSIVE",
        "lower_lows": True,
    }
    params = apply_live_route_constraints(
        {"base_alloc_frac": 0.50, "quote_alloc_frac": 0.50},
        sig,
    )
    assert float(params["base_alloc_frac"]) <= 0.35 + 1e-6


def test_strong_downtrend_defensive_exposure_cap():
    sig = {
        "route_key": "A1|R7|S2|V4|DEFENSIVE",
        "regime_code": "R7",
        "structure_code": "S2",
        "risk_class": "DEFENSIVE",
        "lower_lows": True,
    }
    params = apply_live_route_constraints(
        {
            "base_alloc_frac": 0.50,
            "quote_alloc_frac": 0.50,
            "max_base_exposure_frac": 0.60,
        },
        sig,
    )
    assert float(params.get("max_base_exposure_frac") or params["base_alloc_frac"]) <= 0.40 + 1e-6
