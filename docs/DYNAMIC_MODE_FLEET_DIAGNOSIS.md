# Dinamik Mod — 10 Botluk Filonun Derin Teşhisi

> **Rapor tarihi:** 2026-06-22
> **Yöntem:** Canlı Binance ticker fiyatları + `~/.trader/dca.db` üzerinde `bot_engine_state` / `bot_engine_events` / `bot_virtual_wallet` çözümü + 47 turluk `dynamic_snapshot.history` + kaynak kod okuması
> **Gözlem penceresi:** 2026-06-16 21:50 → 2026-06-22 05:43 (≈ **5.33 gün / 128 saat**)
> **Kapsam:** account_id=2 test (paper) hesabı, 10 DCA-Grid-Trailing bot, hepsi `dynamic_mode=true`, 1000 USDT, base %50, `max_buy_levels=3`, grid şablonu 1/2/3% @ qty 30/30/40
> **Kaynak kod:** `app/botengine/dynamic/`, `app/botengine/strategies/dca_grid_trailing.py`, `app/botengine/orchestrator.py`
> **İlişki:** Bu rapor [`DYNAMIC_MODE_TECHNICAL.md`](DYNAMIC_MODE_TECHNICAL.md)'nin canlı-veri eleştirel tamamlayıcısıdır.

---

## 0. Tek cümlelik hüküm

> Dinamik mod **disiplinli, güvenli-by-construction ve realize tarafında kârlı** (kapanan turlar net **+124.6 USDT**, devreye giren her bot kapalı-tur bazında pozitif). Ama **kaybın yaşadığı yere hiç dokunmuyor** — açık envanter **−392.7 USDT** batık, filo net **−268.1 USDT (−%2.68)**. Üstelik motorun en gelişmiş parçası (ATR×rejim grid adımı) pratikte **atıl**, "düşen bıçak" koruması (`cycle_gate`) production'da **hiç kurulmadı**, ve adaptif katman en çok ihtiyaç duyan 6 botta (cycle-1'de takılı) **yapısal olarak çalışamıyor.**

Bu bir **bug raporu değildir**. Tüm botlarda risk-motoru clamp'ları ve fallback'ları boş; mimari temiz. Sorun, **kaldıraçların yanlış yere bağlı olmasıdır.**

---

## 1. Tur sınırında ne oluyor? (mekanizma özeti)

Her tick'te, `strategy.tick()`'ten **önce**, orkestratör tur-sınırı boru hattını çalıştırır (`cycle_manager.build_snapshot`):

| Adım | Fonksiyon | İş |
|------|-----------|----|
| 1 | `dynamic_overlay_allowed` | `cycle_id ≥ 2` değilse **çık** (ilk tur manuel) |
| 2 | `features.collect_features` | 5m/1h kline → ATR, ADX, RSI, EMA-eğim, hacim-z, spread |
| 3 | `regime.classify` | 8 rejimden biri + güven (histerezisli) |
| 4 | `strategy_engine.suggest` | 6 parametre önerisi + sürekli **stance** (pasif↔agresif) |
| 5 | `smooth_against_prev` | EMA harman, `alpha = 0.3 + 0.4·güven` |
| 6 | `risk_engine.apply_safety` | clamp + rate-limit |
| 7 | `cycle_gate.evaluate` | yeni turu yüksek riskte **beklet** (yalnız cycle≥2, engage olmadan) |

Snapshot **immutable**: tur içinde parametreler sabit kalır, yalnızca tur sınırında yeniden hesaplanır.

---

## 2. Gerçek finansal tablo (canlı fiyatlarla)

Fiyatlar 2026-06-22'de canlı çekildi: BTC 64261.21, ETH 1737.38, SOL 74.03, AVAX 6.306, LTC 45.02, XRP 1.1364, ADA 0.1603, XLM 0.2125, DOGE 0.08339, LINK 7.943.

