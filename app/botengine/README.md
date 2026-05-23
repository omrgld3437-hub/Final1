# app/botengine — Bot Engine v5

**Konum:** `app/botengine/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Canlı bot motoru: emir gönderimi, strateji tick'leri, scheduler, reconcile, intent ledger.

## Bu klasörde ne bulursunuz?

Worker ayrı proses olarak çalışır. UI bot START komutu → DB kuyruk → worker → execution → Binance. Legacy orchestrator da burada (v5 scheduler kapalıysa).

## Önemli dosyalar

worker_main.py · bot_run.py · execution.py · scheduler.py · orchestrator.py

## İçerik özeti

```
__init__.py
adapters/
bot_run.py
cycle_ledger.py
errors.py
execution.py
grid_view.py
intent_ledger.py
kill_switch.py
locks.py
models.py
orchestrator.py
reconcile.py
risk.py
scheduler.py
state_store.py
strategies/
user_stream.py
virtual_wallet.py
worker_main.py
```

## İlgili dokümanlar

docs/engine/BOTENGINE_RUNBOOK.md · app/botengine/_meta/MODULE.md

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
