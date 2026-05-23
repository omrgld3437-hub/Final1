# Changelog

## [Flash Home – Patch H] – 2026-02-12

### Mobile-first “flash” homepage
- **GET /api/home/fast:** No Binance; cached prices (DataHub) + minimal KPIs (DB) + last wallet snapshot (AssetSnapshot). Memory cache TTL 2s. Response: `data.prices`, `data.kpis`, `data.wallet_cached`, `data.wallet_cached_at`, `data.prices_ready`, `data.wallet_live_inflight`; `meta.request_id`, `server_ms`, `payload_bytes`, `cache`, `generated_at`.
- **POST /api/home/wallet/refresh:** Binance wallet refresh with TTL (5s), inflight dedup, cooldown (30s) on rate limit. Optional `force=1` bypasses TTL. Writes AssetSnapshot on success.
- **GET /api/home/wallet/status:** Inflight, last_live_at, cooldown_until, last_error_code.
- **GET /api/home/config:** Feature flag `flash_home_enabled` + refresh policy (no auth).
- **Config (env):** `FLASH_HOME_ENABLED`, `HOME_FAST_CACHE_TTL_SEC`, `WALLET_LIVE_TTL_SEC`, `WALLET_COOLDOWN_SEC`, `HOME_FAST_MAX_ASSETS`, `HOME_FAST_WARN_BYTES`.
- **UI:** storageCache.js, renderHome.js, homeFlash.js; dashboard uses flash pipeline when enabled (localStorage → fast → refresh). “Yenile” triggers wallet/refresh with force=1. “Güncelleniyor…” badge and “Last updated” label.
- **Docs:** docs/sanity/patch_H_flash_home.md, docs/api/home_fast_contract.md, docs/perf_flash_home.md.
- **Tests:** tests/test_home_fast_no_binance.py (fast path must not reference Binance).

---

## [Perf + Consistency Hardening v5.1] – 2026-02-12

### Patch A: Unified lock lease TTL to 10s across codebase
- **app/core/constants.py:** Single source: DEFAULT_LEASE_TTL_SEC=10, LOCK_HEARTBEAT_SEC=3 (env overridable).
- **app/botengine/locks.py:** Imports TTL/heartbeat from app.core.constants; no duplicated literals.
- **docs/sanity/patch_A_lock_ttl.md:** Sanity check + test commands.

### Patch B: Worker-only order placement (web never places orders)
- **app/core/errors.py:** AppError with error_code, error_id, request_id.
- **app/services/binance_spot.py:** Guard at place_order: DATABASE_ROLE/PROCESS_ROLE must be worker; else raise AppError(WORKER_ONLY_OPERATION).
- **app/main.py:** Exception handler for AppError; global 500 response includes error_id.
- **docs/sanity/patch_B_worker_only_trading.md:** Sanity check.

### Patch C: Snapshot payload cap + fields + meta + compression
- **app/api/utils/fields.py:** Allowed snapshot fields validation; INVALID_FIELDS on unknown.
- **app/api/routes.py:** GET /dashboard/snapshot?fields=... ; meta.request_id, server_ms, payload_bytes, trimmed_fields, stale; MAX_SNAPSHOT_BYTES trim.
- **GZipMiddleware** minimum_size=1024 (already present).
- **docs/api/snapshot_contract.md**, **docs/sanity/patch_C_snapshot_payload.md**.

### Patch D: Snapshot query performance (batch queries, executor)
- **app/services/dashboard_snapshot.py:** Batch fetch bots; single query for last_trade per bot (subquery); run_in_executor for sync DB.
- **scripts/perf_snapshot_test.py:** N runs, p50/p95 server_ms.
- **docs/sanity/patch_D_snapshot_perf.md**.

### Patch E: DataHub multi-worker warmup + health gate
- **app/services/data_hub.py:** Warmup on startup (blocking up to X s); get_prices() empty → sync fetch with lock once.
- **GET /api/health/marketdata:** prices_ready flag.
- **docs/sanity/patch_E_datahub_workers.md**.

### Patch F: UI resilience + speed
- **ui/assets/core/apiClient.js:** inFlight reset in finally; AbortController for timeout; exponential backoff hook.
- **ui/assets/dashboard.js:** Snapshot fields per tab (prices,kpis / prices,bots,kpis / wallet,prices); lazy coin logos (IntersectionObserver).
- **docs/sanity/patch_F_ui_perf.md**.

### Patch G: Observability + contract + tooling
- **app/main.py:** request_id middleware (existing); error responses include error_id.
- **docs/observability.md:** Logs + metrics fields.
- **docs/perf_hardening_v5_1.md:** Summary + rollback.

---

## [RAM Probe Snapshots (opt-in RAM_PROBE=1)] – 2026-02-01

