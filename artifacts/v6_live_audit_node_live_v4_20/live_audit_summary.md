# V6 Random 100 x 3 Budget Audit

Generated: 2026-07-05T13:42:33.906131+00:00
Data source: node-live

This is a technical audit only. It does not produce buy/sell advice.

## Overall

- Total coin count: 20
- Total test cases: 60
- Pass: 60
- Warning: 0
- Fail: 0
- Critical fail: 0
- Average score: 82.95

## Selected Symbols

VELODROMEUSDT, SOPHUSDT, MOVEUSDT, ALCXUSDT, LISTAUSDT, LUMIAUSDT, DYDXUSDT, ONDOUSDT, CAKEUSDT, BFUSDUSDT, JUVUSDT, CFGUSDT, SNDKBUSDT, MANTRAUSDT, ARKUSDT, INJUSDT, NEIROUSDT, RVNUSDT, ENJUSDT, GNSUSDT

## Budget Breakdown

|budget|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|50.0|20|20|0|0|0|80.1|
|100.0|20|20|0|0|0|83.4|
|1000.0|20|20|0|0|0|85.35|

## Regime Breakdown

|regime|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|R1|3|3|0|0|0|82|
|R3|18|18|0|0|0|81.67|
|R4|6|6|0|0|0|83.33|
|R5|12|12|0|0|0|81.17|
|R6|9|9|0|0|0|84.44|
|R7|6|6|0|0|0|84.17|
|R8|6|6|0|0|0|87|

## Liquidity Bucket Breakdown

|bucket|cases|pass|warning|fail|critical|avg|
|---|---|---|---|---|---|---|
|L2_RESTRICTED|21|21|0|0|0|82.76|
|L3_NO_DEPLOY|39|39|0|0|0|83.05|

## Worst 20

|symbol|budget|regime|score|failure reason|suggested fix|
|---|---|---|---|---|---|
|CFGUSDT|50.0|R3|73||No fix needed|
|BFUSDUSDT|50.0|R3|74||No fix needed|
|VELODROMEUSDT|50.0|R5|78||No fix needed|
|VELODROMEUSDT|100.0|R5|78||No fix needed|
|SOPHUSDT|50.0|R6|78||No fix needed|
|LISTAUSDT|50.0|R1|78||No fix needed|
|RVNUSDT|50.0|R3|78||No fix needed|
|DYDXUSDT|50.0|R7|79||No fix needed|
|CAKEUSDT|100.0|R4|79||No fix needed|
|JUVUSDT|100.0|R4|79||No fix needed|
|SNDKBUSDT|50.0|R5|79||No fix needed|
|SNDKBUSDT|100.0|R5|79||No fix needed|
|MANTRAUSDT|50.0|R3|79||No fix needed|
|ARKUSDT|50.0|R3|79||No fix needed|
|GNSUSDT|50.0|R5|79||No fix needed|
|GNSUSDT|100.0|R5|79||No fix needed|
|LUMIAUSDT|50.0|R5|80||No fix needed|
|LUMIAUSDT|100.0|R5|80||No fix needed|
|BFUSDUSDT|100.0|R3|80||No fix needed|
|BFUSDUSDT|1000.0|R3|80||No fix needed|

## Best 20

|symbol|budget|regime|score|why successful|
|---|---|---|---|---|
|MOVEUSDT|50.0|R8|88|risk/reward, display, budget checks passed|
|MOVEUSDT|100.0|R8|88|risk/reward, display, budget checks passed|
|MOVEUSDT|1000.0|R8|88|risk/reward, display, budget checks passed|
|ONDOUSDT|100.0|R6|88|risk/reward, display, budget checks passed|
|ONDOUSDT|1000.0|R6|88|risk/reward, display, budget checks passed|
|INJUSDT|100.0|R6|88|risk/reward, display, budget checks passed|
|INJUSDT|1000.0|R6|88|risk/reward, display, budget checks passed|
|LUMIAUSDT|1000.0|R5|87|risk/reward, display, budget checks passed|
|NEIROUSDT|100.0|R3|87|risk/reward, display, budget checks passed|
|NEIROUSDT|1000.0|R3|87|risk/reward, display, budget checks passed|
|ENJUSDT|100.0|R7|87|risk/reward, display, budget checks passed|
|ENJUSDT|1000.0|R7|87|risk/reward, display, budget checks passed|
|ALCXUSDT|50.0|R8|86|risk/reward, display, budget checks passed|
|ALCXUSDT|100.0|R8|86|risk/reward, display, budget checks passed|
|ALCXUSDT|1000.0|R8|86|risk/reward, display, budget checks passed|
|DYDXUSDT|100.0|R7|86|risk/reward, display, budget checks passed|
|DYDXUSDT|1000.0|R7|86|risk/reward, display, budget checks passed|
|CAKEUSDT|50.0|R4|86|risk/reward, display, budget checks passed|
|CAKEUSDT|1000.0|R4|86|risk/reward, display, budget checks passed|
|MANTRAUSDT|100.0|R3|86|risk/reward, display, budget checks passed|

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
