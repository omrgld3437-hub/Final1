# Sanity Check: Bot Engine State Persistence

**Tarih:** 2026-01-28  
**Amaç:** Bot engine'in `initial_allocation_done` ve diğer state alanlarının **kalıcı olarak** persist edildiğini ve sonraki tick'lerde doğru yüklendiğini doğrulamak.

---

## Test Senaryosu

1. **Bot oluştur ve başlat**
   - Sembol: BTCUSDT
   - Bütçe: 50 USDT
   - Base %: 50, Quote %: 50
   - Gridler: 1 satış (+1%), 1 alım (-1%)

2. **Logları izle** (3-5 tick)

---

## Beklenen Log Akışı

### Tick 1 (İlk alloc)

```
BOT_LOOP_START bot_id=1 loop=abcd1234 pid=12345
BOT_DB_SESSION session_id=... conn_id=...
BOT_STATE_LOADED bot_id=1 ver=0 ia_done=False base_qty=0 price=0 updated_at=... hash=...
BOT_ACCOUNT_CTX bot_id=1 account_id=1 has_keys=True
BOT_PRICE bot_id=1 loop=abcd1234 tick=0 status=OK price=89240.02 symbol=BTCUSDT
BOT_STRATEGY_TICK bot_id=1 price=89240.02 ref=None ia_done=False mode=IDLE base_bal=0 quote_bal=50
BOT_STRATEGY_INITIAL_ALLOC bot_id=1 price=89240.02 budget=50.00 base_pct=50.0 quote_pct=50.0 base_qty_usdt=25.00
BOT_STRATEGY_INITIAL_ALLOC_ACTION bot_id=1 action_key=initial_allocation_0 quote_qty=25.00
BOT_ACTION bot_id=1 loop=abcd1234 tick=1 action_key=initial_allocation_0 type=BUY reason=initial_allocation symbol=BTCUSDT quote_qty=25.00
BOT_TRADE_RECORDED bot_id=1 side=BUY qty=0.00028 price=89240.01 fee=0 order_id=55978185337
BOT_STATE_SAVING bot_id=1 ver=0->1 ia_done=True base_qty=0.00028 price=89240.01 hash=abc123
BOT_STATE_SAVED bot_id=1 ver=1 ia_done=True hash=abc123 verify_ia_done=True verify_hash=abc123
BOT_TICK bot_id=1 loop=abcd1234 tick=1 mode=IDLE price=89240.02 ref=89240.01 ia_done=True actions=1
```

### Tick 2 (Grid'e geçmeli)

```
BOT_DB_SESSION session_id=... conn_id=...  # YENİ session
BOT_STATE_LOADED bot_id=1 ver=1 ia_done=True base_qty=0.00028 price=89240.01 updated_at=... hash=abc123  # ÖNCEKİ TICK'İN SAVE'İNİ GÖRMELİ
BOT_PRICE bot_id=1 loop=abcd1234 tick=1 status=OK price=89240.02 symbol=BTCUSDT
BOT_STRATEGY_TICK bot_id=1 price=89240.02 ref=89240.01 ia_done=True mode=IDLE base_bal=0.00028 quote_bal=25
BOT_STRATEGY_INITIAL_DONE bot_id=1 ia_done=True skipping initial alloc
BOT_TICK bot_id=1 loop=abcd1234 tick=2 mode=IDLE price=89240.02 ref=89240.01 ia_done=True actions=0  # initial_allocation YOK, grid tetik bekliyor
```

### Tick 3+

```
BOT_STATE_LOADED bot_id=1 ver=1 ia_done=True ...  # HER TICK'TE TRUE KALMALI, ver artabilir
BOT_STRATEGY_INITIAL_DONE bot_id=1 ia_done=True skipping initial alloc
BOT_TICK ... actions=0  # veya grid action (fiyat tetiklediyse)
```

---

## Kritik Kontrol Noktaları

### ✅ 1. State Load/Save Hash Eşleşmesi

- **Tick N:** `BOT_STATE_SAVED ... hash=abc123 verify_hash=abc123` → commit sonrası re-read aynı hash
- **Tick N+1:** `BOT_STATE_LOADED ... hash=abc123` → sonraki tick aynı hash'i görmeli

**Eğer hash farklı:** State başka biri tarafından ezilmiş veya commit görünmüyor.

### ✅ 2. initial_allocation_done Kalıcılığı

- **Tick 1:** `ia_done=True` save edildi
- **Tick 2+:** `ia_done=True` load edilmeli

**Eğer Tick 2'de `ia_done=False`:** State persist edilmemiş veya ezilmiş.

