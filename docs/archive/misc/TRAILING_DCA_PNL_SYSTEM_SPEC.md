# TRAILING DCA BOT — KAR VE PNL HESAPLAMA SİSTEMİ (TEKNİK REFERANS)

Bu belge yalnızca trailing DCA (dca_grid_trailing) botunun kar ve PnL hesaplama mimarisini, veri akışlarını, formülleri ve sabitleri makine okunabilir ve deterministik şekilde tanımlar. İnsan okunabilirliği hedeflenmez.

---

## 1. GENEL VERİ KAYNAKLARI VE HİYERARŞİ

| Kaynak | Tablo/State | Kullanım |
|--------|-------------|----------|
| bot_engine_state | state_json | base_balance, quote_balance, cycle_id, sell_history, buy_history, cycle_ledger_current, realized_pnl_usdt_cycle, fees_paid_usdt_cycle, cycle_start_equity, last_cycle_profit_usdt, daily_ref_usd, daily_ref_date, last_fill_snapshot, free_quote |
| bot_virtual_wallet | virtual_base, virtual_quote | total_usd = vb*price + vq; check_virtual_budget; sync_virtual_wallet_from_state(state) after save_state |
| trades | Trade | FIFO realized per cycle; cycle completion date = max(ts) in cycle; daily_realized = cycles completed today |
| pnl_snapshots | PnlSnapshot | total_usd, realized, unrealized, daily, monthly; monthly = total_usd - first snapshot in month or initial_total |
| account_daily_realized_pnl | account_id, date_tr, amount_usd | Cache: silinen botların o günkü gerçekleşen PnL; consolidate_date ile güncellenir |

Zaman referansı: turkey_today_start_utc() = Europe/Istanbul 00:00 → naive UTC. Günlük K/Z ve "bugün tamamlanan tur" bu referansa göre.

---

## 2. STATE ALANLARI (PnL İLE İLİŞKİLİ)

- base_balance, quote_balance: apply_fill_to_state ve sync_virtual_wallet_from_state ile güncellenir; fill sonrası Binance snapshot ile last_fill_snapshot içinde de saklanır.
- initial_allocation_done: Sadece execution'da gerçek fill sonrası True. initial_allocation buy_history'ye eklenmez.
- sell_history, buy_history: Her entry { grid_index, qty, price, execution_price? }. Sadece grid/reentry/profit_sell fill'leri; initial_allocation BUY eklenmez.
- realized_pnl_usdt_cycle: apply_fill_to_state SELL'de artar: delta = qty*price - fee - (qty * avg_buy_price); avg_buy_price = _avg_buy_price(state) = buy_history ağırlıklı ortalama fill price.
- fees_paid_usdt_cycle: Her fill'de fee_val eklenir.
- cycle_start_equity: cycle_reset_after_fill'da current_equity yapılır; current_equity = quote_bal + base_bal * price (round 2).
- last_cycle_profit_usdt: cycle_reset_after_fill'da current_equity - cycle_start; round 2.
- cycle_ledger_current: cycle_ledger.py yapısı; cycle_ledger_add_fill ile güncellenir; cycle_reset'te build_cycle_ledger_empty(new_cycle_id, symbol) ile sıfırlanır.
- daily_ref_usd, daily_ref_date: PnlService.calculate_bot_pnl içinde; state.daily_ref_date != today_date ise daily_ref_usd = total_usd, daily_ref_date = today_date, save_state.
- last_fill_snapshot: _write_fill_snapshot_to_state ile { free_quote, locked_quote, base_qty, avg_cost, realized_pnl, fees_total, snapshot_at }; realized_pnl = cycle_pnls pnl_usdt toplamı + realized_pnl_usdt_cycle; fees_total = cycle_pnls fees_usdt + fees_paid_usdt_cycle; avg_cost = _avg_buy_price_total(state) veya reference_price.

---

## 3. VIRTUAL WALLET

- get_virtual_wallet(db, bot_id, symbol) -> (virtual_base, virtual_quote). Yoksa (0,0).
- ensure_virtual_wallet: İlk oluşturmada virtual_base=0, virtual_quote=initial_quote_usdt.
- update_virtual_after_fill(side, fill_qty, quote_value, fee_usdt): BUY => base += fill_qty, quote -= quote_value + fee; SELL => base -= fill_qty, quote += quote_value - fee. MAX(0,...) quote/base için uygulanır.
- sync_virtual_wallet_from_state(db, bot_id, account_id, symbol, base_balance, quote_balance): state source of truth; virtual_wallet satırı state ile eşitlenir (save_state sonrası çağrılır).
- check_virtual_budget: BUY => quote_amount <= virtual_quote * (1 - fee_buffer_pct); SELL => base_qty <= virtual_base. Epsilon: _BASE_QTY_EPSILON = 1e-10.

---

## 4. FILL UYGULAMASI (apply_fill_to_state)

- Girdi: side, executed_qty, executed_price, fee, grid_index?, reason, execution_price?.
- fees_paid_usdt_cycle += fee_val.
- SELL: base_balance -= q; quote_balance += q*p - fee_val; sell_history.append({ grid_index, qty, price, execution_price? }); cost = q * (avg_buy_price or p); realized_pnl_usdt_cycle += (q*p - fee_val - cost). avg_buy_price = _avg_buy_price(state) = buy_history'den ağırlıklı ortalama (sadece fill price, execution_price değil).
- BUY: base_balance += q; quote_balance -= q*p + fee_val; reason != "initial_allocation" ise buy_history.append({ grid_index, qty, price, execution_price? }).

---

## 5. CYCLE LEDGER YAPISI

