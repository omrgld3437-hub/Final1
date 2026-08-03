# Dynamic Mode V2 — teknik analiz ve teslimat raporu

Tarih: 2026-07-29  
Uygulama durumu: **Shadow varsayılan, canlı feature flag varsayılan kapalı**

## 1. Mevcut sistemin gerçek kod akışı

1. İlk tur, `initial_allocation` alış emrinin gerçekten dolmasıyla başlıyor. Sonraki turlar kâr satışı veya kârlı geri alış dolduktan sonra `cycle_reset_after_fill` ile açılıyor.
2. Tur, `trail_profit_sell` veya `trail_reentry_buy` fill’i ile kapanıyor; `_cycle_complete` işareti sonrası `cycle_id` artıyor.
3. Tur fiyatı `initial_reference_price` alanında tutuluyor. `reference_price` eski state uyumluluk alias’ı.
4. Alış/satış grid yüzdeleri `_cycle_reference_price()` sonucuna göre hesaplanıyor; canlı tick veya ara fill referansı değiştirmiyor.
5. Grid durumu `*_grid_fired`, `*_grid_status`, `*_grid_trigger_price`, `*_grid_peak_price`/`*_grid_trough_price` ve `*_grid_fill_price` dizilerinde tutuluyor.
6. Bekleyen grid: `WAITING_TRIGGER`, `fired=False`, `trigger_price=None`.
7. Tetiklenmiş grid: trigger price atanmış ve status `TRAILING`.
8. Trailing başlamış grid: trigger price ile birlikte peak/trough tutuluyor.
9. Emir oluşturma ve borsa durumu `order_intents` durum makinesinde `PERSISTED → SUBMITTING → SUBMITTED/ACKED → PARTIAL/FILLED/...` olarak tutuluyor.
10. Kısmi fill intent katmanında `PARTIAL` olarak korunuyor; V2 bunu değiştirilemez/protected kabul ediyor.
11. Tam grid fill’i history/ledger’a yazılıyor, status `COMPLETED`, `fired=True` oluyor.
12. Satış grid fill’lerinden sonra ağırlıklı satış fiyatı aşağı yönde kırılınca kârlı geri alış trailing’i başlıyor.
13. Alış grid fill’lerinden sonra maliyet tabanı kâr eşiğini aşınca kâr satışı trailing’i başlıyor.
14. Kâr satışı anchor’ı ağırlıklı alış maliyeti; geri alış anchor’ı ağırlıklı satış fiyatı. Trailing başladıktan sonra canlı peak/trough ayrıca izleniyor.
15. Alış trailing’i dipten yükseliş, satış trailing’i tepeden geri çekilme ile tamamlanıyor.
16. Gridler borsaya önceden limit emir olarak gönderilmiyor.
17. Fiyat grid eşiğine gelince sanal trailing başlıyor; trailing tamamlanınca borsa emri oluşturuluyor.
18. Parametre Asistanı base/quote, grid mesafeleri, grid miktar yüzdeleri, trailing ve kâr döngüsü değerlerini üretiyor.
19. Eski Dinamik Mod aynı alanlara rejim/profil çarpanı uyguluyor; grid sayısını başlangıç referansından koruyor.
20. Eski kodda önceki overlay’in tekrar girdi olmasını önleyen `_dynamic_reference` mevcut. V2 de her tur için ayrı immutable referans kullanıyor.
21. Çalışan bakiye `bot_virtual_wallet` senkronu üzerinden state içindeki `base_balance`/`quote_balance` alanlarına geliyor.
22. Canlı signed bakiye doğrulaması bağlıdır: botun sanal bakiyesi üst sınırdır, gerçek serbest bakiye yalnızca bu bütçeyi azaltabilir; hesap bakiyesi bot bütçesini büyütemez.
23. Binance user stream emir güncellemelerini `order_intents` ile eşleştiriyor.
24. REST reconciliation açık/tüm emirleri sorgulayıp yerel intent durumunu Binance gerçeğiyle uzlaştırıyor.
25. Bot/symbol lock ve optimistic `state_version` var. V2 ayrıca karar idempotency anahtarı kullanıyor.
26. State JSON kaydı kendi commit’ini yapıyor; intent ve event fonksiyonlarında da ayrı commit’ler var. Tek bir uçtan uca DB transaction mevcut sistemde yok.
27. Dinamik bilgi bot detay API’sinde `dynamic_mode` bloğunda ve React bot detay sayfasında gösteriliyor.
28. Test altyapısı pytest + JS/TS contract testlerinden oluşuyor.
29. Mevcut çalışma state/config sözleşmesi JSON float kullanıyor. Yeni V2 hesapları Decimal; çalışan eski strateji sınırında float dönüşümü zorunlu kalıyor.
30. Eski strateji ve intent hash/sizing kodunda binary float kullanımı bulundu. V2 iç matematiği bunu taşımıyor, ancak tüm legacy runtime Decimal’e çevrilmeden sistem genelinde float riski tamamen kapanmış sayılmaz.