| Bot | Sembol | Tur | Birikmiş **realize**¹ | Açık **batık**² | Equity | Toplam |
|----|--------|----:|---------:|---------:|------:|-----:|
| 26 | XLMUSDT | **15** | **+101.86** | −62.91 | 1039.0 | **+3.90%** |
| 21 | SOLUSDT | **9** | **+24.38** | −1.10 | 1023.3 | **+2.33%** |
| 22 | AVAXUSDT | 5 | +7.64 | −83.30 | 924.3 | −7.57% |
| 28 | LINKUSDT | 6 | −1.64 | −23.79 | 974.6 | −2.54% |
| 18 | BTCUSDT | **1** | −1.25 | −15.99 | 982.8 | −1.72% |
| 19 | ETHUSDT | **1** | −1.25 | −25.31 | 973.4 | −2.66% |
| 23 | LTCUSDT | **1** | −1.36 | −9.82 | 988.8 | −1.12% |
| 24 | XRPUSDT | **1** | −1.29 | −60.70 | 938.0 | −6.20% |
| 25 | ADAUSDT | **1** | −1.25 | −71.06 | 927.7 | −7.23% |
| 27 | DOGEUSDT | **1** | −1.19 | −38.74 | 960.1 | −3.99% |
| | **FİLO** | | **+124.60** | **−392.70** | **9731.9** | **−2.68%** |