- build_cycle_ledger_empty(cycle_id, symbol): cycle_id, symbol, base_asset, quote_asset, fills=[], buy_qty_total=0, buy_quote_total=0, buy_fee_total_quote=0, sell_qty_total=0, sell_quote_total=0, sell_fee_total_quote=0, avg_cost_quote_per_base=None, realized_pnl_quote=0, breakeven_price=None, matched_qty=0, started_at, inventory_coin_adv_qty=0, inventory_fees_usdt=0, cash_pnl_usdt=0, cash_fees_usdt=0.
- CYCLE_FILL_REASONS = { trail_buy_grid, trail_sell_grid, trail_reentry_buy, trail_profit_sell }. initial_allocation ledger'a eklenmez.
- cycle_ledger_add_fill(ledger, ts, order_id, client_order_id, side, qty, price, fee, fee_asset, reason): fills.append(entry); BUY => buy_qty_total += qty, buy_quote_total += qty*price, buy_fee_total_quote += fee_quote; SELL => sell_qty_total += qty, sell_quote_total += qty*price, sell_fee_total_quote += fee_quote; _cycle_ledger_recompute(ledger).
- _cycle_ledger_recompute: matched_qty = min(buy_qty, sell_qty); avg_cost_quote_per_base = (buy_quote + buy_fee) / buy_qty if buy_qty>0 else None; realized_pnl_quote = sell_quote - buy_quote - (buy_fee + sell_fee); _recompute_dual_pnl(ledger).
- _recompute_dual_pnl: INVENTORY: trail_sell_grid SELL → inv_sells queue; trail_reentry_buy BUY → FIFO match inv_sells, inventory_coin_adv_qty += (buy_qty_equiv - take), inventory_fees_usdt += fees. CASH: trail_buy_grid BUY → cash_buys queue; trail_profit_sell SELL → FIFO match cash_buys, cash_pnl_usdt += gross - buy_fee_alloc - sell_fee_alloc, cash_fees_usdt += fees. Pro rata fee allocation: take/remaining_qty.
- cycle_ledger_breakeven_price(ledger, buy_fee_rate=0.001, sell_fee_rate=0.001): avg = ledger.avg_cost_quote_per_base; None/<=0 => None; return avg * (1+buy_fee_rate) / (1-sell_fee_rate). Clamp fee rates [0,1] ve sell_fee_rate < 1.
- cycle_ledger_trigger_price(ledger, min_net_profit_rate=0.001, buy_fee_rate, sell_fee_rate): be = cycle_ledger_breakeven_price(...); return be * (1 + min_net_profit_rate).

---

## 6. PROFIT EXIT TETİKLEME (STRATEJİ)

- basis_mode: "grid_only" | "total". total => _avg_buy_price_total(state) (initial_alloc_base_qty * initial_alloc_price + buy_history toplamı) / (init_q + grid_q). grid_only => _avg_buy_price_for_trigger(state) (buy_history, execution_price varsa onu kullan).
- pnl_mode: "legacy" | "cycle_only_fee_aware_v1".
- cycle_only_fee_aware_v1: ledger = cycle_ledger_from_state(state, symbol); breakeven = cycle_ledger_breakeven_price(ledger, buy_fee_rate, sell_fee_rate); trigger_price = cycle_ledger_trigger_price(ledger, min_net_profit_rate, buy_fee_rate, sell_fee_rate). P >= trigger_price => TRAIL_PROFIT_SELL. P < trigger_price ve P < breakeven => HOLD (log).
- legacy: avg_buy = _avg_buy_price_total (basis_mode=total) veya _avg_buy_price_for_trigger (grid_only); thr = avg_buy * (1 + profit_exit_rise_pct/100); P >= thr => TRAIL_PROFIT_SELL.
- _profit_exit_sell_qty: buy_history qty toplamı; min(base_balance, total_q). initial_allocation buy_history'de olmadığı için sadece grid alımları satılır.

---

## 7. CYCLE RESET (cycle_reset_after_fill)

- Çağrı: trail_reentry_buy veya trail_profit_sell fill sonrası execution'da.
- current_equity = round(quote_bal + base_bal * price, 2); cycle_start = state.cycle_start_equity; last_cycle_profit_usdt = round(current_equity - cycle_start, 2).
- cycle_id += 1; reference_price = price; sell_grid_fired/trigger_price/peak_price/fill_price, buy_grid_* sıfırlanır; sell_history, buy_history = []; cycle_start_equity = current_equity; grid_reference_quote = current_equity; grid_reference_base = base_bal; _reentry_done, _profit_exit_done, _cycle_complete pop; cycle_ledger_current = build_cycle_ledger_empty(new_cycle_id, symbol).

---

## 8. PNL SERVICE — total_usd KAYNAKLARI

- Öncelik 1: virtual_wallet row varsa total_usd = vb * current_price + vq; base_qty=vb, quote_qty=vq; realized=0, unrealized=0 (vw kullanıldığında).
- initial_allocation_done False ve initial_capital > 0 ve not is_multi => total_usd = initial_capital (gösterim için).
- MULTI: _compute_multi_total_usd_from_state veya fallback initial_capital.
- Fallback (vw yok, tek sembol): Trade tablosundan FIFO; BUY => base_qty += qty, total_cost += qty*price, quote_qty -= cost; SELL => avg_buy = total_cost/base_qty, pnl = (price - avg_buy)*sell_qty, realized += pnl, base_qty -= sell_qty, total_cost -= avg_buy*sell_qty; unrealized = (current_price - avg_buy)*base_qty if base_qty>0; total_usd = quote_qty + base_qty*current_price.

---

## 9. GÜNLÜK VE AYLIK PNL (PnLService)

- initial_capital: config initial_capital_usdt | budget_usd | bot_budget_quote.
- today_date = turkey_today_start_utc().strftime("%Y-%m-%d"). state.daily_ref_date != today_date => state.daily_ref_usd = total_usd, state.daily_ref_date = today_date, save_state.
- daily_ref_usd = state.daily_ref_usd; daily = total_usd - daily_ref_usd; daily_pnl_pct = (daily / daily_ref_usd * 100) if daily_ref_usd>0 else 0.
- month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0). monthly_snap = PnlSnapshot filter ts >= month_start order ts asc first. monthly = total_usd - monthly_snap.total_usd if monthly_snap else total_usd - initial_total.

