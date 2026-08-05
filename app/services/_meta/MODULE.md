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
| `binance_rest_log.py` | REST yük izleme, `rest.log` 60s özet, throttle; `/api/v3/time` budget/throttle muaf |
| `binance_ws.py` | WebSocket; Node bridge satır okuma limiti 16MB (`!miniTicker@arr`) |
| `data_hub.py` | Fiyat cache; `get_prices_for_ui`; `pin_symbols` (worker running-bot); ham 24h/exchangeInfo RAM yok |
| `market_data.py` | `resolve_price_fast`, `refresh_worker_symbol_from_web` |
| `core/security/endpoint_rate_limit.py` | spot/price, transaction-history rate limit |
| `binance_spot.py` | Kompakt exchangeInfo cache (`get_cached_symbol_filters`) |
| `price_hub.py` | Fiyat hub |
| `encryption.py` | AES-256-GCM v2 + HKDF (`BINANCE_MASTER_KEY`, `ENCRYPTION_SALT`); hesap bağlamı |
| `pnl_service.py` | Bot PnL, daily_ref (TR 00:00 equity; aynı gün açılışta initial_capital; günlük K/Z = equity − ref) |
| `spot_engine.py` | UI manuel al/sat |
| `binance_connectivity.py` | Binance upstream hata izleme → bot_engine_events |
| `dashboard_snapshot.py` | Snapshot builder |
| `finance_snapshot.py` | Finans snapshot |
| `audit.py` | Audit log |
| `user_readable_activity_logger.py` | Sade Türkçe kullanıcı işlem geçmişi (`Kullanıcı Logları/`, append-only; prod `2770`) |
| `user_activity_translations.py` | Event/teknik sebep → sade Türkçe çeviri |
| `test_account.py` | Paper test hesabı |
| `wallet_display.py` | Strip/tablo bot_locked; test paper USDT Toplam = 10k − config bütçesi (equity değil) |
| `test_spot_paper.py` | Test hesabı manuel spot paper bakiye |
| `test_simulation.py` | Paper fill: taker komisyon, kayma, emir/tick gecikmesi (bot + manuel spot) |
| `test_account_kpi.py` | Test spot KPI strip + günlük değişim (admin tile = dashboard) |
| `transaction_history_service.py` | İşlem geçmişi API |
| `transaction_history_file_store.py` | Şifreli işlem geçmişi (`.run/tx_history/`); `bootstrap_tx_history_from_binance`; Spot→Bot etiket onarımı (`backfill_bot_attribution_from_db`); bot kapanış convert `record_bot_close_convert_fill`; platform `Ayserose` (uygulama/bot/manuel spot) vs `Binance` (dış sync) |
| `binance_connectivity.py` | Upstream hata; probe OK → `on_connectivity_restored` (paused START + running pending `CONNECTIVITY_STABLE` → flush after loop restart + START `connectivity_resume`) |
| `bot_perf_file_store.py` | Bot performans dosyaları; `reconcile_bot_cycles_file_with_state` (state/arşiv ↔ `bots/{id}.json`) |
| `ip_blocklist.py` | Manager'ın yazdığı `.run/blocked_ips.json` okuma; web middleware 403 |
| `leaderboard_service.py` | Global/structure leaderboard; `running_since_iso` = `bot_run_started_at_iso` (bot detay süre ile aynı) |
| `dynamic_param_score/` | Merkez karar motoru (canlı V6): `engine.py` → `v6/engine.py` → `classify_scenario` → `v6_regime_stickiness` (+ `v6_regime_stickiness_store` memory/file/redis) → `net_profile_library` → `seal_net_profile_shape` → `v6_live_safety` (parabolik referans 4+4 / canlı alış kapalı; R7 koşullu→Kapalı gate). Recovery heuristic → R6. R2 kapısı gevşetildi. Display: `v6_pa_display.regime_stickiness_plain`. `param_pool/` offline/legacy. |
| `param_optimizer/` | **Offline-only** araştırma/kalibrasyon (MC/backtest); canlı karar akışında kullanılmaz |

## Dosya envanteri

### `(kök)`

```
__init__.py
audit.py
user_readable_activity_logger.py
user_activity_translations.py
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
bot_perf_narrative.py
wallet_pricing.py → market_data.get_price_map_flat
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
