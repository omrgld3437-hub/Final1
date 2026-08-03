# Ayserose V2 Yayın Kontrol Listesi

Bu liste, `ayserose.com` yayını öncesinde doğrulanacak kullanıcı kabul ölçütlerinin tek kaynağıdır. Bir madde yalnız kod, üretim derlemesi ve ilgili davranış birlikte doğrulandığında tamamlanır.

## PWA, mobil ve gezinme

- [x] iPhone çentik / Dynamic Island güvenli alanı üst başlıkta korunuyor.
- [x] Mobil alt menü yalnız Anasayfa, Botlar ve Trade içeriyor.
- [x] Profil düğmesi mobil ve masaüstünde aynı görünüyor; ikinci dokunuş ayarları kapatıyor.
- [x] Logo ana sayfanın en üstüne götürüyor.
- [x] Açık modal arka planı kaydırmıyor; modalın kendi içeriği kayabiliyor.
- [x] Alt menü ve modal düğmeleri iPhone alt güvenli alanına taşmıyor.
- [x] PWA çek-bırak yenilemesi canlı cüzdanı zorlar; snapshot, bot motoru, Trade, işlem geçmişi, performans ve finans özetini birlikte günceller.
- [x] Yenileme göstergesi yalnız istekler tamamlanınca başarı verir; ağ veya canlı cüzdan hatasında başarısızlık durumunu gösterir.

## Oturum ve giriş güvenliği

- [x] Giriş sayfasında yalnız giriş formu bulunuyor; kayıt ve şifre sıfırlama görünmüyor.
- [x] Sunucu yeniden başlatması geçerli kalıcı oturumu istemci tarafında düşürmüyor.
- [x] Tekil bir API 401 yanıtı, oturum `whoami` ile doğrulanmadan kullanıcıyı girişe atmıyor.
- [x] Admin hesap görünümünde üstte admin adı değil açılan hesap sahibinin adı görünüyor.
- [x] Yönetici hesap kapsamı ve normal kullanıcı hesap kapsamı birbirine karışmıyor.
- [x] CSRF, HttpOnly çerez, aynı-origin dönüş yolu ve açık yönlendirme kontrolleri korunuyor.

## Ana sayfa

- [x] Bakiye, hızlı özet, cüzdan, bot ve şablon kartları mobil/masaüstünde iç boşluklara sahip.
- [x] 1 USD altındaki cüzdan varlıkları sessizce gizleniyor.
- [x] Varlık sayacı yalnız `N varlık` gösteriyor.
- [x] İşlem geçmişinde miktar, fiyat, toplam ve komisyon gerçek alanlardan okunuyor.
- [x] `Cüzdan` filtresi `Yatırım / çekim` olarak görünüyor.
- [x] Performans açıklaması tamamlanmış tur verisini doğru anlatıyor.
- [x] En iyi bot ayrıntısı ham JSON göstermeden bütün strateji değerlerini anlaşılır sunuyor.
- [x] Şablondan bot başlatma bütçe hariç tüm alanları bot stüdyosuna taşıyor.

## Trade ve coin seçimi

- [x] Boş aramada yalnız favoriler görünüyor.
- [x] Favori özeti günlük değişimi en yüksek (veya zararı en az) favoriyi seçiyor.
- [x] Trade araması Binance'in bütün aktif spot çiftlerinde çalışıyor; BTC ve ETH kotasyonları da fiyat, değişim ve hacimle gösteriliyor.
- [x] Bir harf yazıldığında sonuç listesi açık ve kullanılabilir kalıyor.
- [x] Trade ve bot oluşturucu aynı sembol sözleşmesini kullanıyor.
- [x] Coin görselleri çember içinde kırpılmadan ve boşluk korunarak görünüyor.
- [x] USDT ve SOL görselleri kendi dairesel kabuklarını tamamen dolduruyor; köşeler kabuk dışında görünmüyor.

## Bot oluşturma