### Hedef
- RAM ölçümü: JSONL → `logs/ram_snapshots.log`. Opt-in: `RAM_PROBE=1`.

### Değişiklikler
- **app/observability/ram_probe.py:** `start_ram_probe(component, interval_sec)`, `snapshot_now(component, reason)`, `register_probe_hook(name, fn)`. Snapshot: ts, component, pid, rss_mb, vms_mb, python_heap_estimate_mb, gc (total + dict/list/tuple/str/bytes/asyncio.Task), tracemalloc top 10, hooks. psutil yoksa tek satır hata yazılır; tracemalloc.start(25); daemon thread.
- **app/main.py:** logs/ ve .run/ oluşturuluyor; RAM_PROBE=1 → start_ram_probe("web"); GET `/api/health/ram` (son snapshot).
- **app/botengine/worker_main.py:** logs/ ve .run/ oluşturuluyor; RAM_PROBE=1 → start_ram_probe("worker"); hooks: active_bots, active_tasks, ws_connections, cache_sizes.
- **docs/sanity_check.md:** "RAM Probe Verification" bölümü.
- **docs/ram_probe_runbook.md:** Nasıl açılır, log yeri, alan açıklaması.

---

## [Multi-Asset Rebalance Bot (UI + Backend + Strategy Skeleton)] – 2026-02-02

### Hedef
- Multi-asset rebalance bot: birden fazla coin için hedef dağılım (%100 toplam), rebalance tetikleme (threshold / interval / hybrid).
- UI: Bot yapısı seçiminde yeni kart "Multi-Asset Rebalance Bot"; wizard: Genel (bütçe), Coin sayısı & dağılım, Rebalance kuralları, Onay.
- Backend: MultiAssetRebalanceConfig, validasyon (2–10 coin, toplam %100, benzersiz sembol); bot create’te symbol=MULTI.
- Strategy plugin: multi_asset_rebalance.py (tick skeleton, log REB_MULTI_DECISION); registry’ye kayıtlı. Worker/orchestrator MULTI bot için config + tick desteği.

### Değişiklikler
- **app/botengine/models.py:** MultiAssetRebalanceConfig, config_multi_asset_from_payload.
- **app/api/routes.py:** POST /api/bots/create: strategy_id=multi_asset_rebalance ise assets/rebalance validasyonu, symbol=MULTI, config_json multi config.
- **app/botengine/strategies/multi_asset_rebalance.py:** MultiAssetRebalanceStrategy (strategy_id=multi_asset_rebalance), tick skeleton.
- **app/botengine/strategies/registry.py:** multi_asset_rebalance kaydı.
- **app/botengine/orchestrator.py:** MULTI bot için config (MultiAssetRebalanceConfig), price/base/quote placeholder; is_multi branch.
- **ui/dashboard.html:** dmWizardDca wrapper, dmWizardMulti (adımlar 1–4: Genel, Coin sayısı & dağılım, Rebalance kuralları, Onay).
- **ui/assets/dashboard.js:** BOT_STRUCTURES multi_rebalance kartı; setCreateBotModalWizard, buildMultiAssetRows; collectForm/validateForm multi payload; createBot/createAndStartBot multi error el & displayName.

### Geriye dönük
- Mevcut DCA bot akışı değişmedi. Yeni strateji plugin olarak eklendi.

---

## [Web/API vs Engine Worker Split + Command Queue + Strategy Plugin] – 2026-02-02

### Hedef
- Web ve bot engine ayrı proseslerde; web kapansa bile worker botları çalıştırmaya devam eder.
- Start/stop komutları DB kuyruğu (bot_engine_commands) ile iletilir; web task yaratmaz.
- Multi-tenant: Worker her komutta bot.account_id == command.account_id doğrular.
- Yeni strateji eklemek: Strategy plugin + registry (strategy_id → tick/apply_fill).