### ✅ 3. Çift Loop Tespiti

- **Tüm tick loglarında `loop=` değeri aynı olmalı** (örn. `abcd1234`)
- **Eğer farklı loop ID'leri görürsen:** Çift loop var, state eziliyor olabilir

**Log:** `BOT_START_SKIPPED_ALREADY_RUNNING` → çift start engellendi

### ✅ 4. Transaction Rollback

- **`BOT_DB_TX_ROLLBACK` log'u OLMAMALI** (veya çok nadir, açıklanabilir durumlarda)
- **Eğer rollback görürsen:** Stack trace'den hangi kod yolundan geldiğini bul

### ✅ 5. Session/Connection Tracking

- **Her tick:** `BOT_DB_SESSION` yeni session_id gösterir (normal)
- **Connection ID:** Aynı connection pool kullanılıyor olabilir (normal), ama commit görünür olmalı

---

## Hata Senaryoları ve Kök Nedenler

### Case A: Hash Tick N+1'de farklı

**Kök neden:** State başka bir writer tarafından eziliyor veya commit görünmüyor.

**Fix:** 
- Çift loop kontrolü (`BOT_START_SKIPPED_ALREADY_RUNNING`)
- Process ID kontrolü (multi-worker)
- State version/optimistic locking

### Case B: initial_allocation_done Tick 2'de False

**Kök neden:** Save commit olmuyor veya sonraki tick eski state'i okuyor.

**Fix:**
- Transaction isolation kontrolü
- `db.close()` garanti
- `expire_on_commit` ayarları

### Case C: Rollback görülüyor

**Kök neden:** `append_event`, `Ledger.record_trade`, `update_virtual_after_fill` veya başka bir DB işlemi rollback yapıyor.

**Fix:**
- Rollback stack trace'den kaynak bul
- State save'i rollback'ten izole et (ayrı transaction veya save önce, event sonra)

### Case D: Çift loop (farklı loop ID'leri)

**Kök neden:** Multi-worker, reload, veya çift start.

**Fix:**
- `start_bot` guard (`BOT_START_SKIPPED_ALREADY_RUNNING`)
- Process-level lock (DB lease)
- Tek worker garantisi (`run.sh`)

---

## Idempotency anahtarı

Initial allocation için **sabit key** kullanılmalı; aksi halde her tick farklı key üretir, idempotency çalışmaz.  
**Key:** `initial_allocation_0` (tüm log ve execution'da aynı olmalı).

---

## DB Manuel Kontrol (Opsiyonel)

Uygulama varsayılanı **SQLite** (`app/db/base.py`: `DATABASE_URL` → `sqlite:///./dca.db`). Postgres kullanıyorsanız ikinci SQL'i kullanın.

**SQLite / MySQL:**

```sql
SELECT bot_id, cycle_id, mode, updated_at, 
       json_extract(state_json, '$.initial_allocation_done') AS ia_done,
       json_extract(state_json, '$.initial_alloc_base_qty') AS base_qty,
       json_extract(state_json, '$.initial_alloc_price') AS price
FROM bot_engine_state 
WHERE bot_id = 1;
```

**Postgres:**

```sql
SELECT bot_id, cycle_id, mode, updated_at, 
       state_json->>'initial_allocation_done' AS ia_done,
       state_json->>'initial_alloc_base_qty' AS base_qty,
       state_json->>'initial_alloc_price' AS price
FROM bot_engine_state 
WHERE bot_id = 1;
```

**Yorum:** `updated_at` her tick'te artmalı; `ia_done` TRUE (ilk alloc sonrası); `base_qty` ve `price` > 0 (fill sonrası).

---

## Başarı Kriterleri

- ✅ Tick 1'de `initial_allocation_done=True` save edildi (`BOT_STATE_SAVED verify_ia_done=True`)
- ✅ Tick 2'de `initial_allocation_done=True` load edildi (`BOT_STATE_LOADED ia_done=True`)
- ✅ Tick 2'de `actions=0` (initial_allocation action yok, grid'e geçti)
- ✅ Tick 3+ `ia_done=True` kalıyor
- ✅ Hash'ler eşleşiyor (save → verify → next load)
- ✅ Rollback yok (veya açıklanabilir)
- ✅ Tek loop ID (çift loop yok)

---

## Sonuç

Bu sanity check **state persist sorununu kesinleştirir**. Log'larda hangi case'in gerçekleştiğini görürsün ve ona göre minimal fix uygularsın.

**Eğer tüm kriterler geçerse:** Bot artık initial allocation'ı 1 kere yapıp grid/trailing moduna geçecek.
