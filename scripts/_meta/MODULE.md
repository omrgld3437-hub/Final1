# Modül: scripts

## Amaç

Operasyon, migration, audit, meta senkron.

## Ana scriptler

| Dosya | Görev |
|-------|--------|
| `local_web_worker_helper.py` | Web/worker start-stop |
| `sync_module_meta.py` | `_meta/MODULE.md` envanter |
| `setup_env_master_key.py` | `.env` + master key |
| `reconcile_now.py` | Reconcile |
| `intent_audit.py` | Intent audit |
| `run.sh` | Tek proses dev |

## migrations/

DB init ve migrate scriptleri — [migrations/README.md](../migrations/README.md)

## Dosya envanteri

### `(kök)`

```
_shim.py
annotate_file_headers.py
binance_verify_order.py
binance_weight_sim.py
fetch_binance_coin_logos.py
fetch_coin_logos.sh
fix_cgi_once.py
fix_manager_cgi.py
intent_audit.py
local_web_worker_helper.py
perf_300_bots_sim.py
perf_snapshot_test.py
ram_analyze.py
ram_leak_test.py
ram_stress_scenarios.py
reconcile_now.py
restart_server.py
restart_server_win.py
run.sh
run_fix_crlf.bat
setup_env_master_key.py
sync_ana_basliklar.py
sync_module_meta.py
verify_auth_loop_fix.py
win_launcher.py
```

### `audit/`

```
audit/binance_verify_order.py
audit/intent_audit.py
audit/reconcile_now.py
audit/verify_auth_loop_fix.py
```

### `devops/`

```
devops/annotate_file_headers.py
devops/setup_env_master_key.py
devops/sync_ana_basliklar.py
devops/sync_module_meta.py
```

### `maintenance/`

```
maintenance/fetch_binance_coin_logos.py
maintenance/fetch_coin_logos.sh
maintenance/fix_bat_crlf.ps1
maintenance/fix_cgi_once.py
maintenance/fix_manager_cgi.py
maintenance/run_fix_crlf.bat
```

### `migrations/`

```
migrations/README.md
migrations/create_first_admin.py
migrations/init_db.py
migrations/migrate_account_code_backfill.py
migrations/migrate_admin_fixed.py
migrations/migrate_spot_favorites.py
migrations/migrate_user_activity.py
migrations/set_admin_password_once.py
```

### `perf/`

```
perf/binance_weight_sim.py
perf/perf_300_bots_sim.py
perf/perf_snapshot_test.py
perf/ram_analyze.py
perf/ram_leak_test.py
perf/ram_stress_scenarios.py
```

### `runtime/`

```
runtime/local_web_worker_helper.py
runtime/restart_server.py
runtime/restart_server_win.py
runtime/run.sh
runtime/win_launcher.py
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
