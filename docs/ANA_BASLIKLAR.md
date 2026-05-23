# Ana başlıklar — dosya dizini

**Güncelleme:** 2026-05-23

Tüm proje dosyaları ana kategorilere ayrılmıştır. Kod yolları değişmez.

Otomatik üretim: `python scripts/sync_ana_basliklar.py`

İlgili: [CODE_TREE.md](CODE_TREE.md) · [INDEX.md](INDEX.md)

---

## 01 — Spec ve yapılandırma

*7 dosya*

```
.env.example
.gitattributes
.gitignore
README.md
TRADE_TRAILING_MASTER_SPEC.md
requirements.txt
shared/README.md
```

## 02 — Çalıştırma

*14 dosya*

```
ops/Kurulum.bat
ops/deploy.sh
ops/guncelle.bat
ops/restart.bat
ops/restart.command
ops/run.sh
ops/start
ops/start.bat
ops/start.command
ops/stop.bat
ops/stop.command
run.sh
start.bat
start.command
```

## 03 — Backend (çekirdek)

*29 dosya*

```
app/boot_id.py
app/core/__init__.py
app/core/anomaly_codes.py
app/core/auth/__init__.py
app/core/auth/token_utils.py
app/core/config.py
app/core/constants.py
app/core/errors.py
app/core/logging_helpers.py
app/core/security/__init__.py
app/core/security/rate_limiter.py
app/db/__init__.py
app/db/base.py
app/db/models.py
app/db/schema_guard.py
app/db/session.py
app/error_logging.py
app/main.py
app/middleware/__init__.py
app/middleware/csrf.py
app/middleware/request_metrics.py
app/middleware/security_headers.py
app/observability/__init__.py
app/observability/metrics_stubs.py
app/observability/ram_probe.py
app/server_state.py
app/utils/__init__.py
app/utils/account_code.py
app/utils/tz_utils.py
```

## 03b — API

*19 dosya*

```
app/api/__init__.py
app/api/admin.py
app/api/auth.py
app/api/bots_engine.py
app/api/bots_v2.py
app/api/data_hub_routes.py
app/api/finance.py
app/api/finance_reports.py
app/api/leaderboard.py
app/api/market_data_routes.py
app/api/pricing_routes.py
app/api/routes/__init__.py
app/api/routes/dashboard_bootstrap.py
app/api/routes/home.py
app/api/routes.py
app/api/spot_routes.py
app/api/utils/__init__.py
app/api/utils/fields.py
app/api/ws.py
```

## 04 — Bot Engine

*26 dosya*

```
app/botengine/__init__.py
app/botengine/adapters/__init__.py
app/botengine/adapters/binance_adapter.py
app/botengine/bot_run.py
app/botengine/cycle_ledger.py
app/botengine/errors.py
app/botengine/execution.py
app/botengine/grid_view.py
app/botengine/intent_ledger.py
app/botengine/kill_switch.py
app/botengine/locks.py
app/botengine/models.py
app/botengine/orchestrator.py
app/botengine/reconcile.py
app/botengine/risk.py
app/botengine/scheduler.py
app/botengine/state_store.py
app/botengine/strategies/__init__.py
app/botengine/strategies/base.py
app/botengine/strategies/dca_grid_trailing.py
app/botengine/strategies/multi_asset_rebalance.py
app/botengine/strategies/registry.py
app/botengine/strategies/trdca_pro.py
app/botengine/user_stream.py
app/botengine/virtual_wallet.py
app/botengine/worker_main.py
```

## 05 — Servisler

*25 dosya*

```
app/services/__init__.py
app/services/audit.py
app/services/binance_assets.py
app/services/binance_client.py
app/services/binance_metrics.py
app/services/binance_spot.py
app/services/binance_weight.py
app/services/binance_ws.py
app/services/cache.py
app/services/copytrading_sanitize.py
app/services/dashboard_snapshot.py
app/services/data_hub.py
app/services/encryption.py
app/services/finance_pnl_calculator.py
app/services/finance_snapshot.py
app/services/finance_trade_sync.py
app/services/leaderboard_service.py
app/services/perf_chart_state.py
app/services/pnl_service.py
app/services/price_hub.py
app/services/pricing.py
app/services/pricing_summary.py
app/services/spot_engine.py
app/services/test_account.py
app/services/transaction_history_service.py
```

