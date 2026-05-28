# AI_GRID_ENGINE_REFERENCE.md

```yaml
doc_type: machine_reference
project: final1 / TraderTrailing
strategy_id: dca_grid_trailing
primary_modules:
  - app/botengine/strategies/dca_grid_trailing.py
  - app/botengine/strategies/grid_outage_recovery.py
  - app/botengine/grid_view.py
  - app/botengine/execution.py
  - app/botengine/cycle_ledger.py
  - app/botengine/state_store.py
  - app/botengine/health_watch.py
  - app/services/binance_connectivity.py
canonical_spec: TRADE_TRAILING_MASTER_SPEC.md  # §4270–4365 grid sections; conflict → spec wins
human_audience: false
ai_audience: true
last_sync_conversation: 2026-05-28
includes_updates:
  - cycle_grid_side tur yön kilidi
  - parallel multi-grid same tick + reservation
  - grid_outage_recovery 5 scenarios
  - binance_connectivity → bot_engine_events + HEALTH_CRITICAL
  - bot UI health alerts (botHealthAlerts.js trust /health)
```

---

## 0. EXECUTION TOPOLOGY

```
[Binance REST/WS] ←→ [binance_spot.py / data_hub / price_hub]
         ↑
[FastAPI web] wallet/spot_engine ──note_binance_failure──┐
         ↑                                                  │
[Worker process] orchestrator._bot_loop                     │
    │ load_state(bot_id)                                    │
    │ adapter.get_price(symbol) → P | None (skip tick)      │
    │ virtual_wallet sync base/quote                        │
    │ strategy.tick(state, cfg, P, base, quote)           │
    │   → tick_dca_grid_trailing                            │
    │       should_apply_outage_recovery? apply_*           │
    │       → actions[]                                     │
    │ execution.run_actions(actions)                        │
    │   → BinanceAdapter.place_order                        │
    │   → apply_fill_to_state / cycle_reset_after_fill      │
    │ save_state + flush_queued_events                      │
    │ state.last_tick_at = utcnow                           │
    └ health_watch.run_all_bot_health_checks (worker ~60s)  │
         evaluate_bot_health + active_failure(account) ←────┘
[DB] bot_engine_state.state_json | bot_engine_events | bots.status
[UI] GET /api/bots-engine/{id}/events | /health | /live
     EngineLogLive.js poll | BotHealthAlerts.js banner/blink
```

**Tick skip conditions (no strategy run, no last_tick_at advance in price-missing branch):**
- `P is None or P <= 0` from adapter
- orchestrator continues sleep without trading

**Order placement skip conditions:**
- `state.backoff_until > now` (401 backoff 300s)
- kill_switch active
- idempotency hit (`action_key = f"{reason}_{grid_index}_{client_order_id}"`)
- MIN_NOTIONAL guard fail → SKIP_REASON queued, no place

---

## 1. CONFIG SCHEMA (`DcaGridTrailingConfig`)

Parsed from `bot.config_json` via `DcaGridTrailingConfig.from_dict`.

| field | type | default | usage |
|-------|------|---------|-------|
| `symbol` | str | required | e.g. ETHUSDT |
| `initial_capital_usdt` / `budget_usd` / `bot_budget_quote` | float | — | budget cap |
| `sell_grids[]` | list[dict] | [] | each: `sell_grid_pct` or `trigger_pct`; `sell_qty_pct_of_base` or `qty_pct` |
| `buy_grids[]` | list[dict] | [] | each: `buy_grid_pct` or `trigger_pct`; `buy_qty_pct_of_quote` or `qty_pct` |
| `sell_trigger_trailing_pct` | float | 0.3 | sell exec: `peak * (1 - pct/100)` |
| `buy_trigger_trailing_pct` | float | 0.3 | buy exec: `trough * (1 + pct/100)` |
| `profit_reentry_drop_pct` | float | 1.0 | arm TRAIL_REENTRY_BUY |
| `profit_reentry_rise_pct` | float | 0.3 | reentry exec rise from anchor |
| `profit_exit_rise_pct` | float | 1.0 | arm TRAIL_PROFIT_SELL (legacy) |
| `profit_exit_drop_pct` | float | 0.3 | profit trail drop from anchor |
| `basis_mode` | str | `grid_only` | `total` \| `grid_only` — avg buy for legacy profit arm |
| `pnl_mode` | str | — | `cycle_only_fee_aware_v1` → cycle_ledger breakeven/trigger |
| `buy_fee_rate`, `sell_fee_rate` | float | 0.001 | ledger math |
| `min_net_profit_rate` | float | 0.001 | min profit above breakeven |
| `min_notional_guard` | float | 5.0 | Binance min notional; preflight 10 USDT grid rule |
| `available_quote_buffer_pct` | float | 0.005 | target_budgets cap buffer |
| `tick_interval_ms` | int | 2000 | wake interval; outage threshold input |
| `quote_alloc_pct`, `base_alloc_pct` | float | 50 | IA split + quote pool |
| `strategy_id` | str | `dca_grid_trailing` | registry key |