- [x] Dinamik mod aç/kapat çalışıyor; sabit girdiler yalnız çarpanlarla uyarlanıyor.
- [x] Dinamik mod altındaki üç açıklama kutusu kaldırıldı.
- [x] Parametre Asistanı açıklaması 45 veri/indikatör kapsamını doğru anlatıyor.
- [x] Üretilen bütün dağılım, alış/satış grid, trailing ve kâr döngüsü değerleri görünür.
- [x] Güven ve maksimum alış özet kutuları kaldırıldı.
- [x] `Yedek dağılımı` yerine `Base dağılımı` ifadesi kullanılıyor.
- [x] Ham asistan yapılandırması ve canlı yapı özeti kaldırıldı.
- [x] Asistan profil/rejim kararı kullanıcı dilinde okunuyor.
- [x] Bot sermayesi alanında başlangıçtaki sıfır yeni girişin önünde kalmıyor; tarayıcı sayı sayaçları gizli.
- [x] Bot oluşturucu tüm spot çiftlerini aratıyor; mevcut motor sözleşmesi dışındaki kotasyonlarda riskli bot oluşturmayı açıkça engelliyor.

## Bot listesi

- [x] Kartta durdurma ve silme düğmeleri yok; yalnız ayrıntıda bulunuyor.
- [x] Ayrıntıda durdurma eylemi yok; silme işlemi aktif botu sunucuda güvenle durdurup kaldırıyor.
- [x] Tur etiketi `Aktif tur` olarak güncel bot döngüsünü gösteriyor.
- [x] Bot kartı açılışı ve bot ayrıntısına geçiş gecikmesiz hissediliyor.
- [x] Trade, Botlar ve Ayarlar sekmeleri geçişte yeniden kurulmadığı için arama ve yerel ekran durumu korunuyor.

## Bot ayrıntısı — özet

- [x] `Canlı` sekmesi kaldırıldı; sağlık bilgisi gerekli yerde sessizce korunuyor.
- [x] Yenileme frekansı, başlangıç dağılımı durumu ve ham yanıt metinleri kaldırıldı.
- [x] Base ve quote bakiye/değerleri doğru varlık adı ve dinamik ondalıkla gösteriliyor.
- [x] Dinamik mod yeşil; kapalıysa pasif `Sabit mod` kartı olarak gösteriliyor.
- [x] Strateji parametreleri ham alan listesi olmadan anlaşılır özetleniyor.
- [x] Strateji parametreleri özetin en üstünde; alış ve satış trailing değerleri ilgili grid başlığında.
- [x] Bot silindikten sonra ayrıntı sayfasından çıkılıyor.

## Bot ayrıntısı — grid

- [x] Üstte yalnız aşama, çalışma yönü ve ana rejim uzun kartları bulunuyor.
- [x] Çalışma yönü `Alış Gridler Aktif` veya `Satış Gridler Aktif` diyor.
- [x] Aşama tamamlanan grid sayısı ve sıradaki grid durumunu cümleyle anlatıyor.
- [x] Referans fiyat yalnız bir kez gösteriliyor.
- [x] Başlıklar `Yukarı Satış Gridleri` ve `Aşağı Alış Gridleri`; sayaç `N grid` diyor.
- [x] Grid numarası 1'den başlıyor; kartlarda sol iç boşluk var.
- [x] Tamamlanan gridde yeşil onay işareti bulunuyor.
- [x] Pay etiketi yöne göre `Satış miktarı` / `Alış miktarı`.
- [x] Tetiklenmeyen grid `Tetik bekleniyor` diyor.
- [x] Yön kesinleşince devre dışı kalan ana grid şeridi gizleniyor.
- [x] Kâr döngüsü yönüne göre avantajlı alış/satış açıklamasını gösteriyor.
- [x] Ham grid tablosu, fiyat alanları ve yanıt dökümleri kaldırıldı.

## Bot ayrıntısı — turlar ve işlemler

- [x] Manuel yenile düğmesi yok; görünürken kendini güncelliyor.
- [x] Açık turun sonuç kartı gösterilmiyor; yalnız tamamlanan tur sonuçları var.
- [x] Süre dakika/saat/gün/ay ölçeğinde okunabilir.
- [x] İlk turdaki başlangıç base alımı ayrı kartta görünüyor.
- [x] Ham işlem, tur özeti ve tur listesi alanları kaldırıldı.

## Admin