¹ `cycle_start_equity − 1000`: mevcut tur açıldığındaki birikmiş realize (trimlenmemiş; `cycle_pnls` ring-buffer'dan daha güvenilir).
² `equity − cycle_start_equity`: mevcut açık pozisyonun gerçekleşmemiş zararı.

Tutarlılık kontrolü: `+124.60 − 392.70 = −268.10` ✓ (filo net ile birebir).

### Profesör okuması — kısa gamma imzası

Bu, bir grid/martingale stratejisinin **imza profilidir**: küçük, pozitif, teta-benzeri getiri gidiş-dönüşlerden hasat edilir (realize sütunu); **tüm kuyruk riski fiyat düşerken biriken envanterde** yaşar (batık sütunu). XLM tek başına 14 turda **+101.9** realize üretmiş — *motor çalışıyor*. Ama aynı filo geniş bir piyasa düşüşünde fully-deployed yakalanıp **−392.7** gerçekleşmemiş zarara oturmuş. **Kaybın %100'ü envanter çekilmesidir, işlem mantığı değil.** Strateji "buharlı silindirin önünde kuruş toplama" (short-gamma) profili sergiliyor.

### Küme karşılaştırması (dürüstçe)

| Küme | Equity / Yatırılan | Getiri |
|------|----|----|
| Dinamik-devreye-giren (SOL/AVAX/XLM/LINK) | 3961.1 / 4000 | **−0.97%** |
| Cycle-1'de takılı, saf manuel (BTC/ETH/LTC/XRP/ADA/DOGE) | 5770.8 / 6000 | **−3.82%** |

Fark cazip görünüyor **ama dürüst istatistik bunu motora yazamaz**: kümeler *sonuca göre* seçilmiş (survivorship bias — bkz. Bulgu 1). Bir bot dinamik moda ancak 1. turu kapatarak (kazanarak) ulaşıyor. Bu fark, motorun değerinin kanıtı **değildir.**

---

## 3. Ampirik zamanlama — "takılı tur" olgusu

`bot_engine_events` (CYCLE_START / CYCLE_END) gerçek kadansı gösteriyor:

- **Yıldız botların kadansı bursty.** XLM (bot 26): tur 8→9→10 her biri ~1 saatte kapanmış (ranging hasat kümesi), ama tur 12→13 arası **12 saat** (trend boyunca bekleme).
- **Kazananlar bile zamanlarının çoğunu batık turlarda geçiriyor.** SOL (bot 21): tur 4 kapanışı 2026-06-17 19:06 → tur 5 kapanışı 2026-06-21 09:37. Yani **tek bir tur 3.6 gün sürmüş** — bot 5. turun envanterini bir çekilme boyunca tutmuş, sonra toparlanmada kapatmış.
- **6 takılı bot tam olarak bu durumda**, sadece henüz toparlanmayı yakalamadılar. Yani onların "tek tur kapatamamış" olması bir bot arızası değil; **piyasa rejiminin sonucu** + envanter korumasının yokluğu.

**Çıkarım:** "Takılı tur", filonun normal işleyiş hâlinin bir parçası. Strateji bunu zaman + toparlanma ile çözüyor. Risk, toparlanma gelmediğinde sınırsız.

---

## 4. Derin bulgular (matematikle, kanıtla)

### Bulgu 1 — "İlk tur manuel" kapısı, ters seçilim (adverse selection) üretiyor

`cycle_manager.dynamic_overlay_allowed` → `cycle_id ≥ 2` (`FIRST_DYNAMIC_CYCLE_ID = 2`). Bir bot ancak **1. turu kârla kapatarak** 2. tura ulaşır. Dolayısıyla **dinamik moda giriş, "zaten kazanmış olmak" şartına koşullu.**

**Kanıt (events):** 6 bot (18,19,23,24,25,27) → 1 CYCLE_START, **0 CYCLE_END**. 6 gündür tek tur kapatamamışlar; hepsi 3/3 alım dolmuş (`_buy_levels_fired=3`, `_buy_levels_blocked=true`), ~$2 quote kalmış. Onları de-riske edebilecek adaptif katman **tam da onlarda kapalı.**

Bu, [`DYNAMIC_MODE_TECHNICAL.md`]'deki "ilk tur manuel" ilkesinin istenmeyen yan etkisi: **en büyük ve korumasız tahsis (cycle-1, %50 base) hiçbir adaptif/risk kapısı görmüyor; oysa hasarın çoğu orada oluşuyor.**

### Bulgu 2 — Motorun tacı (ATR×rejim grid adımı) **atıl**: manuel %1 tabanına kaynaklı

`strategy_engine._build_grid_levels` her seviyede `max(dinamik_adım, manuel_adım)` alır. Manuel şablon 1/2/3%. Dinamik adım = `K_ATR · ATR5m · step_mult`, `K_ATR = 0.7`. Level-1 dinamiğin manueli geçmesi için:

```
ATR5m > 1.0 / (0.7 · step_mult)
```

| Rejim | step_mult | Gereken ATR5m |
|------|-----:|-----:|
| LOW_VOL_RANGING | 0.8 | **>%1.79** |
| SQUEEZE | 0.9 | >%1.59 |
| TRENDING_UP | 1.2 | >%1.19 |
| HIGH_VOL_RANGING | 1.4 | >%1.02 |
| TRENDING_DOWN | 1.5 | >%0.95 |
| BREAKOUT | 1.6 | >%0.89 |
| DUMP_RISK | 2.0 | >%0.71 |

**Kanıt:** Gözlemlenen ATR5m aralığı **0.21–1.13%**. 47 turun **hepsinde** uygulanan `grid_step_first = 1.000`. En yüksek ham dinamik adım 0.731 (XLM, tur 7, BREAKOUT) bile manuel 1.0'ın altında kalıp `max()` ile eziliyor:

```
bot 21: grid_step raw=0.432 → applied buy_grid[0]=1.0
bot 22: grid_step raw=0.323 → applied buy_grid[0]=1.0
bot 26: grid_step raw=0.731 → applied buy_grid[0]=1.0
bot 28: grid_step raw=0.318 → applied buy_grid[0]=1.0
```

Yani `suggest()`'in en ayrıntılı kodu (ATR clamp → fee-floor → depth-cap → regime step_mult) **grid geometrisine sıfır etki** etti. Grid ne yüksek volde genişledi ne sakinde daraldı.

**Finansal sonucu:** En derin seviye manuel %3'e kaynaklı. Gerçek bir düşüşte grid **fazla dar** — fiyat sadece **−%3** düşünce 3 seviye de dolup bot **%100 yüklenir**, kuru barut sıfırlanır. 6 takılı botun başına gelen tam olarak budur (giriş→ −5…−9%, üç seviye de yanmış, beklemede).

### Bulgu 3 — Rejim salınımı + düşük güven → tahsis kamçılanması (whipsaw)

XLM (bot 26), tur 6→15:

```
DOWN(.70) BRK(.70) RNG(.50) RNG(.50) RNG(.50) RNG(.40) RNG(.40) UP(.56) UP(stale) DOWN(.42)
 35.5  →  43.9  →  47.0  →  48.5 →  49.2 →  49.6 →  49.8 →  55.1 → (stale) → 45.7   (base %)
```

Base tahsisinde **19.6 puanlık** tepe-dip salınımı, büyük ölçüde **güven 0.40–0.56** (yazı-tura seviyesi) rejim çağrılarından. Her rejim dönüşü base/quote'u mekanik rebalance eder → rejim-değişim fiyatından alıp satar (potansiyel buy-high/sell-low). Yumuşatma `alpha = 0.3 + 0.4·güven`; güven 0.40'ta alpha **0.46** — yani yazı-tura bir çağrıya **%46 ağırlık**. **Düşük güvenli rejimler için yumuşatma fazla geçirgen.**

### Bulgu 4 — Rejim/momentum çelişkisi (SOL, şu anki snapshot)

Bot 21'in mevcut snapshot'ı, rejim ile momentumun **doğrudan çeliştiği** bir durumu donmuş hâlde gösteriyor:

| Sinyal | Değer | Diyor ki |
|------|------|------|
| regime | TRENDING_DOWN (güven **0.42**) | aşağı |
| RSI_1h / RSI_5m | **60.2 / 59.0** | **yukarı (boğa)** |
| ema_slope_1h | −0.137% | ~yatay |
| ret_5m | −0.13% | ~yatay |
| ADX_1h | 28.4 | zayıf trend |
| → **stance** | **DEFENSIVE −0.39**, base **%36.8** (botun tarihindeki en düşük) | |

Aşağı-çağrısı neredeyse tümüyle "ADX≥25 + hafif negatif eğim"e dayanıyor; momentum (RSI ~60) bunu çürütüyor. Sonuç: **bot RSI 60'a doğru maksimum de-riske ediyor.** Ayrıca `reward_score = 0`, çünkü:

```
ranging = clamp01((ADX_TRENDING − adx)/ADX_TRENDING) = clamp01((25 − 28.4)/25) = 0
reward  = ranging · (0.6·atr_fit + 0.4·liq) = 0
```

ADX'in 25'i yalnızca **3.4 puan** aşması tüm grid ödülünü uçurumdan atıyor — oysa %0.41 ATR / RSI-60 / yatay eğim **mükemmel bir grid ortamı.** ADX kapısı 25'te **sert bir uçurum** (histerezis/yumuşak rampa yok).

Bu, hafıza notundaki [[param-assistant-decision-closure]] "teşhis kası A+, karar kası eksik" tespitinin canlı örneği: rejim etiketi ile momentum sinyali çelişiyor, kimse uzlaştırmıyor.

### Bulgu 5 — `cycle_gate` (düşen-bıçak koruması) **ölü yüzey**

HOLD için `risk ≥ HOLD_ON = 0.62` gerek. Baskın terimler `s_fast` (−%4'lük 5m bar = 1.0, w=0.30) ve `s_regime` (DUMP=1.0/DOWN=0.85, w=0.24). Paper modda `spread`/`volume` **null** → `s_spread=0`, `s_volz`/`s_dvol` kırpık. Bu veri setinde gerçekçi maksimum risk:

```
risk_max ≈ W_REGIME · s_regime + küçük momentum
        ≈ 0.24 · 0.85·(0.6+0.4·0.42) ≈ 0.16   →  0.62'nin çok altında
```

Major coinlerde −%4'lük tek 5m mum nadir; **DUMP_RISK 47 turda hiç çıkmadı.**

**Kanıt (events):** account-2 botlarında **tek bir `DYN_CYCLE_HOLD` olayı yok.** Yani tasarımı sağlam olan kapı **production'da hiç kurulmadı**; 6 takılı bot için ise (cycle≥2 sınırı yok) **yapısal olarak kurulamaz**. Koruma kâğıtta var, tape'te yok.

### Bulgu 6 — Kaybın yaşadığı yer hiç bağlı değil: envanter tavanı / DD-stop / günlük zarar yok

- `daily_loss_limit_usd = **0.0**` → günlük zarar devre kesici **kapalı** (config'de doğrulandı).
- `max_buy_levels = 3` @ 1/2/3% → fiyat **−%3** düşünce bot **%100 yüklü**, kuru barut sıfır, tek çıkış toparlanma.
- Bloklandıktan sonra **de-riske mekanizması yok** — bot yalnızca bekler. Girişten: AVAX −8.9%, ADA −8.0%, XRP −7.0%, DOGE −4.8%.
- Hiçbir yerde **envanter tavanı (<%100)** veya **çekilme-stop** yok.

Bu, [[param-assistant-decision-closure]]'da "YAPILMADI" diye işaretlenen **karşı-olgusal ablasyon (envanter tavanı + DD-stop)** ihtiyacının canlı kanıtı. **−392.7'nin tamamı burada yaşıyor.**

### Bulgu 7 — Paper modda kör girdiler

`spread_pct`, `spread_bps`, `volume_24h_usdt` hepsi **null**. Dolayısıyla:
- `liq` → 0.6 varsayılanına düşer (stance reward'ı sabitlenir)
- fee-floor spread bileşenini kaybeder (`SPREAD_FLOOR_MULT` etkisiz)
- `s_spread = 0`, `s_volz`/`s_dvol` zayıflar

**Uyarı:** Test hesabındaki bu sonuçlar okunurken bilinmeli — dinamik motor **kısmi duyularla** çalışıyor; canlı (gerçek orderbook) ortamda likidite/akış sinyalleri farklı davranabilir, sonuçlar birebir genellenemez.

---

## 5. Ne işliyor? (entelektüel dürüstlük)

Eleştiriler yapısal; ama mimarinin güçlü yanları gerçek ve korunmalı:

- **Realize kaydı sağlam.** Kapanan turların net toplamı **+124.6**; XLM 14 turda +101.9. Grid hasat mantığı çalışıyor.
- **Risk motoru sessiz ama hazır.** Tüm botlarda `clamps:[]`, `fallbacks:[]` — öneriler zaten güvenli bantta; motor müdahale etmek zorunda kalmamış.
- **Fail-safe'ler temiz.** Stale veri → önceki applied'a düşüş; exception → hold bırakma; hiçbir bot çökmemiş, donmamış.
- **Yumuşatma + güven-ölçekli alpha** mantıklı tasarlanmış (yalnızca düşük-güven eşiğinde fazla geçirgen — Bulgu 3).
- **Stance, yönü pekiştiriyor, ters çevirmiyor** (tasarım invariantı korunmuş).

**Tek cümle:** Sorun bug değil, *kapsam*. Bağlı kaldıraçlar (grid adımı) atıl; kaybı yöneten kaldıraç (envanter/DD) ise hiç bağlı değil.

---

## 6. Geçerliliğe tehditler (caveats)

1. **Tek piyasa penceresi.** 5.3 gün, genel olarak aşağı eğilimli bir tape. Yukarı/yatay rejimde profil farklı olur; bu rapor bir rejim örneğidir.
2. **Survivorship.** Küme karşılaştırması sonuca göre seçilmiş; nedensel atıf yapılamaz.
3. **Paper mod kör girdileri** (Bulgu 7) — likidite/akış sonuçları canlıda değişebilir.
4. **n küçük.** 4 bot dinamik moda girdi; 47 tur. İstatistiksel güç sınırlı; eğilim göstergesi, ispat değil.
5. **CYCLE_END meta'sında pnl taşınmıyor;** realize, `cycle_start_equity` proxy'siyle hesaplandı (sağlam ama dolaylı).

---

## 7. "En üst seviyeye çıkar" — önceliklendirilmiş yol haritası

| # | Müdahale | Hangi bulgu | Etki |
|--|----------|:--:|:--:|
| **P0** | **Envanter tavanı + çekilme-stop**: açık batık > eşik → yeni alım dur / kısmi de-riske; `daily_loss_limit_usd`'i etkinleştir (risk_engine + dca_grid_trailing) | 6 | 🔴 Kaybın %100'ü |
| **P0** | **Grid adımını tabandan ayır**: `max(dinamik, manuel)` yerine manuel=referans, dinamik adımı gerçekten uygula; veya derinlik-ölçekli taban (strategy_engine._build_grid_levels) | 2 | 🔴 Atıl motor |
| **P1** | **Düşük-güven rejim cezası**: güven<0.55'te alpha'yı kıs / base-swing'i dondur, momentum'a yaslan (strategy_engine + cycle_manager) | 3,4 | 🟡 Whipsaw |
| **P1** | **ADX kapısını yumuşat**: `ranging`'i 25'te uçurum yerine [20,30] rampası + RSI/regime çelişkisinde stance nötrleme | 4 | 🟡 |
| **P2** | **İlk-tur korumasını gözden geçir**: cycle-1 girişine en azından `cycle_gate`'i uygula (en büyük tahsis) | 1,5 | 🟡 |
| **P2** | **Karşı-olgusal ablasyon raporu**: envanter tavanı + DD-stop ile aynı 5 günü yeniden simüle et, −392.7 ne kadar küçülürdü göster | 6 | 🟢 |
| **P3** | **Dürüst atıf**: küme karşılaştırmasını survivorship'e karşı düzelt (turu kapatamayanları da dahil et) | 1 | 🟢 |

---

## Ek A — Tur-tur dinamik karar evrimi (history ring buffer)

### Bot 21 — SOLUSDT
```
cyc | regime          | güven | atr5m | adx1h | base% | trail% | grid_step
  2 | LOW_VOL_RANGING | 0.70  | 0.355 | 17.9  | 50.0  | 0.284  | 1.000
  3 | LOW_VOL_RANGING | 0.70  | 0.390 | 17.9  | 50.0  | 0.300  | 1.000
  4 | LOW_VOL_RANGING | 0.50  | 0.556 | 17.7  | 50.0  | 0.372  | 1.000
  5 | LOW_VOL_RANGING | 0.50  | 0.619 | 17.2  | 50.0  | 0.434  | 1.000
  6 | TRENDING_UP     | 0.79  | 0.213 | 42.1  | 55.9  | 0.348  | 1.000
  7 | SQUEEZE         | 0.60  | 0.349 | 33.2  | 49.4  | 0.342  | 1.000
  8 | TRENDING_DOWN   | 0.43  | 0.352 | 29.1  | 41.1  | 0.359  | 1.000
  9 | TRENDING_DOWN   | 0.42  | 0.412 | 28.4  | 36.8  | 0.400  | 1.000  ← şu an, DEFENSIVE
```

### Bot 26 — XLMUSDT (14 tur kapatmış, +101.9 realize)
```
cyc | regime          | güven | atr5m | adx1h | base% | trail% | grid_step
  2 | LOW_VOL_RANGING | 0.50  | 0.634 | 14.1  | 50.0  | 0.507  | 1.000
  3 | LOW_VOL_RANGING | 0.50  | 0.725 | 14.1  | 50.0  | 0.544  | 1.000
  4 | LOW_VOL_RANGING | 0.50  | 0.825 | 15.1  | 50.0  | 0.602  | 1.000
  5 | LOW_VOL_RANGING | 0.50  | 0.824 | 15.4  | 50.0  | 0.631  | 1.000
  6 | TRENDING_DOWN   | 0.70  | 0.573 | 12.6  | 35.5  | 0.663  | 1.000
  7 | BREAKOUT        | 0.70  | 0.890 | 16.2  | 43.9  | 1.053  | 1.000
  8 | LOW_VOL_RANGING | 0.50  | 0.699 | 18.4  | 47.0  | 0.806  | 1.000
  9 | LOW_VOL_RANGING | 0.50  | 0.791 | 19.7  | 48.5  | 0.719  | 1.000
 10 | LOW_VOL_RANGING | 0.50  | 1.033 | 19.7  | 49.2  | 0.773  | 1.000
 11 | LOW_VOL_RANGING | 0.40  | 1.131 | 22.3  | 49.6  | 0.834  | 1.000
 12 | LOW_VOL_RANGING | 0.40  | 0.790 | 24.8  | 49.8  | 0.741  | 1.000
 13 | TRENDING_UP     | 0.56  | 0.497 | 25.8  | 55.1  | 0.717  | 1.000
 14 | TRENDING_UP     |  —    |  —    |  —    |  —    |  —     |  —    (stale)
 15 | TRENDING_DOWN   | 0.42  | 0.696 | 28.2  | 45.7  | 0.773  | 1.000
```

### Bot 22 — AVAXUSDT / Bot 28 — LINKUSDT
```
B22  2 LOW_VOL_RANGING .70 0.291 17.7 50.0 0.233 1.000
B22  3 LOW_VOL_RANGING .70 0.350 15.1 50.0 0.260 1.000
B22  4 LOW_VOL_RANGING .70 0.354 15.3 50.0 0.274 1.000
B22  5 LOW_VOL_RANGING .50 0.578 15.2 50.0 0.368 1.000
B28  2 LOW_VOL_RANGING .40 0.258 21.0 50.0 0.206 1.000
B28  3 LOW_VOL_RANGING .70 0.345 19.3 50.0 0.247 1.000
B28  4 LOW_VOL_RANGING .70 0.339 17.5 50.0 0.261 1.000
B28  5 LOW_VOL_RANGING .50 0.502 16.5 50.0 0.331 1.000
B28  6 LOW_VOL_RANGING .50 0.568 16.6 50.0 0.393 1.000
```

> **Tek bakışta:** Sağdaki `grid_step` sütunu **47 satırın hepsinde 1.000** — Bulgu 2'nin görsel kanıtı. base% ve trail% hareket ediyor; grid donmuş.

---

## Ek B — Veri kaynakları ve tekrar üretim

- Bot durumu: `sqlite3 ~/.trader/dca.db "SELECT state_json FROM bot_engine_state WHERE bot_id=…"`
- Cüzdan: `bot_virtual_wallet` (virtual_base / virtual_quote)
- Tur olayları: `bot_engine_events` (CYCLE_START / CYCLE_END)
- Canlı fiyat: `GET https://api.binance.com/api/v3/ticker/price`
- Equity = `virtual_base · price + virtual_quote`; realize = `cycle_start_equity − 1000`; batık = `equity − cycle_start_equity`
- Kod: `app/botengine/dynamic/{cycle_manager,strategy_engine,cycle_gate,regime}.py`