**Grid level index:** `i ∈ [0, n-1]` sell, `j ∈ [0, m-1]` buy. Arrays in state sized to `n`, `m`.

---

## 2. STATE SCHEMA (`state_json` keys)

### 2.1 Cycle / reference

| key | type | semantics |
|-----|------|-----------|
| `cycle_id` | int | starts 1; ++ on cycle close |
| `reference_price` | float | tur tetik referansı `ref`; reset to close fill price |
| `cycle_grid_side` | null \| `"SELL"` \| `"BUY"` | tur yön kilidi; see §8 |
| `cycle_start_equity` | float | quote + base×P at cycle start |
| `grid_reference_base` | float | sell qty denominator (fixed per cycle) |
| `grid_reference_quote` | float | buy qty denominator |
| `target_budgets` | dict | `{equity_usdt, target_quote_usdt, target_base_usdt, ts}` caps |
| `initial_allocation_done` | bool | set ONLY in execution after real IA fill |
| `initial_alloc_base_qty`, `initial_alloc_price` | float | IA fill; NOT in buy_history |
| `mode` | str | BotEngineMode value; legacy + cycle-level trails |

### 2.2 Per-grid parallel arrays (len = n or m)

| key | element | set by |
|-----|---------|--------|
| `sell_grid_fired[i]` | bool | execution on fill |
| `sell_grid_trigger_price[i]` | float\|null | threshold `s_i = ref*(1+pct/100)` NOT live P |
| `sell_grid_peak_price[i]` | float\|null | live peak while trailing |
| `sell_grid_fill_price[i]` | float\|null | Binance fill (UI freeze) |
| `buy_grid_fired[j]` | bool | execution |
| `buy_grid_trigger_price[j]` | float\|null | threshold `b_j = ref*(1-pct/100)` |
| `buy_grid_trough_price[j]` | float\|null | live trough |
| `buy_grid_fill_price[j]` | float\|null | fill price |

Init: `_ensure_sell_buy_lists(state, cfg)`.

### 2.3 History

| key | structure |
|-----|-----------|
| `sell_history` | `[{grid_index, qty, price, execution_price?}]` |
| `buy_history` | same; `grid_index=None` for reentry/profit close fills excluded from grid avg |
| `realized_pnl_usdt_cycle`, `fees_paid_usdt_cycle` | legacy cycle PnL in apply_fill |
| `cycle_ledger_current` | fee-aware ledger object |
| `cycle_pnls`, `completed_cycle_dual_pnls` | closed cycle archives |

### 2.4 Cycle-level trailing flags

| key | role |
|-----|------|
| `trail_anchor_price` | reentry/profit anchor |
| `_trail_sell_grid_index`, `_trail_buy_grid_index` | legacy lowest active index |
| `_reentry_done`, `_profit_exit_done`, `_cycle_complete` | cycle close guards |
| `_reentry_avg_sell`, `_reentry_max_buy_price` | reentry hold ceiling |
| `_profit_exit_breakeven`, `_profit_exit_trigger_price` | profit hold floor |

### 2.5 Outage ephemeral (single tick)

| key | cleared |
|-----|---------|
| `_outage_favorable_buy` | int[] indices → force BUY exec path |
| `_outage_favorable_sell` | int[] → force SELL exec |
| `_outage_force_profit_sell` | bool → bypass profit trail drop |
| `_outage_force_reentry_buy` | bool → bypass reentry rise + max_buy |
| `_outage_recovery_at` | ISO timestamp after recovery run |

Pop favorable lists mid-tick after trail loops; force flags on execute.

### 2.6 Runtime / health

| key | role |
|-----|------|
| `last_tick_at` | datetime \| ISO; outage gap + TICK_STALE health |
| `last_error_code` | e.g. API_UNAUTHORIZED, BINANCE_UNREACHABLE |
| `health_error_since`, `health_ack_at` | health/ack reset |
| `backoff_until` | unix ts; 401 skip orders 300s |
| `base_balance`, `quote_balance` | virtual wallet |
| `_pending_engine_events` | queue → flush post-tick max 24 |
| `bot_id` | injected for logging |

---

## 3. MODE FSM (`BotEngineMode`)