## 2. Tespit edilen başlıca riskler

- Eski Dinamik Mod raf/profil/rejim sınıflandırmasına bağlı ve yalnız tur sınırında hesaplanıyor.
- State, borsa, intent ve audit kayıtları tek transaction içinde değil.
- Hesap genelindeki kilitli bakiyenin hangi bota ait olduğunu kanıtlayan ayrıştırma henüz yok; bu yüzden açık emir varken V2 güncellemesi tamamen durur.
- Mevcut strateji para ve yüzdeleri float olarak çalıştırıyor.
- Eski event logger bazı hataları sessizce yutuyor.
- Aktif grid miktarı config overlay ile yanlışlıkla değişebilirdi; V2 coordinator grid başına uygunluk uygulayarak bunu engelliyor.
- İki gridli kurulumda `%40 max single weight` matematiksel olarak imkânsızdır. V2 hard grid-count kuralını koruyup uygulanabilir alt sınırı `1 / grid_count` olarak kullanıyor.

## 3. Oluşturulan V2 modülleri

- `MarketDataCollector`: yalnız `/api/v3` spot mum, depth ve trade verisi.
- `MarketDataQualityEngine`: geometrik kalite puanı ve fail-closed eşikler.
- `FeatureSnapshotBuilder` / `MarketFeatureEngine`: Decimal getiri, ATR, yönlü volatilite, spread, kayma, depth ve mikro gürültü.
- `MarketStateEngine`: continuous state.
- `FormulaCoefficientRepository`: immutable champion.
- `DynamicFormulaEngine`: bütün formüller ve 0,1 çarpan kuantizasyonu.
- `ParameterConstraintProjector`: PAVA tabanlı deterministik isotonic projection.
- `ParameterValidationEngine`: sıralı, all-or-nothing doğrulama.
- `EligibleGridResolver`: legacy state → V2 state eşlemesi.
- `PortfolioBudgetEngine` / `SideBudgetAccountingEngine`: target − consumed − protected muhasebesi.
- `GridUpdateCoordinator`: state-version, idempotency ve yalnız waiting-grid update.
- `ExchangeReconciliationEngine`: belirsiz intent/exchange fail-closed kapısı.
- `DynamicModeScheduler`: saatlik +30 dakika retry +5 dakika mikro kontrol zamanlaması.
- `OutcomeCollector`, `CoefficientCalibrationEngine`, `ShadowEvaluationEngine`, `AuditLogEngine`, `DynamicModeUIAdapter`.
- `DynamicV2AuditRepository`: formula ve analiz kayıtları.

## 4. Korunan ve kaldırılmayan davranışlar

- Grid sayıları ve yönleri değişmiyor.
- İlk allocation, trailing, fill, cycle close ve ledger akışı korunuyor.
- V2 yalnız initialized spot botta çalışıyor.
- Aktif/tetiklenmiş/completed grid konfigürasyonu korunuyor.
- Eski Dinamik Mod kaldırılmadı; V2 flag açıkken bypass ediliyor. Rollback, flag’i kapatarak legacy akışa dönmek.

