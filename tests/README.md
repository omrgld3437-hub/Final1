# tests — Otomatik testler (pytest)

**Konum:** `tests/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Auth, lock TTL, intent idempotency, reconcile, PnL, snapshot sözleşmeleri.

## Bu klasörde ne bulursunuz?

Regresyon güvencesi. Çalıştırma: `make test` veya `pytest tests/`.

## Önemli dosyalar

test_locks_ttl.py · test_intent_idempotency.py · test_home_fast_no_binance.py

## İçerik özeti

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

## İlgili dokümanlar

tests/_meta/MODULE.md

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