```
IDLE
  ├─(sell trigger hit)─→ per-grid TRAIL via sell_grid_trigger_price set (mode may sync TRAIL_SELL_GRID)
  ├─(buy trigger hit)─→ per-grid TRAIL via buy_grid_trigger_price
  ├─(SELL side + sell_history + arm)─→ TRAIL_REENTRY_BUY
  └─(BUY side + basis + arm)─→ TRAIL_PROFIT_SELL

TRAIL_REENTRY_BUY ──fill trail_reentry_buy──→ IDLE + cycle_reset
TRAIL_PROFIT_SELL ──fill trail_profit_sell──→ IDLE + cycle_reset
Per-grid trails do NOT change mode to IDLE on exec; only cycle-level modes return early.
```

**`tick_dca_grid_trailing` evaluation order (strict early-return segments):**

1. `_ensure_sell_buy_lists`; `_heal_cycle_grid_side`
2. Invalid P → `return [], tick_interval_ms/1000`
3. IA self-heal (reference, initial_alloc_base_qty)
4. **Outage:** `should_apply_outage_recovery` → `apply_grid_outage_recovery`
5. Load `_outage_*`, `mode`, `n=len(sell_grids)`, `m=len(buy_grids)`
6. **Initial allocation:** if `not initial_allocation_done` → single BUY `reason=initial_allocation`; **return** (no grid)
7. **if mode==TRAIL_REENTRY_BUY:** update anchor, exec/hold/force → maybe BUY action; **return**
8. **if mode==TRAIL_PROFIT_SELL:** update anchor, exec/hold/force → maybe SELL action; **return**
9. Heal ref; set grid_reference_* / cycle_start_equity if missing
10. **Parallel active sell trails** (all idx with trigger set, not fired): peak update, exec, reserve base
11. **Parallel active buy trails:** trough update, exec, reserve quote
12. `pop _outage_favorable_buy/sell` from state (lists consumed)
13. **New sell triggers:** for each i: `s_i = ref*(1+sell_pct/100)`; `_try_trigger_sell_grid`
14. **New buy triggers:** for each j: `b_j = ref*(1-buy_pct/100)`; `_try_trigger_buy_grid`
15. `_sync_trailing_mode` (legacy mode flag)
16. **Arm reentry** if `cycle_side=="SELL"` and sell_history and not `_reentry_done` → may set TRAIL_REENTRY_BUY; **return**
17. **Arm profit** if `cycle_side=="BUY"` and has_basis and not `_profit_exit_done` → TRAIL_PROFIT_SELL; **return**
18. `return actions, next_wake`

---

## 4. GRID MATHEMATICS

### 4.1 Reference and thresholds

```
ref = state.reference_price  (healed from P if null/<=0)
sell_grid_i threshold:  s_i = ref * (1 + sell_grid_pct_i / 100)
buy_grid_j threshold:   b_j = ref * (1 - buy_grid_pct_j / 100)
```

**Trigger condition (new activation):**
- Sell grid i: `P >= s_i` (price at or above upward level)
- Buy grid j: `P <= b_j` (price at or below downward level)

**On trigger tick:**
- `sell_grid_trigger_price[i] = s_i` (stores threshold, NOT tick price)
- `sell_grid_peak_price[i] = P` (live peak at trigger)
- `buy_grid_trigger_price[j] = b_j`
- `buy_grid_trough_price[j] = P`

### 4.2 Trailing execution thresholds

```
sell_exec_i = sell_grid_peak_price[i] * (1 - sell_trigger_trailing_pct / 100)
buy_exec_j  = buy_grid_trough_price[j] * (1 + buy_trigger_trailing_pct / 100)
```

**Execute place when:**
- Sell: `P <= sell_exec_i` OR `i in _outage_favorable_sell`
- Buy: `P >= buy_exec_j` OR `j in _outage_favorable_buy`

**While trailing (each tick before exec):**
- `peak[i] = max(peak[i], P)`
- `trough[j] = min(trough[j], P)`

### 4.3 Quantity sizing

**Sell qty grid i:**
```
planned = grid_reference_base * sell_qty_pct_of_base[i]
avail   = base_balance - base_reserved
qty     = min(planned, avail)
cap via target_budgets.target_base_usdt / P * (1 - buffer) if set
```

**Buy quote grid j:**
```
pool    = _quote_ref_for_buy_grid(state, cfg, quote_balance)  # grid_reference_quote or equity*quote_alloc
planned = pool * buy_qty_pct_of_quote[j]
avail   = quote_balance - quote_reserved
quote_q = min(planned, avail)
```

**Invariant:** `grid_reference_base` / `grid_reference_quote` are **cycle-fixed**; partial fills do NOT shrink planned qty for unfired grids (test: `test_planned_sell_qty_uses_reference_base_not_remaining_balance`).

### 4.4 Reservation (parallel same tick)

```
base_reserved  = 0.0
quote_reserved = 0.0
for each sell action appended: base_reserved += qty
for each buy action appended:  quote_reserved += quote_qty
```

Prevents double-spend when multiple grids execute same tick.

