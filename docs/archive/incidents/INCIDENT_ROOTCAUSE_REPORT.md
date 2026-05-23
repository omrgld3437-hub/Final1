# Incident Root Cause Report: Bot Engine State Persist / Initial Allocation

**Tarih:** 2026-01-28  
**Kapsam:** Bot engine "çalışıyor görünüp initial alloc yapmaması", referans/tetik fiyatların boş kalması, state persist, çift loop, rollback, stale price.  
**Referans:** `docs/SANITY_CHECK_BOTENGINE_STATE_PERSIST.md` (log akışı ve Case A/B/C/D ayrımı).

---

## 1) Problem Tanımı ve Gözlenen Semptomlar

- **UI:** Bot "Çalışıyor" gösteriyor; referans fiyat yok; grid tetik fiyatları `—`; base/quote 0.
- **Tek anlamı:** Initial allocation ya hiç yapılmadı ya da yapıldı ama **persist edilmedi**; sonraki tick’te state’te `initial_allocation_done=True` ve `reference_price` / `initial_alloc_*` görünmüyor.

---

## 2) Sistemin Çalışma Modeli (Gerçek Call Graph)

Her adım **dosya + fonksiyon** ile kanıtlanmıştır.

| Adım | Dosya | Fonksiyon / Yol | Açıklama |
|------|--------|------------------|----------|
| UI | (frontend) | — | Bot list/detail; "Çalışıyor" status; referans/tetik fiyatlar API’den gelir |
| API start | `app/api/bots_engine.py` | `bots_start` (POST `/{bot_id}/start`) | `start_bot(bot.id, db)` çağrılır (satır ~202) |
| API alt. | `app/api/routes.py` | `start_bot` (POST `/bots/{bot_id}/start`) | `engine_start_bot(bot.id, db)` (satır ~757) |
| Orchestrator | `app/botengine/orchestrator.py` | `start_bot` (satır 201–218) | `Bot.status = "running"`, commit; `_bot_loop(bot_id)` asyncio task |
| Loop | `app/botengine/orchestrator.py` | `_bot_loop` (satır 49–199) | Her tick: `_get_db()` → `load_state` → price → strategy → execution → `save_state` → sleep |
| DB session | `app/botengine/orchestrator.py` | `_get_db` (satır 34–46) | `SessionLocal()`; log: `BOT_DB_SESSION session_id= conn_id= bind=` |
| State load | `app/botengine/state_store.py` | `load_state` (satır 17–48) | `SELECT state_json, cycle_id, mode, ... FROM bot_engine_state`; log: `BOT_STATE_LOADED ver= ia_done= base_qty= price= hash=` |
| State save | `app/botengine/state_store.py` | `save_state` (satır 51–118) | Upsert `bot_engine_state`; `db.commit()`; post-commit re-read; log: `BOT_STATE_SAVING` / `BOT_STATE_SAVED verify_ia_done= verify_hash=` |
| Strategy | `app/botengine/strategies/dca_grid_trailing.py` | `tick_dca_grid_trailing` | State + price → actions (initial_allocation veya grid). Ref: `state.get("reference_price")`, `state.get("initial_allocation_done")` |
| Execution | `app/botengine/execution.py` | `run_actions` (satır 82–259) | Idempotency (`initial_allocation_0`), min notional, virtual budget, adapter order, `apply_fill_to_state`, `save_state`, `Ledger.record_trade`, `update_virtual_after_fill` |
| Adapter | `app/botengine/adapters/binance_adapter.py` | `get_price`, `place_market_buy` | Fiyat: `data_hub.get_price(symbol)`; order: binance_spot |
| DB layer | `app/db/base.py` | `SessionLocal` (satır 31) | `sessionmaker(autocommit=False, autoflush=False, bind=engine)`; `DATABASE_URL` default: `sqlite:///./dca.db` |

---

## 3) State Lifecycle (Yükleme → Karar → Aksiyon → Fill → Persist)

