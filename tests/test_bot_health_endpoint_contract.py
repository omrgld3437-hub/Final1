from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "api" / "bots_engine.py").read_text(encoding="utf-8")


def _function_block(name: str, next_marker: str) -> str:
    start = SOURCE.index(f"async def {name}(")
    end = SOURCE.index(next_marker, start)
    return SOURCE[start:end]


def test_health_display_error_is_defined_inside_health_endpoint():
    health = _function_block("bots_health", '@router.post("/{bot_id}/health/ack")')
    assert 'display_last_error_code = state.get("last_error_code")' in health
    assert '"last_error_code": display_last_error_code' in health


def test_stop_endpoint_does_not_reference_health_alert_locals():
    stop = _function_block("bots_stop", "def _is_worker_only_order_error")
    assert "display_last_error_code" not in stop
    assert "for a in alerts" not in stop
