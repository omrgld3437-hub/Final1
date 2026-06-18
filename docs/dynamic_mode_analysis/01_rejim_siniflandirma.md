# 01 — Rejim Sınıflandırma (S1–S85)

> Kaynak: `app/botengine/dynamic/regime.py`. İşaretler: ✅ doğru · ⚠️ orta · 🔴 önemli.

## A. Rejim sayısı ve kapsamı (S1–S15)

**S1. Kaç rejim var?** 8: `LOW_VOL_RANGING, HIGH_VOL_RANGING, TRENDING_UP, TRENDING_DOWN, SQUEEZE, BREAKOUT, DUMP_RISK, UNKNOWN`. ✅ Spot grid için makul bir taban kümesi.

**S2. UNKNOWN gerçek bir rejim mi yoksa "veri yok" durumu mu?** İkincisi — `atr` ve `adx` ikisi de None ise dönüyor. Strateji onu nötr (manuel-yakın) tuning ile ele alır. ✅ Doğru tasarım.

**S3. Eksik bir rejim var mı?** ⚠️ Evet: **"oversold bounce / accumulation"** (aşırı satım sonrası toparlanma) rejimi yok. RSI hesaplanıyor ama bu fırsatı yakalayan rejim yok.

**S4. "Recovery/relief rally" rejimi gerekir mi?** ⚠️ DUMP_RISK sonrası toparlanmayı ayrı tanımak faydalı olurdu; şu an çöküş sonrası doğrudan TRENDING_UP/RANGING'e düşüyor, ara geçiş yok.

**S5. Düşük likidite / illiquid rejimi var mı?** 🔴 Hayır. `spread_pct` ve `volume_24h_usdt` toplanıyor ama "spread çok geniş / hacim çok düşük → dikkatli ol" rejimi/filtresi yok.

**S6. Yatay piyasa kaç rejimle temsil ediliyor?** İkisi: `LOW_VOL_RANGING` ve `HIGH_VOL_RANGING`. ✅ Grid için doğru ayrım (sakin vs. chop).

**S7. Trend kaç rejimle temsil ediliyor?** İkisi: `TRENDING_UP`, `TRENDING_DOWN`. ✅ Yön ayrımı var.

**S8. Volatilite geçiş rejimleri var mı?** `SQUEEZE` (sıkışma) ve `BREAKOUT` (patlama) var. ✅ Geçiş çifti mevcut.

**S9. Rejimler birbirini dışlıyor mu (mutually exclusive)?** Evet — `_classify_raw` ilk eşleşeni döndürür (erken `return`). ✅ Tek rejim garantili.

**S10. Bir rejim hem trend hem squeeze olabilir mi?** Hayır; öncelik sırası tek sonuç verir (S79). ✅ Ama öncelik sırası önemli (bkz. S81).

**S11. Rejim sayısı "yetersiz" mi?** Çekirdek için yeterli; ⚠️ eksik olan likidite ve RSI-tabanlı (aşırı alım/satım) ayrımları. Sayı değil, **kullanılan sinyal çeşitliliği** dar.

**S12. Çok mu fazla rejim var (over-segmentation)?** Hayır; 7 aktif rejim yönetilebilir. Asıl sorun bazılarının (SQUEEZE/BREAKOUT) ayırt edici tuning'inin zayıf olması (bkz. 03).

**S13. UNKNOWN'a düşüş ne sıklıkta olur?** Yalnız hem ATR hem ADX None iken — yani 5m bile yetersizse. Pratikte `data_fresh=False` zaten stale path'e gider; UNKNOWN nadiren snapshot'a yansır. ✅

**S14. Her rejimin bir strateji karşılığı var mı?** Evet, `REGIME_TUNING` 8 anahtarı da kapsar. ✅ Eşleşme tam.

**S15. Rejim kümesi kullanıcının gördüğü bir şey mi?** Evet, UI banner + history rejimi gösterir. Etiketler `REGIME_LABELS` ile Türkçeleşir. ✅

## B. Rejim eşikleri (S16–S39)

**S16. ADX trend eşiği kaç?** `ADX_TRENDING=25`. ✅ Klasik Wilder eşiği (25 üstü trend).

**S17. ADX ranging eşiği kaç?** `ADX_RANGING=20`. 20–25 arası "belirsiz" bölge. ✅ Standart.

**S18. 20–25 ADX arası ne olur?** `is_trending=False, is_ranging=False` → ATR'ye bakılır: ATR≥1.5 → HIGH_VOL_RANGING, değilse LOW_VOL_RANGING. ✅ Mantıklı geri dönüş.

