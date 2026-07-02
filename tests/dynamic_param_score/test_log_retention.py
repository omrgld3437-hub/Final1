"""Log retention tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.dynamic_param_score.log_retention import (
    directory_size_bytes,
    prune_log_directory,
)
from app.services.dynamic_param_score.persistence import save_decision_log
from app.services.dynamic_param_score.models import DynamicParamDecision


def _decision(did: str) -> DynamicParamDecision:
    return DynamicParamDecision(
        decision_id=did,
        symbol="SOLUSDT",
        timestamp=1,
        run_source="param_assistant",
        final_action="WAIT",
        deployable=False,
        param_score=61,
        confidence_score=50,
        risk_score=40,
        regime_tag="BALANCED_RANGE",
        risk_state="DEFENSIVE",
        selected_profile_name="WAIT_PROFILE",
        selected_profile_bucket="BALANCED_HIGH",
        params=None,
        safety_gates=[],
        blocking_reasons=[],
        warnings=[],
        explain="test",
        telemetry={"sub_scores": {}, "param_pool": {"filtered_out_count": 100, "reject_examples": []}},
    )


def test_prune_reduces_to_target(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for i in range(20):
        p = log_dir / f"{i:04d}.json"
        p.write_text("x" * 50_000, encoding="utf-8")

    before = directory_size_bytes(log_dir)
    assert before > 500_000

    result = prune_log_directory(log_dir, max_bytes=500_000, target_bytes=200_000)
    after = directory_size_bytes(log_dir)

    assert result["pruned"] > 0
    assert after <= 250_000
    assert after < before


def test_compact_log_no_huge_filtered_out(tmp_path: Path, monkeypatch):
    import app.services.dynamic_param_score.persistence as pers

    log_dir = tmp_path / "dps_logs"
    monkeypatch.setattr(pers, "_LOG_DIR", log_dir)

    huge_pool = {"filtered_out": {f"T_{i}": ["score_out_of_range"] for i in range(5000)}}
    d = _decision("abc123")
    d.telemetry["param_pool"] = huge_pool

    save_decision_log(d, {"symbol": "SOLUSDT"}, {})
    text = (log_dir / "abc123.json").read_text(encoding="utf-8")
    assert len(text) < 50_000
    data = json.loads(text)
    pool = data["final_decision"]["telemetry"]["param_pool"]
    assert "filtered_out" not in pool