---

## 5. BUY GRID SCENARIO CATALOG

### B0 — Precondition: `initial_allocation_done == True`

Without IA, tick returns IA action only; no grid logic.

### B1 — IDLE, no trigger, P above buy threshold

```
P > b_j  →  no trigger; buy_grid_trigger_price[j] remains null
```

### B2 — First trigger (single grid)

```
P <= b_j, not fired, trigger null
→ _try_trigger_buy_grid: trigger=b_j, trough=P
→ log BOT_GRID_BUY_TRIGGER
→ no place yet (wait trail rise)
```

### B3 — Trailing to execution

```
trigger set, peak/trough active
each tick: trough = min(trough, P)
when P >= trough * (1 + buy_trail_pct/100):
  → place BUY reason=trail_buy_grid grid_index=j
  → quote_qty from _buy_qty_for_grid with reservation
```

### B4 — Fill consequences

```
execution.run_actions:
  buy_grid_fired[j] = True
  buy_grid_fill_price[j] = fill_price
  freeze buy_grid_trough_price from action.trail_anchor_price

apply_fill_to_state (reason=trail_buy_grid):
  buy_history.append({grid_index:j, qty, price, execution_price})
  _lock_cycle_grid_side(state, "BUY")  # first fill only
  base_balance += qty; quote_balance -= cost+fee
```

### B5 — Parallel multi-buy same tick

```
Multiple j where P <= b_j simultaneously:
  each _try_trigger_buy_grid → same trough=P at trigger tick
  each trails independently but may share same initial trough
  exec same tick if all P >= respective exec_thr:
    quote_reserved accumulates; sum(quote_q) <= quote_balance
test: test_two_buy_grids_parallel_execute_different_quote
test: test_two_buy_grids_trigger_same_trough_and_exec
```

### B6 — cycle_grid_side == SELL (locked)

```
_buy_grids_enabled → False
_try_trigger_buy_grid not called (buy_enabled gate)
existing buy triggers cleared on lock at fill time
reentry TRAIL_REENTRY_BUY still allowed (kar alım)
test: test_after_sell_lock_buy_grid_does_not_trigger
```

### B7 — MIN_NOTIONAL skip

```
_meets_min_notional(config, "BUY", P, quote_qty=q) == False
→ _queue_grid_skip → SKIP_REASON MIN_NOTIONAL
→ no action; grid remains triggered/trailing
```

### B8 — Outage scenarios (buy side)

See §9. Mapped to `_recover_buy_grid`, `_recover_waiting_buy_grid`.

---

## 6. SELL GRID SCENARIO CATALOG

### S1 — IDLE, P below sell threshold

```
P < s_i → no trigger
```

### S2 — First trigger

```
P >= s_i, not fired, trigger null
→ _try_trigger_sell_grid: trigger=s_i, peak=P
→ if grid_reference_base<=0 and base_balance>0: set grid_reference_base
```

### S3 — Trailing to execution

```
each tick: peak = max(peak, P)
when P <= peak * (1 - sell_trail_pct/100):
  → place SELL reason=trail_sell_grid grid_index=i
  → qty from _sell_qty_for_grid with base_reserved
```

### S4 — Fill consequences

```
sell_grid_fired[i] = True
apply_fill_to_state reason=trail_sell_grid:
  sell_history.append(...)
  _lock_cycle_grid_side(state, "SELL")
  realized_pnl vs _avg_buy_price
```

### S5 — Parallel multi-sell

```
Independent peaks/triggers per i
base_reserved prevents over-sell
test: test_parallel_sell_grids_trigger_independently
  grid1 trailing while grid2 triggers at higher P
```

### S6 — cycle_grid_side == BUY (locked)

```
_sell_grids_enabled → False
profit TRAIL_PROFIT_SELL allowed
```

### S7 — Outage (sell side)

See §9 `_recover_sell_grid`.

---

## 7. INITIAL ALLOCATION (IA)

```
IF NOT initial_allocation_done:
  c = initial_capital_usdt
  c_base = c * base_alloc_pct / 100   # quote spent on base
  actions = [{ type: place, side: BUY, quote_qty: c_base, reason: initial_allocation }]
  RETURN early — strategy does NOT set initial_allocation_done
execution on fill:
  state.initial_allocation_done = True
  state.initial_alloc_base_qty, initial_alloc_price set
  NOT appended to buy_history (by design — profit exit qty excludes IA)
cycle close sells only grid buy_history qty (_profit_exit_sell_qty)
```

---

## 8. `cycle_grid_side` LOCK (tur yön kilidi)

### 8.1 Functions

