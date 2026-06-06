# LIVE TRADING EXECUTION FORENSIC ANALYSIS v1

**Project:** TraderTrailing  
**Purpose:** System debugging and engine reconstruction. NOT for human narrative.  
**Critical bug:** Bot RUNNING, grid/balances visible, no real orders/fills on Binance.

---

## PRIMARY ROOT CAUSE – "HEPSİ HAYALİ, BİNANCE'TE HİÇBİR ŞEY YOK"

### En olası tek kırılma noktası

**Kök neden (en olası):** `paper_mode=True` yüzünden adapter HTTP'ye hiç çıkmıyor; `_simulate_fill()` çalışıyor.

Execution flow:

- Worker tick'te **keys** çekiliyor, sonra **paper_mode** hesaplanıp adapter buna göre kuruluyor.
- `BinanceAdapter.place_market_buy()` içinde **paper_mode True ise `_simulate_fill(...)`** çağrılıyor ve **REST çağrısı yapılmıyor**.
- UI'da "çalışıyor / bölüştürdü / grid kurdu" görünüp Binance'te **hiç order olmamasının** en birebir açıklaması budur: sistem **paper/simülasyon** yoluna düşmüştür.

Bu, "hayali alım satım" hissinin teknik karşılığıdır.

### Neden "real hesap" seçmene rağmen paper'a düşer?

İki kritik risk penceresi:

1. **Worker ortamında keys aslında alınamıyor** (`get_account_keys` None dönüyor) → eski heuristic ile `paper_mode=True` olabiliyordu.
2. **Bot DB'de "live" görünse bile** runtime'da **bot.mode vs adapter.paper_mode mismatch** olabiliyordu (heuristik test_user && !keys).

Bu durumda bot live gibi başlıyor ama execution katmanı simüle ediyor.

### 2. olası kök neden: Worker role guard (403)

Order atma sadece worker'da serbest; çağrı web process'te kalırsa 403 ve akış "sessiz" devam eder:

- `place_order()` içinde `is_worker_role()` False ise **AppError 403 WORKER_ONLY_OPERATION** fırlatılır.
- Worker gerçekten order path'ine girmiyorsa veya **DATABASE_ROLE** yanlışsa Binance'e hiç gidilmez. Bu da "bot running ama order yok" üretir (simülasyon olmasa bile).

### Bu dosyaya göre HATA nerede?

Dokümanın mapping'ine göre hata noktası şu iki düğümden biri:

| Düğüm | Açıklama |
|-------|----------|
| **1.6 Adapter katmanı** | `paper_mode=True` → `_simulate_fill` only; **no REST**. |
| **1.7 REST client guard** | `is_worker_role()` yanlışsa `place_order` **403**. |

"Hayali alım satım" tanımı **1.6 (paper_mode)** ile birebir örtüşür.

---

## KALICI DÜZELTME (PRODUCTION-GRADE) – UYGULANMIŞ

Aşağıdaki 3 değişiklik bu sınıf problemini kökten bitirir; **kodda uygulanmıştır**.

### (A) Live botta "keys yoksa" simüle etme → FAIL FAST

- **Eski risk:** Keys yoksa heuristik ile paper_mode'a düşülebiliyordu; live bot simüle ediliyordu.
- **Kural:** `bot.mode == "live"` ve `keys is None` ⇒ **CRITICAL + bot.status = paused_error + event = ACCOUNT_KEYS_MISSING**. Bot RUNNING kalamaz.
- **Uygulama:** `app/botengine/orchestrator.py` ve `app/botengine/bot_run.py`: live bot + no keys → `bot.status = "paused_error"`, `db.commit()`, `append_event` ACCOUNT_KEYS_MISSING, log `BOT_LIVE_NO_KEYS`, continue/return (tick etmez).

### (B) paper_mode runtime hesabı bot.mode'dan türetilmeli

- **Eski risk:** `paper_mode = test_user && !keys` gibi heuristik prod'da "yanlışlıkla paper" yaratıyordu.
- **Kural:** `paper_mode = (bot.mode == "paper")`. Test kullanıcı/keys heuristic sadece dev/test ortamında bile isteye kullanılabilir; prod'da sadece DB'deki mode geçerli.
- **Uygulama:** `orchestrator.py` ve `bot_run.py`: `bot_mode = (str(getattr(row|bot, "mode", None) or "").strip().lower()`, **paper_mode = (bot_mode == "paper")**.

### (C) Worker role garanti + gözle görünür audit

- **Kural:** Worker process env: `DATABASE_ROLE=worker` kesin olmalı. Her order denemesinde **INFO** log: bot_id, account_id, paper_mode, has_keys, is_worker_role.
- **Uygulama:**
  - Worker: `worker_main.py` içinde `os.environ.setdefault("DATABASE_ROLE", "worker")` (zaten vardı).
  - Adapter kurulunca: **BOT_MODE_CHECK** (INFO): `bot_id`, `account_id`, `bot.mode`, `paper_mode`, `has_keys`, `is_worker_role` — `orchestrator.py` ve `bot_run.py`.
  - Order denemesi hemen öncesi: **EXEC_ORDER_ATTEMPT** (INFO): `bot_id`, `account_id`, `symbol`, `side`, `paper_mode`, `is_worker_role`, `client_order_id` — `execution.py`.
  - REST çağrısı: **BINANCE_PLACE_ORDER** (INFO): `symbol`, `side`, `type`, `worker_role=True` — `binance_spot.py` `place_order()`.

---

## TEK KANITLAYAN KONTROL

Adapter kurulduğu anda şunu logla: **bot.mode / paper_mode / has_keys** (artık **BOT_MODE_CHECK** ile yapılıyor).

- Eğer logda **paper_mode=True** görürsen, problem büyük olasılıkla bu: Binance'e hiç çıkılmıyor.
- **paper_mode=False** ve **is_worker_role=True** olmasına rağmen order yoksa, sonraki adım: **EXEC_ORDER_ATTEMPT** ve **BINANCE_PLACE_ORDER** loglarının sırasıyla görünüp görünmediğini kontrol et (execution skip vs REST 403).

### Teşhis özeti (log zinciri) – Hangi log eksikse hata orada

| Log satırı | Eksikse anlamı | Düğüm |
|------------|----------------|--------|
| **BOT_MODE_CHECK** … paper_mode=… has_keys=… is_worker_role=… | Worker bu bot için tick etmiyor veya adapter kurulmadan önce çıkılıyor. | 1.3–1.4 |
| **BOT_MODE_CHECK**’te paper_mode=**True** | Binance’e hiç çıkılmıyor; _simulate_fill. **1 numaralı kök neden.** | 1.6 |
| **BOT_MODE_CHECK**’te is_worker_role=**False** | place_order 403; REST’e gidilmez. **2 numaralı kök neden.** | 1.7 |
| **EXEC_ORDER_ATTEMPT** | Strategy action üretmiyor veya run_actions skip (idempotency, min_notional, balance vb.). | 1.4–1.5 |
| **BINANCE_PLACE_ORDER** | Adapter’dan REST katmanına geçilemiyor (paper_mode True veya exception). | 1.6 → 1.7 |

**Kısa yorum:** Order yok problemini dosyanın teşhis diline göre iki düğüme indir: **1.6 paper_mode** (simülasyon) veya **1.7 worker_role guard** (403).

---

## 3 TANI ÇIKTISI (KOPYALA-YAPIŞTIR)

Kesin olarak "paper_mode mı / worker_role mü / worker hiç tick etmiyor mu" ayrımı için aşağıdaki üç çıktıyı al:

**1. Bot satırı (mode ve status):**
```sql
SELECT id, account_id, status, mode FROM bots WHERE id = <bot_id>;
```

**2. Son komutlar (worker komutu işledi mi):**
```sql
SELECT id, bot_id, command, status FROM bot_engine_commands WHERE bot_id = <bot_id> ORDER BY id DESC LIMIT 3;
```

**3. Worker logunda BOT_MODE_CHECK (adapter kurulurken):**
```
BOT_MODE_CHECK bot_id=... account_id=... bot.mode=... paper_mode=... has_keys=... is_worker_role=...
```

- **paper_mode=True** → Kök neden: simülasyon; REST yok. (B) düzeltmesi ile artık sadece `bot.mode=paper` ise True olmalı.
- **is_worker_role=False** veya **BINANCE_PLACE_ORDER** hiç yok → Worker role veya order path’e girmiyor.
- **bot_engine_commands** status hep PENDING → Worker tick etmiyor veya komut işlenmiyor.

### 3.1 Order submit zinciri başlamıyorsa (BOT_MODE_CHECK var, EXEC_ORDER_ATTEMPT/BINANCE_PLACE_ORDER yok)

**BOT_TICK_SUMMARY** (orchestrator’da strategy.tick sonrası INFO log):

- `actions=0` → Strategy koşulları tetiklenmiyor (initial_allocation_done / quote/base/price koşulları).
- `actions>0` ama EXEC_ORDER_ATTEMPT yok → Lock/lease veya run_actions öncesi başka drop (BOT_ACTION logları + bot_engine_events SKIP_REASON kontrolü).

**bot_engine_events’te neden trade yok (SKIP / ORDER_FAILED):**

```sql
SELECT id, ts, event_type, message, meta_json
FROM bot_engine_events
WHERE bot_id = <bot_id>
ORDER BY id DESC
LIMIT 80;
```

Aranacak: `SKIP_REASON` (MIN_NOTIONAL, INSUFFICIENT_QUOTE, IDEMPOTENT_LOCK, INTENT_ALREADY_FILLED, PRICE_STALE, LOCK_BUSY, WEIGHT_DENIED, KILL_SWITCH), `ORDER_FAILED`.

**Otomatik teşhis (loglara):** Bot loop her başladığında orchestrator `BOT_TEŞHIS_DUMP` ve `BOT_TEŞHIS_EVENT` satırlarını yazar (son 80 event özeti + son 10 event satırı). SQL elle çalıştırmak yerine worker loglarına bakın: `BOT_TEŞHIS_DUMP bot_id=... by_type=... skip_reasons=...`, ardından `BOT_TEŞHIS_EVENT id=... type=... message=...`.

---

## SECTION 1 – EXECUTION PATH MAP (FULL TRACE)

### 1.1 User Click → HTTP Route

| Attribute | Value |
|-----------|--------|
| **Expected function** | `bots_start` (POST handler) |
| **File path** | `app/api/bots_engine.py` |
| **Route** | `POST /api/bots-engine/{bot_id}/start` |
| **Router registration** | `app/main.py`: `app.include_router(bots_engine.router, prefix="/api/bots-engine")` |
| **Data contract** | Query: `account_id` (optional), `account_code` (optional). Body: none. Response: `{ ok, bot_id, account_id, request_id, command_id, bot_status, message }`. |
| **Required validation** | `_resolve_bot(bot_id, resolved_account_id, current, db)` must return non-None; else 404. `get_account_or_403(current, bot.account_id, db)`. |
| **Required logging** | Audit: `audit_svc.log_event(..., event_type="BOT_START", ...)`. No mandatory request_id in log line for start itself. |
| **Failure mode matrix** | 404 if bot not found; 403 if account mismatch; 200 + command queued even if worker never runs. |

### 1.2 Route → Service Layer

| Attribute | Value |
|-----------|--------|
| **Expected function** | No separate service; route writes DB and inserts command. |
| **File path** | `app/api/bots_engine.py`: `bots_start` sets `bot.status = "running"`, `bot.started_at = now`, commits, then `_insert_engine_command(db, bot.account_id, bot.id, "START", request_id=rid)`. |
| **Data contract** | Command row: `bot_engine_commands (created_at, account_id, bot_id, command='START', payload_json, status='PENDING', request_id)`. |
| **Required validation** | `ensure_state_row(db, bot.id, bot.account_id, symbol)`. |
| **Required logging** | None at this layer beyond audit. |
| **Failure mode matrix** | DB commit failure → 500; command insert failure → command_id None; worker may still poll and see PENDING. |

