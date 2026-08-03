# Modül: app/botengine

## Amaç

Bot tick, emir, intent ledger, reconcile — yalnızca worker sürecinde emir gönderir.

## Giriş

```
python -m app.botengine.worker_main
```

## Ana dosyalar

| Dosya | Görev |
|-------|--------|
| `worker_main.py` | Komut poll, scheduler / ensure_running_bots |
| `start_log_brief.py` | İlk START log meta — kısa grid/alloc + dinamik mod durumu |
| `orchestrator.py` | Legacy `_bot_loop` |
| `bot_run.py` | v5 tek tick |
| `scheduler.py` | v5 heap (`BOT_ENGINE_V5_SCHEDULER=1`) |
| `execution.py` | `run_actions` → Binance; `EXEC_ORDER_TIMEOUT_SEC=15`; 401 → `paused_error`; SELL LOT_SIZE preflight; `RUN_ACTION_EXCEPTION` → resilience log |
| `health_watch.py` | `evaluate_bot_health`, `emit_resilience_continue`, `emit_loop_auto_restart`; worker ~60s emit |
| `bot_session.py` | `bot_run_started_at` oturum saati; `resolve_bot_session_start_event_id`; connectivity START sıfırlamaz; event heal |
| `orchestrator.py` | Tick hatalarında running kalır; emilen TRDCA/tick → INFO worker log; döngü crash → auto-restart; `ensure_running_bots` |
| `engine_log_ack.py` | Reset/ack sonrası motor log event filtreleme |
| `order_qty.py` | Decimal `stepSize` floor + `validate_market_sell_qty` |
| `health_watch.py` | Sağlık uyarıları (otomatik durdurmaz) |
| `dynamic/` | Dinamik mod (canlı): `cycle_manager` → DPS V6 (PA ile aynı motor) → **mutlak** plan overlay (`decision_to_overlay`); non-deployable/R8 → tur açılmaz + sabit 30 dk rescan. `regime_multiplier` canlı yolda değil. `safety_gate` max_buy_levels. |
| `dynamic_v2/` | Opt-in alternatif motor (`dynamic_mode_v2`); varsayılan shadow. Kill switch sağlık dönünce açılır; `RUNTIME_EXCEPTION` 15 dk cooldown. Churn limitleri son APPLIED adaya göre. |
| `intent_ledger.py` | Exactly-once intent |
| `locks.py` | Hesap kilidi, lease 10s |
| `reconcile.py` | Binance truth |
| `user_stream.py` | User data stream; HTML/geo engelde `USER_STREAM_NETWORK_BLOCK` (varsayılan 24 saatte bir, env ile ayarlı, `.run/user_stream_network_block_log.json` ile worker restart sonrası da); REST fallback |
| `state_trim.py` | `save_state`/`load_state` öncesi JSON RAM sınırları |
| `state_store.py` | Snapshot; `load_states_list_meta` / `load_states_bulk`; `save_state` → live cache invalidate; `load_state_json_extract` |
| `symbols.py` | `normalize_bot_trading_symbol` — base-only sembol → `*USDT` (SOL → SOLUSDT); create + worker heal |

## Alt klasörler

| Klasör | İçerik |
|--------|--------|
| `strategies/` | dca_grid_trailing, grid_outage_recovery, trdca_pro, multi_asset_rebalance |
| `adapters/` | binance_adapter |

## Stratejiler

| ID | Dosya |
|----|--------|
| `dca_grid_trailing` | `strategies/dca_grid_trailing.py` — dip/tepe/kar trail aktifken `trail_fast_tick_ms` (varsayılan 800) ile hızlı next_wake |
| `trdca_pro` | `strategies/trdca_pro.py` |
| `multi_asset_rebalance` | `strategies/multi_asset_rebalance.py` |

## İlgili

- [docs/BOTENGINE_RUNBOOK.md](../../docs/BOTENGINE_RUNBOOK.md)
- Spec §1B–1L

## Dosya envanteri

### `(kök)`

```
__init__.py
bot_run.py
cycle_ledger.py
errors.py
execution.py
order_qty.py
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
state_trim.py
user_stream.py
virtual_wallet.py
worker_main.py
```

### `adapters/`

```
adapters/__init__.py
adapters/binance_adapter.py
```

### `strategies/`

```
strategies/__init__.py
strategies/base.py
strategies/dca_grid_trailing.py
strategies/multi_asset_rebalance.py
strategies/registry.py
strategies/trdca_pro.py
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
