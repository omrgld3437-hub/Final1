# TRDCA Strateji Audit Raporu (vFinal.2 referans)

Bu doküman, vFinal.2 "strateji mantığı + entegrasyon kilitleri" özetine göre `app/botengine/strategies/trdca_pro.py` ve orchestrator akışının maddeli kontrolüdür.

---

## 1) Özet: Örtüşme

| Alan | Doküman | Kod | Durum |
|------|---------|-----|--------|
| İki motor | TRB + DCA, 0/1 action/tick | `dca_tick` + `trb_tick`, `arbitrate` tek kazanan | ✅ |
| Terminal mod | SAFE_STOP / RESUME_PENDING → aksiyon yok | `strategy_tick` 768-771 erken dönüş | ✅ |
| Snapshot doğrulama | ts, balances, prices, filters, open_order | 755-764: ts, balances_free, prices_last, filters, open_order | ✅ |
| Monotonic tick | snapshot.ts <= last_tick_ts → NOOP | 764-765: ts_ms <= last_tick_ts → NOOP | ✅ |
| Fills önce | apply_fills her zaman en başta | 774-776: snapshot.fills varsa apply_fills, sonra devam | ✅ |
| Open order gate | open_order != null → yeni aksiyon yok | 779-781: open_order varsa NOOP, last_tick_ts güncellenir | ✅ |
| ACK gate | SENT + timeout dolmadı → RESUME_PENDING; doldu → SAFE_STOP | 783-794: aynı mantık, timeout sonrası reason ayrımı var | ✅ |
| Motor patch merge | dca sadece state.dca, trb sadece state.trb | 801-805: patch'ler sadece kendi anahtarlarını yazıyor | ✅ |
| Validation/normalize | Batch minQty/stepSize/minNotional | validate_and_normalize_batch (84-119) | ✅ |
| Arbitration | 0/1 action, fairness | arbitrate (577-607), tek kazanan | ✅ |
| active_intent | legs, commit_snapshot, meta, exec_basket_price, send_time_ms | 825-836 tam set | ✅ |
| apply_fills PARTIAL | Herhangi PARTIAL → SAFE_STOP | 641-645 | ✅ |
| apply_fills FILLED | commit ile pending temizle, kaynağa göre finalize, active_intent=None | 650-706 | ✅ |
| apply_fills UNKNOWN | Dokunma | 647-648: all FILLED değilse return state (mutate yok) | ✅ |
| request_id | deterministik bot_id:ts | _request_id(bot_id, ts_ms) | ✅ |

---

## 2) Eksik veya Farklı Olan Noktalar

### 2.1 Data health gate (price strikes) — DÜZELTİLDİ

**Doküman:** Gerekli fiyatlar yoksa/<=0 ise strike artar; strike limiti aşılırsa → SAFE_STOP(MARKET_DATA_INCOMPLETE).

**Kod (güncel):** DCA/TRB her tick’te `price_null_assets` set’i döndürüyor; `strategy_tick` içinde asset bazında strike artırılıyor (null ise +1, değilse 0). `price_null_strike_limit` (config, default 10) aşılırsa SAFE_STOP(MARKET_DATA_INCOMPLETE) dönülüyor. ✅

---

### 2.2 TRB gap tanımı — DOKÜMAN KODLA HİZALANDI

**Kod (kaynak):** `gap_pct = max(|target_weights[asset] - current_weights[asset]|)` — hedefe göre maksimum sapma.

**Doküman (güncel):** TRB gap = **max |target − current|** (hedef ağırlıktan anlık ağırlığın maksimum sapması). Eşikler (gap_arm_pct, trail_back_pct) bu metriğe göre yorumlanır. Spread (max current − min current) kullanılmıyor.

---

### 2.3 apply_fills sonrası open_order / ACK sırası

**Kod sırası:**  
1) apply_fills  
2) open_order → NOOP  
3) active_intent + ACK timeout

**Doküman:** “Fills önce”, “Open order gate”, “ACK gate” ayrı maddeler; sıra net.

**Durum:** Mantık doğru. Sadece şu netleştirilebilir: apply_fills sonrası `active_intent` bazen temizlenmiş olur (tüm bacaklar FILLED). ACK timeout bloğu sadece `active_intent` hâlâ SENT iken çalışır; dolayısıyla fill’ler gelip intent temizlendiyse bir sonraki tick’te ACK bloğuna düşülmez. ✅

---

### 2.4 Orchestrator: fills’in sonraki tick’e taşınması

**Doküman:** State ilerletme sadece fill ile; “tick içinde ack oldu varsay” yok.

**Kod:** ACTIONS sonrası orchestrator `run_actions` çağırıyor, sonuçları `state["_pending_fills"]` yapıyor; bir sonraki tick’te `_build_trdca_snapshot` bu listeyi `state.pop("_pending_fills", [])` ile alıp `snapshot["fills"]` olarak veriyor. Yani apply_fills bir sonraki tick’in başında, “fills önce” kuralına uygun çalışıyor. ✅

