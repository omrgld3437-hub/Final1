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
| `encryption.py` | AES-256-GCM v2 + HKDF (`BINANCE_MASTER_KEY`, `ENCRYPTION_SALT`); hesap bağlamı |
| `pnl_service.py` | Bot PnL, daily_ref |
| `spot_engine.py` | UI manuel al/sat |
| `binance_connectivity.py` | Binance upstream hata izleme → bot_engine_events |
| `dashboard_snapshot.py` | Snapshot builder |
| `finance_snapshot.py` | Finans snapshot |
| `audit.py` | Audit log |
| `test_account.py` | Paper test hesabı |
| `transaction_history_service.py` | İşlem geçmişi API |
| `transaction_history_file_store.py` | Şifreli işlem geçmişi (`.run/tx_history/`); `bootstrap_tx_history_from_binance` |
| `binance_connectivity.py` | Upstream hata; `try_auto_resume_paused_bots` → `CONNECTIVITY_RECOVERED` + START `payload_json.connectivity_resume` (çift Bismillah logu yok) |
| `bot_perf_file_store.py` | Bot performans saatlik/günlük dosya deposu |

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
transaction_history_file_store.py
bot_perf_file_store.py
bot_performance_service.py
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
