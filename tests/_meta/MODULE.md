# Modül: tests

## Amaç

pytest — güvenlik ve sözleşme testleri.

## Çalıştır

```bash
.venv/bin/pytest tests/ -q
```

## Dosyalar

| Test | Konu |
|------|------|
| `test_intent_idempotency.py` | Intent / clientOrderId |
| `test_locks_ttl.py` | Symbol lock lease |
| `test_worker_only_order_guard.py` | Worker-only emir |
| `test_binance_reconcile.py` | Reconcile |
| `test_auth_security_hardening.py` | CSRF, rate limit |
| `test_auth_session_shared.py` | Session |
| `test_snapshot_*` | Snapshot sözleşmesi |
| `test_home_fast_no_binance.py` | Home fast |
| `test_cycle_ledger.py` | Cycle PnL |
| `test_pnl_trailing_dca.py` | PnL |
| `e2e/test_param_assistant_user_flow.py` | Param Assistant kullanıcı akışı E2E (HTTP) |
| `dynamic_param_score/test_param_assistant_blackbox.py` | Param Assistant API black-box |
| `dynamic_param_score/test_dynamic_mode_v4_final.py` | Dynamic Mode V4 rebalance/retry/invariant |

## Dosya envanteri

### `(kök)`

```
test_auth_security_hardening.py
test_auth_session_shared.py
test_binance_reconcile.py
test_cycle_ledger.py
test_home_fast_no_binance.py
test_intent_idempotency.py
test_locks_ttl.py
test_pnl_trailing_dca.py
test_snapshot_fields_validation.py
test_snapshot_meta_present.py
test_worker_only_order_guard.py
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