**S19. ATR yüksek eşiği kaç?** `ATR_HIGH_PCT=1.5` (%). 5m ATR yüzdesi. ⚠️ Sabit; BTC için yüksek, küçük altcoin için düşük olabilir — sembole göre normalize edilmiyor.

**S20. ATR düşük eşiği kaç?** `ATR_LOW_PCT=0.4` (%). Altı "sakin". ✅ Makul ama yine sembol-bağımsız (S19 ile aynı sınırlama).

**S21. ATR eşikleri coin'e göre uyarlanıyor mu?** 🔴 Hayır. %1.5 ATR bir stablecoin çiftinde "aşırı", bir meme coin'de "sakin" olabilir. Tek sabit eşik tüm semboller için. Normalize (örn. coin'in tarihsel ATR dağılımına göre yüzdelik) yok.

**S22. BBW squeeze eşiği kaç?** `BBW_SQUEEZE=2.5` (1h BBW yüzdesi). Altı sıkışma. ⚠️ Yine sabit/sembol-bağımsız.

**S23. Hacim spike eşiği kaç?** `VOLUME_Z_SPIKE=2.0` (z-score). 2 std üstü. ✅ İstatistiksel olarak makul (~%2.3 kuyruk).

**S24. EMA trend yukarı eşiği?** `EMA_TREND_UP=0.4` (%). 1h EMA(20)'nin 5 bar değişimi ≥%0.4. ⚠️ Çok küçük — 5 saatte %0.4, gürültü seviyesinde.

**S25. EMA trend aşağı eşiği?** `EMA_TREND_DOWN=-0.4` (%). Simetrik. ⚠️ Aynı hassasiyet sorunu.

**S26. DUMP eşiği?** `DUMP_DROP_PCT=-2.0` (1h EMA slope ≤ −%2). ⚠️ "Son bar düşüşü" yorumu (kod yorumunda) yanıltıcı: aslında 1h EMA eğimi, anlık bar değil (bkz. S41).

**S27. Eşikler kullanıcıya açık mı / ayarlanabilir mi?** Hayır — "system-defined, NOT user-tunable". ✅ Tasarım kararı (tutarlılık), ama ⚠️ sembol çeşitliliği için katı.

**S28. ATR_HIGH (1.5) ve ATR_LOW (0.4) arasındaki "orta bant" nasıl ele alınıyor?** Ranging içinde 0.4–1.5 arası → LOW_VOL_RANGING (confidence 0.5). ✅ Orta vol "sakin"e dahil ediliyor — grid için kabul edilebilir.

**S29. BREAKOUT BBW eşiği nasıl belirleniyor?** `bbw >= ATR_HIGH_PCT*4` = 6.0. 🔴 BBW eşiğini bir ATR sabitiyle (×4) türetmek **birim olarak tutarsız** — BBW ve ATR farklı ölçekler; sihirli ×4 katsayısı gerekçesiz.

**S30. SQUEEZE hangi BBW'yi kullanır?** Yalnız `f.bbw_1h` (fallback YOK). 🔴 1h verisi yetersizse (`bbw_1h is None`) SQUEEZE **hiç tetiklenmez**, oysa BREAKOUT 5m fallback'i kullanabilir (asimetri).

**S31. BREAKOUT hangi BBW'yi kullanır?** `bbw = bbw_1h or bbw_5m` (fallback'li). Yani 5m BBW ile de tetiklenebilir. ⚠️ SQUEEZE ile tutarsız (S30).