---

## 10. GÜNLÜK GERÇEKLEŞEN PNL (REALIZED) — TUR BAZLI

- Tur "tamamlandı" = o turdaki son işlemin ts'si ilgili gün içinde (Türkiye 00:00+).
- _daily_realized_for_bot_trades: Trade'ları cycle_id'ye göre grupla; her cycle için max(ts) >= today_start ise FIFO ile realized hesapla (BUY cost biriktir, SELL'de avg_buy ile pnl); toplam.
- daily_realized_from_cycles_completed_today: Tüm botlar için aynı mantık; son olarak get_account_daily_realized_cache(account_id, today_str) eklenir (silinen botlar).
- _realized_for_date_from_trades(db, account_id, date_tr): date_tr gününde tamamlanan turlar (last_ts in [day_start, day_end)); her cycle FIFO realized toplamı.
- consolidate_date: from_cache = get_account_daily_realized_cache; from_trades = _realized_for_date_from_trades; total = from_cache + from_trades; UPSERT account_daily_realized_pnl (amount_usd = total). Bot silinirken bugünkü realized add_to_account_daily_realized_cache ile eklenir.

---

## 11. TRADE TABLOSU VE Ledger.record_trade

- Trade: bot_id, account_id, ts, side, qty, price, fee, fee_asset, slot_id, reference_price, order_id, client_order_id, symbol, cycle_id.
- record_trade: order_id verilmişse (bot_id, order_id) var mı bak; varsa (existing, False); yoksa INSERT (cycle_id default 1), return (trade, True).
- execution fill akışında: apply_fill_to_state; cycle_ledger_add_fill (CYCLE_FILL_REASONS içindeki reason'lar için); Ledger.record_trade(..., cycle_id=state.cycle_id); update_virtual_after_fill; _write_fill_snapshot_to_state; save_state; sync_virtual_wallet_from_state.

---

## 12. PnlSnapshot

- Alanlar: bot_id, account_id, ts, total_usd, realized, unrealized, daily, monthly.
- save_snapshot(db, bot_id, account_id, pnl_data): PnlSnapshot insert, commit.
- Aylık kar: ilk snapshot ay başından itibaren ts >= month_start; monthly = total_usd - o snapshot.total_usd.

---

## 13. FILL SNAPSHOT (last_fill_snapshot)

- _write_fill_snapshot_to_state: adapter.get_account_balances(); free_quote, locked_quote (exchange veya state.quote_balance); base_qty = state.base_balance; avg_cost = _avg_buy_price_total(state) veya state.reference_price; realized_pnl = sum(cycle_pnls.pnl_usdt) + state.realized_pnl_usdt_cycle; fees_total = sum(cycle_pnls.fees_usdt) + state.fees_paid_usdt_cycle; state.last_fill_snapshot = { free_quote, locked_quote, base_qty, avg_cost, realized_pnl, fees_total, snapshot_at }; state.free_quote = free_quote.

---

## 14. ORTALAMA FİYAT FONKSİYONLARI

- _avg_buy_price(state): buy_history; sum(qty*price)/sum(qty). Sadece fill price.
- _avg_buy_price_for_trigger(state): buy_history; execution_price varsa onu kullan, yoksa price; sum(qty*exec_price)/sum(qty).
- _avg_buy_price_total(state): initial_alloc_base_qty * initial_alloc_price + sum(buy_history qty*price); payda initial_alloc_base_qty + sum(buy_history qty). basis_mode=total için.
- _avg_sell_price(state): sell_history; sum(qty*price)/sum(qty).
- _avg_sell_price_for_trigger(state): sell_history; execution_price varsa onu kullan.

---

## 15. SABİTLER VE CONFIG ALANLARI

- buy_fee_rate, sell_fee_rate: default 0.001. cycle_ledger_breakeven_price ve cycle_ledger_trigger_price'ta kullanılır.
- min_net_profit_rate: default 0.001. trigger_price = breakeven * (1 + min_net_profit_rate).
- profit_exit_rise_pct: legacy modda thr = avg_buy * (1 + profit_exit_rise_pct/100).
- profit_reentry_drop_pct: re-entry thr = avg_sell * (1 - profit_reentry_drop_pct/100).
- available_quote_buffer_pct: default 0.005; check_virtual_budget'ta değil; execution'da BUY cap için free_quote * (1 - buffer).
- fee_buffer_pct (initial_allocation): 0.002; required = quote_qty * (1 + fee_buffer_pct).
- _BASE_QTY_EPSILON = 1e-10. Float karşılaştırma SELL tarafında.

---

## 16. EXECUTION FILL AKIŞI (ÖZET)

- ORDER FILLED sonrası: exec_qty, fill_price, fee, side, reason, grid_index, execution_price (action'dan).
- apply_fill_to_state(state, side, exec_qty, fill_price, fee, grid_index, reason, execution_price).
- reason in CYCLE_FILL_REASONS => ledger = cycle_ledger_from_state(state, symbol) veya build_cycle_ledger_empty; cycle_ledger_add_fill(ledger, ...); state.cycle_ledger_current = ledger.
- Ledger.record_trade(db, ..., cycle_id=state.cycle_id).
- update_virtual_after_fill(db, bot_id, symbol, side, fill_qty, quote_value=exec_qty*fill_price, fee_usdt=fee).
- _write_fill_snapshot_to_state(state, adapter, config, symbol).
- save_state(db, bot_id, account_id, state).
- sync_virtual_wallet_from_state(db, bot_id, account_id, symbol, state.base_balance, state.quote_balance).
- reason in (trail_reentry_buy, trail_profit_sell) => cycle_reset_after_fill(state, fill_price, n_sell_grids, m_buy_grids, symbol).

---

## 17. DUAL PNL (INVENTORY vs CASH) — DETAY

- INVENTORY_REASONS: trail_sell_grid, trail_reentry_buy. trail_sell_grid SELL → inv_sells list (qty, price, fee). trail_reentry_buy BUY → FIFO ile inv_sells'ten take; sell_proceeds_net = take*sp - sell_fee_alloc; buy_qty_equiv = sell_proceeds_net / buy_price_eff; inv_coin_adv += buy_qty_equiv - take; inv_fees += sell_fee_alloc + buy_fee_alloc.
- CASH_REASONS: trail_buy_grid, trail_profit_sell. trail_buy_grid BUY → cash_buys list. trail_profit_sell SELL → FIFO match; gross = take*(price - bp); cash_pnl += gross - buy_fee_alloc - sell_fee_alloc; cash_fees += fees.
- get_cycle_type_and_base_delta: trail_profit_sell => (LONG_SCALP, 0); trail_reentry_buy => (INVENTORY_REBALANCE, buy_qty_total - sell_qty_total).

---

## 18. DASHBOARD / API total_usd KULLANIMI

- bots_engine detail: PnlService.calculate_bot_pnl => total_usd, daily, daily_pnl_pct, monthly; current_usd = pnl_data.total_usd; initial_capital from config; UI BOT BAKİYESİ = current_usd.
- dashboard_snapshot: fetch_bots_and_account_kpis; her bot için PnlService.calculate_bot_pnl; current_usd; total_bot_equity_usd; daily_ref için state.daily_ref_usd kullanılır (yeni gün total_usd yazılır).

---

## 19. TÜRKİYE GÜNÜ VE TARİH ARALIKLARI

- turkey_today_start_utc(): datetime.now(Europe/Istanbul).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).replace(tzinfo=None).
- Cycle "bugün tamamlandı": cycle'daki tüm trade'ların max(ts) >= turkey_today_start_utc() (ve isteğe bağlı < tomorrow).
- date_tr format: "%Y-%m-%d". account_daily_realized_pnl.date_tr.

---

## 20. ÖZET FORMÜLLER

- total_usd (tek sembol, vw var): virtual_base * current_price + virtual_quote.
- daily_pnl: total_usd - daily_ref_usd; daily_ref_usd her gece (state.daily_ref_date != today) total_usd ile güncellenir.
- monthly_pnl: total_usd - (ayın ilk PnlSnapshot.total_usd veya initial_capital).
- realized_pnl_quote (cycle ledger): sell_quote_total - buy_quote_total - buy_fee_total_quote - sell_fee_total_quote.
- breakeven_price: avg_cost_quote_per_base * (1+buy_fee_rate) / (1-sell_fee_rate).
- trigger_price: breakeven_price * (1+min_net_profit_rate).
- state.realized_pnl_usdt_cycle (SELL): += qty*price - fee - qty*avg_buy_price; avg_buy_price = buy_history fill price ortalaması.
- last_cycle_profit_usdt: current_equity - cycle_start_equity (cycle_reset anında).

---

## 21. TRADE TABLO ŞEMASI (DB)

- trades: id, bot_id, account_id, ts (DateTime UTC), side (BUY|SELL), qty (Float), price (Float), fee (Float), fee_asset (String default USDT), slot_id (Integer nullable), reference_price (Float nullable), order_id (String nullable unique with bot_id), client_order_id (String nullable), symbol (String nullable), cycle_id (Integer nullable default 1).
- Idempotency: (bot_id, order_id) unique; record_trade order_id ile önce select, varsa insert yapılmaz.

---

## 22. PnlSnapshot TABLO ŞEMASI

- pnl_snapshots: id, bot_id, account_id, ts (DateTime), total_usd (Float), realized (Float default 0), unrealized (Float default 0), daily (Float default 0), monthly (Float default 0).
- Aylık kar sorgusu: ts >= month_start order by ts asc limit 1 => first snapshot of month; monthly = current total_usd - snapshot.total_usd.

---

## 23. account_daily_realized_pnl TABLO ŞEMASI

- account_daily_realized_pnl: account_id (INT), date_tr (TEXT YYYY-MM-DD), amount_usd (FLOAT), updated_at. UNIQUE(account_id, date_tr). ON CONFLICT DO UPDATE amount_usd = excluded.amount_usd (consolidate_date) veya amount_usd += excluded.amount_usd (add_to_account_daily_realized_cache).

---

## 24. CONFIG ANAHTARLARI (PnL / KAR İLE İLİŞKİLİ)

- initial_capital_usdt, budget_usd, bot_budget_quote: Bütçe; total_usd gösterimi (initial_allocation_done=False); initial_total; monthly baseline.
- base_alloc_pct, quote_alloc_pct: initial_allocation dağılımı; cycle_reset sonrası target_quote_usdt / target_base_usdt (equity * alloc).
- buy_fee_rate, sell_fee_rate: 0.001 default; breakeven_price ve trigger_price.
- min_net_profit_rate: 0.001 default; trigger_price = breakeven * (1+min_net).
- profit_exit_rise_pct: legacy profit exit threshold.
- profit_reentry_drop_pct: re-entry threshold avg_sell * (1 - pct/100).
- pnl_mode: "legacy" | "cycle_only_fee_aware_v1".
- basis_mode: "grid_only" | "total"; avg_buy için total = initial + grid.
- available_quote_buffer_pct: BUY cap free_quote * (1 - buffer).

---

## 25. CYCLE LEDGER FIFO DETAY (PSEUDO-CODE)

INVENTORY path: inv_sells = list of (qty_remaining, price, fee). On trail_sell_grid SELL: append (qty, price, fee). On trail_reentry_buy BUY: buy_qty_rem = qty; for each inv_sells[idx]: take = min(sq, buy_qty_rem); sell_fee_alloc = sf * (take/sq); buy_fee_alloc = buy_fee_total * (take/buy_qty_total); sell_proceeds_net = take*sp - sell_fee_alloc; buy_qty_equiv = sell_proceeds_net / buy_price_eff; inv_coin_adv += buy_qty_equiv - take; inv_fees += sell_fee_alloc + buy_fee_alloc; inv_sells[idx][0] -= take; buy_qty_rem -= take. Unmatched buy remainder: inv_fees += buy_fee_total * (buy_qty_rem/buy_qty_total).

CASH path: cash_buys = list of (qty_remaining, price, fee). On trail_buy_grid BUY: append (qty, price, fee). On trail_profit_sell SELL: sell_qty_rem = qty; for each cash_buys[idx]: take = min(bq, sell_qty_rem); buy_fee_alloc = bf*(take/bq); sell_fee_alloc = sell_fee_total*(take/sell_qty_total); gross = take*(price - bp); cash_pnl += gross - buy_fee_alloc - sell_fee_alloc; cash_fees += buy_fee_alloc + sell_fee_alloc; cash_buys[idx][0] -= take; sell_qty_rem -= take.

---

## 26. EDGE CASES VE FALLBACK

- virtual_wallet row yok, Trade yok: calculate_bot_pnl return total_usd=0, realized=0, unrealized=0, daily=0, daily_pnl_pct=0, monthly=0.
- virtual_wallet row yok, Trade var: FIFO from trades; total_usd = quote_qty + base_qty*current_price; current_price = price_hub veya son trade price.
- initial_allocation_done False, initial_capital > 0, not is_multi: total_usd override = initial_capital (UI BOT BAKİYESİ).
- daily_ref_usd == 0: daily_pnl_pct = 0 (division guard).
- monthly_snap None: monthly = total_usd - initial_total.
- ledger avg_cost_quote_per_base None: breakeven_price None, trigger_price None; profit exit (cycle_only_fee_aware_v1) tetiklenmez.
- buy_history boş, SELL fill: avg_buy = p (fill price) cost = q*p => realized delta = -fee_val (sıfır kar).

---

## 27. EXECUTION FILL SIRASI (TAM LİSTE)

1. apply_fill_to_state(state, side, exec_qty, fill_price, fee, grid_index, reason, execution_price).
2. reason in CYCLE_FILL_REASONS: ledger = state.cycle_ledger_current or build_cycle_ledger_empty(cycle_id, symbol); cycle_ledger_add_fill(ledger, ts, order_id, client_order_id, side, exec_qty, fill_price, fee, USDT, reason); state.cycle_ledger_current = ledger.
3. Ledger.record_trade(db, bot_id, account_id, side, exec_qty, fill_price, fee, USDT, slot_id=grid_index, order_id=res.orderId, client_order_id, symbol, cycle_id=state.cycle_id).
4. update_virtual_after_fill(db, bot_id, symbol, side, exec_qty, exec_qty*fill_price, fee).
5. _write_fill_snapshot_to_state(state, adapter, config, symbol).
6. save_state(db, bot_id, account_id, state).
7. sync_virtual_wallet_from_state(db, bot_id, account_id, symbol, state.base_balance, state.quote_balance).
8. reason in (trail_reentry_buy, trail_profit_sell): cycle_reset_after_fill(state, fill_price, n, m, symbol).

---

## 28. PnlService.calculate_bot_pnl DÖNÜŞ ŞEKİLLERİ

- success: { total_usd, realized, unrealized, daily, daily_pnl_pct, monthly, base_qty, quote_qty, current_price }.
- error: { error: "Bot not found" }.
- daily_pnl_pct: round(..., 2). monthly: total_usd - monthly_snap.total_usd or total_usd - initial_total.

---

## 29. GÜNLÜK REFERANS GÜNCELLEME KOŞULU

- today_date = turkey_today_start_utc().strftime("%Y-%m-%d").
- state.daily_ref_date != today_date => yeni gün; state.daily_ref_usd = total_usd (bu tick'te hesaplanan); state.daily_ref_date = today_date; save_state(db, bot_id, account_id, state). Böylece aynı gün içinde daily_ref_usd sabit kalır; ertesi gün ilk hesaplamada total_usd yeni referans olur.

---

## 30. CYCLE TAMAMLANMA TARİHİ TANIMI

- Cycle C "date_tr gününde tamamlandı" <=> cycle C'ye ait tüm Trade kayıtlarında max(ts) in [day_start, day_end) where day_start = date_tr 00:00 Turkey, day_end = day_start + 1 day.
- _realized_for_date_from_trades: her bot, her cycle için last_ts = max(t.ts); if last_ts < day_start or last_ts >= day_end: skip; else FIFO realized toplamı cycle'da, total += realized.
- consolidate_date(date_tr): from_trades = _realized_for_date_from_trades(account_id, date_tr); from_cache = get_account_daily_realized_cache(account_id, date_tr); UPSERT amount_usd = from_cache + from_trades (replace full value, not increment; from_trades zaten tüm mevcut botları kapsar; cache sadece silinen botların o günkü payı).

---

## 31. BOT SİLİNME AKIŞI (PnL KORUMA)

- Bot silinmeden önce: today_str = turkey_today_start_utc().strftime("%Y-%m-%d"); bot_today_realized = _daily_realized_for_bot_trades(db, bot_id, account_id); PnlService.add_to_account_daily_realized_cache(db, account_id, today_str, bot_today_realized). Sonra bot_virtual_wallet, bot_engine_events, pnl_snapshots, bots delete.

---

## 32. FORMÜL REFERANS (TEK SATIR)

total_usd_vw = vb*price + vq. daily = total_usd - daily_ref_usd. daily_pnl_pct = 100*daily/daily_ref_usd if daily_ref_usd>0 else 0. monthly = total_usd - monthly_snap.total_usd | (total_usd - initial_capital). realized_pnl_quote_ledger = sell_quote_total - buy_quote_total - buy_fee - sell_fee. avg_cost_quote_per_base = (buy_quote_total + buy_fee_total_quote) / buy_qty_total. breakeven = avg_cost * (1+buy_fee_rate)/(1-sell_fee_rate). trigger = breakeven * (1+min_net_profit_rate). state_realized_delta_sell = qty*price - fee - qty*avg_buy_price. last_cycle_profit_usdt = round(quote_bal + base_bal*price - cycle_start_equity, 2). FIFO_cycle_realized: per cycle BUY cost biriktir avg_buy=total_cost/base_qty; SELL pnl = (price-avg_buy)*min(qty,base_qty); base_qty -= sell_qty; total_cost -= avg_buy*sell_qty.

---

## 33. PRICE HUB VE current_price KAYNAĞI

- PnlService: current_price = price_hub.get_price(bot.symbol). Yoksa trades[-1].price. Bots_engine detail: pnl_data.current_price; yoksa price_hub.get_price(bot.symbol). total_usd (vw) = vb*current_price + vq. Unrealized (trades fallback) = (current_price - avg_buy_price)*base_qty.

---

## 34. cycle_pnls STATE ALANI (VARSA)

- state.cycle_pnls: list of { pnl_usdt, fees_usdt } geçmiş turlar için; _write_fill_snapshot_to_state içinde realized_pnl = sum(cycle_pnls.pnl_usdt) + realized_pnl_usdt_cycle; fees_total = sum(cycle_pnls.fees_usdt) + fees_paid_usdt_cycle. cycle_reset sonrası cycle_pnls güncellenip güncellenmediği kod path'e bağlı (execution'da cycle_reset_after_fill cycle_pnls append edebilir veya etmeyebilir; spec'te last_fill_snapshot formülü cycle_pnls varsa toplama dahil).

---

## 35. MIN_NOTIONAL VE PnL

- guard_min_notional(notional, min_notional_guard): notional < min_notional => SKIP; fill olmaz => state/vw/ledger güncellenmez. min_notional_guard config (default 10). initial_allocation cap sonrası notional_capped >= min_notional kontrolü yapılır.

---

## 36. INITIAL_ALLOCATION FILL VE CYCLE

- initial_allocation fill: apply_fill_to_state çağrılır (BUY); buy_history'ye eklenmez (reason == "initial_allocation"). cycle_ledger_add_fill çağrılmaz (reason not in CYCLE_FILL_REASONS). Ledger.record_trade cycle_id=0 veya 1 (execution'da cycle_id_intent=0). initial_alloc_base_qty, reference_price state'te set edilir (execution fill handler). cycle_start_equity ilk cycle için initial allocation sonrası mı set edilir: cycle_reset sadece trail_reentry_buy/trail_profit_sell sonrası; ilk cycle cycle_start_equity orchestrator/start'ta veya ilk grid fill'de set edilebilir (kod path'e bakılmalı).

---

## 37. GRID REFERENCE (BÜYÜME)

- grid_reference_quote, grid_reference_base: cycle_reset_after_fill'da current_equity ve base_bal ile set edilir. _sell_qty_for_grid: ref_base = state.grid_reference_base or base_balance; target_budgets varsa cap_base = (target_base_usdt/price)*(1-buffer); ref_base = min(ref_base, cap_base); return min(ref_base * sell_qty_pct_of_base, base_balance). _buy_qty_for_grid: ref = grid_reference_quote or quote_balance; target_quote_usdt cap; return min(ref * qty_pct, quote_balance). Bileşik büyüme: her cycle sonrası referanslar equity ile büyür.

---

## 38. REPAIR / IDEMPOTENCY (FILL)

- Intent zaten FILLED: get_order_by_client_order_id; status FILLED; trades_for_order; apply_fill_to_state, cycle_ledger_add_fill, Ledger.record_trade, save_state; verified_filled=True => skip place order. Böylece aynı fill iki kez state'e işlenmez.

---

## 39. ÖZET SABİTLER TABLOSU

| Sabit | Değer | Kullanım |
|-------|--------|----------|
| buy_fee_rate | 0.001 | breakeven, trigger |
| sell_fee_rate | 0.001 | breakeven, trigger |
| min_net_profit_rate | 0.001 | trigger_price |
| available_quote_buffer_pct | 0.005 | BUY cap |
| initial_fee_buffer_pct | 0.002 | required = quote_qty*(1+buffer) |
| _BASE_QTY_EPSILON | 1e-10 | check_virtual_budget SELL |
| CYCLE_FILL_REASONS | 4 reason | cycle_ledger_add_fill |
| INVENTORY_REASONS | trail_sell_grid, trail_reentry_buy | dual PnL |
| CASH_REASONS | trail_buy_grid, trail_profit_sell | dual PnL |

---

## 40. BELGE VERSİYONU VE KAPSAM

- Strateji: dca_grid_trailing (strategy_id = "dca_grid_trailing"). Tek sembol; MULTI/TRDCA bu belgede hariç.
- Modüller: app.botengine.strategies.dca_grid_trailing, app.botengine.cycle_ledger, app.botengine.execution, app.botengine.virtual_wallet, app.services.pnl_service, app.utils.tz_utils, app.db.models (Trade, PnlSnapshot), app.bot.ledger, schema_guard account_daily_realized_pnl.
- Belge satır hedefi: ~500. İnsan okunabilirliği gerekmez; yapay zeka ve otomasyon referansıdır.

---

## 41. MOD DURUMLARI VE PnL ETKİSİ

- IDLE: initial_allocation_done True; grid tetikleri beklenir; realized_pnl_usdt_cycle mevcut tur için birikimli; cycle_ledger_current güncel.
- TRAIL_SELL_GRID: Yukarı grid satış tetiklendi; fill => SELL apply_fill; realized_pnl_usdt_cycle artar; cycle_ledger trail_sell_grid SELL eklenir.
- TRAIL_BUY_GRID: Aşağı grid alım tetiklendi; fill => BUY apply_fill; buy_history; cycle_ledger trail_buy_grid BUY.
- TRAIL_REENTRY_BUY: Fill => BUY; cycle_ledger trail_reentry_buy; FIFO inventory match; sonrası cycle_reset_after_fill => last_cycle_profit_usdt, cycle_id++, ledger sıfırlanır.
- TRAIL_PROFIT_SELL: Fill => SELL; cycle_ledger trail_profit_sell; FIFO cash match; cycle_reset_after_fill.
- initial_allocation_done False: Sadece initial_allocation action; fill sonrası state.reference_price, initial_alloc_base_qty set; buy_history'ye eklenmez; cycle_ledger'a eklenmez.

---

## 42. TAM SAYIÇ (FILL → STATE DEĞİŞİMİ)

SELL fill: base_balance -= qty; quote_balance += qty*price - fee; sell_history.append(entry); fees_paid_usdt_cycle += fee; cost = qty * avg_buy_price(state); realized_pnl_usdt_cycle += (qty*price - fee - cost). BUY fill (non-initial): base_balance += qty; quote_balance -= qty*price + fee; buy_history.append(entry); fees_paid_usdt_cycle += fee. BUY fill (initial_allocation): base_balance += qty; quote_balance -= qty*price + fee; fees_paid_usdt_cycle += fee; buy_history unchanged; initial_allocation_done = True (execution'da set).

---

## 43. ORCHESTRATOR BAKİYE SINIRI (initial_capital)

- Gerçek hesap: adapter.get_account_balances(); balances_free[a] = float(b.get("free")). initial = config.initial_capital_usdt. initial > 0: actual_total = sum(balances_free[a]*prices_tmp[a]); scale = initial/actual_total; balances_free[a] *= scale. Strateji tick'e iletilen base_balance/quote_balance bu scale'lenmiş değerler (orchestrator tarafında); execution ise gerçek Binance free kullanır (get_account_balances). Virtual wallet ve state fill sonrası gerçek fill miktarlarıyla güncellenir; orchestrator scale sadece "hangi bakiye ile strateji çalışsın" için.

---

## 44. DAILY REFERENCE GÜNCELLEME ZAMANLAMASI

- calculate_bot_pnl her çağrıldığında: state load; total_usd hesaplanır (vw veya trades); today_date = turkey_today_start_utc().strftime("%Y-%m-%d"). state.daily_ref_date != today_date => state["daily_ref_usd"] = total_usd; state["daily_ref_date"] = today_date; save_state. Böylece günün ilk isteği veya gece yarısı sonrası ilk istekte referans güncellenir. Aynı gün içinde daily_ref_usd değişmez; daily = total_usd - daily_ref_usd her seferinde güncel total_usd ile hesaplanır.

---

## 45. AYLIK KAR HESABI ALTERNATİFLERİ

- PnlService return monthly: monthly_snap = PnlSnapshot filter ts>=month_start order ts asc first. monthly = total_usd - monthly_snap.total_usd if monthly_snap else total_usd - initial_total. Yani ayın ilk snapshot'ı yoksa baseline initial_capital. Snapshot'lar save_snapshot ile yazılır (çağrıldığı yerler ayrı; periyodik veya event-driven).

---

## 46. cycle_ledger_from_state SEMANTİĞİ

- state.cycle_ledger_current dict ve ledger.symbol == symbol => return ledger. Değilse build_cycle_ledger_empty(state.cycle_id, symbol) döner (state mutate edilmez). Execution'da fill sonrası state.cycle_ledger_current atanır; cycle_reset'te yeni empty ledger atanır.

---

## 47. FEE ASSET VE QUOTE DÖNÜŞÜMÜ

- cycle_ledger_add_fill: fee_asset != USDT ise log warning; fee_quote = fee (caller'ın USDT'ye çevirmesi beklenir). Tüm ledger realized_pnl_quote ve dual PnL USDT cinsinden. apply_fill_to_state fee_val doğrudan quote (USDT) olarak kullanılır; fees_paid_usdt_cycle, realized_pnl_usdt_cycle USDT.

---

## 48. INITIAL_ALLOCATION COST BASIS (basis_mode=total)

- _avg_buy_price_total: initial_alloc_base_qty * initial_alloc_price + sum(buy_history qty*price); payda initial_alloc_base_qty + sum(buy_history qty). initial_allocation buy_history'de olmadığı için payda = init_q + grid_q; pay = init_q*init_p + grid_v. Profit exit legacy total modunda bu ortalama kullanılır; cycle_only_fee_aware_v1 cycle ledger avg_cost_quote_per_base kullanır (sadece cycle fill'leri).

---

## 49. PERFORMANS HAVUZU SORGULARI (Haftalık / Aylık / Genel)

- consolidate_date(account_id, date_tr): O tarih için account_daily_realized_pnl güncellenir. Haftalık: date_tr aralığındaki her gün için get_account_daily_realized_cache toplamı. Aylık: ay içi date_tr'ler toplamı. Genel: tüm tarihler toplamı veya consolidate_date ile birleştirilmiş cache. PnlService.get_account_daily_realized_cache(db, account_id, date_tr) tek gün okuma.

---

## 50. ÖZET: TEK BOT total_usd KAYNAK ÖNCELİĞİ

1) virtual_wallet row var => total_usd = virtual_base * current_price + virtual_quote. 2) initial_allocation_done False ve initial_capital > 0 (tek sembol) => total_usd = initial_capital. 3) virtual_wallet yok, Trade var => FIFO trades; total_usd = quote_qty + base_qty*current_price. 4) Trade yok => total_usd = 0 (veya MULTI/fallback). daily = total_usd - state.daily_ref_usd; monthly = total_usd - monthly_snap_or_initial.