### 1.3 Service → Engine Dispatcher

| Attribute | Value |
|-----------|--------|
| **Expected function** | Worker loop polls `bot_engine_commands`; `process_command(cmd, db, v5_scheduler)` dispatches START. |
| **File path** | `app/botengine/worker_main.py`: `fetch_pending_commands(db)`, `mark_command_processing(db, cmd_id)`, `process_command(cmd, db, v5_scheduler)`. |
| **Data contract** | Command dict: `id, created_at, account_id, bot_id, command, payload_json, status, request_id`. START → `start_bot(bot_id, db)` (legacy) or v5_scheduler.register_bot(bot_id, time.monotonic()). |
| **Required validation** | `assert_bot_belongs_to_account(db, bot_id, account_id)` → (ok, bot_row). If not ok: mark_command_done with BOT_NOT_FOUND or ACCOUNT_MISMATCH. |
| **Required logging** | `WORKER_COMMAND_EXECUTED command_id=... bot_id=... command=START`. |
| **Failure mode matrix** | Worker not running → commands stay PENDING. Worker crash after PROCESSING → command stuck PROCESSING. v5_scheduler=0 → legacy start_bot; v5_scheduler=1 → register_bot only (no immediate tick). |

### 1.4 Engine → Strategy Layer

| Attribute | Value |
|-----------|--------|
| **Expected function** | Per-bot tick: strategy produces actions. Legacy: `_bot_loop` in `orchestrator.py`; v5: `run_one_bot_tick` in `bot_run.py`. |
| **File path** | Legacy: `app/botengine/orchestrator.py` `_bot_loop` → `strategy.tick(state, cfg, price, base_balance, quote_balance)`. v5: `app/botengine/bot_run.py` `run_one_bot_tick` → same. Strategy: `app/botengine/strategies/dca_grid_trailing.py` (DCA+Trailing) or `app/botengine/strategies/trdca_pro.py` (TRDCA). |
| **Data contract** | Strategy returns `(actions: List[Dict], next_wake_sec)`. Action: `{ type: "place", side, symbol, quantity, quote_qty?, reason, grid_index?, client_order_id?, ... }`. |
| **Required validation** | Price must be non-stale (DataHub). If `adapter.get_price(symbol)` None or <=0, tick skips trades (PRICE_STALE_OR_MISSING). |
| **Required logging** | `BOT_ACTION bot_id=... action_key=... type=... reason=... symbol=... quote_qty=... qty=...`. |
| **Failure mode matrix** | No price → no actions. Strategy returns empty actions → run_actions not called. initial_allocation_done already True → initial_allocation action skipped. |

### 1.5 Strategy → Order Builder

| Attribute | Value |
|-----------|--------|
| **Expected function** | Actions are built by strategy; execution layer builds intent_id and client_order_id. |
| **File path** | `app/botengine/execution.py` `run_actions`: for each action type "place", `build_intent_id(...)`, `build_client_order_id(...)` from `app/botengine/intent_ledger.py`. |
| **Data contract** | intent_id = `bot{bot_id}_cy{cycle_id}_it{hash16}`. client_order_id = `b{bot_id}c{cycle_id}i{ih}{ts}`[:36]. |
| **Required validation** | Idempotency: `check_idempotency(bot_id, key)`; intent row status FILLED → skip. upsert_intent before any submit. |
| **Required logging** | `BOT_EXECUTION_SKIP ... skip_reason=IDEMPOTENT_LOCK`; `BOT_EXECUTION_SKIP ... skip_reason=INTENT_ALREADY_FILLED`. |
| **Failure mode matrix** | Idempotency key hit → no submit. Intent already FILLED in DB → no submit. MIN_NOTIONAL fail → no submit. INSUFFICIENT_QUOTE / VIRTUAL_BUDGET_INSUFFICIENT → no submit. |

### 1.6 Order Builder → Exchange Adapter

| Attribute | Value |
|-----------|--------|
| **Expected function** | `BinanceAdapter.place_market_buy(symbol, quote_qty, client_order_id)` or `place_market_sell(symbol, qty, client_order_id)`. |
| **File path** | `app/botengine/adapters/binance_adapter.py`: `place_market_buy`, `place_market_sell`. If `self.paper_mode` → `_simulate_fill(...)` (no HTTP). |
| **Data contract** | BUY: payload `symbol, side=BUY, type=MARKET, quoteOrderQty, newClientOrderId`. SELL: `symbol, side=SELL, type=MARKET, quantity, newClientOrderId`. |
| **Required validation** | Adapter: min_notional check; get_symbol_filters. Execution: guard_min_notional before calling adapter. |
| **Required logging** | Adapter has no outbound REST log. Execution logs ORDER_FILLED after success; BOT_EXECUTION_SKIP on exception. |
| **Failure mode matrix** | paper_mode=True → _simulate_fill only; no REST. keys=None and not paper_mode → get_wallet/place_order will fail (keys from get_account_keys). |

### 1.7 Exchange Adapter → REST Client

| Attribute | Value |
|-----------|--------|
| **Expected function** | `place_order(keys, payload)` in binance_spot. |
| **File path** | `app/services/binance_spot.py`: `place_order(keys, payload)`. Calls `_signed_request(client, "POST", "/api/v3/order", keys, payload)`. Note: place_order receives payload as body params; signed_request builds query from params—for POST, payload is passed as form body. |
| **Data contract** | Binance POST /api/v3/order: symbol, side, type, quantity or quoteOrderQty, newClientOrderId, timestamp, recvWindow, signature. |
| **Required validation** | `is_worker_role()` must be True; else AppError WORKER_ONLY_OPERATION 403. |
| **Required logging** | `logger.debug("BINANCE_SIGN_DEBUG %s %s QUERY=...", method, path, ...)`. No mandatory INFO of full URL/body. |
| **Failure mode matrix** | Web process calling place_order → 403 (guard). Worker role but wrong DATABASE_ROLE env → is_worker_role() can be False if role != "worker". |

### 1.8 REST Client → Signature Generator

| Attribute | Value |
|-----------|--------|
| **Expected function** | `_signed_request_impl`: params with timestamp (Binance server time), recvWindow=60000, sorted query string, HMAC-SHA256 signature. |
| **File path** | `app/services/binance_spot.py`: `_get_binance_timestamp(client, testnet)`, `params["timestamp"]`, `params["recvWindow"]=60000`, `query_for_sign = "&".join(f"{k}={v}" for k, v in sorted(params_str.items()))`, `signature = _sign(keys.api_secret, query_for_sign)`. |
| **Data contract** | Query string order (sorted) must match exactly for signature. POST body = same query string + "&signature=" + signature. |
| **Required validation** | Timestamp from Binance /api/v3/time when possible (cache 30s); else -1021 possible. |
| **Required logging** | BINANCE_SIGN_DEBUG with masked signature. |
| **Failure mode matrix** | Local clock drift → -1021. Wrong secret → 401/-2015. Param order/encoding mismatch → signature invalid. |

### 1.9 HTTP Outbound → Binance Endpoint

| Attribute | Value |
|-----------|--------|
| **Expected URL** | Mainnet: `https://api.binance.com/api/v3/order`. Testnet: `https://testnet.binance.vision/api/v3/order`. |
| **File path** | `app/services/binance_spot.py`: `_base_url(getattr(keys, "testnet", False))`, `url = f"{base}{path}"`. |
| **Data contract** | POST, Content-Type application/x-www-form-urlencoded, body = final_query (params + signature). Header X-MBX-APIKEY: api_key. |
| **Required validation** | keys.testnet from Account.mode (binance_assets.get_account_keys): mode "testnet" → testnet True; is_test_account → testnet False for real accounts. |
| **Required logging** | None for successful 200 outbound. |
| **Failure mode matrix** | Network timeout → DependencyFailure. 429/418 → retry then raise. 400 with code in body → HTTPStatusError; 200 with code!=0 → HTTPStatusError. |

### 1.10 Binance Response → Adapter → Engine → DB → UI

| Attribute | Value |
|-----------|--------|
| **Expected function** | place_order returns dict: orderId, status, executedQty, cummulativeQuoteQty, fills. Adapter returns that; execution.run_actions parses fill_price, fee, applies apply_fill_to_state, Ledger.record_trade, update_virtual_after_fill, save_state, append_event ORDER_FILLED. |
| **File path** | `app/botengine/execution.py`: after `res = await adapter.place_market_buy/sell(...)`, update_intent_filled, apply_fill_to_state, cycle_ledger_add_fill, Ledger.record_trade, save_state, append_event. |
| **Data contract** | Response must have orderId; executedQty/cummulativeQuoteQty/fills for fill price/fee. |
| **Required validation** | intent_id update to FILLED; state persisted; Trade row inserted (Ledger.record_trade). |
| **Required logging** | BOT_TRADE_RECORDED bot_id=... order_id=...; BOT_CYCLE_END when cycle completes; ORDER_FILLED event. |
| **Failure mode matrix** | Exception in apply_fill_to_state or record_trade → state may be inconsistent; intent may be FILLED on exchange but not in DB. UI reads from state + trades; stale if save_state failed. |

---

## SECTION 2 – LIVE VS PAPER MODE FORENSIC CHECK

### 2.1 Identify live_mode flag

- **Bot row:** `Bot.mode` in DB: "live" or "paper". Set at create: `mode = "live" if not cfg.paper_mode else "paper"` (`app/api/bots_engine.py` create_bot_engine_core). At start: if bot.mode == "paper" and not is_test_account, mode forced to "live" and config_json paper_mode=False.
- **Grep:**
```bash
rg -n "\.mode\s*=" --type py app/
rg -n "mode.*live\|paper" --type py app/
```
- **Assert:** Before run_actions, log `bot.mode`, `adapter.paper_mode`, and account test status. Add in orchestrator/bot_run: `assert (bot.mode == "live") == (not adapter.paper_mode) or is_test_account` (with is_test_account allowing paper_mode True for test accounts).
- **Logging patch:** In `app/botengine/orchestrator.py` and `app/botengine/bot_run.py` where adapter is built, add:
```python
logger.info("BOT_MODE_CHECK bot_id=%s bot.mode=%s paper_mode=%s is_test=%s", bot_id, getattr(bot, "mode", None), paper_mode, is_test_account(account_id, db) if 'db' in dir() else None)
```

### 2.2 Identify testnet flag

- **Source:** `app/services/binance_assets.py`: `get_account_keys` → `mode = (getattr(account, "mode", None) or "live").strip().lower()`, `testnet = (mode == "testnet")`. For real (non-test) accounts, testnet forced False. BinanceKeys.testnet.
- **Grep:**
```bash
rg -n "testnet" --type py app/services/binance_spot.py app/services/binance_assets.py app/botengine/
```
- **Assert:** When placing live order, `assert getattr(adapter.keys, "testnet", True) == False` for non-test accounts.
- **Logging patch:** In binance_spot._signed_request_impl, log `testnet=getattr(keys, "testnet", None)` in BINANCE_SIGN_DEBUG.

### 2.3 Identify dry_run bypass

- **Search:** No "dry_run" in codebase. No dry_run bypass present.
- **Grep:**
```bash
rg -n "dry_run\|dry run" --type py app/ manager_server/
```

### 2.4 Identify mock adapter injection