| fn | file | behavior |
|----|------|----------|
| `get_cycle_grid_side(state)` | dca_grid_trailing | null \| SELL \| BUY |
| `_sell_grids_enabled` | | `side != "BUY"` |
| `_buy_grids_enabled` | | `side != "SELL"` |
| `_lock_cycle_grid_side(state, side)` | | first fill only; clears opposite pending triggers |
| `_heal_cycle_grid_side(state)` | | migrate old bots from fired/history |

### 8.2 Lock trigger

**ONLY on successful fill** in `apply_fill_to_state`:
- `reason == "trail_sell_grid"` → lock SELL
- `reason == "trail_buy_grid"` → lock BUY
- Trigger alone does NOT lock (test: bidi before first fill)

### 8.3 Lock side effects

**SELL lock:**
- Clear unfired `buy_grid_trigger_price[j]`, `buy_grid_trough_price[j]`
- Sell grids + TRAIL_REENTRY_BUY enabled
- Buy grids disabled

**BUY lock:**
- Clear unfired sell triggers/peaks
- Buy grids + TRAIL_PROFIT_SELL enabled

### 8.4 Cycle reset

`cycle_reset_after_fill` → `pop cycle_grid_side`; new cycle both directions until first fill.

### 8.5 UI (`grid_view.compute_grid_profit_view`)

```
enabled[i]  = side_enabled OR sell_grid_fired[i]
disabled[i] = NOT side_enabled AND NOT fired
meta.cycle_grid_side, cycle_side_pending = (side is None)
profit_points visible only when side matches (reentry vs profit_exit)
```

---

## 9. OUTAGE RECOVERY (`grid_outage_recovery.py`)

### 9.1 Gate

```python
gap = seconds_since_last_tick(state)  # from last_tick_at
threshold = max(30.0, tick_interval_sec * 3.0)
tick_interval_sec = max(1.0, tick_interval_ms / 1000)
apply if gap >= threshold AND initial_allocation_done AND valid P
```

Entry: `apply_grid_outage_recovery(state, config, P, bot_id)` — clears prior outage flags first.

### 9.2 Five spec scenarios

| ID | name | buy-side condition (trigger=b_j, exec=trough*(1+trail%)) | action |
|----|------|----------------------------------------------------------|--------|
| 1 | gray_zone | no trigger ever set; P between bands | no change |
| 2 | favorable_exec | triggered, not fired; P < exec (price fell below buy exec) | `_outage_favorable_buy.append(j)` |
| 2s | favorable_exec sell | triggered; P > exec (price above sell exec) | `_outage_favorable_sell.append(i)` |
| 3 | missed_reverse buy | triggered; P >= exec AND P <= trigger | REANCHOR_TROUGH: trough=P |
| 3s | missed_reverse sell | triggered; P <= exec AND P >= trigger | REANCHOR_PEAK: peak=P |
| 4 | grid_missed buy | triggered; P > trigger (price recovered above buy line) | `_reset_buy_grid_trigger` |
| 4s | grid_missed sell | triggered; P < trigger | `_reset_sell_grid_trigger` |
| 5 | partial_cycle | mix of open grids + TRAIL_PROFIT/REENTRY | per-component rules above |

### 9.3 Offline waiting grids (no trigger before gap)

```
_recover_waiting_buy_grid: if P <= b_j → _try_trigger_buy_grid; if immediate exec would fire → favorable
_recover_waiting_sell_grid: symmetric
```

### 9.4 Cycle-level outage

**Profit:** `_recover_profit_exit` — re-anchor `trail_anchor_price=max(old,P)`; set `_outage_force_profit_sell` if missed drop or new high scenario.

**Reentry:** `_recover_reentry_buy` — `anchor=min(old,P)`; respect `_reentry_max_buy_price`; force on missed rise.

### 9.5 Integration tick flow

Outage runs **before** normal trail/trigger loops. Favorable indices consumed in those loops same tick. Flags popped after use.

---

## 10. TRAIL_REENTRY_BUY (kar alım — SELL tur kapanışı)

**Preconditions:**
- `cycle_grid_side == "SELL"` (after sell grid fill(s))
- `sell_history` non-empty
- `not _reentry_done`

**Arm (end of tick, step 16):**
```
fee-aware: cycle_ledger_reentry_arm_price, cycle_ledger_reentry_max_buy_price
legacy: arm = avg_sell * (1 - profit_reentry_drop_pct/100)
        max_buy = avg_sell * (1 - sell_fee) / (1 + buy_fee)
arm when P <= arm_price → mode=TRAIL_REENTRY_BUY, trail_anchor_price=P
```

**Execute (step 7, early return):**
```
anchor = min(anchor, P)
thr = anchor * (1 + profit_reentry_rise_pct/100)
BUY if P >= thr OR _outage_force_reentry_buy
HOLD if P > _reentry_max_buy_price (without force) → log BOT_REENTRY_HOLD
qty = _reentry_buy_qty = min(quote_balance, sum(sell qty*price))
reason = trail_reentry_buy
```

