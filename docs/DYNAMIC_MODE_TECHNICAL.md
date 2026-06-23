# Dinamik Mod (Dynamic Mode) — Teknik Çalışma Mantığı

> **Son güncelleme:** 2026-06-15  
> **Kapsam:** DCA Grid Trailing (`dca_grid_trailing`) — tek sembol botlar  
> **Kaynak kod:** `app/botengine/dynamic/`  
> **UI:** Dashboard oluşturma modalı (`dashboard-create-modal.js`), bot detay (`bot.html`)

---

## 1. Amaç

Dinamik mod, kullanıcının manuel girdiği grid/trailing/kâr eşiklerini **her tur başında** piyasa koşullarına göre otomatik ayarlar. Tur içinde parametreler **sabit** kalır (immutable snapshot). Manuel mod (`dynamic_mode=false`) tamamen aynı davranır; dinamik paket devreye girmez.

**Tasarım ilkeleri:**

| İlke | Açıklama |
|------|----------|
| Güvenlik önce | Risk motoru son sözü söyler; hiçbir öneri doğrudan uygulanmaz |
| Manuel taban | Öneriler kullanıcının şablon config'inden türetilir; tamamen sıfırdan üretilmez |
| Tur bazlı | Snapshot yalnızca `cycle_id` değişince veya `_dynamic_recompute_needed` ile yenilenir |
| Güvenli düşüş | Hata / stale veri → önceki snapshot veya manuel config; bot çökmez |
| Kapatılabilir | `dynamic_mode=false` → paket bypass, state'teki snapshot temizlenir |

---

## 2. Mimari (veri akışı)

```
Orchestrator tick (running bot)
        │
        ▼
 safety_gate.is_dynamic_mode_active(cfg)?
        │ evet
        ▼
 cycle_manager.need_recompute(state)?
        │ evet                          │ hayır
        ▼                               ▼
 build_snapshot()                  apply_overlay(cfg, existing_snapshot)
   ├─ features.collect_features()       │
   ├─ regime.classify()               │
   ├─ strategy_engine.suggest()        │
   ├─ strategy_engine.smooth_against_prev()
   ├─ risk_engine.apply_safety()       │
   └─ state['dynamic_snapshot'] = …   │
        │                               │
        └──────── apply_overlay(cfg, snapshot) ─────┘
                        │
                        ▼
              strategy.tick(state, cfg, price, …)
                        │
                        ▼
              safety_gate.emergency_check()  → NONE (risk brake disabled)
```

**Modüller:**

| Dosya | Rol |
|-------|-----|
| `features.py` | Binance klines (5m/1h), spread, hacim → `MarketFeatures` |
| `indicators.py` | ATR, ADX, BBW, RSI, EMA slope, realized vol (saf fonksiyonlar) |
| `regime.py` | 8 rejim sınıflandırması + histerezis |
| `strategy_engine.py` | Rejim + ATR → parametre **önerisi** (`ParamSuggestion`) |
| `risk_engine.py` | Hard bound, rate limit, grid monotonicity, anti-martingale |
| `cycle_manager.py` | Snapshot oluşturma, overlay, history ring buffer (20 tur) |
| `safety_gate.py` | Ön koşul kontrolü; `max_buy_levels` aktif, günlük limit / stop-loss / emergency brake kapalı |

---

## 3. Ne zaman snapshot yenilenir?

`cycle_manager.need_recompute(state)` true döner:

1. `state['_dynamic_recompute_needed']` set (tur kapanışında `dca_grid_trailing` set eder)
2. `state['dynamic_snapshot']` yok
3. `snapshot.cycle_id != state.cycle_id`

**İlk tur manuel kuralı:** `cycle_id=1` boyunca dynamic overlay uygulanmaz. Bot ilk açılış turunu kullanıcının manuel başlangıç şablonuyla çalıştırır; dinamik snapshot/overlay tur 2 ve sonrasında başlar. API grid görünümü de tur 1'de eski snapshot varsa bile manuel config'i gösterir.

Tur içinde aynı snapshot tekrar `apply_overlay` ile cfg'ye yazılır (cfg her tick raw dict'ten rebuild edilebilir).

---

## 4. Aktif sınırlar ve kapatılan frenler (Safety Gate)

Mevcut operatör kararında otomatik durdurma frenleri devre dışıdır. Dinamik modun aktif ön koşulu yalnızca yapısal DCA sınırıdır:

| # | Katman | Kaynak | Not |
|---|--------|--------|-----|
| 1 | `max_buy_levels >= 1` | Kullanıcı config / DB | DCA üst sınırı; korunur |
| - | `daily_loss_limit_usd` | Config alanı | Korunur ama prerequisite ve runtime enforcement kapalı |
| - | `stop_loss_pct = 8%` | Eski sistem freni | Enjekte edilmez, runtime'da tetiklemez |
| - | `emergency_close_pct = 15%` | Eski sistem freni | Enjekte edilmez, runtime'da tetiklemez |

- **Default enjeksiyon kapalı:** `config_from_ui_payload`, `dynamic_mode=true` olsa bile bütçe×%5 `daily_loss_limit_usd` üretmez. Alan korunur; boş/0 kalabilir.
- **Runtime daily loss kapalı:** `dca_grid_trailing.tick()` eski `_daily_loss_limit_hit` bayrağını temizler ve günlük limit aşımında tick'i durdurmaz. Orchestrator da bu bayrakla botu pause etmez.
- **Emergency brake kapalı:** `safety_gate.emergency_check()` her zaman `action=NONE` döner. Eski `_dyn_emergency` state'i temizlenir; `DYN_STOP_LOSS` / `DYN_EMERGENCY_CLOSE` pause akışı çalışmaz.
- **Create gate:** `bots_create` → `dynamic_mode=true` & `max_buy_levels` eksik/geçersizse `check_prerequisites()` fail → HTTP 400.
- **Update gate:** `update-config` → aynı kontrol → HTTP 400.
- **Runtime:** Ön koşul yine de bozulursa `is_dynamic_mode_active()` false → manuel mod gibi çalışır (güvenli düşüş).

**Acil durum (`emergency_check`):** Kod yolu geriye dönük olarak durur fakat `EMERGENCY_CHECKS_ENABLED=False` olduğu için `NONE` döner. Eşikler tekrar açılırsa davranış duraklatma olur; likidasyon yapmaz.

### 4.1 Tasarım kararı — kapalı frenler neden silinmedi?

Alanlar ve eski kod yolu bilinçli olarak silinmedi:

- **Geri alınabilirlik:** `safety_gate.py` içindeki bayraklar `True` yapılırsa eski korumalar migration gerekmeden geri gelir.
- **Şema uyumu:** DB/config/API alanları korunur; eski bot kayıtları ve UI payload'ları kırılmaz.
- **Dürüst UI/state:** Bayraklar kapalıyken `injected_defaults={}` döner; API detayında sistem freni varmış gibi görünmez.

Sonuç: Bu kurulumda `STOP_LOSS` (tur -%8), `EMERGENCY_CLOSE` (portföy -%15) ve günlük kayıp limiti otomatik duraklatma üretmez.

### 4.2 Tasarım kararı — tur-içi rejim savunması neden yok? (doğrulandı)

Parametreler **immutable snapshot** ilkesiyle yalnız tur sınırında yenilenir; tur ortasında grid yüzdelerini değiştirmek, fired-flag / trigger-price'ları `reference_price`'a bağlı grid state-machine'ini bozardı. Bu kurulumda tur-içi otomatik stop freni yoktur; aşırı alım maruziyeti `max_buy_levels` ile sınırlıdır.

### 4.3 DCA-derinlik koruması — devre dışı kod yolu

**Sorun:** Equity tabanlı -%8 tur stop'u, fiyat **price** olarak çok daha az düştüğünde tetiklenir. Örn. 50/50 başlayan bir bot için fiyat -%16'da equity ~-%8 olur; bot düşüşte alım yaptıkça base ağırlaşır ve eşik daha da erken gelir. Sonuç: kullanıcının **-%20'ye kurduğu alım gridi hiç çalışmadan** bot durabilirdi — bu, DCA'in tüm mantığına aykırı.