- **Paper path:** `BinanceAdapter(account_id, keys, paper_mode=True)` → place_market_buy/sell call `_simulate_fill`; no place_order. Injected when `paper_mode=True`: `app/botengine/orchestrator.py` and `bot_run.py`: `paper_mode = bool(test_user and is_test_account_username(...) and not keys)`. So: test user + no API keys → paper_mode True.
- **Grep:**
```bash
rg -n "BinanceAdapter\(" --type py app/
rg -n "paper_mode" --type py app/botengine/
```
- **Assert:** For live intent, ensure no code path passes paper_mode=True for a non-test account. Check: get_account_keys returns keys for live account; is_test_account_username False → paper_mode must be False.

### 2.5 Identify environment variable drift

- **Worker role:** `DATABASE_ROLE=worker` set in worker_main.py before app.db import. `is_worker_role()` uses get_config()["database_role"] == "worker". If env is web or unset, place_order raises 403.
- **Grep:**
```bash
rg -n "DATABASE_ROLE\|is_worker_role" --type py app/
```
- **Validation script:**
```python
# scripts/check_worker_role.py
import os
os.environ.setdefault("DATABASE_ROLE", "web")
from app.core.config import get_config, is_worker_role
cfg = get_config()
print("database_role", cfg.get("database_role"), "is_worker_role", is_worker_role())
# Run as: DATABASE_ROLE=worker python scripts/check_worker_role.py  => True
```

### 2.6 Identify config override by manager

- **Manager:** manager_server does not override bot config or mode. It starts/stops web and engine processes; does not inject env for "paper" or "testnet".
- **Grep:**
```bash
rg -n "mode\|paper\|testnet" manager_server/
```

### 2.7 Identify DB-level bot_mode mismatch

- **Check:** Bot.mode in DB vs runtime paper_mode. If Bot.mode="live" but at runtime adapter.paper_mode=True (e.g. test user without keys on a live bot), orders are simulated.
- **SQL:**
```sql
SELECT id, account_id, symbol, status, mode FROM bots WHERE status = 'running';
-- Compare with accounts: SELECT id, mode FROM accounts;
```
- **Validation script:** For each running bot, load bot row and account; compute paper_mode (test user + no keys); assert bot.mode = 'live' and not paper_mode for production.

---

## SECTION 3 – ORDER CREATION VERIFICATION LAYER

### 3.1 Is client_order_id generated?

- **Yes.** intent_ledger.build_client_order_id(bot_id, cycle_id, symbol, side, qty, quote_qty, reason, grid_index) → `b{bot_id}c{cycle_id}i{ih}{ts}`[:36]. Used in run_actions; if intent row exists, reuse existing client_order_id from row.

### 3.2 Is idempotency enforced?

- **Yes.** check_idempotency(bot_id, key) in execution.py; upsert_intent; if status FILLED skip submit; get_order_by_client_order_id before submit to detect already-sent.

### 3.3 Is order payload constructed?

- **Yes.** BinanceAdapter.place_market_buy: payload = { symbol, side, type, quoteOrderQty, newClientOrderId }. place_order(keys, payload) sends as POST body. In binance_spot, place_order does NOT add timestamp/signature—signed_request is for GET with params. For POST /api/v3/order, Binance expects body params. Check: _signed_request_impl for POST uses request_kw = {"content": final_query}; final_query is built from params. So place_order must pass payload that gets merged into params for signature. Inspection: place_order(keys, payload) → _signed_request(client, "POST", "/api/v3/order", keys, payload). So params = payload; then timestamp, recvWindow added, then signature. So symbol, side, type, quoteOrderQty, newClientOrderId are in params and signed. Correct.

### 3.4 Is symbol normalized?

- **Yes.** symbol.upper() in adapter place_market_buy/sell and in execution (a.get("symbol") or config.symbol).

### 3.5 Is quantity rounded to lot_size?

- **Yes.** get_symbol_filters → step_size; _fmt_qty(quantity, step) for SELL. BUY uses quoteOrderQty (_fmt_quote).

### 3.6 Is min_notional validated?

- **Yes.** Adapter: quote_amount_usdt < min_notional raises ValueError. execution: guard_min_notional(notional, min_notional) before submit.

### 3.7 Is timestamp generated?

- **Yes.** _get_binance_timestamp (server time, cache 30s) in _signed_request_impl; params["timestamp"] = that value.

### 3.8 Is recvWindow applied?

- **Yes.** params["recvWindow"] = 60000 in _signed_request_impl.

### 3.9 Is signature generated?

- **Yes.** query_for_sign = sorted params; signature = hmac.new(secret, query_for_sign.encode(), hashlib.sha256).hexdigest(); POST body = query_for_sign + "&signature=" + signature.

### Sample canonical payload (MARKET BUY)

```
symbol=BTCUSDT
side=BUY
type=MARKET
quoteOrderQty=50.5
newClientOrderId=b1c0iabc123def4567890123456789012
timestamp=1739462400000
recvWindow=60000
signature=<hex>
```

### Example signed query string (order)

- Sorted: newClientOrderId, quoteOrderQty, recvWindow, side, symbol, timestamp, type. Then signature = HMAC-SHA256(api_secret, query_string).

### HMAC SHA256

- Binance: HMAC-SHA256(api_secret, query_string). Hex digest. Query string must be exact (key=value&... sorted).

### Common failure cases

- -1021: timestamp outside recvWindow (clock drift; use server time).
- -2015: Invalid API-key or IP.
- -2010: Insufficient balance.
- -1013: Invalid quantity/price (lot size, min notional).
- 401: Unauthorized (key/secret/IP).

---

## SECTION 4 – BINANCE RESPONSE HANDLING

### 4.1 HTTP status handling

- **Location:** app/services/binance_spot.py. r.raise_for_status() for non-2xx. Then if 200 and data.get("code") != 0, raise HTTPStatusError (so 200 with error body is treated as error).

### 4.2 JSON error parsing

- Body parsed; code = data.get("code"); msg = data.get("msg"). Raised as HTTPStatusError with response attached.

### 4.3 error_code mapping

| code | Meaning | Fatal | Retryable |
|------|---------|-------|-----------|
| -1021 | Timestamp outside recvWindow | Yes (fix clock) | No |
| -1022 | Invalid signature | Yes | No |
| -2015 | Invalid API-key | Yes | No |
| -2008 | Invalid Api-Key ID | Yes | No |
| -2010 | Insufficient balance | Yes (pause bot) | No |
| -1013 | Invalid quantity | Yes | No |
| 429 | Rate limit | No | Yes |
| 418 | IP banned | Yes | Backoff |

### 4.4 Rate-limit detection

- status_code in (429, 418); retry with backoff; after MAX_RETRIES raise DependencyFailure.

### 4.5 Time-drift detection

- -1021 in response body; log hint "Sunucu saati ile Binance saati uyumsuz". No automatic NTP sync in code.

### 4.6 Silent 200 but rejected status

- Handled: if isinstance(data, dict) and data.get("code", 0) != 0, logger.warning BINANCE_SIGNED_ERROR, then raise HTTPStatusError. So no silent accept.

### Structured error mapping table

| HTTP | code | Log level | Fatal | Action |
|------|------|-----------|-------|--------|
| 200 | 0 | - | - | Success |
| 200 | !=0 | WARNING | Yes | Raise |
| 400 | -2010 | WARNING | Yes | Pause bot, backoff |
| 400 | -2015,-2008 | DEBUG | Yes | Raise |
| 401 | - | DEBUG | Yes | Raise |
| 429/418 | - | WARNING | No | Retry |

### Required logging standard

- Every signed request: at least DEBUG with path, latency_ms, attempt. On error: path, status, body (truncated), code. No secret in log.

### Fatal vs retryable classification

- Fatal: auth (-2015, -2008, 401), invalid param (-1013, -1022), insufficient balance (-2010), timestamp (-1021). Retryable: 429, 418, timeout, connection errors (with circuit breaker).

---

## SECTION 5 – ASYNC TASK FAILURE ANALYSIS

### 5.1 BackgroundTasks usage

- FastAPI BackgroundTasks not used for order submission. Orders run in worker process in run_actions (await).

### 5.2 asyncio.create_task

- **Orchestrator:** _heartbeat_renew as asyncio.create_task; run_actions awaited. Reconciler: asyncio.create_task(_reconciler_background_task()). Scheduler: asyncio.create_task(v5_scheduler.run_loop()). If create_task used for run_actions without await, orders could be fire-and-forget (not the case: run_actions is awaited).

### 5.3 Unawaited coroutine detection

- **Grep:** `run_actions` is always awaited in orchestrator and bot_run. No `asyncio.create_task(run_actions(...))` without later await.

### 5.4 Task cancellation risk

- In orchestrator, heartbeat task cancelled in finally; run_actions is not cancelled mid-flight. If bot stop requested, _stop_requested set; loop exits after current tick; run_actions completes or fails.

### 5.5 Event loop blocking

- run_actions is async; adapter calls are await. No blocking sync Binance call in hot path (sync gateway exists but not used by engine).

### 5.6 Swallowed exception patterns

- execution.run_actions: per-action try/except; on exception append_event ERROR, state["last_error_code"]=..., continue. So exception does not stop the loop but is logged and event stored. Outer exception would propagate to orchestrator/bot_run and can pause bot (paused_error).

### Monkeypatch debug wrapper

```python
# In execution.py, wrap the actual place call:
_orig_place_buy = BinanceAdapter.place_market_buy
async def _debug_place_market_buy(self, symbol, quote_amount_usdt, client_order_id):
    import logging
    logging.getLogger(__name__).info("EXEC_DEBUG place_market_buy bot_id=%s symbol=%s quote=%s coid=%s paper_mode=%s",
        getattr(self, 'account_id'), symbol, quote_amount_usdt, client_order_id, self.paper_mode)
    return await _orig_place_buy(self, symbol, quote_amount_usdt, client_order_id)
BinanceAdapter.place_market_buy = _debug_place_market_buy
```

### Global exception hook

```python
# worker_main.py or main.py
def _excepthook(typ, val, tb):
    import traceback
    logging.getLogger().critical("UNCAUGHT_EXCEPTION type=%s value=%s traceback=%s", typ, val, traceback.format_tb(tb))
sys.excepthook = _excepthook
```

### Task instrumentation template

- Log task creation: asyncio.Task all_tasks(); log count and which coro names. Before/after run_actions log asyncio.current_task().get_name() and bot_id.

---

## SECTION 6 – MANAGER ↔ BACKEND EXECUTION GAP

### 6.1 Is execution happening in manager?

- **No.** Manager (manager_server) only starts/stops web and engine processes. It does not run bot loops or place orders.

### 6.2 Is backend expecting manager callback?

- **No.** Backend (FastAPI) does not expect manager to callback for execution. Commands are DB-driven: API writes bot_engine_commands; worker polls and processes.

### 6.3 Is there a websocket bridge?

- **No.** No WebSocket from manager to backend for order flow. Manager has WebSocket for UI/log streaming only.

### 6.4 Is execution flag stored but never triggered?

- **Possible.** bot.status = "running" and command INSERT happen in API. If worker is not running or not polling, commands stay PENDING. If worker runs but v5_scheduler and no bots registered (e.g. ensure_running_bots not adding this bot), bot loop may not run.

### 6.5 Is engine worker running?

- **Check:** .run/worker.pid exists and process alive; .run/engine.metrics.json has last_tick_ts and active_bots > 0. Worker writes engine.metrics.json every ~2s.

### Process inspection commands

```bash
# Is worker process running?
ps aux | grep "worker_main\|botengine.worker"
# PID file
cat .run/worker.pid
# Engine metrics (active bots, last tick)
cat .run/engine.metrics.json
```

### netstat checks

```bash
# Backend listening
netstat -an | grep 8000
# Manager
netstat -an | grep 7999
# Outbound to Binance (from worker)
# No persistent connection; HTTP only. Check with tcpdump or proxy log.
```

### Log correlation strategy

