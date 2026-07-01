# Dynamic Param V6 — Sıfırdan Kurulum Teknik Programı

**Durum:** Aktif tek motor (2026-07) · V5 runtime kaldırıldı · V6 katalog + ayarlayıcı motor varsayılan

**Final not:** Dynamic Param V5 removed after V6 staging validation. V6 is now the default and only Dynamic Param engine. V6 uses 2.295 catalog profiles, deterministic adjusters, no live fee dependency, cost floor only, BotParams adapter, and DPLV6 telemetry.

**Tek kaynak çapraz referans:** `TRADE_TRAILING_MASTER_SPEC.md` § Dynamic Param Score Engine V6

---

## Özet

V5’in parametre üretimi, shelf ID, route key, fallback, fee-efficiency ve küsuratlı üretim mantığı **tamamen kaldırılacaktır**. Korunan katmanlar: OHLCV çekimi, indikatörler (EMA/RSI/ADX/ATR/ROC/BB/Z), hacim/spread/veri kalitesi, BTC bağlamı, borsa precision.

V6 canlıda parametre **uydurmaz**; senaryo kimliği seçer → katalog profili → deterministik ayarlayıcılar → bütçe ölçekleme → borsa doğrulama.

**Hazır profil sayısı:** 765 taktik × 3 şiddet = **2.295** (`DPLV6_*`)

**Feature flag:** `DPS_ENGINE_VERSION=v6` (varsayılan). `DPS_ENGINE_VERSION=v5` → `RuntimeError` (V5 kaldırıldı).

---

## 1. V5’ten Kaldırılacak Yapılar

- DPLV5 shelf ID, `A2|R2|D3|…` route key, exact/fallback/derived resolver
- Fee efficiency skoru; fee eksikliğiyle karar/grid kapatma
- Küsuratlı base/grid/trailing/kar hedefi üretimi
- Referans/bekle merkezli strateji dili (UI’da referans bandı kaldırıldı)
- Exposure hard cap breach’in senaryo kararını bozması
- Canlı parametre uydurma

## 2. V6 Felsefesi

```
Veri → Senaryo kimliği → Taktik davranış → Şiddet → Hazır profil
     → Ayarlayıcı motor → Bütçe ölçekleme → Borsa doğrulama → Final parametre
```

11 ilke: hazır profil, kötü piyasa = savunmacı (işlem yok değil), cüzdan coin’i yok say, bot bütçesi esas, canlı fee yok say, sabit cost floor, kafes sistemi, katalog + sınırlı delta, açıklanabilir kimlik.

## 3. Bot bütçesi

Girdi: `symbol`, `bot_budget_usdt`, `current_price` — mevcut cüzdan base oranı **kullanılmaz**.

## 4. Fee politikası

Canlı fee alanları seçimde **yok**. Sabit:

| Sabit | Değer |
|-------|-------|
| `DEFAULT_COST_FLOOR_PCT` | 1.2 |
| `MIN_PROFIT_BUFFER_PCT` | 1.0 |

`min_profit_pct = cost_floor + trailing_pct + buffer` → %0.5 kafese yukarı yuvarlanır.

## 5. Parametre kafesi

- **Base/quote:** %5 adımlı (0–95)
- **Grid mesafe:** %1 adımlı; riskli yönde yuvarlama
- **Grid miktar:** %5 katları; yön başına %100; izinli şablonlar (1–5 grid)
- **Trailing:** T0=0.5 … T8=2.9 (%0.3 artış)
- **Kar tetik:** 2.5–8.0 (%0.5 adım) K05…K12

## 6. İşlem modülleri

`INITIAL_BASE_ALLOCATION` · `NORMAL_BUY_GRID` · `SELL_GRID` · `PROFIT_LOOP` (satış → kar alım → kar satış sırası zorunlu)

## 7. Senaryo ağacı

8 ana rejim (R1–R8) · 63 alt · 231 mikro · 765 taktik · 3 şiddet (DEF/STD/ACT)

## 8–20. Input contract, ayarlayıcılar, delta limitleri, bütçe doğrulama, profil ID formatı

Tam formüller ve skor tabloları bu belgenin orijinal iş emrinde tanımlıdır; kod: `app/services/dynamic_param_score/v6/`.

## 21. Test zorunlulukları

- Katalog: 2295 profil, küsurat yok, modül/sıra doğruluğu
- Ayarlayıcı unit testleri (B3, F3, V5, L3, data invalid)
- Çakışma: B3+F3+V5+L3 global limit
- Senaryo regression: R2/R4/R5/R6/R8 örnekleri

## 22. Kod modülleri

```
app/services/dynamic_param_score/v6/
  constants.py, domain/types.py
  v6_input_contract.py, v6_indicator_adapter.py
  v6_scenario_classifier.py, v6_scenario_tree.py
  v6_behavior_resolver.py, v6_severity_resolver.py
  v6_profile_catalog.py, v6_profile_factory.py, v6_profile_validator.py
  v6_quantizer.py, v6_delta_limiter.py, v6_budget_scaler.py
  v6_exchange_validator.py, v6_ui_explainer.py, engine.py
  adjusters/*.py
data/dynamic_param_v6/
  scenario_tree_v6.json, behavior_catalog_v6.json
  parameter_rulebook_v6.json, dplv6_profile_catalog.json
```

## 23. V5 silme planı (sıra)

1. V6 katalog + motor test yeşil
2. PA + DM `DPS_ENGINE_VERSION=v6` staging
3. `v5/`, `param_pool/` seçici, `scenario_alignment`, fee-efficiency scoring kaldır
4. Master spec V5 maddeleri arşiv → `docs/archive/`

---

*Bu dosya editör iş emrinin proje içi kopyasıdır; detaylı skor/delta tabloları implementasyonla `v6/adjusters/` ve `v6/constants.py` içinde kodlanır.*
