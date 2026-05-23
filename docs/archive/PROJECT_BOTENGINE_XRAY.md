# PROJECT BOTENGINE XRAY (LLM Reference)

**Purpose:** Single technical reference for the bot engine, strategy, state, market data, API, UI, security, and observability. No secrets. Repo paths and line refs are authoritative.

**Doc güncelleme:** Her işlemden (bot/UI/API değişikliği) sonra bu dosya en güncel hâline getirilir.  
**Son güncelleme:** 2026-02-02 — UI: Bot create modal iki wizard (DCA / Rebalancing), Rebalancing parametre ekranı, pair strip görünürlük. Rebalancing: coin alanlarında yazarken USDT bazlı arama dropdown + satır bazlı detaylı önizleme (fiyat, 24s %, 24s yüksek/düşük). Binance: signed timestamp + recvWindow; deposit hisrec endTime cap.

---

# 1) EXEC SUMMARY (LLM ODAKLI)

## Projenin amacı
DCA + iki yönlü grid + trailing stratejili, Binance Spot’a bağlı bir bot engine: hesap bazlı bot oluşturma, başlatma/durdurma, per-bot asyncio döngüsü, fiyat → strateji → emir → fill → state/virtual wallet güncellemesi. Cycle PnL fee-aware ve cycle-ledger ile izole; profit-exit breakeven + min_net_profit ile kilitli. UI: dashboard, bot detay, performans grafiği, events/trades API ile beslenir.

## Bot engine high-level flow
1. **Start:** `POST /api/bots-engine/{id}/start` → orchestrator `start_bot` → DB status=running → `_bot_loop(bot_id)` asyncio task.
2. **Loop:** Her iterasyonda DB session aç, state yükle, Binance keys al, fiyat al (data_hub → price_hub fallback → Binance public), virtual wallet ensure, `tick_dca_grid_trailing(state, config, price, base_balance, quote_balance)` → actions.
3. **Execution:** `run_actions` → idempotency/min_notional/virtual_budget guard → symbol lock acquire → adapter place_market_buy/sell → fill parse → `apply_fill_to_state`, cycle_ledger fill (cycle-scoped reasons), virtual_wallet update, Ledger.record_trade, fill snapshot (free_quote/locked_quote), CYCLE_END ise cycle_pnls + cycle_reset_after_fill.
4. **State:** Her tick sonunda `save_state`; `sync_virtual_wallet_from_state` ile virtual_wallet = state base/quote.
5. **Stop:** `_stop_requested.add(bot_id)`, task.cancel(), DB status=stopped.

## En kritik 10 dosya
| Path | Rol |
|------|-----|
| `app/botengine/orchestrator.py` | Per-bot loop, start/stop, ensure_running_bots, delete_bot_fully |
| `app/botengine/execution.py` | run_actions: guard, place order, apply_fill_to_state, cycle_ledger, CYCLE_END, fill snapshot |
| `app/botengine/strategies/dca_grid_trailing.py` | tick_dca_grid_trailing, initial_alloc/grid/reentry/profit_exit, apply_fill_to_state, cycle_reset_after_fill |
| `app/botengine/state_store.py` | load_state, save_state, append_event, list_events |
| `app/botengine/cycle_ledger.py` | Cycle-only PnL: build_cycle_ledger_empty, cycle_ledger_add_fill, breakeven/trigger_price (fee-aware) |
| `app/botengine/virtual_wallet.py` | get_virtual_wallet, update_virtual_after_fill, check_virtual_budget, sync_virtual_wallet_from_state |
| `app/botengine/adapters/binance_adapter.py` | BinanceAdapter: get_account_balances, get_price (data_hub→price_hub→public), place_market_buy/sell |
| `app/api/bots_engine.py` | Bot CRUD, start/stop, detail, events, trades, performance, perf-chart-state |
| `app/services/data_hub.py` | DataHub: prices cache, get_price(symbol), REST/WS refresh; engine fiyat kaynağı |
| `app/db/schema_guard.py` | bot_engine_state, bot_engine_events, symbol_locks, bot_virtual_wallet, trades columns |

## En kritik 10 risk (P0/P1)
1. **P0:** Cycle PnL scope karışması (legacy modda initial_alloc cost cycle’a sızabilir) → pnl_mode=cycle_only_fee_aware_v1 kullan.
2. **P0:** Profit-exit fee-aware değilse break-even altı satış → negatif cycle PnL; pnl_mode=cycle_only_fee_aware_v1 ile trigger_price kullanılıyor.
3. **P0:** quote_qty_capped drift (virtual vs real free_quote) → fill snapshot + available_quote_buffer_pct ile azaltıldı.
4. **P1:** Market data iki kaynak: data_hub (engine) ve UI ayrı klines/fiyat çekebilir → tek doğruluk data_hub + price_hub; UI API üzerinden almalı.
5. **P1:** Stop’ta open order iptal yok → crash’te reconcile yok; dokümanda NOT FOUND.
6. **P1:** Idempotency TTL 5s (initial_alloc 2s); aynı action_key ile 5s içinde tekrar gelirse skip.
7. **P1:** Symbol lock lease 60s; sadece (account_id, symbol) başına tek bot emir atar.
8. **P1:** State save non-transactional (state_json tek blob); crash between save_state ve sync_virtual_wallet → drift.
9. **P2:** price_hub TTL 5s; data_hub PRICE_TTL 120s; stale fiyat PRICE_STALE_OR_MISSING event.
10. **P2:** Fee BNB ise USDT’ye çevriliyor (price_hub); çevrilemezse fee=0 (execution.py ~386–399).

---

# 2) REPO HARİTASI (DCATREE+)

