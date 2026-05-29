# Modül: app/api

## Amaç

FastAPI router’ları — web süreci emir göndermez (worker-only).

## Ana router dosyaları

| Dosya | Alan |
|-------|------|
| `routes.py` | Dashboard, wallet, summary, bots/create |
| `bots_engine.py` | `/api/bots-engine` — start/stop/detail, `/grid-points` (canlı tepe/dip) |
| `auth.py` | Login, session, CSRF |
| `admin.py` | Admin panel |
| `finance.py` | Finans API |
| `finance_reports.py` | Raporlar |
| `spot_routes.py` | Manuel spot; `/spot/price` → DataHub only + rate limit |
| `data_hub_routes.py` | Fiyat hub |
| `market_data_routes.py` | Piyasa verisi |
| `pricing_routes.py` | Fiyatlandırma |
| `leaderboard.py` | Sıralama |
| `ws.py` | WebSocket |
| `bots_v2.py` | Legacy bot API |

## Alt klasörler

| Klasör | İçerik |
|--------|--------|
| `routes/` | home vb. |
| `subroutes/` | dashboard_bootstrap |
| `utils/` | fields |

## Bot start akışı

`POST /api/bots-engine/{id}/start` → DB `running` + `bot_engine_commands` → worker

## Dosya envanteri

### `(kök)`

```
__init__.py
admin.py
auth.py
bots_engine.py
bots_v2.py
data_hub_routes.py
finance.py
finance_reports.py
leaderboard.py
market_data_routes.py
pricing_routes.py
routes.py
spot_routes.py
ws.py
```

### `routes/`

```
routes/__init__.py
routes/dashboard_bootstrap.py
routes/home.py
```

### `utils/`

```
utils/__init__.py
utils/fields.py
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