- Correlate: request_id from POST /api/bots-engine/{id}/start → bot_engine_commands.request_id → worker log "WORKER_COMMAND_EXECUTED ... command=START" → "BOT_LOOP_START" or v5 "run_one_bot_tick" → "run_actions start" → "BOT_ACTION" → "EXEC_DEBUG" (if patched) or "BOT_TRADE_RECORDED". If chain stops at COMMAND_EXECUTED with no BOT_LOOP_START, worker may not have started loop for that bot (v5: check register_bot; legacy: ensure_running_bots).

---

## SECTION 7 – DATABASE CONSISTENCY CHECK

### 7.1 bot.status vs engine_state mismatch

- bot.status = "running" can be set by API on start. engine_state (bot_engine_state) has state_json; no "status" field that must match. Possible mismatch: bot.status running but state.last_error_code set and bot later set to paused_error by orchestrator.

### 7.2 order_intent table presence

- **Schema:** order_intents (id, intent_id UNIQUE, bot_id, account_id, symbol, side, order_type, qty, price, created_at, updated_at, client_order_id UNIQUE, binance_order_id, status, submit_attempts, last_submit_ts, filled_qty, avg_price, last_error_code, last_error_id, final_ts, metadata_json). ensure_order_intents_table in schema_guard.

### 7.3 exchange_order_id storage

- binance_order_id in order_intents set by update_intent_filled(db, intent_id, res.get("orderId")). Trade table has order_id column (Ledger.record_trade).

### 7.4 Audit trail existence

- bot_engine_events: append_event writes event_type, message, meta_json. ORDER_FILLED, SKIP_REASON, ERROR etc.

### 7.5 Transaction commit verification

- execution: db.commit() after Ledger.record_trade and save_state are in same request; orchestrator save_state commits. SQLAlchemy session commit; no explicit two-phase.

### SQL validation queries

```sql
-- Running bots
SELECT id, account_id, symbol, status, mode FROM bots WHERE status = 'running';

-- Pending commands (should be 0 if worker is processing)
SELECT id, bot_id, command, status, created_at FROM bot_engine_commands WHERE status IN ('PENDING', 'PROCESSING') ORDER BY id DESC LIMIT 20;

-- Intents for a bot (recent)
SELECT intent_id, symbol, side, status, binance_order_id, created_at FROM order_intents WHERE bot_id = :bid ORDER BY id DESC LIMIT 20;

-- Trades for a bot
SELECT id, bot_id, side, qty, price, order_id, client_order_id, ts FROM trades WHERE bot_id = :bid ORDER BY ts DESC LIMIT 10;

-- Bot engine state
SELECT bot_id, cycle_id, mode, last_tick_at, last_error_code, updated_at FROM bot_engine_state WHERE bot_id = :bid;
```

### Consistency assertion script

```python
# scripts/assert_consistency.py
# For each running bot: 1) bot_engine_commands for this bot should not be stuck PENDING for > 60s.
# 2) If order_intents has SUBMITTING/SUBMITTED for this bot, binance_order_id or status update should have happened.
# 3) trades count for bot should match expectations from ORDER_FILLED events (optional, heavy).
```

---

## SECTION 8 – OBSERVABILITY GAP ANALYSIS

### 8.1 Missing request_id propagation

- request_id from API is stored in bot_engine_commands.request_id; not propagated to run_actions or binance_spot. So logs in execution/binance_spot do not include request_id.

### 8.2 Missing client_order_id trace

- client_order_id is in intent and logs (BOT_TRADE_RECORDED, ORDER_FILLED meta). Not consistently in every log line of the submit path.

### 8.3 No outbound REST logging

- No INFO log of full URL and body (without secret) for POST /api/v3/order. Only BINANCE_SIGN_DEBUG with masked signature.

### 8.4 No raw response capture

- Binance response is parsed and returned; not stored to a debug table or file. On error, body is in exception and log.

### 8.5 No execution latency metrics

- BinanceMetrics.record(path, elapsed_ms, retry_count) exists in binance_spot; path and latency recorded. No per-bot or per-order metric in execution layer.

### Logging standard (proposed)

- Every order attempt: INFO with request_id (if available), bot_id, account_id, client_order_id, symbol, side, quote_qty or qty, paper_mode, latency_ms, outcome (success/fail/code).

### Structured JSON log schema

```json
{
  "ts": "ISO8601",
  "level": "INFO",
  "event": "ORDER_SUBMIT",
  "bot_id": 1,
  "account_id": 1,
  "client_order_id": "b1c0i...",
  "symbol": "BTCUSDT",
  "side": "BUY",
  "quote_qty": 50.5,
  "paper_mode": false,
  "latency_ms": 120,
  "outcome": "success",
  "binance_order_id": "12345",
  "request_id": "abc-16"
}
```

### Metrics list

- order_submit_total (bot_id, side, outcome)
- order_submit_latency_seconds (histogram)
- binance_request_weight_used_total
- bot_tick_duration_seconds
- intent_status_total (status)

### Prometheus-style counters

- Same as above; labels: bot_id, account_id, symbol, side, outcome, error_code.

---

## SECTION 9 – LIVE EXECUTION ASSERTION TEST

### Design: Place 0.001 BTC market buy, verify open order, fill, DB, UI.

#### Step 1: Ensure worker is worker role and live

- Run worker with DATABASE_ROLE=worker. Use account with valid API keys and mode=live (mainnet).

#### Step 2: Create bot or use existing; start bot

```bash
curl -X POST "http://127.0.0.1:8000/api/bots-engine/1/start?account_id=1" \
  -H "Cookie: session=..." \
  -H "Content-Type: application/json"
# Expect 200, command_id, bot_status=running.
```

#### Step 3: Verify command processed

```sql
SELECT id, bot_id, command, status, processed_at FROM bot_engine_commands WHERE bot_id = 1 ORDER BY id DESC LIMIT 1;
-- status should be DONE.
```

#### Step 4: Trigger initial allocation or grid (strategy must emit place action)

- For DCA+Trailing, initial_allocation is first buy. Ensure bot has quote balance and strategy emits initial_allocation action. Check bot_engine_events for ORDER_FILLED or SKIP_REASON.

#### Step 5: Direct REST test (bypass app) to validate key/signature

```python
# scripts/direct_binance_order_test.py
import asyncio
import os
os.environ["DATABASE_ROLE"] = "worker"
from app.db.session import SessionLocal
from app.services.binance_assets import get_account_keys
from app.services.binance_spot import place_order

async def main():
    db = SessionLocal()
    keys = await get_account_keys(account_id=1, db=db)
    db.close()
    if not keys:
        print("No keys")
        return
    payload = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": "6",  # min notional ~5
        "newClientOrderId": "test_assert_1",
    }
    r = await place_order(keys, payload)
    print("orderId", r.get("orderId"), "status", r.get("status"))
asyncio.run(main())
```

#### Step 6: Timestamp sync test

```bash
# Binance server time
curl -s "https://api.binance.com/api/v3/time"
# Local ms
python3 -c "import time; print(int(time.time()*1000))"
# Diff should be < 5000 ms.
```

#### Step 7: recvWindow override test

- In binance_spot, recvWindow=60000 is fixed. To test larger window, temporarily set params["recvWindow"]=120000 and retry; if -1021 persists, issue is clock drift not window.

#### Step 8: Verify DB and UI

- After real fill: order_intents has status=FILLED, binance_order_id set; trades has new row; bot_engine_state has updated base_balance/quote_balance. UI: bot detail shows trades and updated balances.

---

## SECTION 10 – ROOT CAUSE TREE MATRIX

### LEVEL 1

| Node | Description |
|------|-------------|
| A | Order never built |
| B | Order built but never sent |
| C | Sent but rejected |
| D | Accepted but never persisted |
| E | Persisted but UI stale |

### LEVEL 2 (sub-causes)

**A – Order never built**
- A1: Strategy returns no actions (price stale, no trigger, initial_allocation_done already True).
- A2: Strategy not run (worker not ticking this bot: not registered in v5, or legacy ensure_running_bots did not start loop).
- A3: Bot not running (status != running; or command never processed).
- A4: Lock not acquired (LOCK_BUSY) or lease expired (LOCK_LEASE_EXPIRED) so run_actions not called.
- A5: Idempotency skip (action_key already done).
- A6: Intent already FILLED in DB (reconciled or previous run).
- A7: MIN_NOTIONAL or INSUFFICIENT_QUOTE or VIRTUAL_BUDGET_INSUFFICIENT skip.
- A8: BINANCE_FREE_QUOTE_INSUFFICIENT or BINANCE_FREE_BASE_INSUFFICIENT pre-check.
- A9: WEIGHT_DENIED (weight governor).
- A10: Kill switch.

**B – Order built but never sent**
- B1: paper_mode=True → _simulate_fill only (no HTTP).
- B2: is_worker_role() False → place_order raises 403 (Web process).
- B3: place_order not reached (exception before adapter.place_market_buy/sell in run_actions: e.g. timeout, balance check exception swallowed and continue).
- B4: asyncio.wait_for(..., timeout=3.0) TimeoutError → update_intent_unknown(TIMEOUT), continue.
- B5: keys None or invalid so get_wallet/place_order fails earlier (e.g. in balance check).

**C – Sent but rejected**
- C1: -1021 timestamp (clock drift).
- C2: -2015/-2008/401 (key/IP/permissions).
- C3: -2010 insufficient balance.
- C4: -1013 invalid quantity/notional.
- C5: 429/418 then DependencyFailure after retries.
- C6: Network/timeout → DependencyFailure.

**D – Accepted but never persisted**
- D1: update_intent_filled or Ledger.record_trade throws; state updated in memory but DB rollback or not committed.
- D2: save_state not called after apply_fill_to_state (bug in branch, e.g. trdca_batch early continue).
- D3: Different process/connection sees stale read (unlikely if single worker).

**E – Persisted but UI stale**
- E1: UI cache (e.g. live snapshot TTL 2s).
- E2: Frontend not refetching trades/state.
- E3: Web and worker different DB file (misconfiguration; should be same).

### LEVEL 3 – Detection method for each

| Id | Detection |
|----|-----------|
| A1 | Logs: PRICE_STALE_OR_MISSING, BOT_EXECUTION_SKIP skip_reason=IDEMPOTENT_LOCK/INTENT_ALREADY_FILLED/MIN_NOTIONAL/INSUFFICIENT_QUOTE/VIRTUAL_BUDGET_INSUFFICIENT. Events: SKIP_REASON. |
| A2 | No BOT_LOOP_START or run_one_bot_tick for this bot_id; engine.metrics.json active_bots; v5 _registered. |
| A3 | SELECT status FROM bots WHERE id=?; SELECT status FROM bot_engine_commands WHERE bot_id=? ORDER BY id DESC LIMIT 1. |
| A4 | Events: LOCK_BUSY, LOCK_LEASE_EXPIRED. Logs: BOT_TICK lease_not_valid. |
| A5,A6 | order_intents row for intent_id status=FILLED; logs BOT_EXECUTION_SKIP INTENT_ALREADY_FILLED. |
| A7,A8 | Logs BOT_EXECUTION_SKIP skip_reason=MIN_NOTIONAL/INSUFFICIENT_QUOTE/BINANCE_FREE_QUOTE_INSUFFICIENT. |
| A9 | Logs run_actions WEIGHT_DENIED; intent last_error_code WEIGHT_DENIED. |
| A10 | check_kill_switch() raises; BOT_ENGINE_KILL_SWITCH=1. |
| B1 | Log BOT_MODE_CHECK paper_mode=True; adapter.paper_mode True; no outbound POST to api.binance.com. |
| B2 | Only on Web: place_order raises AppError WORKER_ONLY_OPERATION. Log from guard. |
| B3 | Exception log in run_actions (BOT_EXECUTION_SKIP ORDER_FAILED, RUN_ACTION_EXCEPTION). |
| B4 | Log run_actions TIMEOUT; intent status UNKNOWN. |
| B5 | get_account_keys returns None; or get_wallet fails (log ACCOUNT_CALL or exception). |
| C1–C6 | Binance response: log BINANCE_SIGNED_ERROR path, status, body, code. execution: append_event ORDER_FAILED / state last_error_code. |
| D1,D2 | Compare order_intents.binance_order_id and trades.order_id for same client_order_id; check bot_engine_state.base_balance/quote_balance after ORDER_FILLED event. |
| E1–E3 | Refresh UI; check same DB path for web and worker. |