- **Yükleme:** `app/botengine/state_store.py` → `load_state(db, bot_id)` (satır 17). SELECT `state_json, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at`. JSON parse; `state_version` yoksa 0.
- **Commit noktası:** `save_state` içinde (satır 95, 100) iki kez `db.commit()`: biri upsert, biri `updated_at` güncellemesi. Post-commit re-read (satır 104–116) ile verify log.
- **State blob kritik alanlar:**
  - `initial_allocation_done` (bool): İlk alım yapıldı mı
  - `initial_alloc_base_qty`, `initial_alloc_price`: İlk alım miktar/fiyat
  - `reference_price`: Grid/trailing referansı
  - `cycle_id`: Cycle sayacı
  - `state_version`: Optimistic locking için (artırılır her save’te)

State iskeleti: `app/botengine/models.py` → `build_state_skeleton` (satır 158–191): `state_version: 0`, `initial_allocation_done: False`, `reference_price: None`.

---

## 4) DB Session/Transaction Forensics

- **SessionLocal:** `app/db/base.py` satır 31: `sessionmaker(autocommit=False, autoflush=False, bind=engine)`. Engine: `create_engine(DATABASE_URL)` (satır 13–29); SQLite için `check_same_thread=False`, pool 10/20.
- **Her tick yeni session:** `_bot_loop` her iterasyonda `db = _get_db()` (orchestrator satır 74) → yeni `SessionLocal()`. Tick sonunda `db.close()` (satır 180).
- **Isolation / pool:** SQLite default isolation; connection pool recycle 3600s. Commit sonrası aynı process içinde sonraki `SessionLocal()` aynı DB’yi okur; commit görünür olmalı.
- **Commit görünürlük kanıtı:** `save_state` içinde commit sonrası aynı session ile re-read (state_store satır 104–116); log `BOT_STATE_SAVED verify_ia_done= verify_hash=`. Sonraki tick’te farklı session ile `load_state` → `BOT_STATE_LOADED hash=`. Hash eşleşmeli (Case A’da eşleşmezse overwrite/visibility sorunu).

---

## 5) Double Loop / Multi-worker Forensics

- **Aynı bot_id için kaç task:** `_tasks: Dict[int, asyncio.Task]` (orchestrator satır 27); `start_bot` içinde `if bot_id in _tasks` (satır 211) → zaten varsa `BOT_START_SKIPPED_ALREADY_RUNNING` log, yeni task oluşturulmaz.
- **loop_instance_id:** Her `_bot_loop` girişinde `uuid.uuid4()[:8]` (satır 50); `_loop_instances[bot_id] = loop_instance_id`. Tüm tick loglarında `loop=` aynı olmalı; farklıysa Case D (çift loop).
- **Guard:** `async with _task_create_lock` (satır 210) ile tek thread’de kontrol; çift start engellenir.

---

## 6) Execution Path Forensics

- **Initial alloc action üretimi:** `app/botengine/strategies/dca_grid_trailing.py`: `initial_done` False ve bütçe varsa tek BUY action, `reason="initial_allocation"`; log `BOT_STRATEGY_INITIAL_ALLOC_ACTION action_key=initial_allocation_0`.
- **Orchestrator action_key:** `reason == "initial_allocation"` → `ak = "initial_allocation_0"` (orchestrator satır 151–152); log `BOT_ACTION action_key=initial_allocation_0`.
- **Execution skip nedenleri (kanıt satırları):**
  - Idempotency: `app/botengine/execution.py` satır 105–114: `check_idempotency(bot_id, key)` → skip, `BOT_EXECUTION_SKIP skip_reason=IDEMPOTENT_LOCK`.
  - already_done: satır 114–122: `load_state` ile `initial_allocation_done` True ise state sync, skip.
  - Min notional: satır 129–132: `guard_min_notional` → `BOT_EXECUTION_SKIP skip_reason=MIN_NOTIONAL`.
  - Virtual budget: satır 134–148: `check_virtual_budget` → skip, event yazılır.
  - Order fail: satır 154–159: adapter exception → `BOT_EXECUTION_SKIP skip_reason=ORDER_FAILED`.
