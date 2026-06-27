"""V4 regime fallback hard rules — R8 crash, R15 recovery."""

from __future__ import annotations

import pytest

from app.services.dynamic_param_score.audit_v4.acceptance_v4 import audit_crash_fallback_chain
from app.services.dynamic_param_score.param_generator.feature_bins_v4 import (
    clean_fallback_keys,
    is_forbidden_fallback,
)
from app.services.dynamic_param_score.param_generator.route_manifest_v4 import (
    REGIME_DERIVATION_SOURCES,
)


def test_r8_never_fallback_to_r2():
    report = audit_crash_fallback_chain()
    assert report["r8_to_r2_fallback"] == 0
    assert report["pass"] is True


def test_r8_fallback_chain_allowed_regimes():
    route = "A1|R8|S2|V5|DEFENSIVE"
    fbs = clean_fallback_keys(route)
    for fb in fbs:
        parts = fb.split("|")
        assert parts[1] != "R2"
        assert parts[1] != "R1"
        assert parts[1] != "R3"


def test_r8_forbidden_fallback_pair():
    assert is_forbidden_fallback("R8", "R2") is True
    assert is_forbidden_fallback("R8", "R7") is False


def test_r15_derivation_sources_order():
    assert REGIME_DERIVATION_SOURCES["R15"] == ("R12", "R7", "R6")


def test_r15_never_from_r2_in_derivation():
    assert "R2" not in REGIME_DERIVATION_SOURCES["R15"]


def test_r7_defensive_not_to_r2_balanced():
    route = "A3|R7|S2|V4|DEFENSIVE"
    fbs = clean_fallback_keys(route)
    for fb in fbs:
        parts = fb.split("|")
        if len(parts) >= 5:
            assert not is_forbidden_fallback("R7", parts[1], from_structure="S2", to_structure=parts[2])