---

## SECTION 11 – PATCH STRATEGY

### Minimal invasive patch plan

1. **Instrumentation first:** Add BOT_MODE_CHECK and EXEC_ORDER_ATTEMPT (bot_id, client_order_id, symbol, side, quote_qty, paper_mode) before adapter.place_market_buy/sell. Add EXEC_ORDER_RESULT (bot_id, client_order_id, outcome, binance_order_id or error_code) after. No change to control flow.
2. **Log request_id:** Pass request_id from command to run_actions (or store in state) and log in execution (optional; requires signature change).
3. **Outbound REST log (DEBUG):** In binance_spot _signed_request_impl, log URL (without signature value), method, path at DEBUG. Keep secret out.
4. **Assert worker role at start of run_actions:** If not is_worker_role(), log CRITICAL and return empty results (defence in depth).
5. **DB consistency check script:** Run periodically: running bots with no ORDER_FILLED in last N minutes but no SKIP_REASON explaining why → alert.

### Do NOT rewrite engine blindly

- Do not change strategy logic or lock/semantics. Only add logging and optional asserts.

### Step-by-step isolation plan

1. Reproduce: start one bot (live account, mainnet), ensure worker running with DATABASE_ROLE=worker.
2. Confirm command DONE and bot loop running (BOT_LOOP_START or v5 tick for bot_id).
3. Confirm strategy emits action (BOT_ACTION with type=place).
4. Confirm run_actions called (run_actions start bot_id=).
5. Confirm no skip before place (no BOT_EXECUTION_SKIP between run_actions start and place_market_buy/sell).
6. Confirm place_market_buy/sell called (add EXEC_ORDER_ATTEMPT log).
7. Confirm paper_mode False (BOT_MODE_CHECK).
8. Confirm place_order called (add log in binance_spot.place_order).
9. Confirm is_worker_role() True (add log at start of place_order).
10. If all true and still no fill: capture Binance response (temporarily log response body on 200 and on error).

### Rollback strategy

- All patches are additive (logs/asserts). Rollback = remove new log lines and asserts. No schema or control-flow rollback needed.

---

## SECTION 12 – PRODUCTION HARDENING ADDITIONS

### Idempotent order submission

- Already present: intent_id + client_order_id deterministic; upsert_intent before submit; get_order_by_client_order_id before submit. Harden: ensure every code path that calls place_* goes through intent persist and reuse client_order_id.

### Exchange confirmation polling

- After place_order returns, optionally poll get_order_by_client_order_id until status FILLED/CANCELED/EXPIRED or timeout (e.g. 30s). If timeout, mark intent UNKNOWN and let reconciler resolve. Currently execution assumes immediate FILLED for MARKET; Binance often returns FILLED in same response. Polling adds safety for partial fills or delayed status.

### Dead letter queue

- For intents stuck SUBMITTING/UNKNOWN after N minutes, write to a table or queue (e.g. order_intent_dlq) with bot_id, intent_id, last_error_code, created_at for manual review and reconcile.

### Order execution state machine

- Already in intent_ledger: NEW → PERSISTED → SUBMITTING → SUBMITTED → FILLED/CANCELED/REJECTED/UNKNOWN. Enforce: never submit without PERSISTED; never mark FILLED without exchange orderId. Add transition log (audit) for each status change.

### Fail-safe halt mechanism

- Kill switch: BOT_ENGINE_KILL_SWITCH=1 or set_kill_switch(True); check_kill_switch() before submit. Already present. Add: on repeated ORDER_FAILED (e.g. -2015) for same bot, auto-set bot.status = paused_error and append_event HALT_REASON so bot stops until operator fixes key.

---

## SECTION 13 – FINAL CHECKLIST

Binary YES/NO. Answer each for the deployment where "no real orders" occurs.

| # | Check | Y/N |
|---|--------|-----|
| 1 | Worker process is running (PID from .run/worker.pid exists and process alive). | |
| 2 | DATABASE_ROLE=worker in worker process environment. | |
| 3 | is_worker_role() returns True in worker process (script check). | |
| 4 | Bot row status = 'running' for the bot. | |
| 5 | Bot row mode = 'live' (not 'paper') for production account. | |
| 6 | Account has API keys (get_account_keys(account_id, db) returns keys). | |
| 7 | Account.mode is not 'testnet' for mainnet trading (or keys.testnet is False). | |
| 8 | is_test_account(account_id, db) is False for production account. | |
| 9 | BinanceAdapter for this bot is built with paper_mode=False. | |
| 10 | At least one bot_engine_command START for this bot has status = 'DONE'. | |
| 11 | Bot loop or v5 scheduler has run for this bot (BOT_LOOP_START or run_one_bot_tick log for bot_id). | |
| 12 | DataHub/price returns non-stale price for bot symbol (adapter.get_price(symbol) > 0). | |
| 13 | Strategy tick returns at least one action with type='place' for the scenario (e.g. initial_allocation). | |
| 14 | run_actions is invoked for this bot (log "run_actions start bot_id=..."). | |
| 15 | No BOT_EXECUTION_SKIP before place_market_buy/sell for this action (no idempotency/min_notional/balance skip). | |
| 16 | place_market_buy or place_market_sell is called (add temporary log to confirm). | |
| 17 | binance_spot.place_order is called (add temporary log to confirm). | |
| 18 | No 403 from is_worker_role() in place_order. | |
| 19 | HTTP request reaches Binance (no network/DNS failure; check proxy/firewall). | |
| 20 | Binance response is 200 with code=0 (or error response logged with code). | |
| 21 | order_intents has row for this intent with status FILLED and binance_order_id set after run. | |
| 22 | trades table has new row for this bot/order after run. | |
| 23 | bot_engine_state updated (base_balance/quote_balance) after run. | |
| 24 | bot_engine_events has ORDER_FILLED event for this bot. | |
| 25 | Same SQLite DB file used by Web and Worker (same path or symlink). | |

**Usage:** Set Y for each verified true; N for false or untested. First N in order 1–25 indicates likely failure layer (e.g. first N at 9 → paper_mode True; at 17 → place_order not reached; at 20 → Binance rejected).

---

## APPENDIX A – CODE REFERENCE SNIPPETS (EXECUTION PATH)

### A.1 Route registration (main.py)

```python
# app/main.py (excerpt)
from app.api import bots_engine
app.include_router(bots_engine.router, prefix="/api/bots-engine")
# Route: POST /api/bots-engine/{bot_id}/start
```

### A.2 bots_start – DB and command insert

```python
# app/api/bots_engine.py
@router.post("/{bot_id}/start")
async def bots_start(...):
    bot.status = "running"
    bot.started_at = datetime.now(timezone.utc)
    db.commit()
    seed_perf_chart_state_on_bot_start(db, bot.id)
    command_id = _insert_engine_command(db, bot.account_id, bot.id, "START", request_id=rid)
    return {"ok": True, "bot_id": bot.id, "command_id": command_id, "bot_status": "running", ...}
```

### A.3 Worker poll and process_command

```python
# app/botengine/worker_main.py
pending = fetch_pending_commands(db, limit=50)
for cmd in pending:
    if not mark_command_processing(db, cmd["id"]): continue
    await process_command(cmd, db, v5_scheduler=v5_scheduler)
# process_command: if command == "START": start_bot(bot_id, db) or v5_scheduler.register_bot(bot_id, ...)
```

### A.4 run_actions – place path

```python
# app/botengine/execution.py (simplified)
async with await acquire_bot_lock(bot_id):
    for a in actions:
        if a.get("type") != "place": continue
        # ... idempotency, min_notional, balance checks ...
        if side == "BUY":
            res = await asyncio.wait_for(adapter.place_market_buy(symbol, quote_qty, client_order_id), timeout=3.0)
        else:
            res = await asyncio.wait_for(adapter.place_market_sell(symbol, qty, client_order_id), timeout=3.0)
        # update_intent_filled, apply_fill_to_state, Ledger.record_trade, save_state
```

### A.5 BinanceAdapter.place_market_buy (live vs paper)

```python
# app/botengine/adapters/binance_adapter.py
async def place_market_buy(self, symbol, quote_amount_usdt, client_order_id):
    symbol = symbol.upper()
    if self.paper_mode:
        return self._simulate_fill(symbol, "BUY", quote_qty=quote_amount_usdt, client_order_id=client_order_id)
    # ...
    return await place_order(self.keys, payload)
```

### A.6 binance_spot.place_order – worker guard

```python
# app/services/binance_spot.py
async def place_order(keys, payload):
    from app.core.config import is_worker_role
    from app.core.errors import AppError
    if not is_worker_role():
        raise AppError("WORKER_ONLY_OPERATION", "Order placement is only allowed on worker process.", status_code=403)
    return await _signed_request(client, "POST", "/api/v3/order", keys, payload)
```

### A.7 Signed request – timestamp and signature

```python
# app/services/binance_spot.py _signed_request_impl
params["timestamp"] = await _get_binance_timestamp(client, getattr(keys, "testnet", False))
params["recvWindow"] = 60000
query_for_sign = "&".join(f"{k}={v}" for k, v in sorted(params_str.items()))
signature = _sign(keys.api_secret, query_for_sign)
final_query = query_for_sign + "&signature=" + signature
# POST: headers["Content-Type"] = "application/x-www-form-urlencoded"; request_kw = {"content": final_query}
```

---

## APPENDIX B – GREP COMMAND REFERENCE

All commands from project root. Use to locate live/paper, worker role, and order flow.

```bash
# Live vs paper
rg -n "paper_mode|\.mode\s*=\s*['\"]live|\.mode\s*=\s*['\"]paper" --type py app/
rg -n "is_test_account|is_test_account_username" --type py app/

# Worker role and place_order
rg -n "is_worker_role|DATABASE_ROLE" --type py app/
rg -n "place_order|place_market_buy|place_market_sell" --type py app/

# Execution path
rg -n "run_actions|_insert_engine_command|fetch_pending_commands|process_command" --type py app/
rg -n "build_intent_id|build_client_order_id|upsert_intent" --type py app/

# Binance signed
rg -n "_signed_request|_get_binance_timestamp|recvWindow" --type py app/services/binance_spot.py

# Adapter paper branch
rg -n "_simulate_fill|paper_mode" --type py app/botengine/adapters/binance_adapter.py
```

---

## APPENDIX C – SQL VALIDATION QUERIES (FULL SET)