**S32. ADX eşikleri arasında histerezis var mı (25/20 ayrımı)?** Evet — trend için ≥25, ranging için ≤20; 20–25 arası tampon. ✅ İçsel histerezis (tek eşik flip-flop'u önler). İyi tasarım.

**S33. ATR eşiği için tampon var mı?** Hayır — tek nokta (1.5 ve 0.4). 1.49↔1.51 sınırında HIGH↔LOW arası rejim oynayabilir. ⚠️ Ama dış histerezis (S55) bunu kısmen kapatmalıydı (kapatmıyor, S57).

**S34. Confidence eşikten nasıl türiyor?** Trend için `_conf(adx)`: ADX 25→0.55, 50→0.90 lineer; sabit değerler ranging/squeeze/breakout için elle (0.7/0.6/0.7...). ✅ ADX gücüyle ölçekleniyor (trendde).

**S35. BREAKOUT yönü ayırt ediliyor mu?** 🔴 Hayır. BBW patlaması + hacim "yön" içermez; aşağı yönlü patlama (çöküş) bile `BREAKOUT` → tuning base %50 (nötr). Defansif değil. Yön için slope eklenmeli.

**S36. DUMP ve BREAKOUT çakışırsa?** DUMP önce kontrol edilir (öncelik). slope≤−2 & vol_z≥2 ise BBW'ye bakılmadan DUMP. ✅ Defansif öncelik doğru.

**S37. 1h BBW None iken BREAKOUT 5m BBW ile tetiklenebilir mi?** Evet. ⚠️ 5m BBW çok daha gürültülü; 5m'de BBW≥6 + vol_z≥2 yanlış BREAKOUT üretebilir.

**S38. ATR eşikleri ile grid step katsayısı tutarlı mı?** ATR_HIGH=1.5 iken grid step ≈ 0.7×1.5×step_mult. Eşik ve katsayı ayrı tanımlı; ⚠️ koordine değil (birinin değişmesi diğerini bozabilir).

**S39. Eşiklerin hiçbiri zaman dilimine (5m vs 1h) göre etiketlenmemiş; karışıklık riski?** ATR eşiği 5m ATR'ye, ADX/EMA/BBW_SQUEEZE 1h'e uygulanır ama sabit adları bunu söylemez. ⚠️ Bakım riski (yanlış zaman dilimine uygulama).

## C. DUMP / BREAKOUT / SQUEEZE özel mantığı (S40–S54)

**S40. DUMP_RISK gerçekten flash crash yakalar mı?** 🔴 Hayır. Sinyal 1h EMA slope ≤ −2% (5 bar = 5 saatlik yumuşatılmış eğilim). Anlık 5m çöküşü 1h EMA'ya yansıması saatler alır.

**S41. Kod yorumu "last-bar drop%" diyor, doğru mu?** 🔴 Yanıltıcı. `DUMP_DROP_PCT` adı ve yorumu "son bar" ima eder; gerçekte `ema_slope_1h_pct` (1h EMA'nın 5-bar yüzde değişimi) ile karşılaştırılır.

**S42. DUMP için hacim şartı gerekli mi?** Hem slope≤−2 **hem** vol_z≥2 gerekli (AND). 🔴 Düşük hacimli yavaş çöküş (sızıntı) DUMP sayılmaz — oysa DCA için en tehlikelilerden.

**S43. Ani %10 5m çöküşünde rejim ne olur?** 1h slope henüz −2'ye inmemişse DUMP değil; muhtemelen TRENDING_DOWN (ADX yükselirse) veya HIGH_VOL_RANGING. ⚠️ Gerçek panik geç sınıflanır.

**S44. DUMP confidence'ı kaç?** 0.85 (yüksek). ✅ Tetiklenince güçlü sayılıyor — ama tetikleme koşulu zayıf (S40).

**S45. DUMP tuning'i yeterince defansif mi?** base %15 (çoğu nakit) ✅; step_mult 2.0 (geniş grid) ✅; ama `buy_levels_mult=0.3` **kullanılmıyor** 🔴 → alım miktarı kısılmıyor (yalnız spacing genişliyor).

**S46. BREAKOUT sonrası ne beklenir?** Geniş adım (step_mult 1.6), geniş trailing (1.5), geç kâr (tp 1.5). ✅ Yön belirsizliğine karşı geniş — ama yön-körlük (S35) riskli.

**S47. SQUEEZE doğru ortamı yakalıyor mu?** 1h BBW ≤ 2.5 → tarihsel dar bant. ✅ Kavramsal doğru; ⚠️ 2.5 sabiti sembol-bağımsız.

**S48. SQUEEZE tuning'i "patlamaya hazırlık" yansıtıyor mu?** step_mult 0.9, trail 1.0, base 45 — neredeyse nötr. ⚠️ "Sıkışma sonrası patlama beklentisi" için ayırt edici bir konumlanma yok (örn. daha fazla nakit tutup patlamayı beklemek).

**S49. BREAKOUT ve SQUEEZE arasında geçiş tutarlı mı?** Squeeze (dar BBW) → sonra BBW patlar + hacim → BREAKOUT. ✅ Mantıksal akış doğru; ama BREAKOUT 5m fallback'i SQUEEZE'in 1h-only'siyle çelişebilir (S30/S37).

**S50. DUMP_RISK'te yeni alım tamamen durur mu?** 🔴 Hayır. base %15 hedefi quote'u artırır ama gridler hâlâ kurulur ve `buy_levels_mult` kullanılmadığı için qty kısılmaz. Strateji düşüşte hâlâ (geniş aralıklı) alır.

**S51. BREAKOUT'ta hacim teyidi şart mı?** Evet (`vol_z>=2`). ✅ Hacimsiz BBW genişlemesi BREAKOUT sayılmaz — doğru (yanlış kırılım filtresi).

**S52. SQUEEZE'de hacim rolü var mı?** Hayır — yalnız BBW. ✅ Squeeze hacimden bağımsızdır (doğru), patlama hacimle (BREAKOUT) gelir.

**S53. DUMP eşiği −2% çok mu gevşek/sıkı?** 1h EMA 5-bar −2% ciddi bir düşüş (5 saatte). ⚠️ Hızlı panikte geç; yavaş ayı piyasasında ise sürekli DUMP olabilir (kalıcı −2% slope).

**S54. Ayı trendinde sürekli DUMP_RISK riski?** Evet — kalıcı negatif slope + ara ara hacim spike'ı → tekrar tekrar DUMP. ⚠️ Ama tuning defansif olduğu için zararsız; yalnız base %15'te kalır.

## D. Histerezis & zamansal kararlılık (S55–S70)

**S55. Histerezis mekanizması var mı?** Evet, `MIN_DWELL_CYCLES` + candidate/streak. Ama değer **1**. 🔴 1 ile ilk farklı sınıflandırma anında kabul edilir → fiilen histerezis yok.

**S56. MIN_DWELL=1 ne demek?** `streak >= 1` her zaman doğru olduğundan, farklı raw rejim görülür görülmez geçilir. Histerezis dalı (`confidence*0.5`, current'ta kalma) **hiç çalışmaz**. 🔴 Ölü kod.

**S57. ATR 1.49↔1.51 sınırında rejim oynar mı?** Evet — HIGH↔LOW her tur değişebilir (histerezis kapalı). ⚠️ Ama bu yalnız tur başında olur (S60), her tick değil.

**S58. Rejim "anlık" mı değişiyor?** Hayır — `classify` yalnız `build_snapshot` içinde, o da yalnız **tur başında** (`need_recompute`) çağrılır. Yani rejim **tur bazlı**, tick bazlı değil. ✅ Bu doğal bir tampon.

**S59. O zaman histerezis kapalı olması ne kadar kötü?** Etki sınırlı: turlar seyrek (yalnız profit-exit/re-entry'de kapanır) olduğundan rejim de seyrek hesaplanır. ⚠️ Yine de iki ardışık tur sınır eşikte farklı rejim alabilir.

**S60. Rejim ne sıklıkta yeniden hesaplanır?** Yalnız: (a) `_dynamic_recompute_needed` (tur kapanışı), (b) snapshot yok, (c) `cycle_id` değişti. Zaman/tick bazlı yenileme YOK. ✅/⚠️ (uzun turda donuk).

**S61. Uzun süren tek turda rejim donar mı?** Evet — tur kapanmadıkça snapshot (ve rejim) sabit kalır. ⚠️ Piyasa rejim değiştirse bile yeni rejim uygulanmaz (immutable snapshot ilkesi; tur-içi koruma emergency_check).

**S62. Eğilim mi anlık mı hesaplanıyor?** Trend rejimleri **1h ADX + 1h EMA slope** ile → orta vadeli eğilim. Vol rejimleri **5m ATR** ile → kısa vadeli. ✅ Karma: trend yavaş, vol hızlı.

**S63. Bu karma (1h trend + 5m vol) tutarlı mı?** Mantıklı: grid spacing kısa-vadeli vol'a (5m ATR), yön/alloc orta-vadeli trende (1h) bağlı. ✅ İyi ayrıştırma.

**S64. `classify` ve `update_regime_state` aynı mantığı iki kez mi hesaplıyor?** Evet — streak/candidate geçişi iki fonksiyonda ayrı. 🔴 Kırılgan tekrar (biri değişirse tutarsızlık); şu an MIN_DWELL=1'de ikisi de "anında geç" verdiği için tutarlı.

**S65. Candidate streak state'te saklanıyor mu?** Evet — `dynamic_snapshot.regime_state` içinde. ✅ Turlar arası taşınır.

**S66. Stale turda regime_state korunuyor mu?** Evet — stale path `regime_state: prev_regime_state` taşır, yeniden sınıflamaz. ✅ Doğru.

**S67. MIN_DWELL=2 yapılsa ne olurdu?** Bir rejim değişimi için 2 ardışık tur gerekir; turlar seyrek olduğundan rejim **neredeyse hiç** değişmeyebilir → aşırı tutuculuk. ⚠️ Bu yüzden 1 bilinçli olabilir; gerçek çözüm tick-bazlı histerezis + tur-bazlı uygulama ayrımı.

**S68. Rejim değişimi kademeli mi sert mi yansıyor?** Sert — yeni rejim yeni tuning'i tam uygular; ama parametreler ayrıca smoothing (alpha 0.5) + rate-limit (skaler) ile yumuşar (S281). ✅ Param seviyesinde tampon var.

**S69. Rejim "yanlış" açılırsa zararı ne?** Param önerisi değişir ama risk motoru clamp'ler; en kötü ihtimalle manuel-yakın değerler. ✅ Güvenli düşüş; yanlış rejim felaket değil.

**S70. Gürültülü piyasada rejim sıçraması mümkün mü?** Evet (histerezis kapalı) ama yalnız tur sınırlarında ve param-smoothing ile tamponlu. ⚠️ Sınırlı risk.

## E. Confidence kullanımı (S71–S78)

**S71. Confidence nerede kullanılıyor?** 🔴 Tek yer: `suggest` içinde `TRENDING_DOWN & confidence<0.6 → base=max(target,35)`. Başka hiçbir yerde öneriyi etkilemiyor.

**S72. Confidence step/trail/alloc'u ölçekliyor mu?** Hayır. ⚠️ 0.45 ve 0.90 güvenli bir rejim **aynı** step/trail/tp alır.

**S73. Düşük confidence'ta daha temkinli olmalı değil mi?** Evet — beklenen davranış "belirsizsem manuele yaklaş" olurdu; ⚠️ uygulanmıyor (TD hariç).

**S74. Confidence hesabı doğru mu?** `_conf(adx)` ADX 25–50 → 0.55–0.90 lineer; ranging/squeeze sabitleri makul. ✅ Hesap doğru, **kullanım** zayıf.

**S75. Confidence histerezis dwell'siz dönemde yarıya iniyor mu?** Kodda `confidence*0.5` var ama MIN_DWELL=1'de o dal ölü (S56). 🔴 Pratikte hiç uygulanmaz.

**S76. Confidence UI'da gösteriliyor mu?** History'de `regime_confidence` saklanır; banner reason'larda görünür. ✅ Şeffaf.

**S77. Confidence smoothing'i etkiliyor mu?** Hayır — smoothing sabit alpha 0.5. ⚠️ Düşük confidence'ta daha çok prev'e yaslanmak (düşük alpha) mantıklı olurdu; yapılmıyor.

**S78. Confidence "trend belirsiz" durumunu ölçüyor mu?** Kısmen — trending ama slope flat ise `_conf(adx)*0.7` (azaltılmış). ✅ Belirsizliği yansıtıyor; ama sonuç yalnız S71'de kullanılıyor.

## F. Rejim tutarlılığı & öncelik sırası (S79–S85)

**S79. Sınıflandırma öncelik sırası nedir?** UNKNOWN-guard → DUMP → BREAKOUT → SQUEEZE → (ADX) TRENDING/RANGING → 20-25 belirsiz → ATR fallback. ✅ Defansif (DUMP) önce, güvenli (RANGING) sonra.

**S80. Bu sıra doğru mu?** Büyük ölçüde ✅ (tehlike önce). ⚠️ BREAKOUT, SQUEEZE'den önce: dar BBW + ani hacim varsa BREAKOUT kazanır — doğru. Ama BREAKOUT 5m fallback'i SQUEEZE'i bastırabilir (S37).

**S81. Öncelik sırası bir rejimi tamamen gölgeler mi?** SQUEEZE, BREAKOUT'tan sonra: BBW hem ≤2.5 (squeeze) hem ≥6 (breakout) olamaz, çakışma yok. ✅ Ama BREAKOUT'un 5m fallback'i ile SQUEEZE'in 1h-only'si farklı veri kullandığından nadir tutarsızlık olabilir.

**S82. Trend + yüksek vol aynı anda olursa?** ADX≥25 → trend kazanır (ATR'ye bakılmaz). ✅ Trendde grid yerine yön-odaklı tuning mantıklı.

**S83. Trend güçlü ama slope flat (yön belirsiz) durumu?** `_conf(adx)*0.7` ile düşük confidence, slope işaretine göre TU/TD; ikisi de değilse LOW_VOL_RANGING (0.4). ✅ Makul geri dönüş.

**S84. Aynı feature'larla iki çağrı aynı rejimi verir mi (determinism)?** Evet — `_classify_raw` saf fonksiyon, rastgelelik yok. ✅ Deterministik.

**S85. Rejim sonucu state'i mutate ediyor mu (yan etki)?** `classify` saf; state güncellemesi ayrı `update_regime_state` ile (cycle_manager çağırır). ✅ Ayrım temiz (ama S64 tekrarı).
