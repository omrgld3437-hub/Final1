# Patch D: Snapshot query performance

## Summary
- Batch query for last trade per bot (single GROUP BY instead of N per-bot queries).
- Snapshot endpoint runs only requested field tasks (fewer DB/Binance calls when fields=prices,kpis).

## How to verify
1. **Perf script**
   ```bash
   TOKEN=your_token python scripts/perf_snapshot_test.py --n 50
   ```
   Report p50/p95 server_ms from response meta (or from logs).

2. **Logs**
   Per-subtask timings can be added; snapshot_served log includes server_ms and payload_bytes.

## Expected outcomes
- Snapshot p95 server_ms < 150ms on local dev with warm cache (target).
- DB calls in snapshot: one batch for last_trade per bot; no per-bot loop for last trade.
