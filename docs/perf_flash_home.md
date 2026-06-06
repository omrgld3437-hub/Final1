# Flash Home – Performance (Patch H)

## Targets
- **GET /api/home/fast:** server_ms p95 < 50ms (warm cache); payload_bytes < 50KB typical, < 120KB worst.
- **UI:** First meaningful paint with cached data < 200ms; fast endpoint render < 1s on slow network.

## Before vs After (intent)
- **Before:** Homepage could wait on Binance wallet + snapshot (10–20s on slow/mobile).
- **After:** Homepage shows cached/last-known data immediately; wallet refreshes in background with TTL (5s) and inflight dedup. Network: 1× GET /api/home/fast, 0–1× POST /api/home/wallet/refresh.

## Metrics to watch
- `home_fast_served` logs: `server_ms`, `payload_bytes`, `cache=memory|db`.
- `home_wallet_refresh` logs: `skipped`, `reason=ttl|cooldown|inflight`, `server_ms`.
- Optional: stub metrics for `home_fast` p95 and payload size (see observability).

## Compression
- GZipMiddleware (min_size 1KB) compresses responses. Recommend enabling Brotli/gzip at reverse proxy as well.
