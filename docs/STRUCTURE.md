# Proje yapısı — final1

Tek sayfa referans. Detaylı dosya listesi: [ANA_BASLIKLAR.md](ANA_BASLIKLAR.md)

---

## 1. Ürün kodu (3 modül)

| Klasör | Rol | Giriş |
|--------|-----|-------|
| `app/` | Backend API + Bot Engine | `uvicorn app.main:app` |
| `ui/` | Web paneli (static) | `/ui/dashboard.html` |
| `manager_server/` | Ops paneli | `python -m manager_server` (:7999) |

### app/ iç yapı

```
app/
├── main.py              FastAPI giriş
├── api/                 REST + WS
│   ├── routes.py        Ana dashboard API (modül)
│   └── routes/          Alt router'lar (home, bootstrap)
├── botengine/           Canlı bot motoru (worker)
├── services/            Binance, PnL, DataHub
├── db/ · core/          Veritabanı, config, auth
├── middleware/          CSRF, güvenlik
└── bot/                 Legacy (yeni kod yok)
```

---

## 2. Operasyon

| Klasör | Rol |
|--------|-----|
| `ops/` | Başlat/durdur/deploy scriptleri (asıl mantık) |
| `deploy/` | Sunucu rsync + nginx |
| `scripts/` | Araçlar (runtime, audit, perf, …) |

Kökte yalnızca **wrapper**: `start.command`, `start.bat`, `run.sh`  
Diğer komutlar: `make start|stop|restart|deploy` veya `./ops/...`

---

## 3. Destek

| Klasör | Rol |
|--------|-----|
| `tests/` | pytest |
| `docs/` | Runbook, spec dışı dokümanlar |
| `marketing/` | Opsiyonel tanıtım sitesi (:8080) |

---

## 4. Çalışma zamanı (gitignore)

| Dizin | İçerik |
|-------|--------|
| `.run/` | PID, metrik JSON |
| `logs/` | web.log, worker.log, manager.log |
| `.venv/` | Python sanal ortam |
| `~/.trader/dca.db` | Varsayılan SQLite DB |

`shared/` — eski opsiyonel `.env` / log dizini; yeni kurulumda kullanılmaz.

---

## Yeni kod nereye?

| Ne | Nereye |
|----|--------|
| Bot strateji | `app/botengine/strategies/` |
| REST endpoint | `app/api/` veya `app/api/routes/` |
| Binance / PnL | `app/services/` |
| Panel JS | `ui/assets/` |
| Başlatma | `ops/` |
| Tek seferlik araç | `scripts/audit/` veya `scripts/maintenance/` |

**Değiştirilmez:** Python paket adı `app.*`, worker `app.botengine.worker_main`.
