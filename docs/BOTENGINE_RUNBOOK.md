# Bot Engine Runbook

**Tarih:** 2026-01-28

## Bot create / start / stop / delete

- **Create:** `POST /api/bots-engine` (body: `account_id`, `config_json`). Auth: `require_auth` + `get_account_or_403(account_id)`. Kaynak: `app/api/bots_engine.py` → `bots_create`, `create_bot_engine_core`. Oluşturulunca `ensure_state_row` ile `bot_engine_state` satırı açılır.
- **Start:** `POST /api/bots-engine/{bot_id}/start`. `Bot.status = "running"`, commit; `start_bot(bot_id, db)` → `_bot_loop(bot_id)` asyncio task. Guard: Zaten çalışıyorsa `BOT_START_SKIPPED_ALREADY_RUNNING`, yeni task açılmaz.
- **Stop:** `POST /api/bots-engine/{bot_id}/stop`. `_stop_requested.add(bot_id)`, `Bot.status = "stopped"`, task cancel.
- **Delete:** `POST /api/bots-engine/{bot_id}/delete`. `delete_bot_fully`: stop → symbol lock release → bot_virtual_wallet, bot_engine_events, bot_engine_state, trades, pnl, bot silinir.

## Prod / dev run

- **Uvicorn:** `app/main.py` ile uygulama ayağa kalkar. Reload: `uvicorn --reload` kullanılıyorsa kod değişikliğinde process yeniden başlar; çalışan bot task’leri sonlanır, `ensure_running_bots` ile DB’de status=running olanlar tekrar başlatılır.
- **Worker:** Tek process varsayılır. Multi-worker (örn. gunicorn birden fazla worker) kullanılırsa aynı bot iki process’te çalışabilir; state overwrite riski (Case D). Tek worker veya process-level lock önerilir.

## "Bot çalışmıyor" debug checklist

1. **Loglar:** `BOT_LOOP_START`, `BOT_DB_SESSION`, `BOT_STATE_LOADED`, `BOT_PRICE`, `BOT_ACCOUNT_CTX`, `BOT_ACTION`, `BOT_STATE_SAVING`/`BOT_STATE_SAVED`, `BOT_TICK` izle.
2. **State persist:** Tick 2’de `BOT_STATE_LOADED ia_done=True` ve hash önceki save ile aynı mı? Değilse `docs/SANITY_CHECK_BOTENGINE_STATE_PERSIST.md` Case A/B/C/D.
3. **Fiyat:** `BOT_PRICE status=STALE` sık mı? Data hub fiyat gelmiyorsa trade atlanır.
4. **Hesap anahtarları:** `BOT_ACCOUNT_CTX has_keys=False` ise initial alloc başlamaz; keys eklenmeli.
5. **Execution skip:** `BOT_EXECUTION_SKIP skip_reason=IDEMPOTENT_LOCK|MIN_NOTIONAL|INSUFFICIENT_VIRTUAL_FUNDS|ORDER_FAILED` hangi sebep?
6. **Rollback:** `BOT_DB_TX_ROLLBACK` görülüyorsa stack’ten hangi kod yolundan geldiği bulunur (Case C).
7. **Çift loop:** Farklı `loop=` değerleri varsa çift start/worker (Case D).

Detaylı senaryo ve case ayrımı: `docs/SANITY_CHECK_BOTENGINE_STATE_PERSIST.md` ve `docs/INCIDENT_ROOTCAUSE_REPORT.md`.
