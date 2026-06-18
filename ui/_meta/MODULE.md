# Modül: ui

## Amaç

Web panel — HTML + vanilla JS (FastAPI `/ui` mount).

## Sayfalar

| Dosya | Kullanım |
|-------|----------|
| `dashboard.html` | Ana panel, bot listesi |
| `bot.html` | Üst appbar: WS + TraderTrailing (`botPageAppbar.js`); dinamik mod rozeti üst strip (**Dinamik ✓**, `dynModeStripBadge`); tur işlemleri tek kaynak: `mergeTradesForCyclePanel` → API + `dedupeTradesForPanel`; grid etiketi `grid_detail.display_label` (API enrich); `cycleSideFromDualSnapshot`; grid satış tablosu fiyatları `fmtGridPrice` (= `#botPriceEl` ondalığı), miktar `fmtGridBaseQty` |
| `bot_multi.html` | TRDCA / multi — aynı grid warmup + display fingerprint yenileme |
| `admin.html` | Admin — anında önbellek (inline + localStorage), boot-id bloklamaz |
| `login.html` | Giriş |

## assets/

| Alt klasör | İçerik |
|------------|--------|
| `core/` | apiClient (HTTP 429: `extractHttpDetailMessage` + 30s toast debounce; `suppressRateLimitToast` sessiz poll), appBoot, intervalRegistry |
| `stores/` | dashboardStore, financeStore |
| `services/` | marketData, finance |
| `utils/` | trTime, coinLogo, **dynamicModeParamsView** (Parametreler modal dinamik sekme/leaderboard özeti), **engineLogAccess** (bot log paneli admin-only), botHealthAlerts (aktif uyarı log; sorun çözülünce otomatik kalkar + isteğe bağlı health/ack; Binance çözümü yeşil — `SERVER_UNREACHABLE` sentetik stabil değil; 45 sn dedupe; dashboard satır uyarısı `classifyRowAlerts`; bot sayfası kritik çerçeve), engineLogLive (bootstrap yükleme; sentetik bağlantı logu), engineLogFormat (`CONNECTIVITY_STABLE` yetim satır gizleme + tekilleştirme), **perfSummaryIntros** (Analiz Asistanı 50 ilk karşılama profili) |
| *(kök)* | dashboard.js (**Botlar sekmesi** `activateBotsTab` + `financeBotsDom_v1_*` HTML önbelleği — bot detaydan dönüşte tablo yeniden çizilmez; `bot.html` `bot_detail_ui_v2_*` + `pagehide` persist; dashboard: `isBenignDashboardFetchError`, KPI/cüzdan Canlı/Güncel değil, bot satırı health blink), `botPageAppbar.js` (bot detay WS göstergesi), admin.js, chart.js, **scrollRestore.js** (yenilemede kaydırma — yalnızca tam scope anahtarı), scrollAutoHide.js + scroll-auto-hide.css |

## Bot oluşturma

`dashboard.js` → `createAndStartBot` → `/api/bots/create` + `/api/bots-engine/{id}/start`

**Sembol arama (`#fSymbol`, `#mobileTradeSearchInput`, coin list):** `scope=all` → Binance TRADING tüm çiftler; `fetchCoinSearchPricesBatch` + `ticker_24h` yedek — arama sonuçlarında tüm paritelerin fiyatı (`formatCoinSearchItemPrice`, quote’a göre); `queueCoinSearchPriceFetch` mobil/desktop dropdown canlı doldurma. Bot oluştur `#dmSymbolSearchDropdown`: fiyat poll bitince yalnızca input odaktayken yenilenir; dışarı tıklama / Escape / parite seçimi → `hideCreateModalSymbolDropdown` (`_dmSymbolSearchPriceGen`).

**Cüzdan varlıkları:** `renderVarliklarList` — stabil sıralama, patch-only; `varlikRowTradeState` Al/Sat her zaman aktif; `fmtVarlikQty` (Toplam/Bot kilitli/Kilitli/Kullanılabilir — miktar büyüklüğü + LOT_SIZE üst sınırı, dinamik ondalık) / `walletAssetTotalQty`; `refreshVarliklarWalletMarketData` slim prices. **Dashboard tema:** `dashboard-login-theme.css` — koyu gri zemin (`#1a1d24`), paneller `#242932`, altın accent. Aynı dosya **`page-bot`** (`bot.html`) için de geçerli. **KPI cüzdan (`#kpiCuzdan`, günlük PnL):** `setKpiUsdTextIfChanged` / `setKpiPctTextIfChanged` (cent altı DOM yok); test strip→KPI `scheduleTestAccountKpiCuzdanRefresh` (~450 ms) — canlı fiyat tick flicker azaltma. **Login (`login.html`, `login.css?v=zip-auth1`):** tradertrailing.zip AuthCard glass tema — altın `#f0b90b`, üst sekme çubuğu, hero rozeti; mevcut auth API/JS korunur.

**Bağlantı dönüşü:** `recoverDashboardAfterConnectivity` — `online` / focus / sekme görünür + stale iken `homeFlash.resetRefreshThrottle`, `POST /api/home/wallet/refresh?force=1`, `GET /api/home/connectivity-check` (`maybeToastConnectivityWarning`: CLOCK_DRIFT 120s debounce; KPI stale **Saat senkronu**), `fetchSnapshot`. **Binance IP:** işlemler sunucudan gider; Ayarlar → Sunucu dış IP beyaz listeye eklenmeli (PC IP yetmez). `home.py` hata → `note_binance_failure`; manager `logHumanize` v26 (Ham satırdan yeniden şablon). **Bot detay:** `bot.html?symbol=` + `syncBotStripSymbol` — strip sembolü API ile senkron (cache/patch drift önlemi).

**En İyi 5 Bot:** `loadGlobalLeaderboard` — yapı değişmedikçe tam `innerHTML` yok (`structureSig`); K/Z/süre `patchGlobalLeaderboardMetrics` (logo DOM dokunulmaz, `coinLogoCache` + lazy logo). Boş liste `patchOnly`; 10 sn timeout → `LEADERBOARD_NO_PROFIT_HTML`; `filterLeaderboardItemsForDisplay` + `scheduleLeaderboardSyncFromBots`.

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
assets/scroll-auto-hide.css
assets/scrollAutoHide.js
assets/scrollRestore.js
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
