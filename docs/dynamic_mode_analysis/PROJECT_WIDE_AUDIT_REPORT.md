# Dinamik Mod Proje-Geneli Kod ve Mantık Hatası Denetim Raporu

> Tarih: 2026-06-16  
> Kapsam: `docs/dynamic_mode_analysis/` altındaki 320 soruluk analiz, `app/botengine/dynamic/`, gerçek DCA/grid strateji kullanımı, API/config kapıları, UI/leaderboard yüzeyi ve ilgili testler.  
> Amaç: Dinamik modun para/pozisyon davranışını etkileyen mantık hatalarını, kod buglarını, eksik korumaları ve test boşluklarını düzeltilebilir şekilde çıkarmak.

---

## 1. Kısa Sonuç

Mevcut sistemin güvenlik iskeleti güçlü: snapshot immutable, stale veri fallback'i var, risk engine clamp/rate-limit uyguluyor, manuel mod baypas ediliyor ve max buy levels/daily loss gibi ana emniyetler korunuyor. Bu iyi taraf.

Asıl problem, karar motorunun "zengin veri topluyor ama dar karar veriyor" olması. Raporun ilk halinde `features.py` RSI, spread, 24h hacim, 1h ATR, wick/body ve realized vol toplarken `strategy_engine.suggest()` pratikte sadece `atr_pct_5m + regime tuning` ile değer üretiyordu; ayrıca `REGIME_TUNING` içindeki `buy_levels_mult` alanı kullanılmıyordu.

**Son durum (2026-06-16):** Dinamik mod artık ilk turu manuel şablonla başlatır; grid tetik yüzdelerini manuel seviyenin altına çekmez; grid miktar yüzdelerini manuel şablondaki gibi korur. Bu, 0.30/0.60 gibi aşırı dar dinamik gridlerin ve 47.6/52.4 benzeri anlaşılması zor qty dönüşümlerinin önüne geçer.

Ek olarak, proje-geneli gerçek bir kod bugı var: `dynamic_mode` bazı yerlerde `bool(value)` ile parse ediliyor. Python'da `"false"` string'i truthy olduğu için API veya eski config `"dynamic_mode": "false"` gönderirse sistem bunu açık kabul edebilir.

---

## 2. Önceliklendirilmiş Bulgular

| Öncelik | Bulgu | Etki | Kanıt |
|---|---|---|---|
| P0 | `dynamic_mode="false"` string'i açık sayılabilir | Kullanıcı/entegrasyon dinamik modu kapattığını sanarken açık kalabilir | `app/botengine/models.py:154`, `app/botengine/models.py:444`, `app/botengine/dynamic/safety_gate.py:128` |
| P0 | `buy_levels_mult` ölü config | DUMP/TRENDING_DOWN/BREAKOUT alım azaltma niyeti uygulanmıyor | `strategy_engine.py:69-126`, kullanım yok; buy qty sadece `position_state` ile yarılanıyor `strategy_engine.py:272-283` |
| P0 | Yüksek ATR'de gridler 8%'e çöküp aynı seviyeye yığılabiliyor | Paralel grid motoru aynı eşikte çoklu alım/satım tetikleyebilir | `risk_engine.py:28-32`, `strategy_engine.py:190-196`, strateji paralel tetikler `dca_grid_trailing.py:893-925` |
| P1 | RSI/likidite feature'ları karara girmiyor | Aşırı alımda alım, aşırı satımda satış/re-entry, illiquid coinde kötü dolum riski | `features.py:184-211`; `suggest()` bu alanları kullanmıyor `strategy_engine.py:200-297` |
| P1 | DUMP_RISK flash crash yakalamıyor | Ani 5m düşüş, 1h EMA slope geciktiği için kaçabilir | `regime.py:101-112` |
| P1 | Fee/min-notional farkındalığı öneri katmanında yok | Fee altı/dar gridler üretilir, sonra strateji skip eder; UI ve snapshot yanıltıcı olur | `strategy_engine.py:168`, `dca_grid_trailing.py:846-862`, `dca_grid_trailing.py:1079-1092` |
| P1 | Histerezis fiilen kapalı | Rejim ilk farklı raw sınıflamada hemen değişir | `regime.py:50-54`, `regime.py:194-205` |
| P1 | `confidence` neredeyse dekoratif | Düşük güvenli rejimle yüksek güvenli rejim aynı agresifliği üretir | Tek kullanım `strategy_engine.py:253-258` |
| P2 | SQUEEZE/BREAKOUT zaman dilimi asimetrisi | 1h verisi azsa SQUEEZE yok, BREAKOUT 5m fallback ile açılabilir | `regime.py:83`, `regime.py:114-123`, `features.py:192-198` |
| P2 | Leaderboard snapshot feature adı hatalı | `spread_pct` toplanıyor ama leaderboard `spread_bps` arıyor; spread görünmez | `features.py:206`, `leaderboard_service.py:198-200` |

