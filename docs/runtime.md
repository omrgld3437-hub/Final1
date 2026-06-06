# Runtime — Başlatma ve portlar

Windows deploy scripti (`deploy.ps1`) ve manuel çalıştırma için tek referans.

---

## Web (FastAPI)

```bash
python -m app.main
```

- **Port:** 8000 (uvicorn `host="0.0.0.0"`, `port=8000`)
- **Log:** `logs/app.log` (rotating), konsol

---

## Worker (Engine)

```bash
python -m app.botengine.worker_main
```

- **Port:** yok (süreç; Manager tarafından başlatılır)
- **Log:** Manager `logs/worker.log` tail ile gösterir
- **PID / sayaç:** `.run/worker.pid`, `.run/worker_loop_count`

---

## Manager

```bash
python -m manager_server
```

- **Port:** 7999 (127.0.0.1 only)
- **Log:** `logs/manager.log`
- **PID:** `.run/manager.pid`

---

## Opsiyonel: HTML (omeraltinhtml)

- **Port:** 8080 (env: `OMERALTINHTML_PORT`, default 8080)
- **Path:** `OMERALTINHTML_PATH` ile verilir veya proje içi `omeraltinhtml/` / `Omeraltinhtml/` (Linux’ta klasör adı büyük O ile olabilir; `start.command` ikisini de dener)
- **Linux:** `./start` veya `./start.command` ile tüm servisler (HTML dahil) başlar. Site adresi: **http://127.0.0.1:8080** (yerelde) veya **http://SUNUCU_IP:8080** (uzaktan). Domain (omeraltin.com) için nginx reverse proxy tanımlanmalıdır.
- **Açılmazsa:** `logs/html.log` dosyasına bakın; port 8080 başka süreçte kullanılıyor olabilir.

---

## Port özeti

| Servis  | Port |
|---------|------|
| Web     | 8000 |
| Manager | 7999 |
| HTML    | 8080 |
| Engine  | —    |

---

## .run ve logs

- **.run/**  
  `web.pid`, `worker.pid`, `manager.pid`, `web.metrics.json`, `worker_loop_count`, `audit.json`  
  Manager ve metrikler bu dosyaları kullanır.

- **logs/**  
  `app.log`, `web.log`, `worker.log`, `manager.log`, `ram_snapshots.log` (RAM_PROBE=1)

---

## .env

- Uygulama proje **kökteki** `.env` dosyasını okur (`load_dotenv()`).
- Windows’ta `shared/.env` kullanılacaksa kökteki `.env` junction/symlink ile `shared/.env`’e bağlanabilir.
