"""Audit configuration and constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

REQUIRED_SCHEMA_FIELDS = (
    "profile_id",
    "asset_class",
    "budget_class",
    "regime",
    "risk_level",
    "volatility_bin",
    "atr_1h_bin",
    "adx_bin",
    "rsi_state",
    "bb_position",
    "structure",
    "fee_class",
    "spread_class",
    "buy_grid_count",
    "sell_grid_count",
    "buy_grid_pcts",
    "sell_grid_pcts",
    "buy_distribution",
    "sell_distribution",
    "buy_trailing_pct",
    "sell_trailing_pct",
    "rebuy_trigger_pct",
    "rebuy_trail_pct",
    "resell_trigger_pct",
    "resell_trail_pct",
    "min_budget_required",
    "max_budget_recommended",
    "score_prior",
    "safety_level",
    "version",
)

LEGACY_WAIT_MARKERS = (
    "_FEE_BAD_WAIT",
    "FEE_BAD_WAIT",
    "WAIT_SAFETY",
    "NO_TRADE_WAIT",
)

INVALID_WAIT_REASONS = frozenset(
    {
        "fee_bad",
        "low_volatility",
        "balanced_range",
        "normal_risk",
        "score_60_69",
        "grid_too_close",
        "small_budget",
    }
)

VALID_HARD_WAIT_REASONS = frozenset(
    {
        "price_invalid",
        "data_stale",
        "data_gap",
        "exchange_filter_fail",
        "balance_insufficient",
        "spread_dangerous",
        "crash_filter",
        "api_order_rejected",
        "no_valid_grid_after_min_notional",
        "DUMP_RISK",
        "DATA_STALE",
        "SPREAD_DANGEROUS",
        "MIN_NOTIONAL_HARD_FAIL",
    }
)

AUDIT_BUDGETS = (25, 50, 100, 250, 500, 1000)
AUDIT_SYMBOLS_DEFAULT = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "XRPUSDT",
    "LINKUSDT",
)

SCENARIO_NAMES = (
    "CALM_RANGE_MAJOR",
    "BALANCED_RANGE_MAJOR",
    "VOLATILE_RANGE_MAJOR",
    "CHOPPY_ALTCOIN",
    "LOW_VOL_BUT_FEE_BAD",
    "LOW_BUDGET_50_USDT",
    "LOWER_LOWS_RANGE",
    "HIGHER_HIGHS_RANGE",
    "BTC_CRASH_DRAG",
    "SPREAD_WIDE_BUT_NOT_DANGEROUS",
    "DATA_STALE",
    "MIN_NOTIONAL_EDGE",
    "CRASH_RISK",
)

SAMPLING_CELL_DIMS = (
    "asset_class",
    "budget_class",
    "regime",
    "risk_level",
    "volatility_bin",
    "atr_1h_bin",
    "adx_bin",
    "rsi_state",
    "bb_position",
    "structure",
    "fee_class",
    "spread_class",
    "data_quality",
)

REQUIRED_COVERAGE_REGIMES = frozenset({
    "CALM_RANGE",
    "BALANCED_RANGE",
    "VOLATILE_RANGE",
    "CHOPPY_RANGE",
    "WEAK_DOWNTREND_RANGE",
    "WEAK_UPTREND_RANGE",
    "CRASH_RISK",
    "RECOVERY_RANGE",
})

REQUIRED_COVERAGE_BUDGETS = frozenset({
    "10_25",
    "25_50",
    "50_100",
    "100_250",
    "250_500",
    "500_1000",
})

AUDIT_MODES = (
    "fast-full",
    "smart-sample",
    "deep-risk",
    "smart-full",
    "exhaustive-deep",
    "delta",
    "legacy",
)

ZIP_REQUIRED_FILES = (
    "00_EXECUTIVE_SUMMARY.md",
    "01_PARAM_LIBRARY_OVERVIEW.json",
    "02_PROFILE_SCHEMA_VALIDATION.json",
    "03_GRID_MATH_VALIDATION.json",
    "04_AMOUNT_DISTRIBUTION_VALIDATION.json",
    "05_MIN_NOTIONAL_VALIDATION.json",
    "06_FEE_SPREAD_SLIPPAGE_VALIDATION.json",
    "07_WAIT_DECISION_AUDIT.json",
    "08_SCENARIO_REPLAY_RESULTS.json",
    "09_SELECTION_TRACE_RESULTS.json",
    "10_COVERAGE_GAP_ANALYSIS.json",
    "11_DUPLICATE_PROFILE_REPORT.json",
    "12_BAD_PROFILE_SAMPLES.csv",
    "13_TOP_500_PROFILE_SAMPLES.csv",
    "14_SYMBOL_REPLAY_ETHUSDT.md",
    "15_SYMBOL_REPLAY_BTCUSDT.md",
    "16_CODE_TREE.md",
    "17_DEPENDENCY_GRAPH.md",
    "18_MARKET_DATA_FLOW_TRACE.md",
    "19_FRONTEND_BACKEND_CONTRACT.md",
    "20_FIELD_MAPPING_TABLE.csv",
    "21_TEST_LOGS.txt",
    "22_ERROR_WARNINGS.md",
    "23_FINAL_PASS_FAIL_REPORT.md",
    "FAST_FULL_AUDIT_SUMMARY.json",
    "SMART_SAMPLE_AUDIT_SUMMARY.json",
    "DEEP_RISK_AUDIT_SUMMARY.json",
    "profile_quality_scores.csv",
    "profile_fingerprints.csv",
    "coverage_matrix.csv",
    "selection_trace_samples.jsonl",
)

SECRET_PATTERNS = (
    "API_KEY",
    "API_SECRET",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PRIVATE_KEY",
)


@dataclass
class AuditConfig:
    project_root: Path
    profiles_path: Path | None = None
    output_dir: Path = field(default_factory=lambda: Path("audit_output"))
    sample_live_symbols: Tuple[str, ...] = AUDIT_SYMBOLS_DEFAULT
    full: bool = True
    zip_output: bool = True
    max_profiles: int | None = None
    min_notional_values: Tuple[float, ...] = (5.0, 10.0)
    mode: str = "smart-full"
    sample_per_cell: int = 7
    enhance_pool: bool = False
    baseline_path: Path | None = None

    def resolve_output_dir(self) -> Path:
        return (self.project_root / self.output_dir).resolve()