---

## 3. P0 Bulgular

### P0.1 `dynamic_mode` string parse bugı

Kodun üç kritik yerinde boolean parse, Python truthiness ile yapılıyor:

- `DcaGridTrailingConfig.__init__`: `self.dynamic_mode = bool(r.get("dynamic_mode") or False)` (`app/botengine/models.py:154`)
- `config_from_ui_payload`: `dynamic_on = bool(payload.get("dynamic_mode") or False)` (`app/botengine/models.py:444`)
- runtime gate: `if not bool(cfg_dict.get("dynamic_mode"))` (`app/botengine/dynamic/safety_gate.py:128`)

Bu şu anlama gelir:

```python
bool("false") == True
bool("0") == True
bool("off") == True
```

Leaderboard tarafında doğru parse edilmiş ayrı bir helper var: `_cfg_dynamic_enabled()` string `"false"` için `False` döndürüyor (`app/services/leaderboard_service.py:137-143`) ve bunun testi var (`tests/test_leaderboard_dynamic_mode.py:19-21`). Fakat aynı helper config modeli ve safety gate tarafından kullanılmıyor.

**Gerçek risk (rapor anındaki durum):** API, script, migration veya eski config JSON string değer taşıyorsa bot dinamik modu kapalı sanırken açabilir. Rapor yazılırken `config_from_ui_payload()` bu durumda dynamic_on=True sayıp `daily_loss_limit_usd` otomatik enjekte edebiliyordu.

**Durum (2026-06-16):** Bu akış düzeltildi. `parse_bool()` ortak helper olarak kullanılıyor; `daily_loss_limit_usd` otomatik bütçe×%5 enjekte edilmiyor; safety gate yalnız aktif `max_buy_levels` ön koşulunu kontrol ediyor.

**Düzeltme önerisi:**

1. Ortak bir helper ekle: `parse_bool(v)`.
2. Kabul edilecek truthy: `true`, `1`, `yes`, `on`.
3. Kabul edilecek falsy: `false`, `0`, `no`, `off`, `""`, `None`.
4. `models.py`, `safety_gate.py`, API/UI public helpers aynı helper'ı kullansın.
5. Test ekle:
   - `DcaGridTrailingConfig({"dynamic_mode": "false"}).dynamic_mode is False`
   - `config_from_ui_payload({"dynamic_mode": "false", ...}).dynamic_mode is False`
   - `is_dynamic_mode_active({"dynamic_mode": "false", ...}) is False`

---

### P0.2 `buy_levels_mult` tanımlı ama uygulanmıyor

**Son durum (2026-06-16):** Ürün kararı değişti. `buy_levels_mult` tablodan kaldırıldı; dinamik mod grid qty yüzdelerini artık bilerek değiştirmiyor. Savunma base/quote hedefi ve grid mesafesiyle yapılıyor.

`REGIME_TUNING` her rejim için `buy_levels_mult` tanımlıyor:

- `HIGH_VOL_RANGING`: 0.7
- `TRENDING_UP`: 0.8
- `TRENDING_DOWN`: 0.5
- `BREAKOUT`: 0.6
- `DUMP_RISK`: 0.3

Kanıt: `app/botengine/dynamic/strategy_engine.py:69-126`.

Fakat `suggest()` içinde bu değer hiç okunmuyor. Grid trigger'ları `step_mult` ile, qty dağılımı ise sabit `distribution_growth=1.20` ile kuruluyor (`strategy_engine.py:235-241`). Alım miktarını azaltan tek mekanizma, buy seviyelerinin %70'i dolunca tüm buy grid qty'lerini yarıya indirmek (`strategy_engine.py:272-283`).

**Mantık hatası:** Tuning tablosu "panic/düşüş rejiminde daha az yeni alım" diyor, ama gerçek bot ilk alımları normal dağıtıyor. DUMP'ta base allocation %15'e iniyor, fakat quote tarafı yine buy gridlere tam dağıtılıyor. Bu nakit koruma niyetini "nakdi daha aşağıdaki gridlere yatır" davranışına dönüştürebilir.

**Gerçek motor etkisi:** Buy grid miktarı `_buy_qty_for_grid()` içinde `quote_ref * buy_qty_pct_of_quote` olarak kullanılıyor (`app/botengine/strategies/dca_grid_trailing.py:1142-1153`). Yani suggestion katmanındaki qty yüzdesi doğrudan emir notional'ına dönüyor.

**Düzeltme seçenekleri:**

1. `buy_levels_mult` gerçekten qty toplamına uygulansın:
   - buy grid manual_total = manual_total × buy_levels_mult
   - DUMP 45% toplam manuel buy dağılımı örneğin 13.5%'e iner.
2. Ya da bu alan tablodan kaldırılıp niyet açıkça silinsin.
3. Daha iyi çözüm: `buy_levels_mult` + RSI + spread + max_buy usage birlikte `buy_budget_mult` olarak hesaplanmalı.

Önerilen test:

```python
dump_buy_total < trending_down_buy_total < low_vol_buy_total
```

---

### P0.3 Yüksek ATR'de gridler aynı %8 seviyesine yığılabiliyor

Grid yüzdeleri lineer kuruluyor: `step * (i + 1)` (`strategy_engine.py:190-196`). Risk engine her grid yüzdesini ayrı ayrı `grid_step_pct` sınırına sokuyor; üst sınır 8.0 (`risk_engine.py:28-32`, `risk_engine.py:147-153`).

Örnek:

- ATR clamped = 6
- base_step = 0.7 × 6 = 4.2
- DUMP step_mult = 2.0
- step = 8.4
- Gridler: 8.4, 16.8, 25.2, 33.6
- Risk clamp sonrası: 8, 8, 8, 8

Bu sadece "monoton ama eşit" değil; gerçek strateji paralel grid tetiklemeye izin veriyor (`app/botengine/strategies/dca_grid_trailing.py:893-925`). Alışta aynı fiyat düşüşünde birden fazla buy grid armed olabilir. `max_buy_levels` yürütme anında bloklar (`dca_grid_trailing.py:820-842`), ama ilk birkaç grid yine aynı eşikte emir üretebilir.

**Etki:** Dinamik mod, yüksek vol/dump durumunda DCA derinliğini artırmak yerine tüm DCA seviyelerini tek noktaya sıkıştırıyor. Bu, "derine yayılmış risk" yerine "aynı düşüşte toplu risk" doğurur.

**Düzeltme önerisi:**

1. Clamp sonrası eşitlenen gridleri tespit et.
2. Eşitlenme olursa:
   - grid sayısını azalt,
   - veya toplam derinliği koruyacak şekilde `max_depth_pct` ve spacing normalize et,
   - veya her seviye için bound yerine toplam ladder bound kullan.