## 5. Feature flag ve rollout

- `dynamic_mode_v2=false`: varsayılan, V2 çalışmaz.
- `dynamic_mode_v2=true`: V2 seçilir, legacy dinamik motor bypass edilir.
- `dynamic_mode_v2_shadow=true`: varsayılan; gerçek aday ve audit üretilir, parametre uygulanmaz.
- Canlı uygulama için hem V2 flag açık hem shadow kapalı olmalı.
- Runtime exception, reconciliation belirsizliği veya mikro risk kill switch’i yeni V2 güncellemelerini durdurur; açık işlemleri kapatmaz.

## 6. Veritabanı ve migration

Eklenen tablolar:

- `dynamic_formula_versions`
- `dynamic_analysis_runs`
- `dynamic_grid_updates`
- `dynamic_learning_outcomes`
- `dynamic_calibration_runs`

Migration `upgrade` ve çocuk-tablo-önce `downgrade` destekliyor. SQLite bellek testinde oluşturma, geri alma ve aynı idempotency anahtarının ikinci analizi engellemesi doğrulandı.

## 7. Formül ve katsayı yerleri

- Katsayı sürümü: `FormulaCoefficients.version = dynamic-v2.0.0`
- Formül ağırlıkları: `app/botengine/dynamic_v2/config.py`
- Güvenlik/deadband/saatlik limitler: aynı dosyadaki `DynamicV2Config`
- Base yüzde puan adımı: `[-20, +20]`, 5 puan kademeli
- Grid çarpanları: `0.70–1.90`, 0,1 kademeli
- Grid trailing çarpanları: `0.80–1.60`
- Kâr tetik çarpanları: `0.70–1.80`
- Kâr trailing çarpanları: `0.70–1.70`
- Soft rebase alpha konfigürasyonu: `0.20` (canlı rebase state machine’i henüz bağlı değil)

## 8. Test sonuçları

Çalışan doğrulamalar:

- 16 V2 test fonksiyonu geçti.
- 500 rastgele property örneği: grid sırası/gap ve ağırlık invariants.
- Sakin yatay, yüksek vol yatay, güçlü düşüş ve güçlü yükseliş senaryoları.
- Consumed/protected/remaining örnekleri ve partial fill.
- Aktif grid koruması, state version, idempotent replay.
- Veri kalitesi düşükken mevcut parametreyi koruma.
- Deterministik replay.
- V2 absolute miktarının legacy yüzde olarak ikinci kez yorumlanmaması.
- Bütün Python kaynakları `compileall` ile geçti.
- Migration upgrade/downgrade ve audit idempotency geçti.

Ortam sınırlamaları:

- `pytest` executable/module kurulu değil; testler aynı test modüllerini yükleyen yerel assert koşucusuyla çalıştırıldı.
- React bağımlılık dizini eksik/bozuk (`tsc` executable yok); TypeScript lint/build çalıştırılamadı.

## 9. Bilinen eksikler

- Signed spot account collector’dan gerçek free/locked balance ve açık emir snapshot’ı V2 analizine doğrudan bağlanmadı.
- Güncel symbol filter’ları her analizde borsadan çekilmiyor; servis filter kabul ediyor, entegrasyon varsayılan değer kullanıyor.
- Analiz + audit + state snapshot + grid update tek DB transaction/row lock içinde değil.
- Soft-rebase state machine’i ve üç saat teyit akışı tamamlanmadı.
- Hızlı 24–72 saat candidate utility forward simulation tamamlanmadı.
- OutcomeCollector veritabanı fill/cycle eventlerine otomatik bağlanmadı.
- Calibration challenger üretir fakat backtest/walk-forward/Monte Carlo/approval pipeline’ı uygulanmadı.
- Dedicated V2 teknik UI ekranı yok; API mevcut bot detay bloğunda V2 snapshot’ını sunuyor.
- 20 senaryonun tamamı, gerçek replay veri seti, gerçekçi backtest, walk-forward, stres, Monte Carlo, performans ve çok-worker concurrency testleri tamamlanmadı.
- Legacy execution sınırı halen float; V2 içi Decimal olsa da sistem genelinde “hiç float yok” kabulü sağlanmadı.