**Çözüm (`_deepest_buy_grid_pct` + `DYN_GRID_DEPTH_BUFFER_PCT`):** `emergency_check`, fiyat **en derin (efektif/overlay'lenmiş) alım gridinin + tampon** kadar altına inmeden **asla** tetiklenmez. Yani:

```
guard = en_derin_buy_grid_pct + DYN_GRID_DEPTH_BUFFER_PCT   (varsayılan tampon %5)
price_drop = (reference_price - price) / reference_price × 100
price_drop < guard  →  action = NONE  (plan içi: bot serbest çalışır, gridler çalışır)
price_drop ≥ guard  →  equity/portföy eşikleri uygulanır (plan ötesi: devre kesici)
```

- En derin grid **-%20** ise devre kesici ancak fiyat **≤ -%25**'e inince devreye girebilir → tüm alım gridleri çalışma şansı bulur.
- **Efektif** gridler kullanılır: dinamik modda grid %'leri ATR ile yeniden hesaplandığı için, o turda botun gerçekten kullandığı en derin seviye baz alınır.
- Frenler ileride yeniden açılırsa `reference_price`/`price` çözülemediğinde derinlik guard'ı atlanır ve eski equity eşiği uygulanır.
- Sığ gridli kurulumlarda davranış pratikte eskisi gibidir (örn. en derin -%3 ise guard ≈ -%8, eski eşikle örtüşür).
- Mevcut durumda bu guard çalışmaz, çünkü `EMERGENCY_CHECKS_ENABLED=False` iken `emergency_check()` erken `NONE` döner.

---

## 5. Piyasa rejimleri

`regime.py` çıktıları:

| Rejim | Tipik koşul | Strateji eğilimi |
|-------|-------------|------------------|
| `LOW_VOL_RANGING` | Düşük ATR, düşük ADX | Dar grid, dengeli base/quote |
| `HIGH_VOL_RANGING` | Yüksek ATR, düşük trend | Geniş grid, daha az base |
| `TRENDING_UP` | ADX↑, EMA slope↑ | Daha fazla base, geniş trailing |
| `TRENDING_DOWN` | ADX↑, EMA slope↓ | **Savunma:** az base (%25 hedef), az alış |
| `SQUEEZE` | Dar BBW | Orta ayar |
| `BREAKOUT` | BBW patlaması + hacim | Geniş adım, dikkatli alış |
| `DUMP_RISK` | Ani düşüş proxy | Çok az base (%15), minimal alış |
| `UNKNOWN` | Veri yetersiz | Manuel config'e yakın nötr |

Histerezis: `MIN_DWELL_CYCLES=1` — flip-flop azaltma.

---

## 6. Overlay edilen alanlar

`cycle_manager.apply_overlay` yalnızca şunları değiştirir:

- `base_alloc_pct`, `quote_alloc_pct`
- `sell_grids[]`, `buy_grids[]` (adet korunur, yüzdeler değişir)
- `sell_trigger_trailing_pct`, `buy_trigger_trailing_pct`
- `profit_exit_rise_pct`, `profit_exit_drop_pct`
- `profit_reentry_drop_pct`, `profit_reentry_rise_pct`

**Asla overlay edilmez:** `max_buy_levels`, `daily_loss_limit_usd`, `symbol`, `initial_capital_usdt`, `paper_mode`, fee, tick interval, emir limitleri.

**Grid trigger tabanı:** Dinamik mod grid tetiklerini manuel şablondan daha yakına çekmez. Her seviye için `applied_pct = max(dynamic_pct, manual_pct)` mantığı kullanılır; böylece düşük ATR manuel −%2/−%4 gridleri −%0.30/−%0.60'a düşüremez.

**Grid qty dağılımı — sermaye kullanımı:** Dinamik mod grid qty %'lerini **birebir manuel şablondan korur**. Kullanıcı %50/%50 kurduysa dinamik mod bunu 47.6/52.4 veya 36.4/43.6 gibi yeniden dağıtmaz. Şablonda kullanılabilir qty değeri yoksa %100 eşit bölünür.

**Manuel taban her tur temiz:** Overlay, orchestrator'daki cache'li `cfg` nesnesini yerinde değiştirir; bu yüzden dinamik motor öneriyi üretirken tabanı **her zaman `config_json`'dan (overlay'lenmemiş manuel config) yeniden türetir** — aksi halde öneriler turdan tura kayar (base drift).

---

## 7. Risk motoru sınırları

`risk_engine.BOUNDS` (örnek):

- Grid adım %: 0.10 – 8.0
- Trailing %: 0.15 – 5.0
- Base alloc %: 10 – 80
- Grid qty büyüme oranı cap: **1.5×** (anti-martingale)