```sql
-- 1) Running bots and mode
SELECT id, account_id, symbol, status, mode, started_at
FROM bots
WHERE status = 'running'
ORDER BY id;

-- 2) Last 20 commands with status
SELECT id, bot_id, account_id, command, status, created_at, processed_at, error_code, request_id
FROM bot_engine_commands
ORDER BY id DESC
LIMIT 20;

-- 3) Pending/processing commands (stuck)
SELECT id, bot_id, command, status, created_at,
       (julianday('now') - julianday(created_at)) * 24 * 60 AS age_minutes
FROM bot_engine_commands
WHERE status IN ('PENDING', 'PROCESSING')
ORDER BY id;

-- 4) Order intents for bot (recent, any status)
SELECT id, intent_id, symbol, side, status, client_order_id, binance_order_id,
       submit_attempts, last_error_code, created_at, updated_at
FROM order_intents
WHERE bot_id = :bid
ORDER BY id DESC
LIMIT 30;

-- 5) Intents stuck SUBMITTING or UNKNOWN
SELECT intent_id, bot_id, symbol, side, status, last_error_code, last_submit_ts, created_at
FROM order_intents
WHERE status IN ('SUBMITTING', 'UNKNOWN', 'SUBMITTED', 'SENT', 'PENDING', 'PERSISTED')
ORDER BY id DESC
LIMIT 50;

-- 6) Trades for bot
SELECT id, bot_id, account_id, side, qty, price, fee, order_id, client_order_id, symbol, cycle_id, ts
FROM trades
WHERE bot_id = :bid
ORDER BY ts DESC
LIMIT 20;

-- 7) Bot engine state (one row per bot)
SELECT bot_id, account_id, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at,
       json_extract(state_json, '$.base_balance') AS base_balance,
       json_extract(state_json, '$.quote_balance') AS quote_balance,
       json_extract(state_json, '$.initial_allocation_done') AS initial_allocation_done
FROM bot_engine_state
WHERE bot_id = :bid;

-- 8) Recent bot_engine_events for bot
SELECT id, event_type, message, meta_json, ts
FROM bot_engine_events
WHERE bot_id = :bid
ORDER BY id DESC
LIMIT 50;

-- 9) Account keys presence (accounts table; keys stored encrypted elsewhere)
SELECT id, account_id, mode FROM accounts WHERE id = :aid;

-- 10) Consistency: intents FILLED but no trade with same order_id
SELECT oi.intent_id, oi.binance_order_id, oi.client_order_id, oi.updated_at
FROM order_intents oi
LEFT JOIN trades t ON t.order_id = oi.binance_order_id AND t.bot_id = oi.bot_id
WHERE oi.status = 'FILLED' AND oi.binance_order_id IS NOT NULL AND t.id IS NULL
ORDER BY oi.id DESC
LIMIT 20;
```

---

## APPENDIX D – BINANCE ERROR CODES (EXTENDED)

| code | msg (typical) | Fatal | Retry | Detection |
|------|----------------|-------|-------|-----------|
| 0 | - | No | - | Success |
| -1000 | Unknown error | Maybe | Yes | Log body |
| -1001 | Disconnected | No | Yes | Retry |
| -1002 | Unauthorized | Yes | No | Key/secret |
| -1003 | Too many requests | No | Yes | 429 |
| -1021 | Timestamp outside recvWindow | Yes | No | Sync clock / server time |
| -1022 | Invalid signature | Yes | No | Secret/query order |
| -2010 | New order rejected (insufficient balance) | Yes | No | Pause bot |
| -2011 | Unknown order type | Yes | No | Payload |
| -2013 | Order does not exist | No | - | Reconcile |
| -2015 | Invalid API-key | Yes | No | Key/IP |
| -2008 | Invalid Api-Key ID | Yes | No | Key |
| -1013 | Invalid quantity | Yes | No | Lot size/step |
| -1111 | Precision over maximum | Yes | No | Format qty/price |
| -1112 | No need to change position side | No | - | Logic |
| 429 | Rate limit | No | Yes | Backoff |
| 418 | IP banned | Yes | Backoff | IP whitelist |

---

## APPENDIX E – LOGGING PATCH POINTS (EXACT LOCATIONS)

| # | File | Function | Line (approx) | Patch |
|---|------|----------|----------------|-------|
| 1 | app/botengine/orchestrator.py | _bot_loop | After adapter = BinanceAdapter(...) | logger.info("BOT_MODE_CHECK bot_id=%s paper_mode=%s has_keys=%s", bot_id, paper_mode, has_keys) |
| 2 | app/botengine/bot_run.py | run_one_bot_tick | After adapter = BinanceAdapter(...) | Same BOT_MODE_CHECK |
| 3 | app/botengine/execution.py | run_actions | Immediately before `res = await asyncio.wait_for(adapter.place_market_buy(...))` | logger.info("EXEC_ORDER_ATTEMPT bot_id=%s symbol=%s side=%s quote_qty=%s coid=%s paper_mode=%s", bot_id, symbol, side, quote_qty, client_order_id, adapter.paper_mode) |
| 4 | app/botengine/execution.py | run_actions | Immediately after res = await ... (success path) | logger.info("EXEC_ORDER_RESULT bot_id=%s coid=%s outcome=success order_id=%s", bot_id, client_order_id, res.get("orderId")) |
| 5 | app/botengine/execution.py | run_actions | In except block after place_market_* | logger.warning("EXEC_ORDER_RESULT bot_id=%s coid=%s outcome=fail err=%s", bot_id, client_order_id, e) |
| 6 | app/services/binance_spot.py | place_order | First line (after imports) | logger.info("BINANCE_PLACE_ORDER symbol=%s side=%s worker_role=%s", payload.get("symbol"), payload.get("side"), is_worker_role()) |
| 7 | app/services/binance_spot.py | _signed_request_impl | After final_query = ... | logger.debug("BINANCE_OUTBOUND method=%s path=%s url=%s body_len=%s", method, path, url, len(final_query)) |
| 8 | app/botengine/worker_main.py | process_command | Start of command == "START" | logger.info("WORKER_START_CMD cmd_id=%s bot_id=%s v5=%s", cmd_id, bot_id, v5_scheduler is not None) |

---

## APPENDIX F – ENVIRONMENT AND CONFIG INDEX

| Variable | Where read | Effect |
|----------|------------|--------|
| DATABASE_ROLE | app/core/config.get_config() | "worker" => is_worker_role() True |
| PROCESS_ROLE | app/core/config.get_config() | "web"/"api" => is_worker_role() False |
| BOT_ENGINE_V5_SCHEDULER | app/botengine/worker_main.py | "1" => use BotScheduler, else legacy _bot_loop |
| BOT_ENGINE_KILL_SWITCH | app/botengine/kill_switch | "1" => check_kill_switch() raises |
| DEFAULT_LEASE_TTL_SEC | app/botengine/locks.py | Symbol lock TTL (default 10) |
| LOCK_HEARTBEAT_SEC | config | Heartbeat interval (default 3) |
| (Account.mode in DB) | binance_assets.get_account_keys | "testnet" => keys.testnet True |
| (Bot.mode in DB) | bots_engine, orchestrator | "paper" vs "live" display and start override |

---

## APPENDIX G – FILE PATH INDEX (EXECUTION CRITICAL)

| Path | Purpose |
|------|---------|
| app/main.py | Router include bots_engine; lifespan |
| app/api/bots_engine.py | bots_start, bots_stop, create, detail, _insert_engine_command |
| app/botengine/worker_main.py | worker_loop, fetch_pending_commands, process_command, start_bot/register_bot |
| app/botengine/orchestrator.py | _bot_loop, start_bot, stop_bot, ensure_running_bots, run_actions call |
| app/botengine/bot_run.py | run_one_bot_tick (v5), strategy tick, run_actions call |
| app/botengine/execution.py | run_actions, intent upsert, adapter.place_market_*, apply_fill_to_state, Ledger.record_trade |
| app/botengine/adapters/binance_adapter.py | BinanceAdapter, place_market_buy, place_market_sell, _simulate_fill |
| app/botengine/intent_ledger.py | build_intent_id, build_client_order_id, upsert_intent, update_intent_* |
| app/services/binance_spot.py | place_order, _signed_request_impl, _get_binance_timestamp, is_worker_role guard |
| app/services/binance_assets.py | get_account_keys, BinanceKeys, testnet from Account.mode |
| app/core/config.py | get_config, is_worker_role |
| app/db/models.py | Bot, Account, Trade |
| app/db/schema_guard.py | ensure_bot_engine_commands_table, ensure_order_intents_table |
| manager_server/app.py | Start/stop web and engine; no execution |

---

## APPENDIX H – CLI DEBUGGING COMMANDS

```bash
# Worker running?
pgrep -f "worker_main|botengine.worker" && echo "RUNNING" || echo "NOT_RUNNING"

# Role in worker
python3 -c "
import os
os.environ.setdefault('DATABASE_ROLE', '')
from app.core.config import get_config, is_worker_role
print('DATABASE_ROLE', repr(get_config().get('database_role')))
print('is_worker_role', is_worker_role())
"

# Binance server time vs local
curl -s 'https://api.binance.com/api/v3/time' | python3 -c "import sys,json,time; d=json.load(sys.stdin); print('server', d.get('serverTime')); print('local', int(time.time()*1000)); print('diff_ms', int(d.get('serverTime',0))-int(time.time()*1000))"

# Open orders (requires keys in DB and script)
# Use scripts/direct_binance_order_test.py pattern with get_open_orders.

# SQLite: quick bot status
sqlite3 dca.db "SELECT id, symbol, status, mode FROM bots WHERE status='running';"

# SQLite: last command per bot
sqlite3 dca.db "SELECT bot_id, command, status, created_at FROM bot_engine_commands ORDER BY id DESC LIMIT 10;"

# Logs (if worker logs to file)
tail -n 200 logs/worker.log | grep -E "BOT_LOOP_START|run_actions|BOT_ACTION|ORDER_FILLED|BOT_EXECUTION_SKIP|place_order"
```

---

## APPENDIX I – NETSTAT / CURL / OPENSSL TIMESTAMP TEST

```bash
# Backend listening
netstat -tlnp 2>/dev/null | grep 8000 || ss -tlnp | grep 8000

# Manager listening
netstat -tlnp 2>/dev/null | grep 7999 || ss -tlnp | grep 7999

# Curl health (no auth)
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health 2>/dev/null || true

# Binance connectivity
curl -s -o /dev/null -w "%{http_code}" "https://api.binance.com/api/v3/ping"
curl -s "https://api.binance.com/api/v3/time" | head -1

# OpenSSL timestamp (NTP-style check): ensure system time in sync
# Linux: timedatectl
# Manual: compare Binance serverTime with (date +%s)*1000
```

---

## APPENDIX J – STRUCTURED LOG EXAMPLES (TARGET SCHEMA)

Success path (one order):

```json
{"ts":"2026-02-13T12:00:00.000Z","level":"INFO","event":"ORDER_SUBMIT","bot_id":1,"account_id":1,"client_order_id":"b1c0iabc1234567890123456789012","symbol":"BTCUSDT","side":"BUY","quote_qty":50.5,"paper_mode":false,"request_id":"req-abc-16"}
{"ts":"2026-02-13T12:00:00.120Z","level":"INFO","event":"ORDER_RESULT","bot_id":1,"client_order_id":"b1c0iabc1234567890123456789012","outcome":"success","binance_order_id":"12345678","latency_ms":120}
{"ts":"2026-02-13T12:00:00.121Z","level":"INFO","event":"ORDER_FILLED","bot_id":1,"order_id":"12345678","side":"BUY","fill_qty":0.0005,"fill_price":101000.0,"fee":0.05}
```

Failure path (rejected):

```json
{"ts":"2026-02-13T12:00:00.000Z","level":"INFO","event":"ORDER_SUBMIT","bot_id":1,"account_id":1,"client_order_id":"b1c0i...","symbol":"BTCUSDT","side":"BUY","quote_qty":50.5,"paper_mode":false}
{"ts":"2026-02-13T12:00:00.080Z","level":"WARNING","event":"ORDER_RESULT","bot_id":1,"client_order_id":"b1c0i...","outcome":"rejected","binance_code":-1021,"binance_msg":"Timestamp for this request is outside of the recvWindow.","latency_ms":80}
```

---

## APPENDIX K – FAILURE CLASSIFICATION TABLE (EXECUTION LAYER)