---

## 51. STATE ANAHTARLARI TAM LİSTE (PnL / Bakiye)

base_balance, quote_balance, initial_allocation_done, reference_price, initial_alloc_base_qty, initial_alloc_price, mode, cycle_id, sell_history, buy_history, realized_pnl_usdt_cycle, fees_paid_usdt_cycle, cycle_start_equity, last_cycle_profit_usdt, grid_reference_quote, grid_reference_base, sell_grid_fired, sell_grid_trigger_price, sell_grid_peak_price, sell_grid_fill_price, buy_grid_fired, buy_grid_trigger_price, buy_grid_trough_price, buy_grid_fill_price, trail_anchor_price, trail_activation_price, _trail_sell_grid_index, _trail_buy_grid_index, _reentry_done, _profit_exit_done, _cycle_complete, cycle_ledger_current, daily_ref_usd, daily_ref_date, last_fill_snapshot, free_quote, locked_quote, cycle_pnls (opsiyonel), target_budgets (opsiyonel), state_version.

---

## 52. BOTS_ENGINE DETAY RESPONSE (PnL ALANLARI)

current_usd (pnl_data.total_usd), daily_usd (pnl_data.daily), daily_pnl_pct, initial_capital (config), grid_points, profit_points, reference_display, config_budget_usd, state (base_balance, quote_balance, cycle_id, ...). MULTI/TRDCA: base_value_usd, quote_balance_usd, live_total, effective_balances_map, initial_capital scale.