**Turler arası max göreli değişim (`MAX_RELATIVE_CHANGE = %60`)** yalnızca **skaler** parametrelere uygulanır: `base_alloc_pct`, `sell/buy_trigger_trailing_pct`, `profit_*`. **Grid adım %'leri ve qty dağılımı rate-limit'e tabi DEĞİLDİR** — her tur ATR'den yeniden türetilir, yalnızca hard bound + monotonluk + anti-martingale ile sınırlanır. Gerekçe: volatilite gerçekten sıçradığında grid'in hemen genişlemesi *istenir*; rate-limit burada uyumu geciktirip dar-grid riskini artırırdı. EMA smoothing de yalnızca skalerlere uygulanır.

Geçersiz/NaN değer → ilgili alan için **manuel config fallback** + `fallbacks[]` log.

---

## 8. Stale veri politikası

`features.collect_features` hata verirse `data_fresh=false`:

- Yeni rejim/öneri hesaplanmaz
- Önceki snapshot `applied` kopyalanır (yoksa manuel config mirror)
- UI banner: "veri eski (önceki tur değerleri)"
- Bot çalışmaya devam eder

---

## 9. API / UI entegrasyonu

### Backend

| Endpoint / alan | Davranış |
|-----------------|----------|
| `POST /api/bots-engine` (create) | `dynamic_mode` + safety gate |
| `GET /api/bots-engine/{id}` | `dynamic_mode: { enabled, active, safety_gate, snapshot, emergency }`; kapalı frenlerde `emergency` boş kalır |
| `_effective_grid_config()` | Grid UI sayıları = snapshot `applied` (botun gerçekten koştuğu değerler) |
| Orchestrator | Hook + `DYN_SNAPSHOT` engine event |

### Frontend

