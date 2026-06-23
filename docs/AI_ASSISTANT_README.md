# AI Asistan Sistemi

Bu dokuman, projedeki AI butonu, asistan dili, kelime/cumle havuzu ve Parametre Asistani motoru icin tek bakim noktasidir.

## Tek kaynak dosya

Calisan UI icin ana kaynak:

`ui/assets/modules/ai-assistant-spec.js`

Bu dosya sunlari belirler:

- Asistan kimligi: ad, aile, amac.
- Standart buton: yazi, tooltip, aria etiketi, CSS siniflari.
- Modal metinleri: baslik, etiket, acilis durumu.
- Tasarim tokenlari: vurgu rengi, basari rengi, panel rengi, radius, buton yuksekligi.
- Davranis zamanlamasi: yazma hizi, input doldurma hizi, alan gecis beklemesi.
- API sozlesmesi: tier ve optimize endpointleri.
- Kelime/cumle havuzu: kullaniciya gosterilen asistan acilis, senaryo ve gerekce cumleleri.
- Parametre Asistani senaryo havuzu: 300 adet input-aware cumle kalibi.
- Parametre Asistani gerekce havuzu: 300 adet input-aware yorum kalibi; oneriden sonra secilen parametrelerin nedenini detayli anlatir.
- Hata Asistani bilgi tabani (`errorAssistant`): her saglik/baglanti kodu icin zengin "ne oluyor / neden / etki / cozum adimlari" havuzu, oto-duzeltme aksiyon kimlikleri, tema baglama cumleleri, saglikli/durmus havuzu ve admin/sohbet bayragi.
- Yardimci fonksiyonlar: `greeting`, `paramScenarioLines`, `paramRationaleLines`, `errorGreeting`, `errorReportForCode`, `normalizeErrorCode`, `errorThemeOf`, `errorHealthyReport`, `errorStoppedReport`, `errorConnectLine`, `errorActionMeta`, `formatTemplate`, `applyButton`, `applyStaticText`.

Yeni bir yerde AI butonu veya AI asistan akisi kullanilacaksa kopya tasarim yazilmaz. Ekran, `window.AIAssistantSpec` uzerinden bu dosyayi okur.

## Kod agaci

```text
ui/assets/modules/ai-assistant-spec.js
  Tek kaynak: buton kimligi, tasarim tokenlari, metin havuzu, API yollari.

ui/dashboard.html
  ai-assistant-spec.js dosyasini dashboard-create-modal.js dosyasindan once yukler.

ui/assets/modules/dashboard-create-modal.js
  Parametre Asistani modalini, yazma animasyonunu, backend is takibini ve oneriyi forma uygulama akisini calistirir.
  Metin havuzu, zamanlama, endpoint, statik etiketler, 300 adet senaryo kalibi ve 300 adet detayli gerekce kalibini AIAssistantSpec kaynagindan okur.

ui/assets/modules/bot-error-assistant.js
  Bot detay sayfasindaki Hata Asistani akisi. Canli /health verisini ve motor olaylarini okur, aktif uyarilari
  AIAssistantSpec.errorAssistant bilgi tabanina eslemeler, ayni kokten gelenleri tek tema altinda baglar; her bulgu
  icin neden + etki + adim adim cozum + tek tik oto-duzeltme sunar, gerekirse en altta "Yonetimle sohbet" butonu acar.
  Kendi cumle havuzunu ACMAZ; tum metin/tasarim AIAssistantSpec kaynagindan gelir.
  TASARIM/AKIS: Parametre Asistani ile BIREBIR ayni — ayni buton (yesil tint + gold hover + isik suzulmesi),
  ayni panel/spark/kicker/cursor yapisi, ayni chip ve "yazi akisi" (typewriter streaming: intro karakter-karakter,
  stagger'li chip'ler, bubble bubble yazilan satirlar, sonda choice/footer). Renkler --ai-assistant-* tokenlarindan.
  Stiller bot.html icindedir (bot.html dashboard.css yuklemez), .page-bot altinda scoped.

ui/bot.html
  ai-assistant-spec.js ve bot-error-assistant.js dosyalarini yukler; ust seritte "Hata Asistani" butonunu, modal
  acma/aksiyon koprusunu (Yeniden tara, Uyarilari sifirla=health/ack, Parametreler, Cuzdan, API ayarlari, Sohbet)
  ve saglik durumuna gore butondaki uyari/kritik noktasini baglar. Modal stilleri --ai-assistant-* degiskenlerini kullanir.

app/botengine/health_watch.py
  Hata Asistani'nin okudugu saglik kodlarinin (TICK_STALE_*, LOOP_TASK_MISSING, MIN_NOTIONAL, BINANCE_UNREACHABLE,
  INSUFFICIENT_BALANCE vb.) ve level/cause/actions alanlarinin uretildigi tek kaynak. Yeni kod eklenirse
  errorAssistant bilgi tabanina karsilik gelen giris de eklenmelidir.

ui/assets/dashboard.css
  Asistan butonu/modal/chip gorunumunu cizer.
  Renk ve olcu kararlarini --ai-assistant-* CSS degiskenlerinden alir.

app/api/param_assistant_routes.py
  /api/param-assistant/tiers ve /api/param-assistant/optimize endpointlerini sunar.

app/services/param_optimizer/
  Gecmis veri, indikatör, arama, backtest, walk-forward dogrulama ve Monte Carlo simülasyonunu calistiran backend motorudur.

app/api/auth.py
  Kullanici-admin sohbet motorudur. Bu kisim bugun insan destek sohbetidir; otomatik AI cevap motoru degildir.

app/services/bot_perf_narrative_templates.py
  Bot Performans Asistani icin kalici anlatim havuzu. Mevcut kategori havuzuna ek olarak 300 adet konuskan, veriye bagli performans kalibi icerir.
```