### Değişiklikler
- **bot_engine_commands tablosu:** id, created_at, processed_at, account_id, bot_id, command (START|STOP), payload_json, status (PENDING|PROCESSING|DONE|ERROR), error_code, error_id, request_id. schema_guard ile oluşturulur.
- **API start/stop:** Web artık orchestrator.start_bot/stop_bot çağırmıyor; bot.status güncellenir + bot_engine_commands’a INSERT. Response: command_id, bot_status.
- **worker_main.py:** Ayrı entrypoint (`python -m app.botengine.worker_main`). Komut kuyruğunu poll eder (PENDING → PROCESSING → DONE/ERROR), assert_bot_belongs_to_account ile account doğrular, start_bot/stop_bot çağırır. ensure_running_bots ile running botları toplar. WORKER_HEARTBEAT, WORKER_COMMAND_EXECUTED logları.
- **main.py:** Bot engine recovery (ensure_running_bots) kaldırıldı; worker ayrı proses.
- **Strategy plugin:** app/botengine/strategies/base.py (Strategy ABC: tick, apply_fill), registry.py (register, get_strategy, get_strategy_safe), DcaGridTrailingStrategy wrapper. Orchestrator config.strategy_id veya default dca_grid_trailing ile strategy.tick kullanır.
- **start_stop/start.command** (macOS) ve **start_stop/start.bat** (Windows): Web (uvicorn) + Worker (worker_main) ayrı proseslerde başlatır; logs/web.log, logs/worker.log; .run/web.pid, .run/worker.pid.
- **start_stop/stop.command** ve **start_stop/stop.bat**: Sadece Web. **start_stop/stop-worker.command** ve **stop-worker.bat**: Sadece Worker. **start_stop/stop-all.command** ve **stop-all.bat**: Web + Worker ikisini durdurur.

### Geriye dönük
- Eski config’te strategy_id yok → default dca_grid_trailing.
- API path’ler aynı; davranış komut kuyruğu.

---

## [Clean Cycle Boundaries + Compounding Budgets + Dual KPI] – 2026-02-01

### Hedef
- Cycle sınırları tek doğruluk kaynağı: **cycle_ledger** (USDT net, fee-aware).
- Çift yönlü strateji için **base_delta** (adet kazanımı) KPI.
- Cycle tipi: **LONG_SCALP** (buy→sell) / **INVENTORY_REBALANCE** (sell→buy).
- Bileşik büyüme: Cycle bitince **target_budgets** (equity’den hedef base/quote USDT); tur başında komple al-sat yok, sadece order sizing referansı.
- API/UI geriye dönük uyumlu; observability deterministik.

### Değişiklikler
- **pnl_mode default:** Yeni botlarda `cycle_only_fee_aware_v1` (models.py DcaGridTrailingConfig; config_from_ui_payload aynı default).
- **cycle_pnls şeması:** Her CYCLE_END’te eklenen eleman: `cycle_id`, `pnl_usdt_net`, `fees_usdt`, `matched_qty`, `cycle_type`, `base_delta`, `close_reason`, `close_side`, `pnl_mode`, `ts`; `pnl_usdt` geriye uyumluluk için korundu.
- **CYCLE_END meta:** `cycle_type`, `base_delta`, `close_reason`, `close_side`, `pnl_usdt_net` eklendi; `profit_usdt` aynı değerde bırakıldı.
- **cycle_ledger.py:** `get_cycle_type_and_base_delta(close_reason, ledger)` eklendi; trail_profit_sell→LONG_SCALP/base_delta=0, trail_reentry_buy→INVENTORY_REBALANCE/base_delta=buy_qty_total−sell_qty_total.
- **Target budgets:** Cycle bitince `state["target_budgets"]` = equity_usdt, target_quote_usdt, target_base_usdt (config base/quote alloc %); log `BOT_TARGET_BUDGETS_UPDATED`.
- **Order sizing:** `_buy_qty_for_grid` / `_sell_qty_for_grid` target_budgets varsa referansı cap’liyor: min(balance, target*(1−buffer)); komple rebalance order yok.
- **API (performance):** `cycle_type_last`, `cycle_base_delta_last`, `cycle_pnl_last_net`, `target_budgets` eklendi; mevcut alanlar kaldırılmadı.
- **Docs:** docs/sanity_check.md doğrulama adımları ve beklenen loglar.

### Observability
- CYCLE_END: pnl_usdt_net, base_delta, cycle_type, close_reason, matched_qty, fees.
- BOT_TARGET_BUDGETS_UPDATED: equity_usdt, target_quote, target_base, base_balance, quote_balance, price.

---

## [BotEngine Cycle PnL Fix: fee-aware + cycle isolation] – 2026-02-01

### Amaç
- Loglarda `cycle_id=2 profit_usdt=-0.94` gibi nominal kâr varken negatif PnL görülmesi düzeltildi.
- Cycle PnL hesaplaması **yalnız cycle’a ait fill’ler** ile izole edildi; profit-exit **net kâr** (fee dahil) ile kilitlendi.

### Root cause
- Cycle PnL, global inventory (initial allocation) ile cycle trade’lerin karışması (scope bug).
- Profit-exit tetikleyicisi fee-aware değildi → break-even altı satış → negatif PnL.
- CYCLE_END event’inde `last_cycle_profit_usdt` (equity delta) kullanılıyordu; raporlama `cycle_pnls` (realized) kullanıyordu.

