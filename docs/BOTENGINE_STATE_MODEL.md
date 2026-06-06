# Bot Engine State Model

**Tarih:** 2026-01-28

## state_json şeması (DCA Grid Trailing)

Kaynak: `app/botengine/models.py` → `build_state_skeleton`, strategy/execution alanları.

| Alan | Tip | Açıklama |
|------|-----|----------|
| bot_id, account_id, symbol, status | - | Kimlik |
| cycle_id | int | Cycle sayacı |
| state_version | int | Optimistic locking; her save'te artar |
| reference_price | float \| null | Grid/trailing referans fiyat |
| initial_allocation_done | bool | İlk alım yapıldı mı |
| initial_alloc_base_qty, initial_alloc_price | float | İlk alım miktar/fiyat |
| base_balance, quote_balance | float | Virtual bakiye (gösterim için) |
| mode | str | IDLE, TRAIL_SELL_GRID, TRAIL_BUY_GRID, ... |
| sell_grid_fired, buy_grid_fired | list | Grid slot tetiklenme |
| sell_grid_trigger_price, buy_grid_trigger_price | list | Tetik fiyatları |
| trail_anchor_price, trail_activation_price | float \| null | Trailing anchor/activation |
| realized_pnl_usdt_cycle, fees_paid_usdt_cycle | float | Cycle PnL/fee |
| last_tick_at, last_error_code, retry_at | - | Tick/hata bilgisi |

## Versioning / optimistic locking

- `state_version` load'da yoksa 0 kabul edilir; her `save_state` çağrısında artırılır (`app/botengine/state_store.py`). İleride eşzamanlı yazımda "version uyuşmazsa retry" eklenebilir.

## Persist kuralları

1. **Tek writer (tek loop):** Aynı bot için tek `_bot_loop` task; state'i sadece o task yazar (orchestrator + execution içinde `save_state`).
2. **Commit:** `save_state` içinde upsert sonrası `db.commit()`; post-commit re-read ile verify log (`BOT_STATE_SAVED verify_ia_done= verify_hash=`).
3. **Session:** Her tick yeni session; tick sonunda `db.close()`. Sonraki tick yeni session ile load eder; commit görünür olmalı.
4. **Idempotency:** Initial allocation action key sabit: `initial_allocation_0` (`app/botengine/execution.py`, orchestrator log).

State yazarlarının listesi: `docs/BOTENGINE_STATE_WRITERS.md` (varsa); yoksa sadece `state_store.save_state` ve execution içinden çağrılan `save_state`.
