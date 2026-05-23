# Observability

## Request ID
- Every request gets a `request_id` (from header `X-Request-Id` or generated UUID).
- Middleware sets `request.state.request_id`; response header `X-Request-Id` is set.
- Error responses include `request_id` in the body (`error.request_id`).

## Structured logs
- **snapshot_served:** `request_id`, `payload_bytes`, `server_ms`, `fields`, `trimmed_fields`.
- **datahub_warmup_start/end:** `timeout_sec`, `prices_ready`, `count`.
- **datahub_cache_miss:** when `get_all_prices` is called with empty cache.
- **lock_acquire_ok / lock_heartbeat_fail / lock_release_ok:** account_id, bot_id, symbol, lease_until.

## Error standard
- All API errors use: `error_code`, `error_id` (UUID), `request_id`, `message` (safe, no stack traces to client).
- Example: `{ "ok": false, "error": { "error_code": "WORKER_ONLY_OPERATION", "error_id": "...", "request_id": "...", "message": "..." } }`.

## Metrics (stubs)
- **snapshot_server_ms:** placeholder histogram (count, p50, p95) – see `app/observability/metrics_stubs.py`.
- **snapshot_payload_bytes:** placeholder histogram (count, p50, p95).
- Replace with Prometheus/StatsD when available; call `record_snapshot(server_ms, payload_bytes)` from snapshot endpoint.

## Timing
- Snapshot endpoint logs `server_ms` in meta and in structured log.
- Per-subtask timings (wallet_ms, bots_ms, prices_ms) can be added in snapshot tasks.