## 05b — Legacy bot

*12 dosya*

```
app/bot/__init__.py
app/bot/binance_adapter_v2.py
app/bot/dca_engine_v3.py
app/bot/dca_worker_v3.py
app/bot/engine.py
app/bot/engine_v2.py
app/bot/ledger.py
app/bot/manager.py
app/bot/models.py
app/bot/models_v2.py
app/bot/trailing_engine.py
app/bot/worker_v2.py
```

## 06 — Web paneli

*163 dosya*

```
ui/admin.html
ui/assets/admin-login-theme.css
ui/assets/admin.js
ui/assets/api.js
ui/assets/appBoot.js
ui/assets/binance-colors.css
ui/assets/blink.css
ui/assets/chart.js
ui/assets/coins/1INCH.png
ui/assets/coins/AAVE.png
ui/assets/coins/ACA.png
ui/assets/coins/ADA.png
ui/assets/coins/ALGO.png
ui/assets/coins/ANKR.png
ui/assets/coins/API3.png
ui/assets/coins/APT.png
ui/assets/coins/ARB.png
ui/assets/coins/ARK.png
ui/assets/coins/ATOM.png
ui/assets/coins/AUDIO.png
ui/assets/coins/AVAX.png
ui/assets/coins/AXL.png
ui/assets/coins/AXS.png
ui/assets/coins/BAND.png
ui/assets/coins/BAT.png
ui/assets/coins/BB.png
ui/assets/coins/BCH.png
ui/assets/coins/BNB.png
ui/assets/coins/BONK.png
ui/assets/coins/BTC.png
ui/assets/coins/BUSD.png
ui/assets/coins/CELO.png
ui/assets/coins/CFX.png
ui/assets/coins/CHZ.png
ui/assets/coins/CKB.png
ui/assets/coins/COMP.png
ui/assets/coins/CRV.png
ui/assets/coins/DAI.png
ui/assets/coins/DASH.png
ui/assets/coins/DCR.png
ui/assets/coins/DENT.png
ui/assets/coins/DGB.png
ui/assets/coins/DOGE.png
ui/assets/coins/DOT.png
ui/assets/coins/DYDX.png
ui/assets/coins/EGLD.png
ui/assets/coins/ENJ.png
ui/assets/coins/ENS.png
ui/assets/coins/ETC.png
ui/assets/coins/ETH.png
ui/assets/coins/FDUSD.png
ui/assets/coins/FET.png
ui/assets/coins/FIL.png
ui/assets/coins/FIO.png
ui/assets/coins/FLOKI.png
ui/assets/coins/FLUX.png
ui/assets/coins/FRAX.png
ui/assets/coins/GALA.png
ui/assets/coins/GLMR.png
ui/assets/coins/HBAR.png
ui/assets/coins/ICP.png
ui/assets/coins/ICX.png
ui/assets/coins/IMX.png
ui/assets/coins/INJ.png
ui/assets/coins/JASMY.png
ui/assets/coins/JUP.png
ui/assets/coins/KAVA.png
ui/assets/coins/KNC.png
ui/assets/coins/KSM.png
ui/assets/coins/LDO.png
ui/assets/coins/LINK.png
ui/assets/coins/LRC.png
ui/assets/coins/LTC.png
ui/assets/coins/LUNA.png
ui/assets/coins/LUNC.png
ui/assets/coins/MANA.png
ui/assets/coins/MOVR.png
ui/assets/coins/NEAR.png
ui/assets/coins/ONE.png
ui/assets/coins/ONT.png
ui/assets/coins/PENDLE.png
ui/assets/coins/PEPE.png
ui/assets/coins/PYUSD.png
ui/assets/coins/QTUM.png
ui/assets/coins/RENDER.png
ui/assets/coins/ROSE.png
ui/assets/coins/RUNE.png
ui/assets/coins/RVN.png
ui/assets/coins/SAND.png
ui/assets/coins/SEI.png
ui/assets/coins/SKL.png
ui/assets/coins/SNX.png
ui/assets/coins/SOL.png
ui/assets/coins/STEEM.png
ui/assets/coins/STORJ.png
ui/assets/coins/SUI.png
ui/assets/coins/SUSHI.png
ui/assets/coins/THETA.png
ui/assets/coins/TON.png
ui/assets/coins/TRX.png
ui/assets/coins/TUSD.png
ui/assets/coins/UNI.png
ui/assets/coins/USDC.png
ui/assets/coins/USDP.png
ui/assets/coins/USDT.png
ui/assets/coins/VET.png
ui/assets/coins/WBTC.png
ui/assets/coins/WIF.png
ui/assets/coins/WLD.png
ui/assets/coins/XLM.png
ui/assets/coins/XRP.png
ui/assets/coins/XTZ.png
ui/assets/coins/YFI.png
ui/assets/coins/ZEC.png
ui/assets/coins/ZEN.png
ui/assets/coins/ZIL.png
ui/assets/coins/ZRX.png
ui/assets/components.js
ui/assets/core/apiClient.js
ui/assets/core/errorReporter.js
ui/assets/core/intervalRegistry.js
ui/assets/core/maintenance.js
ui/assets/dashboard-login-theme.css
ui/assets/dashboard.css
ui/assets/dashboard.js
ui/assets/design.css
ui/assets/homeFlash.js
ui/assets/js/maintenanceOverlay.js
ui/assets/login.css
ui/assets/perf_chart_canvas_history.js
ui/assets/perf_chart_rebuild.js
ui/assets/perf_chart_tv.js
ui/assets/renderHome.js
ui/assets/seo.css
ui/assets/services/financeService.js
ui/assets/services/marketDataService.js
ui/assets/spot_engine.js
ui/assets/storageCache.js
ui/assets/stores/botStore.js
ui/assets/stores/dashboardStore.js
ui/assets/stores/financeStore.js
ui/assets/stores/marketStore.js
ui/assets/theme.css
ui/assets/ticker.css
ui/assets/ticker.js
ui/assets/ui.css
ui/assets/utils/coinLogo.js
ui/assets/utils/trTime.js
ui/bot.html
ui/bot_multi.html
ui/chart.html
ui/dashboard.html
ui/index.html
ui/login.html
ui/logs.html
ui/maintenance.html
ui/robots.txt
ui/seo-index.html
ui/server_manager.html
ui/sitemap.xml
ui/splash.html
ui/trader-trailing.html
ui/vendor/lightweight-charts.standalone.production.js
```

