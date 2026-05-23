# app/services — İş servisleri

**Konum:** `app/services/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Binance client, fiyat hub, PnL hesabı, DataHub, audit, şifreleme — API ve Engine'in ortak iş katmanı.

## Bu klasörde ne bulursunuz?

Route'lar ince kalır; ağır iş burada. Binance çağrıları, cache, snapshot birleştirme.

## Önemli dosyalar

binance_client.py · pnl_service.py · data_hub.py · pricing.py · audit.py

## İçerik özeti

```
__init__.py
audit.py
binance_assets.py
binance_client.py
binance_metrics.py
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

## İlgili dokümanlar

app/services/_meta/MODULE.md

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