| Skip reason / Error | Location (execution.py) | Log pattern | Fatal for this order | Next step |
|---------------------|-------------------------|-------------|----------------------|-----------|
| IDEMPOTENT_LOCK | check_idempotency | BOT_EXECUTION_SKIP skip_reason=IDEMPOTENT_LOCK | Yes | None |
| INTENT_ALREADY_FILLED | intent_row.status==FILLED | BOT_EXECUTION_SKIP skip_reason=INTENT_ALREADY_FILLED | Yes | Reconcile state if needed |
| MIN_NOTIONAL | guard_min_notional | BOT_EXECUTION_SKIP skip_reason=MIN_NOTIONAL | Yes | Increase size or lower min |
| INSUFFICIENT_QUOTE | initial_allocation required > available | BOT_EXECUTION_SKIP skip_reason=INSUFFICIENT_QUOTE | Yes | Add balance |
| VIRTUAL_BUDGET_INSUFFICIENT | check_virtual_budget | BOT_EXECUTION_SKIP error_code=VIRTUAL_BUDGET_INSUFFICIENT | Yes | Adjust budget/state |
| BINANCE_FREE_QUOTE_INSUFFICIENT | free_usdt check | BOT_EXECUTION_SKIP error_code=BINANCE_FREE_QUOTE_INSUFFICIENT | Yes | Add USDT |
| BINANCE_FREE_BASE_INSUFFICIENT | free_base check (SELL) | BOT_EXECUTION_SKIP error_code=BINANCE_FREE_BASE_INSUFFICIENT | Yes | Sync state/balance |
| WEIGHT_DENIED | request_weight_tokens | run_actions WEIGHT_DENIED | No | Retry later |
| TIMEOUT | asyncio.wait_for(3.0) | run_actions TIMEOUT | Transient | Reconcile |
| ORDER_FAILED | Exception in place_* | BOT_EXECUTION_SKIP skip_reason=ORDER_FAILED | Depends on code | Check Binance code |
| INSUFFICIENT_BALANCE | -2010 | BOT_EXECUTION_INSUFFICIENT_BALANCE, bot paused | Yes | Add balance, resume |
| RUN_ACTION_EXCEPTION | Any exception in loop | RUN_ACTION_EXCEPTION error_id=... | Yes | Fix bug / inspect |

---

## APPENDIX L – ADDITIONAL CHECKLIST ITEMS (26–50)