---

## 53. DASHBOARD SNAPSHOT BOT ÖĞESİ

bot_id, symbol, status, current_usd (PnLService total_usd), initial_usd (config), daily_pnl_pct, total_pnl_usd (current - initial), daily_bot (current - ref), ref_usd (state daily_ref veya benzeri). fetch_bots_and_account_kpis içinde her bot için calculate_bot_pnl; total_bot_equity_usd += current_usd.

---

## 54. CHECK_VIRTUAL_BUDGET DÖNÜŞÜ

(ok: bool, reason: str, required: float|None, available: float|None). ok True => (True, "", None, None). BUY yetersiz => (False, "INSUFFICIENT_VIRTUAL_FUNDS", quote_amount, available_quote). SELL yetersiz => (False, "INSUFFICIENT_VIRTUAL_FUNDS", base_qty, base). initial_allocation branch execution'da check_virtual_budget kullanılmaz; Binance quote_free ile required kıyaslanır; cap uygulanabilir.

---

## 55. build_cycle_ledger_empty DÖNÜŞ YAPISI (TÜM ANAHTARLAR)

cycle_id, symbol, base_asset, quote_asset, fills=[], buy_qty_total=0, buy_quote_total=0, buy_fee_total_quote=0, sell_qty_total=0, sell_quote_total=0, sell_fee_total_quote=0, avg_cost_quote_per_base=None, realized_pnl_quote=0, breakeven_price=None, matched_qty=0, started_at (ISO), inventory_coin_adv_qty=0, inventory_fees_usdt=0, cash_pnl_usdt=0, cash_fees_usdt=0. _cycle_ledger_recompute sonrası avg_cost_quote_per_base, realized_pnl_quote, matched_qty güncel; breakeven/trigger ayrı fonksiyonla hesaplanır.

