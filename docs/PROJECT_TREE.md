# Proje ağacı

Bu dosya proje dizin yapısını ve her bölümün ne işe yaradığını özetler.

```
proje/
├── app/                          # Ana uygulama (FastAPI + Bot Engine)
│   ├── api/                      # REST & WebSocket API
│   ├── bot/                      # Eski DCA bot modülleri
│   ├── botengine/                # Bot motoru (worker, stratejiler, ledger)
│   ├── db/                       # Veritabanı modelleri ve oturum
│   ├── middleware/               # İstek metrikleri vb.
│   ├── services/                 # Binance, fiyat, PnL, cache
│   ├── utils/                    # Zaman, account_code vb.
│   ├── main.py                   # FastAPI giriş noktası (port 8000)
│   └── ...
│
├── manager_server/               # Manager panel sunucusu (port 7999)
│   └── ...
│
├── ui/                           # Ana web arayüzü (port 8000'den servis edilir)
│   ├── index.html, login.html, dashboard.html, bot.html, chart.html, ...
│   ├── assets/                   # JS, CSS, chart, coin logoları
│   ├── js/
│   └── vendor/                   # lightweight-charts vb.
│
├── scripts/                      # Yardımcı scriptler
│   ├── local_web_worker_helper.py   # Web/Worker start-stop (Manager ve CLI'dan kullanılır)
│   ├── Kurulum.bat               # Windows kurulum
│   ├── run.sh                    # Mac: tek proses (uvicorn)
│   ├── run_fix_crlf.bat          # .bat CRLF düzeltme
│   ├── migrations/               # Veritabanı: init_db, migrate_*.py
│   ├── restart_server.py, restart_server_win.py, win_launcher.py
│   ├── fetch_binance_coin_logos.py, fetch_coin_logos.sh
│   ├── ram_analyze.py, ram_leak_test.py, ram_stress_scenarios.py
│   └── fix_*.py, fix_*.ps1
│
├── docs/                         # Mimari, runbook, raporlar
│   ├── ARCHITECTURE.md, BOTENGINE_RUNBOOK.md, BOTENGINE_STATE_MODEL.md
│   ├── GÜNCEL_README.md, README_WINDOWS.md
│   ├── CHANGELOG.md, SANITY_CHECK.md, PROJECT_TREE.md
│   └── sanity_check*.md, ram_*.md, ...
│
├── tests/                        # Birim / entegrasyon testleri
│   └── test_cycle_ledger.py
│
├── .env.example                  # Örnek ortam değişkenleri
├── .gitignore, .gitattributes
├── requirements.txt
│
├── start.bat                     # Windows: Manager + Web + Engine
├── start.command                 # Mac: Manager + Web + Engine
├── stop.bat                      # Windows: Tümünü durdur
├── stop.command                  # Mac: Tümünü durdur
├── restart.bat                    # Windows: Yeniden başlat
└── restart.command               # Mac: Yeniden başlat
```

## Hızlı başlatma

| Ortam   | Komut / dosya |
|--------|-----------------|
| **Mac** | `./start.command` (Manager + Web + Engine) |
| **Windows** | `start.bat` (Manager + Web + Engine) |
| **Durdurma** | `stop.bat` / `stop.command` |
| **Yeniden başlatma** | `restart.bat` / `restart.command` |

## Önemli URL'ler

- **Manager panel:** http://127.0.0.1:7999/ui  
- **Web uygulama:** http://127.0.0.1:8000  

## Çalışma dizinleri

- **`.run/`** — PID dosyaları (web.pid, worker.pid, manager.pid), locks, metrik önbelleği
- **`logs/`** — web.log, worker.log, manager.log