3. Test ekle: yüksek ATR + DUMP için buy grid pct değerleri unique/non-degenerate olmalı ya da grid sayısı bilinçli azalmalı.

---

## 4. P1 Mantık Hataları

### P1.1 Toplanan feature'ların çoğu karar üretmiyor

`collect_features()` şunları topluyor:

- ATR 5m/1h
- BBW 5m/1h
- realized vol 5m
- wick/body ratio
- RSI 5m/1h
- ADX 1h
- EMA slope 1h
- volume z-score
- spread
- 24h quote volume

Kanıt: `app/botengine/dynamic/features.py:184-211`.

Karara gerçek etki edenler:

- Rejim: `atr_pct_5m`, `bbw_1h/bbw_5m`, `adx_1h`, `ema_slope_1h_pct`, `volume_zscore_5m`
- Strateji: pratikte `atr_pct_5m` + rejim etiketi

RSI, spread, 24h volume, 1h ATR, wick/body, realized vol suggestion'a girmiyor.

**Neden önemli?**

- RSI > 70: yeni alımı kısmak gerekirken yapılmıyor.
- RSI < 30: satış/re-entry davranışı daha dikkatli/istekli ayarlanabilirken yapılmıyor.
- spread yüksek: grid/trailing dar ise kötü dolum riski artıyor.
- volume_24h düşük: illiquid coin'de aynı agresiflik korunuyor.
- wick/body yüksek: chop/fake move teyidi olarak kullanılmıyor.

**Düzeltme önerisi:**

1. `FeatureAdjustment` gibi küçük ve test edilebilir bir katman ekle.
2. Örnek:
   - `rsi_1h > 70`: buy qty × 0.5, base target max 50
   - `rsi_1h < 30`: sell qty × 0.7, reentry drop biraz azalt
   - `spread_pct > threshold`: grid step/trailing min spread×k
   - `volume_24h_usdt < min`: dynamic active ama alım mult düşük veya bot uyarı verir

---

### P1.2 DUMP_RISK "flash crash" değil, gecikmeli trend+volume sinyali

DUMP şu şartla açılıyor:

```python
slope <= -2.0 and volume_zscore >= 2.0
```

Kanıt: `app/botengine/dynamic/regime.py:101-112`.

`slope`, 1h EMA(20)'nin 5 barlık eğimi. Bu yaklaşık 5 saatlik, yumuşatılmış bir sinyal. Ani 5m düşüşte 1h EMA slope henüz -2 olmayabilir. Ayrıca hacim şartı AND olduğu için hacimsiz ama tehlikeli düşüşler DUMP sayılmaz.

**Düzeltme önerisi:**

1. 5m kapanmış mumdan hızlı drop sinyali ekle.
2. DUMP kriterini iki yollu yap:
   - hızlı drop: `last_closed_5m_return <= -x`
   - veya trend dump: `ema_slope_1h <= -2 and vol_z >= 2`
3. Volume spike olmadan yavaş sızıntı düşüşünü `TRENDING_DOWN_HIGH_RISK` gibi ayrı ele al.

---

### P1.3 Histerezis mekanizması var ama fiilen çalışmıyor

`MIN_DWELL_CYCLES = 1` (`regime.py:50-54`). `classify()` içinde farklı rejim ilk görüldüğünde streak 1 oluyor ve `streak >= MIN_DWELL_CYCLES` şartını hemen geçiyor (`regime.py:194-205`).

Bu yüzden "candidate bekletme" ve `confidence * 0.5` dalı pratikte ölü.

**Nüans:** Snapshot yalnız cycle başında hesaplandığı için bu her tick flip-flop yaratmaz. Yine de ardışık cycle'larda eşik çevresinde rejim bir anda değişir.

**Düzeltme önerisi:**

Cycle-bazlı dwell'i 2 yapmak tek başına fazla ağır olabilir. Daha iyi yaklaşım:

- Raw rejimi tick/time bazlı hafif takip et.
- Applied rejimi cycle başında değiştir.
- Dwell'i cycle sayısından çok "son N dakika / son N feature refresh" ile ölç.

---

### P1.4 Confidence kararı neredeyse etkilemiyor

Confidence yalnız şu yerde kullanılıyor:

```python
if TRENDING_DOWN and confidence < 0.6:
    target_base = max(target_base, 35.0)
```

Kanıt: `app/botengine/dynamic/strategy_engine.py:253-258`.

Step, trail, buy qty, tp/reentry ve smoothing alpha confidence'a bağlı değil. 0.45 güvenli ve 0.90 güvenli aynı parametreleri üretebilir.

**Düzeltme önerisi:**

- `confidence` düşükse parametreler manuel config'e yaklaşmalı.
- Smoothing alpha düşük confidence'ta azalmalı.
- Rejim değişimi düşük confidence'ta daha az agresif yansımalı.

---

### P1.5 Fee/min-notional öneri katmanında yok

Dinamik grid step min'i `max(0.05, ...)` (`strategy_engine.py:168`). Bu fee'yi bilmiyor. Düşük ATR'de gridler 0.10-0.30% aralığına sıkışabilir. Kâr çıkışı fee-aware olabilir, ama grid tetik/spacing ekonomik olmayabilir.

Gerçek strateji min notional'ı emirden önce kontrol edip skip edebiliyor (`dca_grid_trailing.py:846-862`, `dca_grid_trailing.py:1079-1092`). Bu çöküşü engeller ama öneri/snapshot/UI tarafında çalışmayacak gridler görülebilir.

**Düzeltme önerisi:**

- `min_grid_step_pct >= k * (buy_fee + sell_fee + min_net_profit_rate)` uygulanmalı.
- `min_notional_guard` ve budget/alloc/qty oranları suggestion'da hesaba katılmalı.
- Emirde skip olacak gridler snapshot'ta daha baştan azaltılmalı veya disabled reason ile işaretlenmeli.

---

## 5. P2 Bulgular

### P2.1 SQUEEZE/BREAKOUT veri asimetrisi

`bbw = f.bbw_1h if f.bbw_1h is not None else f.bbw_5m` ile BREAKOUT fallback alıyor (`regime.py:83`, `regime.py:114-118`). SQUEEZE ise sadece `f.bbw_1h` ile çalışıyor (`regime.py:120-123`). 1h verisi 40 mumdan azsa 1h indikatörleri hiç hesaplanmıyor (`features.py:192-198`).

**Etki:** Yeni coin / az veri durumunda squeeze imkansız, breakout 5m ile mümkün. Bu rejim davranışı zaman dilimi açısından tutarsız.

**Düzeltme:** Ya iki rejim de 1h-only olsun, ya ikisi de açıkça time-frame-aware confidence ile fallback kullansın.

---

### P2.2 BREAKOUT yön-kör

BREAKOUT = BBW genişleme + hacim spike. Yön yok. Aşağı kırılımda da `BREAKOUT` olur ve base target 50 kalır (`strategy_engine.py:105-110`).

**Düzeltme:** BREAKOUT'u `BREAKOUT_UP` / `BREAKOUT_DOWN` veya `BREAKOUT` + direction reason olarak ayır. Direction için 5m/1h close return, EMA slope veya DI farkı kullanılabilir.

---

### P2.3 UI/leaderboard feature isim uyumsuzluğu

`features.py` spread'i `spread_pct` olarak saklıyor (`features.py:206`). Leaderboard public snapshot ise `spread_bps` anahtarını seçmeye çalışıyor (`app/services/leaderboard_service.py:198-200`). Bu yüzden spread verisi toplansa bile leaderboard dynamic modalında görünmez.

**Düzeltme:** Ya `spread_pct` göster, ya features tarafında ayrıca `spread_bps = spread_pct * 100` üret.

---

