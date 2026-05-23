# Patch C: Snapshot payload cap + fields + meta + compression

## Summary
- `fields` query param: `prices`, `wallet`, `bots`, `kpis`. Invalid field -> 400 `INVALID_FIELDS`.
- Response shape: `{ ok, data, meta }` with `meta.request_id`, `server_ms`, `payload_bytes`, `trimmed_fields`, `stale`.
- Payload cap: `MAX_SNAPSHOT_BYTES` (default 500KB); trim optional sections when over cap.
- GZip: `GZipMiddleware` with `minimum_size=1024`.

## How to verify
1. **Fields validation**
   - `GET /api/dashboard/snapshot?account_id=1&fields=foo` with auth -> 400, body has `error_code=INVALID_FIELDS`, `invalid_fields=["foo"]`.
2. **Meta present**
   - `GET /api/dashboard/snapshot?account_id=1&fields=prices,kpis` -> 200, body has `ok=true`, `data`, `meta` with `request_id`, `server_ms`, `payload_bytes`, `trimmed_fields`, `stale`.
3. **Default fields**
   - `GET /api/dashboard/snapshot?account_id=1` -> 200, `data` contains at least `prices` and `kpis` (or `data.server_ts`).
4. **Logs**
   - Structured log `snapshot_served` with `payload_bytes`, `server_ms`, `fields`, `trimmed_fields`.

## Commands
```bash
pytest tests/test_snapshot_fields_validation.py tests/test_snapshot_meta_present.py -v
```
