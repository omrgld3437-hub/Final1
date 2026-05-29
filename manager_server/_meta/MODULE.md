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
| `app.py` | FastAPI, API, WS · `POST /api/stack/restart` (Manager+Web+Engine+HTML tam yeniden başlatma; rota `{key}` önünde tanımlı) |
| `state.py` | PID, log ring (kilitli), gürültü filtresi (deque race, TradeSync cache); helper spawn; IP engel listesi (`.run/blocked_ips.json`); **sistem çalışması** kronometresi (`.run/session.started_at` — manager açılışı + global start/restart'ta sıfırlanır; metrik `system.uptime_s` / `session_started_at`); manager tam restart → `scripts/runtime/manager_reboot.py` |
| `issue_file_store.py` | Olay Merkezi dosya deposu (`.run/issues/`) |
| `reason_engine.py` | Durum açıklama |
| `ui/` | manager.js, logHumanize.js, index.html — özet kartları (Port/PID/Çalışma/Kaynak/Hata), **Sistem çalışması** canlı kronometre (`H:MM:SS`), servis sekmeleri, dosya tabanlı metrik |

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