## 07 — Manager paneli

*8 dosya*

```
manager_server/__init__.py
manager_server/__main__.py
manager_server/app.py
manager_server/reason_engine.py
manager_server/state.py
manager_server/ui/assets/manager.css
manager_server/ui/assets/manager.js
manager_server/ui/index.html
```

## 08 — Scriptler

*25 dosya*

```
scripts/README.md
scripts/annotate_file_headers.py
scripts/binance_verify_order.py
scripts/binance_weight_sim.py
scripts/fetch_binance_coin_logos.py
scripts/fetch_coin_logos.sh
scripts/fix_cgi_once.py
scripts/fix_manager_cgi.py
scripts/intent_audit.py
scripts/local_web_worker_helper.py
scripts/perf_300_bots_sim.py
scripts/perf_snapshot_test.py
scripts/ram_analyze.py
scripts/ram_leak_test.py
scripts/ram_stress_scenarios.py
scripts/reconcile_now.py
scripts/restart_server.py
scripts/restart_server_win.py
scripts/run.sh
scripts/run_fix_crlf.bat
scripts/setup_env_master_key.py
scripts/sync_ana_basliklar.py
scripts/sync_module_meta.py
scripts/verify_auth_loop_fix.py
scripts/win_launcher.py
```

## 09 — Deploy