## 2.1 File Tree (önemli klasörler)
```
app/
  api/           # FastAPI routes: bots_engine, auth, admin, routes, spot_routes, data_hub_routes, finance, pricing_routes
  botengine/     # Engine core: orchestrator, execution, state_store, risk, locks, virtual_wallet, cycle_ledger
  botengine/strategies/  # dca_grid_trailing (tick_dca_grid_trailing, apply_fill_to_state, cycle_reset_after_fill)
  botengine/adapters/   # binance_adapter (BinanceAdapter)
  bot/            # Legacy bot: ledger (Trade record), engine_v2, trailing_engine
  db/             # models, session, schema_guard (bot_engine_state, bot_engine_events, symbol_locks, bot_virtual_wallet)
  services/       # data_hub, price_hub, binance_spot, binance_client, pnl_service, encryption
ui/
  assets/         # dashboard.js, perf_chart_tv.js, core/apiClient.js
  bot.html        # Bot detay sayfası, performans grafiği, events, trades
```

## 2.2 Hot Paths

### Emir akışı (order create → fill → state update)
- **Chain:** `_bot_loop` (orchestrator.py ~97) → `tick_dca_grid_trailing` (dca_grid_trailing.py ~49) → `run_actions` (execution.py ~128) → `adapter.place_market_buy`/`place_market_sell` (binance_adapter.py) → parse fill → `apply_fill_to_state` (dca_grid_trailing.py ~423) → `cycle_ledger_add_fill` (cycle_ledger.py, reason in CYCLE_FILL_REASONS) → `Ledger.record_trade` (app/bot/ledger.py) → `update_virtual_after_fill` (virtual_wallet.py) → `_write_fill_snapshot_to_state` (execution.py) → CYCLE_END ise cycle_pnls append + `cycle_reset_after_fill` → `save_state` (orchestrator tick sonu) → `sync_virtual_wallet_from_state`.
- **Veri:** actions: `{ type: "place", side, symbol, quantity|quote_qty, client_order_id, reason, grid_index? }`. Fill: `executedQty`, `cummulativeQuoteQty`, fills[].commission, commissionAsset → fee USDT’ye çevrilir (execution.py ~380–399). state: base_balance, quote_balance, realized_pnl_usdt_cycle, fees_paid_usdt_cycle, cycle_ledger_current, cycle_pnls.
- **Concurrency:** Per-bot asyncio lock (`acquire_bot_lock`); symbol lock DB (try_acquire_symbol_lock) aynı (account_id, symbol) için tek bot.

### Market data akışı (source → normalize → cache → consumer)
- **Source:** Binance REST (data_hub refresh, binance_spot _sync_public_get), WS (data_hub WS). Engine fiyat: BinanceAdapter.get_price: data_hub.get_price(symbol) → price_hub.get_price(symbol) → binance_spot _sync_public_get("/api/v3/ticker/price") (binance_adapter.py ~79–102).
- **Normalize:** symbol upper; data_hub prices: symbol → {price, change24h, volume24h, ts}. price_hub: symbol → {price, updated_at}; TTL 5s.
- **Cache:** data_hub.prices (PRICE_TTL 120s); price_hub._cache (TTL 5s). data_hub REST loop ~1.5s; WS varsa REST 10s.
- **Consumer:** orchestrator _bot_loop → get_price(symbol) (adapter); UI klines ayrı: `/api/spot/klines` (bot.html, dashboard.js) → Binance/backend.

### UI → API → engine çağrı yolu
- **UI:** bot.html, dashboard.js; `window.apiClient.get/post` (ui/assets/core/apiClient.js). Token: sessionStorage; BroadcastChannel logout.
- **API:** FastAPI; `require_auth` + `get_account_or_403(bot.account_id)` bot route’larında. Bot list: GET /api/bots-engine?account_id=; detail: GET /api/bots-engine/{id}; start: POST /api/bots-engine/{id}/start; stop: POST /api/bots-engine/{id}/stop; events: GET .../events; trades: GET .../trades; performance: GET .../performance.
- **Engine:** start_bot → _bot_loop task; stop_bot → _stop_requested + task.cancel. Engine kendi döngüsünde DB’den state/keys okuyor; API sadece start/stop/read.

### Binance / Finance (imza + deposit)
- **Imzalı istek:** app/services/binance_spot.py — timestamp Binance server time (GET /api/v3/time, 30s cache); recvWindow=60000. _get_binance_timestamp (async), _get_binance_timestamp_sync; -1021 (timestamp outside recvWindow) önlenir.
- **Deposit/withdraw hisrec:** app/api/finance_reports.py — endTime gelecekte olamaz; end_ms > now_ms ise end_ms = now_ms; start_ms >= end_ms ise start_ms = max(0, end_ms - 90 gün). Binance 400 önlenir.

---

# 3) BOT LIFECYCLE

## 3.1 Bot create
- **Endpoint:** POST /api/bots-engine (body: account_id, config_json). File: app/api/bots_engine.py ~111–123.
- **Core:** create_bot_engine_core(account_id, config_dict, db) ~74–108: config_from_ui_payload → DcaGridTrailingConfig.to_dict → config_json; bot_code random 6-digit; Bot(account_id, symbol, mode, config_json, status="stopped", bot_code); ensure_state_row.
- **Validation:** get_account_or_403(current, body.account_id, db). Config validation: DcaGridTrailingConfig(raw) içinde; eksik alanlar default (symbol BTCUSDT, initial_capital_usdt 1000, fee_rate 0.001, vb.).
- **Persist:** bots tablosu (id, account_id, symbol, mode, config_json, status, bot_code, started_at); bot_engine_state satırı ensure_state_row ile (build_state_skeleton).
- **Defaults:** models.py build_state_skeleton: cycle_id 1, base_balance 0, quote_balance 0, initial_allocation_done False, pnl_mode legacy, tick_interval_ms 2000, min_notional_guard 5, initial_fee_buffer_pct 0.002, available_quote_buffer_pct 0.005.

## 3.2 Bot start/stop
- **Start:** start_bot(bot_id, db) (orchestrator.py ~294): Bot status=running, started_at=now; _stop_requested.discard(bot_id); async with _task_create_lock: if bot_id in _tasks → log ALREADY_RUNNING return True; else asyncio.create_task(_bot_loop(bot_id)), _tasks[bot_id]=task. Idempotency: Zaten çalışıyorsa skip, True döner.
- **Stop:** stop_bot(bot_id, db) (~318): _stop_requested.add(bot_id); Bot status=stopped; task.cancel(); asyncio.wait_for(shield(task), 5s); _tasks.pop; _config_cache.pop. Graceful: Sadece task iptal; open order iptal YOK. State flush: Son tick’te save_state zaten yapılmış; stop anında ek flush yok.
- **Idempotency:** Start tekrar → "BOT_START_SKIPPED_ALREADY_RUNNING". Stop tekrar → _stop_requested zaten set, task yoksa sadece DB güncellenir.

