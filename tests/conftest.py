"""Shared E2E fixtures (Param Assistant black-box HTTP)."""

from __future__ import annotations

import pytest

from tools.param_pool.param_assistant_e2e_lib import ParamAssistantHttpClient


@pytest.fixture(scope="module")
def param_assistant_client() -> ParamAssistantHttpClient:
    return ParamAssistantHttpClient()


@pytest.fixture(scope="module")
def network_available() -> bool:
    try:
        import socket

        socket.create_connection(("api.binance.com", 443), timeout=3).close()
        return True
    except OSError:
        return False