*8 dosya*

```
deploy/DEGISKEN_DOSYALAR.txt
deploy/DEPLOY.md
deploy/SABIT_DOSYALAR.txt
deploy/deploy.bat
deploy/deploy.sh
deploy/deploy_windows.sh
deploy/nginx-tradertrailing-server.conf
deploy/show-nginx-config.bat
```

## 10 — Testler

*11 dosya*

```
tests/test_auth_security_hardening.py
tests/test_auth_session_shared.py
tests/test_binance_reconcile.py
tests/test_cycle_ledger.py
tests/test_home_fast_no_binance.py
tests/test_intent_idempotency.py
tests/test_locks_ttl.py
tests/test_pnl_trailing_dca.py
tests/test_snapshot_fields_validation.py
tests/test_snapshot_meta_present.py
tests/test_worker_only_order_guard.py
```

## 11 — Dokümantasyon

*47 dosya*

```
docs/ANA_BASLIKLAR.md
docs/CODE_TREE.md
docs/INDEX.md
docs/STRUCTURE.md
docs/api/home_fast_contract.md
docs/api/snapshot_contract.md
docs/archive/PROJECT_BOTENGINE_XRAY.md
docs/archive/PROJECT_TREE.md
docs/archive/README.md
docs/archive/TRDCA_STRATEGY_AUDIT_vFinal2.md
docs/archive/changelog_auth_fix.md
docs/archive/done_checklist_template.md
docs/archive/incidents/ADMIN_TABS_PERF_MOBILE_DEBUG_DOSSIER.md
docs/archive/incidents/INCIDENT_ROOTCAUSE_REPORT.md
docs/archive/incidents/LIVE_TRADING_EXECUTION_FORENSIC_ANALYSIS_v1.md
docs/archive/incidents/MANAGER_KAPANMA_ANALIZI.md
docs/archive/incidents/SANITY_CHECK_BOTENGINE_STATE_PERSIST.md
docs/archive/incidents/SANITY_CHECK_CYCLE_PNL.md
docs/archive/incidents/binanceverirapor.md
docs/archive/incidents/debug/perf_chart_cursor_dump.md
docs/archive/incidents/ram_root_cause_report.md
docs/archive/misc/ARCHITECTURE.md
docs/archive/misc/CHANGELOG.md
docs/archive/misc/GÜNCEL_README.md
docs/archive/misc/INTERNET_ACCESS.md
docs/archive/misc/README.md
docs/archive/misc/README_WINDOWS.md
docs/archive/misc/TRAILING_DCA_PNL_SYSTEM_SPEC.md
docs/archive/misc/auth_login_stability_hardening.md
docs/archive/misc/changelog_perf_hardening.md
docs/archive/misc/observability.md
docs/archive/misc/perf_flash_home.md
docs/archive/misc/perf_hardening_report.md
docs/archive/misc/perf_hardening_v5_1.md
docs/archive/misc/ram_probe_runbook.md
docs/archive/misc/sanity_check.md
docs/archive/sanity-patches/patch_A_lock_ttl.md
docs/archive/sanity-patches/patch_B_worker_only_trading.md
docs/archive/sanity-patches/patch_C_snapshot_payload.md
docs/archive/sanity-patches/patch_D_snapshot_perf.md
docs/archive/sanity-patches/patch_E_datahub_workers.md
docs/archive/sanity-patches/patch_F_ui_perf.md
docs/archive/sanity-patches/patch_H_flash_home.md
docs/engine/BOTENGINE_RUNBOOK.md
docs/engine/BOTENGINE_STATE_MODEL.md
docs/runtime.md
docs/security_hardening.md
```

