# Home Fast API contract (Patch H)

## GET /api/home/fast

**Query:** `account_id` (required).  
**Auth:** Required (Bearer).  
**Behavior:** No Binance calls. Returns cached prices (DataHub), minimal KPIs (DB), last wallet snapshot (DB). Memory cache TTL 2s.

### Success response (200)
```json
{
  "ok": true,
  "data": {
    "prices": { "BTCUSDT": { "price": 43000, "change24h": 0.5, "ts": 1234567890 }, ... },
    "kpis": { "total_bots": 5, "active_bots": 2, "total_pnl_usd": 100, "daily_bot_pnl_usd": 10, "realized_pnl": 50, "unrealized_pnl": 20 },
    "wallet_cached": { "total_usd": 1000, "assets": [ { "asset": "USDT", "free": 500, "locked": 0, "usdt_value": 500 }, ... ] } | null,
    "wallet_cached_at": "2026-02-12T12:00:00Z" | null,
    "prices_ready": true,
    "wallet_live_inflight": false
  },
  "meta": {
    "request_id": "uuid-or-shortid",
    "server_ms": 12,
    "payload_bytes": 12345,
    "stale": false,
    "cache": "memory|db",
    "generated_at": "2026-02-12T12:00:00.000Z"
  }
}
```

### Error (4xx/5xx)
Standard `{ "ok": false, "error": { "error_code", "error_id", "request_id", "message" } }`.

---

## POST /api/home/wallet/refresh

**Query:** `account_id` (required), `force=0|1` (optional, 1 bypasses TTL, still respects cooldown/inflight).  
**Auth:** Required.  
**Behavior:** May call Binance. Dedup (inflight), TTL skip, cooldown on rate limit.

### Success response (200)
```json
{
  "ok": true,
  "data": {
    "wallet_live": { "total_usd": 1000, "assets": [...], "ts": "..." },
    "wallet_live_at": "2026-02-12T12:00:00Z",
    "skipped": false,
    "inflight": false,
    "refresh_policy": { "ttl_sec": 5, "cooldown_sec": 30 }
  },
  "meta": { "request_id": "...", "server_ms": 120 }
}
```
When skipped (TTL/inflight/cooldown): `skipped: true`, optional `inflight: true`; `wallet_live` may be last cached.

---

## GET /api/home/wallet/status

**Query:** `account_id` (required).  
**Auth:** Required.  
**Response:** `{ "ok": true, "data": { "inflight": false, "last_live_at": "ISO8601|null", "cooldown_until": "ISO8601|null", "last_error_code": "string|null" }, "meta": { "request_id": "..." } }`.