| Yer | Davranış |
|-----|----------|
| Dashboard create modal | Tek ON/OFF toggle; `dynamic_mode`, `daily_loss_limit_usd=0` |
| Bot detay üst bar | Yeşil **Dinamik ✓** rozeti üst strip (`dynModeStripBadge`; state hero'da yok) |
| Dashboard Bots | En İyi 5 Bot satırında **Dinamik ✓** balon; Mevcut Botlar tablosunda dinamik bot logosu yeşil çerçeve + hover ipucu |
| Grid panel banner | Tur eşikleri, rejim, ATR/ADX/BBW özeti |
| Parametreler modal | Dinamik toggle **yok** (yalnız oluşturma anında). **Bot detay:** dinamik aktif botlarda **Genel \| Dinamik** sekmeleri (`dynamicModeParamsView.js`). **Dashboard Bots → En İyi 5 Bot** Parametreler modalı: dinamik durum + aktif tur grid/pozisyon özeti (API `dynamic_mode`). |

---

## 10. State şeması

```json
{
  "dynamic_snapshot": {
    "cycle_id": 3,
    "built_at_ms": 1718400000000,
    "data_fresh": true,
    "regime": "TRENDING_UP",
    "regime_state": { "current": "...", "candidate": "...", "candidate_streak": 0 },
    "features": { "atr_pct_5m": 0.82, "adx_1h": 28.1, "...": "..." },
    "raw": { "...": "ParamSuggestion.to_dict()" },
    "applied": { "...": "ClampedParams.to_dict()" },
    "reasons": ["regime=TRENDING_UP ..."],
    "clamps": [],
    "fallbacks": [],
    "history": [ { "cycle_id": 2, "regime": "...", "ts": "..." } ]
  },
  "_dynamic_recompute_needed": false,
  "_dyn_emergency": null
}
```

---

## 11. Test kapsamı

| Dosya | Ne test eder |
|-------|--------------|
| `tests/test_dynamic_mode.py` | Indicators, risk clamps, safety gate, model flag |
| `tests/test_dynamic_mode_e2e.py` | Tam pipeline, rejim senaryoları, stale fallback |
| `tests/test_grid_view_dynamic_trigger.py` | Grid UI tutarlılığı, trigger ≤ peak |

---

## 12. Projede NE VAR (tamamlanmış)

- [x] Tam backend paketi (`app/botengine/dynamic/*`)
- [x] Orchestrator hook (snapshot build + overlay + emergency)
- [x] Tur kapanışında recompute flag
- [x] Safety gate create + runtime
- [x] Grid view / bot detail API'de snapshot yansıması
- [x] Dashboard'da bot oluştururken toggle
- [x] Bot detay grid banner + üst rozet
- [x] Engine log event `DYN_SNAPSHOT`
- [x] Unit + e2e testler

---

## 13. NE EKSİK (henüz yok / kısmi)

| Eksik | Detay | Öncelik |
|-------|-------|---------|
| **Master spec bölümü** | `TRADE_TRAILING_MASTER_SPEC.md` içinde ayrıntılı Dynamic Mode bölümü kısa referans | Orta |
| **Multi-asset (TRDCA)** | `bot_multi.html` / TRDCA stratejisinde dinamik mod yok | Düşük |
| **Bot detaydan aç/kapa** | Bilinçli olarak kaldırıldı; yalnız create-time toggle | — (tasarım kararı) |
| **Dashboard bot listesi rozeti** | Mevcut bot satırında "Dinamik" işareti yok | Düşük |
| **Manager / wrn-engine** | Dinamik snapshot olayları manager log humanize'da özel etiket yok | Düşük |
| **Operatör paneli** | 20 tur history API/UI ayrı panel yok (state'te var, UI kısmi banner) | Orta |
| **Canlı rejim grafiği** | Rejim geçmişi görselleştirme yok | Düşük |
| **A/B veya backtest** | Dinamik vs manuel karşılaştırma aracı yok | Düşük |
| **Spec sabitleri tablosu** | DYN_STOP_LOSS_PCT, BOUNDS vb. spec constants tablosunda yok | Orta |
| **Paper mode özel path** | Dinamik mod paper'da test edilmiş ama ayrı dokümante edilmemiş | Düşük |

---

## 14. NE FAZLA / dikkat edilmesi gerekenler

| Konu | Açıklama |
|------|----------|
| **Çift banner** | Grid panelinde detaylı banner + üstte rozet — bilinçli; farklı bilgi yoğunluğu |
| **Config şablonu hâlâ gerekli** | Kullanıcı grid **adet** ve başlangıç şablonunu girer; dinamik mod yüzdeleri ayarlar |
| **daily_loss_limit otomatik değil** | Create/update bütçenin %5'ini enjekte etmez; alan 0 kalabilir ve runtime enforcement kapalıdır |
| **stop_loss / emergency_close kapalı** | Sistem enjekte etmez; `safety_gate.injected_defaults={}` döner, `emergency_check()` `NONE` döner |
| **Regime histerezis MIN_DWELL=1** | Bilinçli: cycle-start bazlı, turlar seyrek; pratikte her tur değişebilir. `classify`/`update_regime_state` streak mantığını ayrı tutar — **ikisi senkron kalmalı** (değiştirilirse birlikte) |
| **Klines REST yükü** | Sembol başına cache var; çok bot aynı sembolde OK, farklı sembollerde REST artar |

---

## 15. Hızlı debug checklist

1. `GET /api/bots-engine/{id}` → `dynamic_mode.active` true mu?
2. `state.dynamic_snapshot.cycle_id` == `state.cycle_id` mu?
3. `data_fresh` false ise → Binance klines / ağ; önceki tur değerleri normal
4. `safety_gate.violations` dolu mu → `max_buy_levels` eksik/geçersiz, mod pasif
5. Engine log → `DYN_SNAPSHOT`; `DYN_EMERGENCY` beklenmez çünkü fren kapalı
6. Grid banner görünmüyorsa → `snapshot.applied` boş olabilir (henüz ilk tur bitmemiş)

---

## 16. İlgili dosyalar (indeks)

```
app/botengine/dynamic/
  __init__.py
  features.py
  indicators.py
  regime.py
  strategy_engine.py
  risk_engine.py
  cycle_manager.py
  safety_gate.py
app/botengine/orchestrator.py          # hook ~891–1044
app/botengine/strategies/dca_grid_trailing.py  # _dynamic_recompute_needed
app/api/bots_engine.py                 # create gate, detail block, grid overlay
app/botengine/grid_view.py             # trigger display
ui/assets/modules/dashboard-create-modal.js
ui/bot.html                            # banner + top badge
tests/test_dynamic_mode*.py
tests/test_grid_view_dynamic_trigger.py
```

---

## 17. Davranış Stance + Tur-Giriş Risk Kapısı (2026-06-20)

İki yeni katman eklendi. İkisi de yalnız `dynamic_mode=true` + cycle ≥ 2'de
çalışır, hata/stale veride güvenli düşer ve manuel modu hiç etkilemez.

### 17.1 Davranış Stance (sürekli pasif↔agresif duruş)

`strategy_engine.compute_stance(features, regime_result) → Stance`. Ayrık
`REGIME_TUNING` tablosunun kaba duruşunu, rejim **içinde** sürekli bir skorla
inceltir (aynı rejimdeki iki tur farklı likidite/momentum/kaosta farklı
agresiflik alır).

```
reward (grid-dostu) = ranging × (0.6·atr_fit + 0.4·liq)   # trend reward'ı ezer
risk   (geniş)      = 0.45·regime_risk + 0.30·(downtrend×ADX_strength) + 0.25·chaos
score  = clamp(reward − risk, −1, +1)   # −1 DEFENSIVE … +1 AGGRESSIVE
```

Stance **yalnız skalerleri** nudge'lar — **grid adımını ASLA** (adım saf
ATR/rejim/fee fonksiyonu kalır, böylece "yüksek vol grid'i genişletir" + tüm
e2e invariant'ları korunur). Etkilediği alanlar (sınırlı, risk-engine yine
clamp'ler):

- `base_alloc_pct += score × 8pp`  (agresif → daha çok base; savunmacı → nakit)
- `sell_trail × (1 + score×0.25)`  (agresif → bırak koşsun; savunmacı → erken kilitle)
- `tp_rise × (1 + score×0.30)`     (agresif → yüksek TP; savunmacı → erken bankla)

Yön **pekiştirir, asla ters çevirmez**: savunmacı rejimler (DUMP/TRENDING_DOWN)
zaten negatif stance üretir → daha çok quote. Snapshot'a `stance` (`raw.stance`
+ top-level), API `dynamic_mode.stance` olarak çıkar.

### 17.2 Tur-Giriş Risk Kapısı — "yeni turu riskte beklet"

`app/botengine/dynamic/cycle_gate.py`. Yeni bir tur (cycle ≥ 2) başlarken yakın
vadeli **düşüş riski** yüksekse, taze alımı (yeni quote) düşen piyasaya
sürmeyi erteler — "düşen bıçağa yeni tur açma".

**Risk modeli (0..1):** ağırlıklı alt-sinyaller; yön-bağımsız vol/akış
sinyalleri yumuşak bir `bearish` çarpanıyla kapılır (yükselişte/sakin churn
bekletme üretmez):

```
s_fast(5m flaş düşüş) .30 | s_regime(DUMP/DOWN) .24 | s_mom(RSI düşük & slope<0) .14
s_dvol×bearish .12 | s_volz×bearish .08 | s_spread(likidite) .07 | s_wick×bearish .05
```

**Hold durum makinesi (histerezis):**
- risk ≥ `HOLD_ON` (0.62) → bekletmeye başla.
- risk ≤ `HOLD_OFF` (0.42) ve `RELEASE_CONFIRM` (2) ardışık kontrol → serbest bırak.
- `MAX_HOLD_SEC` (24sa) → asla sonsuza dek dondurma; savunmacı girişe izin ver.
- stale veri / exception → bekletme yok (bot normal çalışır).

**Ne yapar / yapmaz:** yalnız `initial_allocation` + `trail_buy_grid` (taze alım)
withhold edilir; SELL / profit-exit / **tur-kapatan re-entry** ASLA engellenmez,
likidasyon YOK. Immutable-snapshot ilkesine (§4.2) uyar: kapı yalnız tur
sınırında, tur henüz **engage olmadan** (ilk taze alım geçmeden) silahlanır; bir
alım geçtiğinde tur ENGAGE olur ve DCA planı tur sonuna dek kesintisiz koşar
(tur-içi yeniden-bekletme yok). `cycle_reset_after_fill` engage bayrağını sıfırlar.

**Entegrasyon:** orchestrator dinamik hook — yeni snapshot'ta `evaluate(...)`,
hold aktif & engage değilken her tick `await maintain(...)` (cached features).
`strategy.tick` sonrası `filter_actions(state, actions)` taze alımları düşürür ve
`next_wake`'i `RECHECK_SEC` (30s) ile kısar. API `dynamic_mode.cycle_hold`;
engine event `DYN_CYCLE_HOLD` / `DYN_CYCLE_RELEASE`.

**Env (ops):** `DYN_CYCLE_HOLD_ENABLED`, `DYN_CYCLE_HOLD_ON`, `DYN_CYCLE_HOLD_OFF`,
`DYN_CYCLE_HOLD_RELEASE_CONFIRM`, `DYN_CYCLE_HOLD_MAX_SEC`, `DYN_CYCLE_HOLD_RECHECK_SEC`.

**Testler:** `tests/test_dynamic_cycle_gate.py` (risk modeli, hold makinesi,
aksiyon filtresi, stance yönü).
