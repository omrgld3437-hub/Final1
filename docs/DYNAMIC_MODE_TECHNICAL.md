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
              safety_gate.emergency_check()  → STOP_LOSS / EMERGENCY_CLOSE / NONE
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
| `safety_gate.py` | Ön koşul kontrolü, stop-loss %8, emergency close %15 |

---

## 3. Ne zaman snapshot yenilenir?

`cycle_manager.need_recompute(state)` true döner:

1. `state['_dynamic_recompute_needed']` set (tur kapanışında `dca_grid_trailing` set eder)
2. `state['dynamic_snapshot']` yok
3. `snapshot.cycle_id != state.cycle_id`

Tur içinde aynı snapshot tekrar `apply_overlay` ile cfg'ye yazılır (cfg her tick raw dict'ten rebuild edilebilir).

---

## 4. Güvenlik katmanları (Safety Gate)

Dinamik mod **yalnızca** dört katman tam ise aktif:

| # | Katman | Kaynak | Not |
|---|--------|--------|-----|
| 1 | `max_buy_levels >= 1` | Kullanıcı config | DCA üst sınır |
| 2 | `daily_loss_limit_usd > 0` | Kullanıcı config (dyn açılınca default: bütçe×5%) | Günlük kayıp limiti |
| 3 | `stop_loss_pct = 8%` | Sistem enjekte | Tur equity düşüşü |
| 4 | `emergency_close_pct = 15%` | Sistem enjekte | Portföy düşüş devre kesici |

- **Default enjeksiyon:** `config_from_ui_payload` (create + update), `dynamic_mode=true` & `daily_loss_limit_usd` yok/≤0 ise **backend'de** bütçe×%5 (min 5) enjekte eder. UI bağımlılığı yok; mod artık sessizce pasif kalamaz.
- **Create gate:** `bots_create` → `dynamic_mode=true` & ön koşul eksikse `check_prerequisites()` fail → HTTP 400 (enjeksiyon sonrası pratikte yalnız geçersiz config'lerde tetiklenir).
- **Update gate:** `update-config` → aynı kontrol → HTTP 400.
- **Runtime:** Ön koşul yine de bozulursa `is_dynamic_mode_active()` false → manuel mod gibi çalışır (güvenli düşüş).

**Acil durum (`emergency_check`):** **Her tick** sonrası equity ölçülür; eşik aşılırsa bot `paused_error`, `last_error_code=DYN_STOP_LOSS` veya `DYN_EMERGENCY_CLOSE`. **Önemli:** Bu bir *devre kesicidir* — botu duraklatır, **pozisyonu otomatik likidite ETMEZ** (projedeki `daily_loss_limit` davranışıyla aynı; operatör müdahalesi gerekir).

### 4.1 Tasarım kararı — neden "duraklat", neden "likidite değil"? (doğrulandı)

Bu seçim, tüm proje ve DCA stratejisi incelenerek **bilinçli ve doğru** kabul edildi:

- **Emir modeli:** Bot **market** emirleriyle, **tick-driven** çalışır (borsada bekleyen limit emri yok). Duraklatma = tüm trading durur; "bekleyen emir dolmaya devam eder" riski yoktur.
- **Proje deseni:** Projedeki *her* risk olayı duraklatır — `daily_loss_limit` (paused_error), API anahtarı yok/401, vb. Pozisyonu düzleştiren (likidite eden) tek yol **botu silmektir** (`_sell_symbol_base_on_delete`); `stop` bile pozisyonu korur.
- **Strateji tezi:** DCA/grid ortalama-düşürme stratejisi, düşüşte alıp toparlanmada satarak kâr eder. Drawdown dibinde base'i zorla satmak **maksimum zararı kilitler** ve stratejinin dayandığı toparlanma yolunu yok eder. Ayrıca çöküşte market-sell = kötü dolum (slippage). Bu yüzden likidasyon bu strateji için **yanlış** olur.
- **Geri alınabilirlik:** Duraklatma geri alınabilir (operatör devam ettirir); likidasyon geri alınamaz. Erken tetiklenen bir duraklatmanın maliyeti yalnızca bir operatör uyarısıdır.

Sonuç: `STOP_LOSS` (tur -%8) ve `EMERGENCY_CLOSE` (portföy -%15) **koruyucu duraklatmalardır** ("kapatma" değil). Eylem anahtarları/eşikler stabil kimlik olarak korunur; operatöre gösterilen `reason` ve UI metni dürüsttür ("bot duraklatıldı, pozisyon korunuyor"). İki eşik farklı arızayı yakalar: tur-içi sert düşüş (STOP_LOSS) vs. çok turlu yavaş erime (EMERGENCY_CLOSE, başlangıç sermayesine göre).

### 4.2 Tasarım kararı — tur-içi rejim savunması neden yok? (doğrulandı)

Parametreler **immutable snapshot** ilkesiyle yalnız tur sınırında yenilenir; tur ortasında grid yüzdelerini değiştirmek, fired-flag / trigger-price'ları `reference_price`'a bağlı grid state-machine'ini bozardı. Tur-içi koruma **her tick çalışan `emergency_check`** ile sağlanır; aşırı maruziyet ise `max_buy_levels` ile sınırlıdır. Dolayısıyla tasarım tutarlıdır; ek tur-içi parametre mutasyonu eklenmez.

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

**Grid qty dağılımı — sermaye kullanımı:** Dinamik mod grid qty %'lerinin **şeklini** (geometrik dağılım) değiştirir ama kullanıcının manuel şablonundaki **toplam** qty %'sini (örn. 10+15+20=%45) korur. Yani manuel rezerv niyeti iptal edilmez; yalnızca dağılım yeniden biçimlenir. Şablonda kullanılabilir qty değeri yoksa %100'e (tam dağıtım) düşülür.

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
| `GET /api/bots-engine/{id}` | `dynamic_mode: { enabled, active, safety_gate, snapshot, emergency }` |
| `_effective_grid_config()` | Grid UI sayıları = snapshot `applied` (botun gerçekten koştuğu değerler) |
| Orchestrator | Hook + `DYN_SNAPSHOT` engine event |

### Frontend

| Yer | Davranış |
|-----|----------|
| Dashboard create modal | Tek ON/OFF toggle; `dynamic_mode` + default `daily_loss_limit_usd` |
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
| **daily_loss_limit otomatik** | Create/update'te backend bütçenin %5'ini enjekte eder; kullanıcı modalda görmeyebilir. `safety_gate.injected_defaults` detay API'de açık |
| **stop_loss / emergency_close UI'da görünmez** | Sistem enjekte; detay API `dynamic_mode.safety_gate.injected_defaults` içinde döner ama UI banner'da gösterilmiyor (opsiyonel iyileştirme) |
| **Regime histerezis MIN_DWELL=1** | Bilinçli: cycle-start bazlı, turlar seyrek; pratikte her tur değişebilir. `classify`/`update_regime_state` streak mantığını ayrı tutar — **ikisi senkron kalmalı** (değiştirilirse birlikte) |
| **Klines REST yükü** | Sembol başına cache var; çok bot aynı sembolde OK, farklı sembollerde REST artar |

---

## 15. Hızlı debug checklist

1. `GET /api/bots-engine/{id}` → `dynamic_mode.active` true mu?
2. `state.dynamic_snapshot.cycle_id` == `state.cycle_id` mu?
3. `data_fresh` false ise → Binance klines / ağ; önceki tur değerleri normal
4. `safety_gate.violations` dolu mu → prereq eksik, mod pasif
5. Engine log → `DYN_SNAPSHOT`, `DYN_EMERGENCY` satırları
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
