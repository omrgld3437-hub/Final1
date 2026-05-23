# Changelog — Performance & Reliability Hardening

Append-only log of changes for the perf hardening pass.

---

## Phase 0 — Repo discovery (2026-02-12)

- Added `docs/perf_hardening_report.md`: inventory of backend/frontend paths, snapshot endpoint and payload shape, Binance /account usage, DataHub instantiation, lock TTL location, request_id, compression.
- Added this changelog (`docs/changelog_perf_hardening.md`).
- No code or API changes; documentation only.

---

## Phase 1 — Lock TTL unification + safety (2026-02-12)

- **Spec:** TRADE_TRAILING_MASTER_SPEC.md system limits table: `DEFAULT_LEASE_TTL_SEC` corrected from 60 to 10 (with note "heartbeat 3s"). Code was already 10s.
- **locks.py:** Single source of truth remains `DEFAULT_LEASE_TTL_SEC = 10`, `HEARTBEAT_RENEWAL_INTERVAL_SEC = 3`. Added structured logs: `lock_acquire_ok`, `lock_acquire_busy`, `lock_heartbeat_ok` (debug), `lock_heartbeat_fail`, `lock_release_ok`, `lock_release_error` with account_id, bot_id, symbol, lease_until/error_code.
- **locks.py:** Added `lease_still_valid(db, account_id, symbol, bot_id)` — returns True only if bot_id holds a non-expired lease. Call before submit to avoid double-submit after heartbeat failure.
- **orchestrator.py:** Before `run_actions` (single-symbol and MULTI paths), added `lease_still_valid` check; if False, release lock, append_event LOCK_LEASE_EXPIRED, skip submit. Import `lease_still_valid`.
- **Tests:** `tests/test_locks_ttl.py` — `test_ttl_constant_consistency` (DEFAULT_LEASE_TTL_SEC==10, HEARTBEAT==3), `test_lease_still_valid_callable`, `test_lease_still_valid_returns_false_when_no_lock`, `test_lease_still_valid_returns_false_when_expired` (DB fixture skips if table missing).