---

## 56. PROFIT EXIT LEGACY THRESHOLD FORMÜLÜ

thr = avg_buy * (1 + profit_exit_rise_pct/100). avg_buy = _avg_buy_price_total(state) if basis_mode=="total" else _avg_buy_price_for_trigger(state). P >= thr => TRAIL_PROFIT_SELL. cycle_only_fee_aware_v1 kullanıldığında bu branch çalışmaz; trigger_price = breakeven * (1+min_net_profit_rate).

---

## 57. RE-ENTRY THRESHOLD

avg_sell = _avg_sell_price_for_trigger(state) (sell_history; execution_price varsa o). thr = avg_sell * (1 - profit_reentry_drop_pct/100). P <= thr => TRAIL_REENTRY_BUY. sell_history boşsa re-entry tetiklenmez.

---

## 58. _profit_exit_sell_qty VE _reentry_buy_qty

_profit_exit_sell_qty: total_q = sum(buy_history[].qty); return min(base_balance, total_q). Yani sadece grid alımları kadar satış; initial base dahil değil. _reentry_buy_qty: total = sum(sell_history[].qty * price); return min(quote_balance, total). Re-entry satış hasılatı kadar alım.

---

## 59. TUR BAZLI GERÇEKLEŞEN (FIFO) ALGORİTMA

