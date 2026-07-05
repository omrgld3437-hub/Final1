# V6 Random 100 x 3 Budget Audit

Generated: 2026-07-05T13:36:52.651182+00:00
Data source: node-live

This is a technical audit only. It does not produce buy/sell advice.

## Overall

- Total coin count: 5
- Total test cases: 15
- Pass: 15
- Warning: 0
- Fail: 0
- Critical fail: 0
- Average score: 83.6

## Selected Symbols

VELODROMEUSDT, SOPHUSDT, MOVEUSDT, ALCXUSDT, LISTAUSDT

## Budget Breakdown

|budget|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|50.0|5|5|0|0|0|81.6|
|100.0|5|5|0|0|0|84|
|1000.0|5|5|0|0|0|85.2|

## Regime Breakdown

|regime|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|R1|3|3|0|0|0|82|
|R5|3|3|0|0|0|80|
|R6|3|3|0|0|0|82|
|R8|6|6|0|0|0|87|

## Liquidity Bucket Breakdown

|bucket|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|L3_NO_DEPLOY|15|15|0|0|0|83.6|

## Worst 20

|symbol|budget|regime|score|failure reason|suggested fix|
|---|---|---|---|---|---|
|VELODROMEUSDT|50.0|R5|78||No fix needed|
|VELODROMEUSDT|100.0|R5|78||No fix needed|
|SOPHUSDT|50.0|R6|78||No fix needed|
|LISTAUSDT|50.0|R1|78||No fix needed|
|VELODROMEUSDT|1000.0|R5|84||No fix needed|
|SOPHUSDT|100.0|R6|84||No fix needed|
|SOPHUSDT|1000.0|R6|84||No fix needed|
|LISTAUSDT|100.0|R1|84||No fix needed|
|LISTAUSDT|1000.0|R1|84||No fix needed|
|ALCXUSDT|50.0|R8|86||No fix needed|
|ALCXUSDT|100.0|R8|86||No fix needed|
|ALCXUSDT|1000.0|R8|86||No fix needed|
|MOVEUSDT|50.0|R8|88||No fix needed|
|MOVEUSDT|100.0|R8|88||No fix needed|
|MOVEUSDT|1000.0|R8|88||No fix needed|

## Best 20

|symbol|budget|regime|score|why successful|
|---|---|---|---|---|
|MOVEUSDT|50.0|R8|88|risk/reward, display, budget checks passed|
|MOVEUSDT|100.0|R8|88|risk/reward, display, budget checks passed|
|MOVEUSDT|1000.0|R8|88|risk/reward, display, budget checks passed|
|ALCXUSDT|50.0|R8|86|risk/reward, display, budget checks passed|
|ALCXUSDT|100.0|R8|86|risk/reward, display, budget checks passed|
|ALCXUSDT|1000.0|R8|86|risk/reward, display, budget checks passed|
|VELODROMEUSDT|1000.0|R5|84|risk/reward, display, budget checks passed|
|SOPHUSDT|100.0|R6|84|risk/reward, display, budget checks passed|
|SOPHUSDT|1000.0|R6|84|risk/reward, display, budget checks passed|
|LISTAUSDT|100.0|R1|84|risk/reward, display, budget checks passed|
|LISTAUSDT|1000.0|R1|84|risk/reward, display, budget checks passed|
|VELODROMEUSDT|50.0|R5|78|risk/reward, display, budget checks passed|
|VELODROMEUSDT|100.0|R5|78|risk/reward, display, budget checks passed|
|SOPHUSDT|50.0|R6|78|risk/reward, display, budget checks passed|
|LISTAUSDT|50.0|R1|78|risk/reward, display, budget checks passed|

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
