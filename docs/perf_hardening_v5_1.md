# Perf + Consistency Hardening v5.1 — Summary

## Overview
Applied TRADE_TRAILING_MASTER_SPEC v5.0 patches for lock TTL consistency, worker-only trading, snapshot payload/fields/meta, query performance, DataHub warmup, UI resilience, and observability.

## Patches applied

| Patch | Description |
|-------|-------------|
| **A** | Lock TTL single source: `app/core/constants.py` (DEFAULT_LEASE_TTL_SEC=10, LOCK_HEARTBEAT_SEC=3); `app/botengine/locks.py` imports from it. |
| **B** | Worker-only orders: guard in `binance_spot.place_order` and `spot_engine.place_order`; AppError(WORKER_ONLY_OPERATION) with 403. |
| **C** | Snapshot: `fields` param (prices, wallet, bots, kpis); response `{ ok, data, meta }`; MAX_SNAPSHOT_BYTES trim; GZip 1024. |
| **D** | Snapshot query: batch last_trade per bot (single GROUP BY); optional fields reduce work. |
| **E** | DataHub warmup on startup; GET /api/health/marketdata (prices_ready); logs datahub_warmup_* and datahub_cache_miss. |
| **F** | UI: inFlight in finally; AbortController for timeout; snapshot fields per tab; lazy logo observer + cache. |
| **G** | request_id + AppError; observability.md; metrics_stubs (snapshot_server_ms, snapshot_payload_bytes); this summary. |

## Performance targets
- Snapshot p95 server_ms &lt; 150ms (local dev, warm cache).
- Snapshot default payload &lt; 200KB (warn if larger).
- UI polling stable; no inFlight deadlock.
- No web order placement when DATABASE_ROLE≠worker.

## How to verify
```bash
pytest tests/test_locks_ttl.py tests/test_worker_only_order_guard.py tests/test_snapshot_fields_validation.py -v
TOKEN=xxx python scripts/perf_snapshot_test.py --n 50
```
- Manual: GET /api/dashboard/snapshot?account_id=1&fields=prices,kpis → 200, body has `ok`, `data`, `meta` (request_id, server_ms, payload_bytes, trimmed_fields, stale).
- Role test: DATABASE_ROLE=web, POST order endpoint → 403 with error_code WORKER_ONLY_OPERATION.

## Rollback
- **Lock TTL:** Set env `DEFAULT_LEASE_TTL_SEC=60` if needed; or revert `app/core/constants.py` and `app/botengine/locks.py`.
- **Snapshot fields:** Set `SNAPSHOT_FIELDS_ENABLED=0` to request all fields; UI already normalizes `res.data` to flat shape.
- **Worker guard:** Remove guard in `binance_spot.place_order` and `spot_engine.place_order` (not recommended).
- **DataHub warmup:** Set `DATAHUB_WARMUP_TIMEOUT_SEC=0` to skip warmup.
- Revert by commit: each patch is a logical unit; revert specific commits if needed.

## Files touched (summary)
- **New:** app/core/constants.py, config.py, errors.py; app/api/utils/fields.py; app/observability/metrics_stubs.py; docs/sanity/patch_*.md, docs/api/snapshot_contract.md, docs/observability.md, docs/done_checklist_template.md, docs/perf_hardening_v5_1.md; tests/test_worker_only_order_guard.py, test_snapshot_fields_validation.py, test_snapshot_meta_present.py.
- **Updated:** app/botengine/locks.py, app/main.py, app/services/binance_spot.py, spot_engine.py, data_hub.py, dashboard_snapshot.py; app/api/routes.py, spot_routes.py; ui/assets/core/apiClient.js, ui/assets/dashboard.js; docs/CHANGELOG.md.