## 10. 50 maddelik kabul kontrolü

Durumlar: **Geçti**, **Kısmi**, **Eksik**.

1. Yalnız spot: Geçti.
2. Grid sayısı değişmiyor: Geçti.
3. Raf/8.820 profil yok: Geçti (V2 içinde).
4. Sürekli skorlar: Geçti.
5. Parametreye özel formüller: Geçti.
6. 0,1 çarpan: Geçti.
7. Base/quote puan kademesi: Geçti.
8. Sakin yatay daraltma: Geçti.
9. Yüksek vol yatay genişletme: Geçti.
10. Düşüş yakın alış azaltma: Geçti.
11. Düşüş derin alış artırma: Geçti.
12. Düşüş base azaltma: Geçti.
13. Düşüş satış yakınlaştırma: Geçti.
14. Yükseliş satış genişletme: Geçti.
15. Yüksek satış seviyesine miktar: Geçti.
16. Alış tamamen kapanmıyor: Kısmi; pozitif kalan bütçede korunuyor, tüm exchange koşulları canlı test edilmedi.
17. Bütçe aşılmıyor: Geçti (unit/property); canlı signed balance testi eksik.
18. Grid sırası: Geçti.
19. Trailing spread/gürültü: Geçti.
20. Kâr maliyet tabanı: Geçti.
21. Kümülatif çarpan yok: Geçti.
22. Referanstan yeniden hesap: Geçti.
23. Yalnız waiting grid: Geçti.
24. Aktif grid korunuyor: Geçti.
25. Uygulama öncesi state/reconciliation: Geçti; tüm non-final intent durumları ve son-an canlı açık emir sorgusu fail-closed kapıdır.
26. Idempotent: Geçti.
27. Race koruması: Kısmi; state version ve karar+state tek transaction kaydı var, ayrı DB row-lock mekanizması yok.
28. Güvenilmez veride update yok: Geçti.
29. Güvenli aday olmadan yeni tur yok: Kısmi; aktif tur analizi fail-closed, Parametre Asistanı başlangıç gate entegrasyonu eksik.
30. Açıklanabilir karar: Geçti (candidate/audit), dedicated UI eksik.
31. Formül sürümü kayıtlı: Geçti.
32. Kontrollü öğrenme: Kısmi.
33. Öğrenme canlıyı doğrudan değiştirmiyor: Geçti.
34. Challenger test edilmeden champion değil: Geçti (aktivasyon yasak), test pipeline eksik.
35. Rollback: Kısmi; feature flag rollback var, DB champion promotion rollback pipeline’ı yok.
36. Kill switch: Kısmi.
37. Unit testler: Geçti (yerel assert runner).
38. Property testler: Geçti (deterministik random runner).
39. Integration testler: Kısmi.
40. Replay deterministik: Geçti (synthetic).
41. Gerçekçi backtest: Eksik.
42. Walk-forward: Eksik.
43. Stres testleri: Eksik.
44. Monte Carlo: Eksik.
45. UI doğru sebep: Kısmi; API veriyor, dedicated render eksik.
46. Tamamlanmış grid değişmiyor: Geçti.
47. DB kayıtları: Kısmi; analysis/formula var, grid/outcome otomatik yazımı eksik.
48. Güncel exchange filters: Eksik.
49. Eski sistem regresyonu: Kısmi; compile ve izole flag doğrulandı, tam pytest/UI build çalışmadı.
50. Tüm kontroller gerçek çıktıyla kanıtlı: Eksik.

Sonuç: V2’nin güvenli shadow çekirdeği ve ana muhasebe/formül davranışları uygulanmıştır. Yukarıdaki eksikler tamamlanmadan feature flag’in canlı ve shadow-off kullanımı önerilmez.