## 3.3 Bot runtime loop
- **Tick:** _bot_loop (orchestrator.py ~72): while bot_id not in _stop_requested; DB’den Bot row, status running/paused_error değilse break; load_state; get_account_keys; BinanceAdapter(account_id, keys); data_hub.get_price(symbol) veya adapter.get_price; ensure_virtual_wallet; state["base_balance"]/quote_balance = get_virtual_wallet; tick_dca_grid_trailing(state, cfg, price, base_balance, quote_balance) → (actions, next_wake); actions varsa try_acquire_symbol_lock → run_actions → append_event ORDER_FILLED → release_symbol_lock; save_state; sync_virtual_wallet_from_state; daily_ref_date güncellemesi; await asyncio.sleep(max(0.5, next_wake)).
- **Zamanlama:** next_wake = config.tick_interval_ms/1000 (default 2s). Cron yok; sadece sleep.
- **Backpressure:** max_orders_per_minute config var; execution’da doğrudan rate limit uygulanmıyor (risk.py guard_max_orders_per_minute var, çağrı yeri NOT FOUND).
- **Error handling:** Exception → BOT_LOOP_TOPLEVEL_EXCEPTION, error_id uuid, append_event ERROR, state last_error_code, Bot status paused_error; loop devam eder. error_code/error_id/request_id: execution’da SKIP_REASON/ERROR meta’da; API _request_id(request), _detail_err(code, message, rid).

---

# 4) STRATEJİ MOTORU (Strategy Core)

## 4.1 Strateji türleri
- **Grid (sell/buy):** trail_sell_grid, trail_buy_grid. Dosya: dca_grid_trailing.py. Sell: trail_anchor_price * (1 - sell_trigger_trailing_pct/100) ≥ price → SELL qty = _sell_qty_for_grid(state, config, idx, base_balance). Buy: trail_anchor_price * (1 + buy_trigger_trailing_pct/100) ≤ price → BUY qty = _buy_qty_for_grid(state, config, idx, quote_balance). Parametreler: sell_grids[].trigger_pct, qty_pct; buy_grids[].trigger_pct, qty_pct; sell_trigger_trailing_pct, buy_trigger_trailing_pct.
- **DCA:** Initial allocation tek seferlik BUY: base_pct/quote_pct ile bütçe bölünür, quote_qty = c_base (base tarafı USDT cinsinden alım). initial_allocation_done False iken her tick’te bir place action (reason=initial_allocation).
- **Rebalancing:** Yok (NOT FOUND).
- **Trailing buy/sell:** Grid’ler trailing: anchor = max(anchor, price); tetik = anchor * (1 ± trail_pct).
- **Profit-exit:** TRAIL_PROFIT_SELL: avg_buy * (1 + profit_exit_rise_pct/100) ≤ price → SELL (legacy). pnl_mode=cycle_only_fee_aware_v1 ise trigger_price = cycle_ledger_trigger_price(breakeven * (1+min_net_profit_rate)); SELL sadece price >= trigger_price (dca_grid_trailing.py ~296–331). Re-entry: TRAIL_REENTRY_BUY: avg_sell * (1 - profit_reentry_drop_pct/100) ≥ price → BUY.

Decision trace örnek: ia_done=False → initial_allocation action. ia_done=True, mode=IDLE, price ≥ ref*(1+profit_exit_rise_pct) → mode=TRAIL_PROFIT_SELL, action profit_exit SELL. Fill sonrası _cycle_complete veya reason trail_reentry_buy/trail_profit_sell → cycle_pnls append, cycle_reset_after_fill.

## 4.2 Anchor price
- **Başlangıç fiyatı:** reference_price (initial_alloc sonrası fill_price). state["reference_price"].
- **Avg cost:** _avg_buy_price_total (initial + buy_history) veya _avg_buy_price_for_trigger (grid-only, execution_price varsa o). basis_mode=total ise total; grid_only ise grid. Profit-exit tetikte kullanılıyor (legacy).
- **Local peak/trough:** trail_anchor_price, sell_grid_peak_price[], buy_grid_trough_price[] (grid tetik anındaki fiyat).
- **UI referans:** performance API’de reference_price, current_price; grid_view compute_grid_profit_view avg_buy/avg_sell. Engine referansı = state.reference_price; UI aynı state’ten okuyor (detail API).

## 4.3 Cycle tanımı
- **Cycle start:** initial_allocation fill sonrası cycle_id=1, cycle_start_equity set. Sonraki cycle: cycle_reset_after_fill içinde cycle_id++, sell_history/buy_history temizlenir, grid_fired sıfırlanır.
- **Cycle end:** trail_profit_sell veya trail_reentry_buy fill → _cycle_complete veya reason in (trail_reentry_buy, trail_profit_sell) → cycle_pnls.append({cycle_id, pnl_usdt, fees_usdt, matched_qty, pnl_mode}), cycle_reset_after_fill, append_event CYCLE_END.
- **Cycle PnL:** pnl_mode=cycle_only_fee_aware_v1 ise cycle_ledger_current.realized_pnl_quote (sell_quote - buy_quote - fees); legacy ise state.realized_pnl_usdt_cycle (apply_fill_to_state içinde cost = qty*avg_buy, realized += sell_quote - fee - cost). Global inventory karışması: legacy’de avg_buy total/grid_only basis_mode’a bağlı; cycle_ledger sadece trail_* fill’leri toplar, initial_allocation dahil değil.
- **Cycle ledger:** app/botengine/cycle_ledger.py. CYCLE_FILL_REASONS = trail_buy_grid, trail_sell_grid, trail_reentry_buy, trail_profit_sell. build_cycle_ledger_empty, cycle_ledger_add_fill, realized_pnl_quote = sell_quote - buy_quote - total_fees; matched_qty = min(buy_qty_total, sell_qty_total).

