# Modül: manager_server

## Amaç

Yerel ops paneli — süreç başlat/durdur, log, metrik (emir göndermez).

## Giriş

```
python -m manager_server
```

**Port:** 7999 · **UI:** `/ui`

## Dosyalar

| Dosya | Görev |
|-------|--------|
| `app.py` | FastAPI, API, WS · `POST /api/global/{start,stop,restart}` (anında yanıt `pending`; iş `state.schedule_global_action` arka plan thread; çakışmada HTTP 200 + `{ busy: true }`, WARN log yok) · `POST /api/stack/restart` (Manager+Web+Engine+HTML tam yeniden başlatma; rota `{key}` önünde tanımlı) |
| `state.py` | PID, log ring (kilitli), gürültü filtresi (deque race, TradeSync cache, emilen `BOT_*_EXCEPTION` / lease skip / fiyat yok); helper spawn; IP engel listesi (`.run/blocked_ips.json`); **sistem çalışması** kronometresi (`.run/session.started_at` — yalnızca manager süreci yeniden başlayınca sıfırlanır; global start/stop/restart etkilemez); `schedule_global_action` → `global _global_action_running` (UnboundLocalError önlemi); manager tam restart → `scripts/runtime/manager_reboot.py`; özet kart **Saatlik tick / istek** (`ticks_last_60m`, son 60 dk): manager/html = metrics poll; **web** = `request_total` artışı (HTTP, UI etiketi **Saatlik istek**; web PID değişince sayaç sıfırlanır + `web.started_at` alt sınır); engine = `engine.metrics.json`; web proc’da `requests_per_min` tooltip |
| `issue_file_store.py` | Olay Merkezi dosya deposu (`.run/issues/`) |
| `reason_engine.py` | Durum açıklama |
| `ui/` | manager.js, logHumanize.js, index.html — özet kartları (Saatlik tick satırı); header toplu start/stop/restart (`is-busy` yalnız global düğmeler; stuck heal + 90s watchdog) |

## Güvenlik

`MANAGER_ALLOW_REMOTE=1` olmadan yalnızca localhost.

**IP engelleme (Manager → Web):** Güvenlik sekmesinden IP engellenir; liste `.run/blocked_ips.json` dosyasına yazılır. Web (`8000`) `request_metrics_middleware` başında listeyi okur (2s cache) ve engelli IP'ye **403** döner.

| Endpoint | Açıklama |
|----------|----------|
| `GET /api/security/blocked-ips` | Aktif engelli IP listesi |
| `POST /api/security/ban-ip` | `{ "ip", "reason?" }` — web'den engelle |
| `POST /api/security/unban-ip` | `{ "ip" }` — engeli kaldır |

`top_ips` sayaçları web süreci başlangıcından beri **kümülatif**tir; yerel `127.0.0.1` dashboard/API polling ile yüksek görünmesi normaldir.

## Dosya envanteri

### `(kök)`

```
__init__.py
__main__.py
app.py
issue_file_store.py
reason_engine.py
state.py
```

### `ui/`

```
ui/assets/manager.css
ui/assets/manager.js
ui/index.html
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
