# Performance & Reliability Hardening — Inventory & Decisions

**Date:** 2026-02-12  
**Status:** Phase 0 and Phase 1 complete; Phases 2–6 planned/partial.

### Phase 1 summary (Lock TTL + safety)
- **TTL:** Single value 10s everywhere; spec table corrected (was 60).
- **lease_still_valid(db, account_id, symbol, bot_id)** added; orchestrator calls it before `run_actions` in both single-symbol and MULTI paths; if False, lock is released and submit is skipped (LOCK_LEASE_EXPIRED event).
- **Structured logs:** lock_acquire_ok, lock_acquire_busy, lock_heartbeat_ok (debug), lock_heartbeat_fail, lock_release_ok, lock_release_error.

---

## 1. Repository structure — found paths

| Category | Path | Notes |
|----------|------|--------|
| **Backend – snapshot** | `app/services/dashboard_snapshot.py` | fetch_prices, fetch_bots_and_account_kpis, fetch_finance_pnl; 3s task timeout |
| **Backend – routes** | `app/api/routes.py` | GET `/api/dashboard/snapshot` (line ~2021); single aggregated endpoint |
| **Backend – data hub** | `app/services/data_hub.py` | DataHub class; global `data_hub = DataHub()` at module load (line 596) |
| **Backend – locks** | `app/botengine/locks.py` | DEFAULT_LEASE_TTL_SEC=10, HEARTBEAT_RENEWAL_INTERVAL_SEC=3; try_acquire, renew, release, symbol_lock_with_heartbeat |
| **Backend – Binance spot** | `app/services/binance_spot.py` | get_wallet → GET /api/v3/account; _ACCOUNT_CACHE_TTL=30s; in-flight dedupe |
| **Backend – Binance weight** | `app/services/binance_weight.py` | request_weight_tokens, record_weight_used, get_weight_used_last_60s; per-process |
| **Frontend – API client** | `ui/assets/core/apiClient.js` | MAX_CONCURRENT_REQUESTS=2, DEFAULT_TIMEOUT=5000, in-flight dedupe |
| **Frontend – dashboard** | `ui/assets/dashboard.js` | SNAPSHOT_POLL_MS=3000, get(`/api/dashboard/snapshot?account_id=…`, { timeout: 12000 }) |
| **Frontend – intervals** | `ui/assets/core/intervalRegistry.js` | startInterval/register; skips when document.visibilityState === 'hidden' |
| **Main app** | `app/main.py` | request_id middleware (X-Request-Id), GZipMiddleware (min 1000 bytes) |
| **Uvicorn / run** | `scripts/run.sh` | No nginx in repo; uvicorn started by script; no explicit workers count in snippet |
| **Env / config** | `.env.example`, `deploy/DEPLOY.md` | DATABASE_URL, BINANCE_MASTER_KEY; no DATAHUB_MODE, MAX_SNAPSHOT_BYTES doc’d |

---

## 2. Current snapshot endpoints & payload shape

- **Single endpoint:** `GET /api/dashboard/snapshot?account_id=<id>`
  - **Auth:** Bearer + require_account_access.
  - **Backend flow:** asyncio.gather of 4 tasks (each 3s timeout):
    - `fetch_prices()` → DataHub.get_all_prices() (sync in executor)
    - `_fetch_wallet_uncached(account_id, db)` → Binance get_wallet (/api/v3/account) + 24h prices for USD
    - `fetch_bots_and_account_kpis(account_id, db)` → DB only (bots, PnL, KPIs)
    - `fetch_finance_pnl(account_id, db)` → DB + AssetSnapshot
  - **Payload shape:** `{ prices, wallet, pnl, bots, account, server_ts }`; optional `snapshot_trimmed: true` when trimmed.
  - **Cap:** MAX_SNAPSHOT_BYTES=150000 (env); trim prices to top 100 + wallet symbols if over cap; no ETag, no 304.
  - **Response:** JSON only; no Cache-Control/ETag headers; request_id only via main middleware (X-Request-Id).

---

## 3. Where Binance /account (wallet) is fetched

- **Snapshot path:** `api_dashboard_snapshot` → `_fetch_wallet_uncached(account_id, db)` (routes.py ~2326) → `get_account_keys` + `get_wallet(keys)` in binance_spot → **GET /api/v3/account** (weight 10).  
  So **every snapshot poll can trigger a wallet fetch**; there is no per-snapshot cache—only the separate `/binance/wallet` endpoint has its own cache (WALLET_RESPONSE_CACHE_TTL=15s) and in-flight dedupe. Snapshot does not use that endpoint; it calls `_fetch_wallet_uncached` directly ⇒ risk of thundering herd on /account.
- **Dedicated wallet endpoint:** `GET /api/binance/wallet?account_id=` uses cache + in-flight dedupe (routes.py ~2389); 12s timeout.

---

## 4. Where DataHub is instantiated

- **Single place:** `app/services/data_hub.py` line 596: `data_hub = DataHub()` (module-level global).
- **Implication:** Each process (e.g. each Uvicorn worker) has its own DataHub instance ⇒ cold cache / empty prices on first hit per worker; no shared DataHub across workers.

---

## 5. Where lock TTL is defined

- **Source of truth in code:** `app/botengine/locks.py`  
  - `DEFAULT_LEASE_TTL_SEC = 10`  
  - `HEARTBEAT_RENEWAL_INTERVAL_SEC = 3`
- **Spec inconsistency:** TRADE_TRAILING_MASTER_SPEC.md “system limits” table (around line 687) states `DEFAULT_LEASE_TTL_SEC | 60 | locks.py` — **incorrect**; code uses 10. Doc/spec will be aligned to 10 in Phase 1.

---

## 6. Request ID generation & propagation

- **Generation:** `app/main.py` request_id_middleware: `rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())`; stored on `request.state.request_id`.
- **Response header:** `X-Request-Id` set on response (main.py).
- **In responses:** Many endpoints add `request_id` to JSON (auth, routes, bots_engine, etc.); error standard uses `request_id` in detail. Snapshot endpoint does **not** currently include request_id in the JSON body (only via header).

---

## 7. Current compression settings

- **Server:** `app/main.py`: GZipMiddleware (Starlette), minimum_size=1000.
- **Proxy:** No nginx in repo; deploy doc describes rsync/copy; compression is app-only.

---

## 8. Decisions & tradeoffs (for later phases)

| Area | Decision | Tradeoff |
|------|----------|----------|
| Lock TTL | Use 10s everywhere; fix spec table to 10 | Consistency; no behavior change in code |
| Snapshot wallet | Move wallet off hot path; separate /snapshot/wallet or use cached wallet endpoint | Fewer /account calls; possible stale wallet in aggregated snapshot |
| DataHub | Prefer single process (1 worker) or external DataHub service (DATAHUB_MODE=service) | Simplicity vs. multi-worker scaling |
| ETag/304 | Add server-side snapshot cache + ETag; client If-None-Match | Less bandwidth and CPU; more code paths |
| Payload cap | Degrade (trim) rather than 413 for dashboard | UX over strict size guarantee |

---

## 9. File inventory summary

- **Backend:** dashboard_snapshot.py, routes.py (snapshot + wallet), data_hub.py, locks.py, binance_spot.py, binance_weight.py, main.py — all located as above.
- **Frontend:** apiClient.js, dashboard.js, intervalRegistry.js — under ui/assets/ and ui/assets/core/.
- **Config:** .env.example, deploy/DEPLOY.md; no nginx config in repo; uvicorn via scripts/run.sh / start.command.
