# V6 Full Regime Tree Audit

Generated: 2026-07-03T16:37:26.730205+00:00

Objective: V6 profile resolver must maximize controlled risk/reward, not minimize risk.

## Counts

- Main regimes: 8
- Sub scenarios: 63
- Micro scenarios: 231
- Tactical behaviors: 765
- Severity leaf profiles: 2295
- Total nodes: 3362
- Checked leaf profiles: 2295

## Verdict

- Critical fail: 0
- Soft warning: 398
- Unreachable branch: 0
- Duplicate critical branch: 0
- Duplicate soft groups: 78
- Misplaced branch: 0
- Leaf profile failures: 0

## Regime Summary

|regime|name|tactical branches|semantic roles|
|---|---|---|---|
|R1|Strong Uptrend|128|BTC_SUPPORTED_UPTREND, CONTROLLED_MOMENTUM, STRONG_MOMENTUM, TREND_CONTINUATION, TREND_COOLDOWN, TREND_PULLBACK|
|R2|Balanced Range|128|BALANCED_RANGE, MEAN_REVERSION_RANGE, STABLE_RANGE, TWO_WAY_GRID, WEAK_DIRECTION_RANGE|
|R3|Low Volatility Compression|104|CONTROLLED_COOLDOWN, LOW_VOL_COMPRESSION, NOISY_COMPRESSION, PRE_BREAKOUT_COMPRESSION, QUIET_RANGE|
|R4|Volatile Range|96|HIGH_ATR_RANGE, UNSTABLE_BUT_TRADEABLE_RANGE, VOLATILE_RANGE, WICK_CAPTURE_RANGE, WIDE_GRID_RANGE|
|R5|Breakout / Momentum|96|CLEAN_BREAKOUT, LOW_LIQUIDITY_RESTRICTED, OVEREXTENDED_MOMENTUM, PARABOLIC_OVEREXTENDED, POST_BREAKOUT_COOLDOWN, RECOVERY_BREAKOUT|
|R6|Recovery|78|DRAW_DOWN_BOUNCE, RECOVERY, RECOVERY_BREAKOUT, RETEST_RECOVERY, WEAK_RECOVERY|
|R7|Bearish Trend|72|BEARISH_CONTINUATION, BEARISH_RANGE, CONTROLLED_DOWNTREND, LOWER_LOW_DEFENSE, WEAK_BOUNCE_IN_DOWNTREND|
|R8|Crash / Deep Drawdown|63|CAPITULATION, CAPITULATION_CONDITIONAL_PROBE, CRASH_RECOVERY_WATCH, DEEP_DRAWDOWN, PANIC_CRASH|

## Golden Fixture Coverage

- Sub scenario fixtures: 63
- Micro scenario fixtures: 231
- Semantic severity coverage: covered_by_generated_tree_leaf_audit

## Top 20 Errors / Warnings

```json
[
  {
    "node_id": "R1_S01_M001_T001_PB09_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T001_PB09_DEF"
  },
  {
    "node_id": "R1_S01_M001_T001_PB09_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T001_PB09_STD"
  },
  {
    "node_id": "R1_S01_M001_T001_PB09_ACT",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T001_PB09_ACT"
  },
  {
    "node_id": "R1_S01_M001_T002_PB05_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T002_PB05_DEF"
  },
  {
    "node_id": "R1_S01_M001_T002_PB05_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T002_PB05_STD"
  },
  {
    "node_id": "R1_S01_M001_T003_PB09_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T003_PB09_DEF"
  },
  {
    "node_id": "R1_S01_M001_T003_PB09_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T003_PB09_STD"
  },
  {
    "node_id": "R1_S01_M001_T003_PB09_ACT",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T003_PB09_ACT"
  },
  {
    "node_id": "R1_S01_M001_T004_PB05_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T004_PB05_DEF"
  },
  {
    "node_id": "R1_S01_M001_T004_PB05_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-001_T004_PB05_STD"
  },
  {
    "node_id": "R1_S01_M002_T005_PB09_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T005_PB09_DEF"
  },
  {
    "node_id": "R1_S01_M002_T005_PB09_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T005_PB09_STD"
  },
  {
    "node_id": "R1_S01_M002_T005_PB09_ACT",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T005_PB09_ACT"
  },
  {
    "node_id": "R1_S01_M002_T006_PB05_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T006_PB05_DEF"
  },
  {
    "node_id": "R1_S01_M002_T006_PB05_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T006_PB05_STD"
  },
  {
    "node_id": "R1_S01_M002_T007_PB09_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T007_PB09_DEF"
  },
  {
    "node_id": "R1_S01_M002_T007_PB09_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T007_PB09_STD"
  },
  {
    "node_id": "R1_S01_M002_T007_PB09_ACT",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T007_PB09_ACT"
  },
  {
    "node_id": "R1_S01_M002_T008_PB05_DEF",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T008_PB05_DEF"
  },
  {
    "node_id": "R1_S01_M002_T008_PB05_STD",
    "warning": "raw_catalog_R1_base_below_final_contract",
    "profile_id": "DPLV6_R1-01-002_T008_PB05_STD"
  }
]
```
