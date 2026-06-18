# Dinamik Mod Nasıl Çalışır? — Kullanıcı Rehberi

> Bu rapor, **Dinamik Mod**'un DCA/Grid botunla nasıl çalıştığını, neye baktığını, neye göre karar verdiğini ve neyi koruduğunu **açık ve net** ama **detaylı** anlatır. Teknik bilmenize gerek yok; yine de her kararın arkasındaki gerçek mantık ve sayılar burada.
>
> İlgili teknik kaynak: `app/botengine/dynamic/` · Daha derin analiz: `docs/dynamic_mode_analysis/`

---

## 1. Bir bakışta (özet)

Normal (manuel) modda **grid yüzdelerini, trailing'i, kâr eşiklerini ve nakit/coin dağılımını siz elle girersiniz** ve bunlar sabit kalır.

**Dinamik Mod açıkken**, bot bu değerleri **her tur başında piyasaya göre otomatik ayarlar.** Yani:

- Piyasa **sakinse** → dar grid, dengeli dağılım.
- Piyasa **trendliyse** → daha geniş trailing, trende göre nakit/coin ağırlığı.
- Piyasa **düşüyorsa/panikse** → coin/nakit dengesi savunmacılaşır, gridler genişler.

**Önemli:** Dinamik Mod grid adetlerini ve `max_buy_levels` sınırını değiştirmez. Günlük kayıp limiti, %8 stop-loss ve %15 acil kapatma frenleri operatör kararıyla devre dışıdır; dinamik modun aktif güvenliği `max_buy_levels` ve risk filtresinden geçen parametre sınırlarıdır.

---

## 2. Önce temel: DCA/Grid bot nasıl çalışıyor? (kısa hatırlatma)

Dinamik modu anlamak için botun iskeletini bilmek yeterli:

- Botun bir **bütçesi** var ve bunu **base (coin)** ve **quote (nakit/USDT)** olarak ikiye böler (örn. %50 / %50).
- **Alım gridleri (down):** Fiyat referansın altına belirli yüzdelerde indikçe (örn. −%2, −%4, −%6) bot kademeli **alır** (ortalama maliyet düşürme = DCA).
- **Satış gridleri (up):** Fiyat yükseldikçe belirli yüzdelerde kademeli **satar** (kâr alma).
- **Trailing (iz süren):** Bir grid tetiklenince hemen işlem yapmaz; fiyatın dönüşünü "iz sürerek" bekler (daha iyi fiyat yakalamak için).
- **Tur (cycle):** Bot kâr-çıkışı (profit-exit) veya yeniden-giriş (re-entry) yaptığında **tur kapanır**, yeni tur başlar.
- **`max_buy_levels`:** En fazla kaç alım seviyesinin açılabileceğinin sert sınırı (DCA'in dibi).

**Dinamik mod bu iskeleti DEĞİŞTİRMEZ.** Sadece yukarıdaki yüzdeleri (grid aralıkları, trailing, kâr eşikleri, base/quote oranı) tur başında piyasaya göre yeniden hesaplar. Grid **sayınız** ve `max_buy_levels` aynen korunur.

---

## 3. Dinamik mod neyi değiştirir, neye ASLA dokunmaz?

| Bot otomatik AYARLAR (overlay) | Bot ASLA dokunmaz (sizin/sistemin) |
|---|---|
| Base / Quote dağılımı (`base_alloc_pct`) | `max_buy_levels` (DCA sert sınırı) |
| Satış grid yüzdeleri ve dağılımı | `daily_loss_limit_usd` (alan korunur, uygulama devre dışı) |
| Alım grid yüzdeleri ve dağılımı | Sembol, başlangıç sermayesi, komisyon oranları |
| Satış/Alım trailing yüzdeleri | Tick aralığı, dakikalık emir limiti |
| Kâr-alma eşikleri (rise/drop) | Stop-loss %8 / acil %15 frenleri (devre dışı) |
| Yeniden-giriş eşikleri (drop/rise) | Grid **sayısı** (adet korunur, sadece yüzdeler değişir) |

> Yani dinamik mod **yüzdeleri** oynar; **yapıyı ve güvenlik sınırlarını** değil.

---

## 4. NE ZAMAN tepki verir? (Tur bazlı — tick bazlı değil)

Bu, en sık yanlış anlaşılan nokta. **Dinamik mod her saniye/her fiyat hareketinde değer değiştirmez.** Değerler **yalnızca tur başında** bir kez hesaplanır ve **o tur boyunca sabit kalır** (immutable snapshot).

İlk tur özel kuraldır: bot ilk açıldığında **manuel başlangıç değerleriyle** başlar. Dinamik hesaplama tur 2 başında devreye girer.

Yeni hesaplama (snapshot) yalnızca şu durumlarda olur:

1. **Tur kapandığında** (kâr-çıkışı veya yeniden-giriş gerçekleşince),
2. Tur kimliği (`cycle_id`) değiştiğinde,
3. Tur 2+ içinde henüz snapshot yokken.

**Neden böyle?** Çünkü grid yüzdelerini tur ortasında değiştirmek, zaten kurulmuş ve tetiklenmiş gridlerin referanslarını bozardı (kaos olurdu). Tur bazlı olması, kararın **anlık gürültüye değil, oturmuş duruma** göre verilmesini de sağlar.

> **Sonuç:** Dinamik mod "anlık" değil, "tur ritmine" göre nefes alır. Uzun süren bir turda değerler sabit kalır; alım tarafındaki sert sınır `max_buy_levels` ile korunur.

---

## 5. NEYE bakar? (Topladığı veriler)

Bot her snapshot'ta Binance'ten **kapanmış mum** verisi ve anlık piyasa bilgisi çeker:

| Veri | Zaman dilimi | Ne işe yarar |
|------|--------------|--------------|
| **ATR** (Average True Range) | 5 dakika | Kısa vadeli **volatilite** → grid genişliği, trailing |
| **ADX** | 1 saat | **Trend gücü** (trend mi yatay mı?) |
| **EMA eğimi** | 1 saat | **Trend yönü** (yukarı mı aşağı mı?) |
| **BBW** (Bollinger Band Width) | 1s / 5dk | **Sıkışma / patlama** (squeeze / breakout) |
| **RSI** | 1s / 5dk | **Aşırı alım / aşırı satım** |
| **Hacim z-skoru** | 5 dakika | **Hacim patlaması** (breakout/dump teyidi) |
| **Son 5dk getirisi** | 5 dakika | **Ani çöküş** (flash-crash) sinyali |
| **Spread** (alış-satış farkı) | anlık | **Likidite** kalitesi |
| **24s hacim** | 24 saat | Coin'in **likiditesi** (illiquid mi?) |

**Önemli iki ilke:**

- **Yarı oluşmuş mum sayılmaz.** O an oluşmakta olan (kapanmamış) mum hesaba katılmaz — yoksa anlık bir fiyat sıçraması yanlış rejim açabilirdi. İndikatörler **kapanmış** mumlarla hesaplanır.
- **İki zaman dilimi birlikte:** Trend kararı **yavaş** veriden (1 saat), volatilite/grid kararı **hızlı** veriden (5 dakika) gelir. Bu sayede trend gürültüye kapılmaz, grid ise güncel oynaklığa uyar.

> Veri çekilemezse (ağ/borsa sorunu) bot **çökmez**: bir önceki turun değerlerini kullanır ve arayüzde "veri eski" uyarısı gösterir.

---

## 6. REJİMLER — Bot piyasayı nasıl sınıflandırır?

Dinamik modun kalbi budur. Bot, topladığı verilerden piyasayı **8 rejimden birine** koyar ve davranışını ona göre seçer.

### 6.1 Rejimler ve tetiklenme koşulları

| Rejim | Ne demek | Nasıl tetiklenir (basitçe) |
|-------|----------|----------------------------|
| 🟢 **LOW_VOL_RANGING** | Sakin yatay piyasa, ideal grid ortamı | ADX ≤ 20 (trend yok) **ve** ATR düşük (≤ %0.4) |
| 🟡 **HIGH_VOL_RANGING** | Dalgalı/tuzaklı yatay (chop) | ADX ≤ 20 **ve** ATR yüksek (≥ %1.5) |
| 🔵 **TRENDING_UP** | Güçlü yukarı trend | ADX ≥ 25 **ve** EMA eğimi ≥ +%0.4 |
| 🟠 **TRENDING_DOWN** | Güçlü aşağı trend (DCA'in en riskli hâli) | ADX ≥ 25 **ve** EMA eğimi ≤ −%0.4 |
| 🟣 **SQUEEZE** | Tarihi dar bant, patlama öncesi | 1s BBW ≤ 2.5 (yoksa 5dk BBW) |
| ⚡ **BREAKOUT** | Bant patlaması + hacim (yukarı yön) | BBW ≥ 6 **ve** hacim z-skoru ≥ 2 **ve** yön yukarı |
| 🔴 **DUMP_RISK** | Çöküş/panik riski | Son 5dk ≤ −%3 (flash crash) **VEYA** 1s eğim ≤ −%2 + hacim patlaması |
| ⚪ **UNKNOWN** | Veri yetersiz | Yeterli indikatör yoksa (nötr, manuele yakın davranır) |

**Öncelik sırası (önce tehlike):** DUMP_RISK → BREAKOUT → SQUEEZE → Trend/Yatay → belirsizse ATR'ye göre. Yani bir çöküş sinyali varsa, başka her şeyin önüne geçer.

**Yön farkındalığı:** Bir bant patlaması **aşağı** yönlüyse (slope negatif), bu "boğa kırılımı" değildir — bot onu **BREAKOUT (nötr) yerine TRENDING_DOWN (defansif)** olarak ele alır. Bu, "çöküşü yükseliş sanma" hatasını önler.

### 6.2 Rejim ne sıklıkta değişir?

Rejim **tur başında** yeniden hesaplanır (her tick değil). Bu doğal bir tampondur. Ayrıca:

- **Güven (confidence)** düşükse, değerler önceki turun değerlerine **daha yapışık** kalır (ani savruluş olmaz).
- Rejim değişse bile yeni değerler **yumuşatılarak** (smoothing) ve **hız limitiyle** uygulanır — bir turda zıplamaz.

---

## 7. Her rejimde bot NE YAPAR? (Davranış tablosu)

Rejim seçildikten sonra bot temel ayarları o rejime göre ölçekler. Grid miktar yüzdeleri ise manuel şablondaki gibi korunur; dinamik mod onları 47.6/52.4 gibi yeniden dağıtmaz.

| Rejim | Grid mesafesi | Trailing | Base (coin) oranı | Kâr-alma | Grid miktar % |
|-------|:---:|:---:|:---:|:---:|:---:|
| LOW_VOL_RANGING | manuelden dar olmaz | dar | %50 dengeli | erken | manuel korunur |
| HIGH_VOL_RANGING | geniş | geniş | %40 (az coin) | geç | manuel korunur |
| TRENDING_UP | orta/geniş | geniş | %60 (çok coin) | çok geç | manuel korunur |
| TRENDING_DOWN | geniş | orta | **%25 (nakit koru)** | orta | manuel korunur |
| SQUEEZE | manuelden dar olmaz | normal | %45 | normal | manuel korunur |
| BREAKOUT | çok geniş | çok geniş | %50 | geç | manuel korunur |
| DUMP_RISK | en geniş | normal | **%15 (çoğu nakit)** | normal | manuel korunur |
| UNKNOWN | nötr | nötr | %50 | nötr | manuel korunur |

**Okuma örneği:**
- **Düşüş trendinde (TRENDING_DOWN):** bot hedef base oranını düşürür, daha çok nakit taşır ve gridleri genişletir (her dip alımı daha derinde olur).
- **Panikte (DUMP_RISK):** bot hedef base oranını %15'e indirir ve gridleri en geniş hâle getirir. Grid miktar yüzdeleri elle kurduğun oranlarda kalır.
- **Yükseliş trendinde (TRENDING_UP):** bot coin ağırlığını artırır (%60), kârı geç alır ve trailing'i genişletir.

> **Not:** Dinamik mod, manuel grid tetiklerini daha yakına çekmez. Örneğin manuel alım gridlerin −%2/−%4 ise düşük ATR gelse bile bunları −%0.30/−%0.60'a düşürmez; ancak yüksek volatilitede daha uzağa taşıyabilir.

---

## 8. Akıllı ek ayarlamalar (RSI + Likidite + Komisyon)

Rejim ana karardır; üstüne bot şu "ince ayarları" da yapar:

- **Komisyon farkındalığı:** grid aralığı, **komisyon + minimum kârı** ve **spread'i** karşılamayacak kadar dar yapılmaz. Yani "açıldığında zaten zarar edecek" grid üretilmez.
- **Manuel taban:** grid tetik yüzdeleri manuel şablondan daha dar olamaz; dinamik mod yalnızca aynı seviyeyi korur veya genişletir.
- **Miktar korunumu:** grid miktar yüzdeleri manuel şablondaki gibi kalır. %50/%50 kurduysan dinamik mod bunu başka oranlara çevirmez.
- **Derinlik koruması:** çok yüksek volatilitede gridler tek noktaya yığılmaz; **yayılır** (örn. %2, %4, %6, %8) — DCA derinliği korunur.

Bütün bu ayarlar **manuel grid iskelesini** korur; dinamik mod sayı/adet ve miktar niyetini bozmaz.

---

## 9. Aktif sınırlar ve kapatılan frenler

Mevcut operatör kararıyla dinamik ve manuel modda otomatik durdurma frenleri devre dışıdır. Aktif kalan yapısal sınır:

1. **`max_buy_levels ≥ 1`** — DCA sert üst sınırı. Bot aynı turda bu sayının üstünde alım gridini çalıştırmaz.

Devre dışı bırakılan frenler:

- **`daily_loss_limit_usd`** — alan korunur ama günlük kayıp durdurması çalışmaz; bütçenin %5'i otomatik atanmaz.
- **Stop-loss %8** — tur özkaynağı düşüşü botu duraklatmaz.
- **Acil kapatma %15** — portföy düşüş devre kesicisi botu duraklatmaz.

### 9.1 Her üretilen değer risk filtresinden geçer

Hiçbir değer ham uygulanmaz. Risk motoru:
- Her değeri **güvenli aralığa** çeker (örn. grid %0.10–8, trailing %0.15–5, base %10–80).
- Turlar arası **ani sıçramayı** %60 ile sınırlar (skaler değerlerde).
- Grid alım miktarının **katlanarak büyümesini** engeller (anti-martingale, ≤1.5×).
- Bozuk/NaN değer gelirse **manuel ayara** geri düşer.

> Yani en kötü ihtimalle bot "dinamik mod kapalıymış gibi" sınırlı değerlerle çalışır. Bu filtre parametreleri sınırlar; otomatik stop-loss/günlük limit görevi görmez.

### 9.2 Kapatılan frenler artık ne yapmaz?

Bu üç fren artık ne dinamik modda ne manuel modda botu durdurur:

- Günlük zarar `daily_loss_limit_usd` değerini aşsa bile tick durmaz.
- Tur özkaynağı %8'den fazla düşse bile `DYN_STOP_LOSS` oluşmaz.
- Portföy %15'ten fazla düşse bile `DYN_EMERGENCY_CLOSE` oluşmaz.

### 9.3 DCA sert sınırı hâlâ çalışır

`max_buy_levels` kaldırılmadı. Bu alan DB, API validasyonu, strateji ve emir yürütme tarafında yapısal sınırdır. Alım grid sayısı bu sınırı aşarsa yeni BUY emri engellenir; trailing ve kâr çıkışları çalışmaya devam eder.

---

## 10. Somut örnek senaryolar

### Senaryo A — Sakin yatay piyasa (LOW_VOL_RANGING)
ATR %0.3, ADX 15. Bot: manuel gridlerinden daha dara inmez; trailing daralabilir, %50/%50 dağılım korunur, kârı erken alır. **Sonuç:** sakin grid ticareti; kullanıcı şablonu ezilmez.

### Senaryo B — Yükseliş trendi (TRENDING_UP)
ATR %1, ADX 30, eğim +%0.8. Bot: coin ağırlığını %60'a çıkarır, trailing'i genişletir (erken stop-out olmaz), kârı geç alır (trendi sürer). **Sonuç:** yükselişe daha çok katılır, satışta acele etmez.

### Senaryo C — Ani çöküş (DUMP_RISK)
Son 5dk −%4. Bot tur başında DUMP_RISK'e geçerse base hedefi %15'e iner ve gridler genişler. Grid miktar yüzdeleri manuel şablonda kalır. Ancak %8 stop-loss, %15 acil kapatma ve günlük kayıp limiti artık botu durdurmaz. **Sonuç:** parametreler defansifleşebilir ama otomatik durdurma freni yoktur; alım tarafındaki son sert sınır `max_buy_levels` olur.

---

## 11. DCA yapısıyla uyumu — neden çelişmez?

| DCA ilkesi | Dinamik mod uyumu |
|---|---|
| Grid **sayısı** ve `max_buy_levels` sabit | ✅ Korunur — sadece yüzdeler değişir |
| Düşüşte kademeli alım | ✅ Gridler korunur; riskli rejimde **genişler** (daha derin/seyrek), miktar kısılır |
| Tur mantığı (kâr-çıkış / yeniden-giriş) | ✅ Snapshot tur ritmine bağlı; tur içinde sabit |
| Çekirdek pozisyon (rezerv) tutma | ✅ Manuel qty toplamınız korunur; %100'e zorlanmaz |
| Komisyon-farkında kâr | ✅ Gridler komisyon altına düşürülmez |
| Derin DCA (örn. −%20) | ⚠️ Dinamik modda gridler güvenlik için **en fazla %8** derinlikte olur — çok derin DCA isteyen kullanıcı bunu bilmeli |

---

## 12. Doğruluk ve bilmeniz gereken sınırlar

**Doğru çalışan / güçlü yanlar:**
- İndikatör hesapları (ATR/ADX/RSI/BBW) standart ve doğru; kapanmış mumla, hataya dayanıklı.
- Rejim → davranış yönleri ekonomik olarak mantıklı (düşüşte savun, trendde katıl).
- Risk motoru "son söz" sahibi; felaket değer üretilemez.
- Veri eskirse güvenli geri düşüş; bot çökmez.
- Manuel mod tamamen ayrı — dinamik kapalıysa hiç devreye girmez.

**Bilinçli sınırlar / dikkat:**
- Dinamik gridler güvenlik için **≤%8 derinlikte**. Çok derin DCA isteyen, manuel mod kullanmalı.
- Rejim eşikleri tüm semboller için **aynı** (henüz coin'e göre normalize edilmiyor); çok düşük/yüksek volatiliteli egzotik coin'lerde eşikler daha az isabetli olabilir.
- Günlük kayıp limiti, %8 stop-loss ve %15 acil kapatma **devre dışıdır** — gözetimsiz çalışan botta sert çöküşü otomatik durduracak fren yoktur.
- Rejim tur bazlı hesaplandığından, **uzun süren tek bir turda** rejim güncellenmez; o turdaki alım sınırı `max_buy_levels` ile kalır.

---

## 13. Özet — Dinamik modu ne zaman kullanmalı?

**Kullan:**
- Piyasa koşulları değişkense ve her sefer elle ayar yapmak istemiyorsan.
- Düşüşte daha defansif parametreler istiyorsan; otomatik durdurma freni beklemiyorsan.
- Standart bir sembolde (iyi likiditeli) çalışıyorsan.

**Manuel modu tercih et:**
- Çok **derin DCA** (−%10/−%20) planın varsa (dinamik %8 ile sınırlar).
- Tam **deterministik**, hiç değişmeyen bir setup istiyorsan.
- Egzotik/illiquid bir coin'de kendi eşiklerini elle yönetmek istiyorsan.

**Her durumda:** Dinamik mod `max_buy_levels` sınırını gevşetmez; günlük limit ve devre kesici frenleri ise bu kurulumda kapalıdır. Beğenmezsen oluştururken kapatabilirsin — manuel mod aynen eskisi gibi çalışır.

---

> **Tek cümlede:** Dinamik Mod, **sizin grid iskelenizi ve `max_buy_levels` sınırınızı koruyarak**, içindeki yüzdeleri (grid aralığı, trailing, nakit/coin oranı, kâr/alım miktarı) **her tur başında piyasaya — sakinlik, trend, sıkışma, patlama, çöküş — göre otomatik ayarlayan** bir katmandır; günlük limit, %8 stop-loss ve %15 acil fren bu kurulumda kapalıdır.