### Değişiklikler
- **app/botengine/cycle_ledger.py (yeni)**
  - Cycle Trade Ledger: her cycle için fill listesi; `realized_pnl_quote = sell_quote - buy_quote - fees` (NET, fee-aware).
  - `cycle_ledger_add_fill`, `cycle_ledger_breakeven_price`, `cycle_ledger_trigger_price` (fee-aware tetik).
  - Cycle-scoped reasons: `trail_buy_grid`, `trail_sell_grid`, `trail_reentry_buy`, `trail_profit_sell`; initial_allocation ledger’a yazılmaz.
- **Config (models.py)**
  - `buy_fee_rate`, `sell_fee_rate`, `min_net_profit_rate`, `pnl_mode` (`legacy` | `cycle_only_fee_aware_v1`). Varsayılan `legacy` (rollback için).
- **Execution**
  - ORDER_FILLED sonrası cycle-scoped fill’ler `cycle_ledger_current`’a yazılıyor.
  - CYCLE_END’te PnL kaynağı: `pnl_mode=cycle_only_fee_aware_v1` ise cycle ledger `realized_pnl_quote`; yoksa `realized_pnl_usdt_cycle`.
  - CYCLE_END event artık her zaman **realized PnL** (cycle ledger veya legacy) ile loglanıyor; equity delta kaldırıldı.
- **Strategy (dca_grid_trailing)**
  - Profit-exit: `pnl_mode=cycle_only_fee_aware_v1` ise `trigger_price = breakeven_price * (1 + min_net_profit_rate)`; SELL ancak `last_price >= trigger_price`.
  - Breakeven: `avg_cost * (1 + buy_fee_rate) / (1 - sell_fee_rate)`.
  - Structured log: `BOT_PROFIT_EXIT_EVAL` (scope=cycle, decision=SELL|HOLD, reason=...).
- **cycle_reset_after_fill**
  - Yeni cycle için `cycle_ledger_current` sıfırlanıyor (`symbol` parametresi eklendi).
- **API (performance)**
  - `cycle_pnl_last`, `cycle_id_last`, `pnl_calculation_mode`, `realized_pnl_total`, `fees_total` eklendi (geriye dönük uyumlu).

### Observability
- CYCLE_END meta: `realized_pnl_cycle_net`, `matched_qty`, `buy_quote_total`, `sell_quote_total`, `fee_totals_quote`, `pnl_mode`.
- Log: `BOT_CYCLE_END` (realized_pnl_cycle_net, matched_qty, fees_usdt, pnl_mode).

### Rollback
- Config `pnl_mode=legacy` (varsayılan): eski davranış; cycle ledger kullanılmaz, profit-exit nominal tetik.
- Staging’de `pnl_mode=cycle_only_fee_aware_v1` açılabilir; doğrulama sonrası prod.

### Dokümantasyon
- **docs/sanity_check.md:** Cycle PnL doğrulama adımı (opsiyonel).
- **fee_asset:** Execution’da fee USDT’ye çevriliyor; cycle ledger’da `fee_asset` USDT kabul ediliyor, değilse WARNING log + TODO.

---

## [Fix: Initial allocation budget check + logging] – 2026-01-29

### Amaç
- Initial allocation sırasında execution loglarında `budget_before=0 required=0 available=0` görünmesi (yanıltıcı) düzeltildi. required/available artık doğru referanslardan hesaplanıyor.

### Root cause
- `check_virtual_budget` geçtiğinde `(True, "", None, None)` dönüyordu; logda `required or 0`, `available or 0` ile 0 basılıyordu. Ayrıca required hesabı `qty` üzerinden gidiyordu; initial allocation BUY’da `quantity` None olduğu için yanlış değer kullanılabiliyordu.

### Değişiklikler
- **execution.py**
  - Initial allocation BUY için **required** doğru formül: `required = float(quote_qty) * (1.0 + fee_buffer_pct)`; `quote_qty` None/0 ise SKIP + `BOT_EXECUTION_SKIP skip_reason=INVALID_ACTION`.
  - **available** kaynağı: Binance gerçek bakiye (quote free). `get_account_balances()` ile alınan USDT free kullanılıyor; `available + eps < required` ise order atılmıyor, `skip_reason=INSUFFICIENT_QUOTE`.
  - Log düzeltmesi: `BOT_INITIAL_ALLOC_BUDGET` artık `quote_asset=USDT quote_qty=.. fee_buffer=.. required=.. available=.. decision=EXECUTE|SKIP`; `budget_before=0` kaldırıldı.
  - Ek debug loglar (INFO): `BOT_CFG` (bot_id, symbol, budget, base_pct, quote_pct, fee_buffer), `BOT_BALANCES` (bot_id, base_asset, base_free, quote_asset, quote_free), `BOT_REQUIRED` (bot_id, quote_qty, required, available, decision).
