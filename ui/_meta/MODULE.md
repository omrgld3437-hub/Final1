# Modül: ui

## Amaç

Web panel — HTML + vanilla JS (FastAPI `/ui` mount).

## Sayfalar

| Dosya | Kullanım |
|-------|----------|
| `dashboard.html` | Ana panel, bot listesi |
| `bot.html` | Trailing DCA detay — grid warmup; state hero (`/live` 2.5s + süre 1s tick, `syncStateHeroDurationPoll`; çalışan botta detail patch hero’yu ezmez); tur raporu süre sayacı (`cycle_opened_at`, 1s poll, tur değişiminde sıfırlanır) |
| `bot_multi.html` | TRDCA / multi — aynı grid warmup + display fingerprint yenileme |
| `admin.html` | Admin |
| `login.html` | Giriş |

## assets/

| Alt klasör | İçerik |
|------------|--------|
| `core/` | apiClient, appBoot, intervalRegistry |
| `stores/` | dashboardStore, financeStore |
| `services/` | marketData, finance |
| `utils/` | trTime, coinLogo, botHealthAlerts (aktif uyarı log; çözülen HEALTH gizlenir) |
| *(kök)* | dashboard.js (cüzdan canlı yenileme: bot durdur/sil, periyodik force), admin.js, chart.js |

## Bot oluşturma

`dashboard.js` → `createAndStartBot` → `/api/bots/create` + `/api/bots-engine/{id}/start`

## Eksik asset

`vendor/lightweight-charts.standalone.production.js` — grafik sayfaları için

## Dosya envanteri

### `(kök)`

```
admin.html
bot.html
bot_multi.html
chart.html
dashboard.html
index.html
login.html
logs.html
maintenance.html
seo-index.html
server_manager.html
splash.html
trader-trailing.html
```

### `assets/`

```
assets/admin-login-theme.css
assets/admin.js
assets/api.js
assets/appBoot.js
assets/binance-colors.css
assets/blink.css
assets/chart.js
assets/coins/1INCH.png
assets/coins/AAVE.png
assets/coins/ACA.png
assets/coins/ADA.png
assets/coins/ALGO.png
assets/coins/ANKR.png
assets/coins/API3.png
assets/coins/APT.png
assets/coins/ARB.png
assets/coins/ARK.png
assets/coins/ATOM.png
assets/coins/AUDIO.png
assets/coins/AVAX.png
assets/coins/AXL.png
assets/coins/AXS.png
assets/coins/BAND.png
assets/coins/BAT.png
assets/coins/BB.png
assets/coins/BCH.png
assets/coins/BNB.png
assets/coins/BONK.png
assets/coins/BTC.png
assets/coins/BUSD.png
assets/coins/CELO.png
assets/coins/CFX.png
assets/coins/CHZ.png
assets/coins/CKB.png
assets/coins/COMP.png
assets/coins/CRV.png
assets/coins/DAI.png
assets/coins/DASH.png
assets/coins/DCR.png
assets/coins/DENT.png
assets/coins/DGB.png
assets/coins/DOGE.png
assets/coins/DOT.png
assets/coins/DYDX.png
assets/coins/EGLD.png
assets/coins/ENJ.png
assets/coins/ENS.png
assets/coins/ETC.png
assets/coins/ETH.png
assets/coins/FDUSD.png
assets/coins/FET.png
assets/coins/FIL.png
assets/coins/FIO.png
assets/coins/FLOKI.png
assets/coins/FLUX.png
assets/coins/FRAX.png
assets/coins/GALA.png
assets/coins/GLMR.png
assets/coins/HBAR.png
assets/coins/ICP.png
assets/coins/ICX.png
assets/coins/IMX.png
assets/coins/INJ.png
assets/coins/JASMY.png
assets/coins/JUP.png
assets/coins/KAVA.png
assets/coins/KNC.png
assets/coins/KSM.png
assets/coins/LDO.png
assets/coins/LINK.png
assets/coins/LRC.png
assets/coins/LTC.png
assets/coins/LUNA.png
assets/coins/LUNC.png
assets/coins/MANA.png
assets/coins/MOVR.png
assets/coins/NEAR.png
assets/coins/ONE.png
assets/coins/ONT.png
assets/coins/PENDLE.png
assets/coins/PEPE.png
assets/coins/PYUSD.png
assets/coins/QTUM.png
assets/coins/RENDER.png
assets/coins/ROSE.png
assets/coins/RUNE.png
assets/coins/RVN.png
assets/coins/SAND.png
assets/coins/SEI.png
assets/coins/SKL.png
assets/coins/SNX.png
assets/coins/SOL.png
assets/coins/STEEM.png
assets/coins/STORJ.png
assets/coins/SUI.png
assets/coins/SUSHI.png
assets/coins/THETA.png
assets/coins/TON.png
assets/coins/TRX.png
assets/coins/TUSD.png
assets/coins/UNI.png
assets/coins/USDC.png
assets/coins/USDP.png
assets/coins/USDT.png
assets/coins/VET.png
assets/coins/WBTC.png
assets/coins/WIF.png
assets/coins/WLD.png
assets/coins/XLM.png
assets/coins/XRP.png
assets/coins/XTZ.png
assets/coins/YFI.png
assets/coins/ZEC.png
assets/coins/ZEN.png
assets/coins/ZIL.png
assets/coins/ZRX.png
assets/components.js
assets/core/apiClient.js
assets/core/errorReporter.js
assets/core/intervalRegistry.js
assets/core/maintenance.js
assets/dashboard-login-theme.css
assets/dashboard.css
assets/dashboard.js
assets/design.css
assets/homeFlash.js
assets/js/maintenanceOverlay.js
assets/login.css
assets/perf_chart_canvas_history.js
assets/perf_chart_rebuild.js
assets/perf_chart_tv.js
assets/renderHome.js
assets/seo.css
assets/services/financeService.js
assets/services/marketDataService.js
assets/spot_engine.js
assets/storageCache.js
assets/stores/botStore.js
assets/stores/dashboardStore.js
assets/stores/financeStore.js
assets/stores/marketStore.js
assets/theme.css
assets/ticker.css
assets/ticker.js
assets/ui.css
assets/utils/coinLogo.js
assets/utils/trTime.js
```

### `vendor/`

```
vendor/lightweight-charts.standalone.production.js
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
