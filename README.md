# TraderTrailing — final1

Binance Spot bot platformu · DCA · Grid · Trailing · Bot Engine v5

> Dışarıdan projeyi inceliyorsanız: önce [docs/STRUCTURE.md](docs/STRUCTURE.md), sonra her klasördeki `README.md` dosyalarına bakın.

---

## Bu proje nedir?

TraderTrailing, Binance Spot hesaplarında otomatik alım-satım botları (DCA, grid, trailing) çalıştıran bir **web uygulaması + arka plan motoru**dur. Kullanıcı panelden bot oluşturur; emirler ayrı bir **worker** sürecinde, güvenli kuyruk ve intent ledger ile borsaya iletilir.

| Bileşen | Klasör | Port |
|---------|--------|------|
| Web API + panel | `app/` + `ui/` | 8000 |
| Bot Engine worker | `app/botengine/` | — |
| Ops paneli | `manager_server/` | 7999 |
| Tanıtım sitesi (opsiyonel) | `marketing/` | 8080 |

**Tek kaynak spec:** [TRADE_TRAILING_MASTER_SPEC.md](TRADE_TRAILING_MASTER_SPEC.md)

---

## Klasör haritası

| Klasör | README |
|--------|--------|
| `app/` | [app/README.md](app/README.md) — backend Python paketi |
| `ui/` | [ui/README.md](ui/README.md) — web arayüzü |
| `manager_server/` | [manager_server/README.md](manager_server/README.md) |
| `ops/` | [ops/README.md](ops/README.md) — başlat/durdur |
| `scripts/` | [scripts/README.md](scripts/README.md) — araçlar |
| `deploy/` | [deploy/README.md](deploy/README.md) |
| `tests/` | [tests/README.md](tests/README.md) |
| `docs/` | [docs/README.md](docs/README.md) |
| `marketing/` | [marketing/README.md](marketing/README.md) |

Tam liste: [docs/ANA_BASLIKLAR.md](docs/ANA_BASLIKLAR.md)

---

## Başlat / durdur

```bash
cp .env.example .env    # DATABASE_URL: ~/.trader/dca.db önerilir
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./start.command         # veya: make start
./stop.command          # veya: make stop
```

| Komut | Açıklama |
|-------|----------|
| `make start` | Manager + Web + Worker + marketing |
| `make stop` | Tüm servisleri durdur |
| `make restart` | Yeniden başlat |
| `make run` | Dev: yalnızca Web + Worker |
| `make meta` | Klasör README + envanter güncelle |

Panel: http://127.0.0.1:8000/ui/dashboard.html  
Manager: http://127.0.0.1:7999/ui

Veritabanı varsayılan: `~/.trader/dca.db` — ayrıntı [docs/runtime.md](docs/runtime.md)

---

## Dokümantasyon güncelleme

```bash
make meta
# veya:
python3 scripts/devops/generate_folder_readmes.py
python3 scripts/devops/sync_module_meta.py
python3 scripts/devops/sync_ana_basliklar.py
```

---

## Test

```bash
make test
```
