# Snapshot API Contract

## Endpoint
`GET /api/dashboard/snapshot?account_id={id}&fields=prices,wallet,bots,kpis`

## Query parameters
- **account_id** (required): Account ID.
- **fields** (optional): Comma-separated subset of `prices`, `wallet`, `bots`, `kpis`. Default when omitted: `prices,kpis`. Unknown field returns 400 with `error_code=INVALID_FIELDS`.

## Success response (200)
```json
{
  "ok": true,
  "data": {
    "prices": { "BTCUSDT": { "price": 97000, "ts": 1234567890, "is_stale": false }, ... },
    "wallet": { "total_usd": 1000, "assets": [...] },
    "bots": [ { "bot_id": 1, "symbol": "BTCUSDT", "status": "running", ... } ],
    "kpis": { "account": { "bots_balance_usd": 500, "daily_bot_pnl_usd": 0, ... }, "pnl": { ... } },
    "server_ts": 1234567890
  },
  "meta": {
    "request_id": "uuid",
    "server_ms": 12,
    "payload_bytes": 123456,
    "trimmed_fields": [],
    "stale": false
  }
}
```

## Error response (4xx/5xx)
```json
{
  "ok": false,
  "error": {
    "error_code": "INVALID_FIELDS",
    "error_id": "uuid",
    "request_id": "uuid",
    "message": "Unknown snapshot fields",
    "details": { "invalid_fields": ["foo"], "allowed": ["prices", "wallet", "bots", "kpis"] }
  }
}
```

## Trimming
When response size would exceed `MAX_SNAPSHOT_BYTES` (env, default 500KB), optional sections are dropped in order: bots, wallet, then prices trimmed to top 100 + wallet symbols. `meta.trimmed_fields` lists dropped/trimmed section names.

## Fields per view (recommended)
- Dashboard main: `fields=prices,kpis`
- Bots tab open: `fields=prices,bots,kpis`
- Wallet modal open: `fields=wallet,prices`
