# Param Optimizer

Parametre Asistani backend motoru. Bu klasor, bot olusturma ekranindaki AI onerisi icin gecmis veri toplar, indikatörleri hesaplar, aday parametreleri arar, stratejiyi backtest eder ve sonucu frontend'e job olarak dondurur.

## Akis

```text
app/api/param_assistant_routes.py
  HTTP isteklerini alir, sembol/butce/seviye dogrular, job baslatir.

jobs.py
  Async job yasam dongusu, progress, ETA, hata/done durumlari.

tiers.py
  Soft / Medium / High analiz seviyeleri, sure ve CPU butceleri.

engine.py
  Ust orkestrasyon: history -> indicators/features -> robust_engine -> validation -> result.
  GUVEN SKORU: features.confidence yalnizca indikatör netligini olcer; tek basina
  yuksek cikabilir. adjust_confidence() bunu GERCEK out-of-sample sonucla hizalar
  (negatif OOS getiri, az kapanan tur, yuksek dusus ve zayif Monte Carlo guveni
  duser). Boylece OOS negatifken guven 90 kalamaz; out["confidence"] bu hizalanmis
  degerdir, out["confidence_base"] ham indikatör guvenidir.
  ANLATI DURUSTLUGU (build_rationale): "grid dostu" yalnizca Hurst<0.5 VE dusuk ADX
  VE zayif trend iken soylenir (guclu trendde "trendli — zorlayici" + uyari satiri);
  alloc etiketi gercek orana gore verilir; negatif OOS dürüstçe "zarar etti" diye
  belirtilir; in-sample sonucun iyimser oldugu not edilir.

history.py
  Binance gecmis mum verisi ve veri kapsama hazirligi.

indicators.py
  ATR, RSI, ADX, Bollinger genisligi, trend/volatilite sinyalleri.

space.py
  Parametre aday uzayi ve sinirlar.
  FIZIKSEL/MANTIK GUVENLIGI (decode):
    - Alis gridi referans fiyattan MUTLAK dusus %'sidir. Spot piyasada fiyat en
      fazla %100 duser; bu yuzden hicbir alis seviyesi MAX_BUY_DEPTH_PCT (%92)
      esigine ulasamaz — asan (asla dolmayacak olu) seviyeler kesilir
      (_grid_triggers). Satis icin de absurt-derin esik MAX_SELL_RISE_PCT ile elenir.
    - Asagi baski/dump rejiminde base orani DOWN_REGIME_MAX_BASE_PCT (%34) ile
      sinirli ve dim ust sinari daraltilir: savunma GERCEK anlamda quote agirlikli olur.

robust_engine.py
  CANLI optimizasyon motoru (optimize_robust). Genis serbest-parametre taramasi
  yerine, rejim/oynaklik tahmininden uretilen kucuk bir yapisal varyant kumesini
  backtest eder; UI sonuc sekli korunur. engine.run_optimization buna delege eder.

backtest.py
  DCA grid trailing davranisini geriye donuk simule eder.

objective.py
  Skor, risk, getiri, drawdown ve ceza fonksiyonlari.

robust_policy.py
  Rejim-tahminli saglam politika sozlesmesi: OOS beceri kapisi (SS>0),
  klimatoloji fallback, state->parameter politika uretimi, CVaR cezali amac
  yardimcilari ve sert DAGIT/DAGITMA kapisi. Simdilik hafif saf-Python iskelet;
  ileride HMM/GARCH/CSCV-PBO parcalari ayni kontrata takilabilir.
```

## UI ile sozlesme

Frontend sabit endpoint yazmak yerine `ui/assets/modules/ai-assistant-spec.js` icindeki `AIAssistantSpec.api` alanini okur.

Donen sonuc, `ui/assets/modules/dashboard-create-modal.js` icindeki `dmParamAssistantBuildBackendRec` tarafindan forma uygulanabilir parametrelere cevrilir.

## Bakim kurallari

- Kullaniciya gosterilen asistan cumleleri bu klasore eklenmez; tek kaynak `AIAssistantSpec.paramAssistant.greetingPool`, 300 adet input-aware senaryo kalibi iceren `AIAssistantSpec.paramAssistant.scenarioPool` ve 300 adet detayli yorum kalibi iceren `AIAssistantSpec.paramAssistant.rationalePool`.
- Motor, kesin getiri vaadi uretmez; sonuc gecmis veri ve simülasyon baglaminda yorumlanir.
- Uzun sureli High analizlerde job progress ve ETA mutlaka guncel kalmalidir.
- Mum verisi coin+interval bazinda kalici cache'lenir. Ayni coin tekrar analiz
  edildiginde komple yeniden indirme yapilmaz; yalnizca eksik yeni mumlar ve
  gerekiyorsa eksik eski araliklar cache'e eklenir.
- Backend hata verirse frontend hizli yerel parametre sonucu gostermemelidir; kullaniciya
  yeniden deneme veya analiz seviyesi secimi sunulmalidir.