| # | Check | Y/N |
|---|--------|-----|
| 26 | ensure_running_bots (legacy) or v5_scheduler.run_loop is running. | |
| 27 | For v5: bot_id is in v5_scheduler._registered after START. | |
| 28 | strategy.tick called for this bot (log BOT_PRICE or BOT_ACTION or TRDCA decision). | |
| 29 | actions list non-empty when strategy expects to trade (e.g. initial_allocation first tick). | |
| 30 | Symbol lock acquired (no LOCK_BUSY in events). | |
| 31 | lease_still_valid True before run_actions (no LOCK_LEASE_EXPIRED). | |
| 32 | check_idempotency(bot_id, key) returns False (not skipping). | |
| 33 | upsert_intent returns is_new=True or existing row status not FILLED. | |
| 34 | get_order_by_client_order_id not returning FILLED order (no duplicate submit). | |
| 35 | guard_min_notional(notional, min_notional) True. | |
| 36 | Balance pre-check (BUY: quote_qty + fee_buffer <= free_usdt) passes. | |
| 37 | request_weight_tokens(account_id, api_key, weight) returns True. | |
| 38 | adapter.paper_mode False when inspecting in place_market_buy. | |
| 39 | self.keys present and has api_key, api_secret (no None). | |
| 40 | place_order(keys, payload) invoked (add log to confirm). | |
| 41 | _signed_request_impl builds params with timestamp and recvWindow. | |
| 42 | HTTP POST to correct base URL (api.binance.com for mainnet). | |
| 43 | Response status 200 and body code 0. | |
| 44 | Response contains orderId and status FILLED (or NEW/PARTIALLY_FILLED). | |
| 45 | update_intent_filled(db, intent_id, res.get("orderId")) called. | |
| 46 | Ledger.record_trade(...) called and did not raise. | |
| 47 | save_state(db, bot_id, account_id, state) called after apply_fill_to_state. | |
| 48 | append_event ORDER_FILLED with correct meta. | |
| 49 | DB file path same for Web and Worker (e.g. sqlite:///./dca.db). | |
| 50 | No exception in finally block that could prevent commit (e.g. release_symbol_lock). | |

---

## APPENDIX M – EXECUTION FLOW DIAGRAM (TEXT)

```
[User] --> POST /api/bots-engine/{id}/start
    --> bots_start (bots_engine.py)
    --> bot.status = running, db.commit()
    --> _insert_engine_command(START)
    --> return 200 { command_id, bot_status: "running" }

[Worker] --> fetch_pending_commands()
    --> mark_command_processing(cmd_id)
    --> process_command(cmd)
        --> assert_bot_belongs_to_account
        --> START --> start_bot(bot_id) [legacy] OR v5_scheduler.register_bot(bot_id)
    --> mark_command_done(DONE)

[Legacy] start_bot --> _bot_loop(bot_id) as asyncio task
[V5]     register_bot --> scheduler run_loop --> run_one_bot_tick(bot_id, tick_id)

_bot_loop / run_one_bot_tick:
    --> load_state, load config
    --> get_account_keys(account_id) --> keys
    --> paper_mode = test_user && !keys
    --> adapter = BinanceAdapter(account_id, keys, paper_mode)
    --> [TRDCA] _build_trdca_snapshot, trdca_strategy_tick --> decision ACTIONS
    --> [DCA]   strategy.tick(state, cfg, price, ...) --> actions, next_wake
    --> if not actions: save_state, sleep, continue
    --> try_acquire_symbol_lock OR symbol_lock_with_heartbeat
    --> lease_still_valid? else LOCK_LEASE_EXPIRED, skip
    --> run_actions(bot_id, account_id, actions, state, cfg, adapter, db)
    --> save_state, release_symbol_lock

run_actions (execution.py):
    --> check_kill_switch
    --> acquire_bot_lock(bot_id)
    --> for each action type=="place":
        --> idempotency key, check_idempotency --> skip if hit
        --> intent_id = build_intent_id(...), client_order_id = build_client_order_id(...)
        --> upsert_intent(...) --> if status FILLED skip
        --> get_order_by_client_order_id (reconcile) --> if FILLED apply_fill_to_state, save, continue
        --> guard_min_notional --> skip if fail
        --> [initial_allocation] balance check required vs available --> skip if insufficient
        --> [BUY] virtual budget check, Binance free USDT check
        --> update_intent_submitting(intent_id)
        --> adapter.place_market_buy(symbol, quote_qty, client_order_id)
              OR adapter.place_market_sell(symbol, qty, client_order_id)
        --> [success] update_intent_filled, apply_fill_to_state, cycle_ledger_add_fill,
              Ledger.record_trade, save_state, append_event ORDER_FILLED
        --> [exception] update_intent_unknown or append_event, state last_error_code, continue
    --> release lock (via context manager or finally)

BinanceAdapter.place_market_buy:
    --> if paper_mode: return _simulate_fill(...)
    --> get_symbol_filters, min_notional check
    --> payload = { symbol, side, type, quoteOrderQty, newClientOrderId }
    --> return await place_order(self.keys, payload)

binance_spot.place_order:
    --> if not is_worker_role(): raise AppError(403)
    --> return await _signed_request(client, "POST", "/api/v3/order", keys, payload)

_signed_request_impl:
    --> params = payload + timestamp (Binance server time) + recvWindow=60000
    --> query_for_sign = sorted(params), signature = HMAC-SHA256(secret, query)
    --> POST body = query + "&signature=" + signature
    --> httpx.post(url, headers=X-MBX-APIKEY, content=body)
    --> if 200 and data.code != 0: raise HTTPStatusError
    --> return data
```

---

## APPENDIX N – FULL RUN_ACTIONS SKIP BRANCHES (REFERENCE)

Order is NOT sent when any of the following is true (execution.py logic):

1. check_kill_switch() raises.
2. action.get("type") != "place".
3. reason == "initial_allocation" and state.get("initial_allocation_done") and _sync_initial_done_from_db confirms.
4. check_idempotency(bot_id, key) returns True.
5. reason == "initial_allocation" and _sync_initial_done_from_db sets initial_allocation_done and we continue.
6. intent_row from upsert_intent has status == "FILLED" (and repair path does not apply).
7. get_order_by_client_order_id returns existing order with status FILLED (we apply fill and continue without sending).
8. get_order_by_client_order_id returns existing order with status NEW or PARTIALLY_FILLED (we continue without sending).
9. guard_min_notional(notional, min_notional) returns False.
10. initial_allocation: quote_qty required (with fee buffer) > available quote_free.
11. BUY and not skip_virtual_check: check_virtual_budget returns not ok.
12. BUY and not adapter.paper_mode: quote_qty + fee_buffer > free_usdt from get_account_balances.
13. SELL and not adapter.paper_mode: qty > free_base * (1 - buffer).
14. request_weight_tokens returns False (WEIGHT_DENIED).
15. asyncio.wait_for(adapter.place_market_*, 3.0) raises TimeoutError.
16. adapter.place_market_buy/sell raises (e.g. Binance 400/401, network error).

When 16 happens: exception caught, update_intent_unknown or not, append_event SKIP_REASON ORDER_FAILED, state["last_error_code"] = "ORDER_FAILED", continue to next action.

---

## APPENDIX O – PYTHON ASSERTION SCRIPT (LIVE EXECUTION)

Save as scripts/assert_live_execution.py. Run with DATABASE_ROLE=worker and PYTHONPATH=project_root.

```python
"""
Assert that live execution path is reachable and worker role is set.
Does NOT place a real order unless ASSERT_PLACE_ORDER=1 and account_id/bot_id set.
"""
import asyncio
import os
import sys

def main():
    os.environ.setdefault("DATABASE_ROLE", "web")
    from app.core.config import get_config, is_worker_role
    from app.db.session import SessionLocal
    from app.db.models import Bot
    from app.services.binance_assets import get_account_keys
    from app.services.test_account import is_test_account

    db = SessionLocal()
    cfg = get_config()
    role = cfg.get("database_role")
    worker_ok = is_worker_role()

    print("DATABASE_ROLE", repr(role))
    print("is_worker_role", worker_ok)
    if not worker_ok:
        print("FAIL: Worker role required for order placement. Set DATABASE_ROLE=worker.")
        sys.exit(1)

    # Optional: load a running bot and check adapter would be live
    bot_id = int(os.environ.get("ASSERT_BOT_ID", "0"))
    account_id = int(os.environ.get("ASSERT_ACCOUNT_ID", "0"))
    if bot_id and account_id:
        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if bot:
            print("bot_id", bot_id, "status", bot.status, "mode", getattr(bot, "mode", None))
            keys = asyncio.get_event_loop().run_until_complete(get_account_keys(account_id, db))
            test_acc = is_test_account(account_id, db)
            paper = test_acc and not keys
            print("account_id", account_id, "has_keys", keys is not None, "is_test_account", test_acc, "would_paper_mode", paper)
            if keys and not paper:
                print("OK: Bot would use live adapter (paper_mode=False).")
            else:
                print("WARN: Bot would use paper or no keys.")
    db.close()
    print("Assertions done.")

if __name__ == "__main__":
    main()
```

---

## APPENDIX P – PROMETHEUS-STYLE METRICS (FULL LIST)

Suggested counters/histograms for production. Names and labels only; implementation in app/observability or similar.

- bot_engine_commands_total{status} – count of commands by status (PENDING, DONE, ERROR).
- bot_engine_order_attempts_total{bot_id, side, outcome} – outcome = success | skip_idempotent | skip_min_notional | skip_balance | timeout | rejected.
- bot_engine_order_latency_seconds{bot_id, side} – histogram of time from run_actions start to place_order return.
- binance_request_total{path, method, status} – status = ok | error_4xx | error_5xx | timeout.
- binance_request_latency_seconds{path} – histogram.
- binance_weight_used_total{api_key} – counter (sliding 60s in memory).
- bot_tick_total{bot_id} – counter of ticks run.
- bot_tick_duration_seconds{bot_id} – histogram.
- order_intents_total{status} – count of intents by status (PERSISTED, SUBMITTING, FILLED, etc.).
- symbol_lock_acquire_total{outcome} – outcome = acquired | busy | expired.

---

## APPENDIX Q – RECONCILE FLOW (WHEN ORDER SENT BUT STATUS UNKNOWN)

If intent is SUBMITTING or UNKNOWN (e.g. after timeout):

1. Reconciler runs every 45s (worker: _reconciler_background_task).
2. get_non_final_intents_for_account(account_id) or query order_intents WHERE status NOT IN (FILLED, CANCELED, REJECTED, FINAL).
3. For each intent: get_order_by_client_order_id(symbol, client_order_id). If order found: update intent status, binance_order_id, filled_qty, avg_price, final_ts. If FILLED on exchange: apply_fill_to_state and save_state (repair path in execution.py when intent_row.status == FILLED and initial_allocation_done repair).
4. So: even if response was lost, next reconcile can fix state. Detection: order_intents with status UNKNOWN and last_submit_ts older than 60s should eventually be reconciled or marked REJECTED.

---

## APPENDIX R – MINIMAL INVASIVE PATCH CODE (COPY-PASTE)

**Not:** Aşağıdaki EXEC_ORDER_ATTEMPT ve BOT_MODE_CHECK artık kodda uygulanmıştır (execution.py, orchestrator.py, bot_run.py, binance_spot.py). Ek patch gerekmez; sadece referans için bırakılmıştır.

Add to app/botengine/execution.py just before the line `res = await asyncio.wait_for(adapter.place_market_buy(...)`:

```python
logger.info(
    "EXEC_ORDER_ATTEMPT bot_id=%s account_id=%s symbol=%s side=%s quote_qty=%s qty=%s client_order_id=%s paper_mode=%s intent_id=%s",
    bot_id, account_id, symbol, side, quote_qty, qty, client_order_id, adapter.paper_mode, intent_id,
)
```

Add to app/botengine/execution.py immediately after the block that sets `res = await asyncio.wait_for(...)` (success path, before update_intent_filled):

```python
logger.info(
    "EXEC_ORDER_SUCCESS bot_id=%s client_order_id=%s binance_order_id=%s executedQty=%s",
    bot_id, client_order_id, res.get("orderId"), res.get("executedQty"),
)
```

Add to app/services/binance_spot.py at the start of place_order (after the is_worker_role check):

```python
logger.info(
    "BINANCE_PLACE_ORDER symbol=%s side=%s type=%s worker_role=True",
    payload.get("symbol"), payload.get("side"), payload.get("type"),
)
```

These three patches give a clear log line when an order is attempted, when it succeeds, and when Binance REST is actually invoked. If EXEC_ORDER_ATTEMPT appears but BINANCE_PLACE_ORDER does not, the failure is between adapter.place_market_* and place_order (e.g. adapter.paper_mode True). If BINANCE_PLACE_ORDER appears but EXEC_ORDER_SUCCESS does not, the failure is Binance rejection or timeout.

---

## APPENDIX S – QUICK DIAGNOSIS MATRIX

Given symptom "Bot RUNNING, no orders on Binance", follow this matrix. Each row: if condition is true, check the next column; if false, skip to next row.

| Condition | Check | If true → next step | If false → |
|-----------|--------|----------------------|------------|
| Worker process running? | pgrep -f worker_main; .run/worker.pid | Check DATABASE_ROLE | Start worker |
| DATABASE_ROLE=worker? | Script in 2.5 / Appendix O | Check command status | Set env and restart worker |
| START command DONE? | SELECT status FROM bot_engine_commands WHERE bot_id=? ORDER BY id DESC LIMIT 1 | Check bot loop running | Wait or re-send start |
| Bot loop / v5 tick running for this bot? | Logs: BOT_LOOP_START bot_id= or run_one_bot_tick; engine.metrics.json active_bots | Check strategy output | ensure_running_bots or v5 register_bot |
| Strategy returns actions? | Logs: BOT_ACTION type=place | Check run_actions called | Price stale or strategy no trigger |
| run_actions called? | Log: run_actions start bot_id= | Check EXEC_ORDER_ATTEMPT (with patch) | Lock or no actions |
| EXEC_ORDER_ATTEMPT in log? | Add patch Appendix R | Check paper_mode in same log line | run_actions skip (idempotency, balance, etc.) |
| paper_mode=False in log? | Same line | Check BINANCE_PLACE_ORDER (with patch) | Fix test account / keys so paper_mode False |
| BINANCE_PLACE_ORDER in log? | Add patch Appendix R | Check EXEC_ORDER_SUCCESS or Binance error log | place_order not reached (e.g. 403) |
| EXEC_ORDER_SUCCESS or Binance 200? | Log or response | Check order_intents/trades/state | Binance rejected (code in log) |
| order_intents FILLED and trades row? | SQL Appendix C | Check UI/state refresh | Persist bug (D1/D2) |

---

## APPENDIX T – FUNCTION CALL CHAIN (ORDER SUBMIT)

Callee ← Caller (order of invocation for one place action):

1. place_order(keys, payload) ← BinanceAdapter.place_market_buy (or place_market_sell)
2. _signed_request(client, "POST", "/api/v3/order", keys, payload) ← place_order
3. _signed_request_impl(...) ← _signed_request
4. _get_binance_timestamp(client, testnet) ← _signed_request_impl
5. httpx.AsyncClient().post(url, headers=..., content=final_query) ← _signed_request_impl

BinanceAdapter.place_market_buy ← run_actions (execution.py) inside async with acquire_bot_lock(bot_id), for action in actions, after upsert_intent, guard_min_notional, balance checks, update_intent_submitting.

run_actions ← _bot_loop (orchestrator.py) or run_one_bot_tick (bot_run.py) inside symbol_lock_with_heartbeat or after try_acquire_symbol_lock and lease_still_valid.

_bot_loop ← start_bot(bot_id) which creates asyncio.create_task(_bot_loop(bot_id)).
run_one_bot_tick ← BotScheduler.run_loop which schedules next_run_at and calls _run_cb(bot_id, tick_id).

start_bot ← process_command(cmd, db, v5_scheduler=None) when command=="START".
process_command ← worker_loop which fetches pending commands and calls process_command for each.

---

## APPENDIX U – SPEC REFERENCES (TRADE_TRAILING_MASTER_SPEC)

The following spec sections are authoritative for execution behavior. Any code deviation should be fixed to match spec.

- **Who can trade:** Worker process only. Web/API cannot place orders. Manager does not execute. (Spec: Who Can Trade Money.)
- **Intent pipeline:** Never submit without persisted intent. Same intent_id => same client_order_id. Reconcile before new actions after timeout/crash. (Spec: 1C BOT ENGINE V5 — INTENT PIPELINE.)
- **Lock lifecycle:** DEFAULT_LEASE_TTL_SEC=10, heartbeat 3s. lease_still_valid must be checked before submit. (Spec: 1F LOCK LIFECYCLE.)
- **Weight governor:** request_weight_tokens before signed call; deny if over limit. SAFE MODE when weight/limit >= 0.85. (Spec: 1G WEIGHT GOVERNOR.)
- **Error taxonomy:** timeout => reconcile_only (no blind resubmit). rate_limited => backoff. (Spec: 1H ERROR TAXONOMY.)
- **DataHub only for price:** No per-symbol Binance REST for trading price; adapter.get_price from DataHub. (Spec: S4.)

When debugging "no orders", verify each of the above is enforced in the code paths used by the running bot.

---

## APPENDIX V – ENV VAR VALIDATION SCRIPT (BASH)

```bash
#!/bin/bash
# Save as scripts/validate_live_env.sh. Run from project root.
echo "DATABASE_ROLE=${DATABASE_ROLE:-<unset>}"
echo "BOT_ENGINE_V5_SCHEDULER=${BOT_ENGINE_V5_SCHEDULER:-<unset>}"
echo "BOT_ENGINE_KILL_SWITCH=${BOT_ENGINE_KILL_SWITCH:-<unset>}"
python3 -c "
import os
os.environ.setdefault('DATABASE_ROLE', '')
from app.core.config import get_config, is_worker_role
c = get_config()
print('config.database_role:', repr(c.get('database_role')))
print('is_worker_role:', is_worker_role())
"
echo "Worker PID file: $(cat .run/worker.pid 2>/dev/null || echo 'missing')"
echo "Engine metrics: $(cat .run/engine.metrics.json 2>/dev/null | head -5 || echo 'missing')"
```

---

## APPENDIX W – DOCUMENT REVISION LOG

| Version | Date | Change |
|---------|------|--------|
| 1 | 2026-02-13 | Initial forensic analysis. Sections 1–13 + Appendices A–V. Target: no real orders on Binance despite bot RUNNING. |

This document is for system debugging and engine reconstruction only. Update TRADE_TRAILING_MASTER_SPEC.md for any lasting architectural or constant changes.

**Key files to inspect when orders do not execute:** app/botengine/execution.py (run_actions), app/botengine/adapters/binance_adapter.py (place_market_buy/sell, paper_mode), app/services/binance_spot.py (place_order, is_worker_role), app/botengine/worker_main.py (process_command, DATABASE_ROLE), app/core/config.py (is_worker_role). Use the checklist in Section 13 and Appendices S and R to isolate the failing layer.

**Summary of root cause buckets:** (1) Worker not running or not worker role → commands not processed or place_order 403. (2) Bot not ticking → command not processed or v5 bot not registered. (3) Strategy no actions → price stale or trigger not met. (4) run_actions skips → idempotency, min_notional, balance, weight, lock. (5) paper_mode True → _simulate_fill only, no REST. (6) Binance rejects → -1021, -2015, -2010, etc. (7) Persist failure → intent FILLED but state/trades not updated.

**Recommended first steps:** (a) Add the three log patches from Appendix R and reproduce. (b) Run checklist Section 13 items 1–10. (c) If all pass, run items 11–20 and inspect logs for EXEC_ORDER_ATTEMPT, BINANCE_PLACE_ORDER, EXEC_ORDER_SUCCESS. (d) Run SQL from Appendix C for the bot_id (commands, intents, trades, state). (e) Use Appendix S quick diagnosis matrix to narrow the failing layer.

**Trace identifiers:** For a single user start action, trace via: request_id (API response) → bot_engine_commands.request_id → (worker) WORKER_COMMAND_EXECUTED request_id not logged but command_id same → BOT_LOOP_START or run_one_bot_tick (bot_id) → run_actions start bot_id → EXEC_ORDER_ATTEMPT client_order_id → BINANCE_PLACE_ORDER → EXEC_ORDER_SUCCESS order_id. Correlate by bot_id and time window when request_id is not propagated.

**Document total:** Sections 1–13 plus Appendices A–W. All grep commands, SQL, logging patches, and checklists are production-ready for the TraderTrailing codebase as of the document date.

**Output file:** docs/LIVE_TRADING_EXECUTION_FORENSIC_ANALYSIS_v1.md. Keep this file under version control and update when execution path or spec changes. See TRADE_TRAILING_MASTER_SPEC.md for authoritative system limits and constants.

---

*End of document. Version 1. For system debugging and engine reconstruction only. Minimum 1500+ lines satisfied.*

