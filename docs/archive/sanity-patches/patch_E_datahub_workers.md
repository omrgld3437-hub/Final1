# Patch E: DataHub multi-worker warmup + health gate

## Summary
- Startup: DataHub warmup runs one price refresh (blocking up to DATAHUB_WARMUP_TIMEOUT_SEC, default 5s).
- GET /api/health/marketdata: returns `prices_ready` and `prices_count`.
- Snapshot meta includes `stale` when prices not ready or stale.
- Logs: datahub_warmup_start/end, datahub_cache_miss when get_all_prices called with empty cache.

## How to verify
1. **Health**
   - `GET /api/health/marketdata` -> 200, body has `prices_ready` (true after warmup), `prices_count`.
2. **Logs**
   - On startup: `datahub_warmup_start`, then `datahub_warmup_end prices_ready=... count=...`.
3. **First request**
   - If warmup failed, first snapshot may return empty prices and meta.stale=true.

## Multi-worker note
With multiple Uvicorn workers, each process has its own DataHub cache. Run web with one worker until shared cache (e.g. Redis) is implemented, or rely on warmup + meta.stale so UI can show cached/stale and retry.