---

### 2.5 Fill status eşlemesi (exchange → status_map) — DÜZELTİLDİ

**Kod (güncel):**  
- `FILLED` → "FILLED"  
- `PARTIALLY_FILLED`, `CANCELED`, `CANCELLED`, `REJECTED` → "PARTIAL"  
CANCELLED varyantı eklendi. ✅

---

## 3) Apply_fills kenar durumları

| Durum | Beklenen | Kod |
|-------|-----------|-----|
| active_intent yok | Hiçbir şey yapma | 618-619 return state | ✅ |
| Her bacak FILLED | Pending temizle, DCA/TRB finalize, active_intent=None | 650-706 | ✅ |
| Herhangi bacak PARTIAL | SAFE_STOP(PARTIAL_BATCH_EXECUTION) | 641-645 | ✅ |
| Bazı UNKNOWN, hiç PARTIAL yok | State’i değiştirme, intent’i sakla | 647-648 return state | ✅ |
| commit_snapshot ile pending temizliği | Pending’i commit miktarına göre düş; negatif olursa SAFE_STOP(PENDING_CLEANUP_MISMATCH) | 652-665 | ✅ |
| DCA finalize | grid_up/down_consumed, vwap_sell/buy, armed reset | 666-686 | ✅ |
| TRB finalize | plan step_idx++, plan bitince IDLE + trb_cycles_count++ | 688-703 | ✅ |

**Düzeltme:** Negatif pending (double-cleanup / drift) artık SAFE_STOP(PENDING_CLEANUP_MISMATCH) ile sonlanıyor; clamp kaldırıldı.

---

## 4) Merge sınırları ve global alanlar

**Doküman:** dca_tick sadece state.dca, trb_tick sadece state.trb; mode, last_tick_ts, active_intent, pending_* sadece strategy_tick/apply_fills tarafından güncellenir.

**Kod:**
- dca_tick: `patch = {"dca": ...}` (136, 182-341).
- trb_tick: `patch = {"trb": ...}` (352, 403-483).
- strategy_tick: 801-805’te sadece patch anahtarları state’e yazılıyor; mode, last_tick_ts, active_intent, pending_* sadece strategy_tick veya apply_fills içinde set ediliyor.

**Eksik:** `price_null_strikes` merge kuralı dokümanda var (asset bazında max(prev, dca_patch, trb_patch)); kodda patch’ler strikes üretmiyor, bu yüzden merge yok. Data health gate eklenirse bu merge de eklenmeli.

---

## 5) TRB gap / plan üretimi

- **Gap hesabı:** Yukarıda (2.2) belirtildi; metrik dokümandan farklı.
- **Plan üretimi:** `_trb_build_steps` (495-573): SELL_ONLY_THEN_BUY, min_leg_notional, stepSize/floor_to_step, client_order_id deterministik. ✅
- **Initial allocation:** base_sum <= 0 ve quote > 0 iken IDLE→TRAIL’de aynı tick’te plan yapılıp adım atanıyor (435-438). ✅

---

## 6) DCA basket / grid mantığı

- **Basket fiyat:** `_basket_price(weights, prices, quote_asset)` (54-65); ağırlık × fiyat toplamı. ✅
- **Anchor:** state.anchor_price yoksa basket ile başlatılıyor; DCA anchor’ı set etmiyor (179-180). ✅
- **Grid tetik/trail:** UP_SELL/DOWN_BUY için tetik seviyesi (anchor × (1±pct)), ardından peak/trough trailing (236-266). ✅
- **Post-sell/post-buy:** POSTSELL_DIP, POSTBUY_PEAK (207-229). ✅
- **Batch oranları:** DCA bacakları target weights’e oransal (289-304); filters ile normalize. ✅

---

## 7) Determinism ve idempotency

- request_id: `bot_id:ts_ms`. ✅  
- batch_id / intent_id: hash(bot_id, source, …) ile deterministik. ✅  
- active_intent tek kaynak; apply_fills tamamlanınca temizleniyor. ✅  
- Restart sonrası reconcile: intent + legs + commit_snapshot ile “ne bekleniyordu / ne temizlendi” takibi mümkün. ✅  

---

## 8) Özet aksiyon listesi (hepsi uygulandı)

1. **Data health gate:** ✅ DCA/TRB `price_null_assets` döndürüyor; strategy_tick’te merge, strike limit (config: `price_null_strike_limit`, default 10) aşımında SAFE_STOP(MARKET_DATA_INCOMPLETE).
2. **TRB gap:** ✅ Doküman kodla hizalandı: gap = max |target − current| (bu dokümanda 2.2 güncellendi).
3. **Fill status:** ✅ status_map’e `CANCELLED` eklendi.
4. **Pending cleanup:** ✅ Negatif pending’de SAFE_STOP(PENDING_CLEANUP_MISMATCH) dönülüyor.

Kod vFinal.2 akışı ve “fills önce / open order / ACK / merge / apply_fills” kuralları ile uyumlu.