- **Fiyat stale/missing:** Orchestrator satır 116–127: `price` yok veya ≤0 → `BOT_PRICE status=STALE`, `BOT_TICK_PRICE_MISSING`, sleep, trade yok.

---

## 7) Transaction Rollback Avı

- **SQLAlchemy hooks:** `app/botengine/execution.py` satır 30–45: `after_begin`, `after_commit`, `after_rollback`. Rollback’te kısa stack log: `BOT_DB_TX_ROLLBACK session_id= stack=`.
- **Olası rollback kaynakları:** `append_event` (state_store satır 124–150): her event’te `db.commit()`. `Ledger.record_trade` (app/bot/ledger.py satır 54): `db.commit()`. `update_virtual_after_fill` (app/botengine/virtual_wallet.py satır 70+): execute + commit. `save_state`: iki commit. Bu fonksiyonlar ayrı commit kullandığı için birinde exception rollback yaparsa o session’daki önceki commit’ler zaten kalıcı; ancak aynı session içinde save_state’ten önce rollback olursa save kaybolmaz (save_state kendi session’ında commit ediyor). Kritik nokta: orchestrator tek session ile tüm tick’i yapıyor; `run_actions` aynı `db`’yi kullanıyor; `Ledger.record_trade` veya `update_virtual_after_fill` exception verirse rollback o session’ı geri alır — o anda henüz `save_state` çağrılmamış olabilir (orchestrator satır 169: save_state, run_actions’tan sonra). Yani execution içinde record_trade veya update_virtual exception → rollback → aynı session’da sonra gelen save_state yine de commit eder (save_state kendi commit’lerini yapıyor). Asıl risk: execution içinde bir yerde rollback ve exception propagate ederse orchestrator’a, o tick’te save_state atlanabilir veya state yarı güncel kalabilir. Rollback stack’i log’da görülürse Case C.

---

## 8) Root Cause Sonucu (Case A/B/C/D)

Sanity dokümanındaki case’lerle birebir:

| Case | Göstergesi | Kök neden | Dosya/yer |
|------|------------|-----------|------------|
| **A** | Tick N+1’de load hash ≠ Tick N save hash | State overwrite veya commit görünmüyor | state_store load/save; başka writer (BOTENGINE_STATE_WRITERS) |
| **B** | Tick 2’de `ia_done=False` | Save commit olmuyor veya sonraki tick eski state okuyor | state_store save commit; session/isolation |
| **C** | Log’da `BOT_DB_TX_ROLLBACK` | Bir DB işlemi rollback yapıyor | execution/ledger/virtual_wallet/append_event; stack trace |
| **D** | Farklı `loop=` değerleri | Çift loop / multi-worker | orchestrator _tasks, start_bot guard |

Teşhis: Logları topla; hangi case gerçekleşiyorsa o satıra göre minimal fix (SANITY_CHECK_BOTENGINE_STATE_PERSIST.md Case fix’leri).

---

## 9) Minimal Fix Planı (Kanıta Göre)

- **Case A:** Çift loop kontrolü (zaten var); state writer’ları tekilleştir; gerekirse state_version/optimistic lock.
- **Case B:** Save’in commit’ini garanti et; session close öncesi flush/commit; gerekirse save_state’i rollback’ten izole et (ayrı session).
- **Case C:** Rollback stack’ten hangi fonksiyon; o fonksiyonda exception handling veya save_state’i önce çağır, event/ledger/virtual sonra.
- **Case D:** start_bot guard (zaten var); process-level lock veya tek worker garantisi.

---

## 10) “Bot Başladı” Kanıtları (Beklenen Log Snippet’leri)