## Parametre Asistani motoru

1. Kullanici bot olusturma modalinda standart AI butonuna basar.
2. Frontend, `AIAssistantSpec.api.tiers` ile analiz seviyelerini alir.
3. Secilen seviyeye gore `/api/param-assistant/optimize` uzerinden job baslatilir.
4. Backend job; parite gecmisini, indikatörleri, parametre aramasini, backtest sonucunu ve gerekiyorsa Monte Carlo senaryolarini hesaplar.
5. Frontend job durumunu poll eder, sonucu aciklama satirlari ve ozet tablo olarak gosterir.
6. Oneri tamamlaninca frontend, secilen butce/dagilim/grid/trailing/risk/güven kararlarini 10 bolumluk detayli gerekce akisi ile aciklar.
7. Kullanici onay verirse onerilen parametreler forma yazilir.
8. Backend gecikir veya hata verirse mevcut hizli yerel heuristik yedek akisi calisir.

## Hata Asistani motoru

1. Kullanici bot detay sayfasinda ust seritteki "Hata Asistani" butonuna (ya da aktifse Uyari/Kritik rozetine) basar.
2. Modal acilirken once kisa bir "tarama" durumu gosterilir ve `fetchBotHealth()` ile canli /health verisi tazelenir.
3. Modul aktif uyarilari toplar: once filtrelenmis UI secimi (`window._lastHealthUiPick`), ayrica `connectivity_failure` ve sunucu erisilemezligi sentetikleri eklenir.
4. Her uyari `AIAssistantSpec.normalizeErrorCode` ile bilgi tabanindaki temsilci koda eslenir (orn. `RUN_ACTION_EXCEPTION` -> `BOT_CONTINUES_ON_ERROR`), ayni koda dusenler tekillenir, en yuksek seviye korunur.
5. Bulgular temaya gore gruplanir (baglanti / butce-emir / calisma zamani / veri-tick / likidite / cuzdan); ayni temada birden cok bulgu varsa tek bir baglayici cumle ile baglanir (gurultu azaltma).
6. Her bulgu kart olarak cizilir: olasi neden, durum, bunun anlami, sirali cozum adimlari ve tek tik oto-duzeltme butonlari (Parametreler, Cuzdan, API ayarlari, Uyarilari sifirla, Yeniden tara).
7. Hata yoksa saglikli rapor (kontrol edilenler listesi), bot calismiyorsa "durmus" raporu gosterilir.
8. Bir veya daha cok bulgu `needsAdmin` ise modal en altta "Yonetimle sohbet" butonu acar; bu buton dashboard Iletisim sekmesine yonlendirir (`/ui/dashboard.html?tab=contact`).
9. Saglik verisi degistikce (poll) acik modal otomatik yeniden cizilir; butondaki uyari/kritik noktasi guncellenir.