## 6. Doğru Çalışan / Korunması Gereken Kısımlar

1. **Snapshot yaşam döngüsü temiz.** `need_recompute()` snapshot yoksa, cycle değiştiyse veya recompute flag varsa yeniliyor (`cycle_manager.py:53-62`). Tur içinde snapshot tekrar kullanılabiliyor.
2. **Stale veri fallback'i güvenli.** Veri stale ise prev applied veya manuel cfg kullanılıyor (`cycle_manager.py:98-133`).
3. **Overlay alanları sınırlı.** `max_buy_levels`, `daily_loss_limit_usd`, symbol, fee, safety alanları overlay edilmez (`cycle_manager.py:222-255`).
4. **Risk engine çökmez.** NaN/invalid fallback, hard bound clamp ve scalar rate-limit var (`risk_engine.py:90-128`, `risk_engine.py:179-235`).
5. **Max buy levels gerçek emir akışında korunuyor.** Buy execution öncesi limit kontrolü var (`dca_grid_trailing.py:820-842`).
6. **Min notional gerçek emirden önce kontrol ediliyor.** Çalışmayacak emir skip ediliyor (`dca_grid_trailing.py:846-862`, `dca_grid_trailing.py:1079-1092`).
7. **Testler temel invariant'ları kapsıyor.** Bound, allocation toplamı, monotonic grid, anti-martingale, snapshot immutability, stale fallback testleri mevcut (`tests/test_dynamic_mode_e2e.py:160-240`).

Bu kısımlar düzeltilirken korunmalı. Özellikle dynamic mode fix'leri risk engine'in "son söz" rolünü zayıflatmamalı.

---

## 7. Test Boşlukları

Mevcut testler çoğunlukla "değer bound içinde mi / sistem çökmeden snapshot üretiyor mu" seviyesinde. Eksik davranış testleri:

1. `dynamic_mode="false"` config ve gate testleri.
2. `buy_levels_mult` rejime göre buy toplamını gerçekten düşürüyor mu?
3. DUMP yüksek ATR senaryosunda gridler aynı %8'e yığılıyor mu?
4. Düşük ATR senaryosunda fee altı grid üretiliyor mu?
5. RSI overbought/oversold strategy output'u değiştiriyor mu?
6. Spread/volume düşük likidite durumunda strategy output'u değiştiriyor mu?
7. SQUEEZE 1h missing / BREAKOUT 5m fallback tutarlılığı.
8. `confidence` düşükken smoothing/agresiflik azalıyor mu?
9. Leaderboard `spread_pct` gösterimi.

Özellikle ilk dört test P0/P1 seviyesinde yazılmalı. Şu an test paketi bu hataları yakalayacak şekilde tasarlanmamış.

---

## 8. Önerilen Düzeltme Sırası

### Aşama 1 - Para davranışını bozan buglar

1. Ortak bool parse helper'ı ekle ve `dynamic_mode` parse edilen her yerde kullan.
2. `buy_levels_mult`'ı buy qty toplamına bağla.
3. Yüksek ATR grid degeneracy için test yaz ve düzelt.

### Aşama 2 - Ekonomik minimumlar

4. Grid step için fee-aware minimum ekle.
5. Suggestion katmanında min-notional/budget awareness ekle.
6. Snapshot reasons içine "grid ekonomik değil, azaltıldı/atlandı" bilgisi yaz.

### Aşama 3 - Karar zenginliği

7. RSI'yi alım/satım/reentry agresifliğine bağla.
8. Spread ve 24h hacim ile likidite kapısı ekle.
9. Confidence'ı alpha ve tuning intensity için kullan.

### Aşama 4 - Rejim doğruluğu

10. DUMP_RISK'e 5m hızlı düşüş sinyali ekle.
11. BREAKOUT'u yönlü hale getir.
12. SQUEEZE/BREAKOUT fallback politikasını aynı standarda çek.
13. Histerezisi cycle dışı raw tracking veya confidence-weighted yaklaşım ile gerçek hale getir.