## 4.4 PnL & Fee Muhasebesi
- **Fee asset:** Execution’da fills[].commissionAsset; USDT değilse price_hub ile USDT’ye çevrilir (execution.py ~386–399); çevrilemezse fee=0. Ledger.record_trade fee_asset="USDT". Cycle ledger’da fee quote (USDT) kabul; değilse WARNING log.
- **Realized vs unrealized:** realized_pnl_usdt_cycle per cycle; cycle_pnls listesi geçmiş cycle karı. Unrealized: UI’da (equity - cost) hesaplanabilir; engine’de ayrı alan yok.
- **Rounding/stepSize/minNotional:** binance_adapter _fmt_qty (step_size), guard_min_notional(config.min_notional_guard) execution’da (execution.py ~143, 207).
- **Virtual vs real:** virtual_wallet (virtual_base, virtual_quote) DB’de; state base_balance/quote_balance her tick başında virtual’dan set edilir; fill sonrası sync_virtual_wallet_from_state(state). Fill snapshot: _write_fill_snapshot_to_state → free_quote, locked_quote exchange’den; state["free_quote"], state["locked_quote"]; available_quote_for_orders = free_quote * (1 - available_quote_buffer_pct).
- **quote_qty_capped:** execution.py ~268–282: BUY’da state.free_quote ?? virtual_quote, available_quote = free_quote * (1 - buffer_pct); quote_qty > available_quote ise quote_qty = round(available_quote, 2); append_event INFO "quote_qty_capped".

---

# 5) ORDER YÖNETİMİ (Exchange Integration)

## 5.1 Exchange client
- **Nerede:** BinanceAdapter (app/botengine/adapters/binance_adapter.py). get_account_balances → binance_spot.get_wallet(keys); place_market_buy/sell → binance_spot place_order. Keys: get_account_keys(account_id, db) (binance_assets).
- **Imzalı istek timestamp (-1021 önlemi):** binance_spot.py: signed isteklerde timestamp = Binance server time (GET /api/v3/time, 30s cache); recvWindow=60000. _get_binance_timestamp (async) ve _get_binance_timestamp_sync; _signed_request ve _sync_signed_request bu timestamp’i kullanır. Sunucu saati Binance ile uyumsuzsa -1021 alınmaz.
- **Retry/backoff:** binance_spot tarafında genel try/except var; engine’de order fail → SKIP_REASON ORDER_FAILED, state last_error_code; INSUFFICIENT_BALANCE ise paused_insufficient_balance + backoff_until 60s (execution.py ~302–314).
- **Rate limit:** data_hub rate_limit_backoff; BinanceAdapter’da özel rate limit yok.
- **Timeouts:** apiClient.js DEFAULT_TIMEOUT 20000; backend httpx timeout kodda belirtilmemiş (varsayılan).

## 5.2 Order model / idempotency
- **client_order_id:** _action_id(state, prefix, idx) → "be_{botId}_c{cycle}_{prefix}_{idx}" (dca_grid_trailing.py ~316). initial_allocation: key = f"initial_allocation_{bot_id}_{state_ver}_0".
- **order_id:** Binance response orderId; Ledger.record_trade(order_id=...) ile duplicate kontrol (bot_id, order_id) (app/bot/ledger.py ~35–41).
- **Duplicate fill:** record_trade idempotent; aynı order_id tekrar gelirse insert yok. Out-of-order: event’ler append-only; state tek snapshot, son yazan kazanır.

## 5.3 Open orders / cancel
- **Bot stop’ta:** Open order iptal YOK (NOT FOUND). stop_bot sadece task iptal + status=stopped.
- **Crash recovery:** ensure_running_bots DB’de status=running olanları tekrar _bot_loop ile başlatır; open order reconcile YOK.

---

# 6) MARKET DATA KATMANI (Tek Doğruluk Kaynağı)

## 6.1 Data sources
- **Binance REST:** data_hub refresh (prices), binance_spot _sync_public_get("/api/v3/ticker/price", "/api/v3/ticker/24hr"). Engine: adapter.get_price → data_hub.get_price → price_hub.get_price → _sync_public_get (binance_adapter.py ~79–102).
- **WS:** data_hub _mini_ws; ws_status, last_ws_update_ts; REST_PRICE_INTERVAL_WHEN_WS 10s.
- **Cache:** data_hub.prices (PRICE_TTL 120s); price_hub._cache (TTL 5s).
- **intervalRegistry:** UI tarafında (dashboard.js, bot.html): window.intervalRegistry.start/stop/stopByOwner; backend’de yok. Engine kendi asyncio sleep ile tick.
- **Tek kaynak:** Engine fiyatı data_hub → price_hub → public. UI klines ayrı: GET /api/spot/klines (Binance proxy veya backend). Fiyat için UI bazen ayrı endpoint kullanıyor; tam tek kaynak değil (UI chart/klines ayrı çekiyor).

## 6.2 Normalizasyon
- **Symbol:** (symbol or "").upper().strip() or "BTCUSDT" (config, adapter). ETHUSDT → base ETH, quote USDT; _symbol_to_base_quote (cycle_ledger, virtual_wallet) USDT/BUSD/FDUSD/USDC suffix.
- **Precision:** step_size, tick_size binance_adapter get_symbol_filters; _fmt_qty step_size’a yuvarlar.

## 6.3 Cache/TTL
- **Stale:** data_hub get_price age > PRICE_TTL (120s) → None. price_hub 5s. Engine’de price None/stale → PRICE_STALE_OR_MISSING event (orchestrator), append_event SKIP_REASON; next_wake 0.5s.
- **UI blink:** Dashboard summary interval ile poll; data gecikmesi olabilir.

---

# 7) STATE STORE / PERSISTENCE