## 12 — Çalışma zamanı (gitignore)

*47 dosya*

```
.run/audit.json
.run/diagnosis.json
.run/engine.metrics.json
.run/errors_since_reset_manager.json
.run/errors_since_reset_web.json
.run/errors_since_reset_worker.json
.run/html.pid
.run/locks.json
.run/log_reset_manager
.run/log_reset_manager_errors
.run/log_reset_manager_warnings
.run/log_reset_web
.run/log_reset_web_errors
.run/log_reset_web_warnings
.run/log_reset_worker
.run/log_reset_worker_errors
.run/log_reset_worker_warnings
.run/manager.pid
.run/manager_audit.log
.run/restart_helper.log
.run/server.log
.run/server.pid
.run/server_locks.json
.run/web.metrics.json
.run/web.pid
.run/web.started_at
.run/worker.pid
.run/worker_active_bots
.run/worker_loop_count
.run/worker_main_loop_count
logs/app.log
logs/app.log.1
logs/app.log.2
logs/app.log.3
logs/app.log.4
logs/app.log.5
logs/html.log
logs/manager.log
logs/manager_backend.log
logs/ram_report.json
logs/ram_snapshots.log
logs/web.log
logs/worker.log
shared/.env
shared/.run/.gitkeep
shared/data/.gitkeep
shared/logs/.gitkeep
```

## 13 — Marketing sitesi (opsiyonel)

*22 dosya*

```
marketing/.gitignore
marketing/.htaccess
marketing/.well-known/security.txt
marketing/README.md
marketing/_headers
marketing/bg-candles.svg
marketing/calistir.bat
marketing/calistir.command
marketing/en.html
marketing/index.html
marketing/restart.bat
marketing/robots.txt
marketing/script.js
marketing/sitemap.xml
marketing/start
marketing/start.bat
marketing/start.py
marketing/stop.bat
marketing/stop.command
marketing/style.css
marketing/vercel.json
marketing/visits.json
```

## 99 — Diğer

*4 dosya*

```
.cursor/rules/master-spec-ground-truth.mdc
.cursor/rules/module-meta-update.mdc
.env
Makefile
```

## 08c — Scriptler (audit)

```
scripts/audit/binance_verify_order.py
scripts/audit/intent_audit.py
scripts/audit/reconcile_now.py
scripts/audit/verify_auth_loop_fix.py
```

## 08b — Scriptler (devops)

```
scripts/devops/annotate_file_headers.py
scripts/devops/setup_env_master_key.py
scripts/devops/sync_ana_basliklar.py
scripts/devops/sync_module_meta.py
```

## 08e — Scriptler (maintenance)

```
scripts/maintenance/fetch_binance_coin_logos.py
scripts/maintenance/fetch_coin_logos.sh
scripts/maintenance/fix_bat_crlf.ps1
scripts/maintenance/fix_cgi_once.py
scripts/maintenance/fix_manager_cgi.py
scripts/maintenance/run_fix_crlf.bat
```

## 08f — Scriptler (migrations)

```
scripts/migrations/README.md
scripts/migrations/create_first_admin.py
scripts/migrations/init_db.py
scripts/migrations/migrate_account_code_backfill.py
scripts/migrations/migrate_admin_fixed.py
scripts/migrations/migrate_spot_favorites.py
scripts/migrations/migrate_user_activity.py
scripts/migrations/set_admin_password_once.py
```

## 08d — Scriptler (perf)

```
scripts/perf/binance_weight_sim.py
scripts/perf/perf_300_bots_sim.py
scripts/perf/perf_snapshot_test.py
scripts/perf/ram_analyze.py
scripts/perf/ram_leak_test.py
scripts/perf/ram_stress_scenarios.py
```

## 08a — Scriptler (runtime)

```
scripts/runtime/local_web_worker_helper.py
scripts/runtime/restart_server.py
scripts/runtime/restart_server_win.py
scripts/runtime/run.sh
scripts/runtime/win_launcher.py
```
