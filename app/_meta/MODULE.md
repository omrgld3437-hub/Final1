# Modül: app

## Amaç

FastAPI backend, REST/WebSocket API, Binance entegrasyonu, Bot Engine paketi.

## Giriş

| Süreç | Komut |
|-------|--------|
| Web | `uvicorn app.main:app` |
| Worker | `python -m app.botengine.worker_main` |

## Alt klasörler

| Klasör | Doküman | Not |
|--------|---------|-----|
| `api/` | [api/_meta/MODULE.md](api/_meta/MODULE.md) | HTTP API |
| `botengine/` | [botengine/_meta/MODULE.md](botengine/_meta/MODULE.md) | Canlı bot motoru |
| `services/` | [services/_meta/MODULE.md](services/_meta/MODULE.md) | Binance, PnL, DataHub |
| `db/` | — | SQLAlchemy, schema_guard |
| `core/` | — | config, constants, auth |
| `middleware/` | — | CSRF, güvenlik başlıkları |
| `bot/` | — | Legacy — yeni kod ekleme |
| `observability/` | — | RAM probe |

## Ortam

- Web: `DATABASE_ROLE=web`
- Worker: `DATABASE_ROLE=worker`

## İlgili

- [docs/CODE_TREE.md](../../docs/CODE_TREE.md)
- [TRADE_TRAILING_MASTER_SPEC.md](../../TRADE_TRAILING_MASTER_SPEC.md)

## Dosya envanteri

### `(kök)`

```
boot_id.py
error_logging.py
main.py
server_state.py
```

### `api/`

```
api/__init__.py
api/admin.py
api/auth.py
api/bots_engine.py
api/bots_v2.py
api/data_hub_routes.py
api/finance.py
api/finance_reports.py
api/leaderboard.py
api/market_data_routes.py
api/pricing_routes.py
api/routes.py
api/routes/__init__.py
api/routes/dashboard_bootstrap.py
api/routes/home.py
api/spot_routes.py
api/utils/__init__.py
api/utils/fields.py
api/ws.py
```

### `bot/`

```
bot/__init__.py
bot/binance_adapter_v2.py
bot/dca_engine_v3.py
bot/dca_worker_v3.py
bot/engine.py
bot/engine_v2.py
bot/ledger.py
bot/manager.py
bot/models.py
bot/models_v2.py
bot/trailing_engine.py
bot/worker_v2.py
```

### `botengine/`

```
botengine/__init__.py
botengine/adapters/__init__.py
botengine/adapters/binance_adapter.py
botengine/bot_run.py
botengine/cycle_ledger.py
botengine/errors.py
botengine/execution.py
botengine/grid_view.py
botengine/intent_ledger.py
botengine/kill_switch.py
botengine/locks.py
botengine/models.py
botengine/orchestrator.py
botengine/reconcile.py
botengine/risk.py
botengine/scheduler.py
botengine/state_store.py
botengine/strategies/__init__.py
botengine/strategies/base.py
botengine/strategies/dca_grid_trailing.py
botengine/strategies/multi_asset_rebalance.py
botengine/strategies/registry.py
botengine/strategies/trdca_pro.py
botengine/user_stream.py
botengine/virtual_wallet.py
botengine/worker_main.py
```

### `core/`

```
core/__init__.py
core/anomaly_codes.py
core/auth/__init__.py
core/auth/token_utils.py
core/config.py
core/constants.py
core/errors.py
core/logging_helpers.py
core/security/__init__.py
core/security/rate_limiter.py
```

### `db/`

```
db/__init__.py
db/base.py
db/models.py
db/schema_guard.py
db/session.py
```

### `middleware/`

```
middleware/__init__.py
middleware/csrf.py
middleware/request_metrics.py
middleware/security_headers.py
```

### `observability/`

```
observability/__init__.py
observability/metrics_stubs.py
observability/ram_probe.py
```

### `services/`

```
services/__init__.py
services/audit.py
services/binance_assets.py
services/binance_client.py
services/binance_metrics.py
services/binance_spot.py
services/binance_weight.py
services/binance_ws.py
services/cache.py
services/copytrading_sanitize.py
services/dashboard_snapshot.py
services/data_hub.py
services/encryption.py
services/finance_pnl_calculator.py
services/finance_snapshot.py
services/finance_trade_sync.py
services/leaderboard_service.py
services/perf_chart_state.py
services/pnl_service.py
services/price_hub.py
services/pricing.py
services/pricing_summary.py
services/spot_engine.py
services/test_account.py
services/transaction_history_service.py
```

### `utils/`

```
utils/__init__.py
utils/account_code.py
utils/tz_utils.py
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
