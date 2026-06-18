# Dinamik Mod — Düzeltme Çıkarımı ve Uygulama Kaydı

> Tarih: 2026-06-16
> Kaynak: 320 soruluk analiz (`01`–`04`) + `PROJECT_WIDE_AUDIT_REPORT.md` + canlı kod doğrulaması.
> İlke: tüm proje yapısına/mantığına uy, manuel modu byte-identik koru, risk motorunun "son söz" rolünü zayıflatma, mantık hatası bırakma.
> Sonuç: **265 test geçti** (+31 yeni), 0 hata.

---

## 1. Konsolide çıkarım

Analiz ile denetim raporu aynı tabloda buluşuyor: **güvenlik iskeleti sağlam, karar katmanı dar ve bazı niyetler "ölü".** İki rapor birleştirilince düzeltilecekler iki gruba ayrıldı:

1. **Gerçek kod/mantık hataları** (para davranışını bozan veya yanıltan) → düzeltildi.
2. **Tasarım ödünleşmeleri / büyük yeniden-yapılandırmalar** (riskli, düşük getirili) → bilinçli ertelendi, gerekçe yazıldı.

---

## 2. Uygulanan düzeltmeler

| # | Bulgu | Kök neden | Düzeltme | Dosya(lar) | Test |
|---|-------|-----------|----------|-----------|------|
| **P0.1** | `dynamic_mode="false"` açık sayılıyordu | `bool("false")==True` (Python truthiness) | Ortak `parse_bool` helper; model + gate + leaderboard aynı helper'ı kullanıyor | `app/utils/parse_utils.py` (yeni), `models.py`, `safety_gate.py`, `leaderboard_service.py` | `test_parse_bool`, `*_string_false_*` |
| **P0.2** | Dinamik grid miktarları kullanıcı şablonundan kopabiliyordu | Rejim/RSI çarpanları buy/sell qty toplamını ve dağılımını değiştiriyordu | Grid qty yüzdeleri artık manuel şablondan birebir korunuyor; savunma base/quote + grid mesafesiyle yapılıyor | `strategy_engine.py` | `test_grid_qty_percentages_preserve_manual_template_in_risky_regimes` |
| **P0.3** | Yüksek ATR'de gridler 8%'e çöküyordu | liner `step×(i+1)` + per-level 8% clamp | `_resolve_grid_step`: step, `MAX/n` derinlik tavanıyla sınırlanıp gridler yayılıyor (2,4,6,8) | `strategy_engine.py` | `test_high_atr_grids_not_degenerate` |
| **P1.1** | RSI/likidite qty yüzdelerini bozabiliyordu | Feature çarpanları grid miktarlarını yeniden ölçekliyordu | Qty yüzdeleri korunuyor; spread yalnız ekonomik grid mesafe tabanını etkiliyor | `strategy_engine.py` | `test_*_keeps_manual_*_quantities` |
| **P1.2** | DUMP flash-crash yakalamıyordu | yalnız gecikmeli 1h slope+volz | `ret_5m_last` feature'ı + DUMP: son kapanmış 5m bar ≤ −3% → anında DUMP (VEYA slope+volz) | `features.py`, `regime.py` | `test_dump_fast_drop_5m` |
| **P1.4** | `confidence` neredeyse dekoratif | smoothing alpha sabit 0.5 | `alpha_for_confidence`: düşük güven→düşük alpha (prev'e yapışık); 0.5'te eski davranış | `strategy_engine.py`, `cycle_manager.py` | `test_alpha_for_confidence_monotone` |
| **P1.5** | Fee-altı/dar gridler üretilebiliyordu | step tabanı yalnız 0.05% | `_fee_aware_min_step`: step ≥ (buy+sell+min_profit) ve ≥ 2×spread | `strategy_engine.py` | `test_fee_aware_min_grid_step`, `test_spread_widens_fee_floor` |
| **P2.1** | SQUEEZE yalnız `bbw_1h`, BREAKOUT fallback'li | asimetrik veri politikası | SQUEEZE de `bbw` (1h yoksa 5m) fallback'i kullanıyor | `regime.py` | `test_squeeze_falls_back_to_5m_bbw` |
| **P2.2** | BREAKOUT yön-kör (aşağı kırılım nötr %50) | yön sinyali yoktu | Yön slope/ret ile: aşağı kırılım → `TRENDING_DOWN` (defansif), yukarı → BREAKOUT | `regime.py` | `test_downward_breakout_is_defensive_not_neutral` |
| **P2.3** | Leaderboard `spread_bps` arıyor, features `spread_pct` yazıyordu | alan adı uyumsuzluğu | features artık `spread_bps = spread_pct×100` üretiyor | `features.py` | `test_features_expose_spread_bps` |
| **(ek)** | Yarı-oluşmuş (forming) son mum ATR/RSI/BBW'ye dahildi | klines son elemanı oluşum halinde | OHLC indikatörleri kapanmış mumlarla (`k5[:-1]`) hesaplanıyor; vol_z kendi dışlamasını koruyor | `features.py` | (e2e dolaylı) |

### Manuel grid miktarı korunumu
Son ürün kararı: Dinamik mod, grid miktar yüzdelerini kullanıcı şablonundan ayırmaz. Önceki ara çözümde buy/sell deployment çarpanları vardı; bu, UI'da 50/50 kurulmuş gridlerin 47.6/52.4 veya 36.4/43.6 gibi anlaşılması zor oranlara dönüşmesine yol açıyordu. Artık qty savrulması yok; dinamik savunma base/quote hedefi, grid mesafesi, trailing ve kâr eşikleriyle yapılır.

### Risk motoru korundu
Hiçbir düzeltme risk motorunun clamp/rate-limit/monotonluk/anti-martingale "son söz" rolünü zayıflatmadı. Tüm üretim hâlâ `apply_safety`'den geçiyor; `_resolve_grid_step`'in derinlik tavanı risk BOUNDS ile **uyumlu** (8%), clamp'i gereksiz kılıyor ama baypaslamıyor.

### Manuel mod
`dynamic_mode=false` → hook hiç çalışmaz; tüm bu değişiklikler yalnız dinamik aktifken devrededir. Manuel mod byte-identik.

---

## 3. Bilinçli ERTELENEN (gerekçeli)

| Bulgu | Neden ertelendi | Hafifletme |
|-------|------------------|------------|
| **P1.3 Histerezis** (MIN_DWELL=1) | Gerçek tick/zaman-bazlı histerezis büyük yeniden-yapılandırma; `classify`/`update_regime_state` çift-defter mantığını da değiştirmeyi gerektirir ve mevcut test semantiğini kırma riski taşır. Etki sınırlı (rejim tick değil tur bazlı). | P1.4 (confidence→alpha) + forming-mum temizliği rejim-kaynaklı salınımı zaten yumuşatıyor. |
| **tp_drop / re_drop / re_rise rejim-ölçeği** | Bu eşikler için net, gerekçeli rejim katsayısı yok; keyfi çarpan eklemek yeni "kalibre edilmemiş sabit" üretir. | tp_rise zaten rejim-duyarlı; diğerleri ATR-ölçekli (vol'a duyarlı) + smoothing/rate-limit tamponlu. |
| **buy/sell trailing asimetrisi** | Davranış değişikliği; net kazanç belirsiz (TU'da kâr-al dar vs dip-al geniş tartışmalı). | Trailing zaten rejim `trail_mult` ile ölçekli; simetri risk üretmiyor. |
| **ATR/eşiklerin sembole göre normalize edilmesi** | Tarihsel ATR dağılımı/percentile altyapısı gerektirir (büyük iş). | Sabit eşikler + clamp güvenli; yanlış rejim felaket değil (risk motoru clamp'ler). |

---

## 4. Yeni sabitler (kalibre edilebilir)

`strategy_engine.py`: `MAX_GRID_STEP_PCT=8.0`, `FEE_FLOOR_K=1.0`, `SPREAD_FLOOR_MULT=2.0`.
`regime.py`: `DUMP_FAST_DROP_PCT=-3.0`.

Bunlar sezgisel başlangıç değerleri; backtest ile ince ayar yapılabilir.

---

## 5. Doğrulama

- `pytest tests/` → **265 passed, 7 skipped** (skip'ler önceden mevcut/ağ).
- Yeni: `tests/test_dynamic_mode_audit_fixes.py` (31 test) tüm P0/P1/P2 düzeltmelerini kilitliyor.
- Uçtan uca: DUMP+yüksek ATR → gridler `[2,4,6,8]` (degenerate değil), buy toplam ×0.3, `"false"`→False.
