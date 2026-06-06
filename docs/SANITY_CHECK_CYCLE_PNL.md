# Sanity Check: BotEngine Cycle PnL (fee-aware + cycle isolation)

**Tarih:** 2026-02-01  
**Amaç:** Cycle PnL hesaplamasının yalnız cycle fill’leri ile izole edildiğini ve profit-exit’in fee-aware tetik ile break-even altı satış yapmadığını doğrulamak.

---

## Kabul Kriterleri

- Aynı event akışında cycle PnL matematiksel olarak tutarlı (fee-aware net).
- Profit-exit break-even altı satış yapmıyor.
- Loglar “neden zarar/kâr”ı açıklıyor (BOT_PROFIT_EXIT_EVAL, BOT_CYCLE_END).
- API response uyumlu; `cycle_pnl_last`, `cycle_id_last`, `pnl_calculation_mode` dönüyor.

---

## Test Senaryosu (manuel)

1. **Config’te `pnl_mode=cycle_only_fee_aware_v1` ayarla** (staging/test).
2. **Bot başlat:** initial_allocation → birkaç trail_buy_grid fill → profit_exit fill.
3. **Logları kontrol et:**
   - `BOT_PROFIT_EXIT_EVAL` → `scope=cycle`, `decision=SELL` sadece `last_price >= trigger_price` iken.
   - `BOT_CYCLE_END` → `realized_pnl_cycle_net`, `matched_qty`, `fees_usdt`, `pnl_mode`.
4. **API:** `GET /api/bots-engine/{id}/performance` → `cycle_pnl_last`, `cycle_id_last`, `pnl_calculation_mode` alanları mevcut.

---

## Rollback

- Config’te `pnl_mode=legacy` (varsayılan) bırakılırsa eski davranış (nominal tetik, legacy PnL) kullanılır.
