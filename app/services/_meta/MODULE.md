# Modül: app/services

## Amaç

Paylaşılan iş mantığı: Binance, fiyat, PnL, şifreleme, audit.

## Ana dosyalar

| Dosya | Görev |
|-------|--------|
| `binance_spot.py` | Signed REST, `place_order` worker guard |
| `binance_assets.py` | API key, hesap |
| `binance_client.py` | HTTP client |
| `binance_weight.py` | Rate limit / weight |
| `market_data.py` | SSOT okuma — fiyat/24h/sembol (Binance REST yok) |
| `market_data.py` | Cüzdan fiyat map (market_data) |
| `binance_rest_log.py` | REST yük izleme, `rest.log` 60s özet, throttle |
| `binance_ws.py` | WebSocket |
| `data_hub.py` | Fiyat cache |
| `price_hub.py` | Fiyat hub |
| `encryption.py` | Fernet (`BINANCE_MASTER_KEY`) |
| `pnl_service.py` | Bot PnL, daily_ref |
| `spot_engine.py` | UI manuel al/sat |
| `dashboard_snapshot.py` | Snapshot builder |
| `finance_snapshot.py` | Finans snapshot |
| `audit.py` | Audit log |
| `test_account.py` | Paper test hesabı |

## Dosya envanteri

### `(kök)`

```
__init__.py
audit.py
binance_assets.py
binance_client.py
binance_metrics.py
binance_rest_log.py
binance_spot.py
binance_weight.py
binance_ws.py
cache.py
copytrading_sanitize.py
dashboard_snapshot.py
data_hub.py
encryption.py
finance_pnl_calculator.py
finance_snapshot.py
finance_trade_sync.py
leaderboard_service.py
perf_chart_state.py
pnl_service.py
price_hub.py
pricing.py
pricing_summary.py
spot_engine.py
test_account.py
transaction_history_service.py
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
