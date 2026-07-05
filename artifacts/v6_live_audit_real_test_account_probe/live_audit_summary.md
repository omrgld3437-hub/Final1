# V6 Random 100 x 3 Budget Audit

Generated: 2026-07-03T17:05:28.958283+00:00
Data source: node-live

This is a technical audit only. It does not produce buy/sell advice.

## Overall

- Total coin count: 1
- Total test cases: 3
- Pass: 3
- Warning: 0
- Fail: 0
- Critical fail: 0
- Average score: 81.33

## Selected Symbols

VELODROMEUSDT

## Budget Breakdown

|budget|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|50.0|1|1|0|0|0|79|
|100.0|1|1|0|0|0|79|
|1000.0|1|1|0|0|0|86|

## Regime Breakdown

|regime|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|R5|3|3|0|0|0|81.33|

## Liquidity Bucket Breakdown

|bucket|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|L3_NO_DEPLOY|3|3|0|0|0|81.33|

## Worst 20

|symbol|budget|regime|score|failure reason|suggested fix|
|---|---|---|---|---|---|
|VELODROMEUSDT|50.0|R5|79||No fix needed|
|VELODROMEUSDT|100.0|R5|79||No fix needed|
|VELODROMEUSDT|1000.0|R5|86||No fix needed|

## Best 20

|symbol|budget|regime|score|why successful|
|---|---|---|---|---|
|VELODROMEUSDT|1000.0|R5|86|risk/reward, display, budget checks passed|
|VELODROMEUSDT|50.0|R5|79|risk/reward, display, budget checks passed|
|VELODROMEUSDT|100.0|R5|79|risk/reward, display, budget checks passed|

## Repeated Failure Types

|failure|count|
|---|---|

## Root Cause Analysis

Root causes are derived from critical/fail validators. If critical failures are non-zero, inspect minNotional feasibility, low-liq deploy gates, and display contradictions first.

## Code Points To Review

- `app/services/dynamic_param_score/v6/v6_exchange_validator.py`
- `app/services/dynamic_param_score/v6/engine.py`
- `app/services/dynamic_param_score/v6/v6_pa_display.py`
- `app/services/dynamic_param_score/v6/v6_regime_behavior_spec.py`

## Produced Artifacts

- live_audit_raw_results.json
- live_audit_summary.md
- live_audit_failures.md
- live_audit_by_budget.md
- live_audit_by_regime.md
- live_audit_by_liquidity_bucket.md
- live_audit_selected_symbols.txt
- live_audit_replay_snapshots.jsonl
