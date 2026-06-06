"""bot_status_utils — admin/dashboard aktif bot sayımı."""

from types import SimpleNamespace

from app.services.bot_status_utils import (
    count_admin_active_bots,
    count_running_bots,
    is_bot_running,
)


def test_is_bot_running_case_insensitive():
    assert is_bot_running("RUNNING")
    assert is_bot_running(" running ")
    assert not is_bot_running("paused")
    assert not is_bot_running("stopped")


def test_count_running_bots():
    bots = [
        SimpleNamespace(status="running"),
        SimpleNamespace(status="RUNNING"),
        SimpleNamespace(status="paused"),
        SimpleNamespace(status="stopped"),
    ]
    assert count_running_bots(bots) == 2


def test_count_admin_active_bots_includes_paused():
    bots = [
        {"status": "running"},
        {"status": "paused"},
        {"status": "stopped"},
    ]
    assert count_admin_active_bots(bots) == 2
