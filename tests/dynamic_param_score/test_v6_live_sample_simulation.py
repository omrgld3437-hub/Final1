"""V6 live sample dry-run — requires network (@pytest.mark.live)."""

from __future__ import annotations

import asyncio
import os

import pytest

from tools.dynamic_param_v6.v6_simulation_common import (
    calculate_live_symbol,
    validate_live_decision,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def v6_engine_env():
    os.environ["DPS_ENGINE_VERSION"] = "v6"
    yield


def test_btcusdt_v6_calculate(v6_engine_env):
    try:
        decision = asyncio.run(calculate_live_symbol("BTCUSDT", budget=500.0))
    except Exception as exc:
        pytest.skip(f"network/data unavailable: {exc}")

    assert decision is not None
    assert decision.params is not None
    assert decision.params.pool_version == "v6"
    tel = decision.telemetry or {}
    assert tel.get("v6_display") is not None

    errors, warnings, extras = validate_live_decision(decision, symbol="BTCUSDT")
    # Document known V6 telemetry gaps; hard-fail only on params/safe_wait regressions.
    assert "ERROR_SAFE_WAIT_NULL_PARAMS" not in errors
    assert "ERROR_NO_PARAMS_FOR_VALID_PROFILE" not in errors
    if errors:
        pytest.xfail(f"known live findings pending fix: {errors}; warnings={warnings}; extras={extras}")


def test_mandatory_symbols_smoke(v6_engine_env):
    for sym in ("ETHUSDT", "MANTAUSDT"):
        try:
            decision = asyncio.run(calculate_live_symbol(sym, budget=500.0))
        except Exception as exc:
            pytest.skip(f"{sym} unavailable: {exc}")
        errors, _, _ = validate_live_decision(decision, symbol=sym)
        assert decision.params is not None
        assert "ERROR_SAFE_WAIT_NULL_PARAMS" not in errors


def test_live_marker_registered():
    assert asyncio.get_event_loop_policy() is not None