- **Schema:** bot_engine_state (bot_id UNIQUE, account_id, state_json TEXT, cycle_id, mode, last_tick_at, last_error_code, retry_at, updated_at). bot_engine_events (bot_id, account_id, ts, event_type, message, meta_json). schema_guard.py ~309–356.
- **State şeması (state_json):** build_state_skeleton: bot_id, account_id, symbol, status, cycle_id, state_version, reference_price, initial_allocation_done, base_balance, quote_balance, sell_grid_fired, buy_grid_fired, mode, realized_pnl_usdt_cycle, fees_paid_usdt_cycle, cycle_pnls, cycle_ledger_current (cycle_only_fee_aware_v1), free_quote, locked_quote, last_fill_snapshot, vb. models.py ~164–193.
- **Transactional:** save_state tek INSERT/UPDATE; commit. Events append INSERT; commit. İki ayrı commit; atomic değil.
- **Crash recovery:** BOT_STATE_SAVING/SAVED log (state_store); verify row re-read. ensure_running_bots ile status=running botlar yeniden başlatılır.
- **Migration:** schema_guard ile eksik kolon/tablo eklenir; state_json şeması kodda; eski key’ler yoksa default.
- **Locking:** Per-bot asyncio Lock (risk.py). Symbol lock DB (locks.py) (account_id, symbol) lease 60s.

---

# 8) API KATMANI (FastAPI)

## 8.1 Endpoint listesi (bots-engine)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | /api/bots-engine | List bots (account_id query); require_auth, get_account_or_403 |
| POST | /api/bots-engine | Create bot (body: account_id, config_json) |
| GET | /api/bots-engine/{bot_id} | Detail (account_id optional); state, config, grid view |
| POST | /api/bots-engine/{bot_id}/start | start_bot |
| POST | /api/bots-engine/{bot_id}/stop | stop_bot |
| PUT | /api/bots-engine/{bot_id} | Update config |
| DELETE | /api/bots-engine/{bot_id} | delete_bot_fully |
| GET | /api/bots-engine/{bot_id}/events | list_events(limit, after_id) |
| GET | /api/bots-engine/{bot_id}/trades | Ledger.get_trades_dict; cycle_id optional |
| GET | /api/bots-engine/{bot_id}/cycles | Ledger.get_cycle_ids |
| GET | /api/bots-engine/{bot_id}/performance | PnL, chart_series, cycle_pnl_last, pnl_calculation_mode |
| GET/PUT | /api/bots-engine/{bot_id}/perf-chart-state | Grafik state (baseline, samples, range) |

Request/response: Tüm response’larda request_id. Error: _detail_err(error_code, message, request_id). Auth: require_auth Depends; get_account_or_403(current, account_id/bot.account_id, db).

## 8.2 Error taxonomy
- **error_code:** NOT_FOUND, INSUFFICIENT_QUOTE, VIRTUAL_BUDGET_INSUFFICIENT, BINANCE_FREE_QUOTE_INSUFFICIENT, MIN_NOTIONAL, ORDER_FAILED, BOT_LOOP_TOPLEVEL_EXCEPTION, RUN_ACTION_EXCEPTION, INSUFFICIENT_BALANCE, ENCRYPTION_NOT_CONFIGURED, BINANCE_AUTH, BINANCE_RATE_LIMIT, BINANCE_UPSTREAM_ERROR.
- **error_id:** Exception path’lerinde uuid.uuid4() (execution.py ~342).
- **request_id:** request.state.request_id veya uuid (bots_engine.py _request_id). Logging correlation: rid her response’ta; log’larda ayrı request_id alanı yok (middleware’de set edilebilir).

---

# 9) FRONTEND ENTEGRASYONU (UI)