- **tests/test_execution_initial_alloc.py**
  - `required = quote_qty * (1 + fee_buffer)` formül testi; qty None iken required 0 olmuyor.
  - available < required iken execution SKIP ve order placement çağrılmıyor (mock ile doğrulandı).
  - quote_qty None/0 iken INVALID_ACTION skip.

### Dokümantasyon
- **SANITY_CHECK.md:** Bot start → initial allocation → log doğrulama adımı eklendi.
- **docs/sanity_checks.md:** Aynı adım (bot start, initial allocation, logs verify) eklendi.

---

## [Bot Engine Multi-Bot – Symbol Lock, Virtual Wallet, Slippage] – 2026-01-28

### Amaç
- Aynı account’ta birden fazla bot (aynı/farklı sembol) güvenle çalışsın; emirler MARKET; tetik anında market basılsın.

### Değişiklikler
- **DB (schema_guard):** `symbol_locks` (account_id, symbol lease lock), `bot_virtual_wallet` (virtual_base, virtual_quote).
- **locks.py:** `try_acquire_symbol_lock`, `release_symbol_lock` (DB lease, TTL 60s). Lock alamayan bot `LOCK_BUSY` event, trade yok.
- **virtual_wallet.py:** `get_virtual_wallet`, `ensure_virtual_wallet`, `update_virtual_after_fill`, `check_virtual_budget`. BUY/SELL öncesi yetersiz bütçe → `INSUFFICIENT_VIRTUAL_FUNDS` event.
- **Orchestrator:** Virtual wallet ensure + state balance feed; symbol lock acquire → run_actions → release. Delete’te lock release + virtual wallet silme.
- **Execution:** Budget check; fill sonrası `update_virtual_after_fill`; slippage guard → `SLIPPAGE_WARN` event.
- **Strategy:** Aksiyonlara `trigger_price` eklendi (slippage için).
- **Config:** `bot_budget_usdt` alias; `max_slippage_pct` kullanılıyor.
- **Events:** `LOCK_BUSY`, `INSUFFICIENT_VIRTUAL_FUNDS`, `SLIPPAGE_WARN` (ileride `RECONCILE_WARN` opsiyonel).

### Dokümantasyon
- **docs/BOTENGINE_MULTIBOT_PLAN.md:** Dosya planı, DB şeması, akış, edge-case, performans.
- **docs/CHANGELOG_BOTENGINE_MULTIBOT.md**, **docs/SANITY_CHECK_BOTENGINE_MULTIBOT.md**.

### Not
- API değişmedi (`/api/bots-engine` create/start/stop/delete). Tek worker kuralı korunuyor; `run.sh` multibot DB lock notu eklendi.

---

## [Bot Engine Prod Fix Pack – Patch 1–3] – 2026-01-28

### Amaç
- Engine fill’lerin `trades` tablosuna yazılması; UI–API sözleşmesinin tekilleştirilmesi; start/stop/delete/detail akışının düzeltilmesi; log standardı ve staleness guard.

### Patch-1 (P0): Trade ledger + Trades endpoint
- **DB:** `trades` tablosuna `order_id`, `client_order_id`, `symbol` kolonları (schema_guard).
- **Ledger:** `record_trade` idempotent (`order_id` ile duplicate engeli); `(Trade, bool)` döner.
- **Execution:** Her fill sonrası `Ledger.record_trade`; `BOT_TRADE_RECORDED` log.
- **API:** `GET /api/bots-engine/{id}/trades` artık `symbol` / `order_id` döner.

### Patch-2 (P0): UI/Routes contract
- **Create:** UI `POST /api/bots-engine`, `config_json` object. Legacy `POST /api/bots/create` engine create’e yönlendiriliyor.
- **Detail:** UI `GET /api/bots-engine/{id}`. Engine state/grid kullanılıyor.
- **Delete:** UI `POST /api/bots-engine/{id}/delete`. Legacy `DELETE /api/bots/{id}` → `delete_bot_fully` (stop + state/events/trades temizliği).
- **Stop:** `POST /api/bots/{id}/stop` orchestrator `stop_bot` çağırıyor.

### Patch-3 (P1): Stabilite + log + staleness
- **Log:** Her tick `BOT_TICK bot_id=... mode=... price=... next_wake=... actions=...`; her aksiyon öncesi `BOT_ACTION ...`.
- **Staleness:** Fiyat yok/stale iken `no price (stale or missing)` event + log, trade yok.
- **Run:** `run.sh` tek worker (no `--reload` / `--workers`) notu.

### Dokümantasyon
- **docs/CHANGELOG_BOTENGINE_PATCH1.md**, **PATCH2.md**, **PATCH3.md**
- **docs/SANITY_CHECK_BOTENGINE_PATCH1_TRADES.md**, **PATCH2_UI_CONTRACT.md**, **PATCH3_STABILITY.md**

