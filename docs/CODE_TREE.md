# Kod ağacı — final1

**Güncelleme:** 2026-05-23  
**Özet rehber:** [STRUCTURE.md](STRUCTURE.md)

---

## Kök (sade)

```
final1/
├── README.md · TRADE_TRAILING_MASTER_SPEC.md · requirements.txt · Makefile
├── start.command · start.bat · run.sh     → ops/ wrapper
│
├── app/              Backend + Bot Engine
├── ui/               Web paneli
├── manager_server/   Ops paneli
├── ops/              Calistirma
├── scripts/          Araclar (alt klasorlu)
├── marketing/        Tanitim (:8080)
├── deploy/ · tests/ · docs/
└── logs/ · .run/     (runtime, gitignore)
```

---

## app/

```
app/
├── main.py
├── api/
│   ├── routes.py           Ana REST (buyuk modul)
│   ├── routes/             home, dashboard_bootstrap
│   ├── bots_engine.py · auth.py · admin.py · ws.py · …
│   └── utils/
├── botengine/              Worker, scheduler, execution, strategies/
├── services/               Binance, PnL, DataHub
├── db/ · core/ · middleware/ · observability/
└── bot/                    Legacy
```

---

## ui/

```
ui/
├── dashboard.html · bot.html · admin.html · login.html · …
├── assets/
│   ├── dashboard.js · api.js · appBoot.js
│   ├── core/ · stores/ · services/ · utils/
│   └── js/                 maintenanceOverlay vb.
└── vendor/                 Chart kutuphanesi
```

---

## scripts/

```
scripts/
├── README.md
├── runtime/        run.sh, restart_server*, local_web_worker_helper
├── devops/         sync_*, annotate, setup_env_master_key
├── audit/          intent_audit, reconcile_now
├── perf/           ram_*, perf_*
├── maintenance/    logo fetch, CRLF fix
├── migrations/     DB
└── *.py / *.sh     Shim (eski yollar)
```

---

## docs/

```
docs/
├── STRUCTURE.md · INDEX.md · ANA_BASLIKLAR.md · CODE_TREE.md
├── runtime.md · security_hardening.md
├── engine/         BOTENGINE runbook + state model
├── api/            Sozlesmeler
└── archive/        Eski raporlar
```

---

## Yeni kod nereye?

| Ne | Klasör |
|----|--------|
| Bot strateji | `app/botengine/strategies/` |
| REST | `app/api/` veya `app/api/routes/` |
| Binance / PnL | `app/services/` |
| Panel JS | `ui/assets/` |
| Baslatma | `ops/` |
| Arac | `scripts/<kategori>/` |

**Paket yollari degismez:** `app.*`, `uvicorn app.main:app`, `python -m app.botengine.worker_main`
