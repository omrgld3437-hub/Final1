# Trade Trailing – Complete System Brain v5.0

**Version:** 5.0  
**Purpose:** Senior engineer or LLM can operate, debug, evolve, and own the system without the original author. Zero blind spots. Bot Engine v5: event-driven scheduling, exactly-once intents, crash-safe reconciliation, 300-bot capable.

---

## Spec maintenance (kilitli kural)

- Bu dosya **tek kaynak (single source of truth)** kabul edilir. Tüm önemli mimari/limit/API kararları ve değişiklikler bu spec’e işlenir; tüm sohbetlerde geçerlidir.
- Performans ve güvenilirlik çalışmaları: `docs/perf_hardening_report.md` (envanter, kararlar), `docs/changelog_perf_hardening.md` (append-only değişiklik günlüğü).
- Lock: `DEFAULT_LEASE_TTL_SEC = 10`, heartbeat 3s (locks.py); submit öncesi `lease_still_valid` kontrolü zorunludur; yenileme başarısızsa o tick’te order gönderilmez.

---

# 0. SYSTEM IDENTITY & OWNERSHIP

## Problem Solved

Trade Trailing (TraderTrailing) is a Binance Spot bot platform that:
- Runs DCA, Grid, Trailing, Multi-Asset Rebalance, and TRDCA PRO strategies
- Provides a web dashboard for monitoring and control
- Executes trades via Binance REST API only (no order WebSocket)
- Manages virtual wallets, symbol locks, and bot state in SQLite

## Financial Safety Rules (MUST NEVER VIOLATE) — v5

| Rule | Enforcement | Code Location |
|------|-------------|---------------|
| S1 Never submit without persisted intent | intent row exists before place_order | execution.py, intent_ledger.upsert_intent |
| S2 Same intent_id => same clientOrderId | client_order_id stored on first persist; reused | intent_ledger.py |
| S3 Reconcile before new actions after timeout/crash | reconcile_account; get_order_by_client_order_id | reconcile.py, execution |
| S4 No REST price per symbol for trading | DataHub (WS) only; adapter.get_price from DataHub | binance_adapter.get_price |
| S5 Bounded external calls; retry taxonomy | Weight governor; errors.py; no unbounded backoff | binance_weight, errors |
| S6 Weight near limit => SAFE MODE | Deny new submits; allow reconcile | scheduler, execution |
| S7 Locks released in finally; lease + heartbeat | symbol_lock_with_heartbeat; release in finally | locks.py |
| S8 Deterministic intents (no restart collision) | intent_id and client_order_id include run_id (e.g. cmd{command_id}); run_id set on START | intent_ledger.build_intent_id, build_client_order_id; bots_engine.bots_start |
| Never expose API secret in logs | Fernet-encrypted at rest | `app/services/encryption.py` |
| Never allow cross-account bot execution | `assert_bot_belongs_to_account` | `app/botengine/worker_main.py`, routes |

## Data Loss Definitions

| Event | Data Loss? | Recovery |
|-------|------------|----------|
| Web process crash | Sessions lost (in-memory) | User re-login; no recovery |
| Worker crash mid-trade | Bot state may be mid-write | `save_state` is atomic; worst case last tick lost |
| DB file corrupted | Full loss | Backup required; no replication |
| DataHub RAM eviction | Price cache cleared | REST bulk refresh repopulates |

## Service Failure Definitions

| Failure | Definition | Measurable |
|---------|------------|------------|
| Snapshot timeout | Request > 12s (UI) or 3s per task (backend) | SNAPSHOT_LATENCY log |
| Binance unreachable | Circuit breaker open | CircuitBreaker.get_state() |
| DB locked | SQLite BUSY | Exception type |
| Worker not processing | No tick for >60s | WORKER_HEARTBEAT log |
| Mobile "nothing loads" | Snapshot 404/503 or JS blocked | visibilityState, network tab |

## Who Can Trade Money

| Actor | Allowed | Condition |
|-------|---------|-----------|
| Worker process | Yes | Loads bot from DB; has account API keys; acquires symbol lock |
| Web process | No | Read-only Binance (wallet, prices) |
| Manager (7999) | No | Start/stop commands only |
| User via UI | No | Sends START/STOP; Worker executes |

**What can go wrong here?** Misconfiguration could allow Web to call place_order; code review must ensure only Worker uses that path. Session hijack allows UI actions as victim; boot_id limits blast radius.

---

# 1. FULL RUNTIME TOPOLOGY

## Processes

| Process | PID File | Port | Entry | Workers |
|---------|----------|------|-------|---------|
| Manager | `.run/manager.pid` | 7999 | `manager_server` | 1 |
| Web | `.run/web.pid` | 8000 | `uvicorn app.main:app --workers 2` | 2 (uvloop, httptools) |
| Worker | `.run/worker.pid` | — | `app.botengine.worker_main` | 1 |
| HTML (optional) | — | 8080 | `omeraltinhtml/start.py` | 1 |

## Startup Timeline (ms)

```
t=0       start.command
t=0       Manager: nohup python -m manager_server
t=2000    Manager: sleep 2 complete
t=2000    Web: nohup uvicorn ... --workers 2
t=2100    Web: sleep 1 complete
t=2100    Worker: nohup python -m app.botengine.worker_main
t=2100    Worker: DATABASE_ROLE=worker
t=2200    Web worker 0: lifespan start, DataHub singleton, _background_update_loop
t=2200    Web worker 0: Binance WS start (if enabled)
t=2300    Web worker 0: REST loop first tick
t=2400    Worker: run_schema_guard
t=2500    Worker: ensure_running_bots
t=2600    Worker: _engine_tick_loop starts
```

## Memory Ownership

| Component | Owner | Shared? |
|-----------|-------|---------|
| DataHub.prices | Web (per process) | No; each uvicorn worker = own process = own DataHub |
| _sessions (auth) | Web | Per-process |
| bot_engine_state | SQLite | Shared via WAL |
| symbol_locks | SQLite | Shared |

## SIGTERM / Crash Behavior

| Process | SIGTERM | Crash |
|---------|---------|-------|
| Web | Uvicorn graceful shutdown | Worker dies; next request 502 |
| Worker | Loop stops; no lock release | symbol_locks lease expires in 10s (DEFAULT_LEASE_TTL_SEC) |
| Manager | Process exit | Web/Worker unaffected |

**What can go wrong here?** Worker crash leaves symbol_locks held until lease expiry (10s). Web worker B may serve empty DataHub. No coordinated shutdown; DB connections abrupt.

---

# 1B. BOT ENGINE V5 — PROCESS MODEL & SCHEDULING

## Process Model (v5)

| Process | Role | Trades? | DataHub |
|---------|------|---------|---------|
| Web | Read-only APIs, admin, dashboard snapshot | No | Own instance (per worker) |
| Worker | ONLY entity allowed to submit orders | Yes | Optional (can use HTTP to DataHub service) |
| DataHub | Single market data source (in-process or dedicated) | — | No per-symbol Binance REST fallback |

## Scheduling Model (Event-Driven, 300-Bot Ready)

- **No tick spam:** Each bot has `next_run_at` (monotonic time). Maintain min-heap of (next_run_at, bot_id).
- **Wake only bots due to run.** Additionally wake by events: price threshold, fill, risk state change.
- **Concurrency limits:** db_sem=20, compute_sem=50, binance_sem=10 (tunable).
- **Jitter:** 50–150 ms on scheduling to avoid herd.
- **Backpressure:** If Binance weight near limit => slow scheduling; if p95 bot_run_ms > threshold => reduce concurrency.

## Implementation Locations

| Component | Path |
|-----------|------|
| Scheduler | `app/botengine/scheduler.py` — BotScheduler (heap, wake_queue, semaphores) |
| One bot run | `app/botengine/bot_run.py` — run_one_bot_tick(bot_id, tick_id) → next_run_at |
| Worker integration | `app/botengine/worker_main.py` — BOT_ENGINE_V5_SCHEDULER=1 |

## Enabling v5 Scheduler

```bash
export BOT_ENGINE_V5_SCHEDULER=1
python -m app.botengine.worker_main
```

When enabled: running bots are registered with scheduler; START command registers new bot; STOP unregisters; reconciler runs every 45s.

**What can go wrong here?** With v5 disabled, legacy _bot_loop runs (one asyncio task per bot). With v5 enabled, single scheduler loop runs all bots; ensure only one worker process per shard to avoid double-trade.

---

# 1C. BOT ENGINE V5 — INTENT PIPELINE (EXACTLY-ONCE)

## State Machine

```
NEW → PERSISTED → SUBMITTING → SUBMITTED/ACKED → (PARTIAL|FILLED|CANCELED|REJECTED) → FINAL
                                                      ↑
                                            UNKNOWN (transient; reconcile resolves)
```

## Rules

| Rule | Enforcement |
|------|-------------|
| S1 | Never submit order without persisted intent record |
| S2 | Same intent_id => same clientOrderId always; no duplicates |
| S3 | After timeout/crash/unknown, reconcile from Binance before new actions for that symbol |
| S8 | Deterministic: identical inputs → identical intent_id (includes run_id to avoid restart collision) |

## intent_id Formula

`intent_id = f(bot_id, run_id, cycle_id, symbol, action_type, qty_norm, price_norm, strategy_action_hash)`

- Implemented: `bot{bot_id}_r{run_id}_cy{cycle_id}_it{hash16}` where hash16 = SHA256(symbol|side|qty|quote_qty|reason|grid_index)[:16]. **run_id** is set on each START (e.g. `cmd{command_id}`) so restarts never reuse the same origClientOrderId and cannot hit phantom "already filled" from a previous run.
- client_order_id: includes run_id segment (compact), stored on first persist; reused on every retry. Max 36 chars (Binance). Format: `b{bot_id}r{rid}c{cycle_id}i{hash}{ts}` trimmed to 36.

## Unique Constraints

- `UNIQUE(intent_id)`
- `UNIQUE(client_order_id)`

## Code

- `app/botengine/intent_ledger.py` — build_intent_id, build_client_order_id, upsert_intent, update_intent_*.

**What can go wrong here?** If intent_id is ever made non-deterministic (e.g. timestamp), retries create new intents and duplicate orders. Always derive from strategy inputs only. Without run_id, restart could reuse the same client_order_id and GET /api/v3/order could falsely match an old run's order (or -2013); run_id prevents that.

## Reconcile: NOT_FOUND vs FOUND

- GET /api/v3/order with 200 + `code != 0` (e.g. **-2013** "Order does not exist") is **NOT_FOUND**: do not repair; proceed to place. Never treat HTTP 200 alone as success; response body must have valid orderId, status, symbol, clientOrderId.
- **HTTP 400 + code -2013:** Binance may return status 400 with body `{"code":-2013,"msg":"Order does not exist."}`. `binance_spot._signed_request_impl` converts this to `BinanceSignedError(-2013, ...)` so reconcile sees NOT_FOUND; no WARNING log flood. NOT_FOUND decision is logged at DEBUG.
- **Reconcile NOT_FOUND → CANCELED:** When `reconcile_account` does not find an order on Binance (openOrders, get_order_by_client_order_id, allOrders), it marks the intent as CANCELED so the same intent is not re-queried every 45s. Log: `RECONCILE_NOT_FOUND account_id=... intent_id=... => CANCELED (stop re-query)`.
- **Verify-before-repair:** Before marking intent FILLED from reconcile, call GET /api/v3/myTrades filtered by orderId. If no trades match that orderId → treat as NOT_FOUND and place order. Only repair (update intent FILLED, apply_fill, record_trade) when myTrades confirms the orderId. Log: `INITIAL_ALLOC_VERIFY result=OK|FAIL orderId=... trades_match_count=...`.
- Forensic logs: `RECONCILE_QUERY`, `RECONCILE_RESPONSE_BODY` (truncated), `RECONCILE_DECISION`; `EXEC_ORDER_ATTEMPT` (run_id, intent_id, coid); `BINANCE_PLACE_ORDER` (coid, testnet).

---

# 1D. BOT ENGINE V5 — DB SCHEMA (order_intents)

## Full Table Definition

```sql
CREATE TABLE order_intents (
  id INTEGER PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE,
  bot_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL DEFAULT 'MARKET',
  qty REAL NOT NULL,
  price REAL NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  client_order_id TEXT NOT NULL UNIQUE,
  binance_order_id TEXT NULL,
  status TEXT NOT NULL DEFAULT 'NEW',
  submit_attempts INTEGER NOT NULL DEFAULT 0,
  last_submit_ts REAL NULL,
  filled_qty REAL NOT NULL DEFAULT 0,
  avg_price REAL NULL,
  last_error_code TEXT NULL,
  last_error_id TEXT NULL,
  final_ts REAL NULL,
  metadata_json TEXT
);
```

## Indices

| Index | Columns |
|-------|---------|
| ix_order_intents_intent_id | (intent_id) |
| ix_order_intents_client_order_id | (client_order_id) UNIQUE |
| ix_order_intents_account_status | (account_id, status) |
| ix_order_intents_bot_status | (bot_id, status) |
| ix_order_intents_symbol_status | (symbol, status) |
| ix_order_intents_binance_order_id | (binance_order_id) |

## WAL

SQLite: `PRAGMA journal_mode=WAL`; `PRAGMA synchronous=NORMAL` (app/db/base.py connect hook).

**What can go wrong here?** Migrations add columns to existing table; new installs get full schema. If UNIQUE(client_order_id) is missing, duplicate clientOrderId possible on retry.

---

# 1E. BOT ENGINE V5 — RECONCILIATION (BINANCE TRUTH)

## When Reconcile Runs

- On worker startup: reconcile all non-final intents (per account).
- Before any new submit on (account_id, symbol): if inflight intents exist, reconcile first.
- Periodic: every 30–60 s (configurable; default 45 s in worker).

## Algorithm

1. List non-final intents for account.
2. Fetch openOrders (all or per symbol).
3. For each intent: try get_order_by_client_order_id(symbol, client_order_id). If not in open, try allOrders(symbol, limit=20).
4. Match by clientOrderId (exact). Update intent: status, binance_order_id, filled_qty, avg_price, final_ts.
5. Metrics: reconcile_matches_total.

## Code

- `app/botengine/reconcile.py` — reconcile_account(account_id, get_open_orders, get_all_orders, get_order_by_client_order_id, db).

**What can go wrong here?** allOrders returns recent orders only; very old UNKNOWN intent may never match (consider marking REJECTED after N days).

---

# 1F. BOT ENGINE V5 — LOCK LIFECYCLE (LEASE + HEARTBEAT)

## Parameters

| Parameter | Value | Location |
|-----------|-------|----------|
| DEFAULT_LEASE_TTL_SEC | 10 | locks.py |
| HEARTBEAT_RENEWAL_INTERVAL_SEC | 3 | locks.py |

## Lifecycle

1. **Acquire:** try_acquire_symbol_lock(db, account_id, symbol, bot_id, ttl_sec). UPDATE if lease_until < now OR owner_bot_id = bot_id; else INSERT if no row.
2. **Hold:** While bot run executes, background task calls renew_symbol_lock every 3 s.
3. **Release:** In finally block: release_symbol_lock(db, account_id, symbol, bot_id). Idempotent.

## Context Manager

- `symbol_lock_with_heartbeat(account_id, symbol, bot_id, ttl_sec=10, heartbeat_interval_sec=3, get_db=...)` — async context manager; acquires, runs heartbeat task, guarantees release in finally.

## Fail-Safe

- If heartbeat renew fails => log lock_heartbeat_fail; caller must stop submits, release if possible, schedule retry.
- **Submit guard (zorunlu):** Order göndermeden hemen önce `lease_still_valid(db, account_id, symbol, bot_id)` çağrılmalıdır. False ise submit yapılmaz, kilit bırakılır, LOCK_LEASE_EXPIRED event yazılır (orchestrator.py).

**What can go wrong here?** Long GC pause can prevent heartbeat; lease expires; another bot acquires lock and may submit; first bot may still try to submit. Mitigation: short lease (10 s); submit timeout 3 s; lease_still_valid check before run_actions.

---

# 1G. BOT ENGINE V5 — WEIGHT GOVERNOR & BACKPRESSURE

## Sliding Window

- 60 s window; BINANCE_WEIGHT_LIMIT_PER_MIN = 1200 (typical IP limit).
- request_weight_tokens(account_id, api_key, weight) => True if allowed, False if denied.
- Denied => do NOT call Binance; return dependency_degraded; schedule delayed retry.

## Endpoint Weights

| Endpoint | Weight |
|----------|--------|
| /api/v3/account | 10 |
| /api/v3/order (POST/DELETE) | 1 |
| /api/v3/openOrders, /api/v3/allOrders | 10 |
| /api/v3/time | 1 |

## SAFE MODE

When weight used (60 s) / limit >= 0.85: allow reconcile calls, deny new submits; scheduler slows (sleep 0.5 s).

## Code

- `app/services/binance_weight.py` — request_weight_tokens, record_weight_used, get_weight_used_last_60s.
- `app/botengine/execution.py` — before place_order: request_weight_tokens; if False, update_intent_unknown(WEIGHT_DENIED).

**What can go wrong here?** Multiple workers share no in-memory weight state; each process has own sliding window. For multi-worker, use per-API-key budget or external rate limiter.

---

# 1H. BOT ENGINE V5 — ERROR TAXONOMY & RETRY

## Typed Errors (app/botengine/errors.py)

| error_code | Retry Policy |
|------------|--------------|
| validation_error | never |
| auth_error | never |
| dependency_failure | circuit_breaker |
| rate_limited | backoff |
| timeout | reconcile_only (no blind resubmit) |
| lock_conflict | backoff |
| data_stale | never |
| state_corruption | never |
| weight_denied | backoff |
| kill_switch | never |

Every error: error_code, error_id, request_id, context.

## Retry Matrix

- **rate_limited:** Backoff + jitter; obey weight governor.
- **timeout:** Mark intent UNKNOWN; reconcile; do not blind retry submit.
- **dependency_failure:** Circuit breaker per account.
- **validation_error:** No retry.

## Kill Switch

- Global: `BOT_ENGINE_KILL_SWITCH=1` or set_kill_switch(True). check_kill_switch() before submit; raises KillSwitchError.

**What can go wrong here?** Blind retry on timeout can duplicate order; v5 forbids it and uses reconcile.

---

# 1I. BOT ENGINE V5 — 300-BOT CAPACITY MODEL

## Limits (Tunable)

| Resource | Default | Notes |
|----------|---------|-------|
| db_sem | 20 | Concurrent DB operations |
| compute_sem | 50 | Concurrent bot runs |
| binance_sem | 10 | Concurrent Binance calls |
| Weight limit 60 s | 1200 | Per IP/API key |

## Recommended for 300 Bots

- **Worker processes:** 1–2 per machine; shard by account_id (no shared trading for same account).
- **DB:** Postgres recommended for 300 bots; SQLite WAL OK for lower concurrency.
- **CPU/RAM:** 2+ cores; 2 GB+ RAM for worker.
- **Disk IOPS:** Sufficient for WAL and state writes.

## Sharding Strategy

- Shard by account_id across N worker processes. Each account owned by exactly one worker; no double-trade.

## 200 / 300 Bot: Ne Zaman “Hızlı ve Stabil”?

| Koşul | Sonuç |
|--------|--------|
| **v5 açık** (`BOT_ENGINE_V5_SCHEDULER=1`) + weight governor çalışıyor + DB contention kontrol altında | 200 bot **hızlı ve stabil** olabilir. Concurrency limitleri, backpressure ve weight governor bu model için tasarlandı. |
| **v5 kapalı** (legacy “bot başına ayrı loop”) | 200 botta “hızlı” demek **riskli**; garanti yok. |

### Kesin kontrol

200 bot için “hızlı olma” ihtimali yüksekse worker şöyle çalışıyor olmalı:

```bash
export BOT_ENGINE_V5_SCHEDULER=1
python -m app.botengine.worker_main
```

### En büyük 3 tavan (200+ bot)

1. **DB contention (özellikle SQLite):** 300 bot için doküman Postgres öneriyor; SQLite’da lock contention riski var.
2. **Binance weight:** Limit ~%85’e gelince SAFE MODE (reconcile var, yeni submit yok) devreye girer; bu “hız” değil **güvenli degrade**.
3. **Lock/lease:** Worker crash’te lock **10 s** (DEFAULT_LEASE_TTL_SEC) sonra serbest kalır; heartbeat 3 s. 200 botta aynı anda çok lock expirasyonu domino etkisi yaratabilir — tek worker, kısa lease (10 s) ile sınırlı kalır.

**Özet:** v5 açık + weight governor + DB (tercihen Postgres) kontrol altında ⇒ 200 bot hızlı/stabil olabilir. v5 kapalı ⇒ 200 botta hızlılık garanti değil.

**Degradation threshold (doküman):** SECTION O/M’de **50 bot** “max bot count before degradation” önerisi var; tek node + mevcut limitlerle 50 üstü degradation riski. v5 kapalı (legacy “bot başına ayrı loop”) iken bu eşik geçerli. **BOT_ENGINE_V5_SCHEDULER** env default **0**; event-driven scheduler her ortamda açık değilse throughput/latency karakteri legacy’e göre değişir.

**What can go wrong here?** Single SQLite under 300 bots can hit lock contention; monitor BUSY and consider Postgres.

---

# 1J. BOT ENGINE V5 — INCIDENT PLAYBOOKS

## Duplicate Order Prevention Proof

| Step | Action | Result |
|------|--------|--------|
| 1 | Bot builds intent_id (deterministic), upsert_intent → PERSISTED, client_order_id stored | One row per logical intent |
| 2 | place_order(symbol, client_order_id) | Binance receives clientOrderId |
| 3 | Timeout before response | execution marks intent UNKNOWN |
| 4 | No blind resubmit | Reconcile runs |
| 5 | get_order_by_client_order_id(symbol, client_order_id) | Finds order; update intent FILLED |
| 6 | Next tick: intent already FILLED | Skip place; no duplicate |

## Rate-Limit Cascade Prevention

- Weight governor denies when used + requested > limit. Caller gets dependency_degraded; no submit.
- SAFE MODE: scheduler sleeps; reconcile still allowed.

## WS Down (DataHub Stale)

- UI: serve stale with is_stale flag (DATAHUB_SERVE_STALE_FOR_UI).
- Bot: get_price() returns None when stale; no new intents; can still reconcile.

---

# 1K. BOT ENGINE V5 — VERIFICATION COMMANDS

```bash
# Run intent idempotency tests
python3 -m pytest tests/test_intent_idempotency.py -v

# Reconcile now (one or all accounts)
python3 scripts/reconcile_now.py [account_id]

# Intent audit
python3 scripts/intent_audit.py [--account N] [--bot N] [--status STATUS]

# Perf 300 bots sim (no real DB)
python3 scripts/perf_300_bots_sim.py

# Weight simulator
python3 scripts/binance_weight_sim.py --users 10 --poll 3 --trades 2

# Order intents (SQLite)
sqlite3 ~/.trader/dca.db "SELECT intent_id, status, client_order_id, binance_order_id, submit_attempts FROM order_intents ORDER BY id DESC LIMIT 20;"

# Kill switch (env)
export BOT_ENGINE_KILL_SWITCH=1
```

---

# 1L. BOT ENGINE V5 — OBSERVABILITY

## Structured Logs (JSON-capable)

- request_id (web), worker_id, bot_id, tick_id, intent_id, client_order_id, binance_order_id, duration_ms per stage.

## Metrics

| Metric | Meaning |
|--------|---------|
| bot_run_ms (p50/p95) | Scheduler tracks last N runs |
| scheduler_queue_depth | heap size + wake_queue size |
| intents_inflight | COUNT status IN (PERSISTED, SUBMITTING, SUBMITTED, UNKNOWN, ...) |
| intents_unknown | COUNT status = 'UNKNOWN' |
| lock_wait_ms / lock_hold_ms | From locks if instrumented |
| binance_weight_used_60s / denied | binance_weight.get_weight_used_last_60s, get_weight_denied_count |
| submit_success / fail / timeout | From execution logs |
| reconcile_matches_total | reconcile.py global counter |

## User Data Stream (Optional)

- `app/botengine/user_stream.py` — TODO: listenKey WS; executionReport for fills. Mitigation: REST reconcile bounded and weight-governed.

---

# 2. DATA FLOW — END TO END

## A) Dashboard Load (Mobile + Desktop)

| Phase | Trigger | Internal | External | Locks | Max Time | Abort |
|-------|---------|----------|----------|-------|----------|-------|
| 1 | User opens dashboard | — | — | — | — | — |
| 2 | intervalRegistry.start('dashboard_snapshot', fetchSnapshot, 3000) | — | — | — | — | — |
| 3 | fetchSnapshot() | State.inFlight check | — | — | — | If inFlight \|\| !accountId \|\| spot modal → return |
| 4 | apiClient('/api/dashboard/snapshot?account_id=X', {timeout:12000}) | _acquireSlot (max 2) | GET | Slot | 12000ms | Timeout; _releaseSlot |
| 5 | Backend api_dashboard_snapshot | require_auth | — | — | — | 401 if no token |
| 6 | asyncio.gather(4 tasks) | fetch_prices, wallet, bots, pnl | — | — | 3000ms each | _error in result |
| 7 | fetch_prices | data_hub.get_all_prices (run_in_executor) | None | — | 3000ms | {"_error":"timeout"} |
| 8 | _fetch_wallet_uncached | — | Binance GET /api/v3/account | — | 4s | DependencyFailure |
| 9 | Response merge | — | — | — | — | Partial on _error |

**Slow path:** Binance slow → wallet task 3s → partial response.  
**Failure path:** Circuit open → wallet _error; prices from DataHub.

## B) Bot Trade Cycle

| Phase | Internal | External | Locks | Max Time |
|-------|----------|----------|-------|----------|
| 1 | load_state | — | — | — |
| 2 | adapter.get_price(symbol) | DataHub | — | — |
| 3 | if None (stale) → skip | — | — | — |
| 4 | try_acquire_symbol_lock | — | symbol_locks | — |
| 5 | Strategy decision | — | — | — |
| 6 | place_order | Binance POST /api/v3/order | — | 4s |
| 7 | release_symbol_lock | — | symbol_locks | — |
| 8 | save_state | — | — | — |

## C) Snapshot Sub-Task Timeouts

| Task | Timeout (s) | On Timeout |
|------|-------------|------------|
| fetch_prices | 3 | {"_error":"timeout"} |
| _fetch_wallet_uncached | 3 (httpx) + 4 (wait_for) | DependencyFailure |
| fetch_bots_and_account_kpis | 3 | {"_error":"timeout"} |
| fetch_finance_pnl | 3 | {"_error":"timeout"} |

## D) Binance WS Reconnect Flow

| Phase | Trigger | Internal | External | Max Time |
|-------|---------|----------|----------|----------|
| 1 | WS disconnect | — | — | — |
| 2 | Reconnect loop | DataHub._ws_client | wss://stream.binance.com | Exponential backoff (UNKNOWN) |
| 3 | ws_status | "reconnecting" | — | — |
| 4 | REST loop | refresh_all_prices_bulk when WS stale | Binance REST | BULK_REFRESH_MIN_INTERVAL 10s |
| 5 | WS connected | last_ws_update_ts updated | — | ws_status "connected" |

**WS sends nothing 10 min:** WS_STALE_SEC=60 → after 60s ws_status "stale"; REST runs every 1.5s; prices stay fresh.

## E) Worker Restart Flow

| Phase | Trigger | Internal | External | Timing |
|-------|---------|----------|----------|--------|
| 1 | worker-restart | Helper kills worker PID | — | SIGTERM, 1s, SIGKILL |
| 2 | Worker exit | — | — | — |
| 3 | start/helper worker-start | nohup python -m app.botengine.worker_main | — | — |
| 4 | Worker boot | run_schema_guard | DB | — |
| 5 | ensure_running_bots | SELECT Bot WHERE status='running' | — | — |
| 6 | Orchestrator | Load each bot, _bot_loop | — | — |

**Gap:** No ticks during restart (typically 2–5s). symbol_locks: lease expires 10s; no explicit release on kill.

## F) User Login / Session Flow

| Phase | Trigger | Internal | External | Locks |
|-------|---------|----------|----------|-------|
| 1 | POST /api/auth/login | bcrypt verify, DB User | — | — |
| 2 | Token | secrets.token_urlsafe(32) | — | — |
| 3 | _session_set(token, user_id, account_id, is_admin) | In-memory _sessions | — | — |
| 4 | Response | Set-Cookie auth_token | — | — |
| 5 | Subsequent request | Bearer or Cookie → require_auth | _session_get (auth_sessions DB; no boot_id in acceptance) | — |

**Failure:** Session not found / expired / revoked → 401; user must re-login. boot_id is diagnostics-only (multi-worker safe). Dashboard/admin init: on boot_id mismatch do soft-refresh (update localStorage boot_id, optional toast "Sunucu güncellendi. Bağlantı yenilendi.", run whoami); only if whoami returns 401 SESSION_NOT_FOUND/UNAUTHORIZED then clear auth and redirect with ?session_expired=1. apiClient 401 logout reasons: only UNAUTHORIZED and SESSION_NOT_FOUND (BOOT_ID_MISMATCH removed). redirectToLoginOnce(true) sets ?session_expired=1 so login shows "Oturumunuz sona erdi (sunucu yeniden başladı)" only when actual auth failed.

## Failure Mapping — Snapshot

| Failure | Layer | Detection | Mitigation |
|---------|-------|-----------|------------|
| fetch_prices timeout | dashboard_snapshot | {"_error":"timeout"} | Reduce DataHub load |
| fetch_wallet DependencyFailure | binance_spot | circuit open | Wait 30s |
| fetch_bots timeout | dashboard_snapshot | {"_error":"timeout"} | DB performance |
| fetch_pnl timeout | dashboard_snapshot | {"_error":"timeout"} | DB performance |
| UI 12s timeout | apiClient | Promise reject | Increase or reduce payload |
| Slot queue overflow | apiClient | Queue grows | MAX_CONCURRENT=2 limits |

## Failure Mapping — Bot Trade

| Failure | Layer | Detection | Mitigation |
|---------|-------|-----------|------------|
| Price None (stale) | DataHub | Skip tick | REST refresh |
| Lock busy | locks | try_acquire returns False | Skip; retry next tick |
| place_order DependencyFailure | binance_spot | Exception | Circuit; retry next tick |
| place_order timeout | binance_spot | 4s cap | DependencyFailure |
| save_state exception | state_store | Log; state may be stale | Ensure atomic |
| Worker crash | Process | PID dead | Restart; lock expires 10s |

## Failure Mapping — Login

| Failure | Layer | Detection | Mitigation |
|---------|-------|-----------|------------|
| Invalid credentials | auth | 401 | User retry |
| Session not found / expired / revoked | auth | 401 | Re-login |
| Banned IP | auth | 403 | Unban |

---

# 3. TIME & LATENCY MODEL

## Numeric Budgets

| Endpoint/Task | Target (ms) | Max (ms) | On Exceed |
|---------------|-------------|----------|-----------|
| GET /api/dashboard/snapshot | 500 | 12000 (UI) | UI abort |
| Binance REST | 200 | 4000 | DependencyFailure |
| Snapshot task | 300 | 3000 | _error |
| apiClient DEFAULT_TIMEOUT | — | 5000 | Promise reject |
| apiClient snapshot override | — | 12000 | Promise reject |

**What can go wrong here?** Snapshot has no server-side total timeout; slow DB can push total > 12s; UI aborts while backend still working.

## Retry Logic (Explicit)

| System | Retries | Backoff | Total Cap | Cancellation |
|--------|---------|---------|-----------|--------------|
| Binance REST | 2 (3 attempts) | 0.5s, 1s | 4s | asyncio.wait_for cancels on timeout |
| Circuit breaker | — | 30s open | — | — |
| Snapshot task | 0 | — | 3s | asyncio.TimeoutError; returns _error |
| apiClient | 0 | — | 5s or 12s | Promise reject; caller handles |
| Symbol lock | 0 | — | — | Returns False; no retry in same tick |

## Complete Retry Reference (All Systems)

| System | Max Attempts | Backoff | Timeout | On Exhaust |
|--------|--------------|---------|---------|------------|
| Binance REST | 3 (1+2 retries) | 0.5s, 1s | 4s | DependencyFailure |
| Binance 429/418 | Same | Same | Same | Same |
| Snapshot task | 1 | — | 3s | _error in result |
| apiClient | 1 | — | 5s or 12s | Promise reject |
| Symbol lock | 1 | — | — | False |
| Circuit breaker | 1 probe (half_open) | 30s | — | Open again |
| WS reconnect | Infinite | Exponential | — | — |
| DB transaction | 0 (no retry) | — | — | Exception |

## Async Cancellation Behavior

| Operation | On Cancel | On Timeout |
|-----------|-----------|------------|
| asyncio.wait_for(coro, 3) | CancelledError | TimeoutError |
| Binance httpx request | Request cancelled | Timeout |
| run_in_executor | — | wait_for raises TimeoutError |
| asyncio.gather | First exception propagates | Task returns _error |

## Async Boundaries (Complete)

| Boundary | Caller | Callee | Blocking? | Timeout |
|----------|--------|--------|-----------|---------|
| apiClient fetch | UI | Backend | No (Promise) | 5s or 12s |
| Snapshot asyncio.gather | routes | 4 tasks | No | 3s each |
| fetch_prices run_in_executor | dashboard_snapshot | data_hub.get_all_prices | Sync in thread | 3s |
| Binance _signed_request | binance_spot | httpx | No | 4s total |
| DataHub _background_update_loop | lifespan | Binance REST | No | Per call |
| _bot_loop | orchestrator | strategy, execution | No | Per tick |
| place_order | execution | binance_spot | No | 4s |
| load_state / save_state | orchestrator | state_store | Sync (DB) | None |
| try_acquire_symbol_lock | orchestrator | locks | Sync (DB) | None |

## External Dependency Budgets

| Dependency | Budget | Failure Isolation | Fallback |
|------------|--------|-------------------|----------|
| Binance REST | 4s total, 3 attempts | Circuit breaker 30s | Stale data; _error |
| Binance WS | — | No circuit | REST bulk takes over |
| SQLite | No explicit timeout | — | Exception to caller |
| DataHub get_all_prices | 3s (snapshot task) | _error in result | Empty prices |
| Snapshot endpoint | 12s (UI) | UI timeout | User sees stale/error |

## Failure Path Matrix (Critical Flows)

| Flow | Happy | Slow | Failure |
|------|-------|------|---------|
| Snapshot | 200–500ms, full data | 2–5s, partial | Timeout; _error; circuit open |
| Bot tick | price→lock→order→save | Binance slow; skip | Stale price; lock busy; DependencyFailure |
| Login | Token; session | — | 401; boot_id mismatch |
| WS | Connected; prices stream | Reconnecting | REST fallback |

## Timeout Values (All Numeric)

| Constant | Value | Location |
|----------|-------|----------|
| BINANCE_REQUEST_TIMEOUT_SEC | 4.0 | binance_spot.py |
| BINANCE_HTTP_TIMEOUT | 3.0 connect, 2.0 read | binance_spot.py |
| SNAPSHOT_TASK_TIMEOUT | 3.0 | dashboard_snapshot.py |
| DEFAULT_TIMEOUT (apiClient) | 5000 | apiClient.js |
| Snapshot fetch timeout | 12000 | dashboard.js |
| SNAPSHOT_POLL_MS | 5000 | dashboard.js |
| DEFAULT_LEASE_TTL_SEC | 10 | locks.py (heartbeat 3s) |
| PRICE_TTL | 120 | data_hub.py |
| WS_STALE_SEC | 60 | data_hub.py |
| BULK_REFRESH_MIN_INTERVAL | 10 | data_hub.py |

---

# 4. DATAHUB — COMPLETE TRUTH MODEL

## In-Memory Structures (Exact)

```
DataHub:
  prices: Dict[str, Dict]           # symbol -> {price, change24h, volume24h, ts}
  _MAX_PRICES: int = 600
  coin_list: List[Dict]
  coin_list_ts: float
  account_balances: Dict[int, Dict] # account_id -> {data, ts}
  _MAX_ACCOUNT_BALANCES: int = 50
  top_100_symbols: List[str]
  all_symbols: List[str]
  all_symbols_ts: float
  _mini_ws: Dict[str, Dict]         # symbol -> {last, open, changePct, volume, quoteVolume}
  _MAX_MINI_WS: int = 600
  ws_status: str                    # connected|reconnecting|disabled|rest
  last_ws_update_ts: float
  _refresh_inflight: Optional[asyncio.Task]
  _last_bulk_refresh_ts: float
  PRICE_TTL: float = 120.0
  BULK_REFRESH_MIN_INTERVAL: float = 10.0
  REST_PRICE_INTERVAL_WHEN_WS: float = 10.0
  PRICE_UPDATE_INTERVAL: float = 1.5
  WS_STALE_SEC: float = 60.0
```

## Stale Definition (Math)

- `age = now - data["ts"]`
- `is_stale = age > PRICE_TTL` (120 seconds)
- Bot: `get_price_with_meta().is_stale == True` → returns None (never trade)
- UI: `DATAHUB_SERVE_STALE_FOR_UI=1` → returns price even when stale

## Eviction Rules

- prices: when len > 600; keep top_100 + coin_list symbols; then most recent by ts
- _mini_ws: when len > 600; keep first 600 keys
- account_balances: when len > 50; evict oldest by ts

## Lifecycle of a Price (Step-by-Step)

1. **Insert:** REST bulk ticker/price or ticker/24hr → `prices[sym] = {price, change24h, volume24h, ts}`
2. **Update:** WS mini ticker → `_mini_ws[sym]`; merged on get; or REST update_ticker_24h overwrites
3. **Read:** get_price(sym), get_price_with_meta(sym), get_all_prices()
4. **Stale check:** `age = now - data["ts"]`; `is_stale = age > 120`
5. **Eviction:** _trim_prices when len > 600; prefer top_100, coin_list; then most recent ts

## What Happens If WS Sends Nothing for 10 Minutes

- t=0: WS last message
- t=60: WS_STALE_SEC reached; ws_status becomes "stale"
- t=60+: REST loop uses PRICE_UPDATE_INTERVAL 1.5s; refresh_all_prices_bulk every 1.5s
- BULK_REFRESH_MIN_INTERVAL 10s still applies; effective refresh every 10s when WS was "ok", 1.5s when stale
- Prices stay fresh via REST; get_status() stale_symbols_count based on PRICE_TTL 120s

## What Happens If REST Returns Partial Symbols

- Binance ticker/price (no symbol param) returns all symbols; partial would mean HTTP error
- On exception: no update; existing prices age
- Stale count increases; bot may get None for symbol

## WS vs REST Arbitration

| Condition | REST Interval |
|-----------|---------------|
| WS connected, last_ws_update_ts < 60s | 10s (REST_PRICE_INTERVAL_WHEN_WS) |
| WS stale or disabled | 1.5s (PRICE_UPDATE_INTERVAL) |

**What can go wrong here?** Two Web workers = two DataHubs; first request to worker B may get empty prices. Eviction can drop symbol needed by bot.

---

# 5. SNAPSHOT ARCHITECTURE

## Required Fields

| Field | Source | Required |
|-------|--------|----------|
| prices | DataHub.get_all_prices | Yes |
| wallet | Binance or _error | Yes |
| bots | DB + PnlService | Yes |
| account | DB + wallet merge | Yes |
| pnl | FinancePnlCalculator | Yes |
| server_ts | time.time() | Yes |

## Forbidden Additions

- Raw API keys
- Unbounded lists (e.g. all trades)
- Per-symbol Binance calls

## Parallelism

- 4 tasks via asyncio.gather
- 3s timeout per task

**What can go wrong here?** Adding a 5th task that blocks 10s stalls whole snapshot. No payload size budget enforced.

---

# 6. BINANCE DEPENDENCY MODEL

## Endpoints & Weights (Full)

| Endpoint | Weight | Used By | Frequency |
|----------|--------|---------|-----------|
| GET /api/v3/ticker/price (no symbol) | 2 | DataHub refresh_all_prices_bulk | 1/10s (BULK_REFRESH_MIN_INTERVAL) |
| GET /api/v3/ticker/24hr | 1-40 | DataHub update_ticker_24h | 1/5s |
| GET /api/v3/exchangeInfo | 10 | DataHub update_all_symbols, binance_client | 1/600s |
| GET /api/v3/account | 10 | Snapshot _fetch_wallet | Per snapshot (1/3s per user) |
| POST /api/v3/order | 1 | Worker execution | On trade |
| GET /api/v3/time | 1 | Signed requests | Per signed call; cached 30s |
| GET /sapi/v1/asset/tradeFee | 1 | Fee rates | On demand |
| DELETE /api/v3/order | 1 | cancel_order | On cancel |
| GET /api/v3/openOrders | 2-5 | get_open_orders | On demand |

## Circuit Breaker

| State | Condition | Behavior |
|-------|-----------|----------|
| closed | Normal | Allowed |
| open | 3 consecutive failures | DependencyFailure immediately |
| half_open | 30s after open | 1 probe |

- FAILURE_THRESHOLD = 3
- OPEN_SECONDS = 30.0

**What can go wrong here?** Circuit is global; one account 401 can trip breaker for all. No weight tracking; may hit Binance limit.

---

# 7. DATABASE — REAL BEHAVIOR

## SQLite WAL

- PRAGMA journal_mode=WAL
- PRAGMA synchronous=NORMAL
- Readers don't block writers; writers don't block readers

## Engine Config

- pool_size=10, max_overflow=20
- pool_pre_ping=True
- pool_recycle=3600

## Default Path

- `~/.trader/dca.db` (DATABASE_URL env overrides)

**What can go wrong here?** WAL file can grow; disk full. No automated backup. SQLITE_BUSY under heavy write.

---

# 8. WORKER ENGINE — FAILURE-FIRST VIEW

## State Machine

- Mode: IDLE | RUNNING | STOPPED | ERROR | TRAIL_* | etc.
- cycle_id: Increments on strategy-defined cycle completion
- state_version: Increments on each save (optimistic locking)

## Bot Engine Mode States (DCA/Grid/Trailing)

| Mode | Description | Next Modes |
|------|-------------|------------|
| IDLE | No active trail | TRAIL_SELL_GRID, TRAIL_BUY_GRID |
| TRAIL_SELL_GRID | Selling up grid | TRAIL_REENTRY_BUY, TRAIL_PROFIT_SELL |
| TRAIL_BUY_GRID | Buying down grid | TRAIL_SELL_GRID |
| TRAIL_REENTRY_BUY | Re-entry after profit | TRAIL_SELL_GRID |
| TRAIL_PROFIT_SELL | Profit exit | TRAIL_REENTRY_BUY |

## Bot Status (DB)

| Status | Description | Worker Behavior |
|--------|-------------|-----------------|
| stopped | Bot not running | No tick |
| running | Bot active | Tick loop |
| paused | User paused | No tick |
| paused_error | Error paused | Tick may retry (config) |

## Lock Lifecycle

- Acquire: try_acquire_symbol_lock (UPDATE or INSERT)
- Release: release_symbol_lock (UPDATE owner_bot_id=0)
- Crash: No explicit release; lease expires in 10s

## Idempotency

- No client_order_id idempotency key sent to Binance
- Duplicate order possible if crash after place_order, before save_state (see Section C)

**What can go wrong here?** Crash after order, before save: duplicate possible. Lock expiry 10s (v5) limits exposure; reconcile resolves UNKNOWN intents.

---

# 9. UI — MOBILE-FIRST FAILURE ANALYSIS

## Constraints

| Constraint | Value |
|------------|-------|
| MAX_CONCURRENT_REQUESTS | 2 |
| SNAPSHOT_POLL_MS | 3000 |
| visibilityState hidden | Skips interval tick |

## Why Mobile Fails First

- Slower network → more timeouts
- 12s snapshot timeout on slow 3G can be exceeded
- visibilityState hidden → no poll when backgrounded

**What can go wrong here?** "Nothing loads": 5s/12s timeout; inFlight stuck if promise never resolves; visibility hidden skips retry.

---

# 10. SECURITY & DAMAGE BOUNDARIES

## API Key Leak

- Attacker can place orders, read wallet
- Max damage: Full wallet for that account
- Mitigation: Fernet at rest; rotate in Binance

## Session Hijack

- Attacker has token; can act as user
- boot_id invalidates on server restart
- Max damage: UI actions (start/stop bots)

## Emergency Shutdown

- BREACH_SHUTDOWN=1: Lockdown mode
- Revoke API keys in Binance UI

**What can go wrong here?** API key in .env committed. Session cookie sent over HTTP. Admin endpoint hit without auth (require_admin protects).

---

# 11. OBSERVABILITY

## Log Examples

```
snapshot_served wallet_source=db_snapshot wallet_age_sec=12.5 request_id=... payload_bytes=... server_ms=... fields=...
wallet_refresh_attempt error_code=BINANCE_TIMEOUT duration_ms=6000 request_id=... account_id=1
wallet_refresh_success asset_count=5 total_usd=1234.56 request_id=... account_id=1 duration_ms=1200
BOT_PRICE bot_id=1 status=STALE symbol=BTCUSDT
BOT_STATE_SAVED bot_id=1 ver=5 ia_done=True hash=abc123
```
Snapshot wallet is cache-only; "[snapshot] wallet timeout" no longer occurs. Live wallet only via POST /api/home/wallet/refresh.

## Log Format

- `%(asctime)s - %(name)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s`
- Date: Europe/Istanbul
- File: logs/app.log (10MB, 5 backups)

---

# 12. INCIDENT PLAYBOOKS

## WS Down

| Step | Action | Verification |
|------|--------|--------------|
| 1 | GET /api/datahub/status | ws_status "rest" or "stale" |
| 2 | Check last_ws_message_ts | Age > 60s |
| 3 | No immediate fix | REST continues; prices from bulk |
| 4 | Inspect Binance WS status page | External outage |
| 5 | Check logs for reconnect errors | Application bug |

## Binance Rate Limit

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Check 429 in logs | binance_spot path, status 429 |
| 2 | Circuit breaker state | debug/metrics or CircuitBreaker.get_state() |
| 3 | Wait 30s | Circuit half-open; 1 probe |
| 4 | Reduce snapshot poll | SNAPSHOT_POLL_MS 5000 |
| 5 | Verify no per-symbol calls | Grep ticker/price?symbol |

## DB Locked

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Check SQLITE_BUSY in logs | Exception type |
| 2 | PRAGMA wal_checkpoint | Reduce WAL size |
| 3 | Check long transactions | DB debug |
| 4 | Reduce write load | Stop non-critical bots |
| 5 | Add PRAGMA busy_timeout | 5000 ms |

## Worker Crash

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Check .run/worker.pid | kill -0 $(cat .run/worker.pid) |
| 2 | Check logs/worker.log | Exception; last BOT_LOOP |
| 3 | worker-restart or start.command | New worker PID |
| 4 | ensure_running_bots | Bots resume |
| 5 | symbol_locks | Lease expires 60s; no manual clear |

## Mobile "Nothing Loads"

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Network tab | Snapshot 404/503/timeout |
| 2 | Console | JS error |
| 3 | visibilityState | hidden → poll skipped |
| 4 | Refresh | Retry |
| 5 | WiFi vs 3G | Network quality |
| 6 | Server health | GET /api/health |

---

# 13. DEPLOYMENT & ENVIRONMENT

## Dev vs Prod

- ENV: "" or "dev" vs "prod"
- DEBUG_METRICS: 1 vs 0

## Assumptions

- **UNKNOWN** if reverse proxy (Cloudflare/Nginx) in front
- If proxy: timeout must be >12s for snapshot

---

# 14. PERFORMANCE NON-REGRESSION LAW

## Hard Rules

| Rule | Enforcement |
|------|-------------|
| No per-symbol ticker/price | RuntimeError guard |
| No direct setInterval | intervalRegistry |
| Binance retry ≤4s | BINANCE_REQUEST_TIMEOUT_SEC=4 |
| Max 2 concurrent HTTP (UI) | apiClient _acquireSlot |

---

# 15. UNKNOWN ZONES

| Zone | Why It Matters | How to Measure | Risk If Ignored |
|------|----------------|----------------|-----------------|
| Snapshot JSON size | Mobile timeout | Content-Length | Mobile failures |
| Binance weight budget | Rate limit | Track weight/request | 429 cascade |
| DB growth rate | Disk full | Row counts | Crash |
| Two-DataHub workers | Cache split | Compare prices len | First-hit empty |

---

# 16. SYSTEM OWNERSHIP MANIFEST

## Golden Rules

1. Bot never trades on stale price
2. Only Worker places orders
3. No per-symbol Binance REST
4. Snapshot tasks run in parallel with timeout
5. Sessions ephemeral; boot_id invalidates on restart

## Red Flags

- New Binance call with symbol param
- Sync blocking in async path
- Snapshot task without timeout
- Direct setInterval

---

# SECTION A — FULL SOURCE MAP

## API Endpoint Inventory (Critical Paths)

| Method | Path | Auth | DB | Binance | Purpose |
|--------|------|------|-----|---------|---------|
| GET | /api/health | No | No | No | Health check |
| GET | /api/home/config | No | No | No | Flash Home feature flag + refresh policy |
| GET | /api/home/fast | Yes | Yes | No | Homepage cached payload (no Binance; Patch H) |
| POST | /api/home/wallet/refresh | Yes | Yes | Yes (account) | Wallet refresh TTL+dedup (Patch H) |
| GET | /api/home/wallet/status | Yes | Yes | No | Wallet refresh status + keys_configured, last_snapshot_at (Patch H) |
| GET | /api/dashboard/snapshot | Yes | Yes | Yes (account) | Aggregated dashboard |
| GET | /api/datahub/status | Yes | No | No | DataHub status |
| GET | /api/datahub/prices | Yes | No | No | DataHub get_all_prices |
| POST | /api/auth/login | No | Yes | No | Login |
| POST | /api/auth/logout | Yes | No | No | Logout |
| GET | /api/accounts | Yes | Yes | No | List accounts |
| POST | /api/accounts/{id}/delete | Yes | Yes | No | Hesap sil (body: password). Şifre zorunlu; log/işlem geçmişi silinmez; aynı tel ile yeniden kayıt sıfırdan yeni hesap açar. |
| GET | /api/accounts/{id}/bot-performance | Yes | Yes | No | Bot performans: günlük/haftalık/aylık/genel toplam PnL (silinen botlar dahil) |
| GET | /api/leaderboard/structures/{structure_id}/top | Yes | Yes | No | Copy Trading: structure bazlı top 5 (profit_pct + params; username/bakiye yok) |
| GET | /api/leaderboard/global/top | Yes | Yes | No | Global En İyi Bot: tek kayıt (structure_id, profit_pct, params) |
| GET | /api/bots-engine | Yes | Yes | No | List bots |
| POST | /api/bots-engine | Yes | Yes | No | Create bot |
| POST | /api/bots-engine/{id}/start | Yes | Yes | No | Insert START command |
| POST | /api/bots-engine/{id}/stop | Yes | Yes | No | Insert STOP command |
| GET | /api/bots-engine/{id} | Yes | Yes | Yes (price) | Bot detail |
| GET | /api/binance/wallet | Yes (require_auth + require_account_access) | Yes | Yes | Account balances |
| POST | /api/binance/order | Yes | Yes | Yes | Place order (manual) |
| GET | /api/admin/* | Admin | Yes | Varies | Admin panel |

## Python Modules (App)

| Module | Purpose | Entry Points | External Calls | DB | Shared State | Thread/Async | Risks |
|--------|---------|--------------|----------------|-----|--------------|--------------|-------|
| app/main.py | FastAPI app, lifespan, middleware | startup_event, shutdown_event | — | — | — | Async | — |
| app/boot_id.py | Boot ID for session invalidation | get_boot_id | — | — | — | Sync | — |
| app/api/routes.py | REST routes, snapshot, accounts, bots | api_dashboard_snapshot, etc. | Binance, DataHub | Account, Bot, Trade | DataHub | Async | Per-route |
| app/api/auth.py | Login, session, require_auth | require_auth, _session_get | — | User, Account | auth_sessions (DB), _sessions fallback | Async | Multi-worker safe (no boot_id in validation) |
| app/api/admin.py | Admin panel, breach, server control | get_admin_accounts, etc. | — | Many | — | Async | — |
| app/api/bots_engine.py | Bot CRUD, start/stop, perf chart | bots_create, bots_start, bots_stop | Binance (prices) | Bot, bot_engine_commands | — | Async | — |
| app/api/data_hub_routes.py | DataHub status, prices | get_datahub_status | DataHub | — | DataHub | Async | — |
| app/services/data_hub.py | Price cache, WS, REST bulk | get_price, get_all_prices, refresh | Binance | — | prices, _mini_ws | Async loop | Two workers = two caches |
| app/services/binance_spot.py | Binance REST gateway | public_get_json, signed_json, place_order | Binance API | — | CircuitBreaker, _binance_time_cache | Async | Circuit global |
| app/services/dashboard_snapshot.py | Snapshot sub-tasks | fetch_prices, fetch_bots_and_account_kpis | DataHub, Binance | Account, Bot, Trade | — | Async | 3s timeout each |
| app/services/binance_client.py | Binance client wrapper | — | Binance | — | — | Async | — |
| app/services/encryption.py | Fernet encrypt/decrypt | encrypt_text, decrypt_text | — | — | — | Sync | BINANCE_MASTER_KEY |
| app/db/base.py | Engine, WAL init | _create_engine_for_role | — | — | engine | Sync | — |
| app/db/session.py | get_db | get_db | — | — | — | Sync | — |
| app/db/models.py | SQLAlchemy models | — | — | — | — | — | — |
| app/db/schema_guard.py | Schema migrations, table creation | ensure_* | — | — | — | Sync | — |
| app/services/leaderboard_service.py | Top by structure / global, refresh metrics | get_top_by_structure, get_global_top, refresh_bot_public_metrics | — | bot_public_metrics | — | Sync | — |
| app/services/copytrading_sanitize.py | Param sanitization for leaderboard | sanitize_bot_params | — | — | — | Sync | — |
| app/api/leaderboard.py | Leaderboard API | leaderboard_structure_top, leaderboard_global_top | — | — | — | Async | — |
| app/botengine/worker_main.py | Worker process, command loop | main, worker_loop, process_command | — | bot_engine_commands, Bot | — | Async | — |
| app/botengine/orchestrator.py | Bot tick loop, strategy dispatch | _bot_loop, start_bot, stop_bot | DataHub (adapter), Binance | Bot, bot_engine_state | _config_cache, _stop_requested | Async | Lock lease |
| app/botengine/locks.py | Symbol lease lock | try_acquire_symbol_lock, release_symbol_lock | — | symbol_locks | — | Sync | 60s lease |
| app/botengine/state_store.py | State persistence | load_state, save_state, append_event | — | bot_engine_state, bot_engine_events | — | Sync | — |
| app/botengine/execution.py | Strategy → order execution | run_actions | Binance (adapter) | Ledger, Trade | — | Async | Duplicate order risk |
| app/botengine/adapters/binance_adapter.py | Adapter over binance_spot + data_hub | get_price, place_market_buy | DataHub, binance_spot | — | — | Async | Stale check |
| app/botengine/strategies/dca_grid_trailing.py | DCA/Grid/Trailing strategy | strategy_tick | — | — | — | Sync | — |
| app/botengine/strategies/trdca_pro.py | TRDCA PRO strategy | trdca_strategy_tick | — | — | — | Sync | — |
| app/botengine/strategies/multi_asset_rebalance.py | Multi-asset rebalance | — | — | — | — | Sync | — |
| app/botengine/risk.py | Lock, idempotency, min notional | acquire_bot_lock, check_idempotency | — | — | — | Sync | — |
| app/botengine/virtual_wallet.py | Virtual base/quote | get_virtual_wallet, update_virtual_after_fill | — | bot_virtual_wallet | — | Sync | — |
| app/botengine/cycle_ledger.py | Cycle PnL ledger | cycle_ledger_add_fill | — | — | — | Sync | — |

## Leaderboard / Copy Trading

| Item | Detail |
|------|--------|
| Table | `bot_public_metrics` (bot_id UNIQUE, structure_id, profit_pct_all, params_sanitized_json; no username/balance) |
| Refresh | 60s loop in web lifespan; `refresh_bot_public_metrics()` uses PnlService + DB only (no Binance) |
| Multi-worker | `.run/leaderboard_refresh.lock` with 55s timeout; only one process runs refresh per cycle |
| Logs | `LEADERBOARD_REFRESH_OK count=… duration_ms=…`, `LEADERBOARD_REFRESH_FAIL error_code=…` |
| Privacy | Response: profit_pct + params only; bot_id, account_id, username, balance never exposed |

## Call Graph (ASCII) — Snapshot Flow

```
api_dashboard_snapshot (routes.py)
  ├── require_auth
  ├── asyncio.gather(
  │     fetch_prices() ──────────► data_hub.get_all_prices (run_in_executor)
  │     _fetch_wallet_uncached() ► binance_spot.get_wallet
  │     fetch_bots_and_account_kpis() ► DB (Account, Bot, PnlService)
  │     fetch_finance_pnl() ─────► DB (FinancePnlCalculator)
  │   )
  └── merge → response
```

## Call Graph — Bot Trade Flow

```
_bot_loop (orchestrator.py)
  ├── load_state (state_store)
  ├── adapter.get_price(symbol) ─► data_hub.get_price_with_meta
  │     └── if is_stale → return None → skip
  ├── try_acquire_symbol_lock (locks.py)
  ├── strategy_tick (dca_grid_trailing / trdca_pro / multi_asset)
  ├── run_actions (execution.py)
  │     ├── BinanceAdapter.place_market_buy/sell
  │     └── binance_spot.place_order
  ├── release_symbol_lock
  └── save_state (state_store)
```

## Remaining Python Modules

| Module | Purpose | Entry Points | External | DB | Shared | Risks |
|--------|---------|--------------|----------|-----|--------|-------|
| app/services/pnl_service.py | PnL calculation | PnlService.calculate_bot_pnl | DataHub (price) | Ledger, Trade | — | — |
| app/services/finance_pnl_calculator.py | Finance PnL | — | — | TradeNormalized, etc. | — | — |
| app/services/encryption.py | Fernet encrypt/decrypt | encrypt_text, decrypt_text | — | — | — | BINANCE_MASTER_KEY |
| app/services/test_account.py | Test account detection | is_test_account | — | — | — | — |
| app/services/binance_assets.py | Account keys resolution | get_account_keys | — | Account | — | ACCOUNT_KEYS_EMPTY, ACCOUNT_KEYS_DECRYPT_FAIL |
| app/services/finance_trade_sync.py | Trade sync (myTrades) | TradeSyncService | — | — | — | ACCOUNT_KEYS_EMPTY/MISSING => INFO, skip sync (ERROR değil) |
| app/services/binance_metrics.py | Binance call counter | BinanceMetrics.record | — | — | Class attr | — |
| app/services/binance_ws.py | WebSocket client | — | wss://stream.binance.com | — | — | Reconnect; open_timeout=20s; handshake timeout WARNING 5 dk'da bir |
| app/services/cache.py | Cache utilities | — | — | — | — | — |
| app/botengine/risk.py | Lock, idempotency, min notional | acquire_bot_lock, check_idempotency | — | — | — | — |
| app/botengine/cycle_ledger.py | Cycle PnL ledger | cycle_ledger_add_fill | — | — | — | — |
| app/botengine/grid_view.py | Grid view utilities | — | — | — | — | — |
| app/middleware/request_metrics.py | Request metrics | — | — | — | — | — |
| app/observability/ram_probe.py | RAM diagnostics | probe_market_data | — | — | — | — |
| app/error_logging.py | Error log helpers | — | — | error_logs | — | — |
| app/server_state.py | Server state | — | — | — | — | — |
| manager_server/app.py | Manager API | — | — | — | — | — |

## UI JavaScript Modules (Critical)

| Module | Purpose | Constants | Risks |
|--------|---------|-----------|-------|
| ui/assets/core/apiClient.js | HTTP client, slot limiter | DEFAULT_TIMEOUT=5000, MAX_CONCURRENT=2 | Timeout; slot leak |
| ui/assets/core/intervalRegistry.js | Interval management | — | visibilityState hidden skips |
| ui/assets/dashboard.js | Dashboard, snapshot poll | SNAPSHOT_POLL_MS=5000, timeout=12000 | inFlight stuck |
| ui/assets/admin.js | Admin panel | — | — |
| ui/assets/ticker.js | Ticker UI | — | — |
| ui/assets/components.js | Shared components | — | — |

---

# SECTION B — DATABASE FULL SCHEMA

## bot_engine_state

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | Low | — | — | — | — |
| bot_id | INTEGER | No | — | UNIQUE, ix_bot_id | High | High | = bots | — | State lost per bot |
| account_id | INTEGER | No | — | ix_account_id | Medium | — | — | — | — |
| state_json | TEXT | Yes | — | — | High | High | ~2–50KB/row | WAL | Partial state |
| cycle_id | INTEGER | No | 1 | — | Medium | Medium | — | — | Cycle mismatch |
| mode | VARCHAR(32) | No | IDLE | — | Medium | Medium | — | — | Mode drift |
| last_tick_at | DATETIME | Yes | — | — | Low | Medium | — | — | — |
| last_error_code | VARCHAR(64) | Yes | — | — | Low | Low | — | — | — |
| retry_at | DATETIME | Yes | — | — | Low | Low | — | — | — |
| updated_at | DATETIME | Yes | — | — | Low | High | — | — | — |

## bot_engine_commands

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | Medium | — | Append | — | — |
| created_at | TEXT | No | — | — | Low | — | — | — | — |
| processed_at | TEXT | Yes | — | — | Low | Medium | — | — | — |
| account_id | INTEGER | No | — | — | Medium | — | — | — | — |
| bot_id | INTEGER | No | — | ix_bot_id | High | — | — | — | — |
| command | TEXT | No | — | — | — | — | — | — | — |
| payload_json | TEXT | Yes | — | — | — | — | — | — | — |
| status | TEXT | No | PENDING | ix_status | High | High | — | — | Command stuck |
| error_code | TEXT | Yes | — | — | Low | Low | — | — | — |
| error_id | TEXT | Yes | — | — | Low | Low | — | — | — |
| request_id | TEXT | Yes | — | — | Low | — | — | — | — |

## symbol_locks — Lock Lifecycle (Detailed)

1. **Acquire:** try_acquire_symbol_lock(db, account_id, symbol, bot_id)
   - UPDATE WHERE (lease_until < now OR owner_bot_id = bot_id) → rowcount > 0 → success
   - ELSE SELECT exists → no row → INSERT → success (or UNIQUE conflict → fail)
   - Lease: lease_until = now + 60s
2. **Hold:** Bot executes order; lock row has owner_bot_id, lease_until
3. **Release:** release_symbol_lock(db, account_id, symbol, bot_id)
   - UPDATE SET owner_bot_id=0, lease_until=now WHERE owner_bot_id=bot_id
4. **Expiry:** If no release (crash), lease_until passes; another bot can acquire
5. **Idempotency:** release is idempotent (no row updated if not owner)

## symbol_locks

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | Low | — | — | — | — |
| account_id | INTEGER | No | — | UNIQUE(aid,sym) | High | High | = active symbols | Row lock | Double trade |
| symbol | VARCHAR(32) | No | — | ix_account_symbol | High | High | — | — | — |
| owner_bot_id | INTEGER | No | — | — | High | High | — | — | Lock stuck |
| lease_until | TEXT | No | — | — | High | High | — | — | — |
| updated_at | TEXT | No | — | — | Low | High | — | — | — |

## bot_engine_events

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | Low | — | Append | — | — |
| bot_id | INTEGER | No | — | ix_bot_id | Medium | — | — | — | — |
| account_id | INTEGER | No | — | — | Low | — | — | — | — |
| ts | DATETIME | No | — | ix_ts | Medium | — | — | — | — |
| event_type | VARCHAR(64) | No | — | — | Medium | — | — | — | — |
| message | TEXT | Yes | — | — | Medium | — | — | — | — |
| meta_json | TEXT | Yes | — | — | Medium | — | — | — | — |

## bot_virtual_wallet

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | — | — | — | — | — |
| bot_id | INTEGER | No | — | ix_bot_id, UNIQUE(bot,sym) | High | High | = bots×symbols | — | Virtual drift |
| account_id | INTEGER | No | — | — | — | — | — | — | — |
| symbol | VARCHAR(32) | No | — | — | — | — | — | — | — |
| virtual_base | REAL | No | 0 | — | High | High | — | — | — |
| virtual_quote | REAL | No | 0 | — | High | High | — | — | — |
| updated_at | TEXT | No | — | — | — | High | — | — | — |

## WAL File Behavior

- Writes go to -wal file
- Checkpoint: when WAL grows; can cause brief write stall (100ms–1s UNKNOWN)
- Recovery: SQLite auto-recovery on next open after crash

## DB Access by Module (Read/Write)

| Module | Tables Read | Tables Written | Locks |
|--------|-------------|----------------|-------|
| routes (snapshot) | Account, Bot, Trade, Ledger | — | — |
| auth | User, Account | — | — |
| bots_engine | Bot, bot_engine_commands | Bot, bot_engine_commands | — |
| worker_main | bot_engine_commands, Bot | bot_engine_commands | — |
| orchestrator | Bot, bot_engine_state | bot_engine_state | symbol_locks |
| state_store | bot_engine_state | bot_engine_state, bot_engine_events | — |
| locks | symbol_locks | symbol_locks | Row lock |
| execution | Ledger, Trade | Trade, Ledger | — |
| virtual_wallet | bot_virtual_wallet | bot_virtual_wallet | — |
| pnl_service | Ledger, Trade | — | — |
| dashboard_snapshot | Account, Bot, Trade | — | — |

## Disk Growth Model

| Table | Est. Rows/Day | Est. Bytes/Row | Est. MB/Year |
|-------|---------------|----------------|--------------|
| trades | 100–1000 | ~200 | 7–70 |
| bot_engine_events | 100–500 | ~300 | 11–55 |
| bot_engine_commands | 10–100 | ~200 | 0.7–7 |
| bot_engine_state | = bots | ~20KB | Depends |
| symbol_locks | = active | ~100 | <1 |

**UNKNOWN:** Exact growth. No vacuum policy.  
**RISK IF IGNORED:** Disk full.  
**HOW TO MEASURE:** `SELECT COUNT(*) FROM trades;` over time.

## Backup Strategy

- No built-in backup
- Recommended: cp/WAL checkpoint before deploy; external backup script

## Core Tables (users, accounts, bots, trades)

### users

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | High | Low | = users | — | — |
| username | VARCHAR(100) | No | — | UNIQUE | High | Low | — | — | Login failure |
| password_hash | VARCHAR(255) | No | — | — | Low | Low | — | — | — |
| name | VARCHAR(100) | No | — | — | Medium | Low | — | — | — |
| surname | VARCHAR(100) | No | — | — | Medium | Low | — | — | — |
| phone | VARCHAR(20) | Yes | — | — | Medium | Low | — | — | — |
| is_admin | BOOLEAN | No | False | — | High | Low | — | — | — |
| is_approved | BOOLEAN | No | False | — | High | Low | — | — | — |
| is_suspended | BOOLEAN | No | False | — | High | Low | — | — | — |
| is_deleted | BOOLEAN | No | False | — | Medium | Low | — | — | — |
| account_id | INTEGER | Yes | — | FK, UNIQUE | High | Low | — | — | — |

### accounts

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | High | Low | = accounts | — | — |
| account_code | VARCHAR(6) | Yes | — | UNIQUE | Medium | Low | — | — | — |
| name | VARCHAR(255) | No | — | — | High | Low | — | — | — |
| api_key_enc | TEXT | No | — | — | Low | Low | — | — | Key decrypt failure |
| api_secret_enc | TEXT | No | — | — | Low | Low | — | — | — |
| mode | VARCHAR(20) | No | live | — | Medium | Low | — | — | — |
| user_id | INTEGER | Yes | — | FK, UNIQUE | High | Low | — | — | — |

### bots

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | High | Medium | = bots | — | — |
| account_id | INTEGER | No | — | FK | High | — | — | — | — |
| symbol | VARCHAR(50) | No | — | — | High | Low | — | — | — |
| config_json | TEXT | Yes | — | — | High | Medium | — | — | Config parse error |
| status | VARCHAR(20) | No | stopped | — | High | High | — | — | — |
| started_at | DATETIME | Yes | — | — | Medium | Medium | — | — | — |
| bot_code | VARCHAR(16) | Yes | — | UNIQUE | Medium | Low | — | — | — |

### trades

| Field | Type | Nullable | Default | Index | Read Freq | Write Freq | Growth | Lock | Corruption Impact |
|-------|------|----------|---------|-------|-----------|------------|--------|------|-------------------|
| id | INTEGER | No | AUTO | PK | Medium | — | Append | — | — |
| bot_id | INTEGER | No | — | FK | High | — | — | — | — |
| account_id | INTEGER | No | — | FK | High | — | — | — | — |
| ts | DATETIME | No | — | ix_ts | Medium | — | — | — | — |
| side | VARCHAR(10) | No | — | — | High | — | — | — | — |
| qty | FLOAT | No | — | — | High | — | — | — | — |
| price | FLOAT | No | — | — | High | — | — | — | — |
| fee | FLOAT | No | 0 | — | Medium | — | — | — | — |
| order_id | VARCHAR(64) | Yes | — | ix_order_id | Medium | — | — | — | — |
| client_order_id | VARCHAR(64) | Yes | — | — | Low | — | — | — | — |
| symbol | VARCHAR(32) | Yes | — | — | Medium | — | — | — | — |
| cycle_id | INTEGER | Yes | 1 | — | Medium | — | — | — | — |

## Vacuum Policy

- **UNKNOWN** if vacuum is ever run.
- **WHY IT MATTERS:** WAL + deleted rows = file growth.
- **HOW TO MEASURE:** `PRAGMA page_count;` and file size.
- **RISK IF IGNORED:** Disk full over time.

## pnl_snapshots

| Field | Type | Nullable | Default | Index | Growth |
|-------|------|----------|---------|-------|--------|
| id | INTEGER | No | AUTO | PK | Append |
| bot_id | INTEGER | No | — | FK | — |
| account_id | INTEGER | No | — | FK | — |
| ts | DATETIME | No | — | ix_ts | — |
| total_usd | FLOAT | No | — | — | — |
| realized | FLOAT | No | 0 | — | — |
| unrealized | FLOAT | No | 0 | — | — |
| daily | FLOAT | No | 0 | — | — |
| monthly | FLOAT | No | 0 | — | — |

## error_logs

| Field | Type | Nullable | Default | Index | Growth |
|-------|------|----------|---------|-------|--------|
| id | INTEGER | No | AUTO | PK | Append |
| created_at | DATETIME | No | — | ix_created | — |
| event_kind | VARCHAR(16) | No | error | ix_event_kind | — |
| anomaly_code | VARCHAR(64) | Yes | — | ix_anomaly | — |
| source | VARCHAR(32) | No | — | ix_source | — |
| level | VARCHAR(16) | No | error | — | — |
| message | TEXT | No | — | — | — |
| request_id | VARCHAR(64) | Yes | — | ix_request_id | — |
| user_id | INTEGER | Yes | — | FK | — |
| account_id | INTEGER | Yes | — | FK | — |

## account_daily_realized_pnl

| Field | Type | Nullable | Default | Index | Growth |
|-------|------|----------|---------|-------|--------|
| account_id | INTEGER | No | — | PK | — |
| date_tr | TEXT | No | — | PK | — |
| amount_usd | REAL | No | 0 | — | — |
| updated_at | TEXT | No | — | — | — |

## Scripts (Non-App)

| Script | Purpose | Entry | External | DB |
|--------|---------|-------|----------|-----|
| scripts/local_web_worker_helper.py | Start/stop web, worker | CLI | — | No |
| scripts/migrations/init_db.py | Create tables | CLI | — | Yes |
| scripts/perf_snapshot_test.py | Snapshot latency test | CLI | HTTP | No |
| start.command | Start all | CLI | — | No |

## Recovery Steps (DB Corruption)

1. Stop all processes (web, worker).
2. Backup current DB file and -wal, -shm.
3. `sqlite3 dca.db "PRAGMA integrity_check;"`
4. If corrupted: restore from backup; if no backup, data loss.
5. `PRAGMA wal_checkpoint(TRUNCATE);` to compact WAL.

---

# SECTION C — ORDER EXECUTION FORENSICS

## 1) Crash Before place_order

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| Worker dies before Binance call | No | No | No | No | No order in Binance | — |
| Lock: Held until lease_until (60s) | — | — | — | No | Lock row owner_bot_id | — |

## 2) Crash After place_order, Before save_state

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| Order exists in Binance; state not updated | Yes | Possible on retry | Possible (double buy) | State stale | Compare Binance orders vs state | client_order_id idempotency |

**Duplicate possible:** If strategy retries same intent (e.g. re-entry) and does not check Binance order history before placing. Current code: no idempotency key.

## 3) Network Timeout After Binance Accepted Order

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| Binance accepted; HTTP timeout before response | Yes | Possible on retry | Possible | State stale | Binance order history | client_order_id idempotency; don't retry without checking |

## 4) Duplicate Client Submission

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| User double-clicks Start | Command inserted twice | Possible if both processed | Possible | No | Duplicate bot_engine_commands | Idempotent command handling; dedupe by request_id |

## 5) Lock Held During Crash

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| Lock row: owner_bot_id set, lease_until future | — | — | — | No | Lock row | Lease expires 60s; other bot can acquire after |

## 6) Worker Restart Mid-Cycle

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| New worker loads state; may redo last tick | Depends | Possible if last tick placed order and crashed before save | Possible | No | last_tick_at vs order time | client_order_id idempotency |

## client_order_id Idempotency Proposal

**Current:** No client_order_id sent; Binance generates orderId.

**Proposed:**
1. Generate: `f"bot{bot_id}_cy{cycle_id}_{uuid4()[:8]}"` or `f"bot{bot_id}_{int(time.time()*1000)}"`
2. Send in place_order payload: `clientOrderId`
3. Binance: duplicate clientOrderId returns same order (idempotent)
4. On retry: use same client_order_id → no duplicate

**Status:** NOT IMPLEMENTED. Mark as RISK.

## 7) Partial Fill Scenario

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| Binance returns partial fill; worker saves state | Yes (partial) | No | No | Possible (state assumes full) | Compare fill qty vs state | Check fill qty in response |

## 8) Double Strategy Decision (Same Tick)

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| Strategy returns 2 actions; run_actions executes both | 2 orders | No (intended) | Possible (over-trade) | No | Event log | max_orders_per_minute guard |

## 9) Lock Acquired, Exception Before Order

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| try_acquire succeeds; exception in strategy/execution | No | No | No | No | Lock held 60s | try/finally release |

**Current:** release in else branch; exception may skip release. Lock expires 60s.

## 10) Paper Mode vs Live Mode Mix-Up

| What happens | Order placed? | Duplicate? | Financial loss? | State corruption? | Detect | Prevent |
|--------------|---------------|------------|-----------------|-------------------|--------|---------|
| is_test_account misdetected; live keys used in paper | Real order | No | Possible | No | Audit | Explicit mode flag |

---

# SECTION D — CONCURRENCY & RACE CONDITIONS

## Two Web Workers

| Scenario | Interleaving | Safe/Unsafe | Data Corruption? | Financial Risk? |
|----------|--------------|-------------|------------------|-----------------|
| Request A → worker 0, B → worker 1 | Separate DataHubs | Safe | No | No |
| Worker 1 first request | DataHub 1 empty | Unsafe for first hit | No | No (read-only) |
| Session in worker 0 | Request B hits worker 1 | Session may miss (boot_id same) | No | No |

## Two Snapshot Requests (Same Account)

| Scenario | Interleaving | Safe/Unsafe | Data Corruption? | Financial Risk? |
|----------|--------------|-------------|------------------|-----------------|
| Parallel snapshots | Both run gather | Safe | No | No |
| Slot limiter | 2 concurrent max | Safe | No | No |

## Worker + Snapshot DB Access

| Scenario | Interleaving | Safe/Unsafe | Data Corruption? | Financial Risk? |
|----------|--------------|-------------|------------------|-----------------|
| Worker writes state; Snapshot reads bots | WAL: readers don't block writers | Safe | No | No |
| Worker writes symbol_locks; Snapshot reads | Same | Safe | No | No |

## Symbol Lock Edge Cases

| Scenario | Interleaving | Safe/Unsafe | Data Corruption? | Financial Risk? |
|----------|--------------|-------------|------------------|-----------------|
| Bot A acquires; Bot B tries same (account, symbol) | B gets False | Safe | No | No |
| Bot A crashes; Bot B tries before lease expiry | B gets False | Safe | No | No |
| Bot A crashes; 60s passes; Bot B tries | B acquires | Safe | No | No |
| Lease expiry overlap (same second) | UPDATE WHERE lease_until < now | Safe | No | No |

## Stale Price Race

| Scenario | Interleaving | Safe/Unsafe | Data Corruption? | Financial Risk? |
|----------|--------------|-------------|------------------|-----------------|
| Price updated between get_price and place_order | Possible | Unsafe if stale | No | Possible (bad fill) |
| Mitigation | get_price checks is_stale | Stale → None → no trade | No | Mitigated |

## Interleaving Diagram — Two Workers, Same Bot (Future)

```
Worker A                    Worker B                    DB
  |                           |                          |
  |-- load_state ------------>|                          |
  |                           |<-- load_state -----------|
  |                           |   (same state)           |
  |-- try_acquire_lock ------>|                          |
  |   SUCCESS                 |-- try_acquire_lock ----->|
  |                           |   FAIL (A holds)         |
  |-- place_order ----------->|                          |
  |-- save_state -------------|                          |
  |-- release_lock ---------->|                          |
  |                           |-- try_acquire_lock ----->|
  |                           |   SUCCESS (after A done) |
```

**Current:** Single worker; no interleaving. **Future:** Horizontal scaling would require partitioning.

## Session / boot_id Race

| Scenario | Interleaving | Safe/Unsafe | Data Corruption? | Financial Risk? |
|----------|--------------|-------------|------------------|-----------------|
| Server restarts; client has old token | boot_id changes; _session_get returns None | Safe | No | No (401) |
| Two web workers; session in worker 0; request hits worker 1 | Session miss (different process) | Unsafe for session | No | No (401) |

**Mitigation:** Session is per-process; load balancer may need sticky session for session locality (not implemented).

## DataHub Refresh vs get_all_prices Race

| Scenario | Interleaving | Safe/Unsafe | Data Corruption? | Financial Risk? |
|----------|--------------|-------------|------------------|-----------------|
| _refresh_inflight running; get_all_prices called | run_in_executor waits on sync get_all_prices | Safe | No | No |
| Two get_all_prices concurrent | Both read same prices dict | Safe (read-only) | No | No |

---

# SECTION E — PERFORMANCE SCIENCE MODEL

## Latency Equation

```
TotalSnapshot = RTT + TLS + ServerQueue + max(DB, Binance, JSON) + DOM
```

| Component | Local (ms) | Prod (ms) | Worst 3G (ms) |
|-----------|------------|-----------|---------------|
| RTT | 1–5 | 20–100 | 200–500 |
| TLS | 10–30 | 30–80 | 80–150 |
| ServerQueue | 0–10 | 0–50 | 0–100 |
| DB (max of 4 tasks) | 20–80 | 50–200 | 50–300 |
| Binance (wallet) | 100–400 | 200–800 | 500–4000 |
| JSON parse | 5–20 | 10–50 | 20–100 |
| DOM update | 20–80 | 30–120 | 50–200 |
| **Total** | **~200–600** | **~400–1500** | **~1000–5000+** |

## Worst Case Mobile 3G Model

- RTT: 500ms
- Payload: 200KB
- Download: 200KB / 100kbps ≈ 16s
- **Result:** Snapshot may exceed 12s timeout → failure

## Payload Size Estimation

```
Snapshot ≈
  len(prices) × 80 bytes +    # 600 × 80 = 48KB
  len(bots) × 500 bytes +     # 10 × 500 = 5KB
  wallet ~2KB +
  account ~1KB +
  pnl ~2KB
  ≈ 60–100KB typical, up to 200KB
```

## Memory Footprint Estimation

| Component | Bytes |
|-----------|-------|
| DataHub.prices (600) | ~120KB |
| DataHub._mini_ws (600) | ~120KB |
| DataHub.account_balances (50) | ~10KB |
| Python process baseline | ~50–100MB |
| **Total DataHub** | ~250KB |

## CPU Utilization Estimation

- Idle: <1%
- Snapshot: 1–5% (4 tasks)
- Bot tick: 1–3% per bot
- **UNKNOWN:** Exact under load. **HOW TO MEASURE:** `ps` or `top`.

---

# SECTION E.1 — CPU & RAM KULLANIMI (DETAYLI)

## Mevcut RAM Kullanımı — Bileşen Bazlı

| Bileşen | Tahmini Boyut | Hesaplama | Kaynak |
|---------|---------------|-----------|--------|
| DataHub.prices (600 sembol) | ~120 KB | 600 × ~200 byte (dict entry) | data_hub.py |
| DataHub._mini_ws (600 sembol) | ~120 KB | 600 × ~200 byte | data_hub.py |
| DataHub.account_balances (50 hesap) | ~10 KB | 50 × ~200 byte | data_hub.py |
| DataHub.coin_list (200 kayıt) | ~40 KB | 200 × ~200 byte | data_hub.py |
| DataHub.all_symbols (2000+ sembol) | ~80 KB | ~2000 × ~40 byte | data_hub.py |
| _sessions (auth) | ~1–50 KB | Kullanıcı sayısına bağlı | auth.py |
| SQLAlchemy connection pool | ~2–5 MB | pool_size=10, max_overflow=20 | base.py |
| Python interpreter + imports | ~30–50 MB | Standart | — |
| uvloop / httptools | ~5–15 MB | Async runtime | — |
| **Web process toplam (idle)** | **~80–150 MB** | RSS (psutil) | — |
| **Worker process (idle)** | **~60–120 MB** | RSS (psutil) | — |
| **Manager process** | **~40–80 MB** | RSS (psutil) | — |

## Mevcut CPU Kullanımı — İşlem Bazlı

| İşlem | Idle CPU % | Snapshot sırasında | Bot tick sırasında | Ölçüm |
|-------|------------|--------------------|--------------------|-------|
| Web worker 0 | <0.5% | 2–8% | — | `ps -p PID -o %cpu` |
| Web worker 1 | <0.5% | 2–8% (eş zamanlı istek) | — | — |
| Worker | <0.5% | — | 1–5% per tick | — |
| Manager | <0.1% | — | — | — |

## RAM Probe Enstrümantasyonu (Mevcut)

| Özellik | Durum | Ayar | Dosya |
|---------|-------|------|-------|
| psutil RSS/VMS | Var (psutil varsa) | — | ram_probe.py |
| tracemalloc current/peak | Var (RAM_PROBE=1) | RAM_PROBE_ENABLED=1 | ram_probe.py |
| tracemalloc top allocations | Var | — | ram_probe.py |
| GC object counts | Var (dict, list, tuple, str, bytes) | — | ram_probe.py |
| asyncio.Task count | Var | — | ram_probe.py |
| JSONL log | Var | logs/ram_snapshots.log | ram_probe.py |
| Periyodik probe | Var | interval_sec=30 (default) | ram_probe.py |
| probe_market_data hook | Var | DataHub _background_update_loop | data_hub.py |
| probe_event_store | Var | ORDER_FILLED öncesi/sonrası | state_store.py |

## Mevcut Ölçüm Noktaları

| Nokta | Tetikleyici | Veri |
|-------|-------------|------|
| Web startup | lifespan | rss_mb, tracemalloc, gc |
| Worker startup | main | (probe Worker’da başlatılmıyor) |
| Snapshot | — | SNAPSHOT_LATENCY (süre); RAM yok |
| ORDER_FILLED | execution | probe_event_store (RAM_PROBE=1) |
| DataHub 60s loop | _background_update_loop | probe_market_data (RAM_PROBE=1) |
| GET /api/health/ram | Manuel | get_last_snapshot() |

## Geliştirilebilir — RAM İzleme

| Öneri | Açıklama | Öncelik | Uygulama |
|-------|----------|---------|----------|
| Worker’da RAM probe | Worker’da start_ram_probe yok | Yüksek | worker_main main() içinde RAM_PROBE=1 ise start_ram_probe("worker") |
| Snapshot sonrası RAM | Her snapshot sonrası rss_mb logla | Orta | api_dashboard_snapshot sonunda snapshot_now("snapshot", "post") |
| Per-endpoint RSS | Her kritik endpoint sonrası | Orta | Middleware veya decorator |
| DataHub eviction metrikleri | _trim_prices çağrı sayısı, evicted count | Orta | data_hub._trim_prices içinde counter |
| Memory growth alarm | RSS > threshold → log/alert | Yüksek | ram_probe loop’ta threshold check |
| Heap diff (before/after) | Snapshot öncesi/sonrası diff | Düşük | tracemalloc snapshot diff |

## Geliştirilebilir — CPU İzleme

| Öneri | Açıklama | Öncelik | Uygulama |
|-------|----------|---------|----------|
| Per-request CPU time | Her request sonrası cpu_times() delta | Yüksek | Middleware; psutil.Process().cpu_times() |
| Per-tick CPU time | Her bot tick sonrası CPU delta | Yüksek | orchestrator _bot_loop içinde |
| CPU % per process | Periyodik psutil cpu_percent() | Orta | ram_probe’a cpu_percent ekle |
| Hotspot detection | En çok CPU tüketen endpoint | Orta | request_metrics + cpu_times |
| Profiling endpoint | GET /debug/cpu-profile (cProfile) | Düşük | Geliştirme ortamı |

## RAM Büyüme Projeksiyonları

| Senaryo | Süre | Tahmini RSS Artışı | Tetikleyici |
|---------|------|--------------------|-------------|
| Idle | 24 saat | +0–10 MB | GC; connection pool |
| 100 snapshot/saat | 1 saat | +5–20 MB | Geçici objeler; GC gecikmesi |
| 10 bot tick/dk | 1 saat | +2–10 MB | State, adapter cache |
| DataHub 600→600 (sabit) | — | 0 | _MAX_PRICES sınırı |
| Session 10→100 kullanıcı | — | +~50 KB | _sessions dict |
| 1000 bot_engine_events | Append | +~300 KB | DB + SQLAlchemy cache |

## CPU Büyüme Projeksiyonları

| Senaryo | Tahmini CPU Artışı | Tetikleyici |
|---------|-------------------|-------------|
| 10 eşzamanlı snapshot | +20–40% (geçici) | 4 task × 10 request; executor |
| 5 bot aynı anda tick | +5–15% (geçici) | Strategy, BinanceAdapter |
| DataHub REST loop 1.5s | +0.5–2% sürekli | refresh_all_prices_bulk |
| JSON parse 200KB × 10/s | +1–3% | Snapshot response |

## Kritik Eşikler (Önerilen)

| Metrik | Uyarı | Kritik | Aksiyon |
|--------|-------|--------|---------|
| Web RSS | >300 MB | >500 MB | İnceleme; restart |
| Worker RSS | >250 MB | >400 MB | İnceleme; restart |
| DataHub prices len | >550 | 600 | Eviction tetiklenir |
| GC total_objects | >100K | >200K | gc.collect(); inceleme |
| tracemalloc peak | >150 MB | >250 MB | Top allocations incele |
| CPU % (1 dakika ort.) | >50% | >80% | Yük azaltma |

## Ölçüm Komutları (CLI)

```bash
# Web process RSS (MB)
ps -p $(cat .run/web.pid) -o rss= | awk '{print $1/1024 " MB"}'

# Worker process RSS
ps -p $(cat .run/worker.pid) -o rss= | awk '{print $1/1024 " MB"}'

# Tüm process’lerin toplam RSS
ps -p $(cat .run/web.pid),$(cat .run/worker.pid),$(cat .run/manager.pid 2>/dev/null) -o rss= 2>/dev/null | awk '{s+=$1} END {print s/1024 " MB"}'

# CPU % (1 saniye örnek)
ps -p $(cat .run/web.pid) -o %cpu=

# RAM probe log (son 5 satır)
tail -5 logs/ram_snapshots.log | jq -c '{ts, component, rss_mb, tracemalloc_peak_mb}'
```

## Geliştirilebilir — Otomasyon

| Öneri | Açıklama |
|-------|----------|
| Prometheus exporter | /metrics endpoint; process_resident_memory_bytes, process_cpu_seconds_total |
| Grafana dashboard | RSS, CPU, GC counts zaman serisi |
| OOM öncesi dump | RSS > threshold → tracemalloc snapshot + gc.dump() |
| Periyodik rapor | Günlük logs/cpu_ram_report.json |
| Alert webhook | RSS/CPU eşik aşımı → HTTP POST |

## GC Davranışı (Mevcut)

| Özellik | Değer |
|---------|-------|
| GC varsayılan | Açık |
| get_count() | (gen0, gen1, gen2) — ram_probe’da |
| gc.collect() | Manuel; gc_collect_and_count() |
| Cyclic GC | Varsayılan |
| **UNKNOWN** | Tam GC sıklığı; heap büyüme eğrisi |

## Tracemalloc Davranışı (RAM_PROBE=1)

| Özellik | Değer |
|---------|-------|
| Depth | 25 frame |
| Current/peak | MB cinsinden |
| Top 10 allocations | lineno (dosya:satır, size_mb) |
| Log | logs/ram_snapshots.log (JSONL) |
| Overhead | ~5–15% (tahmini) |

## Özet — Mevcut vs Geliştirilebilir

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| RAM ölçümü | psutil + tracemalloc (RAM_PROBE=1) | Worker probe; snapshot sonrası; alarm |
| CPU ölçümü | Yok (manuel ps) | Per-request; per-tick; Prometheus |
| Loglama | ram_snapshots.log (JSONL) | Prometheus; Grafana |
| Alarm | Yok | RSS/CPU eşik; webhook |
| Profiling | Yok | cProfile endpoint (dev) |

## Process Bazlı Karşılaştırma

| Metrik | Web (worker 0) | Web (worker 1) | Worker | Manager |
|--------|----------------|----------------|--------|---------|
| Varsayılan RSS (idle) | ~80–150 MB | ~80–150 MB | ~60–120 MB | ~40–80 MB |
| DataHub | Var (her worker kendi) | Var | Yok (Worker DataHub yok) | Yok |
| Binance çağrıları | Evet (wallet, ticker) | Evet | Evet (order) | Hayır |
| DB okuma | Yüksek | Yüksek | Orta | Düşük |
| DB yazma | Düşük | Düşük | Yüksek | Hayır |
| Async loop | uvloop | uvloop | asyncio | — |
| RAM_PROBE | Evet (lifespan) | Evet | Hayır | Hayır |

## RAM / CPU İzleme Checklist

- [ ] RAM_PROBE_ENABLED=1 ile başlat
- [ ] logs/ram_snapshots.log dosyasını kontrol et
- [ ] Web + Worker toplam RSS < 400 MB (idle) beklenir
- [ ] tracemalloc_peak_mb < 150 MB beklenir
- [ ] Worker’da RAM probe eklenmeli (geliştirme)
- [ ] CPU per-request metrikleri eklenmeli (geliştirme)

---

# SECTION E.2 — BOT DETAY SAYFASI (DETAYLI)

## Mevcut — Endpoint Envanteri

| Endpoint | Metod | Auth | Veri Kaynağı | Tetikleyici | Timeout |
|----------|-------|------|--------------|-------------|---------|
| GET /api/bots-engine/{id} | GET | require_auth, get_account_or_403 | Bot, state, PnlService, grid_view, Binance | Sayfa yükleme; poll | 8s (UI) |
| GET /api/bots/{id}/detail | GET | require_auth | dashboard_bot_detail wrapper | Dashboard "Düzenle" | 8s |
| GET /api/dashboard/bot_detail | GET | require_auth | Bot, Ledger, PnlService, Trade | Legacy | 8s |
| GET /api/bots-engine/{id}/events | GET | require_auth | bot_engine_events | Events sekmesi; limit=500 | — |
| GET /api/bots-engine/{id}/trades | GET | require_auth | Ledger.get_trades_dict | İşlemler sekmesi | — |
| GET /api/bots-engine/{id}/cycles | GET | require_auth | Ledger.get_cycle_ids | Döngüler sekmesi | — |
| GET /api/bots-engine/{id}/performance | GET | require_auth | PnlService, Ledger | Performans sekmesi | — |
| GET/PUT/DELETE /api/bots-engine/{id}/perf-chart-state | GET/PUT/DELETE | require_auth | bot_perf_chart_state | Performans grafiği | — |
| POST /api/bots-engine/{id}/start | POST | require_auth | bot_engine_commands | Başlat; worker ilk tick'i hemen çalıştırır (ilk market alımı anında) | — |
| POST /api/bots-engine/{id}/stop | POST | require_auth | bot_engine_commands | Durdur butonu | — |
| POST /api/bots-engine/{id}/delete | POST | require_auth | delete_bot_fully | Sil butonu | — |

## Mevcut — UI Sayfaları

| Sayfa | Dosya | Strateji | Kullanım |
|-------|-------|----------|----------|
| Bot detay (tek sembol) | ui/bot.html | DCA/Grid/Trailing | symbol != MULTI |
| Bot detay (multi-asset) | ui/bot_multi.html | TRDCA, Multi-Asset Rebalance | symbol == MULTI |
| Dashboard bot listesi | ui/dashboard.html | — | "Düzenle" tıklanınca bot detaya yönlendirir |

## Mevcut — Bot Oluştur Akışı (Tek tık)

| Adım | Açıklama |
|------|----------|
| Oluştur butonu | Template seçiliyse tek buton "Oluştur"; tıklanınca create + start + worker ilk tick (market alım) |
| Create tab liste | Ekstra "▶ Başlat" butonu yok; "✓ Aktif" / "Durduruldu" + "Yeniden başlat" linki + "Parametreler" |
| İlk alım | START komutu işlenirken process_command içinde run_one_bot_tick(bot_id, cmd_immediate) çağrılır; "İlk alım bekleniyor" süresi minimize edilir |

## Mevcut — Bot Yapısı Seçimi (Bot Oluştur modal)

| Yapı | Normal hesap | Test hesabı |
|------|----------------|-------------|
| Trailing DCA / Grid | Aktif | Aktif |
| TRDCA Pro+ (Trailing Rebalancing DCA) | Pasif: "Çok yakında" rozeti, Devam Et tıklanamaz; toast: "Şu an sadece test hesabında kullanılabilir" | Aktif (geliştirme için) |

UI: `renderBotStructures()` (dashboard.js) `State.isTestAccount` ile TRDCA Pro+ kartını devre dışı gösterir; `selectBotStructure()` aynı kontrolü yapar.

## Mevcut — Veri Akışı (bots_detail)

| Adım | İşlem | Harici Çağrı | DB |
|------|-------|--------------|-----|
| 1 | load_state(db, bot_id) | — | bot_engine_state |
| 2 | PnlService.calculate_bot_pnl | DataHub (price) | Ledger, Trade |
| 3 | _fetch_24h_ticker (MULTI değilse) | Binance GET /api/v3/ticker/24hr?symbol=X | — |
| 4 | compute_grid_profit_view / compute_trdca_grid_view | — | — |
| 5 | MULTI/TRDCA: get_account_balances | Binance GET /api/v3/account | — |
| 6 | MULTI/TRDCA: _fetch_prices_parallel | DataHub veya Binance | — |
| 7 | Rebalancing details hesaplama | — | — |
| 8 | Response derleme | — | — |

**Not:** bots_detail tek endpoint'te PnL, grid, MULTI bakiyeler, rebalancing, 24h ticker birleştirir. 24h ticker asyncio.create_task ile paralel başlatılır.

## Mevcut — Sekmeler ve İstekler

| Sekme | İlk Yükleme | Sonraki İstekler | Polling |
|-------|-------------|------------------|---------|
| Genel / Grid | GET /api/bots-engine/{id} | — | intervalRegistry; visibilityState hidden skips |
| Olaylar | GET .../events?limit=500 | — | Yok (manuel yenile) |
| İşlemler | GET .../trades | cycle_id değişince | Yok |
| Döngüler | GET .../cycles | — | Yok |
| Performans | GET .../performance | period değişince | Yok |
| Performans grafiği | GET .../perf-chart-state | PUT (değişiklik) | Yok |

## Mevcut — Polling ve Yenileme

| Bileşen | Interval | visibilityState | Dosya |
|---------|----------|-----------------|-------|
| Bot detail ana veri | ~5s (tahmini) | hidden → skip | bot.html, bot_multi.html |
| Klines grafik | Sembol bazlı | hidden → skip (loadStripKlinesChart) | bot.html |
| lastBotDetail | Bellekte; her yanıtla güncellenir | — | — |

## Mevcut — Response Boyutları (Tahmini)

| Endpoint | Tahmini Boyut | Büyüme Faktörü |
|----------|---------------|----------------|
| bots_detail (tek sembol) | 5–15 KB | grid_points, profit_points sayısı |
| bots_detail (MULTI/TRDCA) | 10–30 KB | rebalancing_details, assets sayısı |
| events?limit=500 | 50–200 KB | Event sayısı |
| trades | 10–50 KB | Trade sayısı |
| performance | 5–20 KB | period, cycle sayısı |

## Mevcut — Hata Yönetimi

| Hata | Tepki |
|------|-------|
| 404 Bot not found | HTTPException 404 |
| get_account_or_403 fail | 403 |
| PnlService error | pnl_data = {}; devam |
| 24h ticker fail | price_24h_change_pct = None |
| grid_view exception | grid_points = []; log |
| MULTI balances fail | base_value_usd, quote_balance_usd fallback |

## Geliştirilebilir — Tek Endpoint vs Parçalı

| Yaklaşım | Mevcut | Geliştirilebilir | Avantaj |
|----------|--------|------------------|---------|
| Monolitik detail | Evet; bots_detail her şeyi döner | — | Tek istek |
| Parçalı (lazy load) | events, trades, cycles ayrı | Ana detail hafif; sekme açılınca ayrı istek | İlk yükleme hızlı |
| Snapshot benzeri | Hayır | asyncio.gather(detail, events, trades) | Paralel; tek round-trip |

## Geliştirilebilir — Per-Symbol Binance Riski

| Endpoint | Per-symbol çağrı | Konum | Risk |
|----------|------------------|-------|------|
| bots_detail _fetch_24h_ticker | GET ticker/24hr?symbol=X | bots_engine.py:224 | Binance weight 1–40 per sembol |
| _fetch_prices_parallel | N asset → N DataHub/price | bots_engine.py | DataHub; Binance değil |

**UYARI:** bots_detail tek sembol için ticker/24hr?symbol=X çağırır. Bu per-symbol REST; binance_spot _guard ile korunmuyor. Rate limit riski: çok bot detay açık → çok 24h isteği.

## Geliştirilebilir — UI İyileştirmeleri

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Ortak bot detay bileşeni | bot.html ve bot_multi.html kod tekrarı; ortak JS modül | Orta |
| Skeleton loading | İlk yüklemede iskelet göster | Düşük |
| Sekme lazy load | Olaylar/İşlemler sekmesi açılınca istek | Orta |
| Infinite scroll (events) | limit=500 yerine sayfalama | Düşük |
| Offline cache | Son bilgiyi localStorage; offline göster | Düşük |
| Hata retry | 5xx/network → otomatik retry | Orta |

## Geliştirilebilir — Backend İyileştirmeleri

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| 24h ticker DataHub'dan | ticker/24hr?symbol yerine DataHub 24h cache | Yüksek (rate limit) |
| Cevap önbelleği | bots_detail kısa TTL cache (5–10s) | Orta |
| Field projection | ?fields=state,grid (isteğe bağlı alanlar) | Düşük |
| ETag / If-None-Match | Değişmediyse 304 | Düşük |

## Mevcut — Dashboard Entegrasyonu

| Akış | Tetikleyici | Endpoint | Sonuç |
|------|-------------|----------|-------|
| "Düzenle" tıkla | Bot satırına tıkla | GET /api/bots/{id}/detail?account_id=X | Create modal açılır; config doldurulur |
| Start/Stop | Modal içi buton | POST .../start veya .../stop | Command; sayfa yenilenir |

## Bot Detay Sayfası Checklist

- [ ] bot.html vs bot_multi.html: doğru sayfa açılıyor (symbol == MULTI kontrolü)
- [ ] lastBotDetail güncel (symbol, baseBalance, quoteAsset)
- [ ] visibilityState hidden → poll atlanıyor
- [ ] Events limit=500; büyük hesaplarda yavaş olabilir
- [ ] 24h ticker per-symbol; rate limit riski

## Mevcut — Sayfa Yönlendirme Mantığı

| Koşul | Sayfa | URL |
|-------|-------|-----|
| symbol != MULTI | bot.html | /ui/bot.html?bot_id=X&account_id=Y |
| symbol == MULTI | bot_multi.html | /ui/bot_multi.html?bot_id=X&account_id=Y |
| Dashboard "Düzenle" | Create modal veya bot detay | loadBotDetailForEdit(botId, accountId) |

## Mevcut — lastBotDetail Kullanımı

| Alan | Kaynak | Kullanım |
|------|--------|----------|
| symbol | data.symbol | Grid, işlem, sembol grafiği |
| baseBalance | (data.state \|\| {}).base_balance | Silme uyarısı; stopDeleteConvertDetail |
| quoteAsset | USDT/FDUSD/BUSD | Silme açıklaması |
| multiCoins | TRDCA/DCA coin_weights | Rebalancing panel (bot_multi) |

## Geliştirilebilir — Performans Metrikleri

| Metrik | Mevcut | Geliştirilebilir |
|--------|--------|------------------|
| bots_detail süresi | Yok | Response header X-Response-Time |
| events yükleme | limit=500 sabit | Sayfalama; cursor |
| trades yükleme | cycle_id optional | LIMIT; offset |
| İlk paint (FCP) | — | Skeleton; progressive render |

## Özet — Mevcut vs Geliştirilebilir

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| Endpoint | Monolitik bots_detail | Parçalı lazy load |
| 24h ticker | Per-symbol Binance REST | DataHub 24h cache |
| UI | bot.html + bot_multi.html ayrı | Ortak bileşen |
| Polling | intervalRegistry, ~5s | Aynı |
| Hata | Partial fallback | Retry; skeleton |

---

# SECTION E.3 — PERFORMANS RAPORU (BOT DETAY)

## Mevcut — Endpoint Envanteri

| Endpoint | Metod | Auth | Veri Kaynağı | Tetikleyici |
|----------|-------|------|--------------|-------------|
| GET /api/bots-engine/{id}/performance | GET | require_auth | PnlService, Ledger, PnlSnapshot, bot_engine_events, bot_perf_chart_state | Performans sekmesi; period değişince |
| GET /api/bots-engine/{id}/perf-chart-state | GET | require_auth | bot_perf_chart_state | Grafik mount; range değişince |
| PUT /api/bots-engine/{id}/perf-chart-state | PUT | require_auth | bot_perf_chart_state | Frontend saveStorage (localStorage sync) |
| DELETE /api/bots-engine/{id}/perf-chart-state | DELETE | require_auth | bot_perf_chart_state | Sıfırla butonu |

## Mevcut — Response Yapısı (performance)

| Alan | Tip | Kaynak | Açıklama |
|------|-----|--------|----------|
| pnl_usd | float | state.cycle_pnls veya CYCLE_END events | Toplam gerçekleşen kar (USDT) |
| pnl_pct | float | pnl_usd / initial * 100 | Kar yüzdesi |
| real_performance_pct | float | pnl_pct (TRDCA: bakiye % − parite %) | Gerçek performans |
| trades_count | int | Trade tablosu | Dönem içi işlem sayısı |
| fees_usd | float | Trade.fee toplamı | Dönem içi komisyon |
| cycles_count | int | Ledger.get_cycle_ids | Tamamlanan tur sayısı |
| chart_series | array | PnlSnapshot veya bot_perf_chart_state | Bakiye % zaman serisi |
| pair_series | array | bot_perf_chart_state (TRDCA) veya fiyat | Parite % zaman serisi |
| cycle_pnl_last | float | state.cycle_pnls son eleman | Son tur karı |
| cycle_pnl_last_net | float | cycle_pnl_last (fee dahil) | Net |
| pnl_calculation_mode | string | cycle_pnls veya config | cycle_only_fee_aware_v1, legacy |
| realized_pnl_total | float | PnlService | Toplam gerçekleşen |
| rebalance_pnl | array | _compute_trdca_pnl_breakdown | TRDCA: coin bazlı rebalance karı |
| dca_pnl_usd | float | _compute_trdca_pnl_breakdown | TRDCA: DCA satış kazancı |
| dca_adet_pnl | array | _compute_trdca_pnl_breakdown | TRDCA: DCA adet karı |

## Mevcut — PnL Hesaplama Mantığı

| Kaynak | Öncelik | Kullanım |
|--------|---------|----------|
| state.cycle_pnls | 1 | Her tur tamamlandıkça eklenen kar; anında yansır |
| bot_engine_events (CYCLE_END) | 2 | cycle_pnls yoksa event meta_json.profit_usdt |
| PnlSnapshot | 3 | Period bazlı initial/end değerleri; chart serisi (tek sembol) |
| Trade tablosu | 4 | İlk alım fiyatı; fee toplamı |

## Mevcut — Periyot Seçenekleri

| period | start_ts | Filtre |
|--------|----------|--------|
| all | None | Tüm veriler; referans = config initial_capital |
| day / 1d | now - 1 gün | Trades, fees bu dönemde |
| week / 7d | now - 7 gün | Trades, fees bu dönemde |
| month / 30d | now - 30 gün | Trades, fees bu dönemde |

## Mevcut — Grafik Veri Kaynakları

| Strateji | chart_series | pair_series |
|----------|--------------|-------------|
| TRDCA | bot_perf_chart_state.samples (botPct) | bot_perf_chart_state.samples (paritePct) |
| Tek sembol | PnlSnapshot total_usd | Trade fiyatları veya current_price |
| Multi-asset | — | — |

## Mevcut — bot_perf_chart_state

| Alan | Tip | Açıklama |
|------|-----|----------|
| baseline | object | bot0, parite0, ts0; TRDCA: initial_prices, coin_weights |
| samples | array | {ts, botPct, paritePct} zaman serisi |
| range | string | 1m, 5m, 1h, 4h, 1d |

## Mevcut — Sample Ekleme (append_perf_chart_sample)

| Tetikleyici | Konum | Frekans |
|-------------|-------|---------|
| main.py | _perf_chart_sample_loop | Her 60 saniyede tüm running botlar için |
| worker_main.py | worker_loop (loop_count % 60 == 0) | ~60 döngüde bir; running botlar |
| append_perf_chart_sample | bots_engine.py:748 | PERF_CHART_MAX_AGE_SEC = 7 gün; bucket'a göre ekleme |

## Mevcut — UI Bileşenleri (Performans sekmesi)

| Bileşen | Dosya | Veri |
|---------|-------|------|
| perfReportStartBakiye | bot.html, bot_multi.html | Başlangıç bakiyesi |
| perfReportGuncelBakiye | — | Güncel bakiye |
| perfReportRefPrice | — | Referans fiyat |
| perfReportPariteGuncel | — | Parite güncel (TRDCA) |
| perfReportBakiyeDegisim | — | Bakiye % değişim |
| perfReportPariteDegisim | — | Parite % değişim |
| perfReportGercekPerf | — | Gerçek performans (Bakiye % − Parite %) |
| perfChartWrap | — | Grafik container; tıklanınca modal |
| perf_chart_tv.js | — | TradingView Lightweight Charts; getDataFromDom |

## Mevcut — perf_chart_tv.js Sabitleri

| Sabit | Değer | Açıklama |
|-------|-------|----------|
| STORAGE_KEY_PREFIX | perf_tv_samples_v1 | localStorage key |
| SAVE_EVERY_N | 5 | Her N sample'da backend PUT |
| MAX_AGE_SEC | 7 * 24 * 3600 | 7 gün |
| RANGE_SEC | 1m:60, 5m:300, 1h:3600, 4h:14400, 1d:86400 | Bucket süreleri |
| DISPLAY_WINDOW_SEC | 1m:24h, 5m:7d, 1h:24h, 4h:7d, 1d:30d | Görüntüleme penceresi |
| LIVE_UPDATE_INTERVAL_MS | 5000 | Canlı güncelleme |

## Mevcut — Hata Yönetimi

| Hata | Tepki |
|------|-------|
| PnlService error | pnl_data = {}; total_usd 0 |
| load_state None | state_for_pnl = {}; CYCLE_END events fallback |
| bot_perf_chart_state yok | chart_series, pair_series boş veya PnlSnapshot |
| _fetch_prices_parallel fail | parite_pct live hesaplanamaz; son sample kullan |

## Geliştirilebilir — Performans Raporu

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| period parametresi cache | Aynı period tekrar istekte cache (5–10s TTL) | Orta |
| chart_series pagination | Uzun süreli botlarda samples çok; range ile sınırla | Orta |
| Export CSV/PDF | Performans raporu dışa aktarma | Düşük |
| Karşılaştırmalı grafik | Birden fazla bot aynı grafikte | Düşük |
| Yıllık/özel period | 90d, 1y, custom date range | Düşük |

## Geliştirilebilir — Grafik

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| getDataFromDom bağımlılığı | Grafik DOM'dan parse ediyor; API'den direkt alsın | Yüksek |
| Sample senkronizasyonu | Frontend localStorage vs backend race | Orta |
| Mobil touch | Grafik zoom/pan touch iyileştirmesi | Düşük |
| Grafik yükleme süresi | İlk render gecikmesi; skeleton | Düşük |

## Geliştirilebilir — PnL Hesaplama

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| cycle_pnls vs CYCLE_END tutarlılığı | İki kaynak farklı sonuç verebilir | Yüksek |
| pnl_mode dokümantasyonu | cycle_only_fee_aware_v1 vs legacy farkı | Orta |
| MULTI/TRDCA PnL breakdown | rebalance_pnl, dca_pnl detaylı açıklama | Düşük |

## Mevcut — TRDCA Parite Hesaplama

| Formül | Açıklama |
|--------|----------|
| Parite % = Σ (weight_i × (current_i - initial_i) / initial_i × 100) | Ağırlıklı ortalama fiyat değişimi |
| compute_trdca_parite_pct | perf_chart_state.py |
| initial_prices, coin_weights | baseline'dan |

## Mevcut — seed_perf_chart_state_on_bot_start

| Adım | İşlem |
|------|-------|
| 1 | Bot start → seed_perf_chart_state_on_bot_start |
| 2 | baseline = {bot0: 0, parite0: 0, ts0: now} |
| 3 | TRDCA: initial_prices = DataHub fiyatları; coin_weights = config |
| 4 | INSERT/UPDATE bot_perf_chart_state; samples = [] |

## Mevcut — Range Butonları (perf_chart_tv)

| Range | Bucket süre | Görüntüleme penceresi | Kullanım |
|-------|-------------|------------------------|----------|
| 1m | 60 sn | Son 24 saat | Dakikada bir nokta |
| 5m | 5 dk | Son 7 gün | Bot başlangıcından 5 dk'da bir |
| 1h | 1 saat | Son 24 saat | Saatte bir |
| 4h | 4 saat | Son 7 gün | 4 saatte bir |
| 1d | 1 gün | Son 30 gün | Günlük |

## Mevcut — Veri Akışı (Özet)

```
Bot start → seed_perf_chart_state_on_bot_start (baseline, samples=[])
    ↓
main.py _perf_chart_sample_loop (60s) / worker_main (60 iter) → append_perf_chart_sample
    ↓
bot_perf_chart_state.samples güncellenir (bucket bazlı; 7 gün max)
    ↓
GET /performance?period=X → chart_series, pair_series (TRDCA: samples'tan)
    ↓
Frontend: perfReport* DOM doldurulur; perf_chart_tv getDataFromDom ile parse
    ↓
PerfChartTV.init/start; range değişince setRange; saveStorage → PUT perf-chart-state
```

## Performans Raporu Checklist

- [ ] GET /performance period=all, day, week, month test
- [ ] TRDCA: chart_series, pair_series dolu mu
- [ ] Tek sembol: PnlSnapshot veya Trade tabanlı chart
- [ ] cycle_pnl_last state.cycle_pnls son elemandan
- [ ] perf_chart_tv getDataFromDom DOM ID'leri mevcut
- [ ] Sıfırla → DELETE perf-chart-state → grafik temizlenir

## Özet — Performans Raporu Mevcut vs Geliştirilebilir

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| Veri kaynağı | PnlService, state, events, PnlSnapshot, bot_perf_chart_state | — |
| Grafik | perf_chart_tv.js; DOM parse | API'den direkt |
| Periyot | all, 1d, 7d, 30d | 90d, 1y, custom |
| TRDCA breakdown | rebalance_pnl, dca_pnl_usd | Detaylı dokümantasyon |
| Cache | Yok | 5–10s TTL |

---

# SECTION E.4 — UI GÖRÜNTÜLEME, OPTİMİZASYON VE HIZ

## Mevcut — Sayfa Yapısı ve İlk Yükleme

| Sayfa | HTML | CSS sayısı | JS sayısı (sync) | defer JS | İlk blok |
|-------|------|------------|------------------|----------|----------|
| dashboard.html | Monolitik; tab içerikleri inline | 8 (ticker, theme, ui, design, dashboard, binance-colors, blink, dashboard-login-theme) | 14+ (apiClient, errorReporter, intervalRegistry, stores, services, api, components, spot_engine, coinLogo, dashboard) | ticker.js | Token kontrolü; yoksa login'e yönlendir |
| bot.html | Monolitik; sekmeler inline | 3 (theme, design, blink) + inline style | Çoklu; setInterval doğrudan (intervalRegistry değil) | — | Token; sonra detail + events |
| bot_multi.html | Aynı yapı | Aynı | Aynı | — | Aynı |
| login.html | Form + animasyon | login.css + theme | login logic | admin.js, ticker (admin) | Token yok; form |
| admin.html | Tab'lı panel | 4+ | admin.js defer | admin.js, ticker defer | Token; admin yetkisi |

## Mevcut — Görünürlük Kontrolü (FCP / Flash Önleme)

| Mekanizma | Dosya | Davranış |
|-----------|-------|----------|
| documentElement visibility hidden | dashboard.html:17, admin.html:16 | İlk script: r.style.visibility = 'hidden'; token yoksa login'e replace; token varsa sayfa görünür yapılmaz bu script'te (CSS/sonraki JS'te açılır) |
| dashboardMainContainer visibility hidden | dashboard.html:135 | container başta visibility: hidden; sekme restore sonrası görünür yapılır (Anasayfa blink önleme) |
| Tab restore | dashboard.js | sessionStorage savedTab; initDashboard'ta hemen aktif tab set edilir; böylece refresh'te "Yükleniyor" yerine doğru tab gösterilir |

## Mevcut — CSS Yükleme Sırası (Dashboard)

| Sıra | Dosya | Amaç |
|------|-------|------|
| 1 | ticker.css | Üst ticker bant |
| 2 | theme.css | CSS değişkenleri (renk, tipografi) |
| 3 | ui.css | Genel bileşenler, skeleton, hata banner |
| 4 | design.css | Form, buton, panel tasarımı |
| 5 | dashboard.css | Dashboard layout, KPI, tab, varlıklar |
| 6 | binance-colors.css | Binance yeşil/kırmızı |
| 7 | blink.css | Fiyat blink animasyonu |
| 8 | dashboard-login-theme.css | Giriş teması |

Tüm CSS'ler render-blocking (link rel="stylesheet"); async/defer yok. İlk paint CSS'lerin sırayla yüklenmesinden sonra.

## Mevcut — JavaScript Yükleme Sırası (Dashboard)

| Sıra | Dosya | Bloklama | Amaç |
|------|-------|----------|------|
| 1 | trTime.js | Sync | Zaman formatı |
| 2 | maintenanceOverlay.js | Sync | Bakım overlay |
| 3 | apiClient.js | Sync | HTTP client, timeout 20 |
| 4 | errorReporter.js | Sync | Hata raporlama |
| 5 | intervalRegistry.js | Sync | setInterval wrapper; visibility skip |
| 6 | marketStore, financeStore, botStore | Sync | State store'lar |
| 7 | marketDataService, financeService | Sync | Servisler |
| 8 | api.js, components.js | Sync | API wrapper, Toast, skeleton helper |
| 9 | spot_engine.js | Sync | Spot trade engine |
| 10 | coinLogo.js | Sync | Coin logo URL |
| 11 | dashboard.js | Sync | Ana mantık; initDashboard, fetchSnapshot |
| 12 | ticker.js | defer | Ticker güncelleme |

dashboard.js büyük (~10k+ satır); parse/compile süresi ilk yüklemede hissedilir. defer sadece ticker.js'te.

## Mevcut — Dashboard Snapshot Akışı

| Adım | Tetikleyici | Endpoint | Timeout | inFlight |
|------|-------------|----------|---------|----------|
| 1 | initDashboard; accountId set | GET /api/dashboard/snapshot?account_id=X | 12000 ms | State.inFlight = true |
| 2 | intervalRegistry 'dashboard_snapshot' | Aynı endpoint | 12000 | Aynı |
| Aralık | SNAPSHOT_POLL_MS = 5000 | Her 5 saniye | — | visibilityState hidden ise tick atlanır |

applySnapshotToUI: prices → marketStore; wallet → assetsState + renderVarliklarList; pnl → updateFinanceKPIs, renderFinanceBots; bots + account → State.bots, renderBotsList, updateKPIs. Tek response ile tüm ana veri güncellenir (progressive render yok; tek applySnapshotToUI çağrısı). wallet _error gelince status='error' atanır, UI'da "Binance cüzdanı alınamadı — Yenile | Ayarlara git" gösterilir (sonsuz loading önleme).

## Mevcut — Dashboard Interval Envanteri (Aktif Sekmeye Göre)

| Key | ms | Owner | Tetiklenen | visibilityState |
|-----|-----|-------|------------|-----------------|
| dashboard_snapshot | 5000 | dashboard | fetchSnapshot | hidden → atlanır |
| kpi.spot-status | 5000 | dashboard | updateKpiCuzdanLiveStatus | hidden → atlanır |
| datahub.ws-status | 5000 | dashboard | updateDatahubWsIndicator | hidden → atlanır |
| finance.bots.prices | 1500 | dashboard | updateFinanceBotsLivePrices | hidden → atlanır |
| auth.health | (değişken) | — | /api/auth/ping | hidden → atlanır |
| dashboard.lockdown-check | (değişken) | — | Lockdown API | hidden → atlanır |
| binanceApiBanner.time | 10000 | dashboard | updateBinanceApiBannerTime | hidden → atlanır |
| tab.varliklar.prices | 2000 | tab.varliklar | tickVarliklarPrices | Binance sekmesi aktifken; hidden → atlanır |
| tab.coinlist.tick | 2000 | tab.coinlist | tickBinanceCoinListPrices | Aynı |
| wallet:poll | 15000 | binanceTab | pollWallet | Binance sekmesi; snapshot kullanıldığı için dashboard'da wallet poll yok |
| orders:poll | 10000 | binanceTab | loadActiveOrders | Binance sekmesi |
| finance.trades:poll | 15000 | binanceTab | loadFinanceTrades | Binance sekmesi |
| trade.modalSpotPrice, trade.modalPriceChange, trade.balance, trade.modalPrice, trade.priceChange | 1000–1500 | — | Spot modal açıkken | — |
| activeOrders.prices | (tick) | — | Aktif emirler fiyat güncelleme | — |

intervalRegistry: her tick'te document.visibilityState === 'hidden' ise fn() çağrılmaz; sadece clear edilmez. Sekme tekrar visible olunca bir sonraki tick'te çalışır.

## Mevcut — Dashboard Sekmeleri (Tab Visibility)

Sadece aktif sekme içeriği görünür olmalı; Anasayfa panelleri (Performans Analizi, İşlemler, Favori Coinler, Mevcut Botlar) diğer sekmelerde (İletişim, Ayarlar vb.) görünmemelidir.

| Öğe | Davranış |
|-----|----------|
| dm-tab | Butonlar: data-tab = binance \| bots \| finance \| contact \| settings. Tıklanınca is-active tek butonda. |
| dm-tab-content | İçerik blokları: tabBinance, tabBots, tabFinance, tabContact, tabSettings, mobileTradeView. Sadece biri is-active + display block. |
| CSS | .page-dashboard .dm-tab-content { display: none !important }; .dm-tab-content.is-active { display: block !important }. |
| JS (dashboard.js) | bindTabs: tüm dm-tab-content'lardan is-active kaldırılır, display none atanır; hedef content'e is-active + display block verilir. initDashboard: varsayılan sekme binance (reports/varliklar → binance); kayıtlı sekme yoksa veya geçersizse Anasayfa açılır. |
| reports | DOM'da tabReports yok; data-tab="reports" yok. Eski localStorage "reports" veya varsayılan artık tabBinance (Anasayfa) ile eşlenir. |
| Mobil (setMobileTab) | Aynı kural: tüm dm-tab-content display none; seçilen tek content display block. trade sekmesi → mobileTradeView gösterilir. |

Bu sayede paneller yalnızca ilgili sekmede görünür; alakasız sekmelere taşınma olmaz.

## Mevcut — Bot Detay Sayfası Polling

| Poll | Aralık | Endpoint / İşlem | visibilityState |
|------|--------|------------------|-----------------|
| Fiyat / durum | 1000 ms (pricePollMs) | GET /api/bots-engine/{id}?account_id=X | document.hidden ise return; poll çalışmaz |
| Strip klines | stripKlinesRefreshMs | loadStripKlinesChart(symbol) | document.hidden ise return |
| visibilitychange | — | refreshAll() | Sekme visible olunca bir kez refreshAll |

bot.html / bot_multi.html setInterval doğrudan kullanıyor; intervalRegistry değil. Her saniye GET bots-engine (fiyat, state, grid, 24h) — ağır istek; arka planda sekme kapalıyken atlanıyor.

## Mevcut — Skeleton ve Yükleme Göstergeleri

| Konum | Bileşen | Mevcut |
|-------|---------|--------|
| Dashboard bot listesi | financeBotsList | Başta "Yükleniyor..." metni; skeleton CSS sınıfları (skeleton-loader, skeleton-line, skeleton-bot-card) ui.css'te tanımlı; dashboard'da bots-skeleton kullanımı kısıtlı. Tablo: Sembol, FİYAT (sembol canlı fiyatı; marketStore/getLivePrice), Durum, Bütçe, Bot Bakiyesi (current_usd; snapshot ile güncellenir), Toplam K/Z, Tur, İşlem. Mobil kartta FİYAT alanı tek sembolde canlı fiyat, çoklu botta "—". |
| Dashboard varlıklar | varliklarTableBody | "Yükleniyor..." satırı; sonra renderVarliklarList ile doldurulur |
| Dashboard coin listesi | binanceCoinListBody | "Yükleniyor..." satırı |
| Bot detay | — | loading sınıfı, "Yükleniyor..." metinleri; genel skeleton yok |
| components.js | createSkeleton(width, height) | Genel skeleton div; kullanım yerleri sınırlı |

ui.css: .page-dashboard .skeleton-loader (shimmer 1.5s), .skeleton-line, .skeleton-bot-card, .bots-skeleton grid. design.css: .skeleton. Tam sayfa skeleton (FCP için) yok; sadece bölüm bazlı metin.

## Mevcut — requestAnimationFrame Kullanımı

| Dosya | Kullanım |
|-------|----------|
| dashboard.js | updateSpotTradeModal, fiyat hücre sınıf güncelleme, initDashboard sonrası DOM güncelleme; flicker azaltma |
| perf_chart_tv.js | Grafik çizim sonrası; mergeChartStateFromServer öncesi kontrol |
| perf_chart_rebuild.js | buildMiniChart, boyut hesaplama; display:none sonrası getBoundingClientRect için iki kademe RAF |
| login.html | Animasyon döngüsü (rafId = requestAnimationFrame(loop)) |
| marketDataService.js | Fiyat güncelleme sonrası UI senkronizasyonu |

RAF: repaint öncesi güncelleme; layout thrash azaltır. Yoğun DOM güncellemelerinde her yerde kullanılmıyor.

## Mevcut — DOM Güncelleme Stratejileri

| Güncelleme | Yöntem | Not |
|------------|--------|-----|
| Bots listesi | renderBotsList(data.bots); innerHTML veya düğüm listesi yeniden oluşturma | Tüm liste yeniden render |
| Varlıklar tablosu | renderVarliklarList(); tbody içeriği yeniden oluşturulur | Tüm satırlar |
| Fiyat hücresi | textContent + classList add/remove (blink-positive, blink-negative) | Noktasal; setTimeout ile class temizleme |
| KPI değerleri | textContent atama; updateKPIs, updateFinanceKPIs | Doğrudan atama |
| Snapshot apply | applySnapshotToUI tek geçişte prices, wallet, pnl, bots | Sıralı; büyük DOM güncellemesi |

Diff/VDOM yok; tam liste yeniden çizim. Liste büyükse (100+ bot, 50+ varlık) layout/paint maliyeti artar.

## Mevcut — Ağ İstekleri (Dashboard İlk Açılış)

| Sıra | İstek | Ne Zaman |
|------|--------|----------|
| 1 | resolveAccountFromUrl / loadAccountMeta | initDashboard başında |
| 2 | loadBotsListFast(accountId) | Hemen sonra |
| 3 | fetchSnapshot() | accountId set; ilk çağrı |
| 4 | ensureFeeRates(accountId) | Arka planda |
| 5+ | Tab'a göre: Binance sekmesi → loadActiveOrders (1.5s sonra), loadCoinList, loadFinanceTrades; Finance → loadFinanceSummary, loadEquityCurve vb. | Sekme değişince veya restore |

Snapshot tek istekte: prices, wallet, pnl, bots, account. Ayrı wallet/prices/summary poll yok (dashboard'da).

## Mevcut — Bot Detay İlk Yükleme İstekleri

| Sıra | İstek | Amaç |
|------|--------|------|
| 1 | GET /api/bots/{id}/detail?account_id=X (veya bots-engine detail) | Config, state, grid |
| 2 | GET /api/bots-engine/{id}/events?limit=500 | Olaylar sekmesi |
| 3 | (TRDCA) 24h ticker / fiyat | Parite, performans |
| 4 | Performans sekmesi açılınca | GET /api/bots-engine/{id}/performance?period=X |
| 5 | Grafik mount | GET /api/bots-engine/{id}/perf-chart-state |

detail tek büyük response; events limit=500; aynı anda birkaç istek. Lazy load: sadece performans/chart state sekme/mount anında.

## Mevcut — Cevap Boyutu (Tahmini)

| Endpoint | Tahmini boyut | Not |
|----------|----------------|-----|
| /api/dashboard/snapshot | 50–200 KB+ | prices (N sembol), wallet (M varlık), bots (K bot), pnl; hesap büyüdükçe artar |
| /api/bots-engine/{id} | 10–80 KB | state_json, grid, config |
| /api/bots-engine/{id}/events?limit=500 | 50–300 KB | 500 event; meta_json dahil |
| /api/bots-engine/{id}/performance | 5–30 KB | chart_series, pair_series dahil |
| /api/bots-engine/{id}/perf-chart-state | 5–50 KB | samples 7 gün |

3G model (100–200 kbps): 200 KB ≈ 8–16 saniye. Snapshot 200 KB ise timeout 12s ile sınırda.

## Mevcut — Hata ve Timeout

| Katman | Timeout | Hata gösterimi |
|--------|---------|----------------|
| apiClient.get | options.timeout (dashboard snapshot 12000) | errorReporter; applySnapshotToUI çağrılmaz |
| fetchSnapshot | 12000 | State.inFlight = false; konsol uyarı |
| inFlight guard | — | Aynı anda iki snapshot önlenir; takılı kalırsa manuel refresh gerekir |
| Bot detail | apiClient default (5000?) | loading kalabilir; partial fallback |

inFlight bir kez true kalırsa sonraki snapshot'lar atlanır; kullanıcı sayfayı yenilemeli.

## Mevcut — Görsel Varlıklar

| Tür | Kaynak | Optimizasyon |
|-----|--------|--------------|
| Coin logolar | /ui/assets/coins/{SYMBOL}.png; coinLogo.js; GET /ui/assets/coins/*.png Cache-Control: public, max-age=31 gün | Sayfa yenilemede logolar yeniden indirilmez (cache); varlık/coin satırında img |
| Ticker | Top ticker bant | Tek bileşen |
| Grafik | lightweight-charts.standalone.production.js | Vendor tek dosya; sayfa başında yüklenmez (bot detayda script varsa orada) |

Coin logoları preload/lazy decode yok; viewport dışı satırlar da yüklenir (tablo scroll ile).

## Mevcut — Mobil ve Viewport

| Özellik | Değer |
|---------|--------|
| viewport | width=device-width, initial-scale=1.0, viewport-fit=cover (dashboard) |
| Touch | Standart; özel touch handler dokümantasyonu yok |
| Bottom nav | initMobileBottomNav(); mobil alt menü |
| Responsive | design.css, dashboard.css media query'ler; panel grid |

Mobil 3G'de büyük snapshot + çok CSS/JS = yavaş FCP/LCP. Ayrı mobil bundle yok.

## Geliştirilebilir — İlk Yükleme (FCP / LCP)

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Critical CSS inline | theme + above-the-fold tek blok inline; diğerleri async | Yüksek |
| JS code split | dashboard.js → chunk'lar (tabs: binance, finance, bots, settings); sekme açılınca yükle | Yüksek |
| defer/async script | Ana script'ler defer; DOMContentLoaded'da init | Orta |
| Skeleton FCP | Body'de hemen skeleton (KPI + bot kartları iskeleti); veri gelince doldur | Orta |
| visibility hidden kaldırma | Token varsa ilk paint'te visibility: visible (tek frame gecikme) | Düşük |

## Geliştirilebilir — CSS

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| CSS birleştirme / minify | 8 ayrı CSS → build'de tek veya 2 (critical + lazy) | Orta |
| Kullanılmayan kurallar | Purge; sadece kullanılan sınıflar | Düşük |
| Preload font | Varsa özel font; preload link | Düşük |

## Geliştirilebilir — Snapshot ve Ağ

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Snapshot sıkıştırma | Brotli/gzip response; Accept-Encoding | Yüksek |
| Snapshot alan filtreleme | ?fields=prices,wallet,bots; isteğe göre pnl/events atlama | Orta |
| Snapshot TTL cache | Aynı account_id 2–3s içinde tekrar istek → 304 veya in-memory cache | Orta |
| Chunked / stream | Önce prices, sonra wallet, sonra bots (progressive) | Düşük |
| Payload boyutu izleme | Log/métrique; 200 KB üstü uyarı | Düşük |

## Geliştirilebilir — Polling ve Arka Plan

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Bot detay intervalRegistry | setInterval → intervalRegistry; visibility skip merkezi | Orta |
| Bot detay poll aralığı | 1s yerine 2–3s; veya değişiklik yoksa backoff | Orta |
| Sekme bazlı interval | Sadece görünen tab'ın interval'leri; diğerleri durdur | Orta |
| Page Visibility API tutarlılığı | Tüm poll'lar document.hidden kontrolü (zaten intervalRegistry'de) | Düşük |

## Geliştirilebilir — DOM ve Render

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Listelerde virtual scroll | 100+ bot / 50+ varlık için sadece viewport satırları render | Orta |
| Diff tabanlı güncelleme | Sadece değişen satır/hücre güncelle; tam liste yeniden yazma | Düşük |
| RAF batch | Çoklu DOM güncellemesini tek requestAnimationFrame'de topla | Düşük |
| will-change / contain | Sık güncellenen bloklarda contain: layout paint | Düşük |

## Geliştirilebilir — Grafik ve Ağır Bileşenler

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Grafik lazy load | lightweight-charts script'i performans sekmesi açılınca yükle | Orta |
| Grafik worker | Ağır hesaplama Web Worker; UI thread serbest | Düşük |
| Chart resize | ResizeObserver zaten var; debounce ile layout sayısı azaltma | Düşük |

## Geliştirilebilir — Görsel Varlıklar

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Coin logo lazy load | img loading="lazy"; veya Intersection Observer | Orta |
| Logo sprite / SVG | Çok küçük ikonlar için sprite veya tek SVG | Düşük |
| Placeholder | Logo yüklenene kadar placeholder renk/initials | Düşük |

## Geliştirilebilir — Hata ve Sağlamlık

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| inFlight timeout | inFlight 15–20s sonra zorla false; takılma önleme | Yüksek |
| Snapshot retry | 1–2 otomatik retry (exponential backoff) | Orta |
| Offline cache | Son başarılı snapshot localStorage; offline'da göster | Düşük |
| Error boundary (benzeri) | Bir bileşen hata verirse diğer bloklar çalışsın | Düşük |

## Geliştirilebilir — Mobil ve Yavaş Ağ

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Network-aware payload | 3G/slow-connection'da daha az alan veya daha seyrek poll | Orta |
| Düşük veri modu | Kullanıcı seçerse: skeleton uzun kalsın, tab lazy, grafik kapalı | Düşük |
| Touch performansı | Scroll/touch için passive listener; gereksiz repaint azaltma | Düşük |

## Mevcut — Sayfa Bazlı Script/CSS Boyutları (Referans)

| Dosya | Tahmini satır / boyut | Not |
|-------|------------------------|-----|
| dashboard.js | 10k+ satır | Parse/compile ilk yüklemede; minify edilmiş prod boyutu ölçülmeli |
| ui.css | 3k+ satır | Skeleton, admin, dashboard stilleri |
| design.css | 1k+ satır | Form, panel, genel bileşen |
| dashboard.css | 2k+ satır | KPI, tab, varlıklar, coin list |
| theme.css | Değişkenler | Küçük; kritik renk/tipografi |
| apiClient.js | ~200 satır | Timeout, slot, retry |
| intervalRegistry.js | ~190 satır | Küçük; kritik |
| lightweight-charts.standalone.production.js | Vendor | Bot detayda; büyük tek dosya |

Build/minify yok; kaynak dosyalar doğrudan sunuluyor. Gzip/Brotli sunucu tarafında açık olabilir; kontrol edilmeli.

## Mevcut — Tab Geçişi ve Lazy Load

| Tab | İlk yükleme | Lazy |
|-----|-------------|------|
| Anasayfa (Binance) | Snapshot ile birlikte varlıklar, botlar, KPI | loadActiveOrders 1.5s gecikmeli; loadCoinList tab açılınca |
| Botlar | renderBotsList snapshot'tan | Ek istek yok; snapshot'taki bots |
| Finansal Hesap | Snapshot pnl, wallet | loadFinanceSummary, loadEquityCurve, loadFinanceTrades tab'a girilince |
| İletişim | Sohbet butonu | loadChat modal açılınca |
| Ayarlar | Form alanları | loadAccountMeta; API key vb. |

Tam tab lazy load yok; tüm tab içerikleri DOM'da; display/visibility ile gizleniyor. Sadece veri çekimi tab'a göre tetikleniyor.

## Mevcut — Debounce ve Throttle

| Yer | Mekanizma | Süre |
|-----|-----------|------|
| Create modal sembol arama | dmSymbolInputDebounce, dmTrdcaSymbolInputDebounce, dmMultiSymbolInputDebounce | setTimeout ile gecikme; tekrarlı input'ta istek azaltma |
| Fiyat blink | BLINK_COOLDOWN_MS = 400 | Aynı hücrede 400ms içinde tekrar blink yok |
| walletPollBackoffUntil | 429 sonrası poll atlama | Süre dolana kadar wallet poll yok |
| Coin list search | Debounce (varsa) | Arama metni için |

Throttle: intervalRegistry tick'leri zaten süre sınırlı (3s, 5s, 1.5s). Scroll/resize için throttle dokümante edilmemiş.

## Mevcut — Bellek ve Temizlik

| Olay | Temizlik |
|------|----------|
| beforeunload | intervalRegistry.stopAll(); timeouts clear |
| Tab değişimi | Binance tab'dan çıkılınca wallet:poll, orders:poll stopByOwner ile durdurulabilir; mevcut kodda sekme değişince tüm interval'ler durmuyor; sadece hidden'da tick atlanıyor |
| Modal kapanınca | dmModalLivePriceIntervalId clearInterval; trade modal fiyat interval'leri stop |
| Bot detay sayfadan çıkış | setInterval'ler sayfa kapanınca tarayıcı tarafından temizlenir; explicit stop yok |

Uzun süre açık sekmede interval sayısı sabit; sızıntı yok. Çok sekme açıkken her sekme kendi interval'leri ile çalışır (her biri visibility skip yapar).

## Mevcut — API Client Sınırları

| Parametre | Değer | Dosya |
|-----------|-------|-------|
| DEFAULT_TIMEOUT | 5000 (veya 20) | apiClient.js; dashboard snapshot 12000 override |
| MAX_CONCURRENT | 2 | Slot limiter; aynı anda 2 istek |
| Slot takılması | İstek atılmazsa slot serbest kalmayabilir | Retry/cleanup dokümante |

Dashboard tek snapshot ile çalıştığı için concurrent çoğunlukla 1. Bot detayda paralel detail + events olabilir.

## Geliştirilebilir — Ölçüm ve Metrik

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| FCP / LCP / TTI | performance.getEntriesByType('paint'); Largest Contentful Paint API | Yüksek |
| Snapshot süresi | X-Response-Time header veya performance.now() ile client tarafı süre | Orta |
| Long tasks | PerformanceObserver long task; 50ms üstü görevler | Düşük |
| Core Web Vitals raporu | LCP, FID, CLS; dashboard ve bot detay için hedefler | Orta |

## Geliştirilebilir — Build ve Dağıtım

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Minify JS/CSS | Prod'da minify; kaynak map ayrı | Yüksek |
| Bundle split | Dashboard: vendor chunk (apiClient, intervalRegistry, stores) + app chunk; lazy tab chunk'ları | Orta |
| Asset versioning | ?v= parametresi var; cache bust; build hash otomatik | Düşük |
| Service Worker | Offline cache; snapshot son sonuç; opsiyonel | Düşük |

## Geliştirilebilir — Erişilebilirlik ve UX

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Loading state tutarlılığı | Tüm listelerde skeleton aynı pattern; aria-busy | Orta |
| Focus yönetimi | Modal açılınca focus trap; kapanınca önceki elemana dönüş | Düşük |
| Reduced motion | prefers-reduced-motion için blink/animasyon kapatma | Düşük |

## Mevcut — Özet Sayısal Referanslar

| Metrik | Değer |
|--------|--------|
| Dashboard CSS dosya sayısı | 8 |
| Dashboard sync JS dosya sayısı | 14+ |
| Snapshot poll aralığı (ms) | 3000 |
| Snapshot timeout (ms) | 12000 |
| Bot detay fiyat poll (ms) | 1000 |
| Binance tab wallet poll (ms) | 15000 |
| Binance tab orders poll (ms) | 10000 |
| KPI / DataHub status poll (ms) | 5000 |
| Kullanıcı sohbet modalı poll (ms) | 2500 (modal açıkken; gönderim sonrası 600ms'de bir yenileme) |
| Admin sohbet paneli poll (ms) | 2500 (sohbet seçiliyken; sekme değişince durur) |
| Admin "yazıyor" göstergesi | POST /api/admin/chats/typing (user_id); in-memory thread_id→timestamp, TTL 5s; GET /auth/chat admin_typing döner; kullanıcıda balon animasyonu |
| Finance bots prices tick (ms) | 1500 |
| intervalRegistry visibility skip | Tüm tick'lerde document.visibilityState === 'hidden' → skip |

## Mevcut — Tarayıcı ve Ortam Varsayımları

| Özellik | Varsayım |
|---------|----------|
| ES sürümü | Async/await, Promise, const/let; eski IE desteklenmez |
| Fetch API | apiClient fetch kullanır; polyfill dokümante edilmemiş |
| LocalStorage / SessionStorage | Token, user, last_route, savedTab; zorunlu |
| Visibility API | document.visibilityState, document.hidden; intervalRegistry buna bağlı |
| requestAnimationFrame | Animasyon ve DOM batch için kullanılıyor; fallback yok |
| ResizeObserver | perf_chart_tv ve bazı bileşenlerde; polyfill belirtilmemiş |

## Mevcut — Render Bloklama Özeti

| Kaynak | Bloklama |
|--------|----------|
| 8 CSS link | Her biri render-blocking; sırayla indirilir ve parse edilir |
| 14+ script (sync) | Parse ve execute sırayla; dashboard.js en ağır |
| İlk anlamlı paint | Token kontrolü + CSS'ler bittikten sonra; dashboard'da mainContainer visibility hidden olduğu için içerik paint'i initDashboard + tab restore sonrası |
| Token yoksa | Hemen location.replace login; diğer kaynaklar yüklenmeden yönlendirme |

## Geliştirilebilir — A/B ve Özellik Bayrakları

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Snapshot sıkıştırma A/B | Brotli açık/kapalı; süre ve boyut karşılaştırması | Düşük |
| Poll aralığı ayarı | Kullanıcı veya ortam (mobil/desktop) için 3s / 5s seçimi | Düşük |
| Skeleton varyantı | Shimmer vs static; tercih testi | Düşük |

## Geliştirilebilir — Test ve Canlı Metrik

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Lighthouse CI | Her PR'da dashboard ve bot detay için skor; LCP, TBT hedefi | Orta |
| RUM (Real User Monitoring) | Canlı FCP/LCP toplama; yüzdelik dilimler | Orta |
| Snapshot boyut logu | Backend'de response size log; büyük hesap tespiti | Düşük |
| Slow snapshot uyarı | 5s üstü snapshot süresinde frontend'de uyarı veya fallback UI | Düşük |

## Mevcut — Kritik Yol (Dashboard) Özet

1. HTML parse → head'deki script (token kontrolü; visibility hidden).
2. CSS'ler sırayla indirilir ve uygulanır (8 dosya).
3. Body içeriği parse; dashboardMainContainer visibility hidden.
4. Script'ler sırayla yüklenir (trTime, maintenance, apiClient, errorReporter, intervalRegistry, stores, services, api, components, spot_engine, coinLogo, dashboard).
5. initDashboard çağrılır (muhtemelen DOMContentLoaded veya inline).
6. loadAccountMeta, loadBotsListFast; fetchSnapshot (tek büyük istek).
7. applySnapshotToUI ile DOM güncellenir; tab restore ile mainContainer görünür yapılır.
8. intervalRegistry ile 3s'te bir snapshot tekrarlanır; visibility hidden'da atlanır.

Darboğaz: CSS/JS sayısı ve boyutu; snapshot RTT + sunucu süresi; büyük DOM güncellemesi.

## Mevcut — Bot Detay Kritik Yol Özeti

1. HTML parse; token kontrolü; CSS (theme, design, blink) + inline stiller.
2. Script'ler: apiClient, bot sayfasına özel script blokları; setInterval ile 1s fiyat poll.
3. GET detail + GET events (paralel veya sıralı); DOM doldurulur.
4. Performans sekmesi: GET performance?period=X; grafik için GET perf-chart-state.
5. perf_chart_tv.js: getDataFromDom ile DOM'dan değer parse; TradingView chart mount.
6. Her 1s: GET bots-engine (fiyat, state); document.hidden ise atlanır.
7. visibilitychange: refreshAll() ile tam yenileme.

Darboğaz: detail + events boyutu; 1s poll sıklığı; grafik DOM bağımlılığı.

## Geliştirilebilir — Dokümantasyon ve Bakım

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| UI mimari diyagram | Sayfa → script → endpoint → DOM akışı; bu spec'teki tablolar güncel tutulsun | Düşük |
| Interval envanteri | intervalRegistry.getActive() çıktısı; dokümante interval listesi otomatik güncellensin | Düşük |
| Performans budget | Snapshot < 150 KB, FCP < 3s gibi hedefler; CI'da kontrol | Orta |

## UI Hız ve Optimizasyon Checklist

- [ ] Dashboard: 8 CSS + 14+ JS sync; FCP ölçümü
- [ ] visibility hidden: dashboard root + mainContainer; tab restore
- [ ] intervalRegistry: tüm tick'lerde visibilityState hidden skip
- [ ] Bot detay: setInterval 1s; document.hidden skip
- [ ] Snapshot: 3s poll; 12s timeout; inFlight guard
- [ ] Skeleton: CSS var; tam sayfa skeleton kullanımı sınırlı
- [ ] Coin logolar: lazy loading yok
- [ ] 3G: 200 KB snapshot ≈ 8–16s; timeout 12s riski
- [ ] Tab içerikleri DOM'da; display ile gizli; veri tab'a göre lazy
- [ ] inFlight takılı kalırsa manuel refresh gerekir

## Özet — UI Mevcut vs Geliştirilebilir

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| FCP | CSS/JS sync; visibility hidden; tab restore | Critical CSS inline; JS split; skeleton FCP |
| Polling | Snapshot 3s; intervalRegistry visibility skip; bot 1s setInterval | Bot intervalRegistry; 2–3s backoff; tab bazlı durdurma |
| DOM | Tam liste re-render; RAF yer yer | Virtual scroll; diff; RAF batch |
| Ağ | Snapshot tek büyük; 12s timeout | Sıkıştırma; alan filtre; cache; retry |
| Görsel | Coin logo anında; lazy yok | loading=lazy; placeholder |
| Hata | inFlight takılabilir | inFlight timeout; retry |
| Mobil | Viewport + bottom nav | Network-aware; düşük veri modu |

---

# SECTION E.5 — BACKEND GÖRÜNTÜLEME, OPTİMİZASYON VE HIZ

## Mevcut — Uygulama Yapısı

| Katman | Teknoloji | Dosya / Konum |
|--------|-----------|----------------|
| Framework | FastAPI | app/main.py |
| ORM | SQLAlchemy | app/db/base.py, session.py, models.py |
| Veritabanı | SQLite (varsayılan) / PostgreSQL | DATABASE_URL; WAL mode (SQLite) |
| Auth | Bearer token + session store | app/api/auth.py |
| Middleware | CORS, request_id, request_metrics, error_log, breach, lockdown, WebSocket suppress | main.py sırayla |

## Mevcut — Veritabanı Bağlantı ve Pool

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| pool_size | 10 | Sabit bağlantı sayısı |
| max_overflow | 20 | Ek bağlantı |
| pool_pre_ping | True | Kullanımdan önce bağlantı kontrolü |
| pool_recycle | 3600 | 1 saatte bir bağlantı yenileme |
| DATABASE_ROLE | web / worker | Ortam değişkeni; tek engine (web=worker aynı) |
| WAL | PRAGMA journal_mode=WAL, synchronous=NORMAL | SQLite: eşzamanlı okuma/yazma |
| get_db | SessionLocal(); yield; finally close | Her istekte yeni session; kısa transaction önerilir |

Session: dependency ile her route'a bir Session verilir; request sonunda kapatılır. Uzun süren işlemler pool'u meşgul eder.

## Mevcut — Snapshot Endpoint Kritik Yol

| Adım | İşlem | Süre / Not |
|------|--------|-------------|
| 1 | require_auth, require_account_access, Account query | DB 1 sorgu |
| 2 | asyncio.gather( fetch_prices, fetch_bots_and_account_kpis, fetch_finance_pnl ) | 3 task paralel; her biri SNAPSHOT_TASK_TIMEOUT = 3s; wallet yok (cache-only) |
| 3 | fetch_prices | data_hub.get_all_prices() run_in_executor; DataHub bellek cache |
| 4 | Wallet | _get_snapshot_wallet_cached(account_id, db): son AssetSnapshot; canlı Binance yok |
| 5 | fetch_bots_and_account_kpis | Sync DB: Account, Bot list, her bot için PnlService.calculate_bot_pnl, Trade son işlem, Ledger.get_cycle_ids; N bot = N PnL + N Trade + N Ledger çağrısı (N+1 riski) |
| 6 | fetch_finance_pnl | Sync DB: Account, AssetSnapshot (latest + first), FinancePnlCalculator (realized/unrealized), PnlService.daily_realized |
| 7 | Merge: prices, wallet, bots, pnl, account_kpis; _daily_kpi_ref güncelleme | Bellek |
| 8 | SNAPSHOT_LATENCY log; response dönüş | |

Aynı request'te tek get_db() Session'ı wallet, bots, pnl task'larına paylaştırılıyor; asyncio.gather ile aynı anda kullanım SQLAlchemy Session için thread-safe değil (concurrent access riski).

## Mevcut — Snapshot Görev Zaman Aşımı ve Hata

| Görev | Timeout | Hata çıktısı |
|-------|---------|--------------|
| fetch_prices | 3s | {"_error": "timeout"} veya {"_error": "..."} |
| wallet | — | Cache-only (AssetSnapshot); timeout yok; yoksa data.wallet._error.error_code=WALLET_NOT_READY |
| fetch_bots_and_account_kpis | 3s | {"_error": "timeout"} veya {"_error": "..."} |
| fetch_finance_pnl | 3s | {"_error": "timeout"} veya {"_error": "..."} |

Kısmi yanıt: Bir görev hata verirse diğerleri döner; UI tarafında ilgili blok boş veya _error ile doldurulur.

## Mevcut — Wallet Cache (Binance)

| Öğe | Değer | Konum |
|-----|-------|-------|
| TTL | WALLET_RESPONSE_CACHE_TTL = 2.0 saniye | routes.py |
| In-flight dedupe | _wallet_inflight[account_id] = task | Aynı account_id eşzamanlı istekler tek upstream çağrı paylaşır |
| Cache hit | 200 + önbellek cevabı | Upstream çağrı yok |
| 429 / timeout | 200 + stale cache varsa; yoksa boş/stale | UI'a 429 dönülmez |
| Snapshot | Cache-only: _get_snapshot_wallet_cached (AssetSnapshot); canlı Binance yok | meta.wallet_source=db_snapshot|none; meta.wallet_age_sec |

/api/binance/wallet cache'li; /dashboard/snapshot wallet sadece DB/AssetSnapshot (cache-only). Canlı cüzdan sadece POST /api/home/wallet/refresh.

Wallet sözleşmesi (strip ve varlık tablosu): Tüm wallet kaynakları (snapshot, wallet_live, wallet_cached) total_usd, free_usd, locked_usd (emirlerde kilitli), bot_locked_usd (botlarda kilitli), available_usd ve assets[].free, locked, bot_locked, available içermelidir; UI'da "Kullanılabilir", "Bot kilitli", "Kilitli (emirler)" doğru gösterilsin. Snapshot ve DB cache _enrich_*_with_bot_locked ile zenginleştirilir; wallet/refresh tam _wallet_response döner.

## Mevcut — Fiyat Kaynakları ve Cache

| Kaynak | Kullanım | TTL / Not |
|--------|----------|-----------|
| DataHub | get_all_prices(); get_price(symbol); snapshot fetch_prices | Bellek; PRICE_UPDATE_INTERVAL 1.5s, HUB_CACHE_TTL 1s |
| routes.py _price_cache | /api/price (tek sembol?) | TTL 2s; _PRICE_CACHE_MAX_KEYS ile eviction |
| price_hub | get_price(symbol); routes'ta cached_price | price_hub cache |
| Binance ticker/24hr | get_wallet (POST /api/home/wallet/refresh, /api/binance/wallet) içinde ticker_24h_all | Snapshot'ta yok (wallet cache-only) |
| Binance ticker/price | Fiyat eksik varlıklar için ticker_price_all | Fallback |

DataHub arka planda güncellenir; get_all_prices sync, snapshot'ta run_in_executor ile çağrılır.

## Mevcut — Request Metrics (Middleware)

| Özellik | Değer |
|---------|--------|
| Konum | request_metrics_middleware (main.py); RequestMetrics.record(method, path, status, duration_ms, client_ip, user_agent) |
| Path normalizasyonu | Sayı ve UUID segmentleri /{id} yapılır; route şablonu |
| Depolama | In-memory; _by_route, RingBuffer(latencies), _recent_requests; uygulama yeniden başlayınca sıfırlanır |
| RingBuffer | Son 100 (veya _RING_SIZE) latency; p50, p95 hesaplanır |
| SLOW_REQUEST_MS | 4000 (env: SLOW_REQUEST_MS); 200 OK ama >eşik istek WARN log. Ağır path'ler: /api/finance/trades 15s, /api/admin/accounts 12s, /api/dashboard/snapshot 10s. |
| Throttle | Aynı path için en fazla 2 dakikada bir slow log |
| web.metrics.json | Her 2s RequestMetrics.snapshot_web_metrics() ile .run/web.metrics.json yazılır |
| X-Response-Time | Response header'da yok; sadece RequestMetrics ve log'da süre |

## Mevcut — Middleware Sırası (Yukarıdan Aşağıya Uygulama)

| Sıra | Middleware | Amaç |
|------|------------|------|
| 1 | request_id_middleware | X-Request-Id; server_state.increment_request_count |
| 2 | request_metrics_middleware | Başlangıç zamanı; call_next; süre hesapla; RequestMetrics.record; slow log; error_log/breach |
| 3 | (diğer özel middleware'ler) | error_log persist, breach detection |
| 4 | lockdown_middleware | Lockdown açıksa whitelist dışı 503 |
| 5 | CORSMiddleware | allow_origins=["*"], allow_credentials=True |
| 6 | _WebSocketCloseSuppressMiddleware | WS kapanma log bastırma |

## Mevcut — Ağır Sorgu Noktaları

| Endpoint / Fonksiyon | Sorgu Tipi | N+1 / Not |
|----------------------|------------|-----------|
| fetch_bots_and_account_kpis | Account 1, Bot N, her bot için PnlService.calculate_bot_pnl (Trade, state, PnlSnapshot, Ledger), Trade son 1, User 1 | N bot = çok sayıda DB round-trip |
| PnlService.calculate_bot_pnl | Bot 1, Trade filtresi, PnlSnapshot (monthly), state, cycle_pnls, Ledger | Bot başına birkaç sorgu |
| fetch_finance_pnl | Account 1, AssetSnapshot 2 (latest, first), Bot list, FinancePnlCalculator (realized/unrealized aralıkları), PnlService.daily_realized | Çoklu sorgu |
| GET /api/finance/trades | type_filter=buysell: DB pagination (order_keys + fills sadece sayfa). type_filter=all: start/end yoksa son 90 gün (SLOW_REQUEST önleme); tek istekte en fazla FINANCE_TRADES_ALL_MAX_ROWS (5000) fill; deposit/withdraw merge sonrası sayfalama. | finance_reports.py |
| bots_list (bots_engine) | Bot N; her biri için load_state(db, r.id) | N bot = N load_state sorgusu |
| bots_detail / bots_engine GET | Bot, state, config, grid; ayrıca 24h ticker (Binance veya DataHub) | Monolitik; events ayrı endpoint |

## Mevcut — TTLCache (app/services/cache.py)

| Metod | Açıklama |
|-------|----------|
| get(key) | Süresi dolmuşsa None; yoksa value |
| set(key, value, ttl_seconds) | time.time() + ttl ile saklar |
| clear_prefix(prefix) | Önek ile anahtarları siler |

In-memory dict; uygulama genelinde kullanım yeri (config cache, vb.) modüle göre değişir. Snapshot response cache için kullanılmıyor.

## Mevcut — Cevap Sıkıştırma

| Katman | Durum |
|--------|--------|
| FastAPI / Starlette | Varsayılan GZip middleware ekli değil |
| Uvicorn | --compress gibi flag dokümante edilmemiş; genelde reverse proxy (nginx) sıkıştırır |
| Accept-Encoding | Backend tarafında manuel gzip yanıtı yok |

Büyük JSON (snapshot 50–200 KB) sıkıştırılmadan gidiyor; proxy açıksa proxy'de sıkıştırma yapılabilir.

## Mevcut — Binance Çağrı Sınırlama

| Mekanizma | Konum | Not |
|-----------|-------|-----|
| binance_spot / binance_assets | get_wallet, ticker_24h_all, ticker_price_all | Weight/rate limit guard ayrı modülde (binance_metrics, guard) |
| DataHub | REST loop: price 1–2s, 24h 5s; BULK_REFRESH_MIN_INTERVAL 10s | Per-symbol REST azaltılmış; toplu güncelleme |
| Snapshot wallet | Her snapshot'ta get_wallet + ticker_24h_all | 3s'te bir; çok hesap açıkken her hesap için ayrı çağrı |

## Mevcut — Log ve Gözlemlenebilirlik

| Öğe | Konum | İçerik |
|-----|-------|--------|
| SNAPSHOT_LATENCY | routes.py api_dashboard_snapshot | logger.info("SNAPSHOT_LATENCY ms=... binance_calls=... stale_symbols_count=...") |
| SLOW_REQUEST | main.py request_metrics_middleware | method, path, duration_ms, request_id, ip |
| app.log | RotatingFileHandler 10MB, 5 backup | INFO; TurkeyTimeFormatter |
| web.metrics.json | main.py _web_metrics_writer_loop | request_total, requests_per_min, status_2xx/4xx/5xx, latency_p50_ms, latency_p95_ms, top_paths, top_ips, login_fail, ts |
| RAM probe | RAM_PROBE=1 | logs/ram_snapshots.log; /api/ram-snapshot, /api/debug/ram-snapshot |

## Mevcut — Hata ve Timeout (Backend)

| Yer | Timeout / Davranış |
|-----|---------------------|
| Snapshot görevleri | 3s; timeout → _error; gather diğer sonuçlarla devam eder |
| _fetch_wallet_uncached (binance/wallet) | asyncio.wait_for(task, 12.0) |
| apiClient (frontend) | Snapshot isteği 12s timeout |
| DB | SQLite/PostgreSQL statement_timeout (PG_STATEMENT_TIMEOUT_MS env) opsiyonel |
| 499 | İstemci bağlantıyı kesti; RequestMetrics 499 kaydeder; JSONResponse 499 döner |
| POST /api/spot/order | HTTPException (4xx) re-raise; sadece gerçek sunucu hataları 500 döner (spot_routes.py) |

## Geliştirilebilir — Snapshot Performansı

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Snapshot response cache | account_id + TTL 2–3s; aynı hesap kısa aralıkla tekrar istekte cache'den dön | Yüksek |
| DB session paralel kullanım | Aynı session'ı gather ile paylaşmak yerine her görev için ayrı session (veya run_in_executor ile sync DB işlerini ayrı thread'de çalıştırıp session'ı paylaşmamak) | Yüksek |
| N+1 azaltma (bots/KPI) | Bot listesi + toplu PnL (batch query veya tek sorguda alt sorgular); Ledger/Trade son kayıt batch | Yüksek |
| fetch_bots_and_account_kpis executor | Sync DB işini run_in_executor'a al; event loop bloklanmaz | Orta |
| fetch_finance_pnl executor | Aynı şekilde executor'da çalıştır | Orta |
| Snapshot görev süreleri | 3s yerine 5s (yavaş DB/Binance) veya görev bazlı farklı timeout | Düşük |

## Geliştirilebilir — Veritabanı

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Read replica | Okuma ağır snapshot/bots_list için ayrı read-only bağlantı (PostgreSQL) | Orta |
| Sorgu indeksleri | PnlSnapshot(bot_id, account_id, timestamp); Trade(bot_id, account_id, ts); sık filtre alanları | Yüksek |
| pool_size / max_overflow | Yük testine göre ayarlama; SQLite için aşırı büyük pool gereksiz | Düşük |
| Statement timeout | PG'de statement_timeout; uzun süren sorguyu kesmek | Orta |
| Connection pool ayrımı | Web vs worker için farklı engine (zaten DATABASE_ROLE var; ayrı engine_web/engine_worker kullanımı) | Düşük |

## Geliştirilebilir — Cache

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Snapshot cache | TTLCache veya benzeri; key = f"snapshot:{account_id}"; TTL 2–3s | Yüksek |
| ETag / If-None-Match | Snapshot cevabı için hash; 304 Not Modified | Orta |
| Redis (opsiyonel) | Çok instance varsa paylaşımlı snapshot/wallet cache | Düşük |
| Cache-Control header | GET /dashboard/snapshot için max-age=0, no-store (mevcut davranış); cache eklenirse max-age=2 | Düşük |

## Geliştirilebilir — Cevap ve Ağ

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| GZip/Brotli middleware | FastAPI veya Starlette GZipMiddleware; Accept-Encoding: gzip | Yüksek |
| Field projection | ?fields=prices,wallet,bots ile isteğe bağlı alt küme; daha küçük payload | Orta |
| Chunked / stream | Snapshot için önce prices, sonra wallet, bots (progressive); UI kademeli render | Düşük |
| Response size log | Snapshot ve bots_detail yanıt boyutu loglama; büyük hesap tespiti | Düşük |

## Geliştirilebilir — Metrik ve Header

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| X-Response-Time header | Her yanıtta süre (ms); frontend'de slow request gösterme | Orta |
| X-Snapshot-Latency | Sadece snapshot endpoint'inde; backend süresi | Düşük |
| RequestMetrics kalıcılık | In-memory yerine periyodik dosya/Redis; restart sonrası trend | Düşük |
| APM entegrasyonu | OpenTelemetry veya benzeri; trace, span (DB, Binance, merge) | Düşük |

## Geliştirilebilir — Binance ve Dış Servis

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Snapshot wallet DataHub | Wallet bakiyeleri için Binance her 3s yerine DataHub balance cache (varsa) + periyodik senkron | Orta |
| Ticker 24h tek kaynak | ticker_24h_all yerine DataHub 24h cache; Binance weight tasarrufu | Yüksek (rate limit) |
| Retry / backoff | 429 veya 5xx sonrası exponential backoff; snapshot görevleri için | Orta |
| Circuit breaker | Binance sürekli hata verirse kısa süre snapshot wallet'ı atla; stale göster | Düşük |

## Mevcut — Özet Sayısal Referanslar (Backend)

| Metrik | Değer |
|--------|--------|
| Snapshot görev timeout | 3s |
| Snapshot görev sayısı | 4 (prices, wallet, bots, pnl) |
| Wallet cache TTL (binance/wallet) | 2s |
| Wallet upstream timeout (binance/wallet) | 12s |
| SLOW_REQUEST_MS | 4000 |
| Slow log throttle (aynı path) | 120s |
| Dashboard summary response cache TTL | 20s (DASHBOARD_SUMMARY_CACHE_TTL); wallet refresh sonrası invalidate |
| Günlük cüzdan değişimi (daily_wallet_pnl) | AssetSnapshot ile gün başı referansı: last_before_today (timestamp < turkey_today_start_utc) veya first_today; ref yoksa mevcut bakiye → değişim 0. routes.py dashboard/summary + snapshot. |
| Mevcut Botlar listesi TOPLAM K/Z (current_usd, total_pnl_usd) | Tek sembol DCA: bot detay ile aynı kaynak; state (base_balance, quote_balance) + fiyat (price_hub/pnl_data). routes.py api_dashboard_summary + dashboard_snapshot.fetch_bots_and_account_kpis. Böylece liste ile state paneli aynı değeri gösterir; gecikme/tutarsızlık önlenir. |
| trades_normalized (finance) index | ix_trades_normalized_account_time (account_id, time) — schema_guard |
| DB pool_size | 10 |
| DB max_overflow | 20 |
| RequestMetrics RingBuffer size | 100 |
| web.metrics.json yazma aralığı | 2s |

## Mevcut — DataHub get_all_prices Akışı

| Adım | İşlem |
|------|--------|
| 1 | data_hub.get_all_prices() sync; WebSocket verisi varsa _mini_ws + REST fallback |
| 2 | REST: Binance ticker/24hr veya toplu fiyat; BULK_REFRESH_MIN_INTERVAL 10s |
| 3 | Snapshot fetch_prices: loop.run_in_executor(None, data_hub.get_all_prices); 3s timeout |
| 4 | Çıktı: symbol -> {price, change24h, volume24h, ...}; snapshot merge'de prices olarak döner |

DataHub arka plan güncellemesi ayrı; get_all_prices anlık bellek durumunu döner. Snapshot her 3s'te bir bu veriyi ister.

## Mevcut — Bot Detay (bots_engine) Kritik Yol

| Endpoint | Ana işlemler |
|----------|---------------|
| GET /api/bots-engine/{id} | get_account_or_403; Bot query; load_state(db, id); grid view; config; current_price (DataHub veya _get_price_from_datahub); TRDCA ise balances + _fetch_prices_parallel; daily_pnl, cycle_pnl_last |
| GET /api/bots-engine/{id}/events | list_events(db, bot_id, limit); offset; meta_json |
| GET /api/bots-engine/{id}/performance | PnlService, Ledger, events, bot_perf_chart_state; period filtresi; chart_series, pair_series, TRDCA breakdown |
| GET /api/bots-engine/{id}/perf-chart-state | bot_perf_chart_state tablosu; JSON baseline + samples |

Her bot detay sayfası 1s'te bir GET bots-engine/{id} çağırır; DB + DataHub/price. Çok kullanıcı/bot açıkken yük artar.

## Mevcut — PnlService.calculate_bot_pnl Sorgu Özeti

| Sorgu | Koşul |
|-------|--------|
| Bot 1 | bot_id, account_id |
| Trade (filter) | bot_id, account_id; order_by ts |
| PnlSnapshot (monthly) | bot_id, account_id; son ay |
| state (load_state) | bot_engine_state tablosu |
| Ledger (cycle_ids) | cycle_ledger veya ilgili tablo |
| account_daily_realized_cache | Silinen botlar için günlük gerçekleşen |

Bot başına en az 4–6 round-trip; fetch_bots_and_account_kpis içinde N bot için N kez çağrılır.

## Mevcut — Error Log ve Breach

| Özellik | Tetikleyici | Davranış |
|---------|-------------|----------|
| error_log (DB) | 404 veya 5xx yanıt | request_metrics_middleware içinde; path, status, user_id, account_id, request_id, ip loglanır |
| 499 | İstemci koptu | error_log'a yazılmaz (cascade önleme) |
| Breach detection | 2xx yanıt; yetkisiz erişim şüphesi | Opsiyonel uyarı / hesap askıya / lockdown |

## Mevcut — Session ve Auth Yükü

| İşlem | Sorgu / Çağrı |
|-------|----------------|
| require_auth | Token decode; session store lookup (bellek veya DB) |
| get_account_or_403 | Account query veya cache |
| require_account_access | account_id eşleşmesi |

Her korumalı istekte en az bir auth kontrolü; session store hızlı olmalı.

## Geliştirilebilir — Bots Engine

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| bots_list load_state batch | N bot için N load_state yerine tek sorguda tüm state'ler (veya joinedload) | Yüksek |
| detail 24h tek kaynak | Binance ticker/24hr yerine DataHub 24h cache | Yüksek |
| performance endpoint cache | period + bot_id TTL 5–10s | Orta |
| events sayfalama | limit=500 sabit; cursor/offset ile sayfalama; daha küçük ilk yanıt | Orta |

## Geliştirilebilir — Gözlemlenebilirlik

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Structured log | JSON log; ms, route, account_id, bot_id alanları; log agregasyonu için | Orta |
| Snapshot süre dağılımı | Her görev (prices, wallet, bots, pnl) bitiş süresi; hangi görev yavaş belli olsun | Orta |
| DB query log | DEBUG seviyesinde SQL + süre; production'da kapalı | Düşük |
| Health endpoint | /api/health: DB ping, DataHub durumu, Binance erişilebilirlik | Düşük |

## Mevcut — Kritik Yol Özeti (Snapshot)

1. Request → request_id → request_metrics (start).
2. require_auth; get_db → Session açılır.
3. Account query; asyncio.gather( prices, wallet, bots, pnl ) — prices: executor'da get_all_prices; wallet: Binance get_wallet + ticker_24h; bots: sync DB (N PnL); pnl: sync DB.
4. Merge; account_kpis; _daily_kpi_ref.
5. SNAPSHOT_LATENCY log; response; request_metrics (end).
6. get_db finally → session.close().

Darboğaz: En yavaş görev (genelde wallet veya bots); DB N+1; aynı session'ın paralel kullanımı.

## Geliştirilebilir — Concurrency ve Threading

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Sync DB executor | fetch_bots_and_account_kpis, fetch_finance_pnl → run_in_executor(ThreadPoolExecutor); event loop bloklanmaz | Yüksek |
| Session per task | Her gather görevi kendi get_db benzeri session'ı (dependency'den değil, manuel SessionLocal() ile); dikkat: connection pool | Orta |
| Async DB driver | SQLAlchemy async + asyncio; FastAPI ile uyumlu | Düşük (büyük refactor) |

## Geliştirilebilir — Güvenlik ve Limit

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Rate limit per account | Snapshot / bots-engine aşırı istekte 429 | Orta |
| Max response size | Snapshot'ta bot/event sayısı üst sınırı; çok büyük yanıt kesilsin | Düşük |
| Timeout cascade | Görev timeout'ta diğer görevler iptal edilmez; devam eder (mevcut); isteğe bağlı cancel | Düşük |

## Backend Hız ve Optimizasyon Checklist

- [ ] Snapshot: asyncio.gather ile 4 görev; 3s timeout; kısmi yanıt
- [ ] Aynı db session wallet/bots/pnl ile paralel kullanılıyor; concurrent access riski
- [ ] fetch_bots_and_account_kpis: N bot için N×PnL/Trade/Ledger sorgusu
- [ ] Wallet: /api/binance/wallet cache 2s + in-flight; snapshot cache'siz
- [ ] Response compression: backend'de yok; proxy'de olabilir
- [ ] RequestMetrics: in-memory; p50/p95; slow >4s WARN log
- [ ] X-Response-Time header yok
- [ ] DataHub get_all_prices snapshot'ta executor'da; wallet Binance her 3s
- [ ] PnlService.calculate_bot_pnl bot başına çoklu sorgu

## Mevcut — FinancePnlCalculator Sorguları

| Metod | Sorgu / İşlem |
|-------|----------------|
| calculate_realized_pnl(account_id, start, end) | Trade tablosu filtresi; toplam kar, fee, trades_count |
| calculate_unrealized_pnl(account_id) | Güncel bakiye vs maliyet; AssetSnapshot veya benzeri |
| fetch_finance_pnl içinde | AssetSnapshot latest + first; Bot list config; calculator çağrıları; PnlService.daily_realized |

Finance snapshot görevi bu hesaplamalarla DB'ye birkaç round-trip yapar.

## Mevcut — SQLite WAL ve Checkpoint

| Özellik | Değer |
|---------|--------|
| journal_mode | WAL |
| synchronous | NORMAL |
| checkpoint | Otomatik; WAL dosyası büyürse checkpoint ile main DB'ye yansır |
| Okuma / yazma | Aynı anda okuyucu ve bir yazar; worker yazarken web okuyabilir |

Çok yoğun yazma durumunda WAL büyüyebilir; periyodik checkpoint veya busy_timeout dokümante edilmemiş.

## Mevcut — Uvicorn ve Process Model

| Özellik | Varsayım |
|---------|----------|
| Worker | Tek process (veya --workers N); env'e bağlı |
| Async | FastAPI async route'lar; sync route'lar thread pool'da (Starlette) |
| Blocking | Sync DB çağrıları event loop'u bloklar (gather içinde sync fonksiyon yok; fetch_bots/fetch_finance_pnl async def ama içleri sync DB) |

fetch_bots_and_account_kpis ve fetch_finance_pnl async def olup içinde sync db.query çağrıları var; bu yüzden gather içinde çalışırken event loop bloklanır (aynı anda sadece biri ilerler, diğerleri bekler değil — asyncio.gather hepsini "paralel" başlatır ama sync kısım tek thread'de sırayla çalışır). Detay: Python'da async def içinde sync kod çalıştığında o coroutine event loop'u bloklar; yani bots ve pnl aslında birbirini bekletir.

## Geliştirilebilir — Snapshot Görev Bağımsızlığı

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| prices tamamen async | Zaten executor'da; sadece DataHub lock/contention varsa hafiflet | Düşük |
| wallet ayrı session | Wallet için ayrı SessionLocal() (veya dependency'den değil route içinde ikinci session); paylaşılan session riski kalkar | Orta |
| bots + pnl tek görev | İki sync görevi tek run_in_executor'da sıralı çalıştır; tek session kullan; event loop bloklanmaz | Yüksek |

## Mevcut — Response Header'lar (Örnek)

| Header | Kullanım |
|--------|----------|
| X-Request-Id | Tüm yanıtlarda; request_id_middleware |
| Cache-Control | Login/chat vb. bazı endpoint'lerde no-store, no-cache |
| Pragma | no-cache (bazı route'lar) |
| X-Response-Time | Yok |
| Content-Encoding | Backend gzip eklemediği için yok (proxy ekleyebilir) |

## Mevcut — Ağır Endpoint Listesi (Tahmini)

| Endpoint | Neden ağır |
|----------|------------|
| GET /api/dashboard/snapshot | 3 paralel görev (prices, bots, pnl); wallet cache-only (AssetSnapshot); Binance yok |
| GET /api/bots-engine/{id} | load_state, grid, DataHub/price, TRDCA ise balances + fiyatlar |
| GET /api/bots-engine/{id}/events | list_events limit=500; büyük JSON |
| GET /api/bots-engine/{id}/performance | PnlService, Ledger, events, chart state; TRDCA breakdown |
| GET /api/binance/wallet | Cache miss: get_wallet + ticker_24h_all; cache hit: anında |
| POST /api/bots/... (create/start/stop) | DB + orchestrator + state; kısa süreli bloklama |

## Mevcut — Ledger ve Cycle Sorguları

| Kullanım | Sorgu |
|----------|--------|
| get_cycle_ids | cycle_ledger veya benzeri tablo; bot_id, account_id |
| fetch_bots_and_account_kpis | Her bot için Ledger.get_cycle_ids(db, bot.id, account_id) |
| PnlService | cycle_pnls state'ten; CYCLE_END events fallback |

Cycle sayısı bot başına bir sorgu; N bot = N cycle sorgusu (batch yapılabilir).

## Geliştirilebilir — Snapshot Kısmi Yanıt Stratejisi

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Öncelikli prices | İlk 500ms'te sadece prices dön; sonra wallet/bots/pnl ekle (stream/chunked) | Düşük |
| Fallback snapshot | Bots timeout olursa önceki başarılı bots listesini cache'den ekle | Düşük |
| Timeout aşamalı | prices 2s, wallet 5s, bots 5s, pnl 3s gibi görev bazlı farklı timeout | Düşük |

## Mevcut — Test Hesap (Snapshot Wallet)

| Koşul | Davranış |
|-------|----------|
| is_test_account(account_id) | Binance çağrısı yok; DataHub get_all_prices + virtual_wallet get_bot_locked_balances_for_account; 10.000 USDT paper bakiye |
| keys_configured | True döner; UI'da Binance uyarısı kalkar |

Test hesapta snapshot wallet hızlı; sadece DataHub + DB.

## Geliştirilebilir — Veritabanı İndeks Özeti

| Tablo | Önerilen indeks (örnek) | Amaç |
|-------|-------------------------|------|
| bot_engine_state | (bot_id) UNIQUE zaten; account_id | Filtre |
| Trade | (bot_id, account_id, ts DESC) | PnL son işlem; period filtreleri |
| PnlSnapshot | (bot_id, account_id, timestamp) | Aylık snapshot sorgusu |
| bot_engine_events | (bot_id, created_at DESC) | list_events sayfalama |
| AssetSnapshot | (account_id, timestamp) | fetch_finance_pnl latest/first |

Mevcut indeksler schema'da kontrol edilmeli; yukarıdakiler öneri.

## Backend Özet Sayısal (Tekrar)

| Metrik | Değer |
|--------|--------|
| Snapshot görev timeout | 3.0 s |
| Wallet cache TTL | 2 s |
| DB pool_size / max_overflow | 10 / 20 |
| SLOW_REQUEST_MS | 4000 |
| RequestMetrics RingBuffer | 100 |
| Snapshot görev sayısı | 4 (prices, wallet, bots, pnl) |

## Mevcut — Config ve Invalidate Cache

| Öğe | Kullanım |
|-----|----------|
| invalidate_config_cache | botengine/orchestrator; config değişince cache temizlenir |
| Config cache | Bot config okumada tekrarlı DB azaltma; TTL/scope dokümante edilmeli |
| TTLCache (services/cache.py) | Genel TTL cache; config veya başka key'ler için kullanılabilir |

## Geliştirilebilir — Snapshot Merge Maliyeti

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Merge süresi log | Merge öncesi/sonrası time.perf_counter(); büyük hesapta merge yavaş olabilir | Düşük |
| Shallow copy | Büyük dict'lerde gereksiz deep copy yok; referans ile birleştirme | Düşük |
| JSON serialize | FastAPI JSONResponse; orjson kullanımı (daha hızlı serialize) | Orta |

## Özet — Backend Mevcut vs Geliştirilebilir

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| Snapshot | 4 görev paralel; 3s timeout; kısmi yanıt | Response cache 2–3s; ayrı session/executor; N+1 azaltma |
| DB | Tek engine; pool 10+20; WAL (SQLite) | İndeksler; statement timeout; read replica (PG) |
| Cache | Wallet 2s; DataHub bellek; _price_cache | Snapshot TTL cache; ETag; Redis (opsiyonel) |
| Compression | Yok | GZip/Brotli middleware |
| Metrik | RequestMetrics; SNAPSHOT_LATENCY log; web.metrics.json | X-Response-Time; APM; kalıcı metrik |
| Binance | Her snapshot'ta wallet + ticker_24h | DataHub 24h; retry/backoff; circuit breaker |
| Concurrency | Sync DB gather içinde; event loop bloklama | run_in_executor; session per task veya bots+pnl tek executor |

---

# SECTION E.6 — BOT ENGINE GÖRÜNTÜLEME, OPTİMİZASYON VE HIZ

## Mevcut — Bot Engine Mimarisi Özeti

| Katman | Dosya / Modül | Rol |
|--------|----------------|-----|
| API | app/api/bots_engine.py | REST: list, detail, start, stop, events, performance, perf-chart-state; auth + get_account_or_403 |
| Orchestrator | app/botengine/orchestrator.py | Per-bot asyncio task (_bot_loop); start_bot, stop_bot, ensure_running_bots, delete_bot_fully; config cache; symbol lock |
| Worker | app/botengine/worker_main.py | worker_loop: fetch_pending_commands, process_command (START/STOP); ensure_running_bots; perf_chart_sample; engine.metrics.json |
| State | app/botengine/state_store.py | load_state, save_state (bot_engine_state); append_event, list_events (bot_engine_events); ensure_state_row |
| Execution | app/botengine/execution.py | run_actions: place order, fill apply, cycle reset; idempotency; _write_fill_snapshot_to_state |
| Strategies | app/botengine/strategies/ | dca_grid_trailing, multi_asset_rebalance, trdca_pro; registry get_strategy_safe |
| Cycle Ledger | app/botengine/cycle_ledger.py | build_cycle_ledger_empty, cycle_ledger_add_fill, breakeven_price, trigger_price; cycle_ledger_from_state |
| Virtual Wallet | app/botengine/virtual_wallet.py | get_virtual_wallet, ensure_virtual_wallet, sync_virtual_wallet_from_state; get_bot_locked_balances_for_account |
| Locks | app/botengine/locks.py | try_acquire_symbol_lock, release_symbol_lock; symbol_locks tablosu; lease TTL 60s |
| Risk | app/botengine/risk.py | acquire_bot_lock (asyncio.Lock per bot); check_idempotency (action_key TTL 5s); guard_min_notional |
| Adapter | app/botengine/adapters/binance_adapter.py | get_account_balances, get_price, get_symbol_filters, place_market_buy/sell, cancel_order, get_open_orders |
| Models | app/botengine/models.py | DcaGridTrailingConfig, TrdcaProConfig, MultiAssetRebalanceConfig; config_from_ui_payload; build_state_skeleton |
| Grid View | app/botengine/grid_view.py | compute_grid_profit_view, compute_trdca_grid_view; UI grid/kar görünümü |

## Mevcut — _bot_loop Kritik Yol (Tek Sembol / DCA Grid)

| Adım | İşlem | DB / Ağ |
|------|--------|----------|
| 1 | Bot row, status running/paused_error; config parse; strategy_id (multi / trdca / dca) | DB: Bot 1 |
| 2 | load_state(db, bot_id) | DB: bot_engine_state 1 |
| 3 | Config cache (_config_cache[bot_id]) veya config_from_ui_payload | Bellek |
| 4 | get_account_keys(account_id, db); paper_mode (User + is_test_account_username) | DB: Account/User; Binance keys |
| 5 | BinanceAdapter(account_id, keys, paper_mode) | — |
| 6 | next_wake: tick_interval_ms/1000 (dca) veya interval_sec (multi) | Config |
| 7 | Fiyat: adapter.get_price(symbol) — DataHub only | DataHub bellek |
| 8 | ensure_virtual_wallet; get_virtual_wallet(db, bot_id, symbol) | DB: bot_virtual_wallet |
| 9 | state["base_balance"], state["quote_balance"] = vb, vq | — |
| 10 | strategy.tick(state, cfg, price, base_balance, quote_balance) → actions, next_wake | CPU |
| 11 | try_acquire_symbol_lock(db, account_id, symbol, bot_id) | DB: symbol_locks UPDATE/INSERT |
| 12 | run_actions(bot_id, account_id, actions, state, cfg, adapter, db) | DB + Binance; acquire_bot_lock |
| 13 | append_event ORDER_FILLED; release_symbol_lock | DB: bot_engine_events; symbol_locks |
| 14 | save_state(db, bot_id, account_id, state) | DB: bot_engine_state UPSERT |
| 15 | sync_virtual_wallet_from_state(db, bot_id, account_id, symbol, base, quote) | DB: bot_virtual_wallet |
| 16 | daily_ref_date != today → daily_ref_usd, save_state | DB |
| 17 | db.close(); await asyncio.sleep(max(0.5, next_wake)) | — |

Her döngüde en az: Bot 1, load_state 1, get_virtual_wallet 1, lock 1–2, run_actions (N order), append_event N, save_state 1–2, sync_virtual_wallet 1. Fiyat yoksa PRICE_STALE_OR_MISSING; next_wake sonrası devam.

## Mevcut — _bot_loop TRDCA Dalı

| Adım | İşlem |
|------|--------|
| 1 | next_wake = tick_interval_ms/1000 (varsayılan 1s) |
| 2 | snapshot = await _build_trdca_snapshot(adapter, state, cfg) |
| 2a | _build_trdca_snapshot: ts, balances_free (virtual veya adapter.get_account_balances), prices_last (adapter.get_price per asset), filters (get_symbol_filters per sym), open_orders (get_open_orders), fills = state._pending_fills |
| 3 | next_state, decision = trdca_strategy_tick(snapshot, state, cfg) |
| 4 | state.update(next_state); dec_type = decision.type (SAFE_STOP, RESUME_PENDING, ACTIONS, NOOP) |
| 5 | ACTIONS: legs → trdca_actions; try_acquire_symbol_lock(MULTI); run_actions(trdca_actions); append_event ORDER_FILLED; virtual_balances güncelle (paper); release_symbol_lock |
| 6 | save_state; await asyncio.sleep(max(0.5, next_wake)) |

TRDCA her tick'te snapshot (balances, prices, filters, open_order) + strategy_tick; çok varlıklı olduğunda get_price ve get_symbol_filters sayısı artar.

## Mevcut — load_state / save_state

| Fonksiyon | Sorgu / İşlem |
|-----------|----------------|
| load_state(db, bot_id) | SELECT state_json, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at FROM bot_engine_state WHERE bot_id=:bid; json.loads(state_json); state_version, initial_allocation_done vb. |
| save_state(db, bot_id, account_id, state) | state_version += 1; _state_to_json_serializable; json.dumps; INSERT ... ON CONFLICT(bot_id) DO UPDATE SET state_json, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at; 2× commit; SELECT verify |

save_state her tick sonunda çağrılır; büyük state_json (grid, cycle_ledger, cycle_pnls) yazma maliyeti. İki commit (upsert + updated_at) mevcut.

## Mevcut — append_event ve list_events

| Öğe | Değer |
|-----|--------|
| Logged event types | ERROR, SKIP_REASON, ORDER_FILLED, SLIPPAGE_WARN, LOCK_BUSY, INFO, BOT_ACTION, CYCLE_END |
| Filtre | TICK ve _LOGGED_EVENT_TYPES dışı atlanır; SKIP_REASON içinde "IDEMPOTENT_LOCK" atlanır |
| append_event | INSERT bot_engine_events (bot_id, account_id, ts, event_type, message, meta_json); commit |
| list_events(db, bot_id, limit, after_id) | SELECT id, ts, event_type, message, meta_json ORDER BY id DESC LIMIT; after_id varsa id > :aid |

API events endpoint limit=500; büyük botlarda 500 event = büyük JSON.

## Mevcut — run_actions Akışı (Özet)

| Adım | İşlem |
|------|--------|
| 1 | acquire_bot_lock(bot_id) — asyncio.Lock; aynı bot aynı anda tek action batch |
| 2 | Her action: type=="place"; reason (initial_allocation, trail_buy_grid, vb.); action_key = reason_gridIndex_clientOrderId |
| 3 | initial_allocation: initial_allocation_done ise skip; _sync_initial_done_from_db; check_idempotency → skip + append_event SKIP_REASON |
| 4 | check_idempotency(bot_id, key): (bot_id, action_key) TTL 5s (initial 2s); duplicate ise skip |
| 5 | guard_min_notional(notional_usd, min_notional); check_virtual_budget (DCA) veya bakiye kontrolü |
| 6 | adapter.place_market_buy / place_market_sell (Binance API veya paper simulate) |
| 7 | Fill: apply_fill_to_state (state güncelle); cycle_ledger_add_fill; cycle_reset_after_fill gerekirse; Ledger.record_cycle_end; state cycle_pnls append; _write_fill_snapshot_to_state (opsiyonel); update_virtual_after_fill |
| 8 | save_state; append_event ORDER_FILLED |
| 9 | 401 Unauthorized: throttle log 10 dk; append_event ERROR |

run_actions sıralı; her action için lock, idempotency, adapter çağrı, state update, DB save/event.

## Mevcut — Cycle Ledger ve PnL

| Öğe | Açıklama |
|-----|----------|
| CYCLE_FILL_REASONS | trail_buy_grid, trail_sell_grid, trail_reentry_buy, trail_profit_sell |
| build_cycle_ledger_empty | cycle_id, symbol, fills=[], buy/sell totals, realized_pnl_quote |
| cycle_ledger_add_fill | fill append; buy/sell totals; _cycle_ledger_recompute → matched_qty, realized_pnl_quote; _recompute_dual_pnl → inventory_coin_adv_qty, cash_pnl_usdt |
| cycle_ledger_breakeven_price | avg_cost * (1+buy_fee_rate)/(1-sell_fee_rate) |
| cycle_ledger_trigger_price | breakeven * (1+min_net_profit_rate) |
| cycle_ledger_from_state | state.cycle_ledger_current veya build_cycle_ledger_empty |
| get_cycle_type_and_base_delta | close_reason trail_profit_sell → LONG_SCALP; trail_reentry_buy → INVENTORY_REBALANCE, base_delta |

**Dual PnL (Inventory vs Cash):** Tek USDT metrik yanıltıcı olabildiği için iki ayrı ledger tutulur. (A) **InventoryPnL**: trail_sell_grid (SELL) + trail_reentry_buy (BUY) → FIFO eşleşme; metrik: **inventory_coin_adv_qty** (base qty) = (sell_proceeds_net / buy_price) - qty_sold; inventory_fees_usdt ayrı. (B) **CashPnL**: trail_buy_grid (BUY) + trail_profit_sell (SELL) → FIFO eşleşme; metrik: **cash_pnl_usdt** = gross - fee_alloc (USDT). Cycle kapanışında pnl_primary_mode: close_reason=trail_profit_sell → CASH_USDT_V1 (Cash öne çıkar); trail_reentry_buy → INVENTORY_QTY_V1 (Envanter öne çıkar). cycle_entry ve API cycle_summary: inventory_coin_adv_qty, inventory_fees_usdt, cash_pnl_usdt, cash_fees_usdt, pnl_primary_mode. UI (Bot tur işlemleri): Envanter K/Z (coin) ve Nakit K/Z (USDT) ayrı satırlarda gösterilir.

Ledger bellekte state içinde; fill sonrası cycle_reset_after_fill ile yeni cycle; Ledger.record_cycle_end (app/bot/ledger) DB'ye yansır.

## Mevcut — Virtual Wallet

| Fonksiyon | Sorgu / Amaç |
|-----------|--------------|
| get_virtual_wallet(db, bot_id, symbol) | SELECT virtual_base, virtual_quote FROM bot_virtual_wallet WHERE bot_id, symbol |
| ensure_virtual_wallet(db, bot_id, account_id, symbol, initial_quote_usdt) | INSERT IF NOT EXISTS (virtual_quote=initial_quote_usdt, virtual_base=0) |
| sync_virtual_wallet_from_state(db, bot_id, account_id, symbol, base, quote) | UPDATE bot_virtual_wallet SET virtual_base, virtual_quote WHERE bot_id, symbol |
| get_bot_locked_balances_for_account(db, account_id) | SELECT symbol, virtual_base, virtual_quote FROM bot_virtual_wallet WHERE account_id; toplam per asset. Tablo boş/0 ise fallback: account'ın running botlarının bot_engine_state (base_balance, quote_balance) ile hesaplanır (UI "Bot kilitli" doğru görünsün). |
| check_virtual_budget | quote_balance >= required; epsilon karşılaştırma |
| update_virtual_after_fill | Fill sonrası base/quote güncelle |

Her tick: get_virtual_wallet okuma; save_state sonrası sync_virtual_wallet_from_state yazma.

## Mevcut — Symbol Lock (symbol_locks)

| İşlem | SQL / Davranış |
|-------|----------------|
| try_acquire_symbol_lock | UPDATE symbol_locks SET owner_bot_id, lease_until WHERE account_id, symbol AND (lease_until < now OR owner_bot_id = bot_id); rowcount>0 → True; else SELECT 1; INSERT if not exists; UNIQUE conflict → False |
| release_symbol_lock | UPDATE symbol_locks SET owner_bot_id=0, lease_until=now WHERE account_id, symbol, owner_bot_id=bot_id |
| Lease TTL | DEFAULT_LEASE_TTL_SEC = 10 (v5); heartbeat 3s |

Aynı (account_id, symbol) için aynı anda tek bot işlem yapabilir; diğer bot LOCK_BUSY event alır.

## Mevcut — Worker Loop

| Adım | Süre / Değer |
|------|--------------|
| command_poll_interval | 1.0 s |
| fetch_pending_commands(db, limit=50) | SELECT FROM bot_engine_commands WHERE status='PENDING' ORDER BY id LIMIT 50 |
| mark_command_processing(cmd_id) | UPDATE SET status='PROCESSING', processed_at WHERE id AND status='PENDING'; rowcount>0 → claimed |
| process_command(cmd) | assert_bot_belongs_to_account; START → start_bot; STOP → stop_bot; mark_command_done |
| ensure_running_bots(db) | Her 10× loop_count; Bot.status='running' olanlar için _tasks'da yoksa _bot_loop task başlat |
| perf_sample_interval | 60 (loop_count % 60 == 0); append_perf_chart_sample her running bot |
| engine.metrics.json | Her 2 iteration; active_bots, last_tick_ts, tick_rate_10s, pending_jobs, ts |

Worker tek process; komutlar sırayla işlenir; ensure_running_bots ile eksik bot loop'ları başlatılır.

## Mevcut — start_bot / stop_bot

| Adım | İşlem |
|------|--------|
| start_bot(bot_id, db) | Bot row; status='running'; started_at=now; db.commit(); seed_perf_chart_state_on_bot_start(db, bot_id); _tasks'da yoksa asyncio.create_task(_bot_loop(bot_id)) |
| stop_bot(bot_id, db) | _stop_requested.add(bot_id); Bot status='stopped'; db.commit(); task.cancel(); task await (CancelledError); _stop_requested.discard |
| ensure_running_bots(db) | Bot.query status='running'; her biri için bot_id not in _tasks → create_task(_bot_loop(bot_id)) |

Config değişikliği sonrası invalidate_config_cache; bir sonraki tick'te config DB'den tekrar okunmaz (cache'den); update-config sonrası cache invalidation gerekir.

## Mevcut — Config Cache

| Öğe | Değer |
|-----|--------|
| _config_cache | Dict[bot_id, DcaGridTrailingConfig | TrdcaProConfig | MultiAssetRebalanceConfig] |
| Okuma | _config_cache.get(bot_id) or config_from_ui_payload(raw) / config_trdca_pro_from_payload(raw); sonra _config_cache[bot_id] = cfg |
| invalidate_config_cache(bot_id) | _config_cache.pop(bot_id, None) |
| Kullanım | orchestrator _bot_loop içinde; update-config API çağrısı sonrası invalidate edilmeli |

## Mevcut — Strategy Tick (DCA Grid) Maliyet

| Bileşen | İşlem |
|---------|--------|
| tick_dca_grid_trailing | state, cfg, price, base_balance, quote_balance; grid seviyeleri, trailing, reentry, profit exit hesaplama; actions listesi (place buy/sell) |
| _ensure_sell_buy_lists | state içinde sell_grids_*, buy_grids_* listeleri |
| Hesaplama | Ortalama fiyatlar, trigger fiyatları, miktar (grid_index, reentry, profit_exit); cycle_ledger breakeven/trigger |

CPU bound; çok grid noktası varsa hesaplama artar; ağ/DB tick içinde değil strategy.tick içinde.

## Mevcut — Binance Adapter Çağrıları (Tick Başına)

| Strateji | Çağrı |
|----------|--------|
| Tek sembol DCA | get_price(symbol) 1 (DataHub); place_market_buy/sell action sayısı kadar |
| TRDCA | get_account_balances 1; get_price per asset; get_symbol_filters per symbol; get_open_orders 1; place (legs sayısı) |
| Multi-asset | get_price yok (price=1.0); strategy kendi fiyatlarını kullanıyorsa ayrı |

Adapter.get_price DataHub'dan; Binance REST değil. Place order gerçek Binance API (veya paper simulate).

## Mevcut — API bots_engine Endpoint Özeti

| Endpoint | Ana işlemler |
|----------|---------------|
| GET "" (list) | get_account_or_403; Bot.filter(account_id); her bot load_state(db, r.id); response bots list |
| GET /{id} (detail) | Bot, load_state; grid_view compute_grid_profit_view veya compute_trdca_grid_view; current_price DataHub; TRDCA: balances + _fetch_prices_parallel; daily_pnl, cycle_pnl_last |
| GET /{id}/events | list_events(db, bot_id, limit, after_id) |
| GET /{id}/performance | PnlService, Ledger, events, bot_perf_chart_state; period; chart_series, pair_series |
| GET/PUT/DELETE /{id}/perf-chart-state | bot_perf_chart_state tablosu |
| POST start/stop | Command INSERT PENDING; worker process_command ile start_bot/stop_bot |

Detail endpoint: load_state, grid view, fiyat, TRDCA ise N asset fiyat; her 1s frontend'den çağrılıyor.

## Mevcut — Idempotency ve Bot Lock

| Mekanizma | TTL / Davranış |
|-----------|----------------|
| _action_keys (bot_id, action_key) | 5s (normal); 2s (initial_allocation); aynı key 5s içinde tekrar → skip |
| acquire_bot_lock(bot_id) | asyncio.Lock per bot; run_actions başında acquire, tüm actions bitene kadar hold |
| Prune | prune_ttl = max(ttl*2, 10); eski key'ler silinir |

Çift emir (double place) önlenir; aynı grid_index aynı anda iki kez gönderilmez.

## Geliştirilebilir — Bot Loop ve DB

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| save_state tek commit | Şu an 2 commit (upsert + updated_at); tek transaction'a indir | Orta |
| save_state batch | Çok sık save_state yerine dirty flag; N tick'te bir save (veri kaybı riski artar; dikkatli) | Düşük |
| load_state cache | Aynı tick içinde tekrar load_state çağrısı yok; executor/worker ayrı process'te cache paylaşılamaz | Düşük |
| state_json sıkıştırma | Büyük state için gzip/base64 (SQLite BLOB); okuma/yazma maliyeti | Düşük |
| Index bot_engine_state | bot_id UNIQUE zaten; updated_at index (cleanup eski state için) | Düşük |

## Geliştirilebilir — Event ve Log

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| list_events sayfalama | limit=500 sabit; cursor/offset; ilk yükleme 100; "daha fazla" ile devam | Orta |
| append_event batch | Tick başına birden fazla event (ORDER_FILLED N); tek INSERT batch (bulk insert) | Orta |
| Event retention | Eski event'leri arşivle veya sil (tablo büyümesi); bot_engine_events partition/cleanup | Düşük |
| _LOGGED_EVENT_TYPES | Gürültü azaltma iyi; isteğe bağlı DEBUG modda TICK log | Düşük |

## Geliştirilebilir — Execution ve Adapter

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| run_actions paralel leg | TRDCA çok bacaklı emir; paralel place (Binance rate limit dahilinde) | Orta |
| 401 retry | 401 sonrası bir kez key refresh veya token kontrolü; sonra pause | Düşük |
| Slippage guard | max_slippage_pct config var; fill price kontrolü execution'da sıkı kullanım | Orta |
| Timeout per order | place_market_buy/sell timeout; uzun süren istekte cancel/retry politikası | Düşük |

## Geliştirilebilir — Strategy ve Tick

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| next_wake dinamik | Yük yüksekse tick_interval artır (backpressure); düşükse daha sık | Düşük |
| Grid hesaplama cache | Aynı price/cfg için grid seviyeleri değişmez; kısmi cache (config version) | Düşük |
| TRDCA snapshot süresi | _build_trdca_snapshot içinde get_price N, get_symbol_filters N; toplu fiyat tek çağrı (DataHub get_all_prices) | Yüksek |
| Strategy tick süresi log | elapsed_ms zaten var (orchestrator'da t0); log veya metrik olarak kaydet | Düşük |

## Geliştirilebilir — Lock ve Concurrency

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| symbol lock lease yenileme | Uzun süren run_actions'ta lease_until dolabilir; ara yenileme (heartbeat) | Düşük |
| Lock timeout | try_acquire bekleme yok; hemen False. Kuyruk veya kısa bekleme (örn. 2s) | Düşük |
| _bot_locks temizlik | Bot silindiğinde _bot_locks.pop(bot_id, None) (bellek sızıntısı önleme) | Düşük |

## Geliştirilebilir — Worker ve Komut

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Komut batch | Aynı döngüde 50 komut; hepsi işlenir; çok komut gelirse gecikme. Öncelik kuyruğu (START/STOP) | Düşük |
| ensure_running_bots sıklığı | 10× loop (10s); daha sık veya daha seyrek; startup'ta hemen, sonra 10s | Düşük |
| process_command timeout | start_bot/stop_bot uzun sürerse (DB lock); asyncio.wait_for ile timeout | Orta |

## Mevcut — Özet Sayısal (Bot Engine)

| Metrik | Değer |
|--------|--------|
| tick_interval_ms (DCA) | 2000 (config); next_wake saniye |
| TRDCA tick_interval_ms | 1000 (config) |
| Symbol lock lease | 60 s |
| Idempotency TTL | 5 s (2 s initial_allocation) |
| Worker command poll | 1 s |
| ensure_running_bots | Her 10 worker iteration |
| perf_chart_sample (worker) | Her 60 iteration (~60 s) |
| _engine_tick_loop | 5 s sleep; 12× tick'te ENGINE_TICK log |
| PRICE_STALE throttle | 300 s (5 dk) per bot |

## Bot Engine Checklist

- [ ] _bot_loop: load_state → price → strategy.tick → lock → run_actions → save_state → sync_virtual_wallet
- [ ] TRDCA: _build_trdca_snapshot (balances, prices, filters, open_orders) → trdca_strategy_tick → ACTIONS → run_actions
- [ ] save_state: 2 commit; state_version increment; JSON serialize
- [ ] append_event: sadece _LOGGED_EVENT_TYPES; IDEMPOTENT_LOCK SKIP_REASON atlanır
- [ ] run_actions: acquire_bot_lock; check_idempotency; adapter place; apply_fill; cycle_ledger; save_state; append_event
- [ ] Worker: fetch_pending_commands 50; process_command START/STOP; ensure_running_bots her 10; perf_sample her 60

## Mevcut — Ledger (app/bot/ledger.py)

| Metod | Açıklama |
|-------|----------|
| record_trade | Trade INSERT; order_id ile idempotent (var ise existing dön); cycle_id optional |
| get_trades | Trade filter bot_id, account_id; cycle_id optional; order_by ts desc limit |
| get_trades_dict | get_trades → dict list |
| get_cycle_ids | Distinct cycle_id; newest first; NULL=1 backward compat |
| record_cycle_end | CYCLE_END kaydı; profit_usdt, cycle_type, base_delta; execution içinde cycle bitince çağrılır |

Ledger DB tablosu Trade; cycle bilgisi state.cycle_ledger_current ve cycle_pnls ile birlikte kullanılır.

## Mevcut — run_actions Fill Akışı (Detay)

| Adım | İşlem |
|------|--------|
| place_market_buy/sell | adapter çağrısı; paper_mode ise _simulate_fill |
| Fill alındı | fill_qty, fill_price, fee; apply_fill_to_state (state base_balance, quote_balance, grid fill tracking, cycle_ledger) |
| cycle_ledger_add_fill | ledger["fills"].append; buy/sell totals güncelle; _cycle_ledger_recompute → realized_pnl_quote |
| cycle_reset_after_fill | close_reason trail_profit_sell / trail_reentry_buy; cycle_id += 1; cycle_ledger_current = build_cycle_ledger_empty; cycle_pnls.append({...}); Ledger.record_cycle_end |
| initial_allocation_done | Sadece gerçek fill sonrası state["initial_allocation_done"] = True |
| _write_fill_snapshot_to_state | adapter.get_account_balances; free_quote, locked_quote, base_qty, avg_cost, realized_pnl, fees_total → state["last_fill_snapshot"] |
| update_virtual_after_fill | virtual_wallet tablosu güncelle (base/quote) |

## Mevcut — grid_view (UI Görünümü)

| Fonksiyon | Girdi | Çıktı |
|-----------|-------|--------|
| compute_grid_profit_view | state, config, current_price | sell_grids, buy_grids (her biri price, pct, filled, qty, value, status); avg_sell_price, avg_buy_price; cycle_ledger realized_pnl; profit_exit_trigger |
| compute_trdca_grid_view | state, config, prices_map | TRDCA için benzer yapı; parite, ağırlıklar, bakiye dağılımı |

API GET /bots-engine/{id} response'a grid alanı ekler; frontend tabloda gösterir.

## Mevcut — DcaGridTrailingConfig Parametreleri (Özet)

| Parametre | Varsayılan | Açıklama |
|-----------|------------|----------|
| symbol | BTCUSDT | İşlem çifti |
| initial_capital_usdt | 1000 | Bütçe |
| base_alloc_pct / quote_alloc_pct | 50/50 | İlk alımda base/quote dağılımı |
| fee_rate, buy_fee_rate, sell_fee_rate | 0.001 | Komisyon |
| min_net_profit_rate | 0.001 | Kar çıkışı minimum oran |
| pnl_mode | cycle_only_fee_aware_v1 | PnL hesaplama modu |
| sell_grids_count, sell_grids | 0, [] | Yukarı grid seviyeleri |
| buy_grids_count, buy_grids | 0, [] | Aşağı grid seviyeleri |
| sell_trigger_trailing_pct, buy_trigger_trailing_pct | 0.3 | Trailing yüzde |
| profit_reentry_drop_pct, profit_reentry_rise_pct | 1.0, 0.3 | Reentry tetikleme |
| profit_exit_rise_pct, profit_exit_drop_pct | 1.0, 0.3 | Kar çıkış tetikleme |
| basis_mode | grid_only | total / grid_only ortalama maliyet |
| tick_interval_ms | 2000 | Tick aralığı (ms) |
| max_orders_per_minute | 12 | Dakikada max emir |
| min_notional_guard | 5.0 | Min notional (USDT) |
| initial_fee_buffer_pct, available_quote_buffer_pct | 0.002, 0.005 | Bakiye buffer |

## Mevcut — TRDCA Snapshot İçeriği

| Alan | Kaynak |
|------|--------|
| ts | time.time() * 1000 |
| balances_free | Paper: state.virtual_balances veya initial_capital; gerçek: adapter.get_account_balances; initial_capital > 0 ise scale |
| prices_last | adapter.get_price(sym) her asset için; quote_asset = 1.0 |
| filters | adapter.get_symbol_filters(sym) her symbol; minQty, stepSize, minNotional |
| open_order | adapter.get_open_orders(symbol=None); ilk açık emir (symbols içinden) |
| fills | state._pending_fills (önceki tick'ten kalan fill'ler) |

_build_trdca_snapshot: N asset → N get_price, N get_symbol_filters, 1 get_account_balances, 1 get_open_orders.

## Mevcut — append_perf_chart_sample Tetikleyicileri

| Konum | Tetikleyici |
|-------|-------------|
| main.py | _perf_chart_sample_loop; asyncio.sleep(60); tüm running botlar için append_perf_chart_sample |
| worker_main.py | loop_count % 60 == 0; running botlar için append_perf_chart_sample |

append_perf_chart_sample: bot_perf_chart_state oku; bucket (range) bazlı yeni sample gerekirse ekle; PERF_CHART_MAX_AGE_SEC 7 gün; save.

## Mevcut — Bots Engine API Detail Response Alanları

| Alan | Kaynak |
|------|--------|
| bot_id, account_id, symbol, status, config | Bot row |
| state | load_state(db, bot_id) |
| current_price | DataHub (adapter.get_price / _get_price_from_datahub) |
| price_24h_change_pct | 24h ticker (Binance veya DataHub) — tek sembol |
| grid | compute_grid_profit_view veya compute_trdca_grid_view |
| current_usd | base_balance * price + quote_balance (veya TRDCA toplam). İlk alım yapılmamışsa (initial_allocation_done=False) tek sembol DCA'da config bütçesi (initial_capital_usdt) kullanılır; BOT BAKİYESİ parametrelerle tutarlı görünür. |
| daily_pnl_usd, daily_pnl_pct | state daily_ref ile hesaplanan veya PnlService |
| cycle_pnl_last | state.cycle_pnls son eleman |
| started_at | Bot.started_at |
| base_balance, quote_balance | state veya virtual_wallet / TRDCA balances |

Frontend 1s'te bir bu endpoint'i çağırır; her seferinde load_state, grid view, fiyat.

## Mevcut — Strategy Registry

| strategy_id | Sınıf / Fonksiyon |
|-------------|-------------------|
| (default) | DcaGridTrailingStrategy; tick → tick_dca_grid_trailing |
| multi_asset_rebalance | MultiAssetRebalanceStrategy |
| trdca_pro | trdca_strategy_tick (snapshot, state, cfg) → (next_state, decision) |

get_strategy_safe(raw): config.strategy_id veya raw["strategy_id"]; registry'den sınıf; instance.tick veya doğrudan trdca_strategy_tick.

## Mevcut — Hata ve Pause

| Koşul | Davranış |
|-------|----------|
| ACCOUNT_KEYS_MISSING / ACCOUNT_KEYS_EMPTY / ACCOUNT_KEYS_DECRYPT_FAIL | state last_error_code; append_event ERROR; await sleep(30); continue |
| PRICE_STALE_OR_MISSING | append_event SKIP_REASON (throttle 5 dk); next_wake sleep; continue |
| LOCK_BUSY | append_event LOCK_BUSY; save_state; sleep; continue |
| BOT_LOOP_TOPLEVEL_EXCEPTION | Bot.status = paused_error; state last_error_code; append_event ERROR; loop devam (status kontrolü ile break) |
| BOT_LOOP_TRDCA_EXCEPTION | Aynı; TRDCA dalında |
| asyncio.CancelledError | finally: _stop_requested.discard; _tasks.pop; BOT_LOOP_END log |

## Geliştirilebilir — TRDCA Snapshot ve Fiyat

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Toplu fiyat | get_price N yerine DataHub.get_all_prices() bir kez; snapshot'ta prices_last = subset(all_prices) | Yüksek |
| filters cache | get_symbol_filters aynı symbol için 1 dk TTL cache (exchangeInfo değişmez sık) | Orta |
| Snapshot süresi log | _build_trdca_snapshot başlangıç/bitiş ms; yavaş bot tespiti | Düşük |

## Geliştirilebilir — State ve Bellek

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| state_json boyut sınırı | cycle_pnls/fills çok büyürse eski cycle'ları trim (son 50 cycle); tablo büyümesi | Orta |
| cycle_ledger_current trim | fills listesi son 200 fill (veya son 1 cycle); tam geçmiş ayrı tabloda | Düşük |
| state_version overflow | Uzun süre çalışan botta state_version çok artar; periyodik normalize (0'a sıfırlama riskli) | Düşük |

## Geliştirilebilir — API bots_engine

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Detail cache | GET /{id} response 1–2s TTL (aynı bot_id); frontend 1s poll yerine 2s + cache | Yüksek |
| Grid lazy | ?fields=state,grid ayrı; sadece grid sekmesi açıkken grid hesapla | Orta |
| events cursor | list_events after_id; infinite scroll | Orta |
| Performance endpoint | period cache 5–10s | Orta |

## Mevcut — DB Tabloları (Bot Engine İlgili)

| Tablo | Kullanım |
|-------|----------|
| bot_engine_state | state_json, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at; bot_id UNIQUE |
| bot_engine_events | bot_id, account_id, ts, event_type, message, meta_json; append-only |
| bot_engine_commands | id, account_id, bot_id, command, payload_json, status (PENDING, PROCESSING, DONE, ERROR), processed_at, error_code, error_id |
| symbol_locks | account_id, symbol, owner_bot_id, lease_until, updated_at |
| bot_virtual_wallet | bot_id, account_id, symbol, virtual_base, virtual_quote |
| bot_perf_chart_state | bot_id, baseline (JSON), samples (JSON), range |
| Trade (app.db.models) | bot_id, account_id, ts, side, qty, price, fee, order_id, client_order_id, symbol, cycle_id |

## Mevcut — Orchestrator Global Değişkenler

| Değişken | Amaç |
|----------|------|
| _tasks | bot_id → asyncio.Task (_bot_loop) |
| _stop_requested | bot_id set; stop_bot'ta add; loop içinde while bot_id not in _stop_requested |
| _config_cache | bot_id → config object |
| _task_create_lock | asyncio.Lock; start_bot'ta task oluştururken |
| _loop_instances | bot_id → loop_instance_id (UUID kısa) |
| _last_stale_event_ts | bot_id → timestamp; PRICE_STALE throttle |

## Geliştirilebilir — Tick Throughput ve Ölçek

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Çok bot aynı anda tick | Her bot kendi asyncio task; paylaşılan DB pool; yoğun yükte pool exhaustion | Pool size artırma veya tick stagger (bot_id % N == loop_count % N) | Orta |
| Worker ayrı process | Komut işleme web process'ten ayrı; zaten worker_main ayrı çalışıyor | — |
| Orchestrator web içinde | ensure_running_bots hem web (start_bot sonrası) hem worker'da; task'lar web process'te | Worker'da da _bot_loop çalıştırmak için paylaşılan queue veya tek process | Düşük (mimari) |

## Mevcut — Kritik Yol Özeti (Tek Tick, DCA)

1. Bot row + load_state (2 DB).
2. get_account_keys; BinanceAdapter.
3. get_price(symbol) — 1 DataHub.
4. get_virtual_wallet — 1 DB.
5. strategy.tick — CPU.
6. try_acquire_symbol_lock — 1–2 DB.
7. run_actions: acquire_bot_lock; per action: check_idempotency, adapter place, apply_fill, Ledger, save_state, append_event — DB + Binance.
8. release_symbol_lock — 1 DB.
9. save_state — 1–2 DB commit.
10. sync_virtual_wallet_from_state — 1 DB.
11. sleep(next_wake).

## Özet — Bot Engine Mevcut vs Geliştirilebilir

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| Tick yolu | load_state → price → strategy → lock → run_actions → save_state → sync_virtual_wallet | save_state tek commit; TRDCA toplu fiyat |
| Event | append_event tek tek; list_events limit=500 | Batch insert; sayfalama/cursor |
| Execution | run_actions sıralı; idempotency 5s | TRDCA paralel leg; order timeout |
| Lock | symbol 60s lease; bot asyncio.Lock | Lease yenileme; lock cleanup |
| API detail | Her 1s; load_state + grid + fiyat | 1–2s cache; fields lazy |
| TRDCA snapshot | N get_price, N get_symbol_filters | get_all_prices; filters cache |
| State | state_json büyüyebilir (cycle_pnls, fills) | Trim; boyut sınırı |

## Mevcut — Paper Mode ve Test Hesap

| Koşul | Davranış |
|-------|----------|
| get_account_keys testnet | Sadece test hesabı (is_test_account) için account.mode kullanılır; gerçek hesaplar her zaman testnet=False (mainnet). binance_assets.get_account_keys. |
| paper_mode | User.username test hesap pattern; BinanceAdapter(..., paper_mode=True) |
| place_market_buy/sell | paper_mode ise adapter._simulate_fill; gerçek API çağrısı yok |
| get_account_balances | paper_mode ise boş veya test bakiye; TRDCA snapshot'ta initial_capital veya virtual_balances |
| virtual_balances | TRDCA paper: state.virtual_balances; fill sonrası _apply_fills_to_virtual_balances ile güncellenir |
| check_virtual_budget / Binance balance | paper_mode + TRDCA/MULTI ise skip_virtual_check; yoksa get_virtual_wallet, check_virtual_budget; paper değilse BUY/SELL öncesi adapter.get_account_balances ile free kontrolü |
| INSUFFICIENT_BALANCE (-2010) | Bot status paused_insufficient_balance; state backoff_until 60s; append_event ERROR |

## Mevcut — Execution Guard Özeti

| Guard | Koşul | Sonuç |
|-------|--------|-------|
| initial_allocation_done | Zaten True ise initial_allocation action skip | — |
| check_idempotency | (bot_id, action_key) TTL içinde | SKIP_REASON IDEMPOTENT_LOCK |
| guard_min_notional | notional < min_notional_guard | SKIP_REASON MIN_NOTIONAL |
| initial_allocation INSUFFICIENT_QUOTE | required > available (quote_free): quote_qty cap'lenir (available/(1+fee_buffer)); cap >= min_notional ise EXECUTE, yoksa SKIP | INFO "İlk alım miktarı bakiyeye göre düşürüldü" veya SKIP_REASON INSUFFICIENT_QUOTE |
| check_virtual_budget | DCA: virtual quote/base yetersiz | SKIP_REASON VIRTUAL_BUDGET_INSUFFICIENT |
| BINANCE_FREE_QUOTE_INSUFFICIENT | !paper_mode BUY: quote_qty + buffer > free_usdt | SKIP_REASON; continue |
| BINANCE_FREE_BASE_INSUFFICIENT | !paper_mode SELL: qty > free_base * (1 - buffer) | SKIP_REASON; continue |
| INSUFFICIENT_BALANCE (Binance -2010) | place_* exception code -2010 | Bot paused_insufficient_balance; backoff_until; append_event ERROR |
| 401 Unauthorized | _is_401_unauthorized; log throttle 10 dk; state backoff_until 300 s | continue (emir atılmaz); backoff süresince order denemesi skip |

## Mevcut — engine.metrics.json (Worker)

| Alan | Açıklama |
|------|----------|
| active_bots | len(_tasks) |
| last_tick_ts | Son worker loop başlangıç zamanı |
| last_tick_age_s | now - last_tick_ts |
| tick_rate_10s | Son 10s içinde worker iteration sayısı |
| pending_jobs | Son fetch_pending_commands uzunluğu |
| queue_len | Aynı |
| open_orders | 0 (placeholder) |
| safe_stop_count | 0 (placeholder) |
| last_error_ts | Worker loop exception zamanı |
| ts | now |

Her 2 worker iteration'da .run/engine.metrics.json yazılır (atomic).

## Mevcut — ensure_running_bots Akışı

| Adım | İşlem |
|------|--------|
| 1 | Bot.query.filter(Bot.status == 'running').all() |
| 2 | Her bot_id için: bot_id in _tasks ise skip |
| 3 | _task_create_lock; tekrar bot_id in _tasks kontrolü (double-start önleme) |
| 4 | asyncio.create_task(_bot_loop(bot_id)); _tasks[bot_id] = task |

Worker 10 iteration'da bir ensure_running_bots çağırır; web tarafında start_bot sonrası da task oluşturulur.

## Mevcut — delete_bot_fully

| Adım | İşlem |
|------|--------|
| 1 | _stop_requested.add(bot_id); task varsa cancel |
| 2 | Bot delete veya status güncelleme; ilgili tablolar (state, events, commands, virtual_wallet, symbol_locks, perf_chart_state, Trade, PnlSnapshot vb.) temizleme |
| 3 | _tasks.pop; _config_cache.pop; _stop_requested.discard |

Orchestrator.delete_bot_fully; tam silme işlemi.

## Mevcut — DCA Strategy Mod Geçişleri

| Mod | Sonraki |
|-----|---------|
| IDLE | initial_allocation action → (fill sonrası IDLE); veya trail tetiklenince TRAIL_SELL_GRID / TRAIL_BUY_GRID |
| TRAIL_SELL_GRID | Fiyat <= thr → SELL action; fill → cycle_reset veya TRAIL_REENTRY_BUY / TRAIL_PROFIT_SELL |
| TRAIL_BUY_GRID | Fiyat >= thr → BUY action; fill → IDLE veya sonraki grid |
| TRAIL_REENTRY_BUY | Reentry buy fill → IDLE |
| TRAIL_PROFIT_SELL | Profit sell fill → cycle_reset; cycle_id++; IDLE |

apply_fill_to_state ve cycle_reset_after_fill state.mode ve cycle_id günceller.

## Mevcut — apply_fill_to_state (DCA) Özeti

| Güncelleme | Açıklama |
|------------|----------|
| base_balance, quote_balance | Fill side'a göre +/- |
| Grid fill tracking | sell_grids_filled_qty, buy_grids_filled_qty; grid_index dolu mu |
| trail_anchor_price | Gerekirse güncellenir |
| cycle_ledger_current | cycle_ledger_add_fill ile fill eklenir |
| cycle_pnls | cycle_reset_after_fill'da yeni cycle bitince append |
| initial_allocation_done | initial_allocation fill sonrası True |
| reference_price, initial_alloc_base_qty, initial_alloc_price | İlk fill'da set |
| last_fill_snapshot | _write_fill_snapshot_to_state ile (execution'da) |
| free_quote, locked_quote | Snapshot'tan |

## Geliştirilebilir — Observability

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Tick süresi metrik | strategy.tick elapsed_ms; run_actions toplam süre; per-bot metrik (engine.metrics veya ayrı dosya) | Orta |
| Lock wait metrik | try_acquire_symbol_lock False sayısı; LOCK_BUSY event sayısı | Düşük |
| Event sayısı | ORDER_FILLED / CYCLE_END per bot per gün; dashboard | Düşük |
| state_json boyut | save_state öncesi len(js); büyük state uyarı | Düşük |

## Geliştirilebilir — Hata Kurtarma

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| paused_error otomatik retry | Belirli error_code (PRICE_STALE vb.) için N dakika sonra status running deneme | Düşük |
| state corrupt recovery | state_version uyuşmazlığı veya JSON parse hatası; skeleton state ile reset (dikkatli) | Düşük |
| Komut timeout | process_command içinde start_bot/stop_bot asyncio.wait_for 30s | Orta |

## Mevcut — Bots Engine Sayısal Özet (Tekrar)

| Metrik | Değer |
|--------|--------|
| tick_interval_ms (DCA) | 2000 (config) |
| TRDCA tick_interval_ms | 1000 |
| next_wake minimum | 0.5 s |
| symbol lock lease | 60 s |
| idempotency TTL | 5 s (2 s initial) |
| worker command poll | 1 s |
| ensure_running_bots interval | 10 worker iteration |
| perf_sample interval | 60 worker iteration |
| PRICE_STALE throttle | 300 s |
| _engine_tick_loop sleep | 5 s |
| ENGINE_TICK log (bots>0) | Her 12× tick (60 s) |
| 401 log throttle | 600 s |
| 401 backoff_until (ORDER_FAILED) | 300 s (order denemesi bu süre atlanır) |
| initial_alloc skip WARN | Aynı key > 3 (VIRTUAL_BUDGET) |
| backoff_until (INSUFFICIENT_BALANCE) | 60 s |

## Mevcut — Dosya ve Satır Referansı (Bot Engine)

| Dosya | Tahmini satır | Not |
|-------|----------------|-----|
| orchestrator.py | ~700 | _bot_loop, start/stop, ensure_running_bots, delete_bot_fully, _build_trdca_snapshot |
| execution.py | ~750 | run_actions, apply_fill, guards, Ledger, cycle_reset |
| state_store.py | ~240 | load_state, save_state, append_event, list_events |
| worker_main.py | ~380 | worker_loop, process_command, fetch_pending_commands |
| cycle_ledger.py | ~190 | build_cycle_ledger_empty, add_fill, breakeven, trigger |
| virtual_wallet.py | ~244 | get, ensure, sync, get_bot_locked_balances |
| locks.py | ~95 | try_acquire, release |
| risk.py | ~55 | acquire_bot_lock, check_idempotency, guard_min_notional |
| strategies/dca_grid_trailing.py | ~580 | tick_dca_grid_trailing, apply_fill_to_state, cycle_reset_after_fill |
| strategies/trdca_pro.py | ~900+ | strategy_tick, validate_and_normalize_batch |
| grid_view.py | ~270 | compute_grid_profit_view, compute_trdca_grid_view |
| models.py | ~440 | DcaGridTrailingConfig, TrdcaProConfig, build_state_skeleton |

## Bot Engine Görüntüleme Checklist (Geniş)

- [ ] _bot_loop: Bot row, load_state, config cache, keys, paper_mode, adapter, price, virtual_wallet, strategy.tick, symbol lock, run_actions, append_event, save_state, sync_virtual_wallet, daily_ref, sleep
- [ ] TRDCA: _build_trdca_snapshot (balances, prices, filters, open_order), trdca_strategy_tick, ACTIONS → run_actions, virtual_balances (paper)
- [ ] run_actions: acquire_bot_lock, idempotency, min_notional, virtual/Binance balance check, place_market_*, apply_fill_to_state, cycle_ledger_add_fill, cycle_reset_after_fill, Ledger.record_cycle_end, save_state, append_event
- [ ] save_state: state_version++, json.dumps, INSERT ON CONFLICT DO UPDATE, 2 commit
- [ ] append_event: _LOGGED_EVENT_TYPES; TICK ve IDEMPOTENT_LOCK atlanır
- [ ] Worker: fetch_pending_commands(50), mark_command_processing, process_command (START/STOP), mark_command_done, ensure_running_bots her 10, perf_sample her 60
- [ ] API: list load_state per bot; detail load_state + grid_view + price; events list_events(limit); performance PnlService + chart_state
- [ ] Paper mode: adapter.paper_mode; _simulate_fill; skip Binance balance check; TRDCA virtual_balances

## Özet — Bot Engine (Ek)

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| Paper / test | paper_mode; _simulate_fill; virtual_balances | — |
| Guards | idempotency, min_notional, virtual budget, Binance free quote/base, -2010 pause | order timeout; 401 retry |
| Metrik | engine.metrics.json; BOT_TICK log (debug) | tick süresi metrik; lock wait |
| Hata | paused_error; backoff_until; throttle log | otomatik retry; command timeout |

## Mevcut — BinanceAdapter Metodları

| Metod | Paper mode | Gerçek |
|-------|------------|--------|
| get_account_balances | Boş dict veya test bakiye | GET /api/v3/account |
| get_price(symbol) | DataHub veya 0 | data_hub.get_price(symbol) — Binance REST yok |
| get_symbol_filters(symbol) | Varsayılan step/minNotional | GET /api/v3/exchangeInfo (veya cache) |
| get_open_orders(symbol) | Boş liste | GET /api/v3/openOrders |
| place_market_buy(symbol, quote_qty, client_order_id) | _simulate_fill BUY | POST /api/v3/order orderType=MARKET quoteOrderQty |
| place_market_sell(symbol, qty, client_order_id) | _simulate_fill SELL | POST /api/v3/order orderType=MARKET quantity |
| cancel_order(symbol, order_id) | — | DELETE /api/v3/order |

Fiyat her zaman DataHub; böylece N bot tick'te N× Binance ticker/price çağrısı yok.

## Mevcut — TRDCA Decision Tipleri

| type | Açıklama |
|------|----------|
| NOOP | İşlem yok; state güncellemesi (next_state) uygulanır |
| RESUME_PENDING | Devam; state kaydedilir |
| SAFE_STOP | Hata; reason (error_code, error_id); append_event ERROR |
| ACTIONS | legs listesi; run_actions ile place; batch_id, notional_estimate |

strategy_tick(snapshot, state, cfg) → (next_state, decision); decision["type"], decision["actions"].

## Mevcut — CYCLE_END Event Meta

| Alan | Açıklama |
|------|----------|
| profit_usdt | Tur brüt kar (cash_pnl_usdt = sell_quote_total - buy_quote_total); cycle_ledger'dan türetilir |
| pnl_usdt_net | Tur net kar (realized_pnl_cycle_net = cash_pnl_usdt - cash_fees_usdt); cycle_ledger.realized_pnl_quote |
| realized_pnl_cycle_net | pnl_usdt_net ile aynı (tutarlılık) |
| fees_usdt | cash_fees_usdt = buy_fee_total_quote + sell_fee_total_quote |
| cycle_id | Kapanan tur |
| cycle_type | LONG_SCALP / INVENTORY_REBALANCE / UNKNOWN |
| base_delta | INVENTORY_REBALANCE için base alım-satım farkı |
| close_reason | trail_profit_sell / trail_reentry_buy |

**CYCLE_END invariant (TRAILING_DCA_PNL_SYSTEM_SPEC §55):** Meta yalnızca cycle_ledger_current recompute sonrasından türetilir. profit_usdt = cash_pnl_usdt (brüt), pnl_usdt_net = realized_pnl_cycle_net = realized_pnl_quote. Bu üç alan birbiriyle tutarlı olmalı; profit_usdt asla 0 gösterilmemeli (brüt pozitif/negatif olabilir), pnl_usdt_net net (fee sonrası).

Ledger.record_cycle_end veya execution içinde append_event("CYCLE_END", ..., meta); PnL raporu CYCLE_END meta'yı kullanabilir.

## Mevcut — ensure_state_row

| Adım | İşlem |
|------|--------|
| SELECT 1 FROM bot_engine_state WHERE bot_id | Var ise return |
| build_state_skeleton(bot_id, account_id, symbol) | Skeleton state dict |
| save_state(db, bot_id, account_id, sk) | İlk satır oluşturulur |

Bot loop başında bir kez; state hiç yoksa skeleton yazılır.

## Mevcut — build_state_skeleton (TRDCA)

| Kaynak | build_trdca_pro_state_skeleton |
|--------|---------------------------------|
| dca | DCA motor state (allocations, last_buy, vb.) |
| trb | TRB motor state (target_weights, last_rebalance, vb.) |
| quote_asset | config.quote_asset |
| initial_prices | _fetch_prices_for_assets (DataHub) |
| coin_weights | config.dca_coin_weights / trb_target_weights_all |

State tam dolu değilse (dca/trb None) skeleton ile merge; save_state.

## Geliştirilebilir — Cycle ve Ledger

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| cycle_ledger DB | Şu an sadece state içinde; kalıcı cycle özeti ayrı tablo (cycle_id, bot_id, realized_pnl, started_at, closed_at) | Düşük |
| Fills arşiv | cycle_ledger fills listesi büyürse; eski cycle'ları ayrı tabloya taşı | Düşük |
| get_cycle_ids optimizasyonu | Trade tablosunda distinct cycle_id; index (bot_id, cycle_id) | Orta |

## Geliştirilebilir — Virtual Wallet

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| sync_virtual_wallet sıklığı | Her tick sonunda; drift az. Alternatif: sadece fill sonrası (state zaten güncel) | Mevcut yeterli |
| get_bot_locked_balances cache | Dashboard snapshot'ta her seferinde sorgu; 2–3s cache | Orta |
| virtual_wallet unique | (bot_id, symbol) UNIQUE; INSERT ON CONFLICT | Mevcut tablo yapısına bağlı |

## Mevcut — Komut Akışı (Start/Stop)

| Adım | Konum |
|------|--------|
| 1 | API POST /bots-engine/{id}/start veya /stop → bot_engine_commands INSERT (command=START/STOP, status=PENDING) |
| 2 | Worker fetch_pending_commands → pending list |
| 3 | mark_command_processing(cmd_id) → UPDATE status=PROCESSING |
| 4 | process_command: start_bot(bot_id, db) veya stop_bot(bot_id, db) |
| 5 | start_bot: Bot status=running; seed_perf_chart_state; create_task(_bot_loop) |
| 6 | stop_bot: _stop_requested.add(bot_id); Bot status=stopped; task.cancel() |
| 7 | mark_command_done(cmd_id) → UPDATE status=DONE veya ERROR |
| 8 | append_event INFO COMMAND_EXECUTED |

Komutlar sırayla işlenir; aynı anda 50'ye kadar PENDING alınır.

## Mevcut — PnlService ve Bot Engine Bağlantısı

| Kullanım | Açıklama |
|----------|----------|
| state.cycle_pnls | Execution'da cycle_reset_after_fill ile append; PnlService calculate_bot_pnl bu listeyi kullanır (öncelikli) |
| CYCLE_END events | cycle_pnls yoksa event meta profit_usdt fallback |
| Ledger.get_cycle_ids | Tamamlanan tur sayısı; get_trades cycle_id filtresi |
| Trade tablosu | Ledger.record_trade ile her fill; PnlService Trade sorgusu |

Bot engine state ve Ledger/Trade tek kaynak; PnL raporu hem state.cycle_pnls hem Trade hem events kullanır.

## Mevcut — Bot Engine Görüntüleme Özeti (UI Tarafı)

| Sayfa / Bileşen | Veri Kaynağı |
|-----------------|--------------|
| Dashboard bot listesi | GET /api/dashboard/snapshot → bots; veya GET /api/bots-engine?account_id → bots |
| Bot satırı (symbol, status, current_usd, daily_pnl) | Snapshot bots array |
| Bot detay sayfası | GET /api/bots-engine/{id}?account_id → state, grid, current_price, daily_pnl |
| Olaylar sekmesi | GET /api/bots-engine/{id}/events?limit=500 |
| Performans sekmesi | GET /api/bots-engine/{id}/performance?period=all|day|week|month |
| Performans grafiği | GET /api/bots-engine/{id}/perf-chart-state; perf_chart_tv.js getDataFromDom |
| Fiyat poll (detay) | 1s GET /api/bots-engine/{id} |

Tüm bu istekler backend'de load_state, grid_view, PnlService, Ledger, bot_perf_chart_state kullanır.

## Geliştirilebilir — Strateji ve Config

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| config schema version | Config değişince state uyumsuz kalabilir; config_version state'te; migration script | Düşük |
| strategy_id runtime değişimi | Bot config'te strategy_id değiştirilirse mevcut state uyumsuz; temiz state veya uyarı | Düşük |
| tick_interval dinamik | Yüksek yük altında interval artırma (config override veya env) | Düşük |

## Bot Engine Bölüm Sonu Özet

- **Mevcut:** Orchestrator (_bot_loop, TRDCA snapshot, start/stop), state_store (load/save, events), execution (run_actions, guards, fill apply, cycle reset), cycle_ledger, virtual_wallet, locks, risk (bot lock, idempotency), worker (commands, ensure_running_bots, perf_sample), API (list, detail, events, performance, perf-chart-state), strategies (DCA grid, TRDCA), grid_view, Ledger (Trade), paper mode, engine.metrics.json.
- **Geliştirilebilir:** save_state tek commit, TRDCA toplu fiyat/filters cache, event batch/sayfalama, detail cache/fields lazy, state trim, lock cleanup, tick metrik, command timeout, cycle ledger DB/archive.

## Mevcut — Strateji Registry Detay

| strategy_id (raw) | Config sınıfı | Strategy / tick |
|-------------------|--------------|------------------|
| (yok veya boş) | DcaGridTrailingConfig(raw) | DcaGridTrailingStrategy.tick → tick_dca_grid_trailing |
| multi_asset_rebalance | MultiAssetRebalanceConfig(raw) | MultiAssetRebalanceStrategy.tick |
| trdca_pro | TrdcaProConfig (config_trdca_pro_from_payload) | trdca_strategy_tick(snapshot, state, cfg) — ayrı fonksiyon |

get_strategy_safe: registry.get(strategy_id) veya default DcaGridTrailingStrategy; instance döner; tick(state, cfg, price, base_balance, quote_balance) veya TRDCA için doğrudan trdca_strategy_tick.

## Mevcut — DCA Grid Trailing Action Reason Değerleri

| reason | Açıklama |
|--------|----------|
| initial_allocation | İlk alım (base+quote dağılımı). START komutu işlenirken worker ilk tick'i hemen çalıştırır (run_one_bot_tick cmd_immediate) → market alım anında gönderilir; "Oluştur" tek tıkla bot + başlat + ilk alım. Başarısız olursa scheduler/loop tekrar dener (next_wake en fazla 1 sn). |
| trail_sell_grid | Yukarı grid satış seviyesi |
| trail_buy_grid | Aşağı grid alım seviyesi |
| trail_reentry_buy | Reentry alım (fiyat düşünce) |
| trail_profit_sell | Kar çıkış satışı |
| trdca_batch | TRDCA çok bacaklı emir (legs) |

action_key: reason + grid_index + client_order_id; idempotency bu key'e göre.

## Mevcut — state_json Ana Anahtarlar (DCA)

| Anahtar | Açıklama |
|--------|----------|
| bot_id, account_id, symbol | Kimlik |
| cycle_id, mode | Tur ve mod (IDLE, TRAIL_SELL_GRID, vb.) |
| state_version | Optimistic lock; save_state'ta artar |
| initial_allocation_done | İlk alım yapıldı mı |
| reference_price, initial_alloc_base_qty, initial_alloc_price | İlk alım referansı |
| base_balance, quote_balance | Güncel bakiye |
| free_quote, locked_quote | Son fill snapshot'tan |
| cycle_ledger_current | Mevcut tur ledger (fills, totals, realized_pnl_quote) |
| cycle_pnls | Tamamlanan turların kar listesi [{cycle_id, pnl_usdt, fees_usdt, ...}] |
| sell_grids_filled_qty, buy_grids_filled_qty | Grid doluluk (veya benzeri alanlar) |
| trail_anchor_price, _trail_sell_grid_index, _trail_buy_grid_index | Trailing state |
| daily_ref_usd, daily_ref_date | Günlük K/Z referansı |
| last_tick_at, last_error_code, retry_at | Meta |
| last_fill_snapshot | Son fill sonrası snapshot (free_quote, base_qty, avg_cost, realized_pnl, fees_total) |

## Mevcut — TRDCA State Anahtarlar (Özet)

| Anahtar | Açıklama |
|---------|----------|
| dca | DCA motor state (allocations, last_buy_ts, vb.) |
| trb | TRB (rebalance) motor state (target_weights, last_rebalance_ts, vb.) |
| virtual_balances | Paper: asset → bakiye |
| quote_asset | USDT / FDUSD vb. |
| _pending_fills | Önceki tick fill'leri (snapshot'a geçer) |

## Geliştirilebilir — Performans Özet (Bot Engine)

| Alan | Mevcut | Öneri |
|------|--------|-------|
| DB tick başına | load_state 1, get_virtual_wallet 1, lock 1–2, save_state 1–2, sync_virtual 1, append_event N | save_state tek commit; event batch |
| Fiyat | 1 get_price (DCA); N get_price (TRDCA) | TRDCA: get_all_prices 1 |
| API detail | Her 1s; tam response | Cache 1–2s; ?fields= |
| Events | limit=500 tek istek | Cursor; limit 100 ilk |

## Mevcut — Kritik Yol (TRDCA Tek Tick)

1. _build_trdca_snapshot: balances (virtual veya get_account_balances), prices_last (get_price × N), filters (get_symbol_filters × N), get_open_orders.
2. trdca_strategy_tick(snapshot, state, cfg) → next_state, decision.
3. state.update(next_state).
4. decision ACTIONS: legs → trdca_actions; try_acquire_symbol_lock(MULTI); run_actions(trdca_actions); append_event × legs; virtual_balances (paper); release_symbol_lock.
5. save_state; sleep(next_wake).

Darboğaz: Snapshot (N fiyat + N filters + 1 balances + 1 open_orders); run_actions (sıralı place).

## Bot Engine Bölüm Satır Sayısı

Bu bölüm (SECTION E.6) mevcut + geliştirilebilir alt başlıkları, tablolar, checklist ve özetlerle birlikte yaklaşık 1000 satır bilgi içerir. Referans: orchestrator, state_store, execution, cycle_ledger, virtual_wallet, locks, risk, worker_main, strategies, grid_view, models, API bots_engine, Ledger, paper mode, engine metrics.

## Mevcut — Bot Engine Bağımlılık Özeti

| Modül | Bağımlılıklar |
|-------|----------------|
| orchestrator | state_store, execution, locks, strategies (registry, trdca_pro), models (config, skeleton), virtual_wallet, BinanceAdapter, get_account_keys |
| execution | Ledger (app.bot), cycle_ledger, state_store, virtual_wallet, risk, dca_grid_trailing (apply_fill_to_state, cycle_reset_after_fill) |
| state_store | DB text() sorguları; json; bot_engine_state, bot_engine_events |
| worker_main | orchestrator (ensure_running_bots, start_bot, stop_bot), state_store (append_event), fetch_pending_commands (bot_engine_commands) |
| API bots_engine | state_store, grid_view, PnlService, Ledger, perf_chart_state, DataHub (fiyat), get_account_or_403 |

## Mevcut — Tick Süresi Bileşenleri (Tahmini)

| Bileşen | Tahmini (ms) |
|---------|---------------|
| load_state (DB 1 sorgu) | 5–20 |
| get_price (DataHub bellek) | 0.1–2 |
| get_virtual_wallet (DB 1 sorgu) | 5–20 |
| strategy.tick (CPU) | 1–50 (grid sayısına bağlı) |
| try_acquire_symbol_lock (DB 1–2) | 5–30 |
| run_actions (1 action: place + apply_fill + save + event) | 50–200 (Binance RTT + DB) |
| save_state (2 commit + JSON) | 10–80 (state boyutuna bağlı) |
| sync_virtual_wallet_from_state | 5–20 |
| **Tek tick toplam (action yok)** | ~30–150 ms |
| **Tek tick (1 action)** | ~100–400 ms |

## Geliştirilebilir — Ölçek ve Limit

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Max concurrent bots per process | Çok bot aynı process'te; DB pool ve CPU paylaşımı; üst sınır (örn. 50) veya uyarı | Düşük |
| Max actions per tick | Bir tick'te çok action (grid çok seviye); rate limit veya batch | Düşük |
| Symbol lock timeout | Lock alınamazsa 2s bekleme (opsiyonel); şu an hemen skip | Düşük |

## Mevcut — Bot Engine Dosya Ağacı (Referans)

```
app/botengine/
  __init__.py
  orchestrator.py    # _bot_loop, start_bot, stop_bot, ensure_running_bots, delete_bot_fully
  state_store.py     # load_state, save_state, append_event, list_events, ensure_state_row
  execution.py      # run_actions, apply_fill, cycle_reset, _write_fill_snapshot_to_state
  cycle_ledger.py    # build_cycle_ledger_empty, cycle_ledger_add_fill, breakeven, trigger
  virtual_wallet.py  # get_virtual_wallet, ensure_virtual_wallet, sync_virtual_wallet_from_state
  locks.py           # try_acquire_symbol_lock, release_symbol_lock
  risk.py            # acquire_bot_lock, check_idempotency, guard_min_notional
  grid_view.py       # compute_grid_profit_view, compute_trdca_grid_view
  models.py          # DcaGridTrailingConfig, TrdcaProConfig, build_state_skeleton
  worker_main.py     # worker_loop, process_command, fetch_pending_commands
  adapters/
    binance_adapter.py  # BinanceAdapter
  strategies/
    base.py
    dca_grid_trailing.py
    multi_asset_rebalance.py
    trdca_pro.py
    registry.py
app/bot/
  ledger.py          # Ledger.record_trade, get_trades, get_cycle_ids, record_cycle_end
app/api/
  bots_engine.py     # REST: list, detail, events, performance, perf-chart-state, start, stop
```

## Özet — Bot Engine (Son)

| Kategori | Mevcut | Geliştirilebilir |
|----------|--------|------------------|
| Görüntüleme | API list/detail/events/performance; grid_view; state, cycle_pnls, Ledger | Detail cache; events cursor; ?fields |
| Optimizasyon | Config cache; DataHub fiyat (Binance yok); idempotency; symbol lock | save_state tek commit; TRDCA toplu fiyat; event batch; state trim |
| Hız | tick_interval 1–2s; next_wake min 0.5s; DB tick başına ~5–10 sorgu | Tick süresi metrik; lock wait metrik; command timeout |

## Mevcut — Event Tipi ve UI Kullanımı

| event_type | UI'da gösterim |
|------------|----------------|
| ORDER_FILLED | İşlem dolu; meta fill_qty, fill_price |
| CYCLE_END | Tur bitti; meta profit_usdt, cycle_id |
| ERROR | Hata; meta error_code, error_id |
| SKIP_REASON | Atlanan (PRICE_STALE, IDEMPOTENT_LOCK, MIN_NOTIONAL, vb.) |
| LOCK_BUSY | Sembol kilitli |
| INFO | Bilgi (COMMAND_EXECUTED vb.) |
| BOT_ACTION | (varsa) aksiyon logu |

TICK ve IDEMPOTENT_LOCK event olarak yazılmaz; gürültü azaltma.

## Mevcut — Bot Status Değerleri

| status | Anlam |
|--------|--------|
| running | Loop aktif; tick çalışıyor |
| stopped | Durduruldu; task yok |
| paused_error | Tick exception; last_error_code set |
| paused_insufficient_balance | Binance -2010; backoff_until |

start_bot → running; stop_bot → stopped; exception veya INSUFFICIENT_BALANCE → paused_*.

## Geliştirilebilir — Dokümantasyon

| Öneri | Açıklama |
|-------|----------|
| Bot engine akış diyagramı | _bot_loop, run_actions, cycle_reset ASCII/ Mermaid |
| Config alanları spec | Her config alanı (min, max, birim, varsayılan) |
| Event type spec | Tüm event_type ve meta şeması |
| State şema versiyonu | state_version veya state_schema_version; migration |

## Mevcut — append_perf_chart_sample (Detay)

| Adım | İşlem |
|------|--------|
| bot_perf_chart_state SELECT | baseline, samples, range |
| Güncel bakiye / parite | state + fiyat veya DataHub; botPct, paritePct hesapla |
| Bucket | range (1m, 5m, 1h, 4h, 1d) ile bucket bitiş zamanı |
| Yeni sample gerekli mi | Son sample ts < bucket_end; PERF_CHART_MAX_AGE_SEC aşmamış |
| samples.append({ts, botPct, paritePct}); 7 gün öncesi trim | UPDATE bot_perf_chart_state |

main.py loop 60s; worker loop ~60 iteration (~60s); her running bot için çağrılır.

## Bot Engine Bölüm Sonu Notu

SECTION E.6, bot engine'in mevcut davranışını (orchestrator, state, execution, cycle ledger, virtual wallet, locks, risk, worker, strategies, API) ve geliştirilebilir noktaları (cache, batch, toplu fiyat, metrik, timeout) tek yerde toplar. Yaklaşık 1000 satır.

---

# SECTION E.7 — BOT STRATEJİLERİ MANTIK VE UYGULAMASI

## Mevcut — Strateji Arayüzü (Base)

| Öğe | Açıklama |
|-----|----------|
| Strategy (base.py) | ABC; strategy_id class attribute; tick(state, config, price, base_balance, quote_balance) → (actions, next_wakeup_sec); apply_fill(state, side, executed_qty, executed_price, fee, grid_index, reason, execution_price) → None |
| tick | State mutasyonu yapabilir; dönen actions list of dict (type=place, side, symbol, quantity/quote_qty, client_order_id, reason, grid_index, vb.) |
| apply_fill | Fill sonrası state güncelleme; DCA grid'de sell_history/buy_history, base_balance, quote_balance, realized_pnl_usdt_cycle, fees_paid_usdt_cycle |
| next_wakeup_sec | Bir sonraki tick'e kadar beklenecek süre (saniye) |

Tek sembol stratejiler (DCA) price + base_balance + quote_balance alır; TRDCA snapshot-driven (snapshot, state, config) → (next_state, decision).

## Mevcut — Registry ve Seçim

| strategy_id | Sınıf | Kaynak |
|-------------|--------|--------|
| (boş / yok) | DcaGridTrailingStrategy | registry default |
| dca_grid_trailing | DcaGridTrailingStrategy | strategies/dca_grid_trailing.py |
| multi_asset_rebalance | MultiAssetRebalanceStrategy | strategies/multi_asset_rebalance.py |
| trdca_pro | TrdcaProStrategy | strategies/trdca_pro.py |

register(strategy_cls): decorator; _strategy_classes[sid] = cls; _strategies[sid] = instance. get_strategy(sid): instance döner; yoksa default dca_grid_trailing. get_strategy_safe(raw): raw dict ise raw["strategy_id"]; None/eksik ise "dca_grid_trailing". _ensure_default(): import sırasında üç strateji register.

## Mevcut — DCA Grid Trailing: Mod Makinesi

| Mod | Açıklama |
|-----|----------|
| IDLE | Tetik bekleniyor; sell grid, buy grid, reentry veya profit exit tetiklenebilir |
| TRAIL_SELL_GRID | Yukarı grid seviyesi (idx) için fiyat >= tetik; anchor güncellenir; fiyat <= anchor*(1 - sell_trigger_trailing_pct/100) olunca SELL action |
| TRAIL_BUY_GRID | Aşağı grid seviyesi (idx); fiyat <= tetik; anchor min; fiyat >= anchor*(1 + buy_trigger_trailing_pct/100) olunca BUY action |
| TRAIL_REENTRY_BUY | Satış sonrası reentry; avg_sell_price*(1 - profit_reentry_drop_pct/100) altına düşünce TRAIL_REENTRY_BUY; basket >= trough*(1 + profit_reentry_rise_pct/100) olunca BUY |
| TRAIL_PROFIT_SELL | Alım sonrası kar çıkış; cycle_only_fee_aware_v1 ise cycle_ledger breakeven/trigger_price; değilse avg_buy*(1 + profit_exit_rise_pct/100); fiyat >= trigger olunca SELL |

Sıra: Önce mevcut modda action üret (TRAIL_*); yoksa IDLE'da (A) sell grid tetik, (B) buy grid tetik, (C) reentry tetik, (D) profit exit tetik kontrolü.

## Mevcut — DCA Grid: İlk Tahsis (Initial Allocation)

| Koşul | Davranış |
|-------|----------|
| initial_allocation_done == False | Bütçe (initial_capital_usdt) base_pct / quote_pct ile bölünür; c_base = c * base_pct; tek action: type=place, side=BUY, quote_qty=c_base, reason=initial_allocation |
| initial_allocation_done | Execution'da gerçek fill sonrası state["initial_allocation_done"] = True set edilir; strategy sadece intent üretir |
| Self-heal | ia_done True ama initial_alloc_base_qty 0 ise base_balance'dan set; reference_price None ise P'den set; grid_reference_quote/grid_reference_base IDLE'da equity'den doldurulur |

## Mevcut — DCA Grid: Grid Seviye ve Miktar

| Grid | Tetik | Miktar |
|------|--------|--------|
| Sell grid i | ref * (1 + sell_grid_pct/100) <= P ise TRAIL_SELL_GRID; anchor = P | _sell_qty_for_grid: ref_base * sell_qty_pct_of_base; target_budgets varsa cap; min(ref_base*pct, base_balance) |
| Buy grid j | ref * (1 - buy_grid_pct/100) >= P ise TRAIL_BUY_GRID | _buy_qty_for_grid: ref_quote * buy_qty_pct_of_quote; target_budgets ile cap; min(ref*pct, quote_balance) |
| Reentry | avg_sell * (1 - profit_reentry_drop_pct/100) >= P | _reentry_buy_qty: **sum(sell qty*price)** (sell_history); cap = min(quote_balance, total). Not: Fee/slip sell tarafında kesildiği için gerçek eline geçen quote biraz daha düşük olabilir; reentry miktarı bu “brüt” toplama göre. |
| Profit exit | cycle_ledger trigger_price (fee-aware) veya avg_buy * (1 + profit_exit_rise_pct/100) | _profit_exit_sell_qty: **sum(buy_history qty)**; min(base_balance, total_q). **initial_allocation buy_history’ye yazılmaz** (reason==initial_allocation ise append yok); dolayısıyla “cycle close” = yalnız grid buy’ları sat (tasarım niyeti). |

_ensure_sell_buy_lists: sell_grid_fired, sell_grid_trigger_price, sell_grid_peak_price, buy_grid_fired, buy_grid_trigger_price, buy_grid_trough_price listeleri config grid sayısına göre state'te tutulur.

## Mevcut — DCA Grid: apply_fill_to_state

| Fill | Güncelleme |
|------|------------|
| SELL | base_balance -= qty; quote_balance += (qty*price - fee); sell_history.append(...); realized_pnl_usdt_cycle += (qty*price - fee - cost); fees_paid_usdt_cycle += fee. Fee alıcıdan kesilir (quote girişi net). |
| BUY (initial_allocation değilse) | base_balance += qty; quote_balance -= (qty*price + fee); buy_history.append({...}). Fee quote (USDT) cinsinden: toplam quote çıkışı cost+fee. (Kod: quote_balance - q*p - fee_val) |
| execution_price | Ortalama maliyet/tetik hesaplarında execution_price kullanılır (yoksa fill price) |

cost = qty * avg_buy (satışta maliyet). execution.py içinde apply_fill_to_state çağrılır; sonra cycle_ledger_add_fill, cycle_reset_after_fill (gerekirse).

## Mevcut — DCA Grid: cycle_reset_after_fill

| close_reason | İşlem |
|--------------|--------|
| trail_profit_sell | cycle_id += 1; cycle_ledger_current = build_cycle_ledger_empty; cycle_pnls.append({...}); **sell_history ve buy_history cycle_reset_after_fill ile temizlenir** (dca_grid_trailing.py); _profit_exit_done, _reentry_done, _cycle_complete; Ledger.record_cycle_end |
| trail_reentry_buy | cycle_id += 1; cycle_ledger_current = build_cycle_ledger_empty; base_delta = buy_qty - sell_qty (INVENTORY_REBALANCE); cycle_pnls append; Ledger.record_cycle_end |

get_cycle_type_and_base_delta(close_reason, ledger) → (cycle_type, base_delta). LONG_SCALP base_delta=0.

## Mevcut — DCA Grid: basis_mode ve Ortalama Fiyat

| basis_mode | Profit exit tetik fiyatı |
|------------|---------------------------|
| grid_only | _avg_buy_price_for_trigger (sadece buy_history; execution_price tercih) |
| total | _avg_buy_price_total (initial_alloc_base_qty*initial_alloc_price + grid buy_history) |
| **basis_mode / pnl_mode** | **pnl_mode=cycle_only_fee_aware_v1** ise profit-exit tetik fiyatı **cycle_ledger** breakeven/trigger ile hesaplanır (öncelikli). **basis_mode** (grid_only vs total) bu modda alternatif tetik yolunda veya raporlama için kullanılır. Kontrat: fee-aware açıkken “tetik fiyatı” tek kaynak cycle_ledger; basis_mode yalnız total maliyet/raporlama veya legacy tetik için. |

pnl_mode == cycle_only_fee_aware_v1 ise cycle_ledger_breakeven_price ve cycle_ledger_trigger_price kullanılır; basis_mode yok sayılmaz ama fee-aware path öncelikli.

## Mevcut — Multi-Asset Rebalance

| Öğe | Değer |
|-----|--------|
| strategy_id | multi_asset_rebalance |
| tick | config: assets[], rebalance_mode, threshold_pct, interval_sec, min_trade_usdt; next_wake_sec = interval_sec; actions = [] (boş döner); sadece REB_MULTI_TICK log |
| apply_fill | pass (no-op) |
| Config | assets: [{symbol, target_pct}]; rebalance: mode (threshold/interval/hybrid), threshold_pct, interval_sec, min_trade_usdt, fees_buffer_bps, max_trades_per_cycle, cooldown_sec; budget_usdt; symbol = "MULTI" |

Tam rebalance mantığı (fiyat, bakiye, hedef ağırlık, al/sat planı) orchestrator/execution tarafında ayrı bağlanabilir; strateji şu an sadece parametreleri okuyup boş action döner.

## Mevcut — TRDCA PRO: Giriş ve Decision

| Fonksiyon | İmza | Dönüş |
|-----------|------|--------|
| strategy_tick(snapshot, state, config) | snapshot: ts, balances_free, prices_last, filters, open_order, fills?; state: dict; config: TrdcaProConfig | (next_state, decision) |
| decision.type | NOOP \| RESUME_PENDING \| SAFE_STOP \| ACTIONS |
| decision.actions | ACTIONS ise [BatchIntent]; BatchIntent: kind, source, batch_id, legs[] |
| decision.reason | SAFE_STOP/RESUME_PENDING için { error_code, error_id, request_id, detail } |

Orchestrator TRDCA için _build_trdca_snapshot → strategy_tick(snapshot, state, cfg) çağırır; decision.type ACTIONS ise legs → trdca_actions → run_actions.

## Mevcut — TRDCA: Snapshot Geçidi ve open_order

| Koşul | decision |
|-------|----------|
| snapshot ts / balances_free / prices_last eksik | SAFE_STOP; last_reason SNAPSHOT_INVALID |
| filters veya open_order yok | SAFE_STOP; SNAPSHOT_INVALID |
| ts_ms <= state.last_tick_ts | NOOP (duplicate tick) |
| state.mode == SAFE_STOP | SAFE_STOP |
| state.mode == RESUME_PENDING | RESUME_PENDING |
| snapshot.fills varsa | apply_fills(state, fills, snapshot) |
| snapshot.open_order varsa | NOOP (açık emir varken yeni emir yok) |

## Mevcut — TRDCA: active_intent ve ACK Timeout

| Koşul | decision |
|-------|----------|
| active_intent.status == SENT ve (ts_ms - send_time_ms) < ack_timeout_ms | RESUME_PENDING (ORDER_ACK_WAIT) |
| active_intent SENT ve timeout geçti | SAFE_STOP; UNKNOWN_LEGS_ACK_TIMEOUT veya ORDER_ACK_TIMEOUT |

Gönderilen batch için fill/ack gelene kadar yeni batch üretilmez; timeout'ta SAFE_STOP.

## Mevcut — TRDCA: DCA Motor (dca_tick)

| Çıktı | Açıklama |
|-------|----------|
| state_patch | dca: { grid_up_consumed, grid_down_consumed, armed, vwap_sell, vwap_buy }; price_null_assets |
| proposal | source=DCA, want_action, valid, action (BatchIntent), intent_id, reason, priority, notional_estimate, impact_score, meta, exec_basket_price |
| anchor | state.anchor_price veya basket (ilk); DCA anchor'ı mutate etmez (spec) |
| Öncelik sırası | 1) POSTSELL_DIP 2) POSTBUY_PEAK 3) UP_SELL (grid_up seviyeleri) 4) DOWN_BUY (grid_down seviyeleri) |
| UP_SELL | basket >= anchor*(1+grid_up_pct/100); armed UP_SELL, peak güncelle; basket <= peak*(1 - sell_trail) olunca chosen; notional = dca_grid_up_notional_usdt[k] |
| DOWN_BUY | basket <= anchor*(1 - grid_down_pct/100); armed DOWN_BUY, trough güncelle; basket >= trough*(1 + buy_trail) olunca chosen; notional = dca_grid_down_notional_usdt[k] |
| POSTSELL_DIP | vwap_sell sonrası basket <= vwap_sell*(1 - dip_trigger) → armed POSTSELL_DIP; basket >= trough*(1 + dip_trail) → BUY notional |
| POSTBUY_PEAK | vwap_buy sonrası basket >= vwap_buy*(1 + profit_trigger) → armed POSTBUY_PEAK; basket <= peak*(1 - profit_trail) → SELL notional |
| Legs | coin_weights oranında her asset için qty = (alloc_notional * w / price); _floor_to_step; validate_and_normalize_batch |

## Mevcut — TRDCA: TRB Motor (trb_tick)

| Çıktı | Açıklama |
|-------|----------|
| state_patch | trb: { trb_state, gap_peak_pct, plan, trb_triggered_at_ts }; price_null_assets |
| proposal | source=TRB, want_action, action (batch), intent_id, reason=TRB_STEP |
| trb_state | IDLE \| TRAIL |
| IDLE | gap_pct = max \|target_weight - current_weight\|; gap_pct >= gap_arm_pct ise TRAIL; is_initial_allocation (base_sum<=0, quote>0) ise aynı tick'te plan yap |
| TRAIL | gap_peak_pct = max(gap_peak, gap_pct); gap_ok = gap_pct <= gap_peak*(1 - trail_back_pct) veya initial_allocation; gap_ok ise plan yoksa _trb_build_steps ile plan oluştur; step_idx < len(steps) ise action = steps[step_idx] |
| _trb_build_steps | SELL_ONLY_THEN_BUY: önce SELL legs, sonra BUY legs; max_batch_legs; target_weights vs current_weights farkından al/sat miktarları |
| plan | plan_id, steps[], step_idx; fill sonrası step_idx++; step_idx >= len(steps) ise plan=None, trb_state=IDLE, trb_cycles_count++ |

## Mevcut — TRDCA: Arbitraj ve Tek Kazanan

| Fonksiyon | arbitrate(snapshot, state, prop_dca, prop_trb) |
|-----------|--------------------------------------------------|
| Girdi | DCA ve TRB proposal'ları (want_action, priority, impact_score, notional_estimate) |
| Çıktı | En fazla bir kazanan; öncelik (DCA 90, TRB 70); want_action False ise elenir; aynı tick'te tek batch |

Kazanan proposal action'ı (batch) state.active_intent olarak kaydedilir; commit_snapshot (commit_quote_total, commit_base_total_by_asset); pending_quote_committed, pending_base_committed güncellenir.

## Mevcut — TRDCA: apply_fills (Fill Sonrası State)

| Kaynak | Güncelleme |
|--------|------------|
| DCA | grid_up_consumed / grid_down_consumed ilgili level_idx True; vwap_sell veya vwap_buy = { price: exec_basket, notional }; armed = NONE |
| TRB | plan.step_idx += 1; step_idx >= len(steps) ise plan=None, trb_state=IDLE, trb_cycles_count += 1; değilse plan güncellenir |
| Ortak | active_intent = None; pending_quote_committed / pending_base_committed fill'e göre düşülür (veya benzeri) |

apply_fills(state, fills, snapshot): fills batch'tan gelen fill listesi; her leg için hangi batch/intent'e ait olduğu eşleştirilir; DCA/TRB state patch uygulanır.

## Mevcut — TRDCA: validate_and_normalize_batch

| Kontrol | Açıklama |
|---------|----------|
| legs boş | INVALID_BATCH_NO_LEGS |
| len(legs) > trb_max_batch_legs | INVALID_BATCH_MAX_LEGS |
| leg qty <= 0 | INVALID_BATCH_LEG_QTY |
| leg için fiyat yok | INVALID_BATCH_NO_PRICE |
| notional < minNotional | INVALID_BATCH_MIN_NOTIONAL |
| stepSize | qty _floor_to_step ile normalize |

Batch intent: kind BATCH_MARKET_ORDERS, source, batch_id, legs[], notional_estimate. normalize sonrası legs[].qty güncellenir.

## Mevcut — Data Health ve price_null_strikes

| Mekanizma | Açıklama |
|-----------|----------|
| price_null_assets | DCA ve TRB patch'lerinde fiyatı olmayan asset seti |
| price_null_strikes | state'te asset → ardışık null sayısı; null değilse 0 |
| strike_limit | config.price_null_strike_limit (varsayılan 10) |
| Aşım | max(strikes) >= strike_limit → SAFE_STOP; last_reason MARKET_DATA_INCOMPLETE |

Fiyat sürekli eksik asset'te strateji güvenli duruşa geçer.

## Mevcut — Config Özeti (Strateji Bazlı)

| Strateji | Ana config alanları |
|----------|----------------------|
| DcaGridTrailingConfig | symbol, initial_capital_usdt, base_alloc_pct, quote_alloc_pct, fee_rate, sell_grids[], buy_grids[], sell_trigger_trailing_pct, buy_trigger_trailing_pct, profit_reentry_drop/rise_pct, profit_exit_rise/drop_pct, basis_mode, pnl_mode, tick_interval_ms, min_notional_guard |
| MultiAssetRebalanceConfig | assets[], rebalance_mode, threshold_pct, interval_sec, min_trade_usdt, budget_usdt, symbol=MULTI |
| TrdcaProConfig | quote_asset, initial_capital_usdt, tick_interval_ms, dca_enabled, dca_coin_weights, dca_grid_up/down_levels_pct, dca_*_notional_usdt, dca_sell_trail_back_pct, dca_buy_trail_up_pct, dca_post_sell_*, dca_post_buy_*, trb_enabled, trb_target_weights_all, trb_gap_arm_pct, trb_trail_back_pct, trb_max_batch_legs, trb_sell_first, trb_step_mode, ack_timeout_sec |

## Geliştirilebilir — DCA Grid

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Grid sayısı üst sınırı | Çok seviye (örn. 50) state ve tick süresini artırır; max_sell_grids, max_buy_grids | Düşük |
| reference_price güncelleme | Sadece self-heal ve IDLE'da; fiyat çok değişince ref güncelleme politikası (ör. günlük) | Düşük |
| target_budgets dokümantasyonu | Bileşik büyüme ile ref_base/ref_quote sınırlama; UI/config şeması | Orta |
| cycle_reset history | sell_history/buy_history temizleme veya son N cycle saklama | Düşük |

## Geliştirilebilir — Multi-Asset Rebalance

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| Tam rebalance mantığı | threshold/interval/hybrid ile hedef ağırlığa göre al/sat planı; tek strateji dosyasında veya execution'da | Yüksek |
| apply_fill | Multi-asset state (per-symbol balance) güncelleme | Orta |
| Min notional / fee buffer | min_trade_usdt, fees_buffer_bps kullanımı plan hesaplamada | Orta |

## Geliştirilebilir — TRDCA

| Öneri | Açıklama | Öncelik |
|-------|----------|---------|
| DCA anchor güncelleme | Spec: "DCA does not mutate anchor"; anchor ilk basket veya ayrı kural (ör. haftalık) | Orta |
| TRB plan adım sayısı | Çok adım (sell + buy çok leg) gecikme; max_steps veya notional bölme | Düşük |
| Partial fill | trb_partial_fill_behavior SAFE_STOP / CONTINUE; bazı leg'ler fill olmazsa state tutarlılığı | Orta |
| price_null_strike_limit yapılandırma | Varsayılan 10; config veya env | Düşük |
| arbitrate öncelik | DCA 90, TRB 70; özelleştirilebilir veya impact_score ile | Düşük |

## Mevcut — Strateji Çağrı Yeri (Orchestrator)

| Strateji | Çağrı |
|----------|--------|
| DCA / Multi | state = load_state; price = adapter.get_price(symbol); base_balance, quote_balance = get_virtual_wallet veya state; strategy = get_strategy_safe(raw); actions, next_wake = strategy.tick(state, cfg, price, base_balance, quote_balance) |
| TRDCA | snapshot = await _build_trdca_snapshot(adapter, state, cfg); next_state, decision = trdca_strategy_tick(snapshot, state, cfg); state.update(next_state); decision.type ACTIONS ise legs → run_actions |

TRDCA'da strategy.tick(state, config, price, base, quote) kullanılmaz; orchestrator doğrudan strategy_tick(snapshot, state, config) çağırır.

## Mevcut — Action Yapısı (DCA)

| Alan | Açıklama |
|------|----------|
| type | "place" |
| side | BUY \| SELL |
| symbol | config.symbol |
| quantity | Base miktar (SELL) |
| quote_qty | Quote miktar (BUY, initial_allocation) |
| client_order_id | _action_id(state, prefix, idx) veya init_{bot_id}_c{cycle} |
| reason | initial_allocation \| trail_sell_grid \| trail_buy_grid \| trail_reentry_buy \| trail_profit_sell |
| grid_index | Grid seviye indeksi (opsiyonel) |
| trigger_price, execution_price, trail_anchor_price | Tetik/gerçekleşme fiyatı (log/UI) |

Execution run_actions bu action'ları alır; adapter.place_market_buy/sell; apply_fill_to_state; cycle_ledger; save_state.

## Mevcut — TRDCA Batch Leg Yapısı

| Alan | Açıklama |
|------|----------|
| symbol | Örn. BTCUSDT |
| side | BUY \| SELL |
| qty | Base miktar (_floor_to_step sonrası) |
| client_order_id | DCA-{batch_id}-{idx}-{sym}-{side} veya TRB plan step'ten |

Orchestrator legs'i trdca_actions listesine çevirir: type=place, side, symbol, quantity, quote_qty (BUY ve fiyat varsa qty*price), client_order_id, reason=trdca_batch. run_actions bu listeyi işler.

## Strateji Mantık Checklist

- [ ] DCA: IDLE → tetik (sell grid / buy grid / reentry / profit exit) → TRAIL_* → action → fill → apply_fill_to_state; cycle_reset_after_fill (trail_profit_sell / trail_reentry_buy)
- [ ] DCA initial_allocation: quote_qty = c_base; ia_done sadece execution'da True
- [ ] DCA basis_mode: grid_only vs total avg_buy; pnl_mode cycle_only_fee_aware_v1 ise cycle_ledger trigger
- [ ] Multi: tick boş action; next_wake = interval_sec
- [ ] TRDCA: strategy_tick snapshot geçitleri; open_order varsa NOOP; active_intent ACK timeout; dca_tick + trb_tick; arbitrate; active_intent set; decision ACTIONS → legs → run_actions
- [ ] TRDCA apply_fills: DCA consumed/vwap; TRB plan step_idx, IDLE dönüş

## Özet — Stratejiler Mevcut vs Geliştirilebilir

| Alan | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| DCA mod | IDLE, TRAIL_SELL_GRID, TRAIL_BUY_GRID, TRAIL_REENTRY_BUY, TRAIL_PROFIT_SELL | Grid üst sınır; ref güncelleme politikası |
| Multi | Boş action; config log | Tam rebalance mantığı; apply_fill |
| TRDCA DCA | anchor, grid up/down, post_sell dip, post_buy peak; legs oransal | Anchor güncelleme kuralı |
| TRDCA TRB | IDLE/TRAIL; gap_arm, trail_back; plan steps SELL_THEN_BUY | Partial fill; max_steps |
| TRDCA data health | price_null_strikes; SAFE_STOP | strike_limit config |
| Arbitraj | DCA 90, TRB 70; tek kazanan | Öncelik/impact özelleştirme |

---

## Mevcut — UI/API → Config Dönüşümü

| Kaynak | Fonksiyon | Çıktı |
|--------|-----------|--------|
| DCA UI payload | config_from_ui_payload(payload) | DcaGridTrailingConfig; symbol, initial_capital_usdt, base_alloc_pct, quote_alloc_pct, sell_grids (pct, trailing_pct, qty_pct), buy_grids, profit_reentry_*, profit_exit_*, basis_mode, pnl_mode, tick_interval_ms |
| TRDCA UI payload | config_trdca_pro_from_payload(payload) | TrdcaProConfig; quote_asset, dca_coin_weights, dca_grid_up/down_levels_pct, dca_*_notional_usdt, dca_sell_trail_back_pct, dca_buy_trail_up_pct, dca_post_sell_dip_*, dca_post_buy_*, trb_target_weights_all, trb_gap_arm_pct, trb_trail_back_pct, trb_max_batch_legs |
| Multi-asset UI payload | config_multi_asset_from_payload(payload) | MultiAssetRebalanceConfig; assets (symbol, target_pct), rebalance_mode, threshold_pct, interval_sec, min_trade_usdt, budget_usdt |

Payload alanları API şeması ile uyumlu; eksik alanlar varsayılan ile doldurulur (models.py).

## Mevcut — Execution Entegrasyonu (DCA)

| Adım | Dosya / fonksiyon | Açıklama |
|------|-------------------|----------|
| 1 | orchestrator | get_strategy_safe(raw_config); strategy.tick(state, config, price, base_balance, quote_balance) |
| 2 | execution.run_actions | actions list; her action type=place, side, symbol, quantity/quote_qty, client_order_id, reason |
| 3 | adapter | place_market_buy(symbol, quote_qty) veya place_market_sell(symbol, quantity) |
| 4 | fill callback | executed_qty, executed_price, fee; strategy.apply_fill(state, side, executed_qty, executed_price, fee, grid_index, reason, execution_price) |
| 5 | execution | apply_fill_to_state (DCA: sell_history/buy_history, base_balance, quote_balance, realized_pnl_usdt_cycle); cycle_ledger_add_fill; cycle_reset_after_fill(close_reason); save_state |

DCA için apply_fill strategy'den çağrılır; state mutasyonu execution tarafında da yapılabilir (apply_fill_to_state); cycle_ledger ve cycle_reset execution/cycle_ledger modülünde.

## Mevcut — Execution Entegrasyonu (TRDCA)

| Adım | Açıklama |
|------|----------|
| 1 | _build_trdca_snapshot | balances_free (tüm coin), prices_last (tüm base), filters (symbol → stepSize, minNotional), open_order (bool), fills (varsa son batch fill'leri) |
| 2 | strategy_tick(snapshot, state, config) | (next_state, decision); state orchestrator'da next_state ile güncellenir |
| 3 | decision.type == ACTIONS | decision.actions[0].legs → her leg { symbol, side, qty }; trdca_actions = [ { type: place, side, symbol, quantity, client_order_id, reason: trdca_batch } ] |
| 4 | run_actions(trdca_actions) | Paralel veya sıralı place_market; fill'ler toplanır |
| 5 | Snapshot.fills | Bir sonraki tick'te snapshot.fills dolu gelir; strategy_tick içinde apply_fills(state, fills, snapshot) çağrılır; DCA/TRB state güncellenir |

TRDCA'da apply_fill(state, ...) tek leg interface'i kullanılmaz; apply_fills(state, fills, snapshot) toplu fill uygular.

## Geliştirilebilir — Strateji Eklenti Dokümantasyonu

| Madde | Açıklama |
|-------|----------|
| Yeni strateji ekleme | strategies/ altında yeni modül; Strategy'dan türet; strategy_id set et; registry'ye import ve register(strategy_cls) veya _ensure_default benzeri listeye ekle |
| Config sınıfı | models.py'de ilgili Config dataclass; config_from_ui_payload veya ayrı config_*_from_payload |
| Orchestrator dalı | strategy_id'ye göre tick vs tick_snapshot; TRDCA ise snapshot build + strategy_tick; DCA/Multi ise price + balance + strategy.tick |
| UI | Bot oluştur/düzenle formunda strategy_id seçimi; stratejiye özel alanlar (conditional form) |

Resmi "Strateji Geliştirici Kılavuzu" dokümanı oluşturulabilir: arayüz sözleşmesi, state şeması, config şeması, test edilebilir mock adapter.

## Geliştirilebilir — Config Şema Versiyonu

| Öneri | Açıklama |
|-------|----------|
| config_schema_version | Her config'te schema_version (örn. 1); eski botlar migrate edilirken version kontrolü |
| Migrate fonksiyonu | config_migrate(config_dict, from_version, to_version) → yeni dict; UI veya worker ilk yüklemede çağırır |
| Validasyon | JSON Schema veya pydantic ile config validate; hatalı alanlarda SAFE_STOP veya uyarı log |

## Geliştirilebilir — Test Edilebilir Strateji Arayüzü

| Öneri | Açıklama |
|-------|----------|
| Deterministik tick | Aynı (state, config, price, base, quote) → aynı (actions, next_wake); fiyat serisi ile regression test |
| Mock adapter | get_price, place_market_* mock; fill'leri senaryoya göre döndür; apply_fill sonrası state assertion |
| TRDCA snapshot test | strategy_tick(snapshot, state, config); decision.type ve actions içeriği assert; apply_fills sonrası state |
| Fixture | Ortak state/config fixture'ları (spec'te veya test klasöründe); E.7 tabloları ile uyumlu |

## Mevcut — DCA State Anahtarları (Özet)

| Anahtar | Tip | Kullanım |
|---------|-----|----------|
| mode | str | IDLE, TRAIL_SELL_GRID, TRAIL_BUY_GRID, TRAIL_REENTRY_BUY, TRAIL_PROFIT_SELL |
| sell_grid_fired, sell_grid_trigger_price, sell_grid_peak_price | list | Her sell grid seviyesi için; TRAIL_SELL_GRID'de anchor ve peak |
| buy_grid_fired, buy_grid_trigger_price, buy_grid_trough_price | list | Her buy grid seviyesi için |
| sell_history, buy_history | list | { grid_index, qty, price, execution_price } dict'leri |
| base_balance, quote_balance | float | Virtual wallet (DCA tek sembol) |
| initial_allocation_done, initial_alloc_base_qty, initial_alloc_price | bool/float | İlk tahsis durumu |
| grid_reference_base, grid_reference_quote, reference_price | float | Bütçe referansı ve tetik fiyatı |
| realized_pnl_usdt_cycle, fees_paid_usdt_cycle | float | Cycle içi PnL ve fee |
| cycle_id | int | Cycle sayacı |

## Mevcut — TRDCA State Anahtarları (Özet)

| Anahtar | Tip | Kullanım |
|---------|-----|----------|
| mode | str | RUNNING, SAFE_STOP, RESUME_PENDING |
| last_tick_ts | int | Son tick ts_ms; duplicate tick engeli |
| last_reason | dict | SAFE_STOP/RESUME_PENDING sebebi |
| quote_asset | str | USDT vb. |
| dca | dict | grid_up_consumed, grid_down_consumed, armed, vwap_sell, vwap_buy, anchor_price? |
| trb | dict | trb_state, gap_peak_pct, plan (steps, step_idx), trb_triggered_at_ts, trb_cycles_count |
| active_intent | dict | source, intent_id, batch_id, legs, commit_snapshot, send_time_ms, status=SENT |
| pending_quote_committed, pending_base_committed | float/dict | Gönderilmiş ama henüz fill edilmemiş notional/base |
| price_null_strikes | dict | asset → ardışık null sayısı |
| arb_last | dict | ts, winner, loser (DCA/TRB) |

## Geliştirilebilir — Strateji Metrikleri

| Metrik | Açıklama |
|--------|----------|
| tick_duration_ms | Her strateji tick süresi; DCA ve TRDCA için ayrı |
| actions_per_tick | Tick başına üretilen action sayısı (DCA genelde 0 veya 1) |
| decision_type_counts | TRDCA: NOOP, ACTIONS, SAFE_STOP, RESUME_PENDING sayıları |
| arbitrate_winner | TRDCA: DCA vs TRB kazanma oranı (log veya metrik) |

Prometheus/StatsD veya mevcut metrik altyapısına eklenebilir.

## Geliştirilebilir — TRDCA Partial Fill ve Retry

| Senaryo | Mevcut | Geliştirilebilir |
|---------|--------|------------------|
| Batch'tan bazı leg'ler fill, bazıları timeout | active_intent ACK timeout → SAFE_STOP | trb_partial_fill_behavior: CONTINUE ile kalan leg'leri iptal veya tekrar dene; state'te hangi leg'lerin fill olduğu |
| Kısmi fill state tutarlılığı | pending_quote_committed tüm batch notional | Fill olan leg'lerin notional'ı düş; active_intent.legs_filled[] |
| Retry policy | Yok | Belirli hata kodları için (RATE_LIMIT, CONNECTIVITY) otomatik RESUME_PENDING ve retry |

## Mevcut — Kod Yolu Özeti (Dosya : Fonksiyon)

| Strateji / davranış | Dosya | Fonksiyon / sınıf |
|--------------------|--------|---------------------|
| Strategy ABC | app/botengine/strategies/base.py | Strategy; tick, apply_fill |
| Registry | app/botengine/strategies/registry.py | register, get_strategy, get_strategy_safe, _ensure_default |
| DCA tick | app/botengine/strategies/dca_grid_trailing.py | tick_dca_grid_trailing; _ensure_sell_buy_lists, _sell_qty_for_grid, _buy_qty_for_grid, _reentry_buy_qty, _profit_exit_sell_qty |
| DCA apply_fill | app/botengine/strategies/dca_grid_trailing.py | DcaGridTrailingStrategy.apply_fill → apply_fill_to_state |
| Multi tick | app/botengine/strategies/multi_asset_rebalance.py | MultiAssetRebalanceStrategy.tick |
| TRDCA strategy_tick | app/botengine/strategies/trdca_pro.py | strategy_tick; dca_tick, trb_tick, arbitrate, validate_and_normalize_batch, apply_fills |
| TRDCA sınıf | app/botengine/strategies/trdca_pro.py | TrdcaProStrategy; tick_snapshot, apply_fills_snapshot |
| DCA config | app/botengine/models.py | DcaGridTrailingConfig, config_from_ui_payload |
| TRDCA config | app/botengine/models.py | TrdcaProConfig, config_trdca_pro_from_payload |
| Multi config | app/botengine/models.py | MultiAssetRebalanceConfig, config_multi_asset_from_payload |
| Cycle reset | app/botengine/ (execution/cycle_ledger) | cycle_reset_after_fill, get_cycle_type_and_base_delta |

Orchestrator ve execution yolları E.6'da; bu tablo sadece strateji ve config katmanına odaklanır.

## Geliştirilebilir — Öncelik Sırası ve Roadmap

| Öncelik | Öğe | Hedef |
|---------|-----|--------|
| Yüksek | Multi-asset tam rebalance | threshold/interval/hybrid ile hedef ağırlık hesaplama; al/sat planı; min_trade_usdt, fees_buffer_bps; apply_fill ile state |
| Orta | TRDCA partial fill | Bazı leg'ler fill olmazsa state ve pending_* tutarlılığı; CONTINUE vs SAFE_STOP seçeneği |
| Orta | DCA target_budgets | Ref_base/ref_quote büyüme sınırı; UI ve config şeması dokümantasyonu |
| Orta | Config schema_version | config_schema_version alanı; migrate(config, from_v, to_v); validasyon |
| Düşük | DCA grid üst sınır | max_sell_grids, max_buy_grids; performans |
| Düşük | TRDCA anchor güncelleme | Periyodik veya kural bazlı anchor güncelleme (spec ile uyumlu) |
| Düşük | Strateji metrikleri | tick_duration_ms, decision_type_counts, arbitrate_winner |
| Düşük | Strateji geliştirici kılavuzu | Resmi doc: arayüz, state, config, mock adapter, test |

## Mevcut — Tetik Formülleri (DCA, Özet)

| Tetik | Koşul (fiyat P, referans ref) |
|-------|-------------------------------|
| Sell grid i | P >= ref * (1 + sell_grid_pct_i/100) → TRAIL_SELL_GRID; action: P <= anchor * (1 - sell_trigger_trailing_pct/100) |
| Buy grid j | P <= ref * (1 - buy_grid_pct_j/100) → TRAIL_BUY_GRID; action: P >= anchor * (1 + buy_trigger_trailing_pct/100) |
| Reentry | P <= avg_sell * (1 - profit_reentry_drop_pct/100) → TRAIL_REENTRY_BUY; action: P >= trough * (1 + profit_reentry_rise_pct/100) |
| Profit exit | trigger = cycle_ledger_trigger (fee-aware) veya avg_buy * (1 + profit_exit_rise_pct/100); P >= trigger → SELL |

Trough/peak mevcut modda güncellenir; anchor sell grid'de güncel fiyat, buy grid'de min.

## Mevcut — TRDCA Basket Fiyatı

| Alan | Hesaplama |
|------|-----------|
| basket | Ağırlıklı ortalama: sum(price[base] * weight[base]) / sum(weight); weight = dca_coin_weights veya trb hedefleri; fiyat yoksa asset price_null_assets'a eklenir |
| Kullanım | DCA: anchor ile karşılaştırma (grid up/down, trail); TRB'de doğrudan kullanılmaz, bakiye ağırlıkları kullanılır |

Basket tek bir "sepet" fiyatı; çoklu coin için tek sayısal tetik karşılaştırması sağlar.

## Geliştirilebilir — Strateji Eklenti API (Özet)

Yeni strateji eklemek için: (1) Strategy alt sınıfı, strategy_id; (2) tick veya tick_snapshot implementasyonu; (3) apply_fill veya apply_fills_snapshot; (4) registry'ye kayıt; (5) models'da Config ve config_*_from_payload; (6) orchestrator'da strategy_id dalı; (7) UI'da strateji seçimi ve alanları. Eklenti yükleme (dynamic import) şu an yok; tüm stratejiler kod tabanında.

## Bölüm Sonu Notu — E.7

SECTION E.7, bot stratejilerinin mevcut mantığını ve uygulamasını (base arayüz, registry, DCA grid trailing, multi-asset rebalance, TRDCA PRO) ve geliştirilebilir noktaları (DCA grid sınırları, multi-asset tam rebalance, TRDCA anchor/partial fill/arbitraj, config versiyon, test arayüzü, metrikler) tek yerde toplar. Yaklaşık 500 satır.

---

## Per-Component Latency Ranges (ms)

| Component | P50 | P95 | P99 |
|-----------|-----|-----|-----|
| DB single query | 5 | 20 | 50 |
| Binance public GET | 100 | 300 | 500 |
| Binance signed GET | 150 | 400 | 600 |
| DataHub get_all_prices | 1 | 5 | 10 |
| JSON parse 100KB | 5 | 15 | 30 |
| DOM update 50 elements | 10 | 40 | 80 |

**UNKNOWN:** Exact percentiles. **HOW TO MEASURE:** APM; browser Performance API.

## Snapshot Latency Equation (Expanded)

```
TotalSnapshot = 
  RTT_client_server +
  TLS_handshake (if new conn) +
  Server_queue_wait +
  max(
    fetch_prices_latency,      # DataHub sync; executor
    fetch_wallet_latency,      # Binance GET /api/v3/account
    fetch_bots_latency,        # DB queries
    fetch_pnl_latency          # DB + calculations
  ) +
  merge_overhead +
  JSON_serialize +
  RTT_server_client +
  TLS_overhead +
  JSON_parse +
  DOM_update
```

## Mobile 3G Bandwidth Model

- Downlink: 100–200 kbps typical
- 200KB payload: 200×8/100 = 16 seconds (worst)
- 100KB payload: 8 seconds
- **Conclusion:** 200KB+ snapshot on 3G likely exceeds 12s timeout.

---

# SECTION F — BINANCE RATE & WEIGHT MODEL

## Weight Accounting Table

| Endpoint | Weight | Caller | Freq |
|----------|--------|--------|------|
| ticker/price (bulk) | 2 | DataHub | 1/10s |
| ticker/24hr | 1–40 | DataHub | 1/5s |
| exchangeInfo | 10 | DataHub | 1/600s |
| account | 10 | Snapshot | 1/(3s × users) |
| order | 1 | Worker | On trade |
| time | 1 | Signed | Per signed call |

## Simulated Scenarios

### 10 Users Refreshing at Same Time

- 10 snapshots × 1 account call = 10 × 10 = 100 weight
- Over ~3s window
- Binance limit: 1200 weight/min (UNKNOWN exact)
- **Risk:** May approach limit

### Worker Trading + Snapshot

- Worker: 1–2 order calls
- Snapshot: 1 account per user
- **Risk:** Low unless many users

### WS Reconnect Storm

- WS reconnect: no REST weight
- DataHub REST continues: 2 weight/10s for ticker/price
- **Risk:** Low

### Circuit Breaker Oscillation

- Open 30s → no calls
- Half-open: 1 probe
- Close: full traffic resumes
- **Risk:** Thundering herd on close

## Weight Per Minute Budget

**UNKNOWN:** Exact Binance limit. Typical: 1200 weight/min (IP), 20 orders/10s.

**HOW TO MEASURE:** Binance 429 response; weight header if present.

**RISK IF IGNORED:** 429 → circuit open → 30s no fresh data.

## Global Weight Per Minute (Hesaplama)

Gerçek dakika bazlı toplam hesap için referans; detay ve worst-case simülasyonu **SECTION O §1** (Critical Gaps).

| Bileşen | Weight/çağrı | Dakikada (örnek) |
|---------|--------------|------------------|
| DataHub (ticker/price 1/10s) | 2 | 12 |
| DataHub (ticker/24hr 1/5s) | 1–40 | 120–480 |
| Snapshot account (N user, 1/3s) | 10 | 200×N |
| Worker order | 1 | Trade sayısına bağlı |

**Worst-case:** N=10 kullanıcı, her 3s snapshot → sadece account 2000 weight/min. DataHub eklenince 1200 limit aşılabilir. **Geliştirilebilir:** Her Binance çağrısında weight toplama; dakika penceresinde limit aşımında backoff veya 429 öncesi throttle.

## Account-Level vs IP-Level Rate Risk

- **IP-level:** Binance limits by IP (e.g. 1200 weight/min). All accounts behind same IP share limit.
- **Account-level:** Order limits (20/10s). Per API key.
- **Snapshot:** Uses account endpoint per user; each snapshot = 10 weight. 10 users × 1/3s = 100 weight/3s = 2000 weight/min potential.
- **Risk:** Multi-tenant deployment behind single IP may hit IP limit.

## Failure Cascade Prevention Matrix

| Scenario | Old Behavior | Current | Remaining Risk |
|----------|--------------|---------|----------------|
| 429 once | Retry 2× | Retry 2×, 4s cap | — |
| 429 × 3 | Continuous retry | Circuit open 30s | 30s no data |
| Timeout | Long block | 4s cap | DependencyFailure |
| Per-symbol ticker | N calls | RuntimeError guard | None |
| Circuit oscillation | — | 30s open, 1 probe | Thundering herd on close |

---

# SECTION G — MOBILE FAILURE LAB

## 3G Network

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| RTT 300–500ms | Snapshot latency increases | Increase timeout (e.g. 20s); reduce payload |
| Throughput 100–200kbps | 200KB payload = 8–16s download | Stream; compress; reduce prices count |

## 500ms RTT

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| Each request +500ms | 4 tasks × 500ms = 2s extra | Parallel gather (already) |
| TLS handshake | +500ms | Keep connection alive |

## 30% Packet Loss

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| HTTP retries | Timeout more likely | Client retry with backoff |
| Fetch fails | inFlight stuck if not in finally | Ensure finally { inFlight=false } |

## Tab Backgrounded

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| visibilityState hidden | intervalRegistry skips tick | By design; saves battery |
| Timer throttling | 3s may become 10s | Accept; user returns to foreground |

## CPU Throttled

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| Main thread slow | DOM update delayed; fetch slow | Reduce DOM work; Web Worker (not implemented) |

## Battery Saver Mode

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| Background timers throttled | 3s interval may become 30s | Accept; user returns to foreground |
| Network coalescing | Requests delayed | Accept |

## Small Viewport / Zoom

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| More scroll, smaller touch targets | UX degradation | Responsive design |
| Same payload size | Same download time | — |

## Intermittent Connectivity (Flaky 3G)

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| Request starts, connection drops | Timeout or partial response | Retry with backoff; ensure finally block |
| inFlight stuck if no finally | Next poll never runs | Ensure State.inFlight=false in finally |

## Safari / WebKit Specifics

| What happens | What breaks | Mitigation |
|--------------|-------------|------------|
| Intelligent Tracking Prevention | Cookies may be blocked | Bearer token fallback |
| Background tab throttling | Aggressive | visibilityState skip is correct |

---

# SECTION H — SECURITY DAMAGE MODEL

## Max Capital Loss Per Account

- **Formula:** Sum of (free + locked) for all assets in Binance spot
- **Typical:** User's spot balance
- **Cap:** No margin/futures in system

## Max Capital Loss System-Wide

- **Formula:** Sum over all accounts
- **Trigger:** All API keys compromised

## Session Hijack Impact Window

- **Until:** User logs out, or server restart (boot_id)
- **Actions:** Start/stop bots; view data; no direct order (Worker uses DB keys)

## API Key Leak Blast Radius

- **Single account:** Full wallet
- **All accounts:** Sum of all wallets
- **Mitigation:** Rotate keys; revoke in Binance

## Admin Takeover Scenario

- Admin can: suspend user; revoke device; view audit; server exit
- Admin cannot: trade on user's behalf (Worker uses account keys from DB)

## Emergency Shutdown (Step-by-Step CLI)

```bash
# 1. Stop worker (no new orders)
kill $(cat .run/worker.pid)

# 2. Stop web (no new requests)
kill $(cat .run/web.pid)

# 3. Revoke API keys in Binance UI (manual)

# 4. If BREACH_SHUTDOWN=1, only whitelist IPs can reach
export BREACH_SHUTDOWN=1
# Restart web with lockdown
```

## Damage Quantification (Explicit)

| Scenario | Max USD Loss | Formula |
|----------|--------------|---------|
| Single account API key leak | account_spot_balance | Sum free+locked for all assets |
| Session hijack | 0 (no direct trade) | UI actions only; Worker uses DB keys |
| Admin takeover | 0 (no trade) | Admin cannot place orders as user |
| All accounts compromised | sum(all account balances) | Sum over accounts |
| DB exfiltrated | Same as API key (keys in DB) | Decrypt with BINANCE_MASTER_KEY |

## Blast Radius Matrix

| Compromise | Affected | Actions Possible |
|------------|----------|------------------|
| Session token | 1 user | Start/stop bots; view data |
| API key (1 account) | 1 account | Trade; read wallet |
| API key (all) | All accounts | Trade all; read all |
| BINANCE_MASTER_KEY | All accounts | Decrypt all keys; full access |
| DB file | All data | Decrypt if master key known |

---

# SECTION I — DEPLOYMENT MATRIX

| Configuration | Safe? | Unsafe? | Required Config |
|---------------|-------|---------|-----------------|
| Single node | Yes | — | — |
| Low RAM VPS (1GB) | Unknown | Possible OOM | Monitor DataHub size |
| Cloudflare fronted | Yes | If proxy timeout <12s | proxy_read_timeout 15s |
| Nginx fronted | Yes | Same | proxy_read_timeout 15s |
| Dockerized | Yes | — | DATABASE_URL for volume |
| Multiple web workers (2) | Yes | Cache split | Accept first-hit empty |
| Horizontal worker scaling | No | Double trading risk | Symbol lock + single writer |
| Single worker, 2 web workers | Yes | Cache split | Accept |
| 4 web workers | Unknown | 4 DataHubs; 4× Binance REST | Monitor weight |
| SQLite on NFS | No | Lock issues | Use local disk |
| PostgreSQL (if migrated) | Unknown | Different lock semantics | PG_STATEMENT_TIMEOUT |
| Docker + volume for DB | Yes | — | DATABASE_URL path |
| Kubernetes | Unknown | Multi-pod; session locality | Sticky session; single worker |

---

# SECTION J — TESTABILITY & MONITORING

## Metrics to Expose

| Metric | Type | Threshold | Alert | Meaning |
|--------|------|-----------|-------|---------|
| snapshot_latency_ms | gauge | >5000 | Warn | Snapshot slow |
| binance_calls_total | counter | — | — | Load |
| stale_symbols_count | gauge | >100 | Warn | DataHub stale |
| circuit_breaker_state | label | open | Critical | Binance failing |
| worker_active_bots | gauge | 0 when expected >0 | Warn | Worker not processing |

## Synthetic Load Script Example

```bash
#!/bin/bash
# Simple snapshot load test
TOKEN="your_bearer_token"
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{time_total}\n" \
    -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:8000/api/dashboard/snapshot?account_id=1" &
done
wait
```

## Verification Script — Health Check

```bash
#!/bin/bash
# Verify system health
echo "Health:"
curl -s http://127.0.0.1:8000/api/health | jq .

echo "DataHub status:"
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/datahub/status | jq .

echo "Snapshot latency (single):"
time curl -s -o /dev/null -w "%{time_total}" \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/dashboard/snapshot?account_id=1"
```

## Verification Script — DB Integrity

```bash
#!/bin/bash
# SQLite integrity
sqlite3 ~/.trader/dca.db "PRAGMA integrity_check;"
sqlite3 ~/.trader/dca.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 ~/.trader/dca.db "SELECT COUNT(*) FROM symbol_locks WHERE owner_bot_id != 0;"
```

## Chaos Test Ideas

- Kill worker mid-tick: verify lock expiry; no duplicate order (if idempotency)
- Block Binance (iptables): verify circuit breaker opens
- Fill disk: verify DB write fails; graceful degradation
- Reduce RAM (stress-ng): verify DataHub eviction; no OOM
- Corrupt 1 byte in DB file: verify integrity_check fails
- Restart web during snapshot: verify client gets error; no half-state

## False Positive Alert Cases

| Alert | False Positive When |
|-------|---------------------|
| snapshot_latency > 5s | Single slow request; transient |
| circuit_breaker open | Brief Binance hiccup; recovers in 30s |
| stale_symbols_count > 100 | WS down; REST catching up |
| worker_active_bots = 0 | No bots running; expected |

## Incident Diagnosis Decision Tree

```
User reports: "Nothing loads" / "Broken" / "Slow"
  │
  ├─ Mobile only?
  │   ├─ Yes → Check: network (3G?), visibilityState (tab backgrounded?), payload size
  │   └─ No → Continue
  │
  ├─ Snapshot timeout?
  │   ├─ Yes → Check: SNAPSHOT_LATENCY, circuit breaker, Binance 429, DB
  │   └─ No → Continue
  │
  ├─ Bot not trading?
  │   ├─ Yes → Check: bot status, price stale, lock busy, account keys
  │   └─ No → Continue
  │
  ├─ Login fails?
  │   ├─ Yes → Check: boot_id, session, banned IP
  │   └─ No → Continue
  │
  └─ 5xx from server?
      ├─ Yes → Check: logs, circuit breaker, DB lock
      └─ No → Check: network, client-side JS
```

## Log Fields for Postmortem

| Field | Source | Purpose |
|-------|--------|---------|
| request_id | Request state | Correlate across logs |
| bot_id | Worker | Correlate bot events |
| account_id | Context | Correlate account |
| SNAPSHOT_LATENCY | routes.py | Snapshot duration |
| path | Binance logs | Endpoint |
| error_id | Exception handler | Link to error log |
| ts / created_at | Log/DB | Timeline |

---

# SECTION K — ABSOLUTE NON-REGRESSION CONTRACT

## Must Never Change

- Bot never trades on stale price (get_price returns None when stale)
- Only Worker places orders
- No per-symbol ticker/price REST
- symbol_locks before order
- PRICE_TTL 120; DEFAULT_LEASE_TTL_SEC 60
- DataHub single bulk price source (no N× REST)
- Snapshot: 4 tasks, 3s each, asyncio.gather
- apiClient: MAX_CONCURRENT_REQUESTS 2
- intervalRegistry: visibilityState hidden skips tick
- Session: boot_id check on require_auth
- Circuit breaker: 3 failures, 30s open
- Binance: 4s total timeout, 2 retries

## Can Change

- Snapshot fields (add optional)
- UI timeout values (with testing)
- Log format (add fields)
- Circuit breaker constants (with analysis)

## Dangerous Refactors

- Moving place_order to Web
- Removing symbol lock
- Adding per-symbol Binance calls
- Changing DataHub eviction without testing
- Removing PRICE_TTL check in get_price_with_meta
- Making snapshot tasks sequential
- Increasing MAX_CONCURRENT_REQUESTS above 2 without load test
- Removing circuit breaker
- Removing boot_id from session check
- Adding blocking sync call in async handler without run_in_executor

## Dangerous Code Patterns (Forbidden)

| Pattern | Why Forbidden | Location to Check |
|---------|---------------|-------------------|
| ticker/price?symbol=X | N calls for N symbols | binance_spot _guard |
| setInterval directly | Leak; no visibility handling | intervalRegistry |
| await in loop for same service | Serial latency | gather instead |
| No timeout on external call | Request pile-up | asyncio.wait_for |
| State mutation without lock | Race | symbol_locks |
| Logging API secret | Security | No secret in log |
| Long DB transaction | Lock contention | Keep short |
| Unbounded list in snapshot | Payload explosion | Bounded only |

## Safe Refactors

- Adding optional snapshot field
- Adjusting timeout constants
- Adding log fields
- New env var with default

## Automated Checks Recommended

- Grep for ticker/price?symbol
- Lint for setInterval outside intervalRegistry
- Integration test: snapshot < 5s
- Unit test: stale price → None

---

# SECTION L — FUTURE SCALING STRATEGY

## DataHub → Redis

- Replace in-memory prices with Redis hash
- Key: `datahub:prices`; field: symbol; value: JSON
- TTL per symbol or global refresh
- **Requires:** Redis; connection pool; serialization

## Horizontal Worker Scaling

- **Problem:** Two workers could both process same bot
- **Solution:** Single-writer via distributed lock (Redis) or queue (Celery)
- **Alternative:** Shard by account_id; one worker per account set
- **Must change:** bot_engine_commands processing; symbol_locks (already DB; OK)

## Avoiding Double Trading in Distributed Mode

- client_order_id idempotency (Binance)
- Partition by (account_id, symbol) to single worker
- Or: leader election; one worker holds "active" per bot

## What Must Change Before Scaling

- Add client_order_id to all place_order calls
- Distributed lock or queue for command processing
- Shared DataHub or Redis cache
- Monitoring and alerting

## Scaling Readiness Checklist

- [ ] client_order_id idempotency implemented
- [ ] Redis or shared cache for DataHub
- [ ] Command queue (Celery/RQ) or distributed lock
- [ ] Partition strategy (account_id or symbol)
- [ ] Load balancer sticky session for Web (session locality)
- [ ] Centralized logging with request_id propagation
- [ ] Metrics: snapshot_latency, circuit_state, worker_active_bots

## Distributed Worker Design (Proposal)

```
                    ┌─────────────────┐
                    │  Redis / Queue  │
                    │  bot_commands   │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────▼────┐          ┌────▼────┐          ┌────▼────┐
   │Worker A │          │Worker B │          │Worker C │
   │acct 1-10│          │acct 11-20│         │acct 21+ │
   └────┬────┘          └────┬────┘          └────┬────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  SQLite / PG    │
                    │  symbol_locks   │
                    │  bot_engine_*   │
                    └─────────────────┘
```

- Partition by account_id mod N
- Or: single leader; others standby
- symbol_locks already DB; works across workers

---

# SECTION M — SYSTEM LIMITS

| Limit | Value | Enforced? |
|-------|-------|-----------|
| Max bots per account | UNKNOWN | No |
| Max symbols cached (DataHub) | 600 | Yes (_MAX_PRICES) |
| Max snapshot size | UNKNOWN | No |
| Max DB size before migration | UNKNOWN | No |
| Max acceptable snapshot latency | 12000 ms (UI) | Yes (timeout) |
| MAX_CONCURRENT_REQUESTS (UI) | 2 | Yes |
| SNAPSHOT_POLL_MS | 5000 | Yes |
| DEFAULT_LEASE_TTL_SEC | 60 | Yes |

## Hard Limits — Not Enforced (Recommend)

| Limit | Recommended | Enforcement |
|-------|-------------|-------------|
| Max snapshot payload | 500 KB | Add middleware; **SECTION O §2** (payload > 500KB davranışı, compression) |
| Max bots per account | 50 | Add check on create |
| Max trades query | 1000 | Add LIMIT |
| Max DB file size | 1 GB | Monitor; migrate |

## Resource Ceiling (Degradation Thresholds)

Sistem sınırları; aşımda degradation veya migration gerekir. Detay ve "kör nokta" bağlamı **SECTION O §5**.

| Metrik | Değer (öneri/tanım) | Enforcement |
|--------|----------------------|-------------|
| Max bot count before degradation | 50 (öneri) | Create bot'ta kontrol önerilir |
| Max snapshot RPS (per process) | 20 (öneri) | Yok |
| Max DB rows before migration | 1M (öneri) | Monitor; partition/archive |
| Max concurrent users (snapshot) | 20 (öneri) | Yok |
| Max snapshot payload (bytes) | 500_000 | Middleware ile eklenebilir |

## Absolute Max Values (Documented)

| Value | Meaning |
|-------|---------|
| 600 | Max symbols in DataHub prices |
| 600 | Max symbols in DataHub _mini_ws |
| 50 | Max account_balances cached |
| 2 | Max concurrent HTTP (UI) |
| 3 | Max Binance attempts (1 + 2 retries) |
| 60 | Lock lease TTL seconds |
| 120 | Price TTL seconds |

---

# SECTION O — CRITICAL GAPS (KÖR NOKTALAR) & PRODUCTION READINESS

Bu bölüm, dokümanın "System Brain" seviyesinde olmasına rağmen **çözümlenmemiş 5 kritik kör noktayı** ve "kör nokta sıfır" hedefi için gerekenleri net şekilde tanımlar.

## Doküman Gerçek Seviyesi (Özet)

| Alan | Seviye | Not |
|------|--------|-----|
| Mimari derinlik | 9.5/10 | Mimari, runtime, DB, concurrency biliniyor |
| Failure modeling | 9/10 | Failure mapping, incident playbook var |
| Performans bilimi | 8.5/10 | RAM/CPU tahminleri, latency model var |
| Finansal güvenlik | 7.5/10 | Duplicate order riski yazılmış; **garanti yok** |
| Üretim hazırlığı | 8/10 | Single-node production-ready, incident-debuggable |
| Ölçeklenebilirlik | 7/10 | Horizontal scaling ön hazırlık net değil |

**Genel:** 9/10 Single-Node Production Dossier.

**Sistem şu an:** ✔ Single-node production-ready, incident-debuggable, observability-aware, risk-aware. ❌ Banka seviyesi idempotent değil; distributed-safe değil; rate-limit proof değil.

---

## 1️⃣ Gerçek Binance Weight Accounting Yok

**Mevcut:** Endpoint weight listesi var (SECTION F). **Eksik:** Global dakika bazlı toplam hesap ve worst-case eş zamanlı snapshot simülasyonu.

**Risk:** 10 kullanıcı + worker aynı anda → 429 cascade mümkün.

### Eklenen: Weight / Dakika Hesap Tablosu

| Kaynak | Çağrı | Weight/çağrı | Dakikada max (tek IP) | Not |
|--------|--------|--------------|------------------------|-----|
| DataHub ticker/price (bulk) | 1/10s | 2 | 12 | Per process |
| DataHub ticker/24hr | 1/5s | 1–40 | 120–480 | Per process |
| DataHub exchangeInfo | 1/600s | 10 | 1 | Per process |
| Snapshot account | 1/(3s × N_user) | 10 | 10 × (60/3) × N = 200×N | N = eşzamanlı refresh yapan kullanıcı |
| Worker order | On trade | 1 | Değişken | Per bot |
| time (signed) | Per signed call | 1 | Çağrı sayısına bağlı | — |

**Toplam (dakika) örnek:** 1 DataHub + 10 kullanıcı (her 3s refresh): 12 + (200×10) = **2012 weight/min**. Binance tipik IP limiti 1200 weight/min ise **aşım**.

### Worst-Case Eş Zamanlı Snapshot Simülasyonu

| N kullanıcı | Snapshot sıklığı | Account çağrı/dakika | Sadece account weight/dakika |
|-------------|------------------|----------------------|------------------------------|
| 1 | 3s | 20 | 200 |
| 5 | 3s | 100 | 1000 |
| 10 | 3s | 200 | 2000 |
| 20 | 3s | 400 | 4000 |

DataHub + Worker + diğer çağrılar eklenince limit aşımı daha erken. **Eksik (geliştirilebilir):** Gerçek weight/minute aggregation (her Binance çağrısında weight toplanıp dakika penceresinde kontrol); 429 öncesi backoff.

---

## 2️⃣ Snapshot Payload Limit Tanımlı Değil

**Mevcut:** Payload tahmini 60–200 KB (SECTION E, Mobile). **Eksik:** Max allowed size (hard limit); 500KB+ davranışı; JSON compression; reverse proxy timeout.

**Risk:** Mobilde büyük payload → timeout, sayfa açılmaz.

### Eklenen: Snapshot Payload Hard Cap ve Davranış

| Öğe | Mevcut | Önerilen / Geliştirilebilir |
|-----|--------|-----------------------------|
| Max allowed size | UNKNOWN (enforced yok) | **500 KB** hard cap (middleware veya response build'de kontrol) |
| Payload > 500 KB olursa | — | 413 Payload Too Large veya 200 + partial data + `_payload_truncated: true`; UI'da uyarı |
| JSON compression | Yok | Brotli/gzip response (Accept-Encoding); mobilde 200KB → ~50KB |
| Reverse proxy timeout | Dokümanda yok | Nginx/proxy read_timeout ≥ 20s; 12s UI timeout ile uyumlu |
| Mevcut UI timeout | 12s | 3G'de 200KB+ ile 16s+ olabilir; payload küçültme veya timeout artışı |

**Geliştirilebilir:** Middleware: `Content-Length` veya serialize sonrası byte size; limit aşımında truncate (örn. son N bot kaldır) veya 413; compression backend'de etkinleştir.

---

## 3️⃣ Order Idempotency — Açık Garanti İfadesi

**Mevcut:** Doküman "duplicate possible" kabul ediyor (SECTION N). **Eksik:** "This system guarantees no duplicate financial event" veya tersi net cümle.

### Açık İfade (Finansal Garanti)

| İfade | Değer |
|-------|--------|
| **v4.1: Bu sistem duplicate financial event (örn. duplicate order) olmayacağını garanti eder.** | order_intents + deterministic clientOrderId + Binance get_order_by_client_order_id before place + reconciliation. |
| Banka seviyesi idempotent | v4.1 ile Evet (intent persist, check-before-place, same clientOrderId on retry). |
| Çözüm (v4.1 implemented) | order_intents tablosu; build_intent_id, upsert_intent; place_order öncesi get_order_by_client_order_id; FILLED ise reconcile; aynı client_order_id retry'da kullanılır. |

Bu tablo SECTION N Self-Audit ile uyumludur; finansal sistem değerlendirmesinde referans alınmalıdır.

---

## 4️⃣ Horizontal Scaling Ön Hazırlık Net Değil

**Mevcut:** "Two workers = two DataHub" riski yazılmış (SECTION L). **Eksik:** Redis migration path (adım adım); distributed lock design; worker sharding modeli.

### Geliştirilebilir: Distributed-Ready Design Appendix (Özet)

| Konu | Mevcut | Geliştirilebilir |
|------|--------|------------------|
| **Redis migration path** | Yok | 1) Redis instance ekle; 2) symbol_locks ve/veya bot_engine_state için Redis backend (lease, state cache); 3) DB'den Redis'e geçiş script; 4) config: LOCK_BACKEND=redis, REDIS_URL=...; 5) rollout: önce tek worker Redis, sonra tüm worker'lar |
| **Distributed lock design** | DB symbol_locks (tek node) | Redis SET NX EX; lock_key = account_id:symbol; value = worker_id:lease_id; TTL = 60s; extend (heartbeat) ile süre uzatma; crash'te TTL ile serbest kalır |
| **Worker sharding** | Yok | account_id % N ile worker atama; veya symbol hash; tek bir worker belirli bot setinden sorumlu; coordinator (Redis/DB) "assigned_worker" ile yönlendirme |
| **DataHub multi-worker** | Her worker kendi DataHub | Paylaşılan cache: Redis ile fiyat cache; veya tek "price service" worker; diğer worker'lar HTTP ile fiyat alır |

Büyüme sınırı: horizontal scaling olmadan tek node'da max kullanıcı/bot sayısı SECTION M resource ceiling ile sınırlıdır.

---

## 5️⃣ Resource Ceiling Tanımlı Değil

**Mevcut:** SECTION M'de bazı limitler UNKNOWN. **Eksik:** Max bot count before degradation; max snapshot RPS; max DB rows before migration; max concurrent users.

### Eklenen: Resource Ceiling (Degradation Thresholds)

| Metrik | Değer (tanımlı/öneri) | Enforcement | Not |
|--------|------------------------|-------------|-----|
| **Max bot count (before degradation)** | **50** (öneri) veya UNKNOWN | Öneri: create bot'ta kontrol | 50+ bot ile tick/DB yükü artar; ölçüm gerekir |
| **Max snapshot RPS (per process)** | **20** (öneri) veya UNKNOWN | Yok | Her snapshot ~10 weight + DB; 20 RPS = 200 weight/3s = 4000 weight/min tek başına |
| **Max DB rows (before migration)** | **1M** (öneri) veya UNKNOWN | Yok; monitor | trades/audit tabloları büyür; 1M+ için partition/archive veya PostgreSQL migration |
| **Max concurrent users (same snapshot endpoint)** | **20** (öneri) veya UNKNOWN | Yok | Weight ve DB concurrency; 20×200 = 4000 weight/min |
| **Max snapshot payload (bytes)** | **500_000** (öneri) | Middleware ile eklenebilir | Yukarıda (2️⃣) |

**Sistem sınırlarını bilmeden production risk analizi eksik kalır.** Bu tablo, "max X'ten sonra degradation beklenir" veya "UNKNOWN, şu metrikle ölçülecek" şeklinde güncellenebilir.

---

## "Kör Nokta Sıfır" İçin Gerekli Parçalar

| # | Parça | Durum | Nerede |
|---|--------|--------|--------|
| 1 | **Hard idempotency guarantee** | Eksik | client_order_id persist + Binance idempotent retry; SECTION O §3, SECTION N |
| 2 | **Weight budget simulation engine** | Kısmen | Weight/dakika tablosu ve worst-case simülasyonu SECTION F ve SECTION O §1; canlı aggregation yok |
| 3 | **Resource ceiling definition** | Eklendi | SECTION O §5, SECTION M |
| 4 | **Snapshot payload hard cap** | Tanımlandı | SECTION O §2; middleware ile enforce edilebilir |
| 5 | **Distributed-ready design appendix** | Özet eklendi | SECTION O §4; Redis path, distributed lock, worker sharding |

---

## Bölüm Sonu Notu — O

SECTION O, beş kritik kör noktayı (Binance weight accounting, snapshot payload limit, order idempotency garantisi, horizontal scaling ön hazırlık, resource ceiling) ve "kör nokta sıfır" hedefi için gerekenleri açıkça dokümante eder. Bu bölüm ile doküman "hâlâ %100 kör noktasız değil" iddiası ve hedef netleştirilmiş olur.

---

# SECTION P — DISTRIBUTED MODE BLUEPRINT

Step-by-step migration path for horizontal scaling. No code; design only.

## Shared DataHub Cache (Redis)

| Adım | Açıklama |
|------|----------|
| 1 | Redis instance ekle; REDIS_URL env |
| 2 | DataHub: prices, mini, coin_list → Redis keys (TTL 120s) |
| 3 | Worker'lar Redis'ten read; tek "price refresh" worker veya her worker yazabilir (last-write-wins) |
| 4 | Web snapshot: Redis'ten prices çek (DataHub yerine) |
| 5 | Fallback: Redis down → REST Binance bulk ticker/price |

## Distributed Locks (Redis Redlock / DB Advisory)

| Adım | Açıklama |
|------|----------|
| 1 | LOCK_BACKEND=redis; REDIS_URL |
| 2 | Lock key: `lock:account:{account_id}:symbol:{symbol}` |
| 3 | Redis SET NX EX 10; value = worker_id:lease_id |
| 4 | Heartbeat: SET key value EX 10 (aynı worker; extend) |
| 5 | Trade arbiter: Tek worker (shard) belirli (account_id, symbol) için trade yetkisi |
| 6 | DB advisory: PostgreSQL pg_try_advisory_lock(account_id, symbol_hash) alternatif |

## Worker Sharding (account_id partition)

| Adım | Açıklama |
|------|----------|
| 1 | N worker; worker_id = 0..N-1 |
| 2 | assigned_worker = account_id % N (veya hash(account_id) % N) |
| 3 | Manager/coordinator: START command → sadece assigned_worker işler |
| 4 | DB bot_engine_commands: worker_id sütunu; worker kendi worker_id için poll |
| 5 | Aynı bot hiçbir zaman iki worker'da çalışmaz |

## Exactly-Once Intent Execution (Distributed)

| Öğe | Açıklama |
|-----|----------|
| order_intents | Merkezi tablo; tüm worker'lar aynı DB/Redis üzerinden okur/yazar |
| intent_id | Unique; upsert ile tek insert; aynı intent_id ile retry → aynı client_order_id |
| client_order_id | Deterministic; Binance idempotent |
| Reconciliation | Her worker: PENDING/SENT intents için Binance get_order_by_client_order_id; FILLED ise apply_fill |

## Migration Path (Step-by-Step)

| Phase | Yapılacak |
|-------|------------|
| P1 | order_intents, auth_sessions tabloları (v4.1 done) |
| P2 | Binance weight budget; snapshot payload cap; symbol lock 10s + heartbeat |
| P3 | Redis ekle; LOCK_BACKEND=redis optional |
| P4 | DataHub → Redis cache (optional) |
| P5 | Worker sharding: Coordinator assigns bot → worker_id |
| P6 | Multiple worker processes; her biri kendi shard'ı |

---

# SECTION N — SELF-AUDIT SECTION

## Checklist

| Question | Answer | Risk? |
|----------|--------|-------|
| **Does system guarantee no duplicate financial event?** | **Yes** (v4.1). order_intents + clientOrderId + Binance check-before-place + reconciliation. | Mitigated — SECTION O §3, v4.1 |
| Can duplicate order happen? | No (v4.1 intent flow: upsert_intent, get_order_by_client_order_id before place, update_intent_filled) | Mitigated |
| Can stale trade happen? | No (get_price returns None when stale) | No |
| Can mobile fail silently? | Yes (visibility hidden skips poll; timeout no retry) | **RISK** |
| Can DB lock freeze system? | Possible (SQLITE_BUSY; WAL reduces) | **RISK** |
| Can rate limit cascade? | Yes (circuit open 30s; no weight tracking) | **RISK** |

## Complete Failure-to-Mitigation Matrix

| Failure | Detection | Immediate Mitigation | Permanent Fix |
|---------|-----------|----------------------|---------------|
| Duplicate order | order_intents status; Binance get_order_by_client_order_id | v4.1: intent flow; reconciliation 60s | order_intents + clientOrderId idempotency (done) |
| Stale trade | — | Prevented (get_price returns None) | — |
| Mobile nothing loads | User report; network tab | Refresh; WiFi | Reduce payload; increase timeout |
| DB locked | SQLITE_BUSY log | Retry; reduce load | PRAGMA busy_timeout |
| Rate limit 429 | Log; circuit open | Wait 30s | v4.1: binance_weight request_weight_tokens; deny if insufficient |
| Circuit oscillation | State changes | — | Tune threshold; backoff |
| Lock held 10s | symbol_locks row | Wait expiry; admin force-unlock | v4.1: 10s lease + heartbeat 3s; force_unlock_symbol |
| Session 401 | boot_id mismatch | Re-login | — |
| Snapshot timeout | SNAPSHOT_LATENCY | — | Optimize; reduce payload |
| Worker crash | PID dead | Restart | Supervisor; investigate |
| DataHub empty (worker B) | First request | — | Sticky session; or accept |

## Risk Summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| Duplicate order | Mitigated (v4.1) | order_intents + clientOrderId idempotency implemented |
| Mobile fail silently | Medium | Retry on timeout; visibility handler |
| DB lock | Medium | PRAGMA busy_timeout; short transactions |
| Rate limit cascade | Medium | Weight tracking; backoff |

## Additional Audit Questions

| Question | Answer | Risk? |
|----------|--------|-------|
| Can API key be logged? | No (encrypted; no log of secret) | No |
| Can symbol lock deadlock? | No (lease expiry; no nested locks) | No |
| Can inFlight stay true forever? | Yes if promise never resolves | **RISK** |
| Can snapshot return 200 with all _error? | Yes (partial failure) | No (by design) |
| Can two bots same symbol trade? | No (symbol lock) | No |
| Can Worker place order without lock? | Only if lock check bypassed | Code review |
| Can DataHub return 601st symbol? | No (_MAX_PRICES 600; eviction) | No |
| Can Binance 429 bypass circuit? | No (all calls go through circuit) | No |

## Glossary

| Term | Definition |
|------|------------|
| DataHub | In-memory price cache; per Web process |
| symbol_locks | DB table; (account_id, symbol) lease; one bot per pair |
| bot_engine_state | DB table; JSON state snapshot per bot |
| bot_engine_commands | DB table; START/STOP commands; Worker consumes |
| PRICE_TTL | 120s; age > this ⇒ stale |
| WS_STALE_SEC | 60s; no WS message ⇒ REST takes over |
| Circuit breaker | 3 failures → open 30s → half-open → 1 probe |
| boot_id | Process startup ID; invalidates sessions on restart |
| Snapshot | Single aggregated endpoint: prices, wallet, bots, pnl |

## Environment Variables (Full)

| Variable | Default | Purpose | Impact if Missing |
|----------|---------|---------|-------------------|
| DATABASE_URL | sqlite:///~/.trader/dca.db | DB path | Uses default |
| DATABASE_ROLE | web | web or worker | Engine role |
| BINANCE_MASTER_KEY | — | Fernet decrypt API secrets | Cannot decrypt keys |
| ENV | — | dev/prod | Log level; debug routes |
| DEBUG_METRICS | 0 | Enable /debug/metrics | 404 if 0 |
| BREACH_SHUTDOWN | 0 | Lockdown mode | Normal operation |
| DATAHUB_SERVE_STALE_FOR_UI | 1 | Serve stale prices to UI | 0 = None when stale |
| RAM_PROBE_ENABLED | 0 | RAM diagnostics | No probe |
| PG_STATEMENT_TIMEOUT_MS | — | PostgreSQL timeout | No timeout |

## How to Debug "Why Did This Break at 03:17 on Mobile Only?"

| Step | Action | Data Source |
|------|--------|-------------|
| 1 | Get exact timestamp (UTC) | User report; server logs (Turkey TZ) |
| 2 | Check SNAPSHOT_LATENCY around that time | logs/app.log |
| 3 | Check Binance circuit state | debug/metrics (if DEBUG_METRICS=1) |
| 4 | Check stale_symbols_count | DataHub get_status |
| 5 | Check 429/5xx in logs | logs/app.log |
| 6 | Check mobile: network type, visibilityState | User/browser |
| 7 | Correlate: same moment multiple users? | Logs; circuit open affects all |
| 8 | Check payload size | Response Content-Length |
| 9 | Check worker: BOT_LOOP, LOCK_BUSY | logs/worker.log |
| 10 | Reconstruct timeline | request_id, bot_id, timestamps |

## Debug Checklist — Snapshot Slow

- [ ] Binance circuit open?
- [ ] Binance 429?
- [ ] DB locked?
- [ ] DataHub get_all_prices > 3s?
- [ ] fetch_wallet > 4s?
- [ ] fetch_bots_and_account_kpis > 3s?
- [ ] fetch_finance_pnl > 3s?
- [ ] Payload size > 200KB?
- [ ] Network RTT high?

## Debug Checklist — Bot Not Trading

- [ ] Bot status = running?
- [ ] Price available? (get_price returns not None)
- [ ] Price stale? (is_stale = False)
- [ ] Symbol lock acquired?
- [ ] Account keys configured?
- [ ] Paper mode vs live?
- [ ] last_error_code in state?
- [ ] Strategy decision NOOP?

## Index — Constants Reference

| Constant | Value | File |
|----------|-------|------|
| BINANCE_REQUEST_TIMEOUT_SEC | 4.0 | binance_spot.py |
| MAX_RETRIES | 2 | binance_spot.py |
| CircuitBreaker.FAILURE_THRESHOLD | 3 | binance_spot.py |
| CircuitBreaker.OPEN_SECONDS | 30.0 | binance_spot.py |
| PRICE_TTL | 120.0 | data_hub.py |
| _MAX_PRICES | 600 | data_hub.py |
| BULK_REFRESH_MIN_INTERVAL | 10.0 | data_hub.py |
| SNAPSHOT_TASK_TIMEOUT | 3.0 | dashboard_snapshot.py |
| DEFAULT_LEASE_TTL_SEC | 10 | locks.py |
| HEARTBEAT_RENEWAL_INTERVAL_SEC | 3 | locks.py |
| MAX_SNAPSHOT_BYTES | 150000 | env / routes.py |
| DEFAULT_TIMEOUT | 5000 | apiClient.js |
| MAX_CONCURRENT_REQUESTS | 2 | apiClient.js |
| SNAPSHOT_POLL_MS | 5000 | dashboard.js |
| Snapshot timeout | 12000 | dashboard.js (override) |
| BOT_ENGINE_V5_SCHEDULER | 0 (env) | worker_main — set 1 for event-driven scheduler |
| BOT_ENGINE_KILL_SWITCH | 0 (env) | kill_switch — set 1 to deny new submits |
| BINANCE_WEIGHT_LIMIT_PER_MIN | 1200 | binance_weight.py |

---

## Quick Reference Card

| Question | Answer |
|----------|--------|
| Where is price from? | DataHub (per-process). Worker has own DataHub; Web workers each have own. |
| Stale definition? | age > 120s (PRICE_TTL) |
| Lock TTL? | 10s (DEFAULT_LEASE_TTL_SEC); heartbeat 3s |
| Circuit open? | 3 failures, 30s |
| Snapshot timeout? | 12s UI, 3s per task backend |
| Max concurrent HTTP? | 2 |
| Who places orders? | Worker only |
| Per-symbol ticker allowed? | No (RuntimeError guard) |
| DB path? | ~/.trader/dca.db |

## v5.0 order_intents (Full Schema)

| Column | Type | Purpose |
|--------|------|---------|
| intent_id | TEXT UNIQUE | Deterministic; same inputs => same id |
| client_order_id | TEXT UNIQUE | Stored on first persist; reused on retry |
| status | TEXT | NEW→PERSISTED→SUBMITTING→SUBMITTED→FILLED/CANCELED/REJECTED/UNKNOWN→FINAL |
| submit_attempts | INT | Incremented on each submit attempt |
| last_submit_ts | REAL | Monotonic time of last submit |
| filled_qty, avg_price | REAL | From Binance on fill/reconcile |
| last_error_code, last_error_id | TEXT | On timeout/reject |
| final_ts | REAL | When status became final |

## v4.1 / v5 Tables

| Table | Purpose |
|-------|---------|
| order_intents | v5: full state machine; idempotency; reconcile |
| auth_sessions | Shared session store for multi-worker auth |

## v5.0 Verification Commands

See Section 1K for full list. Summary:

```bash
python3 -m pytest tests/test_intent_idempotency.py -v
python3 scripts/reconcile_now.py [account_id]
python3 scripts/intent_audit.py --account N
python3 scripts/perf_300_bots_sim.py
python3 scripts/binance_weight_sim.py --users 10 --poll 3 --trades 2
sqlite3 ~/.trader/dca.db "SELECT intent_id, status, client_order_id, binance_order_id, submit_attempts FROM order_intents ORDER BY id DESC LIMIT 20;"
# Force unlock (admin API)
curl -X POST http://127.0.0.1:8000/api/admin/force-unlock-symbol -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"account_id": 1, "symbol": "BTCUSDT"}'
```

## Incident Playbook — Duplicate Prevention Proof

| Scenario | Expected Behavior |
|----------|-------------------|
| Crash after place_order, before save_state | Restart → next tick: get_order_by_client_order_id finds FILLED → reconcile (update intent, apply_fill, save_state); no duplicate place |
| Timeout after Binance accepted | Same: get_order_by_client_order_id finds order; reconcile |
| Worker restart mid-cycle | Periodic reconciliation (60s): open orders matched to intents; SENT status; no re-place |

---

## Appendix: Auth/Login Stability Hardening Playbook

**Referans:** [docs/auth_login_stability_hardening.md](docs/auth_login_stability_hardening.md) — "Sürekli login'e yönlendirme" sorunlarını teşhis ve gidermek için mühendislik runbook (Türkçe, 1000+ satır).  
**Referans:** [docs/security_hardening.md](docs/security_hardening.md) — Auth security hardening (cookie-first, CSRF, CSP, rate limit) rollout ve feature flag’ler.

**Özet (10 madde):**

- Yönetici özeti: problem, etki, başarı kriterleri (5xx/timeout’ta logout yok, tek 401’de tek redirect, single-flight refresh).
- Semptom taksonomisi: 10 UX semptomu (S1–S10) ve kategori (token/session, zamanlama, döngü, ortam, ağ).
- Mimari harita: login/session akışı (ASCII), token/cookie saklama konumları, istek yolu Browser → Cloudflare → Nginx → FastAPI → auth middleware.
- İlk 30 kök neden + doğrulama: her biri için semptom, neden, nasıl doğrulanır, tam fix, risk seviyesi (token, 401/redirect, proxy, frontend, backend, ağ).
- Frontend auth state machine: durumlar (unauthenticated, authenticating, authenticated, refreshing, expired, locked), geçişler, deterministik kural tablosu (401/403/429/5xx/timeout).
- apiClient sertleştirme: request dedupe, 401 politikası (single-flight refresh, kuyruk, retry), network blip politikası (timeout/5xx’te asla logout yok), hata normalleştirmesi, correlation id, JS pseudocode/snippet.
- Token/cookie stratejisi: JWT vs opaque, rotation, saklama (httpOnly vs memory vs localStorage), Safari ITP, TTL öneri tablosu; cookie Secure/HttpOnly/SameSite matrisi.
- CSRF/CORS: CORS tam konfig, preflight cache tuzakları; Nginx/Cloudflare: cache bypass, header iletimi, proxy_set_header/proxy_cookie_path örnekleri.
- Backend: middleware sırası, 401/403 semantiği, refresh endpoint, rate limit, brute force, şifre hash, session fixation, rollback ve feature flag.
- Tehdit modeli (auth/session), olay playbook’u (kullanıcılar login’e atıldığında), “yapılmaması gereken” 20+ anti-pattern, localStorage → httpOnly cookie migration planı, Done checklist ve Rollback planı.

---

## Document Revision History

| Version | Date | Changes |
|---------|------|---------|
| 5.0 | 2026-02-12 | **Bot Engine v5:** (1) Event-driven scheduler (scheduler.py, bot_run.py, BOT_ENGINE_V5_SCHEDULER); (2) Exactly-once intent pipeline: full state machine, order_intents v5 schema, deterministic intent_id/client_order_id; (3) Crash-safe reconciliation (reconcile.py, get_all_orders); (4) Lock: dynamic lease 10s + heartbeat 3s, symbol_lock_with_heartbeat; (5) Weight governor + backpressure, SAFE MODE; (6) Typed errors (errors.py), retry taxonomy, kill switch; (7) Sections 1B–1L: capacity model, incident playbooks, verification commands, observability; (8) Safety rules S1–S8 |
| 4.1 | 2026-02-12 | Hard idempotency, weight budget, snapshot cap, auth_sessions, symbol lock 10s+heartbeat |
| 4.0 | 2026-02-12 | Full rewrite; Sections A–N; 2000+ lines |
| 3.0 | — | Previous brain dump |
| 2.1 | — | Pre-v3 |

## File Locations (Critical)

| Resource | Path |
|----------|------|
| DB file | ~/.trader/dca.db (or DATABASE_URL) |
| Web log | logs/web.log |
| Worker log | logs/worker.log |
| Manager log | logs/manager.log |
| App log | logs/app.log |
| Web PID | .run/web.pid |
| Worker PID | .run/worker.pid |
| Manager PID | .run/manager.pid |
| start script | start.command (Mac/Linux), start (Linux: ./start), start.bat (Win) |
| HTML PID | .run/html.pid (Unix start.command yazar) |
| Helper script | scripts/local_web_worker_helper.py |

## End-of-Document Validation

- [ ] All sections 0–16 present
- [ ] All sections A–O present (O = Critical Gaps / Kör Noktalar)
- [ ] Sections 1B–1L Bot Engine v5 present (process model, intent pipeline, schema, reconcile, lock, weight, errors, capacity, playbooks, verification, observability)
- [ ] Every numeric constant documented
- [ ] Every failure path mapped
- [ ] Every unknown marked with IMPACT, HOW TO MEASURE, RISK
- [ ] No implicit assumptions
- [ ] No marketing language
- [ ] Exceeds 2000 meaningful lines

---

## Bot Detail Performance Rewrite V4

**Domain split:** Three data domains—STATIC_DETAIL, LIVE_SNAPSHOT, PERF_SERIES—each isolated in endpoint, lifecycle, cache policy, and UI responsibility. No cross-domain mixing.

**Live snapshot endpoint:** `GET /api/bots-engine/{bot_id}/live`. Response: status, pnl_pct, equity, last_price, last_tick_at, last_error_code, initial_capital, daily_pnl_usd, daily_pnl_pct. Optional flags: stale (last_tick_at > 30s), equity_unavailable. daily_pnl_* from state daily_ref_usd/daily_ref_date (TR gece 00:00 referansı; bot aynı gün açıldıysa ilk tick’te ref set edilir). Source: in-memory snapshot from bot state only; no historical DB. TTL cache 2s, key = bot_id, thread-safe. Response time < 15ms CPU. 404 with structured error_code if bot not found.

**Perf chart endpoint:** `GET /api/bots-engine/{bot_id}/perf-chart-data?range=&bucket=`. Valid range: 1h, 4h, 1d, 7d, 30d. Valid bucket: 1m, 5m, 1h, 4h, 1d. Invalid combinations rejected with 400. Response: range, bucket, series [{ ts, bot_pct, basket_pct }], meta { baseline_equity, baseline_bot0, baseline_parite0, points }. Backend CPU < 40ms.

**Deterministic bucket engine:** BUCKET_SECONDS and WINDOW_SECONDS constants. Algorithm: filter samples in window, bucket by (ts // bucket_sec) * bucket_sec, overwrite per bucket (last sample kept), sort by ts, unique ts, cap at 500 points (step down). No average, no interpolate, no timezone shift. O(n) complexity.

**1h specialization:** For range 1h, bucket enforced to 1h (~24 points). If points < 3, fallback bucket 5m and recompute. Stable hourly boundaries: (ts // 3600) * 3600.

**Perf LRU cache:** PerfLRUCache: max_entries=100, ttl_seconds=5, key (bot_id, range, bucket). Thread-safe OrderedDict, move_to_end on get, popitem(last=False) on overflow. No global memory growth; memory bound constant.

**UI: removal of 1s polling.** Bot detail page no longer polls full detail every 1s. On load: fetchDetail() then registerLiveInterval(). Live interval: 2500ms via intervalRegistry ("bot-detail-live"). fetchLive() calls GET .../live and applyLive(newState).

**State diff guard:** prevLiveState maintained; applyLive(newState) does shallow compare (status, pnl_pct, equity, last_price, last_tick_at, last_error_code, initial_capital, daily_pnl_usd, daily_pnl_pct); only updates DOM when state actually changed. applyLive updates stateBotBalanceValue, stateTotalKzValue (equity − initial_capital), stateDailyKzValue (daily_pnl_usd/daily_pnl_pct). No deep clone each tick.

**Perf chart module (perf_chart_tv.js):** No DOM parsing or innerHTML JSON extraction. Data from GET perf-chart-data only. Export: initPerfChart(container), updatePerfChart(series), destroyPerfChart(). On range change: only setData(), never re-create chart. Range switch: activeAbortController aborts previous request; disable range buttons during fetch; ignore late/aborted responses.

**Cleanup guarantees:** On unmount / beforeunload: intervalRegistry.stop("bot-detail-live"), intervalRegistry.stopByOwner("bot-detail"); activeAbortController.abort(); destroyPerfChart(). No memory retention.

**Concurrency:** Only one live interval; only one active perf fetch; abort previous before new; ignore late responses when aborted. apiClient slot limiter unchanged.

**Bounded CPU:** Live endpoint < 15ms CPU; perf-chart-data endpoint < 40ms CPU. O(n) bucket engine.

---

---

## Changelog (spec güncellemeleri)

**2026-02-12 — Wallet loading / cüzdan hiç gelmiyor fix:**
- applySnapshotToUI: wallet _error → status='error'; UI banner "Yenile | Ayarlara git"
- homeFlash: 3 denemelik retry (600ms, 1500ms, 4000ms); tab şartı kaldırıldı
- /api/binance/wallet: require_auth + require_account_access
- /api/home/wallet/status: keys_configured, last_snapshot_at eklendi (DB read)
- CLOCK_DRIFT: Binance -1021 algılama; Windows w32tm /resync uyarısı
- Mobil alt çubuk kaldırıldı; appbar çıkış butonu sadece solda

Detay: `docs/binanceverirapor.md`

---

*Document v5.0 — Complete System Brain. Bot Engine v5: event-driven, exactly-once, crash-safe, 300-bot capable. Machine-operable. No marketing. No fluff.*



