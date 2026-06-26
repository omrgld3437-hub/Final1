/*
 * ai-assistant-spec.js
 *
 * AI asistan butonu, sohbet/akış dili, metin havuzu ve UI davranışları için
 * tek kaynak. Yeni bir ekranda AI butonu ya da asistan motoru kullanılacaksa
 * kopyalama yapılmaz; bu dosyadaki AIAssistantSpec okunur.
 */
(function () {
    "use strict";

    function buildParamAssistantScenarioPool() {
        var openings = [
            "Selam {name}, {symbol} ekranında önce veriyi sakin okuyorum;",
            "Merhaba {name}, {symbol} için tek bir sinyale yaslanmadan ilerliyorum;",
            "{name}, {base}/{quote} tarafında önce piyasanın ritmini ayırıyorum;",
            "Şu an {symbol} için tabloyu uçtan uca kontrol ediyorum;",
            "{name}, öneriyi kurmadan önce {symbol} verisini risk ve fırsat tarafıyla birlikte tartıyorum;",
            "Bu okuma {symbol} için sadece fiyat hareketine değil, çalışma alanına da bakıyor;",
            "{base} bacağında aceleci davranmadan {quote} rezervini de hesaba katıyorum;",
            "{name}, burada hedefim gösterişli değil, uygulanabilir bir parametre seti çıkarmak;",
            "{symbol} için canlı değerleri geçmiş karakterle aynı çerçeveye koyuyorum;",
            "Parametreleri yazmadan önce {symbol} tarafında trend, bant ve emir gerçekliğini birlikte süzüyorum;"
        ];
        var evidence = [
            "anlık fiyat {price}, 24s değişim {change}, veri kapsaması {coverage} seviyesinde.",
            "rejim {regime}, volatilite {volatility}, trend skoru {trendScore}; bu üçlü grid mesafesini belirleyen ana omurga.",
            "ADX {adx} ve RSI {rsi} beraber okunduğunda momentum ile yorulma sinyali ayrışıyor.",
            "ATR bileşiği {volUnit}, önerilen step {stepPct}; yani gridler gürültüye fazla yapışmadan yerleşiyor.",
            "risk skoru {riskScore}/100, fırsat skoru {opportunityScore}/100; öneri bu iki değerin dengesine göre şekilleniyor.",
            "bütçe {budget} {quote}; minimum emir gerçekliği nedeniyle seviye sayısını {upGridCount}/{downGridCount} dengesinde tutuyorum.",
            "başlangıç dağılımı base %{basePct} / quote %{quotePct}; iki bacağın da çalışabilir kalması için bu oranı koruyorum.",
            "satış trailing %{upTrail}, alış trailing %{downTrail}; tetik geldikten sonra dönüş teyidi arıyorum.",
            "geçmiş pencere özeti {dataText}; veri zayıfsa güveni aşağı çekip öneriyi daha temkinli kuruyorum.",
            "güven skoru {confidence}/100; bu skor hem veri kalitesini hem de rejim uyumunu birlikte yansıtıyor."
        ];
        var decision = [
            "Bu yüzden grid aralığını daraltırken komisyon tabanını ezmiyorum.",
            "Bu yüzden öneri, hızlı kazanç vaadi yerine ölçülü kapanabilirlik üzerine kuruluyor.",
            "Bu yüzden alım ve satım tarafını aynı anda canlı bırakacak bir dağılım seçiyorum.",
            "Bu yüzden trend baskısı artarsa mesafeyi açıp gereksiz tetikten kaçınıyorum.",
            "Bu yüzden yataylık güçlüyse grid verimini artıracak ama aşırı sıkışmayacak bir yapı seçiyorum.",
            "Bu yüzden düşük bütçede seviye sayısını şişirmeden her emrin çalışabilir olmasına öncelik veriyorum.",
            "Bu yüzden trailing yüzdelerini fiyatın normal nefes aralığıyla uyumlu tutuyorum.",
            "Bu yüzden risk yükseldiğinde fırsat skoru iyi olsa bile öneriyi kontrollü agresiflikte bırakıyorum.",
            "Bu yüzden geçmiş getiri tek başına karar vermiyor; drawdown ve volatilite de aynı ağırlıkta okunuyor.",
            "Bu yüzden formdaki her inputu aynı mantık zincirinin parçası olarak dolduruyorum."
        ];
        var close = [
            "Sonuç: bu set veriye bağlı, ama geleceği garanti etmez; amaç daha tutarlı bir çalışma alanı kurmak.",
            "Bu okuma kesinlik iddiası değil; canlı piyasa değişirse parametreler yeniden kontrol edilmelidir.",
            "Ben bu öneriyi mevcut verinin en tutarlı senaryosu olarak yazıyorum; son karar yine risk tercihine bağlı."
        ];
        var out = [];
        for (var i = 0; i < 300; i++) {
            out.push(
                openings[i % openings.length] + " " +
                evidence[Math.floor(i / openings.length) % evidence.length] + " " +
                decision[Math.floor(i / (openings.length * evidence.length)) % decision.length] + " " +
                close[i % close.length]
            );
        }
        return out;
    }

    function buildParamAssistantRationalePool() {
        function make(count, leads, metrics, conclusions) {
            var out = [];
            for (var i = 0; i < count; i++) {
                out.push(
                    leads[i % leads.length] + " " +
                    metrics[Math.floor(i / leads.length) % metrics.length] + " " +
                    conclusions[Math.floor(i / (leads.length * metrics.length)) % conclusions.length]
                );
            }
            return out;
        }
        return {
            overview: make(30, [
                "Önerinin ana mantığı şu:",
                "Bu seti seçerken ilk baktığım şey tek bir gösterge değil, göstergelerin birlikte anlattığı tablo oldu:",
                "Ben bu parametreleri bir tahmin cümlesi gibi değil, risk-fırsat dengesi gibi kurdum:",
                "Bu öneride önce piyasa karakterini, sonra botun taşıyabileceği emir yapısını eşleştirdim:",
                "Parametreleri seçerken önceliğim hızlı görünmek değil, çalışabilir bir grid iskeleti kurmaktı:"
            ], [
                "{symbol} tarafında rejim {regime}, volatilite {volatility}, risk {riskScore}/100 ve fırsat {opportunityScore}/100 seviyesinde.",
                "Veri kapsaması {coverage}; bu yüzden kararlar canlı fiyat, geçmiş pencere ve güven skoru birlikte okunarak verildi.",
                "Anlık fiyat {price}, 24s değişim {change}; bu hareket geçmiş penceredeki bantlarla karşılaştırıldı."
            ], [
                "Bu yüzden öneri, agresif bir kâr vaadi yerine daha kontrollü tetik, kapanış ve sermaye dağılımı mantığına dayanıyor.",
                "Bu yapı, piyasa değişirse yeniden kontrol edilmesi gereken ama mevcut veride tutarlı görünen bir başlangıç setidir."
            ]),
            budget: make(30, [
                "Bütçe kararını {budget} {quote} üzerinden kurdum:",
                "Bütçe tarafında en kritik sınır minimum emir gerçekliğiydi:",
                "{quote} bütçesini grid sayısına bölerken temel hedefim her seviyeyi çalışabilir bırakmaktı:",
                "Bu bütçeyle çok fazla seviye açmak kağıt üzerinde güzel görünse de pratikte emirleri zayıflatabilir:",
                "Bütçe seçiminde botun nefes alanı ile emir büyüklüğü arasında denge aradım:"
            ], [
                "seviye dengesi {upGridCount} satış / {downGridCount} alış olarak tutuldu.",
                "grid sayısı, minimum emir tutarı ve komisyon etkisi aynı anda kontrol edildi.",
                "çok küçük emirlerin komisyonla ezilmemesi için bütçe bölünmesi sınırlı tutuldu."
            ], [
                "Bu yüzden sayı çoğaltmak yerine daha az ama uygulanabilir seviye tercih edildi.",
                "Amaç her gridin piyasada gerçekten emir olabilecek güçte kalmasıdır.",
                "Bütçe artarsa seviye sayısı genişletilebilir; bütçe düşerse bu disiplin daha da önemli olur."
            ]),
            allocation: make(30, [
                "Başlangıç dağılımını base %{basePct} / quote %{quotePct} seçmemin nedeni şu:",
                "Base ve quote dağılımında tek tarafı tamamen boş bırakmak istemedim:",
                "Dağılım kararı, botun hem yükseliş hem düşüş tarafında işlem üretebilmesi için kuruldu:",
                "Bu oranı seçerken sadece bugünkü fiyatı değil, iki bacağın çalışabilirliğini düşündüm:",
                "Sermaye dağılımında ana fikir, botu tek yönlü bir bahse çevirmemekti:"
            ], [
                "{regime} rejiminde trend baskısı ile geri dönüş ihtimali aynı anda okunuyor.",
                "risk {riskScore}/100 olduğu için quote rezervi tamamen tüketilmedi.",
                "fırsat {opportunityScore}/100 olduğu için base tarafı da tamamen zayıf bırakılmadı."
            ], [
                "Bu sayede fiyat yukarı giderse satış bacağı, aşağı gelirse alış bacağı hâlâ anlamlı kalır.",
                "Dağılımın amacı maksimum iddia değil, iki yönlü devam edilebilirliktir.",
                "Piyasa sert tek yöne kırılırsa bu oran yeniden gözden geçirilmelidir."
            ]),
            sellGrid: make(30, [
                "Satış gridlerini {sellGridText} şeklinde seçmemin arkasındaki mantık:",
                "Yukarı yön seviyelerinde çok yakın tetik kullanmadım çünkü:",
                "Satış tarafındaki grid aralığı, yükselişi erken boğmadan kâr alma alanı bırakmak için seçildi:",
                "Satış gridleri fiyatın normal salınımına değil, anlamlı yukarı harekete tepki versin istedim:",
                "Bu satış merdiveni, base tarafını tek seferde boşaltmak yerine kademeli çalıştırmak için kuruldu:"
            ], [
                "step {stepPct}, ATR bileşiği {volUnit} ve trend skoru {trendScore} birlikte okundu.",
                "rejim {regime}; bu yüzden satış seviyeleri ne fazla yakın ne de ulaşılamayacak kadar uzak tutuldu.",
                "risk {riskScore}/100 olduğu için satış kademeleri sermayeyi kontrollü boşaltacak şekilde dağıtıldı."
            ], [
                "Böylece bot yükselişte parça parça realize eder, ama tüm pozisyonu tek mumda tüketmez.",
                "Bu seçim, hızlı tepkiye değil, daha temiz kapanış ihtimaline öncelik verir.",
                "Eğer piyasa çok güçlü trend üretirse satış gridleri tekrar genişletilebilir."
            ]),
            buyGrid: make(30, [
                "Alış gridlerini {buyGridText} olarak seçmemin nedeni:",
                "Aşağı yön seviyelerinde amaç panik alımı değil, kontrollü geri çekilme toplamak:",
                "Alış tarafını kurarken düşüşün normal gürültü mü yoksa gerçek baskı mı olduğunu ayırmaya çalıştım:",
                "Bu alış merdiveni, quote rezervini tek noktada harcamamak için kademeli tasarlandı:",
                "Alış gridleri, fiyat düşerken botun aceleci değil ölçülü davranması için ayarlandı:"
            ], [
                "drawdown ve downside volatilite risk skoru {riskScore}/100 içine yansıtıldı.",
                "ATR bileşiği {volUnit} olduğu için gridler çok sıkışık bırakılmadı.",
                "fırsat skoru {opportunityScore}/100, geri çekilmenin çalışılabilir olup olmadığını gösterdi."
            ], [
                "Bu nedenle alışlar dip tahmini yapmaz; fiyat alan verdikçe kademeli pozisyon kurar.",
                "Amaç tek seferde en iyi yeri bulmak değil, düşüşü yönetilebilir parçalara bölmektir.",
                "Sert düşüşte quote rezervinin korunması için bu dağılım bilinçli olarak ölçülü tutuldu."
            ]),
            trailing: make(30, [
                "Trailing değerlerini satış %{upTrail} / alış %{downTrail} seçmemin nedeni:",
                "Trailing tarafında doğrudan tetik yerine dönüş teyidi arıyorum:",
                "Bu yüzdeler, tetik görüldükten sonra fiyatın gerçekten yön değiştirip değiştirmediğini okumak için seçildi:",
                "Satış ve alış trailing'i aynı mantıkla ama farklı piyasa hareketlerine göre dengelendi:",
                "Trailing seçimi, grid tetiklerinin hemen emirleşip gürültüye yakalanmasını azaltmak için yapıldı:"
            ], [
                "volatilite {volatility}, ATR bileşiği {volUnit} ve step {stepPct} aynı bantta değerlendirildi.",
                "çok düşük trailing gereksiz emir, çok yüksek trailing kaçan kapanış riski doğurur.",
                "rejim {regime} olduğu için dönüş onayı tamamen gevşek bırakılmadı."
            ], [
                "Bu yüzden trailing, tetik sonrası küçük bir teyit filtresi gibi çalışacak seviyede tutuldu.",
                "Amaç en tepeden/en dipten işlem iddiası değil, daha makul kapanış yakalamaktır.",
                "Volatilite değişirse ilk kontrol edilecek alanlardan biri bu trailing yüzdeleridir."
            ]),
            profitCycle: make(30, [
                "Kâr döngüsü tarafında rebuy %{rebuyTrigger} ve resell %{resellTrigger} seçimini şöyle kurdum:",
                "Rebuy/resell değerleri gridlerden ayrı, kapanan turun yeniden devreye giriş mantığını yönetiyor:",
                "Bu bölümde amaç, tur kapandıktan sonra botun yeni döngüye fazla erken ya da fazla geç dönmemesi:",
                "Kâr döngüsü eşikleri, kapanış sonrası piyasanın gerçekten alan verip vermediğini görmek için seçildi:",
                "Re-entry ve profit-exit tarafını birbirine çok yakın tutmadım çünkü:"
            ], [
                "trend skoru {trendScore}, risk {riskScore}/100 ve fırsat {opportunityScore}/100 birlikte değerlendirildi.",
                "rejim {regime}; bu yüzden tur sonrası tekrar girişte kontrollü mesafe kullanıldı.",
                "güven {confidence}/100 olduğu için aşırı iddialı bir yeniden giriş eşiği seçilmedi."
            ], [
                "Bu, botun kapattığı kârı hemen geri vermesini azaltmaya yardımcı olur.",
                "Bu eşikler piyasaya tekrar dahil olmayı geciktirmez, ama küçük gürültüye de atlamaz.",
                "Döngü performansı birkaç tur sonra ölçülüp yeniden kalibre edilebilir."
            ]),
            risk: make(30, [
                "Risk denklemini özellikle ayrı tuttum:",
                "Bu öneride risk sadece düşüş ihtimali demek değil:",
                "Risk skorunu {riskScore}/100 görmemin nedeni, birkaç zayıf sinyalin birlikte okunması:",
                "Fırsat skoru {opportunityScore}/100 olsa bile risk tarafını tamamen yok saymadım:",
                "Parametreleri seçerken risk ve fırsatı aynı terazide tuttum:"
            ], [
                "drawdown, downside volatilite, trend baskısı ve veri kapsaması birlikte değerlendirildi.",
                "risk {riskScore}/100, fırsat {opportunityScore}/100; yani yapı ne tamamen savunmacı ne de kontrolsüz agresif.",
                "veri kapsaması {coverage}, güven {confidence}/100; bu da önerinin temkin seviyesini belirledi."
            ], [
                "Bu yüzden gridler çalışabilir ama aşırı sıkışık değil.",
                "Bu yüzden sermaye dağılımı iki bacağı da canlı tutacak şekilde seçildi.",
                "Risk artarsa önce grid mesafesi ve trailing yeniden kontrol edilmelidir."
            ]),
            confidence: make(30, [
                "Güven skorunu {confidence}/100 olarak vermemin nedeni:",
                "Bu önerinin güveni sadece son fiyata dayanmıyor:",
                "Güven puanı, verinin tutarlılığı ile piyasa rejiminin okunabilirliğini birleştiriyor:",
                "Ben bu skoru bir kesinlik değil, önerinin dayanıklılık göstergesi olarak kullanıyorum:",
                "Bu setin güven seviyesini hesaplarken şu çerçeveyi kullandım:"
            ], [
                "kapsama {coverage}, rejim {regime}, volatilite {volatility}, risk {riskScore}/100.",
                "çoklu pencere verisi, kısa vade momentum ve uzun karakter aynı yöne ne kadar bakıyor diye kontrol edildi.",
                "ADX {adx}, RSI {rsi}, trend skoru {trendScore} ve ATR {volUnit} aynı tabloda okundu."
            ], [
                "Bu skor yüksek olsa bile geleceği garanti etmez; sadece mevcut verinin öneriyi ne kadar desteklediğini gösterir.",
                "Bu yüzden sonucu uygulamadan önce bütçe ve risk iştahıyla uyumlu olup olmadığı tekrar düşünülmelidir.",
                "Canlı piyasa karakteri değişirse güven skoru da aynı hızda yeniden okunmalıdır."
            ]),
            final: make(30, [
                "Özetle bu parametreleri seçmemin nedeni:",
                "Kısa karar cümlesiyle toparlarsam:",
                "Bu setin arkasındaki ana fikir şu:",
                "Sonuç olarak öneri şu mantığa dayanıyor:",
                "Benim bu öneride korumaya çalıştığım denge şu:"
            ], [
                "bütçe çalışabilir kalıyor, iki bacak boş kalmıyor, gridler ATR ve riskle uyumlu, trailing ise dönüş teyidi arıyor.",
                "fiyatın normal gürültüsüyle gerçek hareketini ayırmaya çalışan ölçülü bir yapı oluşuyor.",
                "risk-fırsat dengesi, komisyon tabanı ve geçmiş bantlar aynı anda hesaba katılıyor."
            ], [
                "Bu nedenle öneri agresif bir iddia değil; kontrollü, açıklanabilir ve gerektiğinde yeniden kalibre edilebilir bir başlangıç planıdır.",
                "Bu planın başarısı tek mumla değil, birkaç tur boyunca net sonuç, komisyon ve kapanış kalitesiyle ölçülmelidir.",
                "Uygulandıktan sonra en iyi kontrol noktaları grid doluluk oranı, tur kapanış kalitesi ve alpha etkisidir."
            ])
        };
    }

    /*
     * Hata Asistanı bilgi tabanı.
     * Her sağlık/bağlantı kodu için zengin, input-aware bir tanı havuzu tutar:
     *   what  -> "ne oluyor" (durum tarifi, çoklu varyant)
     *   why   -> "neden" (kök sebep adayları, çoklu varyant)
     *   impact-> botun işlemine/paraya etkisi (çalışmaya devam ediyor mu?)
     *   steps -> sırayla uygulanabilir, ince ayrıntılı çözüm adımları
     *   actions -> UI'da tek tıkla oto-düzeltme/yönlendirme buton kimlikleri
     * needsAdmin true ise modal en altta "Yönetimle sohbet" butonunu açar.
     * Tüm cümle havuzu burada (merkezde) durur; UI modülü kendi havuzunu açmaz.
     */
    function buildErrorAssistant() {
        var themes = {
            connectivity: {
                id: "connectivity",
                label: "Binance bağlantısı ve API erişimi",
                root: "botun Binance'e ulaşması",
                connect: [
                    "Bu uyarıların hepsi aynı kökten besleniyor: {symbol} botunun Binance ile konuşması şu an sağlıklı değil.",
                    "Aşağıdaki maddeler ayrı ayrı görünse de tek bir zincire bağlı — Binance/API erişimi kesilince hepsi peş peşe tetikleniyor.",
                    "Bunları tek tek değil, tek bir bağlantı sorunu olarak okumak doğru olur; erişim düzelince çoğu kendiliğinden kapanır."
                ]
            },
            funds: {
                id: "funds",
                label: "Bütçe, bakiye ve emir büyüklüğü",
                root: "emir tutarı ile bakiye/limit uyumu",
                connect: [
                    "Bu maddeler aynı temaya bakıyor: emirlerin Binance'in minimum tutar/lot kurallarıyla ya da serbest bakiyenle uyumu.",
                    "Hepsi bütçe-emir büyüklüğü dengesiyle ilgili; bütçeyi veya grid yüzdesini ayarlamak bu uyarıların çoğunu birlikte çözer.",
                    "Bunları tek bir başlık altında topluyorum çünkü kök neden ortak: emir, çalışabilir minimum büyüklüğün altına düşüyor."
                ]
            },
            runtime: {
                id: "runtime",
                label: "Motor döngüsü ve çalışma zamanı",
                root: "engine döngüsünün kesintisiz dönmesi",
                connect: [
                    "Bu kayıtlar motor döngüsünün sağlığıyla ilgili; çoğu kendi kendini toparlayan, izlenmesi gereken olaylardır.",
                    "Aynı olayın farklı yüzleri: döngü bir an takıldı/yeniden açıldı. Sistem otomatik kurtarmayı zaten deniyor.",
                    "Bunları tek bir 'çalışma zamanı' başlığında birleştiriyorum; tekrarlamadığı sürece müdahale gerektirmez."
                ]
            },
            data: {
                id: "data",
                label: "Tick akışı ve fiyat verisi",
                root: "taze fiyat/tick verisi",
                connect: [
                    "Bu uyarılar veri tazeliğiyle ilgili: bot, karar verecek güncel fiyatı/tick'i beklemek zorunda kaldı.",
                    "Hepsi aynı noktaya işaret ediyor — veri akışı bir süre duraksadı; akış dönünce bot kaldığı yerden devam eder.",
                    "Bunları tek başlıkta topluyorum çünkü ortak sebep aynı: piyasa verisi ya da tick zamanında gelmedi."
                ]
            },
            liquidity: {
                id: "liquidity",
                label: "Likidite ve piyasa koşulları",
                root: "piyasa derinliği ve eşzamanlı erişim",
                connect: [
                    "Bu maddeler piyasa koşullarıyla ilgili: kayma ve kilit meşguliyeti çoğunlukla volatilite/likidite kaynaklıdır.",
                    "İkisi de aynı ortamı anlatıyor — hareketli ya da ince bir piyasada bot temkinli davranıyor."
                ]
            },
            wallet: {
                id: "wallet",
                label: "Cüzdan görünürlüğü",
                root: "cüzdan snapshot tazeliği",
                connect: [
                    "Bu uyarı işlem döngüsünü değil, bakiyenin ekranda ne kadar güncel göründüğünü etkiler."
                ]
            },
            generic: {
                id: "generic",
                label: "Genel bot sağlığı",
                root: "botun genel durumu",
                connect: [
                    "Aşağıdaki bulguları birlikte değerlendiriyorum."
                ]
            }
        };

        var persona = {
            openings: [
                "Merhaba {name}, {symbol} botunu uçtan uca taradım.",
                "Selam {name}, {symbol} için sağlık taramasını yaptım; durumu birlikte okuyalım.",
                "{name}, {symbol} botunun son tick'ini, loglarını ve Binance bağlantısını kontrol ettim.",
                "Merhaba {name}, {symbol} tarafında neler olduğuna baktım ve özetliyorum.",
                "Selam {name}, {symbol} botunun motor durumunu, emir geçmişini ve bağlantısını gözden geçirdim.",
                "{name}, {symbol} için tanı motorunu çalıştırdım; bulgular şöyle.",
                "Merhaba {name}, {symbol} botunu inceledim — sana net bir tablo çıkarıyorum.",
                "Selam {name}, {symbol} için sağlık kontrolü tamam; önemli noktaları sıralıyorum.",
                "{name}, {symbol} botunda durumu taradım; gürültüye boğmadan en kritik şeyi öne alıyorum.",
                "Merhaba {name}, {symbol} için bağlantı, tick, emir ve bakiye tarafını birlikte denetledim."
            ],
            healthy: [
                "İyi haber: {symbol} botunda aktif bir hata yok. Son tick zamanında geldi, döngü çalışıyor ve Binance bağlantısı sağlıklı.",
                "{symbol} botu şu an sorunsuz görünüyor. Emirler reddedilmiyor, tick akışı düzenli; bakiye ve bağlantı tarafında uyarı yok.",
                "Taradım ve kritik ya da uyarı seviyesinde bir bulgu çıkmadı. Bot normal ritminde çalışıyor; yapman gereken bir şey yok.",
                "Her şey yolunda {name}: {symbol} için döngü canlı, fiyat verisi taze ve son işlemlerde reddedilen emir görmüyorum.",
                "{symbol} botu sağlıklı. Bağlantı açık, tick gecikmesi yok ve son 15 dakikada tekrarlayan bir emir/kilit uyarısı bulamadım.",
                "Net söyleyeyim: aktif sorun yok. {symbol} botu beklenen şekilde çalışıyor, müdahale gerektiren bir durum görmüyorum.",
                "Kontrol ettim {name}, {symbol} tarafı temiz. Motor dönüyor, emirler geçiyor, Binance erişimi stabil.",
                "Şu an alarm yok. {symbol} botu düzenli tick atıyor ve bağlantı/bakiye tarafında çözülmemiş bir uyarı kalmamış."
            ],
            healthyChecks: [
                "Son tick tazeliği ve motor döngüsünün canlılığı",
                "Binance API erişimi, anahtar yetkisi ve IP beyaz listesi",
                "Emir reddi geçmişi (LOT_SIZE / MIN_NOTIONAL / yetersiz bakiye)",
                "Fiyat verisi akışı ve cüzdan snapshot tazeliği",
                "Son 15 dakikadaki kayma (slippage) ve kilit meşguliyeti uyarıları"
            ],
            healthyClose: [
                "Durum değişirse bu paneli tekrar açıp güncel tanıyı alabilirsin.",
                "Yeni bir uyarı düşerse anında buraya yansır; istediğinde 'Yeniden tara' diyebilirsin.",
                "İçin rahat olsun; bir sorun belirirse burada en ince ayrıntısına kadar açıklarım."
            ],
            stopped: [
                "{symbol} botu şu an çalışmıyor (durdurulmuş). Bu bir hata değil; bot durdurulduğu için sağlık taraması beklemede.",
                "Bot duraklatılmış durumda, bu yüzden aktif tick/emir taraması yapmıyorum. Başlattığında tekrar kontrol edebilirim.",
                "{symbol} botu çalışır durumda değil. Hata izleme yalnızca çalışan botlarda anlamlı; çalıştırınca durumu tazelerim."
            ],
            stoppedClose: [
                "Botu çalıştırdıktan birkaç tick sonra bu paneli açarsan canlı tanıyı veririm."
            ],
            closings: [
                "Bir adımı denedikten sonra 'Yeniden tara' ile sonucu birlikte görebiliriz.",
                "Takıldığın yer olursa adımları tek tek geçebiliriz; acele etme.",
                "Uyguladıktan sonra uyarı kapanmazsa bana tekrar sor, daha derine inerim."
            ],
            reassure: [
                "Panik yok — bu durumda fonların borsada güvende, mesele botun şu anki davranışıyla ilgili.",
                "Bu tür uyarılar genelde toparlanabilir; adımları izleyince çoğu kısa sürede kapanır.",
                "Endişelenme, ne olduğunu ve nasıl düzeleceğini adım adım anlatıyorum."
            ],
            adminPrompt: [
                "Bu noktada bazı kontroller sunucu/yönetim tarafında. Takılırsan aşağıdaki butondan yönetim ekibine yazabilirsin; gerekli detayı hazır göndereceğim.",
                "Adımlar sonuç vermezse bu konu yönetim tarafında bir kontrol gerektirebilir — alttaki sohbet butonuyla destek ekibine ulaşabilirsin.",
                "Eğer kendi tarafındaki adımları denediysen ve sorun sürüyorsa, bunu yönetim ekibinin görmesi en sağlıklısı. Sohbeti aşağıdan açabilirsin."
            ],
            severityWord: {
                critical: "Kritik",
                warn: "Uyarı",
                info: "Bilgi"
            },
            genericUnknown: {
                what: [
                    "{symbol} botunda standart kataloğumda olmayan bir durum kodu ({code}) gördüm; yine de elimden gelen yorumu yapayım.",
                    "{symbol} için alışılmadık bir kod ({code}) düştü; net bir tanı yerine güvenli bir yol haritası vereyim."
                ],
                why: [
                    "Bu kod bilinen sağlık listemde yok; nadir ya da yeni bir durum olabilir.",
                    "Tanımlı bir şablonu olmadığı için kök nedeni logdaki ham satırdan okumak en doğrusu."
                ],
                impact: [
                    "Emin olmadığım için temkinli yaklaşıyorum; ham log satırı en güvenilir bilgiyi verir."
                ],
                steps: [
                    "Bot Logları'nda {code} koduna ait satırı bul ve oku.",
                    "Birkaç dakika bekleyip 'Yeniden tara' de; geçiciyse kapanabilir.",
                    "Sürerse aşağıdaki sohbetten {code} kodunu yönetim ekibine ileterek sor."
                ]
            }
        };

        function e(cfg) { return cfg; }

        var codeBook = {
            // ---- Tick / veri teması ----
            TICK_STALE_WARN: e({
                label: "Tick gecikmesi", level: "warn", theme: "data",
                continues: true, needsAdmin: false,
                what: [
                    "{symbol} botu çalışıyor görünüyor ama son tick beklenenden geç geldi (yaklaşık {tickAge}s önce, beklenen aralık ~{interval}s).",
                    "Motor hâlâ ayakta, yalnızca tick ritmi bir miktar yavaşladı; grid değerlendirmesi normalden geç dönüyor."
                ],
                why: [
                    "Worker geçici olarak yük altında olabilir ya da kısa bir ağ/veri duraksaması yaşanmış olabilir.",
                    "Aynı sunucuda çok sayıda bot aynı anda tick atıyorsa sıra beklemesi tek tük gecikme yaratabilir."
                ],
                impact: [
                    "Bu seviyede emirler durmaz; bot kaldığı yerden devam eder, sadece tepki süresi biraz uzar."
                ],
                steps: [
                    "Birkaç dakika bekle; çoğu tick gecikmesi worker yükü düşünce kendiliğinden normale döner.",
                    "Logda (Bot Logları) ardışık ERROR ya da 'Atlandı' satırı var mı bak; varsa kök neden orada görünür.",
                    "Gecikme sürer ve kritiğe (tick durdu) dönerse botu durdurup yeniden başlatmak ritmi sıfırlar."
                ],
                actions: ["refresh", "reset"]
            }),
            TICK_STALE_CRIT: e({
                label: "Tick durdu", level: "critical", theme: "data",
                continues: false, needsAdmin: true,
                what: [
                    "{symbol} botu veritabanında çalışır görünüyor ama uzun süredir tick almıyor (son tick ~{tickAge}s önce). Grid/emir mantığı şu an ilerlemiyor.",
                    "Motor 'çalışıyor' durumunda ama fiilen ilerlemiyor: beklenen ~{interval}s aralık çoktan aşıldı, döngü takılmış olabilir."
                ],
                why: [
                    "Engine worker süreci durmuş, çökmüş ya da yeniden başlatılıyor olabilir.",
                    "Binance API erişimi, IP beyaz listesi veya sunucu saati kaymış olabilir; tick döngüsü ilk adımda takılıyordur.",
                    "Döngü bir hatada kilitlenmiş ve otomatik kurtarma henüz devreye girmemiş olabilir."
                ],
                impact: [
                    "Bu kritik bir durum: tick gelmediği sürece bot yeni grid/emir kararı veremez, fiyat fırsatlarını kaçırabilir."
                ],
                steps: [
                    "Önce 'Yeniden tara' de; tek seferlik bir gecikmeyse tazeleme sonrası temizlenebilir.",
                    "Binance bağlantısını kontrol et: API anahtarı geçerli mi, sunucu IP'si beyaz listede mi, sistem saati doğru mu?",
                    "Engine worker'ın ayakta olduğunu doğrula (sunucuda ./start.command çalışıyor olmalı).",
                    "Bot Logları'ndaki son kritik satırı oku; kök neden çoğunlukla orada yazılıdır.",
                    "Kısa sürede düzelmezse botu durdurup yeniden başlat; sorun sürerse yönetim ekibiyle iletişime geç."
                ],
                actions: ["refresh", "apiKeys", "contact"]
            }),
            NO_TICK_YET: e({
                label: "Henüz ilk tick yok", level: "warn", theme: "data",
                continues: true, needsAdmin: false,
                what: [
                    "{symbol} botu başlatıldı ama henüz ilk tick kaydedilmedi. Motor ısınıyor olabilir.",
                    "Bot yeni ayağa kalktı; ilk tick/ilk alım tamamlanana kadar bu uyarı normal olabilir."
                ],
                why: [
                    "Worker başlatma komutu yeni işlendi ve ilk döngü henüz tamamlanmadı.",
                    "İlk base alımı bakiye/limit beklemesinde olabilir; ilk tick ona bağlı gecikebilir."
                ],
                impact: [
                    "Genellikle geçici: ilk tick düştüğünde uyarı kendiliğinden kapanır."
                ],
                steps: [
                    "1-2 dakika bekle; ilk tick düşünce uyarı temizlenir.",
                    "Worker'ın çalıştığını doğrula; başlatma komutu işlendi mi kontrol et.",
                    "Birkaç dakika geçtiği halde tick gelmiyorsa botu durdurup yeniden başlat."
                ],
                actions: ["refresh"]
            }),
            PRICE_STALE_OR_MISSING: e({
                label: "Fiyat verisi yok / bayat", level: "warn", theme: "data",
                continues: true, needsAdmin: false,
                what: [
                    "Bu tick'te {symbol} için güncel fiyat okunamadı; emir gönderilmedi ve döngü bekleyerek devam etti.",
                    "Piyasa fiyatı bir süredir tazelenmiyor; bot emir atmak yerine güvenli tarafta bekledi."
                ],
                why: [
                    "Market data WebSocket bağlantısı geçici koptu ya da gecikti.",
                    "Sembol Binance'te kısıtlanmış/duraklatılmış olabilir veya veri kaynağı anlık boş döndü."
                ],
                impact: [
                    "Bot bilinçli olarak emir atmıyor; bayat fiyatla işlem yapmaktansa beklemek doğru davranıştır."
                ],
                steps: [
                    "Market data / worker WS bağlantısını kontrol et; çoğu zaman akış kendiliğinden döner.",
                    "Sembolün Binance'te aktif işlem gördüğünden emin ol.",
                    "Uyarı sürüyorsa botu yeniden başlatmak veri aboneliğini tazeler."
                ],
                actions: ["refresh", "reset"]
            }),
            FIRST_BUY_STUCK: e({
                label: "İlk alım bekleniyor", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "{symbol} botu çalışıyor ama ilk base alımı henüz gerçekleşmedi; bir bakiye/limit engeli olabilir.",
                    "Bot tick atıyor fakat başlangıç pozisyonunu (ilk alım) kuramadı."
                ],
                why: [
                    "Serbest {quote} bakiyesi bot bütçesini karşılamıyor olabilir.",
                    "İlk alım tutarı Binance minimumunun (≈10 {quote}) altında kalıyor olabilir.",
                    "Grid/başlangıç dağılım yüzdeleri ilk emri çok küçük yapıyor olabilir."
                ],
                impact: [
                    "Bot al-sat döngüsüne başlayamaz; ilk alım olmadan grid mantığı tam çalışmaz."
                ],
                steps: [
                    "Cüzdandaki serbest {quote} bakiyesini ve bot bütçesini (initial_capital) karşılaştır.",
                    "Bot Logları'nda MIN_NOTIONAL veya yetersiz bakiye uyarısı var mı bak.",
                    "Başlangıç dağılımını ve bütçeyi, ilk alım ≈10 {quote} üzerinde olacak şekilde ayarla.",
                    "Düzeltince Parametreler'den güncelle; bot bir sonraki uygun tick'te ilk alımı dener."
                ],
                actions: ["openParams", "wallet"]
            }),
            WALLET_SNAPSHOT_STALE: e({
                label: "Cüzdan verisi güncel değil", level: "warn", theme: "wallet",
                continues: true, needsAdmin: false,
                what: [
                    "Ekrandaki spot bakiye, son canlı Binance cüzdan yenilemesinden değil, eski bir snapshot'tan (~{ageMin} dk önce) gösteriliyor.",
                    "Bakiye görünürlüğü gecikmiş; rakamlar anlık olmayabilir."
                ],
                why: [
                    "Cüzdan snapshot yenilemesi gecikti; genelde API okuma izni ya da geçici bağlantı kopması kaynaklı.",
                    "Kullanıcı stream'i bir süre kopuksa snapshot tazelenemez."
                ],
                impact: [
                    "Bu uyarı işlem döngüsünü değil yalnızca bakiyenin ne kadar güncel göründüğünü etkiler; bot tick atıyorsa al-sat devam eder."
                ],
                steps: [
                    "Dashboard'da Binance/Anasayfa sekmesinde cüzdan yenilemesini kontrol et.",
                    "API anahtarı, IP beyaz listesi ve Spot okuma iznini doğrula.",
                    "Bot tick atmaya devam ediyorsa işlem etkilenmez; rakamlar yenilenince güncellenir."
                ],
                actions: ["wallet", "refresh"]
            }),

            // ---- Bütçe / emir teması ----
            LOT_SIZE: e({
                label: "Lot / step filtresi (LOT_SIZE)", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "Emir miktarı Binance'in lot adımı (stepSize) / minimum miktar (minQty) kuralına uymadığı için reddedildi (-1013, LOT_SIZE).",
                    "Gönderilmek istenen miktar borsanın izin verdiği adım büyüklüğüne oturmuyor."
                ],
                why: [
                    "Grid base/quote yüzdesi, bu sembol için emri çok küçük ya da yanlış adımda üretiyor.",
                    "Bütçe seviyelere bölününce her emir minQty'nin altına düşüyor olabilir."
                ],
                impact: [
                    "İlgili grid emri geçmiyor; diğer seviyeler çalışmaya devam eder ama o kademe boşta kalır."
                ],
                steps: [
                    "Grid base/quote yüzdesini veya bot bütçesini artırarak emir miktarını minQty üzerine çıkar.",
                    "Sembolün minQty ve stepSize değerine uygun miktar seç (çok küçük kademelerden kaçın).",
                    "Bot Logları'nda hangi seviyenin (Satış/Alım #n) takıldığını gör ve o kademeyi düzelt.",
                    "Düzeltince Parametreler'den uygula; tekrarlayan reddi 'Uyarıları sıfırla' ile temizle."
                ],
                actions: ["openParams", "reset"]
            }),
            MIN_NOTIONAL: e({
                label: "Minimum tutar (MIN_NOTIONAL)", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "Emrin notional değeri (fiyat × miktar) Binance'in minimum işlem tutarının altında kaldığı için reddedildi.",
                    "Emir, borsanın kabul ettiği en küçük işlem büyüklüğünü karşılamıyor."
                ],
                why: [
                    "Bütçe çok sayıda seviyeye bölününce her emir ~10 {quote} eşiğinin altına iniyor.",
                    "Grid/ilk alım yüzdeleri emri minimumun altına çekiyor."
                ],
                impact: [
                    "O emir gönderilemez; bütçeyi seviyeye daha cömert dağıtmak gerekir."
                ],
                steps: [
                    "Grid emir tutarını veya bütçeyi artır; her emir en az ~10 {quote} olacak şekilde planla.",
                    "İlk alım ve grid yüzdelerini gözden geçir; seviye sayısını azaltmak emir başına tutarı büyütür.",
                    "Parametreler'den güncelle ve uyarıları sıfırla."
                ],
                actions: ["openParams", "reset"]
            }),
            MIN_NOTIONAL_AFTER_CAP: e({
                label: "Minimum tutar (cap sonrası)", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "Emir, serbest bakiye sınırına göre küçültüldükten sonra bile minimum işlem tutarının altında kaldı.",
                    "Bakiye yetmediği için emir kırpıldı ve kırpılan tutar minimumun altına düştü."
                ],
                why: [
                    "Serbest {quote} ya da base bakiye, çalışabilir bir emir için yetersiz.",
                    "Grid yüzdesi yüksek ama bakiye onu taşıyamıyor."
                ],
                impact: [
                    "Bakiye artana ya da grid yüzdesi düşene kadar bu kademe emir üretemez."
                ],
                steps: [
                    "Serbest {quote} (veya base) bakiyesini artır.",
                    "Grid yüzdesini düşürüp bütçeyi yükselt; emir, cap sonrası bile minimumun üstünde kalsın.",
                    "Cüzdanı kontrol et, Parametreler'den ayarla."
                ],
                actions: ["wallet", "openParams"]
            }),
            INSUFFICIENT_QUOTE: e({
                label: "Yetersiz {quote}", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "Alım emri için yeterli serbest {quote} (örn. USDT) yok.",
                    "Bot alım yapmak istedi ama hesapta o an yeterli serbest {quote} bulamadı."
                ],
                why: [
                    "Bakiye başka emirlerde/botlarda kilitli olabilir ya da gerçekten azalmış olabilir.",
                    "Alım grid yüzdeleri mevcut bakiyenin üstünde tutar talep ediyor."
                ],
                impact: [
                    "Alım kademeleri geçmez; satış tarafı çalışmaya devam edebilir."
                ],
                steps: [
                    "Cüzdandaki serbest {quote} bakiyesini kontrol et; gerekiyorsa ekle.",
                    "Aynı hesapta başka botlar bakiyeyi kilitliyor mu bak.",
                    "Grid alım yüzdelerini bakiyeye göre düşür ve Parametreler'den uygula."
                ],
                actions: ["wallet", "openParams"]
            }),
            ORDER_FAILED: e({
                label: "Emir gönderilemedi", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "Binance emir isteği reddedildi veya bir ağ hatasıyla karşılaşıldı.",
                    "Emir borsaya iletilemedi; bot bir sonraki uygun tick'te yeniden deneyecek."
                ],
                why: [
                    "Binance tarafından bir filtre/izin hatası (kod), ya da geçici ağ sorunu olabilir.",
                    "API anahtarının Spot işlem izni veya IP beyaz listesi eksik olabilir."
                ],
                impact: [
                    "Tek seferlik reddiler genelde önemsizdir; tekrarlarsa kök nedene bakmak gerekir."
                ],
                steps: [
                    "Bot Logları'nda emir satırındaki Binance kodunu ve mesajını oku (asıl ipucu orada).",
                    "API anahtarı, IP beyaz listesi ve Spot işlem iznini doğrula.",
                    "Sık tekrar ediyorsa bütçe/grid yüzdesini gözden geçir; geçiciyse 'Yeniden tara' yeterli."
                ],
                actions: ["refresh", "apiKeys"]
            }),
            ORDER_TIMEOUT: e({
                label: "Emir zaman aşımı", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "Binance emir yanıtı zaman aşımına uğradı; emir sonucu zamanında dönmedi.",
                    "Emir gönderildi ama yanıt beklenen sürede gelmedi."
                ],
                why: [
                    "Geçici ağ gecikmesi ya da Binance tarafında anlık yoğunluk olabilir."
                ],
                impact: [
                    "Bot birkaç dakika içinde tekrar dener; genelde kendiliğinden düzelir."
                ],
                steps: [
                    "Ağ bağlantısını kontrol et; çoğu zaman tek seferlik gecikmedir.",
                    "Tekrarlıyorsa Binance API durumunu ve sunucu ağını kontrol et.",
                    "Birkaç dakika sonra 'Yeniden tara' ile durumu doğrula."
                ],
                actions: ["refresh"]
            }),
            REPEATED_ORDER_FAIL: e({
                label: "Tekrarlayan emir hatası", level: "warn", theme: "funds",
                continues: true, needsAdmin: false,
                what: [
                    "Son 15 dakikada {failCount} kez Binance emir reddi kaydedildi; bu artık tek seferlik bir sorun değil.",
                    "Emirler ısrarla geçmiyor — kalıcı bir filtre/bakiye/izin sorunu var demektir."
                ],
                why: [
                    "Çoğunlukla LOT_SIZE / MIN_NOTIONAL (emir çok küçük) ya da yetersiz bakiye tekrarı.",
                    "API izni/IP beyaz listesi eksikse her emir aynı şekilde reddedilir."
                ],
                impact: [
                    "Emirler sürekli geri döndüğü için bot etkili işlem yapamıyor; kök nedeni çözmek şart."
                ],
                steps: [
                    "Bot Logları'nda hangi kodun tekrarlandığını belirle (LOT_SIZE / MIN_NOTIONAL / -2010 / bakiye).",
                    "En sık görülen koda göre düzelt: emri büyüt (bütçe/grid) veya bakiye/izin sorununu gider.",
                    "Düzelttikten sonra 'Uyarıları sıfırla' ile tekrar sayacını temizle ve 'Yeniden tara' de.",
                    "Worker yeni başlatıldıysa eski reddiler kalmış olabilir; reset bunları temizler."
                ],
                actions: ["openParams", "reset"]
            }),
            INSUFFICIENT_BALANCE: e({
                label: "Yetersiz bakiye — bot durduruldu", level: "critical", theme: "funds",
                continues: false, needsAdmin: false,
                what: [
                    "Emir gönderilemedi çünkü Binance hesabında yeterli serbest bakiye yok ve bot güvenlik için duraklatıldı.",
                    "Bakiye, botun bütçesini karşılamaya yetmediği için bot durduruldu; manuel yeniden başlatma gerekiyor."
                ],
                why: [
                    "Hesaptaki serbest {quote}/base bakiye, bot bütçesinin (initial_capital) altına düştü.",
                    "Bakiye başka işlemlerde kullanıldı ya da çekildi."
                ],
                impact: [
                    "Bot şu an işlem yapmıyor; bakiye eklenip yeniden başlatılana kadar bekler. Mevcut varlığın yerinde durur."
                ],
                steps: [
                    "Binance cüzdanına bot bütçesini karşılayacak kadar {quote} ekle.",
                    "Bütçeyi düşürmek istersen Parametreler'den initial_capital değerini güncelle.",
                    "Hazır olunca botu yeniden başlat; sağlıklı bakiyeyle döngü kaldığı yerden devam eder.",
                    "Düzelttikten sonra 'Yeniden tara' ile durumu doğrula."
                ],
                actions: ["wallet", "openParams", "refresh"]
            }),

            // ---- Bağlantı teması ----
            BINANCE_UNREACHABLE: e({
                label: "Binance'e ulaşılamıyor", level: "critical", theme: "connectivity",
                continues: false, needsAdmin: true,
                what: [
                    "Hesap bakiyesi veya piyasa verisi Binance API üzerinden okunamıyor; bot Binance'le konuşamıyor.",
                    "Binance erişimi kopuk: bot ne bakiye ne de fiyat tarafını güvenle okuyabiliyor."
                ],
                why: [
                    "Sunucunun internet erişimi ya da Binance API tarafında geçici bir kesinti olabilir.",
                    "Sunucu IP'si Binance API anahtarının beyaz listesinde olmayabilir.",
                    "API anahtarı geçersiz/iptal edilmiş ya da Spot izni kapalı olabilir."
                ],
                impact: [
                    "Erişim yokken bot emir atamaz ve bakiye okuyamaz; bu yüzden kritik seviyede."
                ],
                steps: [
                    "İnternet/sunucu erişimini kontrol et; geçici kesintiyse birkaç dakikada düzelebilir.",
                    "Binance API anahtarının geçerli ve Spot izninin açık olduğunu doğrula.",
                    "Sunucu IP'sinin API anahtarı beyaz listesinde olduğundan emin ol (beyaz liste sıkça atlanır).",
                    "Birkaç dakika bekleyip 'Yeniden tara' de; düzelince bot otomatik devam eder.",
                    "Sorun sürerse sunucu IP'si gibi yönetim tarafı detaylar gerekebilir — aşağıdan destek ekibine yaz."
                ],
                actions: ["refresh", "apiKeys", "contact"]
            }),
            API_UNAUTHORIZED: e({
                label: "API anahtarı yetkisiz (401 / -2015)", level: "critical", theme: "connectivity",
                continues: false, needsAdmin: true,
                what: [
                    "Binance, API anahtarını reddetti (401 / -2015): anahtar geçersiz, izinsiz ya da IP beyaz listesi dışında.",
                    "Kimlik doğrulama başarısız; Binance bu anahtarla isteği kabul etmiyor."
                ],
                why: [
                    "API anahtarı/secret yanlış, süresi dolmuş veya silinmiş olabilir.",
                    "Sunucu IP'si anahtarın beyaz listesinde değildir (en sık sebep).",
                    "Anahtarda Spot işlem izni etkin değildir."
                ],
                impact: [
                    "Yetki olmadan bot hiçbir emir/okuma yapamaz; bağlantı yetkiyle düzelmeli."
                ],
                steps: [
                    "Binance hesabında API anahtarı ve secret'ın doğru girildiğini kontrol et (Ayarlar).",
                    "Anahtarda 'Spot & Margin Trading' okuma/işlem izninin açık olduğunu doğrula.",
                    "Sunucunun çıkış IP'sini API anahtarının IP beyaz listesine ekle.",
                    "Düzeltince 'Yeniden tara' de; erişim dönerse durmuş botlar otomatik devam eder.",
                    "Sunucu IP'sini bilmiyorsan aşağıdaki sohbetten yönetim ekibine sor; sana doğru IP'yi iletelim."
                ],
                actions: ["apiKeys", "refresh", "contact"]
            }),
            ACCOUNT_KEYS_MISSING: e({
                label: "API anahtarı tanımlı değil", level: "critical", theme: "connectivity",
                continues: false, needsAdmin: false,
                what: [
                    "Bu hesapta Binance API anahtarı tanımlı değil; bot borsaya bağlanamıyor.",
                    "Sistem, bu hesap için kayıtlı bir API anahtarı bulamadı."
                ],
                why: [
                    "API anahtarı hiç eklenmemiş ya da hesaptan kaldırılmış olabilir."
                ],
                impact: [
                    "Anahtar olmadan bot işlem yapamaz; önce anahtar tanımlanmalı."
                ],
                steps: [
                    "Ayarlar'dan Binance API anahtarı ve secret'ı ekle.",
                    "Anahtarda Spot okuma/işlem iznini etkinleştir.",
                    "Sunucu IP'sini beyaz listeye ekle, ardından 'Yeniden tara' de."
                ],
                actions: ["apiKeys", "refresh"]
            }),
            ACCOUNT_KEYS_EMPTY: e({
                label: "API anahtarı boş", level: "critical", theme: "connectivity",
                continues: false, needsAdmin: false,
                what: [
                    "Kayıtlı API anahtarı alanı boş görünüyor; geçerli bir anahtar okunamadı.",
                    "Anahtar kaydı var ama içeriği boş — kimlik bilgisi eksik."
                ],
                why: [
                    "Anahtar yarım kaydedilmiş ya da bir güncelleme sırasında boşalmış olabilir."
                ],
                impact: [
                    "Geçerli anahtar girilene kadar bot bağlanamaz."
                ],
                steps: [
                    "Ayarlar'dan API anahtarı ve secret'ı yeniden, eksiksiz gir.",
                    "Kaydettikten sonra Spot izni ve IP beyaz listesini doğrula.",
                    "'Yeniden tara' ile bağlantıyı test et."
                ],
                actions: ["apiKeys", "refresh"]
            }),
            ACCOUNT_KEYS_DECRYPT_FAIL: e({
                label: "API anahtarı çözülemedi", level: "critical", theme: "connectivity",
                continues: false, needsAdmin: true,
                what: [
                    "Kayıtlı API anahtarı sunucuda çözülemedi (şifre çözme hatası); anahtar okunamıyor.",
                    "Anahtar saklı ama sistem onu güvenli şekilde çözemedi — sunucu tarafı bir sorun var."
                ],
                why: [
                    "Sunucudaki şifreleme anahtarı değişmiş ya da kayıt bozulmuş olabilir.",
                    "Bu genellikle kullanıcı tarafı değil, yönetim/sunucu tarafı bir konudur."
                ],
                impact: [
                    "Anahtar çözülemediği için bot bağlanamaz; yeniden anahtar girişi veya yönetim müdahalesi gerekir."
                ],
                steps: [
                    "Önce API anahtarını Ayarlar'dan silip yeniden eklemeyi dene.",
                    "Sorun sürerse bu sunucu tarafı bir konudur; aşağıdaki sohbetten yönetim ekibine bildir.",
                    "Yönetim kontrol ederken botu başlatmayı bekletmen daha güvenli."
                ],
                actions: ["apiKeys", "contact"]
            }),
            CLOCK_DRIFT: e({
                label: "Sunucu saati kaymış (-1021)", level: "critical", theme: "connectivity",
                continues: false, needsAdmin: true,
                what: [
                    "Sunucu saati Binance ile uyuşmuyor (-1021); zaman damgası penceresi dışında kaldığı için istekler reddediliyor.",
                    "Saat farkı Binance'in kabul ettiği toleransı aştı, bu yüzden imzalı isteler geçmiyor."
                ],
                why: [
                    "Sunucu sistem saati senkron değil (NTP gecikmesi/sapması).",
                    "Bu bir yapılandırma/sunucu konusudur; kullanıcı API anahtarıyla ilgili değildir."
                ],
                impact: [
                    "Saat düzelene kadar imzalı istekler reddedilir; bot emir veremez."
                ],
                steps: [
                    "Bu konu sunucu zaman senkronizasyonu gerektirir (NTP).",
                    "Kullanıcı tarafında yapılacak bir şey yoksa aşağıdaki sohbetten yönetim ekibine bildir.",
                    "Saat düzeltilince 'Yeniden tara' de; erişim otomatik döner."
                ],
                actions: ["contact", "refresh"]
            }),
            BINANCE_RATE_LIMIT: e({
                label: "Binance oran limiti", level: "warn", theme: "connectivity",
                continues: true, needsAdmin: false,
                what: [
                    "Binance API oran limitine takıldı; istekler geçici olarak kısıtlanıyor.",
                    "Çok sık istek nedeniyle Binance kısa süreli bir yavaşlatma uyguluyor."
                ],
                why: [
                    "Aynı hesapta/sunucuda yoğun istek trafiği oluşmuş olabilir.",
                    "Geçici bir tepe yük; genelde kısa sürede normale döner."
                ],
                impact: [
                    "Emirler gecikebilir ama bot durmaz; limit penceresi geçince hız normale döner."
                ],
                steps: [
                    "Birkaç dakika bekle; oran limiti kendiliğinden açılır.",
                    "Aynı hesapta çok sayıda bot varsa yükü gözden geçirmek tekrarını azaltır.",
                    "Sık yaşanıyorsa 'Yeniden tara' ile durumu izle."
                ],
                actions: ["refresh"]
            }),
            CONNECTIVITY_DEGRADED: e({
                label: "Bağlantı zayıf (backoff)", level: "warn", theme: "connectivity",
                continues: true, needsAdmin: false,
                what: [
                    "Bot geçici 'backoff' modunda; bağlantı zayıfladığı için emirler sınırlı/gecikmeli olabilir.",
                    "Erişim dalgalandığı için bot temkinli moda geçti ve hızını düşürdü."
                ],
                why: [
                    "Binance API'ye erişimde aralıklı kopmalar/gecikmeler yaşanıyor.",
                    "Ağ tarafında geçici dalgalanma olabilir."
                ],
                impact: [
                    "Bot çalışmaya devam eder; bağlantı düzelince otomatik tam hıza döner."
                ],
                steps: [
                    "Binance API ve ağ erişimini kontrol et.",
                    "Genelde kendiliğinden düzelir; düzelince backoff kalkar.",
                    "Uzun sürerse 'Yeniden tara' ile bağlantı durumunu doğrula."
                ],
                actions: ["refresh"]
            }),
            SERVER_UNREACHABLE: e({
                label: "Sunucuya ulaşılamıyor", level: "critical", theme: "connectivity",
                continues: false, needsAdmin: true,
                what: [
                    "Uygulama sunucusuna şu an ulaşılamıyor; bu sayfa canlı veri çekemiyor.",
                    "Tarayıcı, kendi sunucumuza bağlanamadı — bu bir Binance değil, altyapı erişim sorunu."
                ],
                why: [
                    "Sunucu yeniden başlatılıyor olabilir ya da ağ/erişim tarafında geçici bir kesinti var.",
                    "Kendi internet bağlantın da kopmuş olabilir."
                ],
                impact: [
                    "Sunucu dönene kadar canlı durum güncellenmez; bottan bağımsız bir erişim konusudur."
                ],
                steps: [
                    "Önce kendi internet bağlantını kontrol et, sayfayı yenile.",
                    "Birkaç dakika bekle; sunucu yeniden başlıyorsa kısa sürede döner.",
                    "Sürerse aşağıdaki sohbet üzerinden (mümkünse başka bir cihazdan) yönetim ekibine bildir."
                ],
                actions: ["refresh", "contact"]
            }),

            // ---- Çalışma zamanı / döngü teması ----
            LOOP_TASK_MISSING: e({
                label: "Bot döngüsü yok — kurtarma bekleniyor", level: "critical", theme: "runtime",
                continues: true, needsAdmin: true,
                what: [
                    "Bot veritabanında çalışıyor görünüyor ama engine içinde aktif döngü bulunamadı; worker otomatik yeniden başlatmayı deniyor.",
                    "Kayıt 'çalışıyor' diyor fakat fiili döngü düşmüş; sistem onu yeniden ayağa kaldırmaya çalışıyor."
                ],
                why: [
                    "Worker süreci yeniden başlamış ve döngüyü henüz tekrar açmamış olabilir.",
                    "Döngü beklenmedik şekilde sonlanmış; otomatik kurtarma sırada."
                ],
                impact: [
                    "Kısa süreli olması beklenir: birkaç saniye içinde BOT_LOOP_AUTO_RESTART düşüp döngü geri gelmeli."
                ],
                steps: [
                    "10-60 saniye bekle; loglarda BOT_LOOP_AUTO_RESTART satırı gelmeli ve tick yeniden başlamalı.",
                    "Tick döndüyse 'Uyarıları sıfırla' ile kurtarma gürültüsünü temizle.",
                    "Uyarı uzun süre kalkmıyorsa worker süreci kontrol gerektirir — aşağıdan yönetim ekibine yaz."
                ],
                actions: ["refresh", "reset", "contact"]
            }),
            BOT_LOOP_AUTO_RESTART: e({
                label: "Bot döngüsü yeniden başlatılıyor", level: "critical", theme: "runtime",
                continues: true, needsAdmin: false,
                what: [
                    "Engine döngüsü beklenmedik şekilde sonlandı; veritabanında çalışıyor göründüğü için worker döngüyü otomatik yeniden açıyor.",
                    "Döngü bir an düştü ama sistem onu kendisi yeniden başlatıyor — kurtarma çalışıyor."
                ],
                why: [
                    "Sunucu yeniden başlatılmış olabilir (deploy/restart) ya da döngü tek seferlik bir hatayla çıkmış olabilir.",
                    "Genelde geçici bir olaydır ve otomatik toparlanır."
                ],
                impact: [
                    "Bot çalışmaya devam eder; kısa kesinti sonrası tick ve loglar geri gelir."
                ],
                steps: [
                    "Birkaç saniye bekle; tick ve loglar devam etmeli.",
                    "Devam ettiyse 'Uyarıları sıfırla' ile bu kurtarma kaydını temizleyebilirsin.",
                    "Çok sık tekrarlıyorsa worker ve Binance bağlantısını kontrol et."
                ],
                actions: ["refresh", "reset"]
            }),
            BOT_CONTINUES_ON_ERROR: e({
                label: "Tick hatası — bot çalışıyor", level: "warn", theme: "runtime",
                continues: true, needsAdmin: false,
                what: [
                    "Bir tick sırasında toparlanabilir bir hata oluştu ({errorCode}); bot durdurulmadı, döngü çalışmaya devam ediyor.",
                    "Tek bir tick hata verdi ama bot bunu yutup devam etti — döngü kesilmedi."
                ],
                why: [
                    "Anlık bir veri/işlem istisnası olabilir; bir sonraki tick'te genelde kapanır.",
                    "Sürekli tekrarlıyorsa altta bütçe, API ya da worker kaynağı gibi bir kök neden olabilir."
                ],
                impact: [
                    "Tasarım gereği bot tek tick hatasında durmaz; sürekli tekrar etmediği sürece önemsizdir."
                ],
                steps: [
                    "Bot Logları'nda hata detayına bak ({errorCode} satırı).",
                    "Tek seferlikse 'Uyarıları sıfırla' ile temizle ve izlemeye devam et.",
                    "Sürekli tekrarlıyorsa grid bütçesi, API erişimi veya worker kaynağını kontrol et."
                ],
                actions: ["reset", "refresh"]
            }),
            STATE_ERROR: e({
                label: "Bot hata durumunda", level: "critical", theme: "runtime",
                continues: false, needsAdmin: true,
                what: [
                    "Son tick sırasında kritik bir hata kodu kaydedildi ({errorCode}); bot bu durumu çözülmemiş olarak işaretliyor.",
                    "State'te kritik bir hata var; bot güvenli tarafta kalmak için bunu öne çıkarıyor."
                ],
                why: [
                    "Genelde API yetkisi, bakiye ya da güvenli durdurma gibi kritik bir kök neden vardır ({errorCode}).",
                    "Kod ne ise çözüm de ona göre değişir; log satırı asıl ipucudur."
                ],
                impact: [
                    "Kritik hata çözülene kadar bot beklemede kalabilir; kök nedeni gidermek gerekir."
                ],
                steps: [
                    "Bot Logları'ndaki 'Hata' satırını oku; {errorCode} kodunun ne dediğine bak.",
                    "API anahtarı/izin veya bakiye kaynaklıysa ilgili ayarı düzelt.",
                    "Düzelttikten sonra 'Uyarıları sıfırla' ve ardından botu yeniden başlatmayı dene.",
                    "Kod tanıdık değilse ya da sürerse aşağıdan yönetim ekibine danış."
                ],
                actions: ["refresh", "apiKeys", "reset", "contact"]
            }),
            STATE_ERROR_WARN: e({
                label: "Uyarı kodu aktif", level: "warn", theme: "runtime",
                continues: true, needsAdmin: false,
                what: [
                    "Bot state'inde çözülmemiş bir uyarı/hata kodu var ({errorCode}); kritik değil ama açık duruyor.",
                    "Aktif bir uyarı kodu var; izlenmesi gerekir ama bot çalışmaya devam ediyor."
                ],
                why: [
                    "Geçici bir ağ/limit ya da emir uyarısı henüz temizlenmemiş olabilir.",
                    "Çoğu zaman kendiliğinden düzelir; düzelmezse log detayı yön gösterir."
                ],
                impact: [
                    "Genelde toparlanabilir; bot çalışmaya devam eder."
                ],
                steps: [
                    "Son log kayıtlarını incele; {errorCode} ne diyor bak.",
                    "Geçici görünüyorsa bir süre bekle, sonra 'Yeniden tara' de.",
                    "Düzeldiyse 'Uyarıları sıfırla' ile kaydı temizle."
                ],
                actions: ["refresh", "reset"]
            }),

            // ---- Likidite / piyasa teması ----
            REPEATED_LOCK_BUSY: e({
                label: "Tekrarlayan kilit meşgul", level: "warn", theme: "liquidity",
                continues: true, needsAdmin: false,
                what: [
                    "Son 15 dakikada sembol kilidi meşgul olduğu için birden fazla tick atlandı.",
                    "Bot, aynı sembol üzerinde başka bir işlemin kilidini beklerken birkaç tick'i geçti."
                ],
                why: [
                    "Aynı hesapta aynı sembolde başka bir bot/işlem kilidi tutuyor olabilir.",
                    "Eşzamanlı erişim çakışması kısa süreli kilit beklemesi yaratır."
                ],
                impact: [
                    "Atlanan tickler döngüyü yavaşlatır ama bot durmaz; kilit serbest kalınca normalleşir."
                ],
                steps: [
                    "Aynı sembolde çalışan başka bot var mı kontrol et; gerekiyorsa birini durdur.",
                    "Çakışma sürüyorsa kilidi tutan işlemi serbest bırak.",
                    "Düzeldikten sonra 'Uyarıları sıfırla' ile sayacı temizle."
                ],
                actions: ["reset", "refresh"]
            }),
            REPEATED_SLIPPAGE: e({
                label: "Tekrarlayan kayma uyarısı", level: "warn", theme: "liquidity",
                continues: true, needsAdmin: false,
                what: [
                    "Son 15 dakikada birden fazla yüksek kayma (slippage) kaydedildi; gerçekleşen fiyat hedeften belirgin saptı.",
                    "Emirler beklenenden farklı fiyatlardan doluyor — piyasa hareketli ya da ince."
                ],
                why: [
                    "Yüksek volatilite ya da düşük likidite, emir anında fiyatı kaydırıyor.",
                    "Grid aralığı, mevcut oynaklığa göre dar kalmış olabilir."
                ],
                impact: [
                    "Kayma kâr/zarar dengesini etkileyebilir ama bot çalışmaya devam eder."
                ],
                steps: [
                    "Sembolün o anki volatilitesini/likiditesini değerlendir.",
                    "Grid aralığını biraz açmayı veya emir büyüklüğünü gözden geçirmeyi düşün (Parametreler).",
                    "Geçici dalgalanmaysa düzeldiğinde 'Uyarıları sıfırla' de."
                ],
                actions: ["openParams", "reset"]
            })
        };

        // Teknik istisna kodlarını bilgi tabanındaki temsilci koda eşler.
        var aliases = {
            BOT_LOOP_TOPLEVEL_EXCEPTION: "BOT_CONTINUES_ON_ERROR",
            BOT_LOOP_TRDCA_EXCEPTION: "BOT_CONTINUES_ON_ERROR",
            BOT_TICK_EXCEPTION: "BOT_CONTINUES_ON_ERROR",
            RUN_ACTION_EXCEPTION: "BOT_CONTINUES_ON_ERROR",
            CONNECTIVITY_RECOVERED: "CONNECTIVITY_DEGRADED",
            CONNECTIVITY_PAUSED: "CONNECTIVITY_DEGRADED",
            SAFE_STOP: "STATE_ERROR",
            WORKER_ONLY_OPERATION: "STATE_ERROR"
        };

        var actionLabels = {
            refresh: { label: "Yeniden tara", title: "Sağlık taramasını tekrarla", kind: "ghost" },
            reset: { label: "Uyarıları sıfırla", title: "Çözülen uyarı/log gürültüsünü temizle", kind: "ghost" },
            openParams: { label: "Parametreleri aç", title: "Bütçe/grid ayarlarını düzenle", kind: "accent" },
            wallet: { label: "Cüzdana git", title: "Binance bakiyesini kontrol et", kind: "ghost" },
            apiKeys: { label: "API ayarları", title: "API anahtarı ve izinleri", kind: "ghost" },
            contact: { label: "Yönetimle sohbet", title: "Destek ekibine yaz", kind: "accent" },
            exportLog: { label: "Logları indir", title: "Tüm log kayıtlarını dışa aktar", kind: "ghost" }
        };

        return {
            identity: {
                id: "ai-error-assistant",
                name: "Hata Asistanı",
                family: "ayserose AI",
                purpose: "Botun canlı sağlık ve bağlantı durumunu okur; sorun varsa nedenini ve çözümünü adım adım anlatır."
            },
            button: {
                className: "bot-error-assistant-btn",
                label: "Hata Asistanı",
                compactLabel: "Tanı",
                title: "Bot için canlı hata taraması ve çözüm önerisi",
                ariaLabel: "Bot hata asistanını aç",
                healthyLabel: "Sağlık Asistanı"
            },
            modal: {
                title: "Bot Hata Asistanı",
                healthyTitle: "Bot Sağlık Durumu",
                label: "Hata asistanı",
                closeLabel: "Kapat",
                scanStatus: "Bot taranıyor",
                checklistTitle: "Kontrol ettiklerim",
                stepsTitle: "Çözüm adımları",
                whyTitle: "Olası neden",
                impactTitle: "Bunun anlamı",
                connectedTitle: "İlişkili bulgular",
                contactTitle: "Yönetim desteği gerekebilir"
            },
            timing: {
                textMs: 8,
                introPauseMs: 80,
                linePauseMs: 95,
                chipStaggerMs: 35,
                dotPauseMul: 1.35
            },
            themes: themes,
            persona: persona,
            codeBook: codeBook,
            aliases: aliases,
            actionLabels: actionLabels
        };
    }

    var PARAM_ASSISTANT_SCENARIO_POOL = buildParamAssistantScenarioPool();
    var PARAM_ASSISTANT_RATIONALE_POOL = buildParamAssistantRationalePool();
    var ERROR_ASSISTANT = buildErrorAssistant();

    function stableIndex(seed, n, salt) {
        var s = String(seed || "") + "|" + String(salt || 0);
        var h = 2166136261;
        for (var i = 0; i < s.length; i++) {
            h ^= s.charCodeAt(i);
            h = Math.imul(h, 16777619);
        }
        return Math.abs(h >>> 0) % Math.max(1, n || 1);
    }

    var spec = {
        version: "2026.06.20-err1",
        identity: {
            id: "ai-assistant",
            name: "AI Asistan",
            family: "ayserose AI",
            purpose: "Piyasa verisini, geçmiş pencereleri ve bot parametrelerini tek bir kontrollü öneri akışında birleştirir."
        },
        design: {
            accent: "#f0b90b",
            success: "#0ecb81",
            panelTint: "#1e2329",
            buttonBg: "#2b3139",
            buttonMinHeight: "36px",
            buttonRadius: "8px",
            modalRadius: "12px",
            chipRadius: "999px"
        },
        button: {
            className: "dm-param-assistant-btn",
            wrapClassName: "dm-param-assistant-btn-wrap",
            label: "Parametre Asistanı",
            compactLabel: "AI",
            title: "Parite verilerine göre parametre önerisi",
            ariaLabel: "Parametre asistanını aç"
        },
        modal: {
            title: "Parametre Asistanı",
            label: "Parametre Asistanı",
            initialStatus: "Parite ve bütçe hazırlanıyor…",
            closeLabel: "Kapat"
        },
        timing: {
            textMs: 18,
            inputMs: 70,
            fieldPauseMs: 230,
            chipBaseDelayMs: 70,
            introPauseMs: 180
        },
        cache: {
            marketHistoryTtlMs: 10 * 60 * 1000,
            marketHistoryTimeoutMs: 9000
        },
        api: {
            tiers: "/api/param-assistant/tiers",
            optimize: "/api/param-assistant/optimize",
            calculate: "/api/param-assistant/calculate",
            active: "/api/param-assistant/active"
        },
        progress: {
            prefix: "DPS",
            defaultMessage: "Piyasa analizi yapılıyor",
            scoreLabel: "ParamScore",
            percentSeparator: "·",
            etaPrefix: "tahmini ~"
        },
        copy: {
            fallbackUserName: "dostum",
            dataPartial: "Bazı geçmiş pencerelerde veri sınırlı geldi; öneriyi güven skoruna indirim vererek ürettim.",
            dataHealthy: "Veri akışı yeterli; öneriyi çok pencereli hesapla üretiyorum.",
            localFallbackStatus: "Geçmiş veri gecikti; hızlı öneri hazırlanıyor",
            backendFallbackSuffix: "hızlı öneriye geçiliyor"
        },
        paramAssistant: {
            resultSchemaVersion: "3.4",
            scenarioPool: PARAM_ASSISTANT_SCENARIO_POOL,
            scenarioPoolSize: PARAM_ASSISTANT_SCENARIO_POOL.length,
            rationalePool: PARAM_ASSISTANT_RATIONALE_POOL,
            rationalePoolSize: Object.keys(PARAM_ASSISTANT_RATIONALE_POOL).reduce(function (sum, key) {
                return sum + (PARAM_ASSISTANT_RATIONALE_POOL[key] || []).length;
            }, 0),
            greetingPool: PARAM_ASSISTANT_SCENARIO_POOL.concat([
                "Selam {name}, ben parametre asistanın. {symbol} için canlı fiyatı, kısa vade mumlarını ve uzun dönem geçmişini birlikte okuyorum.",
                "Merhaba {name}, {symbol} ekranını açtım; geçmiş pencereleri ve canlı momentumu aynı masada tartıyorum.",
                "{name}, {symbol} için parametre masasına geçtim; fiyat, hacim, volatilite ve trend sinyalini birlikte okuyorum.",
                "Selam {name}, {base} tarafında acele etmiyorum; önce {symbol} verisini geniş zaman pencereleriyle ölçüyorum.",
                "Merhaba {name}, {symbol} için asistan devrede; kısa vadeyi uzun geçmişle karşılaştırıp temiz bir set çıkarıyorum.",
                "{name}, {symbol} analizini başlatıyorum; grid mesafesini hisle değil, bant ve risk matematiğiyle kuracağım.",
                "Selam {name}, {symbol} için canlı veriyi aldım; şimdi 1 ay, 3 ay, 1 yıl ve 4 yıl izini aynı anda okuyorum.",
                "Merhaba {name}, {symbol} bot ayarı için önce piyasanın ritmini dinliyorum; sonra inputlara geçeceğim.",
                "{name}, {symbol} üzerinde çalışıyorum; amacım gürültüye fazla yaklaşmadan çalışabilir bir grid seti önermek.",
                "Selam {name}, {symbol} için fiyat davranışını, drawdown geçmişini ve volatilite yoğunluğunu birlikte hesaplıyorum.",
                "Merhaba {name}, {symbol} parametreleri için veri masası hazır; canlı fiyatı eski döngülerle kıyaslıyorum.",
                "{name}, {base} için aceleci bir öneri vermeyeceğim; önce {symbol} geçmişini çok pencereli okuyorum.",
                "Selam {name}, {symbol} tarafında asistan modundayım; trend, bant ve minimum emir gerçekliğini birlikte dengeliyorum.",
                "Merhaba {name}, {symbol} için öneri motorunu çalıştırdım; her inputu tek tek dayanaklı seçiyorum.",
                "{name}, {symbol} verisini açtım; kâr odaklı ama ölçülü bir parametre iskeleti kuruyorum.",
                "Selam {name}, {symbol} için kısa vade nabzı ve uzun vade karakteri aynı ekranda birleşiyor.",
                "Merhaba {name}, {symbol} üzerinde grid için doğru mesafeyi arıyorum; bant, ATR ve rejim sinyali karar verecek.",
                "{name}, {symbol} hesaplamasına başladım; önce piyasa yapısını, sonra bütçe taşıma kapasitesini okuyorum.",
                "Selam {name}, {base} için parametre önerisini hazırlıyorum; {quote} bacağını da boşta bırakmayacağım.",
                "Merhaba {name}, {symbol} için veri geliyor; öneri, tek bir fiyat hareketine değil çoklu pencereye dayanacak.",
                "{name}, {symbol} botu için analiz masası açıldı; volatilite, trend ve risk aynı terazide.",
                "Selam {name}, {symbol} için canlı fiyatı gördüm; şimdi geçmiş bantların nereye izin verdiğini hesaplıyorum.",
                "Merhaba {name}, {symbol} tarafında asistan not alıyor; aşırı sıkışık veya fazla gevşek grid istemiyoruz.",
                "{name}, {symbol} için başlıyorum; hedefim emirlerin çalışabileceği, gürültüye de yem olmayacak bir set.",
                "Selam {name}, {base} hareketini {quote} tarafıyla birlikte okuyorum; öneriyi iki bacak dengesiyle kuracağım.",
                "Merhaba {name}, {symbol} için piyasa hafızasını tarıyorum; son gün değil, uzun karakter de hesaba giriyor.",
                "{name}, {symbol} analizinde ilk iş veri kalitesini ölçmek; sonra parametreleri güven skoruyla bağlayacağım.",
                "Selam {name}, {symbol} için 24 saatlik bant tek başına yetmez; uzun dönem izini de denkleme alıyorum.",
                "Merhaba {name}, {symbol} bot ayarında kâr ihtimalini artıracak mesafeyi matematikle seçeceğim.",
                "{name}, {symbol} için strateji terazisi açıldı; volatilite kullanılabilir mi, trend baskısı ne kadar, bakıyorum.",
                "Selam {name}, {symbol} için hesap başlıyor; grid, trailing ve dağılım aynı rejim kararından beslenecek.",
                "Merhaba {name}, {symbol} üzerinde geniş pencere analizi yapıyorum; öneri aceleci değil, kontrollü olacak."
            ])
        },
        formatTemplate: function (template, values) {
            var data = values || {};
            var out = String(template || "").replace(/\{([a-zA-Z0-9_]+)\}/g, function (_, key) {
                var v = data[key];
                if (v == null || v === "") return "";
                return String(v);
            });
            out = out.replace(/\s+,/g, ",").replace(/,\s*,/g, ",").replace(/,\s*\./g, ".");
            out = out.replace(/\(\s*,/g, "(").replace(/,\s*\)/g, ")");
            out = out.replace(/\s{2,}/g, " ").replace(/ ,/g, ",").trim();
            return out;
        },
        randomIndex: function (max) {
            var size = Math.max(1, Number(max) || 1);
            try {
                if (window.crypto && window.crypto.getRandomValues) {
                    var arr = new Uint32Array(1);
                    window.crypto.getRandomValues(arr);
                    return arr[0] % size;
                }
            } catch (e) {}
            return Math.floor(Math.random() * size);
        },
        greeting: function (values) {
            var pool = spec.paramAssistant.greetingPool || [];
            var data = values || {};
            function ok(key) { return data[key] != null && data[key] !== ""; }
            var filtered = pool.filter(function (tmpl) {
                if (!ok("basePct") && (/\{basePct\}/.test(tmpl) || /\{quotePct\}/.test(tmpl))) return false;
                if (!ok("price") && /\{price\}/.test(tmpl)) return false;
                if (!ok("change") && /\{change\}/.test(tmpl)) return false;
                if (!ok("coverage") && /\{coverage\}/.test(tmpl)) return false;
                return true;
            });
            if (!filtered.length) filtered = pool.slice(0, 12);
            var template = filtered[spec.randomIndex(filtered.length)] || filtered[0] || "";
            return spec.formatTemplate(template, data);
        },
        paramScenarioLines: function (values, count) {
            var pool = spec.paramAssistant.scenarioPool || [];
            var data = values || {};
            var size = Math.max(1, Math.min(Number(count) || 6, pool.length));
            var seed = [
                data.symbol,
                data.regime,
                data.volatility,
                data.riskScore,
                data.opportunityScore,
                data.confidence
            ].join("|");
            var picked = [];
            var used = {};
            for (var i = 0; picked.length < size && i < pool.length * 2; i++) {
                var idx = stableIndex(seed, pool.length, i);
                if (used[idx]) continue;
                used[idx] = true;
                picked.push(spec.formatTemplate(pool[idx], data));
            }
            return picked;
        },
        paramRationaleLines: function (values) {
            var data = values || {};
            var pools = spec.paramAssistant.rationalePool || {};
            var categories = [
                "overview",
                "budget",
                "allocation",
                "sellGrid",
                "buyGrid",
                "trailing",
                "profitCycle",
                "risk",
                "confidence",
                "final"
            ];
            var seed = [
                data.symbol,
                data.regime,
                data.stepPct,
                data.riskScore,
                data.opportunityScore,
                data.confidence,
                data.budget
            ].join("|");
            return categories.map(function (category, i) {
                var pool = pools[category] || [];
                if (!pool.length) return "";
                var idx = stableIndex(seed, pool.length, category + "|" + i);
                return spec.formatTemplate(pool[idx], data);
            }).filter(Boolean);
        },
        errorAssistant: ERROR_ASSISTANT,
        normalizeErrorCode: function (input) {
            var raw;
            if (typeof input === "string") {
                raw = input;
            } else if (input && typeof input === "object") {
                var meta = input.meta || {};
                raw = input.code || meta.error_code || input.error_code || input.health_code || meta.health_code;
            }
            raw = String(raw || "").toUpperCase().trim();
            if (!raw) return "";
            var kb = ERROR_ASSISTANT.codeBook;
            if (kb[raw]) return raw;
            var alias = ERROR_ASSISTANT.aliases[raw];
            if (alias && kb[alias]) return alias;
            return raw;
        },
        errorThemeOf: function (code) {
            var key = spec.normalizeErrorCode(code);
            var entry = ERROR_ASSISTANT.codeBook[key];
            return (entry && entry.theme) || "generic";
        },
        errorTechnicalCode: function (input) {
            if (!input || typeof input !== "object") return "";
            var meta = input.meta || {};
            return String(meta.error_code || input.error_code || "").toUpperCase().trim();
        },
        errorGreeting: function (values) {
            var pool = ERROR_ASSISTANT.persona.openings || [];
            var tmpl = pool[spec.randomIndex(pool.length)] || pool[0] || "";
            return spec.formatTemplate(tmpl, values || {});
        },
        errorPickStable: function (pool, seed, salt, values) {
            if (!pool || !pool.length) return "";
            var idx = stableIndex(seed, pool.length, salt);
            return spec.formatTemplate(pool[idx], values || {});
        },
        errorHealthyReport: function (values) {
            var p = ERROR_ASSISTANT.persona;
            var data = values || {};
            var seed = [data.symbol, data.botId, data.tickAge].join("|");
            return {
                healthy: true,
                lead: spec.errorPickStable(p.healthy, seed, "healthy", data),
                checks: (p.healthyChecks || []).map(function (c) { return spec.formatTemplate(c, data); }),
                close: spec.errorPickStable(p.healthyClose, seed, "healthyClose", data)
            };
        },
        errorStoppedReport: function (values) {
            var p = ERROR_ASSISTANT.persona;
            var data = values || {};
            var seed = [data.symbol, data.botId].join("|");
            return {
                stopped: true,
                lead: spec.errorPickStable(p.stopped, seed, "stopped", data),
                close: spec.errorPickStable(p.stoppedClose, seed, "stoppedClose", data)
            };
        },
        errorConnectLine: function (themeId, values) {
            var theme = ERROR_ASSISTANT.themes[themeId] || ERROR_ASSISTANT.themes.generic;
            var pool = (theme && theme.connect) || [];
            var data = values || {};
            var seed = [themeId, data.symbol].join("|");
            return spec.errorPickStable(pool, seed, "connect", data);
        },
        errorClosing: function (values) {
            var pool = ERROR_ASSISTANT.persona.closings || [];
            var data = values || {};
            return spec.errorPickStable(pool, [data.symbol, data.code].join("|"), "closing", data);
        },
        errorReassure: function (values) {
            var pool = ERROR_ASSISTANT.persona.reassure || [];
            var data = values || {};
            return spec.errorPickStable(pool, [data.symbol, data.code].join("|"), "reassure", data);
        },
        errorAdminPrompt: function (values) {
            var pool = ERROR_ASSISTANT.persona.adminPrompt || [];
            var data = values || {};
            return spec.errorPickStable(pool, [data.symbol, data.code].join("|"), "admin", data);
        },
        errorActionMeta: function (id) {
            return ERROR_ASSISTANT.actionLabels[id] || null;
        },
        errorReportForCode: function (code, ctx) {
            var data = ctx || {};
            var key = spec.normalizeErrorCode(code);
            var kb = ERROR_ASSISTANT.codeBook;
            var p = ERROR_ASSISTANT.persona;
            var entry = kb[key];
            var seed = [key, data.symbol, data.errorCode, data.tickAge].join("|");
            if (!entry) {
                var g = p.genericUnknown || {};
                var gdata = {};
                Object.keys(data).forEach(function (k) { gdata[k] = data[k]; });
                gdata.code = key || data.errorCode || "?";
                var glevel = String(data.level || "warn").toLowerCase();
                return {
                    code: gdata.code,
                    found: false,
                    theme: "generic",
                    level: glevel,
                    badge: p.severityWord[glevel] || p.severityWord.warn,
                    label: data.title || ("Tanımsız durum (" + gdata.code + ")"),
                    continues: true,
                    needsAdmin: true,
                    what: spec.errorPickStable(g.what, seed, "what", gdata),
                    why: spec.errorPickStable(g.why, seed, "why", gdata),
                    impact: spec.errorPickStable(g.impact, seed, "impact", gdata),
                    steps: (g.steps || []).map(function (s) { return spec.formatTemplate(s, gdata); }),
                    actions: ["refresh", "contact"]
                };
            }
            return {
                code: key,
                found: true,
                theme: entry.theme || "generic",
                level: entry.level || "warn",
                badge: p.severityWord[entry.level] || p.severityWord.warn,
                label: spec.formatTemplate(entry.label, data),
                continues: !!entry.continues,
                needsAdmin: !!entry.needsAdmin,
                what: spec.errorPickStable(entry.what, seed, "what", data),
                why: spec.errorPickStable(entry.why, seed, "why", data),
                impact: spec.errorPickStable(entry.impact, seed, "impact", data),
                steps: (entry.steps || []).map(function (s) { return spec.formatTemplate(s, data); }),
                actions: (entry.actions || []).slice()
            };
        },
        applyButton: function (button) {
            if (!button) return;
            button.textContent = spec.button.label;
            button.title = spec.button.title;
            button.setAttribute("aria-label", spec.button.ariaLabel);
            if (spec.button.className && !button.classList.contains(spec.button.className)) {
                button.classList.add(spec.button.className);
            }
        },
        applyDesignVars: function () {
            if (!document.documentElement) return;
            var d = spec.design || {};
            var vars = {
                "--ai-assistant-accent": d.accent,
                "--ai-assistant-success": d.success,
                "--ai-assistant-panel-tint": d.panelTint,
                "--ai-assistant-button-bg": d.buttonBg,
                "--ai-assistant-button-min-height": d.buttonMinHeight,
                "--ai-assistant-button-radius": d.buttonRadius,
                "--ai-assistant-modal-radius": d.modalRadius,
                "--ai-assistant-chip-radius": d.chipRadius
            };
            Object.keys(vars).forEach(function (key) {
                if (vars[key]) document.documentElement.style.setProperty(key, vars[key]);
            });
        },
        applyStaticText: function (root) {
            spec.applyDesignVars();
            var base = root || document;
            spec.applyButton(base.getElementById ? base.getElementById("dmParamAssistantBtn") : document.getElementById("dmParamAssistantBtn"));
            var title = document.getElementById("dmParamAssistantTitle");
            if (title) title.textContent = spec.modal.title;
            var label = document.getElementById("dmParamAssistantIntroLabel") ||
                document.querySelector("#dmParamAssistantModal .perf-summary-assistant-label");
            if (label) label.textContent = spec.modal.label;
            var status = document.getElementById("dmParamAssistantStatus");
            if (status && !status.textContent.trim()) status.textContent = spec.modal.initialStatus;
        }
    };

    window.AIAssistantSpec = spec;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { spec.applyStaticText(document); });
    } else {
        spec.applyStaticText(document);
    }
}());