Hata kodlari ile bilgi tabani eslemesi: `app/botengine/health_watch.py` kod uretir, `AIAssistantSpec.errorAssistant.codeBook` her kod icin kullaniciya gosterilecek dili tutar. Bilinmeyen kodlar icin `genericUnknown` guvenli fallback'i devreye girer.

## Sohbet motoru ayrimi

Projede `app/api/auth.py` altindaki chat endpointleri kullanici ile admin arasindaki destek sohbetidir:

- `/api/auth/chat`
- `/api/auth/chat/send`
- `/api/auth/chat/read`
- `/api/auth/chat/end`
- `/api/admin/chats/*`

Bu kanal otomatik AI cevabi uretmez. Gelecekte AI destekli cevap eklenirse:

- UI kimligi, buton tasarimi ve cumle havuzu yine `ai-assistant-spec.js` kaynagindan okunmalidir.
- Model/cevap uretim mantigi ayri bir backend servisinde tutulmalidir.
- Insan sohbeti ile otomatik asistan kayitlari DB seviyesinde ayirt edilebilir olmalidir.

## Kelime ve cumle havuzu kurallari

- Havuzun ana yeri `AIAssistantSpec.paramAssistant.greetingPool`.
- Parametre Asistani icin asil senaryo havuzu `AIAssistantSpec.paramAssistant.scenarioPool`; 300 adet kalip uretir.
- Parametre Asistani icin detayli yorum havuzu `AIAssistantSpec.paramAssistant.rationalePool`; 10 kategori altinda 300 adet kalip uretir.
- Oneri sonrasi aciklama `AIAssistantSpec.paramRationaleLines(values)` ile uretilir; butce, dagilim, satis gridleri, alis gridleri, trailing, kar dongusu, risk, guven ve final karar mantigini kapsar.
- Bot Performans Asistani icin asil havuz `app/services/bot_perf_narrative_templates.py`; toplam havuz 690+ kaliptir ve bunun 300 adedi yeni konuskan senaryo paketidir.
- Hata Asistani icin asil havuz `AIAssistantSpec.errorAssistant`; persona (acilis/saglikli/durmus/kapanis/admin), tema baglayicilari ve kod basina `what/why/impact/steps` + `actions` burada tutulur. UI modulu (`bot-error-assistant.js`) bu havuzu sadece okur, kendi cumlesini yazmaz.
- Hata Asistani cumleleri panik dili kullanmamali; durumu, etkisini (bot calismaya devam ediyor mu?) ve uygulanabilir cozumu net vermelidir. Yatirim garantisi verilmez.
- Her cumle `{name}`, `{symbol}`, `{base}`, `{quote}`, `{regime}` degiskenlerini destekler.
- Cumleler yatirim garantisi vermemeli, "kesin kazanir" gibi ifadeler kullanmamalidir.
- Cumleler veri, risk, bant, volatilite, gecmis pencere ve olculu karar dilinde kalmalidir.
- Havuz buyutulecekse ayni anlamli 100 kopya yerine farkli piyasa baglamlari eklenmelidir.
- UI modulu icinde yeni cumle havuzu acilmaz; sadece merkezi havuz okunur.

## Yeni AI butonu ekleme standardi

1. Sayfada `ui/assets/modules/ai-assistant-spec.js` dosyasini ilgili modülden once yukle.
2. Butonu normal HTML ile olustur.
3. Butona `AIAssistantSpec.applyButton(buttonEl)` uygula.
4. UI metinlerini `AIAssistantSpec.modal`, `AIAssistantSpec.button`, `AIAssistantSpec.copy` alanlarindan oku.
5. CSS gerekiyorsa `--ai-assistant-*` degiskenlerini kullan; yeni renk/radius sabiti yazma.
6. Backend endpoint gerekiyorsa path'i modül icinde sabitleme; `AIAssistantSpec.api` alanina ekle.

## Dogruluk ve risk sinirlari

- Asistan onerileri gecmis veri ve simülasyon tabanlidir; gelecekte kesin getiri vaadi olarak sunulmaz.
- Backend optimizasyon sonucu uygulanmadan once kullanici onayi gerekir.
- Minimum butce, veri kapsama kalitesi ve backend hata durumlari kullaniciya acik gosterilir.
- Hata halinde sistem sessizce bozulmaz; hizli yerel yedek akisa duser.