---

## [Admin Hata Logu – Sıfırla + sadece yeni hatalar] – 2026-01-27

### Amaç
- "Hataları sıfırla" sonrası liste **tamamen temiz** olsun; "Test hatası oluştur" ile yalnızca yeni hata görünsün, **Toplam 1 hata**.

### Değişiklikler
- **ui/assets/admin.js**
  - `state.errorLogsResetAfterId`: Sıfırdan sonra yalnızca `id > resetAfterId` olan hatalar listelenir; toplam = listelenen sayı.
  - **resetErrorLogs (async):** Mevcut hatalar `GET /api/admin/error-logs` ile çekilir, hepsi `dismissedErrorSignatures` / `dismissedErrorIds` ile dismiss edilir. `GET /api/admin/error-logs/count` → `latest_id` alınır, `errorLogsResetAfterId = latest_id` atanır. Liste boşaltılır, toast "Hatalar sıfırlandı."
  - **loadErrorLogs:** `errorLogsResetAfterId != null` ise ek filtre: `id > errorLogsResetAfterId`. Yalnızca sıfırdan sonra oluşan hatalar gösterilir.
  - **updateErrorLogsTotalDisplay(displayedCount):** Reset modunda toplam = `displayedCount` (veya DOM’daki `.error-log-item` sayısı). "Toplam X hata" buna göre güncellenir.

### Sonuç
- Hataları sıfırla → Liste tertemiz.
- Test hatası oluştur → 1 satır, **Toplam 1 hata**. Eski hatalar tekrar listelenmez.

### Dokümantasyon
- **SANITY_CHECK.md:** Tarih 2026-01-27, proje güncel2; "Admin Hata Logları" bölümü ve manuel test adımı eklendi.
- **CHANGELOG.md:** Bu girdi eklendi.
- **docs/security.md:** Güvenlik tasarımı ve tehdit modeli dokümanı (mevcut durum envanteri, P0/P1/P2 riskler).

---

## [Güvenlik: Hesap yetkisi – URL asla yetki kaynağı değil] – 2026-01-26

### Amaç
- Dashboard `?account_code=...` ile açılabiliyordu; yetki tamamen session + DB ownership ile doğrulanmalı.
- Bazı endpoint'lerde **auth/ownership kontrolü yoktu**; eklenerek başka hesabın verisine erişim kapatıldı.

### Backend
- **app/api/auth.py**
  - `require_account_access`: 403 cevabı `detail={"error_code": "FORBIDDEN", "message": "..."}` standardına çekildi.
  - **get_account_or_403(current, account_id, db):** Hesabı DB'den yükler; `account.user_id != current["user_id"]` ve admin değilse 403. Yetki kaynağı her zaman session'daki user_id.
- **app/api/routes.py**
  - **GET /api/binance/wallet**, **GET /api/binance/open-orders**, **GET /api/binance/fee-rates**, **GET /api/binance/order-history**, **GET /api/binance/spot_modal_bootstrap:** `Depends(require_auth)` ve `get_account_or_403(current, account_id, db)` eklendi (önceden auth yoktu).
  - **GET /api/accounts/by-code/{account_code}**, **GET /api/accounts/{account_id}**, **GET /api/accounts/{account_id}/settings:** Ownership kontrolü `get_account_or_403` ile yapılıyor; 404/403 gövdesi error_code + message.
- **app/api/spot_routes.py**
  - **GET /api/spot/quick_data**, **POST /api/spot/order**, **GET /api/spot/commission**, **GET /api/spot/price:** `Depends(require_auth)` ve `get_account_or_403(current, account_id, db)` eklendi.

### Dokümantasyon
- **docs/SECURITY_ACCOUNT_OWNERSHIP.md:** Hesap yetkisi kuralları, güncellenen endpoint listesi, test senaryoları.

### Test
- URL'ye başka kullanıcının account_code’u yazıldığında → 403.
- Token olmadan wallet/open-orders/spot → 401.
- Token ile başka account_id ile wallet/open-orders/spot → 403.

---

## [Üst ticker şeridi canlı fiyat – /api/pricing/summary] – 2026-01-25

### Eklenen
- **Backend**
  - **GET /api/pricing/summary**: Üst ticker bar için tek endpoint.
  - Yanıt alanları: `ts`, `usdtry`, `eurtry`, `gbptry`, `btcusd`, `ethusd`, `xauusd`, `gram_altin_tl`, `ons_altin_usd`, `source_status` (fx, metals, crypto: live|stale|error).
  - **app/services/pricing_summary.py**: FX (exchangerate.host), metals (Binance PAXGUSDT), crypto (DataHub → Binance REST). Cache TTL: FX 120s, Metals 120s, Crypto 2s. In-flight dedupe (asyncio.Lock). httpx AsyncClient reuse, timeout 8s/connect 3s.
  - **app/api/pricing_routes.py**: Router prefix `/api/pricing`, route `/summary`.