**Close:** `cycle_reset_after_fill`; `pnl_primary_mode=INVENTORY_QTY_V1`; dual PnL inventory path.

**test:** `test_reentry_only_after_sell_grid_fill` — no arm without sell fill.

---

## 11. TRAIL_PROFIT_SELL (kar satış — BUY tur kapanışı)

**Preconditions:**
- `cycle_grid_side == "BUY"`
- `has_basis` = buy_history OR (initial_alloc done — arm only; qty excludes IA)
- `not _profit_exit_done`

**Arm (step 17):**
```
IF pnl_mode == cycle_only_fee_aware_v1:
  ledger = cycle_ledger_with_basis(state, config)
  breakeven = cycle_ledger_breakeven_price(ledger)
  trigger = cycle_ledger_trigger_price(ledger, min_net_profit_rate, fees, profit_exit_rise_pct)
  arm when P >= trigger; store _profit_exit_breakeven, _profit_exit_trigger_price
ELSE legacy:
  avg = _avg_buy_price_total if basis_mode==total else _avg_buy_price_for_trigger
  thr = avg * (1 + profit_exit_rise_pct/100)
```

**Execute (step 8):**
```
anchor = max(anchor, P)
thr = anchor * (1 - profit_exit_drop_pct/100)
thr = max(thr, _profit_exit_breakeven)  # never sell below breakeven
SELL if P <= thr OR _outage_force_profit_sell
HOLD if P < breakeven without force
qty = _profit_exit_sell_qty = min(base_balance, sum(buy_history qty))  # IA excluded
reason = trail_profit_sell
```

**Close:** `cycle_reset_after_fill`; `pnl_primary_mode=CASH_USDT_V1`.

**test:** `test_profit_exit_hold_below_breakeven` — armed then crash → no action.

---

## 12. `apply_fill_to_state` / `cycle_reset_after_fill`

### 12.1 apply_fill_to_state (strategy module)

| side | reason | effects |
|------|--------|---------|
| SELL | trail_sell_grid | sell_history, lock SELL, balances, realized_pnl |
| BUY | trail_buy_grid | buy_history, lock BUY |
| BUY | trail_reentry_buy | buy_history grid_index None; cycle close path |
| SELL | trail_profit_sell | sell_history; cycle close path |
| BUY | initial_allocation | balances only; NO buy_history |

### 12.2 cycle_reset_after_fill

Triggered from execution when `reason in CYCLE_FILL_REASONS`:
```python
CYCLE_FILL_REASONS = {trail_buy_grid, trail_sell_grid, trail_reentry_buy, trail_profit_sell}
# initial_allocation NOT included
```

Reset actions:
- Archive grid fills, close trades, ledger
- `cycle_id += 1`
- `reference_price = fill_price` (new tur ref)
- Reset all grid arrays to empty/false
- Clear histories, pop cycle_grid_side, reentry/profit flags
- Recompute grid_reference_quote/base from post-close balances
- New empty cycle_ledger_current

---

## 13. EXECUTION LAYER (`execution.py`)

### 13.1 run_actions pipeline

```
for action in actions:
  guard backoff / kill / idempotency
  balance pre-check (Binance get_wallet via adapter)
  adapter.place_order(...)
  on fill: apply_fill_to_state + cycle_ledger_add_fill
  if reason in CYCLE_FILL_REASONS: cycle_reset_after_fill
  set grid fired flags + fill prices on state arrays
  append_event ORDER_FILLED / ERROR / SKIP_REASON
```

### 13.2 Error handling matrix

| condition | bot.status | last_error_code | backoff | event |
|-----------|------------|-----------------|---------|-------|
| 401 Unauthorized | paused_error | API_UNAUTHORIZED | 300s | ERROR throttled 600s |
| insufficient balance | paused_insufficient_balance | INSUFFICIENT_BALANCE | 60s | — |
| BINANCE unreachable (web) | running/paused | BINANCE_UNREACHABLE | — | via binance_connectivity |
| MIN_NOTIONAL | running | — | — | SKIP_REASON |

### 13.3 Idempotency

```
client_order_id = _action_id(state, reason_suffix, grid_index)
origClientOrderId pattern: bot{id}_r{run_id}_cy{cycle}_it{hash16}
hash16 = SHA256(symbol|side|qty|quote_qty|reason|grid_index)[:16]
```

---

## 14. CYCLE LEDGER / DUAL PNL

**Inventory path:** sell grids + reentry buy close → `inventory_coin_adv_qty`

**Cash path:** buy grids + profit sell close → `cash_pnl_usdt`

