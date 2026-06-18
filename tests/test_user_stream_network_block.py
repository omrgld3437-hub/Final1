"""User stream HTML/proxy block — yanlış DISCONNECTED/PERSISTENT log spam önleme."""

from __future__ import annotations

import pytest
import time

from app.botengine.user_stream import (
    UserStreamNetworkBlockError,
    _response_looks_like_html_block,
)


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 410) -> None:
        self.text = text
        self.status_code = status_code

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


def test_response_looks_like_html_block_true() -> None:
    res = _FakeResponse("<html><body>410 Gone</body></html>")
    assert _response_looks_like_html_block(res) is True


def test_response_looks_like_html_block_json_false() -> None:
    res = _FakeResponse('{"code":-2015,"msg":"Invalid API-key"}')
    assert _response_looks_like_html_block(res) is False


def test_network_block_error_carries_status() -> None:
    err = UserStreamNetworkBlockError(410)
    assert err.status_code == 410
    assert "410" in str(err)


def test_network_block_env_float_helper(monkeypatch) -> None:
    from app.botengine import user_stream as mod

    monkeypatch.setenv("USER_STREAM_TEST_FLOAT", "7200")
    assert mod._env_float("USER_STREAM_TEST_FLOAT", 3600, min_value=60) == 7200

    monkeypatch.setenv("USER_STREAM_TEST_FLOAT", "10")
    assert mod._env_float("USER_STREAM_TEST_FLOAT", 3600, min_value=60) == 3600

    monkeypatch.setenv("USER_STREAM_TEST_FLOAT", "not-a-number")
    assert mod._env_float("USER_STREAM_TEST_FLOAT", 3600, min_value=60) == 3600


@pytest.mark.asyncio
async def test_create_listen_key_html_raises_network_block(monkeypatch) -> None:
    from app.botengine import user_stream as mod

    class FakeKeys:
        api_key = "k"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None):
            return _FakeResponse("<html>blocked</html>", 410)

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: FakeClient())

    client = mod.UserStreamClient(
        account_id=3,
        keys=FakeKeys(),
        market="spot",
        on_order_update=mod._legacy_callback(None),
        account_label="test (id=3)",
    )

    with pytest.raises(UserStreamNetworkBlockError):
        await client._create_listen_key()


def test_network_block_warning_throttled_across_restart(tmp_path, monkeypatch) -> None:
    from app.botengine import user_stream as mod

    log_file = tmp_path / "user_stream_network_block_log.json"
    monkeypatch.setattr(mod, "_NETWORK_BLOCK_LOG_FILE", log_file)
    monkeypatch.setattr(mod, "_RUN_DIR", tmp_path)

    now = time.time()
    mod.set_persisted_network_block_warn_at(3, "spot", now - 60.0)

    should, _, _ = mod.should_emit_network_block_warning(3, "spot", 0.0, now=now)
    assert should is False

    should_later, _, _ = mod.should_emit_network_block_warning(
        3, "spot", 0.0, now=now + mod._NETWORK_BLOCK_LOG_INTERVAL_SEC + 1
    )
    assert should_later is True


def test_network_block_client_loads_persisted_on_init(tmp_path, monkeypatch) -> None:
    from app.botengine import user_stream as mod

    log_file = tmp_path / "user_stream_network_block_log.json"
    monkeypatch.setattr(mod, "_NETWORK_BLOCK_LOG_FILE", log_file)
    monkeypatch.setattr(mod, "_RUN_DIR", tmp_path)

    ts = time.time() - 120.0
    mod.set_persisted_network_block_warn_at(3, "spot", ts)

    class FakeKeys:
        api_key = "k"

    client = mod.UserStreamClient(
        account_id=3,
        keys=FakeKeys(),
        market="spot",
        on_order_update=mod._legacy_callback(None),
    )
    assert client._last_network_block_warn_at == ts