---

## 9. Dosya Bazlı Düzeltme Haritası

### `app/botengine/models.py`

- `dynamic_mode` parse helper kullanmalı (`models.py:154`, `models.py:444`).
- `config_from_ui_payload()` string false durumunda daily loss enjekte etmemeli.

### `app/botengine/dynamic/safety_gate.py`

- `is_dynamic_mode_active()` raw bool yerine ortak parse helper kullanmalı (`safety_gate.py:121-130`).
- Dynamic depth guard, dinamik grid 8%'e sıkıştığında guard'ı da 13%'e sıkıştırıyor (`safety_gate.py:171-184`). Grid degeneracy düzeltildikten sonra guard da gerçek efektif ladder'a göre çalışmalı.

### `app/botengine/dynamic/strategy_engine.py`

- `buy_levels_mult` kullanılmalı veya kaldırılmalı (`strategy_engine.py:69-126`).
- `_build_grid_levels()` fee/min-depth aware olmalı (`strategy_engine.py:141-197`).
- `sell_trail == buy_trail` simetrisi gözden geçirilmeli (`strategy_engine.py:246-250`).
- `tp_drop`, `re_drop`, `re_rise` rejim-kör kalmamalı (`strategy_engine.py:262-267`).
- `smooth_against_prev()` alpha confidence'a bağlanabilir (`strategy_engine.py:305-344`).

### `app/botengine/dynamic/regime.py`

- `MIN_DWELL_CYCLES=1` histerezisi pratikte kapatıyor (`regime.py:50-54`).
- DUMP 1h EMA slope + vol_z şartıyla gecikmeli (`regime.py:101-112`).
- BREAKOUT yön-kör (`regime.py:114-118`).
- SQUEEZE 1h-only, BREAKOUT fallback'li (`regime.py:83`, `regime.py:120-123`).

### `app/botengine/dynamic/features.py`

- Feature set iyi ama karar katmanı kullanmıyor (`features.py:184-211`).
- Forming candle konusu ayrıca ele alınmalı: klines son mumu içeriyor; volume z-score dışında indikatörler bunu dışlamıyor.

### `app/botengine/strategies/dca_grid_trailing.py`

- Paralel trigger gerçek davranış, bu yüzden dynamic grid yığılması kritik (`dca_grid_trailing.py:893-925`).
- Min notional emir öncesi skip iyi, ama suggestion katmanına daha erken taşınmalı (`dca_grid_trailing.py:846-862`, `dca_grid_trailing.py:1079-1092`).

### `app/services/leaderboard_service.py`

- `_cfg_dynamic_enabled()` doğru helper mantığını içeriyor; ortaklaştırılabilir (`leaderboard_service.py:137-143`).
- `spread_bps` / `spread_pct` isim uyumsuzluğu düzeltilmeli (`leaderboard_service.py:198-200`).

---

## 10. Nihai Değerlendirme

Dinamik mod "güvenlik açısından çökmez" seviyesine yakın; fakat "piyasa rejimine göre gerçekten akıllı ve ekonomik karar üretir" seviyesinde eksikler var. En kritik iki fark:

1. Kodun güvenlik katmanı sağlam.
2. Karar katmanı eksik bağlı, bazı niyetler ölü, bazı ekonomik gerçekler geç katmanda yakalanıyor.

Bu yüzden ilk sprintte indikatör formüllerine dokunmak yerine şu üç işi yapmak en yüksek getiriyi verir:

1. `dynamic_mode` bool parse bugını düzelt.
2. `buy_levels_mult` ve grid degeneracy sorunlarını düzelt.
3. Fee/min-notional farkındalığını suggestion katmanına taşı.

Bu üçü düzelmeden RSI/likidite gibi daha rafine sinyaller eklense bile sistemin temel davranışı hâlâ yanlış veya yanıltıcı kalabilir.