Aşağıdaki gibi 20–40 satır log görülmeli:

**Tick 1 (initial alloc):**
```
BOT_LOOP_START bot_id=1 loop=abcd1234 pid=12345
BOT_DB_SESSION session_id=... conn_id=...
BOT_STATE_LOADED bot_id=1 ver=0 ia_done=False base_qty=0 price=0 updated_at=... hash=...
BOT_ACCOUNT_CTX bot_id=1 account_id=1 has_keys=True
BOT_PRICE bot_id=1 loop=abcd1234 tick=0 status=OK price=89240.02 symbol=BTCUSDT
BOT_STRATEGY_TICK bot_id=1 price=89240.02 ref=None ia_done=False ...
BOT_STRATEGY_INITIAL_ALLOC_ACTION bot_id=1 action_key=initial_allocation_0 quote_qty=25.00
BOT_ACTION bot_id=1 loop=abcd1234 tick=1 action_key=initial_allocation_0 type=BUY reason=initial_allocation ...
BOT_TRADE_RECORDED bot_id=1 side=BUY qty=0.00028 price=89240.01 ...
BOT_STATE_SAVING bot_id=1 ver=0->1 ia_done=True base_qty=0.00028 price=89240.01 hash=abc123
BOT_STATE_SAVED bot_id=1 ver=1 ia_done=True hash=abc123 verify_ia_done=True verify_hash=abc123
BOT_TICK bot_id=1 loop=abcd1234 tick=1 mode=IDLE price=89240.02 ref=89240.01 ia_done=True actions=1
```

**Tick 2 (grid’e geçiş):**
```
BOT_DB_SESSION session_id=... conn_id=...
BOT_STATE_LOADED bot_id=1 ver=1 ia_done=True base_qty=0.00028 price=89240.01 updated_at=... hash=abc123
BOT_PRICE bot_id=1 loop=abcd1234 tick=1 status=OK price=89240.02 symbol=BTCUSDT
BOT_STRATEGY_INITIAL_DONE bot_id=1 ia_done=True skipping initial alloc
BOT_TICK bot_id=1 loop=abcd1234 tick=2 mode=IDLE price=89240.02 ref=89240.01 ia_done=True actions=0
```

Başarı: Tick 1’de `BOT_STATE_SAVED verify_ia_done=True verify_hash=...`; Tick 2’de `BOT_STATE_LOADED ia_done=True hash=` aynı; initial alloc tek; grid tetik fiyatları referansla dolar.

---

## Instrumentation Zorunluluğu (Kodda Mevcut)

Aşağıdaki loglar rapor öncesi kodda olmalı (şu an ekli):

| Log | Dosya | Durum |
|-----|--------|--------|
| BOT_LOOP_START bot_id loop pid | orchestrator.py | Var (satır 54) |
| BOT_DB_SESSION session_id conn_id bind | orchestrator.py _get_db | Var (satır 45) |
| BOT_STATE_LOADED ver ia_done base_qty price updated_at hash | state_store.py load_state | Var (satır 44–46) |
| BOT_ACTION action_key=initial_allocation_0 | orchestrator.py | Var (satır 151–155) |
| BOT_DB_TX_BEGIN/COMMIT/ROLLBACK | execution.py SQLAlchemy events | Var (satır 31–44) |
| BOT_STATE_SAVING / BOT_STATE_SAVED verify_ia_done verify_hash | state_store.py save_state | Var (satır 70–72, 114–116) |
| BOT_PRICE status=OK\|STALE | orchestrator.py | Var (eklendi) |
| BOT_ACCOUNT_CTX has_keys | orchestrator.py | Var (eklendi) |

---

**Sonuç:** Kök neden log’larla Case A/B/C/D’den biri olarak tespit edilir; bu rapor + SANITY_CHECK_BOTENGINE_STATE_PERSIST.md ile tek cümlede “tam olarak nerede kırılıyor” netleştirilip final fix uygulanabilir.
