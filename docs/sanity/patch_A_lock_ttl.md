# Patch A: Lock TTL Single Source of Truth

## Summary
Unified lock lease TTL to 10s across the codebase. Single definition in `app/core/constants.py`; `app/botengine/locks.py` imports from it.

## How to run tests
```bash
pytest tests/test_locks_ttl.py -v
```

## How to verify TTL in logs
- Lock acquire/renew logs use the constant; lease_until is now + 10s from acquire.
- Grep for single definition: `grep -r "DEFAULT_LEASE_TTL_SEC" app/` should show definition in `app/core/constants.py` and imports in `app/botengine/locks.py`.
- No remaining "60" in lock context: `grep -n "60" app/botengine/locks.py` should show no TTL-related literal.

## Expected outcomes
- `test_ttl_constant_consistency` passes: DEFAULT_LEASE_TTL_SEC == 10, HEARTBEAT_RENEWAL_INTERVAL_SEC == 3.
- Lock release is attempted in `symbol_lock_with_heartbeat` finally block even on exception.