Per cycle: base_qty=0, total_cost=0, realized=0. For trade in cycle_trades (ts asc): if BUY: base_qty += qty; total_cost += qty*price. if SELL: avg_buy = total_cost/base_qty; sell_qty = min(trade.qty, base_qty); realized += (trade.price - avg_buy)*sell_qty; base_qty -= sell_qty; total_cost -= avg_buy*sell_qty. Cycle realized toplamı bu realized. Günlük realized = sum(cycle realized for cycles where max(ts) in today).

---

## 60. FEE BUFFER VE CAP (EXECUTION)

initial_allocation: required = quote_qty*(1+fee_buffer_pct); available = quote_free; available < required => capped_quote = round(available/(1+fee_buffer_pct), 2); capped_quote >= min_notional => quote_qty = capped_quote, required = quote_qty*(1+fee_buffer_pct), EXECUTE. Diğer BUY: available_quote_for_orders = free_quote*(1-buffer_pct); quote_qty > available_quote => quote_qty = round(available_quote, 2); min_notional kontrol.

---

## 61. KAPSAM ÖZETİ

Trailing DCA bot: tek sembol; initial_allocation → grid sell/buy → re-entry veya profit exit → cycle_reset. Kar: state realized_pnl_usdt_cycle (tur içi); cycle_ledger realized_pnl_quote ve dual (inventory/cash); last_cycle_profit_usdt (equity farkı); Trade tablosu FIFO ile günlük/aylık realized; total_usd = vw veya trades fallback; daily = total_usd - daily_ref_usd; monthly = total_usd - snapshot veya initial. Tüm zamanlar Türkiye 00:00 referanslı.

---

Belge sonu. Tüm referanslar app/botengine (strategies/dca_grid_trailing, cycle_ledger, execution, virtual_wallet), app/services/pnl_service, app/utils/tz_utils, app/db/models, app/bot/ledger ve TRADE_TRAILING_MASTER_SPEC ile uyumludur. Tüm referanslar app/botengine (strategies/dca_grid_trailing, cycle_ledger, execution, virtual_wallet), app/services/pnl_service, app/utils/tz_utils, app/db/models, app/bot/ledger ve TRADE_TRAILING_MASTER_SPEC ile uyumludur.
