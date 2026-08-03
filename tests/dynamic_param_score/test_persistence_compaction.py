from __future__ import annotations

from app.services.dynamic_param_score.persistence import _compact_telemetry


def test_db_compaction_preserves_decision_telemetry_without_reject_fanout():
    telemetry = {
        "indicators": {"rsi": 51.2},
        "v6_display": {"regime_label": "Dengeli"},
        "param_pool": {
            "selected_template": "R4_STD",
            "filter_summary": {"risk": 12},
            "filtered_out": {
                "candidate-1": ["risk"],
                "candidate-2": ["budget"],
            },
        },
    }

    compacted = _compact_telemetry(telemetry)

    assert compacted["indicators"] == {"rsi": 51.2}
    assert compacted["v6_display"]["regime_label"] == "Dengeli"
    assert compacted["param_pool"]["selected_template"] == "R4_STD"
    assert compacted["param_pool"]["filter_summary"] == {"risk": 12}
    assert "filtered_out" not in compacted["param_pool"]


def test_compaction_does_not_mutate_live_decision_telemetry():
    telemetry = {
        "indicators": {"rsi": 49.0},
        "param_pool": {"filtered_out": {"candidate": ["risk"]}},
    }

    _compact_telemetry(telemetry)

    assert telemetry["param_pool"]["filtered_out"] == {"candidate": ["risk"]}
