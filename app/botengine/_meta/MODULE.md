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
| `start_log_brief.py` | İlk START log meta — kısa grid/alloc özet |
| `orchestrator.py` | Legacy `_bot_loop` |
| `bot_run.py` | v5 tek tick |
| `scheduler.py` | v5 heap (`BOT_ENGINE_V5_SCHEDULER=1`) |
| `execution.py` | `run_actions` → Binance; 401 → `paused_error`; SELL LOT_SIZE preflight; `RUN_ACTION_EXCEPTION` → resilience log |
| `health_watch.py` | `evaluate_bot_health`, `emit_resilience_continue`, `emit_loop_auto_restart`; worker ~60s emit |
| `orchestrator.py` | Tick hatalarında running kalır; döngü crash → auto-restart; `ensure_running_bots` |
| `order_qty.py` | Decimal `stepSize` floor + `validate_market_sell_qty` |
| `health_watch.py` | Sağlık uyarıları (otomatik durdurmaz) |
| `intent_ledger.py` | Exactly-once intent |
| `locks.py` | Hesap kilidi, lease 10s |
| `reconcile.py` | Binance truth |

## Alt klasörler

| Klasör | İçerik |
|--------|--------|
| `strategies/` | dca_grid_trailing, grid_outage_recovery, trdca_pro, multi_asset_rebalance |
| `adapters/` | binance_adapter |

## Stratejiler

| ID | Dosya |
|----|--------|
| `dca_grid_trailing` | `strategies/dca_grid_trailing.py` |
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