**Ledger functions (cycle_ledger.py):**
- `cycle_ledger_with_basis` — merges IA if basis_mode total
- `cycle_ledger_breakeven_price`
- `cycle_ledger_trigger_price(min_net_profit_rate, fees, profit_rise_pct)`
- `cycle_ledger_reentry_arm_price`, `cycle_ledger_reentry_max_buy_price`

**close_reason → primary mode:**
- `trail_profit_sell` → CASH_USDT_V1
- `trail_reentry_buy` → INVENTORY_QTY_V1

---

## 15. GRID VIEW API (`grid_view.py`)

**Entry:** `compute_grid_profit_view(state, config, price) → (grid_points, profit_points, meta)`

**grid_points[] fields:**
```yaml
type: sell|buy
i: index
trigger_price: ref * pct formula
fired: bool
trigger_hit_price: sell_grid_trigger_price[i] or buy equivalent
anchor: live peak/trough OR frozen if fired
execution_price: computed exec threshold OR fill
active: trailing now
enabled: side_enabled OR fired
disabled: NOT enabled side AND NOT fired
qty_pct, planned_base_qty, planned_usd
```

**meta:**
```yaml
ref_display, ref_available, cycle_grid_side, cycle_side_pending
avg_sell_grid, avg_buy_grid  # qty-weighted from histories
quote_pool_usd
```

**Endpoint:** `GET /api/bots-engine/{id}` embeds grid via bots_engine detail builder.

---

## 16. HEALTH / BINANCE CONNECTIVITY / UI ALERTS

### 16.1 binance_connectivity.py

```
note_binance_failure(account_id, error_code, message, source)
  → in-memory TTL 180s
  → async thread: for bots status in (running, paused_error, paused_insufficient_balance):
       append_event ERROR + HEALTH_CRITICAL (health_code=BINANCE_UNREACHABLE)
       state.last_error_code = error_code
       throttle 120s per bot_id

note_binance_success(account_id) → clear failure

Sources hooked: routes.py wallet upstream fail, spot_engine balance fail
```

### 16.2 health_watch.py

```
evaluate_bot_health(bot, state, db):
  TICK_STALE_WARN if tick_age >= max(20, interval*2.5)
  TICK_STALE_CRIT if tick_age >= max(60, interval*5)
  STATE_ERROR if last_error_code in _CRITICAL_ERROR_CODES (incl API_UNAUTHORIZED, BINANCE_UNREACHABLE)
  active_failure(account_id) → BINANCE_UNREACHABLE alert
  emit_health_alerts throttled: WARN 300s, CRIT 120s per code
```

### 16.3 Bot UI (bot.html + assets)

```
EngineLogLive.js:
  poll GET /api/bots-engine/{id}/events?after_id=&limit=
  merge max 500 events; full refresh 90s; poll error → fetchBotHealth

BotHealthAlerts.js:
  GET /health alerts trusted directly (no HEALTH_* log evidence required)
  Resetle dismiss until re-fire or persistent /health condition
  syncDom: hero-alert-blink on critical/warn OR _botLiveProblem (stale tick/API)
  panel-health-critical / panel-health-warn CSS

botShowAsError:
  API_UNAUTHORIZED | ACCOUNT_KEYS_MISSING | BINANCE_UNREACHABLE
  stale tick >30s | equity_unavailable
```

**Important separation:**
- Manager `err-web` = application logs (spot_engine, wallet)
- Bot `#engineLogList` = `bot_engine_events` table only
- binance_connectivity bridges web failures → bot events

---

## 17. ACTION PAYLOAD SCHEMA

```python
{
  "type": "place",
  "side": "BUY" | "SELL",
  "symbol": str,
  "quantity": float,      # SELL only
  "quote_qty": float,     # BUY only
  "client_order_id": str,
  "reason": (
    "initial_allocation" |
    "trail_sell_grid" |
    "trail_buy_grid" |
    "trail_reentry_buy" |
    "trail_profit_sell"
  ),
  "grid_index": int | None,
  "trigger_price": float,       # live P at decision
  "execution_price": float,     # exec_thr
  "trail_anchor_price": float,  # peak or trough at decision
}
```

---

## 18. EVENT TYPES (bot_engine_events)

Logged types (`_LOGGED_EVENT_TYPES`):
```
ERROR, SKIP_REASON, ORDER_FILLED, ORDER_ATTEMPT, SLIPPAGE_WARN, LOCK_BUSY,
INFO, BOT_ACTION, CYCLE_END, CYCLE_START, HEALTH_WARN, HEALTH_CRITICAL
```

Grid-relevant:
- `ERROR` — API_UNAUTHORIZED, BINANCE_UNREACHABLE
- `SKIP_REASON` — MIN_NOTIONAL, ORDER_FAILED, etc.
- `HEALTH_CRITICAL` / `HEALTH_WARN` — health_code in meta
- `ORDER_FILLED` — after execution