- **Frontend**
  - **ui/assets/ticker.js**: Artık `GET /api/pricing/summary` kullanıyor (`apiClient.get`), `intervalRegistry.start("pricing:summary", refresh, 2000, "header")`. Değer yoksa "—", 0 yazılmıyor. Format: TRY 4 ondalık, BTC/ETH/gram/ons 2 ondalık. Hata durumunda son değerler korunuyor.

### Kullanılan API kaynakları
- **Crypto (BTC/USD, ETH/USD):** DataHub cache (BTCUSDT, ETHUSDT); yoksa Binance `GET /api/v3/ticker/price?symbol=BTCUSDT|ETHUSDT`.
- **FX (USD/TRY, EUR/TRY, GBP/TRY):** `https://api.exchangerate.host/latest?base=USD&symbols=TRY,EUR,GBP` (EUR/TRY = USD/TRY÷USD/EUR, GBP/TRY = USD/TRY÷USD/GBP).
- **Metals (Ons Altın USD):** Binance `PAXGUSDT` (1 PAXG ≈ 1 troy ons). Gram Altın TL = `xauusd * usdtry / 31.1034768`.

### Teknik
- Backend’de aynı anda gelen istekler tek upstream çağrı (in-flight lock).
- Frontend 2 sn’de bir poll eder; backend cache sayesinde dış API’ler sık çağrılmaz.

---

## [Wallet TRY bug fix – tek kaynak + FX guard] – 2026-01-25

### Root cause (TRY bug)
- Cüzdan tablosunda "TRY" satırı bazen **kur değeri** (örn. 27.81 USD/TRY) ile bakiye gibi görünüyordu; toplam şişiyordu (416 yerine ~1620).
- Backend zaten sadece Binance `balances` döndürüyordu; TRY için USD formülü `amount/price` olarak düzeltilmişti. Kalan risk: Binance’ten gelen TRY bakiyesi yanlış yorumlanabilir veya eski bir bug’dan kalan veri.

### Fixed
- **Backend (routes.py)**:
  - `_wallet_response`: TRY/EUR/GBP için **FX guard**: `total_usd > total_qty` ise satır eklenmez (1 TRY < 1 USD; böyle veri FX contamination).
  - Wallet listesi **tek kaynak**: Sadece Binance `/api/v3/account` balances; kur/ticker asla eklenmez.
  - `/api/binance/wallet`: **TTL cache 1.5s** + **async lock** (in-flight dedupe); `_fetch_wallet_uncached` ile tek upstream çağrı.
  - Price fallback’te USDT{asset} (TRY için) kontrolü eklendi.
- **Frontend (dashboard.js)**:
  - Cüzdan satırları **yalnızca** `assetsState.wallet.assets` (API’den); coin list / FX ticker ile merge yok.
  - **FX guard**: `isWalletAssetSuspiciousFx()` – TRY/EUR/GBP ve `total_usd > total_qty` ise satır render edilmez.
  - `renderAssetsList` ve `renderVarliklarList` bu filtreyi kullanır.

### Technical
- `FIAT_ASSETS = {"TRY", "EUR", "GBP"}` backend’de; `WALLET_FX_ASSETS` frontend’de.
- Wallet response cache: `_wallet_response_cache`, `WALLET_RESPONSE_CACHE_TTL = 1.5`, `_wallet_cache_lock`.

---

## [Binance Integration – Mega Prompt] – 2026-01-25

### Added
- **app/services/binance_spot.py**: Binance Spot API modülü
  - `BINANCE_API`, `BINANCE_TESTNET` base URL’ler
  - `_public_get`, `_signed_request` (timestamp, HMAC SHA256, X-MBX-APIKEY)
  - 429/418 için exponential backoff + retry
  - `get_wallet`, `get_open_orders`, `fetch_exchange_info`, `ticker_price_all`, `ticker_24h_all`, `place_order`, `get_trade_fee`
  - httpx.AsyncClient kullanımı
- **app/services/binance_assets.py**: Hesap anahtarları
  - `BinanceKeys` (api_key, api_secret, testnet)
  - `get_account_keys(account_id, db)` – decrypt, ACCOUNT_NOT_FOUND / ACCOUNT_KEYS_MISSING
  - `fetch_prices_map`, `_convert_to_usd` (finance_snapshot uyumu)