- [x] Acil bakım konsolu düğmesi yok.
- [x] Bekleyen kayıt kartı ve Kayıt Talepleri sekmesi yok.
- [x] Operasyon özetinde veri kaynağı sağlığı, hızlı inceleme ve okunmamış sohbet kartı yok.
- [x] Üstteki `Merhaba Admin...` açıklaması yok.
- [x] Sunucu IP, ağ trafiği ve bağlantı kapasitesi anlamlı fallback ile görünüyor.
- [x] Hata kayıtlarını sıfırlama eylemi açık onayla çalışıyor.
- [x] Admin pop-up'ı normal kullanıcı V2 ekranına ulaşıyor ve kapatılabiliyor.
- [x] Hesap listesi paralel canlı bakiye toplama ve kısa süreli sunucu önbelleğiyle gecikmeyi azaltıyor.
- [x] Portföy ve İletişim yalnız test hesabında görünüyor.
- [x] Canlı bağlantı düğmesi masaüstünde kullanıcı adının solunda.
- [x] Hesap adlarının altında teknik ID gösterilmiyor; hesap kapsamı değişiminde önceki hesabın verisi bellekte tutulmuyor.

## Kalite, performans ve yayın

- [x] TypeScript denetimi hatasız.
- [x] Üretim derlemesi hatasız ve boyut bütçesi içinde.
- [x] Veri, ondalık, auth, cutover ve PWA sözleşme testleri geçiyor.
- [x] Kritik ekranlar mobil ve masaüstü genişliklerinde tarayıcıyla doğrulanıyor.
- [x] Klavye odağı, Escape, aria etiketleri ve reduced-motion davranışı kontrol ediliyor.
- [x] Kayıtlı hata logları incelendi; anlamsız tarama 404'leri ve beklenen oturum 401'leri yeni hata kaydı oluşturmuyor.
- [x] Frontend yalnız V2 hedef klasörüne yayınlanıyor; eski UI'ye dönen bağlantı kalmıyor.
- [x] Kimlik doğrulamalı ekranlar izole gerçek API testinde; canlı alan adı, giriş, eski URL geçişleri ve yayın paketi dışarıdan doğrulanıyor.

## Son doğrulama kaydı

- 21 Temmuz 2026: TypeScript, üretim derlemesi ve frontend sözleşme testleri geçti.
- 21 Temmuz 2026: Auth, oturum, PWA, yayın ve bot sağlık testlerinde 40 test geçti; 4 koşula bağlı test atlandı.
- 21 Temmuz 2026: 390×844 mobil ve 1440 px masaüstü tarayıcı kontrollerinde yatay taşma ve konsol hatası görülmedi.
- 21 Temmuz 2026: Canlı sağlık yanıtı, 603 fiyat, çalışan worker ve üç aktif servis doğrulandı.
- 21 Temmuz 2026: Yayın sonrası son 30 dakikalık hata akışı boş; 401/404 filtre probları veritabanında 0 kayıt bıraktı.
- 21 Temmuz 2026: Bot özetinde ikinci tur dinamik parametreleri başlangıç değeri → uygulanan değer → çarpan biçiminde doğrulandı.
- 21 Temmuz 2026: Aktif grid yönü tek şerit, dinamik kâr döngüsü başlığı ve mobil kart ipucu 390 px görünümde doğrulandı.
- 21 Temmuz 2026: Trade favori fiyat/değişim hızlı yüklemesi, mobil/masaüstü kart boşlukları ve eşit bot işlem düğmeleri doğrulandı.
- 21 Temmuz 2026: Tüm spot parite araması, hacim/değişim eşlemesi, tek harf coin önerisi, sekmeler arası arama korunumu ve sermaye sıfır girdisi tarayıcıda doğrulandı.
- 21 Temmuz 2026: Profil metinleri, kalıcı hesap silme açıklaması ve güvenli olmayan USDT-dışı bot oluşturma sınırı tarayıcıda doğrulandı.
- 21 Temmuz 2026: Hesap kapsamı, bot hesap izolasyonu ve PWA kalıcı oturum paketinde 11 test geçti; 3 koşula bağlı test atlandı.
- 22 Temmuz 2026: PWA çek-bırak yenilemesi canlı cüzdan, snapshot ve sekme verileri için genişletildi; frontend sözleşmesi ile 9 cüzdan/PWA backend testi geçti.
