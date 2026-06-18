from __future__ import annotations

from app.botengine.execution import (
    BALANCE_DRIFT_BASE_WARN_PCT,
    BALANCE_DRIFT_QUOTE_WARN_USD,
    _asset_total_balance,
    _balance_drift_severity,
    _compute_balance_drift_metrics,
    _should_log_balance_drift_worker,
)


def test_asset_total_balance_includes_locked():
    balances = {
        "SOL": {"free": 0.05, "locked": 0.45},
        "USDT": {"free": 40, "locked": 10},
    }
    assert _asset_total_balance(balances, "SOL") == 0.5
    assert _asset_total_balance(balances, "USDT") == 50.0


def test_locked_orders_no_false_drift():
    virt_base = 0.5
    real_free = 0.05
    real_locked = 0.45
    base_pct, quote_drift = _compute_balance_drift_metrics(
        virt_base, 50.0, real_free + real_locked, 50.0
    )
    assert base_pct == 0.0
    assert quote_drift == 0.0
    assert _balance_drift_severity(base_pct, quote_drift) == "INFO"


def test_free_only_would_have_shown_old_false_warn():
    virt_base = 0.5
    real_free = 0.454
    base_pct_free_only = abs(real_free - virt_base) / virt_base * 100
    assert base_pct_free_only > 5.0
    base_pct_total, _ = _compute_balance_drift_metrics(virt_base, 50.0, 0.5, 50.0)
    assert base_pct_total < 5.0


def test_warn_thresholds():
    assert _balance_drift_severity(BALANCE_DRIFT_BASE_WARN_PCT + 0.1, 0) == "WARN"
    assert _balance_drift_severity(5.0, BALANCE_DRIFT_QUOTE_WARN_USD + 0.01) == "WARN"
    assert _balance_drift_severity(9.29, 1.88) == "INFO"


def test_worker_log_cooldown_same_profile():
    bot_id = 999001
    assert _should_log_balance_drift_worker(bot_id, 9.3, 1.88) is True
    assert _should_log_balance_drift_worker(bot_id, 9.29, 1.88) is False
