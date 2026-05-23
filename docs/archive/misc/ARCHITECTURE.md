# Architecture

**Tarih:** 2026-01-28

## Modüller

| Modül | Yol | Açıklama |
|-------|-----|----------|
| API | `app/api/` | FastAPI routes: auth, accounts, bots, bots_engine, admin, finance, spot, data_hub |
| Bot Engine | `app/botengine/` | Orchestrator, state_store, execution, strategies (DCA grid trailing), adapters (Binance), virtual_wallet, locks, risk |
| DB | `app/db/` | base (engine, SessionLocal), session (get_db), models, schema_guard |
| Services | `app/services/` | data_hub (fiyat cache), binance_spot, binance_assets, encryption, audit, pnl, pricing |
| Bot (legacy) | `app/bot/` | Ledger, trailing_engine, worker_v2, binance_adapter_v2 |

## Thread / Task Modeli

- **FastAPI:** Tek process, asyncio event loop. Uvicorn ile çalışır.
- **Bot engine:** Her bot için bir `asyncio.Task` (`_bot_loop`). Task’ler `app/botengine/orchestrator.py` içinde `_tasks: Dict[int, asyncio.Task]` ile tutulur.
- **Single worker varsayımı:** Aynı bot_id için tek loop; `start_bot` guard ile çift start engellenir (`BOT_START_SKIPPED_ALREADY_RUNNING`).

## Single Source of Truth

- **Bot state:** `bot_engine_state` tablosu (state_json snapshot). Yükleme: `app/botengine/state_store.py` → `load_state`. Kayıt: `save_state`.
- **Fiyat:** `app/services/data_hub` (tek kaynak). Bot engine adapter: `app/botengine/adapters/binance_adapter.py` → `get_price(symbol)` data_hub’dan okur.
- **Virtual bütçe:** `bot_virtual_wallet` (virtual_base, virtual_quote). Fill sonrası `app/botengine/virtual_wallet.py` → `update_virtual_after_fill`.

## Data Hub

- **Dosya:** `app/services/data_hub.py`
- **Görev:** Fiyat cache (REST + opsiyonel WS). `get_price(symbol)` → `{ price, change24h, volume24h }` veya None (stale/missing).
- **TTL:** Fiyat stale süresi; bot engine fiyat yoksa trade atlamaz, `BOT_PRICE status=STALE` loglar.

## Adapter

- **Binance:** `app/botengine/adapters/binance_adapter.py`. Keys: `app/services/binance_assets.get_account_keys(account_id, db)`. Order: `place_market_buy` / `place_market_sell` → `app/services/binance_spot`.

## DB

- **Varsayılan:** SQLite `sqlite:///./dca.db` (`app/db/base.py`: `DATABASE_URL`).
- **Session:** Her request/tick için yeni session (`SessionLocal()`); kullanım sonrası `db.close()`.
