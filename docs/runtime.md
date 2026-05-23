# Runtime — Başlatma ve portlar

Tek operasyon referansı. Scriptler: `ops/` (kökteki `start.command` vb. wrapper).

---

## Hızlı başlat

```bash
./start.command          # veya ops/start.command
./stop.command
./restart.command
./deploy.sh              # sunucu: pull + restart
./run.sh                 # dev: yalnizca Web + Worker
```

Windows: `start.bat` → `ops/start.bat` (Manager + Web + Worker + marketing)

---

## Web (FastAPI)

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- **Port:** 8000 (`WEB_HOST=0.0.0.0` ile dis erisim)
- **Log:** `logs/web.log`, `logs/app.log`
- **PID:** `.run/web.pid`

---

## Worker (Bot Engine)

```bash
python -m app.botengine.worker_main
```

- **Port:** yok
- **Log:** `logs/worker.log`
- **PID:** `.run/worker.pid`

Bot tick icin worker **zorunlu**. Calismiyorsa `./start.command` veya Manager uzerinden baslatin.

---

## Manager

```bash
python -m manager_server
```

- **Port:** 7999 (127.0.0.1)
- **Log:** `logs/manager.log`
- **PID:** `.run/manager.pid`
- **SSH tuneli:** `ssh -L 7999:127.0.0.1:7999 user@host` → http://127.0.0.1:7999/ui/

---

## Opsiyonel: marketing sitesi (:8080)

- **Klasor:** `marketing/` (birincil); eski adlar `omeraltinhtml/`, `Omeraltinhtml/` desteklenir
- **Env:** `OMERALTINHTML_PATH`, `OMERALTINHTML_PORT` (default 8080)
- **Log:** `logs/html.log`
- **Dis erisim:** nginx reverse proxy veya `WEB_HOST=0.0.0.0` (Web icin)

---

## Port ozeti

| Servis | Port |
|--------|------|
| Web | 8000 |
| Manager | 7999 |
| Marketing | 8080 |
| Worker | — |

---

## Veritabani

Varsayilan: `~/.trader/dca.db` (`.env` → `DATABASE_URL`)

---

## .run ve logs

| Dizin | Icerik |
|-------|--------|
| `.run/` | `web.pid`, `worker.pid`, `manager.pid`, `html.pid`, metrik JSON |
| `logs/` | `web.log`, `worker.log`, `manager.log`, `html.log` |

---

## .env

Proje kokundeki `.env` okunur (`load_dotenv()`).