- **Request ID middleware** (main.py): Her istek için `request_id`, cevap header’ı `X-Request-Id`
- **Hata standardı**: Binance hatalarının eşlenmesi
  - 401/403 → BINANCE_AUTH
  - 429/418 → BINANCE_RATE_LIMIT
  - 5xx → BINANCE_UPSTREAM_ERROR
  - `_map_binance_error()` routes içinde kullanılıyor

### Changed
- **DataHub (data_hub.py)**:
  - `update_prices()`: REST ile `/api/v3/ticker/price` (NO-OP kaldırıldı)
  - `update_ticker_24h()`: `/api/v3/ticker/24hr` ile fiyat/değişim/hacim güncelleme
  - `update_coin_list()`: 24h verisiyle coin listesi (USDT, quoteVolume sıralı)
  - `update_all_symbols()`: `/api/v3/exchangeInfo` ile sembol listesi
  - Arka plan döngüsü: fiyat ~1.5s, 24h 5s, coin_list/symbols 600s
  - `get_hub_data()`: `data_status: "live"`, `ws_status: "rest"` (stale/binance_disabled kaldırıldı)
- **/api/binance/wallet**: Gerçek signed `/api/v3/account`, `_wallet_response` ile assets/total_usd/free_usd/locked_usd
- **/api/binance/open-orders**: Gerçek signed `/api/v3/openOrders`
- **/api/dashboard/summary**: `spot_balance_usd` wallet total_usd ile dolduruluyor (2s cache)
- **SpotEngine (spot_engine.py)**: Fiyat önceliği DataHub → price_hub → public ticker
- **Frontend pollWallet (dashboard.js)**: `GET /api/binance/wallet?account_id=...` çağrısı, gelen veri `assetsState.wallet`’a yazılıyor

### Fixed
- NO-OP’ler kaldırıldı (boş cüzdan / boş emir listesi artık yok; gerçek API kullanılıyor)
- DataHub sürekli “stale / binance_disabled” dönme sorunu giderildi
- Dashboard’da spot bakiye her zaman 0 görünme sorunu giderildi (wallet cache ile)
- Cüzdan sekmesinde veri gelmeme sorunu giderildi (pollWallet API’e bağlandı)

### Technical
- Wallet total_usd cache: routes’ta `_wallet_total_cache` (TTL 2s) dashboard summary için
- Binance hata dönüşleri `error_code` ve uyumlu `detail` ile HTTPException

---

## [Prompt #2 – WebSocket DataHub + Ortak Binance Katmanı] – 2026-01-25

### Added
- **app/services/binance_ws.py**: Binance WebSocket combined stream
  - `!miniTicker@arr` → DataHub prices + mini map
  - Reconnect + exponential backoff + jitter; ping/heartbeat; clean stop
  - Live: `wss://stream.binance.com:9443/stream?streams=!miniTicker@arr`
  - Testnet URL parametreli (testnet=True)
- **DataHub WebSocket**: `start_ws(testnet=False)`, `stop_ws()`, `_on_ws_message()`
  - `ws_status`: "connected" | "reconnecting" | "disabled" | "rest"
  - `last_ws_update_ts`; REST price interval gevşetildi (10s) when WS active
  - `get_hub_data()`: `data_status` / `ws_status` gerçek değerler
- **binance_spot.py ortak ağ geçidi**:
  - `public_get_json()`, `signed_json()`, `build_signed_params()` (test edilebilir)
  - Loglama: endpoint, method, latency_ms, attempt, request_id (secrets yok)
  - Sync gateway: `_sync_public_get()`, `_sync_signed_request()` (botlar için)
- **app/services/binance_client.py**: Bot’lar için sync facade
  - `BinanceClient(api_key, api_secret, testnet)` → tek kapı binance_spot
  - `get_ticker_price`, `get_exchange_info`, `place_market_order`, `get_balance`
  - `BinanceAPIError`, `InsufficientBalanceError`, `InvalidAPIKeyError`, `NetworkError`
- **requirements.txt**: `websockets>=12.0`

### Changed
- **data_hub.py**: WS callback ile `prices` + `_mini_ws` güncellenir; `_build_mini_map` WS öncelikli
- **main.py**: Startup’ta `data_hub.start_ws(testnet=False)`; shutdown’da `stop_background_updates` içinde WS stop
- **finance_trade_sync.py**: exchangeInfo public (fetch_exchange_info), myTrades signed (_signed_request)
- **spot_engine.py**: ImportError fallback kaldırıldı; doğrudan binance_assets / binance_spot import

### Technical
- Tüm Binance HTTP (public + signed) binance_spot üzerinden; botlar binance_client → binance_spot
- REST fallback: WS yoksa veya kesilince DataHub REST loop aynen çalışır