- **Sayfalar:** dashboard.html (bot listesi, özet), bot.html (bot detay: state, performans grafiği, events, trades, cycles, start/stop, config). admin.html (hesap/bot yönetimi).
- **UI state:** dashboard.js State (accountId, bot list, vb.); sessionStorage token; BroadcastChannel logout. Bot detay sayfa yüklemede GET /api/bots-engine/{id}?account_id=.
- **API noktaları:** window.apiClient.get/post (apiClient.js); base URL window.location.origin; Authorization: Bearer token (sessionStorage); timeout 20s.
- **Modal/Chart/Reports:** perf_chart_tv.js (LightweightCharts, bucket snapshot, crosshair tooltip, mouseleave hide); PerfChartTV.init(botId, accountId); modal açılınca createModalChart. Events: GET .../events?limit=500. Trades: GET .../trades; cycles: GET .../cycles.
- **Bot Create modal (#dmModal):** Tek modal, iki wizard gövdesi: **dmWizardDca** (Trailing DCA) ve **dmWizardMulti** (Rebalancing). Akış: "Bot Oluştur" → openBotStructureModal() (yapı seçimi) → selectBotStructure(template) → currentSelectedTemplate = template; closeBotStructureModal(); fillModalWithTemplate(); openCreateBotModal(). openCreateBotModal içinde currentSelectedTemplate sıfırlanmaz (sadece !botId ise createModalEditMode sıfırlanır); setCreateBotModalWizard(currentSelectedTemplate?.id || "trailing_dca") ile hangi wizard gösterileceği belirlenir. Rebalancing seçilince sadece dmWizardMulti, DCA seçilince sadece dmWizardDca gösterilir; Trailing DCA parametre ekranına dokunulmaz.
- **Rebalancing parametre ekranı (dmWizardMulti):** Genel (ana para birimi USDT readonly, fMultiBudget — placeholder "Kullanılabilir: X USDT"); Coin sayısı ve dağılım (fMultiCoinCount 2–10, multiAssetRows — buildMultiAssetRows: her satır multi-asset-row, sembol + hedef % + multi-asset-preview). Coin alanında yazarken: dmMultiSymbolSearchDropdown (USDT çiftleri, fiyat + 24s %); seçince veya Enter/blur ile geçerli sembol → updateMultiAssetPreview(idx, symbol): Fiyat, 24s %, 24s yüksek, 24s düşük (marketStore.getMini + /api/spot/klines). Rebalance kuralları; Özet (multiConfirmTable). Tasarım DCA ile aynı. createBotErrorMulti. CSS: #dmWizardMulti .form-input, .multi-asset-preview, .dm-multi-confirm-table (dashboard.css).
- **Pair strip (dmSelectedPairStrip):** Parite girilip onaylanana kadar gizli. setCreateBotModalWizard("trailing_dca") ile strip gösterilmez (display: none); openCreateBotModal strip’i gizler. Görünür olması: fSymbol’de Enter (dropdown ilk sonuç veya yazılan sembol normalize) veya dropdown’dan tıklayınca updateCreateBotModalPairStrip(symbol) çağrılır; strip.style.display = 'flex'. dmTahminStrip aynı kural.
- **Performans darboğazları:** Çok sık poll (dashboard.summary 5s, wallet poll 2s); intervalRegistry ile stopByOwner ile temizleniyor. Grafik setData her 5s live update.
- **Duplication riski:** cycle_pnls state’te; performance API hem state.cycle_pnls hem CYCLE_END eventlerinden topluyor (state öncelikli). Trades Ledger’dan tek kaynak; duplicate yok.

---

# 10) GÜVENLİK KATMANI (NO SECRETS)

- **Auth/session:** auth.py: HTTPBearer optional; token sessionStorage; _sessions[token] = {user_id, account_id, is_admin, boot_id, device_id}; boot_id sunucu restart’ta değişir, eşleşmeyen 401. require_auth Depends; get_account_or_403(current, account_id, db) bot route’larında.
- **Admin/user:** is_admin session’da; admin route’ları ayrı. Hesap izolasyonu: get_account_or_403 ile kullanıcı sadece kendi account_id’sine erişir.
- **CSRF/CORS:** main.py CORSMiddleware; CORS ayarları var. CSRF token NOT FOUND.
- **Input validation:** Pydantic BotCreateBody; config DcaGridTrailingConfig(raw). Symbol/quantity sayısal kontrol execution’da.
- **Rate limit/abuse:** API genel rate limit NOT FOUND. Binance rate limit data_hub’da backoff.
- **Cihaz/IP onayı:** Dokümanda "cihaz ve ip onayı yok" kısıtı; mevcut kod device_id session’da var; approved_at devices tablosunda (schema_guard); tam akış dokümanda yok.
- **Secrets handling:** VAR. .env: load_dotenv() (main.py ~24). BINANCE_MASTER_KEY: routes.py ~264 "Şifreleme anahtarı (BINANCE_MASTER_KEY) .env dosyasında tanımlı değil" mesajı; API key şifreleme için. DB password: DATABASE_URL env (session; maskeli). Keys: get_account_keys(account_id, db) decrypt ile; nereden geliyor: accounts tablosu / encrypted key storage (maskeli).

---

# 11) OBSERVABILITY

- **Log format:** Python logging; format '%(asctime)s - %(name)s - %(levelname)s - %(message)s'. Bot engine: BOT_LOOP_START, BOT_STATE_LOADED, BOT_STRATEGY_TICK, BOT_ACTION, BOT_TRADE_RECORDED, BOT_CYCLE_END, BOT_FILL_SNAPSHOT, BOT_PROFIT_EXIT_EVAL, BOT_EXECUTION_CAP_QUOTE, BOT_EXECUTION_SKIP, BOT_STATE_SAVING/SAVED.
- **Metrics:** ENGINE_TICK active_bots=N (orchestrator); ENV=prod and not DEBUG_METRICS ise metrics route devre dışı (main.py ~688). request_metrics middleware var.
- **Tracing:** request_id var; distributed trace NOT FOUND.
- **Kritik event’ler:** ORDER_FILLED (append_event); CYCLE_END (profit_usdt, pnl_mode, matched_qty, fees_usdt); quote_qty_capped (INFO); BOT_STATE_SAVED; SKIP_REASON (IDEMPOTENT_LOCK, MIN_NOTIONAL, VIRTUAL_BUDGET_INSUFFICIENT, BINANCE_FREE_QUOTE_INSUFFICIENT).
- **Eksik loglar:** Profit-exit HOLD nedenleri (below_breakeven) BOT_PROFIT_EXIT_EVAL ile loglanıyor (cycle_only_fee_aware_v1). Legacy modda tetik eşiği logu yok. PnL karar detayı (avg_cost, trigger) sadece fee_aware modda.

---

# 12) PERFORMANS PROFİLİ (Bottleneck Map)

- **UI:** DOM: grafik LightweightCharts; büyük events listesi tek seferde render. Fetch: dashboard summary 5s, bot detail sayfa yüklemede bir kez; apiClient timeout 20s. Render: perf_chart setData her 5s; modal açıldığında resize observer.
- **Backend:** I/O: Her tick DB session, load_state, save_state, append_event; symbol lock UPDATE/INSERT. Locks: asyncio bot lock, DB symbol lock. Polling: Tick sleep 2s; fiyat data_hub cache’den.
- **WS/REST:** Engine REST only (data_hub REST loop); WS varsa data_hub’da REST 10s. UI klines REST.
- **Jet gibi hedef:** Tick interval 2s zaten; order path’te gereksiz bekleme yok. Opsiyonel: state save batch; event append batch; fiyat tek istekte çok sembol.

---

# 13) RİSKLER & BUG BACKLOG (P0/P1/P2)

1. **P0 – Cycle PnL negatif (nominal kâr varken):** Scope: initial cost cycle’a karışıyor veya profit-exit fee-altı. Fix: pnl_mode=cycle_only_fee_aware_v1 + trigger_price. Verify: Aynı event akışında cycle PnL ≥ 0 (fee sonrası).
2. **P0 – Profit-exit break-even altı satış:** Tetik nominal. Fix: breakeven_price * (1+min_net_profit_rate). Verify: BOT_PROFIT_EXIT_EVAL decision=SELL sadece price>=trigger.
3. **P0 – quote_qty_capped drift:** virtual vs real. Fix: fill snapshot + available_quote_buffer_pct. Verify: Log free_quote, cap sonrası emir reddi azalır.
4. **P1 – Market data çift kaynak:** UI klines ayrı. Fix: UI fiyat/klines sadece API’den. Verify: Engine ve UI aynı fiyat kaynağına gider.
5. **P1 – Stop’ta open order iptal yok:** Open order kalır. Fix: stop_bot içinde get_open_orders + cancel. Verify: Stop sonrası exchange’de open 0.
6. **P1 – Idempotency TTL 5s:** Aynı action 5s içinde tekrar gelirse skip. Risk: Gerçek retry gerekirse skip. Verify: Dokümantasyon; gerekirse TTL artır.
7. **P1 – Symbol lock 60s:** Lease bitince başka bot alabilir; aynı anda iki bot aynı sembole emir atmaz. Verify: LOCK_BUSY event beklenen.
8. **P1 – State vs virtual sync:** save_state sonrası sync_virtual_wallet_from_state; arada crash → drift. Fix: Tek transaction veya reconcile on load. Verify: Restart sonrası virtual == state.
9. **P1 – Fee BNB → 0:** price_hub’da sembol yoksa fee=0. Fix: Fee USDT’ye çevrilemezse log + opsiyonel pause. Verify: Fee asset log.
10. **P2 – price_hub TTL 5s:** Çok kısa; data_hub 120s. Stale risk. Verify: PRICE_STALE_OR_MISSING sıklığı.
11. **P2 – max_orders_per_minute kullanılmıyor:** risk.guard_max_orders_per_minute çağrılmıyor. Fix: execution path’te guard ekle. Verify: Dakikada N’den fazla emir yok.
12. **P2 – ensure_running_bots started_at güncelliyor:** Her recovery’de started_at=now; orijinal start zamanı kaybolur. Verify: İsteğe bağlı started_at sadece ilk start.
13. **P2 – config_from_ui_payload min_net_profit_rate yok:** UI payload’da yok; default. Verify: UI’da opsiyonel alan.
14. **P2 – CYCLE_END profit_usdt legacy’de equity delta değil:** Artık realized PnL (cycle_pnls) kullanılıyor. Verify: CYCLE_END meta profit_usdt == cycle_pnls son pnl_usdt.
15. **P2 – Grafik tooltip mouseleave:** Eklendi (perf_chart_tv.js). Verify: Grafikten çıkınca tooltip kaybolur.
16. **P2 – Modal legend dinamik:** Eklendi (botLabel/pariteLabel). Verify: Modal’da güncel % görünür.
17. **P2 – cycle_ledger_from_state symbol mismatch:** Ledger cycle_id != state.cycle_id ise yeni empty ledger. Verify: İlk trail_* fill’de ledger doğru.
18. **P2 – initial_allocation client_order_id:** f"init_{bot_id}_c{cycle}" ama strategy’de f"init_{state.get('bot_id',0)}_c{cycle}". bot_id state’te set (orchestrator). Verify: Idempotency key ile uyumlu.
19. **P2 – Bot delete_bot_fully trades siler:** Tüm Trade satırları silinir; raporlama bozulur. Verify: Soft delete veya archive.
20. **P2 – _sync_initial_done_from_db free_quote/locked_quote:** Sync listesinde; yeni alanlar. Verify: Tab reopen’da snapshot kalır.
21. **P2 – Perf chart state:** Tek kaynak backend; önce GET perf-chart-state, boş/hatalıysa localStorage yedek. Sekme görünür olunca state backend'den yeniden alınır; reset sunucuyu da siler. Verify: Yeni cihazda sunucu state’i kullanılır.
22. **P2 – Slippage check trigger_price vs fill_price:** append_event SLIPPAGE_WARN; max_slippage_pct config. Verify: Büyük sapmada event.
23. **P2 – paused_insufficient_balance:** -2010 sonrası status paused_insufficient_balance, backoff_until 60s. Verify: 60s sonra tekrar deneme (loop devam eder).
24. **P2 – LOCK_BUSY:** try_acquire_symbol_lock False → append_event LOCK_BUSY, actions skip. Verify: Aynı account+symbol’de tek bot trade.
25. **P2 – RUN_ACTION_EXCEPTION:** state last_error_code set; append_event ERROR. Verify: Event list’te görünür.
26. **P2 – BOT_STATE_SAVING json.dumps fail:** js="{}"; state_hash="error". Verify: Log warning; state boş yazılır (risk).
27. **P2 – cycle_reset_after_fill symbol:** symbol verilmezse cycle_ledger_current init yok. execution’da symbol=symbol geçiliyor. Verify: Yeni cycle’da ledger var.
28. **P2 – pnl_mode default legacy:** Yeni botlar legacy. Verify: Staging’de cycle_only_fee_aware_v1 manuel/config.
29. **P2 – API performance cycle_pnl_last:** state_for_pnl.cycle_pnls son eleman. Verify: Response’ta cycle_pnl_last, cycle_id_last dolu.
30. **P2 – Event types _LOGGED_EVENT_TYPES:** TICK, IDEMPOTENT_LOCK skip; ERROR, SKIP_REASON, ORDER_FILLED, CYCLE_END, INFO, vb. saklanır. Verify: Event list’te gereksiz TICK yok.

---

# 14) GELİŞTİRME YOL HARİTASI (Iteratif Patch Plan)

**Sprint 1:** (1) pnl_mode=cycle_only_fee_aware_v1 default yapma (config flag); (2) BOT_PROFIT_EXIT_EVAL log’unu legacy’de de tetik eşiği ile yaz; (3) tests/test_cycle_ledger.py pytest ile CI. Risk: Default değişince davranış. Test: Mevcut botlar legacy kalır.

**Sprint 2:** (1) max_orders_per_minute guard execution’da; (2) stop_bot’ta open order cancel (get_open_orders + cancel); (3) state_store + virtual_wallet tek transaction (veya reconcile on load). Risk: Cancel fail. Test: Stop sonrası open 0.

**Sprint 3:** (1) Market data: UI klines tek endpoint (backend proxy); (2) request_id middleware’de set, log’da correlation; (3) delete_bot_fully trades soft-delete veya archive. Risk: UI klines gecikme. Test: Chart aynı veri.

**Sprint 4:** (1) Fee BNB→USDT fail’de log + opsiyonel pause; (2) ensure_running_bots started_at sadece ilk start; (3) config_from_ui_payload min_net_profit_rate, pnl_mode. Risk: Minimal. Test: UI’dan pnl_mode gönder.

**Sprint 5:** (1) Backend rate limit (per account/IP); (2) CORS/CSRF dokümantasyon; (3) BOT_STATE_SAVING json fail’de state’i yazma, retry. Risk: Rate limit false positive. Test: Load test.

**Sprint 6:** (1) Metrics: bot_cycle_pnl_net, bot_cycle_winrate (Prometheus/StatsD); (2) Tracing: request_id span; (3) Grafik bucket sayısı limit (performans). Risk: Metrik patlaması. Test: Dashboard.

**Sprint 7:** (1) Idempotency TTL config; (2) Symbol lock TTL config; (3) Tick interval floor 1s. Risk: Çok sık tick. Test: Config değişimi.

**Sprint 8:** (1) Crash recovery: open order reconcile (start’ta exchange open vs state); (2) state hash checksum; (3) Event meta schema version. Risk: Reconcile yanlış işaret. Test: Simüle crash.

**Sprint 9:** (1) UI: cycle_pnl_last, pnl_calculation_mode gösterimi; (2) Perf chart export; (3) Event filter (type). Risk: UI karmaşıklık. Test: E2E.

**Sprint 10:** (1) Docs: runbook güncelleme; (2) Sanity check otomasyon; (3) Rollback plan dokümantasyonu. Risk: Yok. Test: Manuel.

---

# APPENDIX A) KOD PARÇALARI (Kısa, hedefli)

**Orchestrator loop girişi (orchestrator.py ~97–114):**
```python
while bot_id not in _stop_requested:
    db = _get_db()
    try:
        row = db.query(Bot).filter(Bot.id == bot_id).first()
        status_lower = (str(row.status or "").lower()) if row else ""
        if not row or status_lower not in ("running", "paused_error"):
            break
        ...
        state = load_state(db, bot_id)
        ...
        actions, next_wake = tick_dca_grid_trailing(state, cfg, price, base_balance, quote_balance)
        ...
        run_result = await run_actions(bot_id, account_id, actions, state, cfg, adapter, db=db, ...)
```

**Cycle ledger PnL (cycle_ledger.py ~59–78):**
```python
def cycle_ledger_add_fill(ledger, ts, order_id, client_order_id, side, qty, price, fee, fee_asset, reason):
    ...
    if side == "BUY":
        ledger["buy_qty_total"] += qty
        ledger["buy_quote_total"] += qty * price
        ledger["buy_fee_total_quote"] += fee_quote
    else:
        ledger["sell_qty_total"] += qty
        ...
    _cycle_ledger_recompute(ledger)  # realized_pnl_quote = sell_quote - buy_quote - total_fees
```

**State save (state_store.py ~69–99):**
```python
def save_state(db, bot_id, account_id, state):
    state["state_version"] = state.get("state_version", 0) + 1
    state_serializable = _state_to_json_serializable(state)
    js = json.dumps(state_serializable, ensure_ascii=False)
    db.execute(text("""INSERT INTO bot_engine_state (...) VALUES (...) ON CONFLICT(bot_id) DO UPDATE SET ..."""), {...})
    db.commit()
```

**Adapter get_price (binance_adapter.py ~79–102):**
```python
def get_price(self, symbol: str) -> Optional[float]:
    from app.services.data_hub import data_hub
    d = data_hub.get_price(symbol)
    if d and isinstance(d, dict): p = d.get("price"); ...
    from app.services.price_hub import price_hub
    p = price_hub.get_price(symbol); ...
    from app.services.binance_spot import _sync_public_get
    data = _sync_public_get("/api/v3/ticker/price", {"symbol": sym_upper}, testnet=False)
```

---

# APPENDIX B) DATA SCHEMAS

**BotConfig (DcaGridTrailingConfig.to_dict):** symbol, initial_capital_usdt, bot_budget_usdt, base_alloc_pct, quote_alloc_pct, fee_rate, buy_fee_rate, sell_fee_rate, min_net_profit_rate, pnl_mode, paper_mode, sell_grids[], buy_grids[], sell_trigger_trailing_pct, buy_trigger_trailing_pct, profit_reentry_drop_pct, profit_reentry_rise_pct, profit_exit_rise_pct, profit_exit_drop_pct, basis_mode, tick_interval_ms, max_orders_per_minute, max_slippage_pct, min_notional_guard, initial_fee_buffer_pct, available_quote_buffer_pct.

**BotState (state_json):** bot_id, account_id, symbol, status, cycle_id, state_version, reference_price, initial_allocation_done, initial_alloc_base_qty, initial_alloc_price, base_balance, quote_balance, sell_grid_fired[], buy_grid_fired[], sell_grid_trigger_price[], buy_grid_trigger_price[], sell_grid_peak_price[], buy_grid_trough_price[], sell_grid_fill_price[], buy_grid_fill_price[], mode, trail_anchor_price, trail_activation_price, sell_history[], buy_history[], grid_reference_quote, grid_reference_base, cycle_start_equity, realized_pnl_usdt_cycle, fees_paid_usdt_cycle, cycle_pnls[], cycle_ledger_current (optional), free_quote, locked_quote, last_fill_snapshot (optional), last_tick_at, last_error_code, _profit_exit_done, _reentry_done, _cycle_complete.

**OrderFill event (ORDER_FILLED meta):** order_id, client_order_id, side, fill_qty, fill_price, fee, reason. CYCLE_END meta: cycle_id, profit_usdt, pnl_mode, matched_qty, fees_usdt, realized_pnl_cycle_net?, buy_quote_total?, sell_quote_total?, fee_totals_quote?.

**UI performance response:** request_id, bot_id, account_id, pnl_usd, pnl_pct, real_performance_pct, trades_count, cycles_count, fees_usd, realized, total_usd, initial_usd, balance_start_usd, config_budget_usd, balance_end_usd, reference_price, current_price, chart_series, pair_series, cycle_pnl_last, cycle_id_last, pnl_calculation_mode, realized_pnl_total, fees_total.

---

*End of PROJECT_BOTENGINE_XRAY.md. No secrets. All references to repo paths and line numbers are from the codebase at the time of writing.*

**Güncelleme kuralı:** Her bot/UI/API ile ilgili işlemden sonra bu dosya en güncel hâline getirilir (wizard, parametre ekranı, API davranışı, Binance/finance değişiklikleri vb.).