Silent SKIP: `PRICE_STALE_OR_MISSING`, `IDEMPOTENT_LOCK`

---

## 19. TEST MATRIX (file → invariant)

| test file | case |
|-----------|------|
| test_grid_outage_recovery.py | gap threshold; gray zone; favorable buy/sell; reset; waiting offline trigger; profit force |
| test_cycle_grid_side.py | bidi before fill; lock clears opposite; buy blocked after SELL lock; reentry requires sell fill |
| test_parallel_grids.py | same trough trigger; parallel quote reservation; parallel sell trigger independence |
| test_binance_connectivity.py | failure TTL; success clears |
| test_cycle_ledger.py | profit breakeven hold; fee-aware trigger |

---

## 20. GLOBAL INVARIANTS (must hold)

1. `len(sell_grid_*) == len(config.sell_grids)` after `_ensure_sell_buy_lists`
2. First grid **fill** (not trigger) sets `cycle_grid_side`; persists until cycle_reset
3. `reference_price` changes only at cycle_reset (fill price) or IA heal — NOT outage reanchor
4. Outage reanchor adjusts peak/trough only, not `reference_price`
5. Parallel exec: `sum(sell qty) <= base_balance`, `sum(buy quote) <= quote_balance` via reservation
6. `initial_allocation` never in `buy_history`; profit exit qty excludes IA base
7. Cycle close reasons ⊆ CYCLE_FILL_REASONS; IA excluded
8. Opposite-side triggers cleared on lock only if not yet fired
9. TRAIL_REENTRY only when cycle_side SELL; TRAIL_PROFIT only when cycle_side BUY
10. MIN_NOTIONAL fail never places order; grid state remains triggered
11. 401 → paused_error + backoff; orders not attempted until backoff expires
12. Web Binance fail → binance_connectivity → bot ERROR/HEALTH_CRITICAL for account bots

---

## 21. FUNCTION INDEX

| function | module |
|----------|--------|
| `tick_dca_grid_trailing` | dca_grid_trailing.py |
| `_try_trigger_sell_grid`, `_try_trigger_buy_grid` | dca_grid_trailing.py |
| `_sell_qty_for_grid`, `_buy_qty_for_grid`, `_quote_ref_for_buy_grid` | dca_grid_trailing.py |
| `_lock_cycle_grid_side`, `_heal_cycle_grid_side`, `_sync_trailing_mode` | dca_grid_trailing.py |
| `_reentry_buy_qty`, `_profit_exit_sell_qty` | dca_grid_trailing.py |
| `apply_fill_to_state`, `cycle_reset_after_fill` | dca_grid_trailing.py |
| `should_apply_outage_recovery`, `apply_grid_outage_recovery`, `gap_threshold_sec` | grid_outage_recovery.py |
| `_recover_sell_grid`, `_recover_buy_grid`, `_recover_profit_exit`, `_recover_reentry_buy` | grid_outage_recovery.py |
| `compute_grid_profit_view` | grid_view.py |
| `run_actions`, `apply_fill_to_state` caller | execution.py |
| `append_event`, `queue_engine_event`, `flush_queued_events` | state_store.py |
| `evaluate_bot_health`, `emit_health_alerts` | health_watch.py |
| `note_binance_failure`, `active_failure` | binance_connectivity.py |
| `DcaGridTrailingStrategy.tick` | dca_grid_trailing.py (plugin entry) |

---

## 22. DECISION TREE (single tick, compact)

```
tick(P):
  if not IA: return [IA_BUY]
  if outage: recover_state_flags(P)
  if mode REENTRY: handle_reentry(P); return
  if mode PROFIT: handle_profit(P); return
  for i in sell_grids if sell_enabled:
    if triggered[i] and not fired[i]: trail_sell(i,P) → maybe action
  for j in buy_grids if buy_enabled:
    if triggered[j] and not fired[j]: trail_buy(j,P) → maybe action
  for i in sell_grids if sell_enabled: try_trigger_sell(i,P)
  for j in buy_grids if buy_enabled: try_trigger_buy(j,P)
  if side==SELL and can_arm_reentry: arm_reentry(P); return
  if side==BUY and can_arm_profit: arm_profit(P); return
  return actions
```

---

## 23. VERSION / SYNC NOTES

When modifying grid logic:
1. Update this file
2. Update `TRADE_TRAILING_MASTER_SPEC.md` §4270+
3. Add/adjust tests in `tests/test_grid_*.py`, `test_cycle_grid_side.py`, `test_parallel_grids.py`
4. Run `python scripts/sync_module_meta.py` if new modules

**Spec precedence:** If this doc conflicts with `TRADE_TRAILING_MASTER_SPEC.md`, spec is ground truth; update this doc to match after spec changes.
