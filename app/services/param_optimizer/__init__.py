"""Param optimizer — OFFLINE research/calibration only. Live decisions use dynamic_param_score."""

from app.services.param_optimizer.backtest import BacktestResult, run_backtest

OFFLINE_ONLY = True
DEPRECATED_LIVE_PATH = True

__all__ = ["run_backtest", "BacktestResult", "OFFLINE_ONLY", "DEPRECATED_LIVE_PATH"]
