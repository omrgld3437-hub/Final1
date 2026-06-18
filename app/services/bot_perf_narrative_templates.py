"""
Permanent template pool for the bot performance narrative ("Analiz özeti").

Goal: produce professional, AI-style, full-sentence Turkish commentary that is
filled with REAL computed data and never feels repetitive. The narrative builder
(`bot_perf_narrative.py`) computes a rich `inputs` dict, picks one template per
section from the relevant category via a STABLE-but-varied selector (so a given
month always reads the same, while different months/cycles vary), and fills the
`{placeholder}` fields.

Conventions
-----------
* Every template is a complete, grammatical Turkish sentence (or two).
* `{placeholder}` fields are pre-formatted strings supplied by the builder
  (e.g. `{net}` = "+$1.47", `{alpha}` = "-4.99%", `{regime}` = "yatay / dalgalı").
* Categories are chosen by the builder from computed conditions; within a
  category any template is interchangeable (same meaning, different wording).
* Dual-leg accounting is respected everywhere: "nakit bacak" = realized USDT
  (BUY-side cycles), "envanter bacak" = extra coin quantity (SELL-side cycles).

Total templates: 320+ (see `pool_size()`).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List


# =============================================================================
# 1) HEADLINE  (inputs: label, total, net, gross, alpha)
# =============================================================================

HEADLINE = {
    "no_cycles": [
        "{label}: Bu ay henüz kapanmış tur yok; değerlendirme için veri birikmesi bekleniyor.",
        "{label}: Ay içinde tamamlanmış tur bulunmuyor — sonuçlar ilk kapanışla netleşecek.",
        "{label}: Kapanmış tur olmadığından bu ay için performans okuması yapılamıyor.",
        "{label}: Henüz realize edilmiş bir tur yok; bot pozisyonu açık taşıyor olabilir.",
        "{label}: Bu ayın defteri boş — kapanan tur olmadan kâr/zarar ölçülmez.",
        "{label}: Tamamlanmış tur kaydı yok; rapor bir sonraki kapanışta anlam kazanacak.",
    ],
    "pos_alpha_neg": [
        "{label}: {total} tur · net nakit {net} — realize tarafı kârlı, ancak al-tut benchmark tarafı zayıf.",
        "{label}: {total} turda net {net} realize; nakit pozitif fakat coin tutmanın gerisinde kalınmış.",
        "{label}: Net nakit {net} ile ay artıda kapandı, ama benchmark tarafı zayıf — alpha negatif.",
        "{label}: {total} tur kârlı kapansa da ({net}) al-tut karşılaştırması bu ay botun aleyhine.",
        "{label}: Operasyonel olarak kârlı bir ay ({net}); yine de benchmark tarafı zayıf kaldı.",
        "{label}: {total} tur, net {net} — kasada artı var fakat fırsat maliyeti tarafı olumsuz.",
        "{label}: Realize nakit {net} pozitif; al-tut benchmark tarafı zayıf, yani coin tutmak daha çok kazandırırdı.",
    ],
    "pos_alpha_pos": [
        "{label}: {total} tur · net nakit {net} — hem realize kârlı hem al-tut benchmarkı geçilmiş.",
        "{label}: Güçlü bir ay: {total} turda net {net} ve coin tutmaya kıyasla pozitif alpha.",
        "{label}: Net {net} realize ve benchmark üstü performans — aktif ticaret bu ay değer kattı.",
        "{label}: {total} tur kârlı ({net}) ve al-tut alternatifini geride bırakmış; ideal profil.",
        "{label}: Hem kasa hem benchmark tarafı pozitif — {total} turda net {net}.",
        "{label}: Bu ay bot, {net} net getiriyle coin tutmanın da önüne geçmiş.",
        "{label}: {total} tur, net {net}, pozitif alpha — strateji piyasayla uyumlu çalışmış.",
    ],
    "pos_alpha_flat": [
        "{label}: {total} tur · net nakit {net} — nakit tarafı yapıcı, ay artıda kapandı.",
        "{label}: {total} turda net {net} realize; istikrarlı, yapıcı bir ay profili.",
        "{label}: Net nakit {net} ile ay pozitif; sonuç sağlam ve sürdürülebilir görünüyor.",
        "{label}: {total} tur kârla kapandı (net {net}); benchmarkla başa baş bir seyir.",
        "{label}: Ay artıda: {total} tur, net {net} — kasayı koruyarak büyütmüş bir performans.",
        "{label}: {total} tur · net {net} — temkinli ama olumlu bir ay.",
        "{label}: Net {net} realize; bot bu ay sermayeyi verimli biçimde çevirmiş.",
    ],
    "neg": [
        "{label}: {total} tur · net nakit {net} — zorlu bir ay, realize taraf eksiye döndü.",
        "{label}: {total} turun ardından net {net}; ay strateji aleyhine işledi.",
        "{label}: Net nakit {net} ile ay negatif kapandı — grid veya piyasa yönü uyumsuzdu.",
        "{label}: Zorlu bir dönem: {total} tur, net {net}; kasada erime var.",
        "{label}: {total} tur, net {net} — bu ay komisyon ve piyasa birlikte aleyhe çalışmış.",
        "{label}: Ay eksiyle kapandı (net {net}); tek başına paniklemeyi değil, izlemeyi gerektirir.",
        "{label}: {total} turda net {net} — performans bu ay beklentinin altında.",
    ],
    "zero": [
        "{label}: {total} tur · net nakit {net} — büyük ölçüde başa baş bir ay.",
        "{label}: {total} turun net etkisi {net}; ay nötr, kayda değer bir sapma yok.",
        "{label}: Net {net} ile ay yatay kapandı — ne kazanç ne kayıp baskın.",
        "{label}: {total} tur, net {net}; sonuç dengede, sermaye korunmuş.",
        "{label}: Başa baş bir ay (net {net}); strateji sermayeyi koruma kıvamında çalışmış.",
        "{label}: {total} tur · net {net} — nötr bir performans tablosu.",
    ],
    # net nakit eksi AMA alpha pozitif: düşen piyasada al-tut'tan iyi korunma.
    "neg_alpha_pos": [
        "{label}: {total} tur · net nakit {net} — realize tarafı eksi, ancak düşen piyasada al-tut'tan daha iyi korunmuş (pozitif alpha).",
        "{label}: Ay nakitte {net} ile zararda; yine de bot, coini tutmaya kıyasla daha az kaybetmiş — alpha pozitif.",
        "{label}: {total} turda net {net}; kasada erime var ama benchmark altında, düşüşte göreli üstünlük sağlanmış.",
        "{label}: Realize taraf eksi ({net}); fakat pozitif alpha, stratejinin düşüşte koruyucu çalıştığını gösteriyor.",
        "{label}: {total} tur, net {net} — mutlak getiri negatif, göreli getiri (alpha) pozitif; düşüş al-tut'tan iyi atlatılmış.",
        "{label}: Nakitte {net} kayıp; ancak coin tutmak bu ay daha çok kaybettireceğinden alpha artıda.",
    ],
    # nakit ~0, envanter (coin) POZİTİF: kazanç coin tarafında.
    "inv_led": [
        "{label}: {total} tur · kazanç bu ay coin tarafında (envanter); nakit bacak nötr.",
        "{label}: Ay envanter ağırlıklı geçti — kasada hareket yok ama elde tutulan coin adedi artmış.",
        "{label}: {total} turda nakit nötr; bot bu ay USDT yerine fazladan coin biriktirmiş.",
        "{label}: Kazanç nakitte değil envanterde — coin adedi artışıyla kapanan bir ay.",
        "{label}: {total} tur · nakit başa baş, ama envanter bacak pozitif; bot coin pozisyonunu büyütmüş.",
        "{label}: Bu ay realize USDT yok; sonuç coin biriktirme (envanter avantajı) olarak okunmalı.",
    ],
    # nakit ~0, envanter (coin) NEGATİF: coin tarafında kayıp.
    "inv_led_neg": [
        "{label}: {total} tur · nakit nötr, fakat envanter tarafında coin adedi gerilemiş.",
        "{label}: Ay nakitte hareketsiz; envanter bacak coin tarafında kayıpla kapanmış.",
        "{label}: {total} turda realize USDT yok; sonuç coin adedinde net azalma olarak görünüyor.",
        "{label}: Kasada değişim yok, ancak envanter tarafı bu ay coin kaybetmiş.",
        "{label}: {total} tur · nakit başa baş, envanter negatif; coin pozisyonu küçülmüş.",
    ],
}


# =============================================================================
# 2) SUMMARY  (intro / cash / inventory)
# =============================================================================

SUMMARY_INTRO = [
    "Bu ay bot {symbol} paritesinde {total} kapanmış tur üretmiş: {cash_closed} aşağı yönlü nakit turu ve {inv_closed} yukarı yönlü envanter turu. Strateji çift bacaklı çalışır: aşağı/nakit bacak, fiyat geri çekildikten sonra yapılan kademeli (DCA) alımların toparlanmada satışıyla realize edilen USDT kârını ölçer; yukarı/envanter bacak ise yüksekten satıp düşükten geri alarak kazanılan fazladan coin adedini ölçer. İki bacak farklı birimlerde raporlanır (biri USDT, diğeri coin).",
    "{symbol} botu ay içinde toplam {total} tur kapatmış ({cash_closed} nakit, {inv_closed} envanter). Çift bacaklı mantıkta nakit bacak, dipten alıp toparlanmada satarak USDT kârını; envanter bacak ise yüksekten satıp daha ucuza geri alarak biriken ekstra coin adedini temsil eder. Bu yüzden iki sonuç farklı birimlerde okunur.",
    "Bu dönem {symbol} üzerinde {total} tur tamamlandı: {cash_closed} aşağı yönlü (nakit) ve {inv_closed} yukarı yönlü (envanter). Nakit bacak realize USDT kazancını ölçerken, envanter bacak coin adedindeki net değişimi ölçer; ikisi aynı ölçeğe indirgenmez.",
    "Ay boyunca {symbol} botu {total} kapanış üretti — {cash_closed} nakit, {inv_closed} envanter turu. Hatırlatma: nakit bacak 'dip alımı + toparlanma satışı = USDT kârı' döngüsünü, envanter bacak 'tepe satışı + ucuz geri alım = fazladan coin' döngüsünü raporlar.",
    "{symbol} paritesinde bu ay {total} tur kapandı ({cash_closed}/{inv_closed} nakit/envanter). Botun iki kazanç kanalı vardır: USDT cinsinden realize edilen nakit kâr ve coin adedi cinsinden biriken envanter avantajı; rapor ikisini ayrı ayrı sunar.",
    "Bu ayki tablo {symbol} için {total} kapanmış turdan oluşuyor: {cash_closed} nakit, {inv_closed} envanter. Aşağı/nakit bacak geri çekilmeleri USDT kârına çevirir; yukarı/envanter bacak yükselişleri fazladan coin'e çevirir — sonuçlar farklı birimlerdedir.",
    "{symbol} botu {total} turla ayı tamamladı ({cash_closed} aşağı, {inv_closed} yukarı yön). Çift yönlü grid mantığında nakit ve envanter bacakları birbirinden bağımsız ölçülür; biri kasayı (USDT), diğeri eldeki coin miktarını büyütmeyi hedefler.",
    "Bu ay {symbol} için kapanan tur sayısı {total} ({cash_closed} nakit + {inv_closed} envanter). Nakit bacak realize USDT, envanter bacak ise coin adedi avantajıdır; raporun geri kalanı bu iki kanalı ayrı değerlendirir.",
    "Dönem özeti: {symbol} botu {total} tur kapattı; {cash_closed} tanesi nakit (USDT realize), {inv_closed} tanesi envanter (coin biriktirme) yönünde. İki bacağın birimleri farklı olduğundan tek bir rakama indirgenmez.",
    "{symbol} üzerinde {total} kapanmış tur ile aya bakıldığında dağılım {cash_closed} nakit / {inv_closed} envanter şeklinde. Nakit bacak 'al-bekle-sat' ile USDT, envanter bacak 'sat-bekle-geri al' ile coin adedi kazanır.",
]

# İşaret-nötr: hem kâr (+$1.47) hem zarar (-$0.35) net değeri için doğru okunur.
SUMMARY_CASH = [
    "Nakit bacak hesabı: brüt {gross} − komisyon {fees} = net {net}.",
    "Nakit tarafın aritmetiği: brüt {gross} sonucundan {fees} komisyon düşülünce net {net} kalır.",
    "Realize USDT akışı: brüt {gross}, komisyon {fees}, net sonuç {net}.",
    "Kasaya yansıyan: brüt {gross} eksi {fees} işlem maliyeti, yani net {net}.",
    "Nakit bacakta brüt sonuç {gross}; {fees} komisyon sonrası net {net}.",
    "USDT tarafında brüt {gross}'tan {fees} komisyon çıktıktan sonra net {net} kalmış.",
    "Net nakit {net} = brüt {gross} − komisyon {fees}; raporlanan değer komisyon sonrasıdır.",
    "Nakit bacak: {gross} brüt, {fees} maliyet, {net} net — sonuç komisyon düşülerek ölçülür.",
]

SUMMARY_INV_PRESENT = [
    "Envanter bacakta toplam {inv_coin} {base} avantaj (coin adedi); komisyon maliyeti {inv_fees}. Bu kalem nakit değil, elde tutulan coin miktarındaki net değişimi temsil eder.",
    "Yukarı/envanter tarafında {inv_coin} {base} ek coin biriktirilmiş ({inv_fees} komisyon); bu USDT değil, aynı sermayeyle daha fazla coin tutma avantajıdır.",
    "Envanter bacak {inv_coin} {base} net coin avantajı üretti (maliyet {inv_fees}). Kazanç burada nakitte değil, coin adedinde okunmalı.",
    "Coin adedi tarafında net değişim {inv_coin} {base} ({inv_fees} komisyon) — botun 'sat-geri al' döngüsüyle elde tuttuğu fazladan miktar.",
    "Envanter bacakta {inv_coin} {base} avantaj birikmiş; komisyon {inv_fees}. Bu sonuç USDT kârından ayrı, ikinci bir kazanç kanalıdır.",
    "Yukarı yön turlarından {inv_coin} {base} ek coin ({inv_fees} maliyet) gelmiş; portföydeki coin adedi bu kadar artmış sayılır.",
    "Envanter kanalı bu ay {inv_coin} {base} net coin sağladı ({inv_fees} komisyon) — nakit kârla karıştırılmamalı, farklı birimdedir.",
]

SUMMARY_INV_ABSENT = [
    "Bu ay yukarı/envanter bacağında tamamlanmış tur yok; bu nedenle ayın ana sonucu USDT nakit kârı üzerinden okunmalı ve sonuç tek bacak ağırlıklı değerlendirilmelidir.",
    "Envanter yönünde kapanış olmadığından coin biriktirme kanalı bu ay sessiz kalmış; rapor nakit (USDT) tarafına dayanır.",
    "Yukarı yön turu kapanmadığı için envanter avantajı sıfır; sonuç tek bacaklı, yani sadece realize nakit üzerinden anlamlı.",
    "Bu dönem envanter bacağı kapalı sonuç üretmedi; coin adedi avantajı yok, değerlendirme nakit kâra odaklanır.",
    "Envanter tarafında tamamlanmış tur bulunmuyor; bu yüzden ay, USDT realize sonucuyla tek yönlü okunmalıdır.",
    "Coin biriktirme bacağı bu ay devreye girmemiş; rapordaki ana ölçü realize nakit kârdır.",
    "Yukarı/envanter kanalında kapanış yok — sonuç tek bacak ağırlıklı; ikinci kanal henüz veri üretmedi.",
]

# Envanter NEGATİF (coin kaybı) — "avantaj" demeden, doğru çerçeveyle.
SUMMARY_INV_NEG = [
    "Envanter bacakta net {inv_coin} {base} değişim (coin adedi); komisyon {inv_fees}. Bu ay coin tarafında dezavantaj oluşmuş — elde tutulan miktar azalmış.",
    "Yukarı/envanter tarafında coin adedi {inv_coin} {base} gerilemiş ({inv_fees} komisyon); bu bir kazanç değil, coin cinsinden kayıptır.",
    "Envanter bacak bu ay {inv_coin} {base} ile negatif sonuç verdi (maliyet {inv_fees}); coin pozisyonu küçülmüş.",
    "Coin adedi tarafında net değişim {inv_coin} {base} ({inv_fees} komisyon) — envanter bacak bu ay dezavantaj üretmiş.",
    "Envanter kanalı {inv_coin} {base} negatif kapadı ({inv_fees}); elde tutulan coin miktarı azalmış.",
]

# Nakit ~0 ama envanter aktif: nakit satırını sade ve doğru çerçevele.
SUMMARY_CASH_INV_LED = [
    "Nakit bacakta bu ay kayda değer hareket yok (net {net}); kazanç/sonuç tamamen envanter (coin) tarafında oluştu.",
    "Realize USDT akışı bu ay nötr (net {net}) — sonuç nakit değil, coin adedi tarafında okunmalı.",
    "Nakit taraf başa baş (net {net}); ayın asıl hareketi envanter bacağında, coin cinsindendir.",
    "Bu ay nakit bacak hareketsiz kaldı (net {net}); değişim coin adedinde gerçekleşti.",
    "Kasaya yansıyan net {net}; nakit nötr olduğundan ay envanter (coin) tarafından okunur.",
]


# =============================================================================
# 3) ALPHA  (definition + reading by band)
# =============================================================================

ALPHA_DEF = [
    "Oturum performansı (alpha) {alpha}. Alpha = bot bakiye yüzdesi eksi paritenin aynı dönemdeki yüzdesel hareketi (yani coini hiç işlem yapmadan tutma, al-tut benchmark'ı).",
    "Bu oturumun alpha değeri {alpha}. Alpha, botun yüzdesel getirisinden paritenin kendi hareketini çıkarır; pozitifse aktif ticaret coin tutmayı geçmiş demektir.",
    "Oturum alpha'sı {alpha}. Tanım gereği alpha, bot getirisi ile 'sadece coini tut' senaryosu arasındaki farktır.",
    "Alpha {alpha} olarak ölçüldü. Bu metrik, botu pasif al-tut alternatifiyle aynı sermaye üzerinden kıyaslar.",
    "Oturum performansı (alpha) {alpha} — yani botun getirisi, coini hiç dokunmadan tutmaya göre bu kadar farklı seyretmiş.",
]

ALPHA_POS = [
    "Alpha pozitif: bot, aynı dönemde aynı sermayeyle coini yalnızca elde tutma senaryosunu geçmiş; aktif grid ticareti benchmark'ın üzerine net değer katmış.",
    "Pozitif alpha, botun al-tut alternatifinden daha iyi performans verdiğini gösteriyor — ticaret bu pencerede işe yaramış.",
    "Alpha artıda: aktif strateji, coini pasif tutmaya kıyasla fazladan getiri üretmiş.",
    "Bu oturumda bot, benchmark'ı geçmiş; pozitif alpha aktif yönetimin değer kattığının kanıtı.",
    "Alpha pozitif olduğundan, botun bu dönem coin tutmaktan daha verimli çalıştığı söylenebilir.",
    "Pozitif alpha: gridlerin alım-satım ritmi, pasif tutmaya göre ek kazanç sağlamış.",
    "Bot, al-tut çizgisinin üzerinde kapanmış — aktif ticaretin lehe çalıştığı bir pencere.",
]

ALPHA_FLAT = [
    "Alpha nötre yakın: botun getirisi ile coini yalnızca elde tutma senaryosu birbirine yakın seyretmiş; aktif ticaret bu pencerede belirgin bir avantaj veya dezavantaj yaratmamış.",
    "Alpha sıfıra yakın olduğundan, bot ile pasif tutma arasında kayda değer bir fark oluşmamış.",
    "Nötr alpha: aktif ticaret bu dönem ne öne geçirmiş ne geride bırakmış; sonuç benchmarkla başa baş.",
    "Bot, al-tut çizgisiyle hemen hemen aynı performansı vermiş — alpha nötr bölgede.",
    "Alpha dengede: gridlerin etkisi bu pencerede pasif tutmayla benzer bir noktada kalmış.",
    "Nötre yakın alpha, stratejinin bu ay piyasayla paralel hareket ettiğini gösteriyor.",
    "Bot ile benchmark arasındaki fark ihmal edilebilir düzeyde — alpha nötr.",
]

ALPHA_NEG = [
    "Alpha negatif: kapanan turlar USDT kârı üretmiş olsa da, oturum genelinde bot al-tut benchmarkının gerisinde kalmış. Bu bir zarar değil, bir fırsat maliyetidir: bu pencerede coini hiç işlem yapmadan tutmak daha yüksek getiri sağlayabilirdi.",
    "Negatif alpha, botun coini pasif tutmaya göre geride kaldığını gösterir; nakit kâr olsa bile coin tutmak bu dönem daha çok kazandırırdı (fırsat maliyeti).",
    "Alpha eksi: realize nakit pozitif olabilir, ancak bot al-tut benchmarkını yakalayamamış — bu bir kayıp değil, kaçırılan getiridir.",
    "Bu oturumda alpha negatif; yani aktif ticaret, coini sadece tutmaya kıyasla bu pencerede değer kaybettirmiş (fırsat maliyeti).",
    "Negatif alpha: bot kasayı büyütmüş olsa da benchmarkın gerisinde; özellikle yükselen piyasada gridlerin kârı erken alması bu farkı doğurabilir.",
    "Alpha eksiye işaret ediyor — coin tutmak bu dönem daha iyiydi. Nakit kâr gerçek, fakat fırsat maliyeti var.",
    "Bot al-tut çizgisinin altında kapanmış; alpha negatif olduğundan ayı 'coin tutmaktan iyi' diye okumamak gerekir.",
    "Negatif alpha, stratejinin bu pencerede piyasanın yukarı ivmesini tam yakalayamadığını gösterir; sonuç zarar değil, geride kalan getiridir.",
]


# =============================================================================
# 4) MARKET  (regime line / caveat / cross-conditions)
# =============================================================================

# Yön bildiren fiillerle MUTLAK değer ({price_abs}) kullanılır; işaretli
# {price_change} yalnız yön-nötr ifadelerde geçer (çifte-negatif olmasın diye).
MARKET_UP = [
    "Ay içinde kapanan turların ilk ve son kapanışına göre parite {price_abs} yükselmiş; bu geriye dönük okumayla ay **{regime}** sınıfına girdi.",
    "Kapanış fiyatları {price_abs} değer kazanmış; retrospektif okumayla ay **{regime}** görünümünde.",
    "Tur kapanışları arasında parite {price_abs} değerlenmiş — ay genel olarak **{regime}** karakterde.",
    "İlk-son kapanış karşılaştırması {price_abs} yükseliş gösteriyor; rejim etiketi **{regime}**.",
    "Bu ay fiyat {price_abs} yukarı yönlü hareket etti; geriye dönük sınıflandırma **{regime}**.",
    "Parite kapanışlar bazında {price_abs} artıda; ayın rejimi **{regime}** olarak değerlendirildi.",
    "Kapanışlar arasında {price_abs}'lik yukarı hareket var — ay **{regime}** geçti.",
]

MARKET_DOWN = [
    "Ay içinde kapanan turların kapanış fiyatları {price_abs} gerilemiş; bu retrospektif okumayla ayın rejimi **{regime}** olarak etiketlendi.",
    "Parite tur kapanışları arasında {price_abs} değer kaybetmiş — ay **{regime}** bir profil çizdi.",
    "Kapanış fiyatları {price_abs} düşmüş; geriye dönük sınıflandırma **{regime}**.",
    "İlk-son kapanış farkı {price_abs} düşüş gösteriyor; ay **{regime}** rejimine yerleşti.",
    "Bu ay fiyat {price_abs} geriledi; rejim etiketi **{regime}** olarak hesaplandı.",
    "Tur kapanışları {price_abs}'lik bir düşüşe işaret ediyor — ay **{regime}** karakterli.",
    "Parite {price_abs} aşağı yönlü kapanış üretmiş; ayın geriye dönük rejimi **{regime}**.",
]

MARKET_FLAT = [
    "Ay içinde kapanan turların kapanış fiyatları {price_abs} ile sınırlı hareket etmiş; bu retrospektif okumayla ay **{regime}** olarak etiketlendi.",
    "Parite tur kapanışları arasında yalnızca {price_abs} oynamış — ay büyük ölçüde **{regime}** geçti.",
    "Kapanış fiyatları {price_abs}'lik dar bir bantta kalmış; rejim **{regime}**.",
    "İlk-son kapanış farkı {price_change}; piyasa bu ay **{regime}** bir seyir izledi.",
    "Fiyat {price_abs} ile yatay sayılır bir aralıkta kaldı; rejim etiketi **{regime}**.",
    "Tur kapanışları {price_abs}'lik küçük bir değişim gösteriyor — ay **{regime}** karakterinde.",
    "Parite bu ay {price_change} ile nötr bir kapanış tablosu çizdi; rejim **{regime}**.",
]

MARKET_UNKNOWN = [
    "Ay içi fiyat karşılaştırması için yeterli kapanış fiyatı yok; piyasa rejimi bu ay net olarak sınıflandırılamadı.",
    "Yeterli kapanış verisi olmadığından bu ayın piyasa rejimi güvenle etiketlenemedi.",
    "Kapanış fiyatı azlığı nedeniyle ayın rejimi belirsiz kaldı; yorum nakit/envanter sonuçlarına dayanmalı.",
    "Rejim sınıflandırması için iki uçtan yeterli kapanış fiyatı bulunamadı — ay 'belirsiz' olarak işaretlendi.",
    "Bu ay piyasa rejimi hesaplanamadı; veri yetersizliği yorumun fiyat tarafını sınırlıyor.",
]

MARKET_CAVEAT = [
    "Önemli ayrım: buradaki rejim etiketi, botun canlı motorunun (dinamik mod) kullandığı teknik-indikatör rejimi DEĞİLDİR. Yalnızca ay içinde kapanan turların ilk ve son kapanış fiyatını karşılaştıran, raporlama amaçlı geriye dönük bir özettir.",
    "Not: bu rejim etiketi geriye dönük bir özettir — kapanış fiyatlarının ilk/son karşılaştırması. Botun canlı dinamik-mod rejimiyle (ATR/ADX/RSI temelli) karıştırılmamalıdır.",
    "Hatırlatma: rapordaki rejim, canlı motorun teknik rejimi değil; yalnızca ayın kapanış fiyatlarına bakan basit, geriye dönük bir sınıflandırmadır.",
    "Bu rejim okuması raporlama amaçlıdır ve kapanış-fiyatı temellidir; dinamik modun anlık indikatör rejimini temsil etmez.",
    "Dikkat: bu etiket, ay içi ilk ve son kapanışın kıyasından üretilir — botun gerçek-zamanlı rejim motorundan bağımsızdır.",
    "Bu sınıflandırma yalnızca tarihsel kapanış farkına dayanır; canlı dinamik-mod kararlarıyla doğrudan ilişkili değildir.",
    "Açıklama: rejim etiketi geçmişe bakan bir özet; botun o an hangi teknik rejimde işlem yaptığını göstermez.",
]

MARKET_UP_CASH_NEG = [
    "Coin yükselirken nakit bacak zayıf kalmış görünüyor; envanter turlarının tamamlanma hızı ya da grid aralığı, yukarı hareketin bir kısmını yakalayamamış olabilir.",
    "Fiyat artarken realize nakit eksiye dönmüş — bu, gridlerin yukarı ivmeyi tam karşılayamadığına işaret edebilir.",
    "Yükselen piyasada nakit tarafın geride kalması, kâr alımının erken veya grid aralığının dar olmasından kaynaklanabilir.",
    "Coin değer kazanırken nakit bacağın zayıflaması tipik olarak 'erken sat, geç geri al' baskısının işaretidir; grid aralığı gözden geçirilebilir.",
    "Parite yukarı giderken kasanın gerilemesi, envanter bacağının yeterince devreye girmediğini düşündürüyor.",
    "Yükselişte nakit zayıflığı: bot muhtemelen yükselişi nakde çevirirken coin biriktirme fırsatını ıskalamış olabilir.",
]

MARKET_DOWN_CASH_POS = [
    "Düşüş/yatay piyasada kademeli grid alımları ve trailing satışlar, bu stratejinin yapısal olarak güçlü olduğu profildir; aşağı yön turları bu ortamda tipik olarak daha verimli çalışır.",
    "Fiyat gerilerken nakit bacağın artıda olması beklenen ve sağlıklı bir sonuçtur — DCA + trailing tam da bu ortam için tasarlanmıştır.",
    "Düşüşte realize nakit kazancı, gridlerin dip alımlarını toparlanmada kâra çevirdiğini gösterir; stratejinin doğal sahası.",
    "Yatay/aşağı piyasada pozitif nakit, botun geri çekilmeleri verimli biçimde paraya çevirdiğine işarettir.",
    "Parite zayıfken kasanın büyümesi, kademeli alım ve iz-süren satış mekanizmasının iyi çalıştığının kanıtı.",
    "Düşen piyasada nakit bacağın güçlü olması, stratejinin en rahat ettiği koşulun yakalandığını gösterir.",
]


# =============================================================================
# 5) STRATEGY BALANCE
# =============================================================================

STRATEGY_CASH_HEAVY = [
    "Ağırlık aşağı/nakit bacakta: {cash_closed} nakit kapanışa karşı {inv_closed} envanter kapanışı. Bu, botun ay boyunca ağırlıklı olarak geri çekilme sonrası toparlanmaları USDT kârına çevirdiğini gösterir.",
    "Bu ay denge nakit tarafında ({cash_closed}/{inv_closed}); bot çoğunlukla 'dip al, toparlanmada sat' döngüsünü çalıştırmış.",
    "Nakit bacak baskın ({cash_closed} kapanış, envanter {inv_closed}); strateji ayı USDT realize ederek geçirmiş.",
    "Turların büyük kısmı nakit yönünde kapandı ({cash_closed}'e karşı {inv_closed}) — ay realize USDT odaklı işledi.",
    "Dağılım nakit ağırlıklı ({cash_closed}/{inv_closed}); botun ana kazanç kanalı bu ay USDT tarafı olmuş.",
    "Ağırlık aşağı yön turlarında ({cash_closed} nakit / {inv_closed} envanter); coin biriktirmeden çok kâr realize edilmiş.",
    "Nakit kapanışlar ({cash_closed}) envanteri ({inv_closed}) belirgin biçimde geçmiş; ay tek kanaldan, nakitten beslenmiş.",
]

STRATEGY_INV_HEAVY = [
    "Ağırlık yukarı/envanter bacakta: {inv_closed} envanter kapanışına karşı {cash_closed} nakit kapanış. Coin biriktirme veya yeniden alım bacağı bu ay daha belirleyici olmuş; ana kazanç USDT değil coin adedi tarafında.",
    "Bu ay denge envanter tarafında ({inv_closed}/{cash_closed}); bot ağırlıklı olarak 'tepe sat, ucuza geri al' ile coin biriktirmiş.",
    "Envanter bacak baskın ({inv_closed} kapanış, nakit {cash_closed}); kazanç bu ay coin adedinde okunmalı.",
    "Turların çoğu yukarı yönde kapandı ({inv_closed}'e karşı {cash_closed}) — ay coin biriktirme odaklı geçti.",
    "Dağılım envanter ağırlıklı ({inv_closed}/{cash_closed}); botun ana kanalı bu ay fazladan coin tutmak olmuş.",
    "Yukarı yön turları ({inv_closed}) nakit turlarını ({cash_closed}) geçmiş; sonuç USDT değil coin tarafında yoğunlaşıyor.",
    "Ağırlık envanter bacakta; bot bu ay USDT realize etmekten çok pozisyonun coin adedini büyütmüş.",
]

STRATEGY_BALANCED = [
    "Nakit ve envanter turları görece dengeli dağılmış ({cash_closed}/{inv_closed}); çift yönlü grid stratejisi ay içinde her iki yönü de kullanmış.",
    "Bu ay iki bacak da çalışmış ({cash_closed} nakit / {inv_closed} envanter); strateji hem USDT realize etmiş hem coin biriktirmiş.",
    "Denge sağlıklı ({cash_closed}/{inv_closed}); dual-grid mimarisi her iki yönde de sonuç üretmiş.",
    "Nakit ve envanter kapanışları yakın ({cash_closed}/{inv_closed}) — bot piyasanın iki yönünü de değerlendirmiş.",
    "İki kanal dengeli işledi ({cash_closed} nakit, {inv_closed} envanter); bu, grid yapısının tam kapasite çalıştığını gösterir.",
    "Bacak dağılımı dengede ({cash_closed}/{inv_closed}); ne nakit ne envanter tarafı baskın, ikisi birlikte katkı verdi.",
    "Hem aşağı hem yukarı yön turları üretilmiş ({cash_closed}/{inv_closed}); çift yönlü stratejinin ideal çalışma profili.",
]

STRATEGY_SINGLE_LEG = [
    "Envanter yönünde hiç kapanış olmadığından coin biriktirme / yeniden alım (re-entry) bacağı bu ay kapalı bir sonuç üretmemiş; strateji tek bacak ağırlıklı okunmalıdır.",
    "Tek bacak çalışmış: yalnızca {cash_closed} nakit kapanış var, envanter tarafı sessiz. Sonuç USDT üzerinden değerlendirilmeli.",
    "Bu ay gridin yalnız bir yarısı sonuç üretti; diğer bacak ya tetiklenmedi ya da kapanmadı — tek yönlü bir tablo.",
    "Envanter bacağı kapalı kaldığından strateji tek kanaldan çalıştı; bu, piyasanın tek yönlü hareketine veya grid yarısının atıl kalmasına işaret edebilir.",
    "Sonuçlar tek bacakta toplanmış; ikinci kanalın bu ay devreye girmemesi, grid aralığı veya piyasa yönü açısından kontrol edilebilir.",
    "Yalnızca bir bacak kapanış verdi; çift yönlü stratejinin tam potansiyeli bu ay kullanılmamış.",
]


# =============================================================================
# 6) FEES
# =============================================================================

FEES_TOTAL = [
    "Toplam komisyon maliyeti {total_fees} (nakit {fees}, envanter {inv_fees}). Komisyon pozitif kazanç değil; her alım-satımda borsaya ödenen ve brüt sonuçtan düşülen bir işlem maliyetidir.",
    "Ay genelinde {total_fees} komisyon ödenmiş ({fees} nakit + {inv_fees} envanter) — bu bir gider kalemidir, kazanca eklenmez, brüt sonuçtan düşülür.",
    "İşlem maliyeti toplamı {total_fees} ({fees}/{inv_fees}); komisyon kâr değil, net sonucu küçülten bir maliyettir.",
    "Komisyonlar bu ay {total_fees} tuttu (nakit {fees}, envanter {inv_fees}); raporlanan net rakam bu gider düşülmüş halidir.",
    "Toplam borsa komisyonu {total_fees} ({fees} + {inv_fees}); pozitif bir kalem değil, brütten çıkan maliyettir.",
    "Bu ayki komisyon yükü {total_fees} ({fees} nakit / {inv_fees} envanter) — net kâr bu tutar düşülerek hesaplanır.",
    "İşlem giderleri toplamı {total_fees}; komisyon kazanç değil, her emirde ödenen ve sonucu aşağı çeken maliyettir.",
]

FEES_PER_CYCLE = [
    "Tur başına ortalama komisyon maliyeti {fee_per_cycle}; raporlanan net sonuç, bu maliyet düşüldükten sonraki değerdir.",
    "Ortalama her tur {fee_per_cycle} komisyon üretmiş — net sonuçlar bu giderin ardından raporlanır.",
    "Tur başı maliyet {fee_per_cycle}; işlem sıklığı arttıkça bu kalemin toplamı da büyür.",
    "Kapanış başına ortalama {fee_per_cycle} komisyon ödenmiş; verimlilik bu maliyetin brüte oranıyla okunur.",
    "Tur başına {fee_per_cycle} komisyon — düşük tutulması net getiriyi doğrudan iyileştirir.",
    "Ortalama tur maliyeti {fee_per_cycle}; net rakamlar bu giderden arındırılmış değerlerdir.",
]

FEES_LOW = [
    "Komisyon yükü brüt kazanca oranla düşük kalmış; işlem profili verimli, kâr maliyete erimiyor.",
    "Maliyet/brüt oranı düşük — bot bu ay komisyonu verimli yönetmiş.",
    "Komisyonlar brüt kazancın küçük bir kısmı; bu, tur sıklığının dengeli olduğunu gösterir.",
    "Düşük komisyon oranı, stratejinin gereksiz işlem yapmadan kâr ürettiğine işaret eder.",
    "Komisyon tarafı verimli; brüt kazancın büyük kısmı net olarak kasada kalmış.",
    "İşlem maliyeti baskısı hafif — kâr-maliyet dengesi sağlıklı.",
]

FEES_HIGH = [
    "Komisyon yükü brüt kazancın belirgin bir kısmını götürmüş; tur sıklığı veya grid aralığı fazla agresif olabilir.",
    "Maliyet/brüt oranı yüksek — gridlerin çok sık tetiklenmesi net getiriyi baskılıyor olabilir.",
    "Komisyonlar brüt kazancın önemli bir bölümünü yemiş; grid aralığını biraz açmak verimliliği artırabilir.",
    "Yüksek komisyon oranı, işlem sıklığının kârı aşındırdığına işaret ediyor; parametreler gözden geçirilebilir.",
    "İşlem maliyeti baskısı belirgin; aynı kârı daha az işlemle üretmek net sonucu iyileştirir.",
    "Komisyon yükü dikkat çekici düzeyde — tur başına getiri ile maliyet dengesi izlenmeli.",
]

FEES_ZERO = [
    "Bu ay komisyon maliyeti oluşmamış; sonuç doğrudan brüt = net olarak okunabilir.",
    "Komisyon kalemi sıfır — net ve brüt rakamlar bu ay örtüşüyor.",
    "İşlem maliyeti kaydedilmemiş; raporlanan sonuç komisyon etkisinden bağımsızdır.",
    "Bu dönem komisyon gideri yok; net sonuç brüt ile aynı.",
    "Komisyon maliyeti görünmüyor — sonuçlar maliyet düşülmeden de aynı kalır.",
]


# =============================================================================
# 7) SUSTAINABILITY notes  (each factor, multiple phrasings)
# =============================================================================

SUSTAIN_NET_POS = [
    "Net nakit PnL pozitif: strateji, komisyonları karşıladıktan sonra ay içinde sermayeyi koruyarak büyütmüş.",
    "Realize nakit artıda; bot bu ay maliyetleri çıkardıktan sonra kasaya net katkı sağlamış.",
    "Pozitif net nakit, stratejinin sermayeyi koruyup üzerine koyduğunu gösteriyor.",
    "Net sonuç artıda — komisyon sonrası bile bot bu ay kazanç üretmiş.",
    "Nakit taraf pozitif kapandı; sermaye korunarak büyütülmüş.",
    "Net PnL pozitif: ayın realize tarafı sağlam bir temel sunuyor.",
]

SUSTAIN_NET_NEG = [
    "Net nakit PnL negatif: grid aralığı, başlangıç base/quote dağılımı veya piyasa yönü bu ay strateji lehine çalışmamış olabilir.",
    "Realize nakit eksiye dönmüş; piyasa yönü ya da grid parametreleri bu ay uyumsuz kalmış olabilir.",
    "Net sonuç negatif — komisyon ve piyasa birlikte aleyhe çalışmış görünüyor.",
    "Nakit taraf eksi kapandı; parametre ve volatilite uyumu gözden geçirilmeli.",
    "Net PnL negatif: tek başına alarm değil, ancak grid/bütçe ayarı kontrol edilmeli.",
    "Realize taraf bu ay kayıpta; yönelimin sürmesi halinde parametre revizyonu düşünülebilir.",
]

SUSTAIN_WINRATE_HIGH = [
    "Tur başarı oranı {winrate}: kapanışların büyük çoğunluğu kârlı/avantajlı sonuçlanmış.",
    "Yüksek başarı oranı ({winrate}) — turların neredeyse tamamı artıda kapanmış.",
    "Kazanan tur oranı {winrate}; tutarlılık güçlü, kayıplar istisna kalmış.",
    "{winrate} başarı oranı, stratejinin kapanışları güvenle kâra çevirdiğini gösterir.",
    "Tutarlılık yüksek: turların {winrate}'i kârlı sonuçlanmış.",
    "Başarı oranı {winrate} ile güçlü; bu, grid/trailing eşiklerinin iyi konumlandığına işaret eder.",
]

SUSTAIN_WINRATE_LOW = [
    "Tur başarı oranı {winrate}: zararlı kapanışlar baskın; grid ve trailing eşikleri gözden geçirilmeli.",
    "Düşük başarı oranı ({winrate}) — turların önemli kısmı kayıpla kapanmış.",
    "Kazanan tur oranı {winrate}; tutarlılık zayıf, eşikler yeniden değerlendirilmeli.",
    "{winrate} başarı oranı, kapanışların kâra dönüş kalitesinde sorun olabileceğini gösteriyor.",
    "Tutarlılık düşük: turların yalnızca {winrate}'i artıda; parametre revizyonu düşünülebilir.",
    "Başarı oranı {winrate} ile zayıf; grid aralığı veya trailing mesafesi gözden geçirilmeli.",
]

SUSTAIN_FEE_LOW = [
    "Komisyon yükü brüt kazancın küçük bir kısmı; işlem profili verimli, kâr komisyona erimiyor.",
    "Düşük komisyon oranı verimli bir işlem profiline işaret ediyor.",
    "Maliyet tarafı hafif; brütün büyük kısmı net olarak korunmuş.",
    "Komisyon/brüt oranı düşük — sürdürülebilirlik açısından olumlu bir sinyal.",
    "İşlem maliyeti baskısı az; bu, tempo ile getiri dengesinin iyi olduğunu gösterir.",
]

SUSTAIN_FEE_HIGH = [
    "Komisyon yükü brüt kazancın belirgin bir kısmını götürmüş; tur sıklığı veya grid aralığı fazla agresif olabilir.",
    "Yüksek komisyon oranı, işlem sıklığının kârı aşındırdığını düşündürüyor.",
    "Maliyet/brüt oranı yüksek — gridleri biraz açmak sürdürülebilirliği iyileştirebilir.",
    "Komisyon baskısı belirgin; aynı getiriyi daha az işlemle üretmek hedeflenebilir.",
    "İşlem maliyeti yüksek seyrediyor; net getiri bu kalemden olumsuz etkileniyor.",
]

SUSTAIN_DUAL = [
    "Hem aşağı (nakit) hem yukarı (envanter) bacak tur üretmiş; çift yönlü grid dengesi bu ay korunmuş.",
    "İki bacak da çalışmış — dual-grid mimarisi tam kapasite işlemiş, bu sürdürülebilirlik için olumlu.",
    "Nakit ve envanter kanallarının ikisi de sonuç verdi; dengeli kullanım sağlıklı bir profildir.",
    "Çift yönlü çalışma korunmuş; bu, stratejinin piyasanın her iki yönünü de değerlendirdiğini gösterir.",
    "Her iki bacağın aktif olması, grid yapısının dengeli ve verimli kullanıldığına işaret eder.",
]

SUSTAIN_SINGLE = [
    "Sonuçlar tek bacakta yoğunlaşmış; ya piyasa tek yönlü hareket etmiş ya da gridin diğer yarısı bu ay atıl kalmış olabilir.",
    "Tek kanal baskın — diğer bacağın sessizliği, grid aralığı veya piyasa yönü açısından kontrol edilebilir.",
    "Gridin yalnız bir yarısı çalışmış; çift yönlü potansiyel bu ay tam kullanılmamış.",
    "Sonuç tek yönlü; bu durum kalıcılaşırsa grid parametreleri gözden geçirilebilir.",
    "Tek bacakta yoğunlaşma var; dengeyi geri getirmek için karşı bacağın neden tetiklenmediği incelenebilir.",
]

SUSTAIN_ALPHA_POS = [
    "Oturum alpha {alpha}: bot, al-tut karşılaştırmasının üzerine ek getiri üretmiş.",
    "Pozitif alpha ({alpha}) sürdürülebilirliği destekliyor — aktif ticaret değer katmış.",
    "Alpha {alpha} ile benchmark üstü; strateji piyasayla uyumlu çalışıyor.",
    "Oturum alpha'sı {alpha}; bu, botun pasif tutmaya kıyasla öne geçtiğini gösteriyor.",
    "Pozitif alpha ({alpha}), mevcut yapılandırmanın koşullara uygun olduğuna işaret eder.",
]

SUSTAIN_ALPHA_NEG = [
    "Oturum alpha {alpha}: nakit turlar kârlı olsa da bot al-tut benchmarkının gerisinde; bu bir fırsat maliyetidir.",
    "Negatif alpha ({alpha}) — realize kâr olsa bile coin tutmak bu pencerede daha iyiydi.",
    "Alpha {alpha} ile benchmarkın altında; sürdürülebilirlik açısından izlenmesi gereken bir sinyal.",
    "Oturum alpha'sı {alpha}; bot kasayı büyütse de pasif tutmanın gerisinde kalmış.",
    "Negatif alpha ({alpha}), stratejinin yükseliş ivmesini tam yakalayamadığına işaret edebilir.",
]

SUSTAIN_ALPHA_FLAT = [
    "Oturum alpha {alpha} ile nötre yakın; realize nakit sonuç ile al-tut benchmarkı belirgin biçimde ayrışmamış.",
    "Alpha {alpha} — bot ile pasif tutma arasında kayda değer fark yok.",
    "Nötr alpha ({alpha}); strateji bu ay benchmarkla paralel seyretmiş.",
    "Oturum alpha'sı {alpha} ile dengede; aktif ticaret ne öne geçirmiş ne geride bırakmış.",
    "Alpha {alpha} nötr bölgede; sonuç benchmarkla başa baş okunabilir.",
]


# =============================================================================
# 8) OUTLOOK
# =============================================================================

OUTLOOK_STRONG_ALPHA_NEG = [
    "Kapanmış turlar operasyonel olarak kârlı; ancak alpha negatif olduğundan bu ay 'coin tutmaktan daha iyi' diye okunmamalı. Öncelikle grid aralığı, başlangıç base/quote dağılımı ve yukarı/envanter bacağın neden kapanmadığı incelenmeli — özellikle yükselen piyasada nakit bacağın kârı fazla erken alıp almadığı kontrol edilmeli.",
    "Sonuçlar sağlam ama alpha negatif; bu yüzden ayı benchmark karşısında bir zafer gibi okumamak gerekir. Grid aralığı ve kâr-alma eşiğinin yükselişi yeterince yakalayıp yakalamadığı gözden geçirilebilir.",
    "Realize taraf güçlü, fakat benchmark gerisinde kalınmış. Bir sonraki ay için grid aralığını ve envanter bacağının tetiklenme koşullarını incelemek en yüksek getiriyi sağlar.",
    "Operasyonel kârlılık iyi; negatif alpha ise kâr-alımının erken olabileceğini düşündürüyor. Kâr-alma eşiğini biraz genişletmek yükseliş yakalama oranını artırabilir.",
    "Tablo kârlı ama benchmarkın altında; öncelik, yükselen piyasada coin biriktirme bacağının neden devreye girmediğini anlamak olmalı.",
    "Güçlü bir realize performans, zayıf bir benchmark sonucu. Grid/dağılım ayarları, yukarı ivmeden daha fazla pay almaya yönelik kalibre edilebilir.",
]

OUTLOOK_STRONG = [
    "Mevcut tempo sürdürülebilir görünüyor; grid parametrelerini agresif biçimde değiştirmeden mevcut yapılandırmayla izlemeye devam edilebilir.",
    "Profil sağlam — acele bir parametre değişikliği gerekmiyor; mevcut kurulumla izlemeye devam etmek mantıklı.",
    "Sonuçlar güçlü ve dengeli; strateji mevcut haliyle korunup yakından gözlenebilir.",
    "Ay olumlu kapandı; yapılandırmayı bozmadan sürdürmek ve bir sonraki ayla karşılaştırmak en sağlıklısı.",
    "Performans tutarlı görünüyor; gereksiz müdahaleden kaçınıp mevcut tempoyu izlemek yeterli.",
    "Güçlü bir ay; mevcut grid ve dağılım ayarları işe yarıyor, korunmaları önerilir.",
]

OUTLOOK_MEDIUM = [
    "Performans karışık bir profil çiziyor; önümüzdeki ay tur başına net getiri, komisyon oranı ve bacak dengesi yakından izlenmeli.",
    "Sonuçlar orta bantta; net getiri/komisyon dengesi ve bacak dağılımı bir sonraki ayda dikkatle takip edilmeli.",
    "Karışık bir tablo — güçlü ve zayıf yanlar bir arada; küçük, ölçülü ayarlamalarla iyileştirme denenebilir.",
    "Profil nötr-pozitif arası; acele karar yerine bir ay daha veri toplayıp eğilimi görmek doğru olur.",
    "Orta seviye performans; komisyon oranı ve win-rate önümüzdeki dönemde anahtar göstergeler olacak.",
    "Tablo dengeli ama belirsiz; parametreleri sabit tutup trendi gözlemlemek en bilgilendirici yol.",
]

OUTLOOK_WEAK = [
    "Zayıf ay profili; grid aralığı, bütçe veya piyasa volatilitesi gözden geçirilmeli. Tek bir kötü ay başlı başına strateji iptali gerektirmez, ancak üst üste iki zayıf ay net bir risk işaretidir.",
    "Performans zayıf; grid aralığı ve bütçe dağılımı incelenmeli. Bir kötü ay normaldir, fakat eğilim sürerse müdahale gerekir.",
    "Sonuçlar tatmin edici değil; volatilite uyumu ve grid parametreleri kontrol edilmeli — tek ayla panik yapılmamalı ama ikinci zayıf ay ciddiye alınmalı.",
    "Zayıf bir dönem; piyasa koşulları stratejiye uymamış olabilir. Parametre revizyonu için bir ay daha izlemek, sonra karar vermek mantıklı.",
    "Ay olumsuz kapandı; grid/bütçe ayarları gözden geçirilmeli. Üst üste iki zayıf ay, yapılandırmanın yeniden ele alınmasını gerektirir.",
    "Düşük performanslı bir ay; tek başına strateji değişimi değil, ama yakın izleme ve olası kalibrasyon gerektirir.",
]

OUTLOOK_ALPHA_NEG_REMINDER = [
    "Hatırlatma: negatif alpha, nakit kârın kötü olduğu anlamına gelmez; yalnızca botun aynı sermayeyle coini hiç işlem yapmadan tutma alternatifine göre bu pencerede daha düşük getiri verdiğini gösterir.",
    "Not: alpha negatifliği bir zarar değil; coini pasif tutmanın bu dönem daha kazançlı olacağı anlamına gelen bir fırsat maliyetidir.",
    "Önemli: negatif alpha realize kârı geçersiz kılmaz; sadece benchmarka göre geride kalındığını söyler.",
    "Hatırlatma: alpha karşılaştırmalı bir ölçüdür; eksi olması botun para kaybettiği değil, daha iyisinin mümkün olduğu anlamına gelir.",
    "Not: negatif alpha, stratejinin yanlış olduğunu değil, bu pencerede piyasanın pasif tutmayı ödüllendirdiğini gösterir.",
    "Hatırlatma: kasada artı varken alpha eksi olabilir — bu ikisi çelişmez, biri mutlak biri göreli getiridir.",
]

OUTLOOK_ALPHA_POS_NOTE = [
    "Oturum alpha pozitif; bot, al-tut alternatifine göre fazladan getiri üretiyor — mevcut yapılandırma piyasa koşullarıyla uyumlu çalışıyor.",
    "Pozitif alpha, aktif ticaretin bu dönem coin tutmayı geçtiğini doğruluyor; kurulum koşullarla örtüşüyor.",
    "Alpha artıda — strateji yalnızca kâr etmiyor, benchmarkı da geçiyor; bu, ayar-piyasa uyumunun işareti.",
    "Bot benchmark üstünde; mevcut grid ve dağılım, piyasanın bu rejiminde değer üretiyor.",
    "Pozitif alpha, yapılandırmayı bozmadan sürdürmek için güçlü bir gerekçe sunuyor.",
]


# =============================================================================
# 9) CYCLE (per-tur) — leads always start with "Tur #{cid}" and carry the figures
# =============================================================================

CYCLE_BUY_PROFIT = [
    "Tur #{cid} (aşağı yön — nakit turu) kârla kapandı: brüt {gross_c}, komisyon {fees_c}, net {net_c}.",
    "Tur #{cid} aşağı/nakit bacakta net {net_c} kazançla sonuçlandı (brüt {gross_c}, komisyon {fees_c}).",
    "Tur #{cid} nakit yönünde artıda kapandı — brüt {gross_c}, maliyet {fees_c}, net {net_c}.",
    "Tur #{cid} (nakit turu) USDT kârıyla tamamlandı: net {net_c} (brüt {gross_c}, komisyon {fees_c}).",
    "Tur #{cid} dip alımlarını net {net_c} kâra çevirmiş (brüt {gross_c}, {fees_c} komisyon).",
    "Tur #{cid} aşağı yön turu kârlı: brüt {gross_c}'ten {fees_c} komisyon sonrası net {net_c}.",
    "Tur #{cid} (nakit) pozitif kapandı; realize net {net_c}, brüt {gross_c}, maliyet {fees_c}.",
    "Tur #{cid} nakit bacakta {net_c} net getiri sağladı (brüt {gross_c} − komisyon {fees_c}).",
]

CYCLE_BUY_LOSS = [
    "Tur #{cid} (aşağı yön — nakit turu) zararla kapandı: brüt {gross_c}, komisyon {fees_c}, net {net_c}.",
    "Tur #{cid} nakit yönünde eksiye döndü — brüt {gross_c}, maliyet {fees_c}, net {net_c}.",
    "Tur #{cid} (nakit turu) net {net_c} ile kayıpta kapandı (brüt {gross_c}, komisyon {fees_c}).",
    "Tur #{cid} aşağı yön turu zararlı: brüt {gross_c}'ten {fees_c} komisyon sonrası net {net_c}.",
    "Tur #{cid} nakit bacakta {net_c} net kayıp üretti (brüt {gross_c}, {fees_c} komisyon).",
    "Tur #{cid} (nakit) negatif kapandı; realize net {net_c}, brüt {gross_c}, maliyet {fees_c}.",
]

CYCLE_SELL_PROFIT = [
    "Tur #{cid} (yukarı yön — envanter turu) avantajla kapandı: {inv_c} {base} ek coin.",
    "Tur #{cid} envanter yönünde {inv_c} {base} fazladan coin kazandırdı.",
    "Tur #{cid} (envanter turu) coin adedini {inv_c} {base} artırarak tamamlandı.",
    "Tur #{cid} yukarı bacakta {inv_c} {base} net coin avantajı üretti.",
    "Tur #{cid} 'tepe sat - ucuza geri al' döngüsüyle {inv_c} {base} ek coin sağladı.",
    "Tur #{cid} (envanter) pozitif kapandı; elde tutulan coin {inv_c} {base} arttı.",
]

CYCLE_SELL_LOSS = [
    "Tur #{cid} (yukarı yön — envanter turu) dezavantajla kapandı: {inv_c} {base} coin.",
    "Tur #{cid} envanter yönünde {inv_c} {base} ile coin adedi tarafında kayıp üretti.",
    "Tur #{cid} (envanter turu) coin avantajı sağlayamadı: {inv_c} {base}.",
    "Tur #{cid} yukarı bacakta {inv_c} {base} net coin değişimiyle eksiye kapandı.",
    "Tur #{cid} (envanter) negatif kapandı; coin adedi tarafı {inv_c} {base} geriledi.",
]

CYCLE_MECH_PROFIT_SELL = [
    "Mekanizma: fiyat geri çekilirken kademeli (DCA) alınan grid pozisyonu, toparlanma sırasında trailing kâr-satışıyla kapatıldı; kazanç doğrudan USDT olarak realize edildi.",
    "İşleyiş: dipte biriktirilen pozisyon, fiyat dönünce iz-süren satışla bozuldu ve kâr USDT'ye çevrildi.",
    "Bu tur, geri çekilmede alınan gridlerin toparlanmada trailing ile satılmasıyla kapandı — sonuç nakit kâr.",
    "Mekanizma özeti: kademeli alım + toparlanmada trailing satış = realize USDT kazancı.",
    "Fiyat düşerken alınan, yükselişte iz-sürerek satılan klasik nakit döngüsü tamamlandı.",
    "Pozisyon dipte kuruldu, dönüşte trailing kâr-satışıyla nakde çevrildi.",
    "İşleyiş: DCA alımları toparlanmada trailing satışla kapanıp USDT kârı olarak gerçekleşti.",
]

CYCLE_MECH_REENTRY = [
    "Mekanizma: yüksekten yapılan satışın ardından trailing ile daha düşük seviyeden yeniden alım (re-entry) tamamlandı; kazanç USDT olarak değil, aynı sermayeyle elde tutulan fazladan coin adedi olarak ölçülür.",
    "İşleyiş: tepede satıldı, geri çekilmede iz-sürerek daha ucuza geri alındı; sonuç fazladan coin.",
    "Bu tur, yüksek satış + düşük geri alım döngüsüyle kapandı — kazanç coin adedinde, nakitte değil.",
    "Mekanizma özeti: tepe satışı + trailing re-entry = elde tutulan coin miktarında artış.",
    "Fiyat yüksekken satılan, düşüşte iz-sürerek geri alınan envanter döngüsü tamamlandı.",
    "Pozisyon tepede nakde çevrildi, dönüşte daha ucuza geri kuruldu; fark coin adedine yazıldı.",
    "İşleyiş: satış sonrası trailing re-entry ile aynı sermayeye daha fazla coin düştü.",
]

CYCLE_BUY_NEUTRAL = [
    "Tur #{cid} (aşağı yön — nakit turu) başa baş kapandı: brüt {gross_c}, komisyon {fees_c}, net {net_c}.",
    "Tur #{cid} nakit yönünde nötr sonuçlandı — brüt {gross_c}, komisyon {fees_c}, net {net_c}.",
    "Tur #{cid} (nakit turu) kâr-zarar üretmeden kapandı: net {net_c} (brüt {gross_c}, komisyon {fees_c}).",
    "Tur #{cid} aşağı yön turu başa baş: brüt {gross_c}, maliyet {fees_c}, net {net_c}.",
    "Tur #{cid} nakit bacakta nötr kapandı (net {net_c}); brüt {gross_c}, komisyon {fees_c}.",
]

CYCLE_SELL_NEUTRAL = [
    "Tur #{cid} (yukarı yön — envanter turu) nötr kapandı: coin adedinde net değişim {inv_c} {base}.",
    "Tur #{cid} envanter yönünde başa baş — kayda değer coin avantajı oluşmadı ({inv_c} {base}).",
    "Tur #{cid} (envanter turu) coin adedini neredeyse değiştirmeden kapandı: {inv_c} {base}.",
    "Tur #{cid} yukarı bacakta nötr sonuç verdi ({inv_c} {base}).",
]

CYCLE_MECH_BUY_GENERIC = [
    "İşleyiş: aşağı yön (nakit) bacağı kapandı; sonuç USDT tarafında realize edildi.",
    "Mekanizma: kademeli alım pozisyonu nakit tarafında kapatıldı.",
    "Bu tur nakit bacakta kapandı; sonuç USDT cinsinden ölçülür.",
    "İşleyiş: aşağı yön döngüsü tamamlandı, sonuç realize USDT olarak yazıldı.",
    "Mekanizma: nakit bacak kapanışı — pozisyon USDT'ye çevrildi.",
]

CYCLE_MECH_SELL_GENERIC = [
    "İşleyiş: yukarı yön (envanter) bacağı kapandı; sonuç coin adedi tarafında oluştu.",
    "Mekanizma: envanter döngüsü tamamlandı; sonuç coin adedinde ölçülür.",
    "Bu tur envanter bacakta kapandı; sonuç USDT değil coin cinsindendir.",
    "İşleyiş: yukarı yön kapanışı — etki elde tutulan coin miktarına yansıdı.",
    "Mekanizma: envanter bacak kapanışı; sonuç coin adedinde görüldü.",
]

CYCLE_DUR_SHORT = [
    "Tur kısa sürdü (≈ {dur_h} saat); hızlı bir geri çekilme-toparlanma döngüsü yakalanmış.",
    "Yaklaşık {dur_h} saatlik kısa bir tur — piyasa hızlı dönmüş.",
    "Tur ≈ {dur_h} saatte kapandı; çevik bir kapanış profili.",
    "Kısa tur (≈ {dur_h} saat); döngü hızlı tamamlanmış.",
    "Yaklaşık {dur_h} saat sürdü — kısa ve verimli bir kapanış.",
]

CYCLE_DUR_LONG = [
    "Tur uzun sürdü (≈ {dur_h} saat); pozisyon kapanış koşulunu sabırla beklemiş.",
    "Yaklaşık {dur_h} saatlik uzun bir tur — kapanış için piyasanın dönmesi beklenmiş.",
    "Tur ≈ {dur_h} saatte kapandı; sabır gerektiren, uzun soluklu bir döngü.",
    "Uzun tur (≈ {dur_h} saat); pozisyon hedefine ulaşana dek taşınmış.",
    "Yaklaşık {dur_h} saat sürdü — kapanış koşulu geç oluşmuş, sabırlı bir tur.",
]


# =============================================================================
# Registry + selector
# =============================================================================

TEMPLATES: Dict[str, List[str]] = {}
# Headline sub-categories are flattened with a "headline." prefix.
for _k, _v in HEADLINE.items():
    TEMPLATES[f"headline.{_k}"] = _v
TEMPLATES.update(
    {
        "summary_intro": SUMMARY_INTRO,
        "summary_cash": SUMMARY_CASH,
        "summary_inv_present": SUMMARY_INV_PRESENT,
        "summary_inv_neg": SUMMARY_INV_NEG,
        "summary_inv_absent": SUMMARY_INV_ABSENT,
        "summary_cash_inv_led": SUMMARY_CASH_INV_LED,
        "alpha_def": ALPHA_DEF,
        "alpha_pos": ALPHA_POS,
        "alpha_flat": ALPHA_FLAT,
        "alpha_neg": ALPHA_NEG,
        "market_up": MARKET_UP,
        "market_down": MARKET_DOWN,
        "market_flat": MARKET_FLAT,
        "market_unknown": MARKET_UNKNOWN,
        "market_caveat": MARKET_CAVEAT,
        "market_up_cash_neg": MARKET_UP_CASH_NEG,
        "market_down_cash_pos": MARKET_DOWN_CASH_POS,
        "strategy_cash_heavy": STRATEGY_CASH_HEAVY,
        "strategy_inv_heavy": STRATEGY_INV_HEAVY,
        "strategy_balanced": STRATEGY_BALANCED,
        "strategy_single_leg": STRATEGY_SINGLE_LEG,
        "fees_total": FEES_TOTAL,
        "fees_per_cycle": FEES_PER_CYCLE,
        "fees_low": FEES_LOW,
        "fees_high": FEES_HIGH,
        "fees_zero": FEES_ZERO,
        "sustain_net_pos": SUSTAIN_NET_POS,
        "sustain_net_neg": SUSTAIN_NET_NEG,
        "sustain_winrate_high": SUSTAIN_WINRATE_HIGH,
        "sustain_winrate_low": SUSTAIN_WINRATE_LOW,
        "sustain_fee_low": SUSTAIN_FEE_LOW,
        "sustain_fee_high": SUSTAIN_FEE_HIGH,
        "sustain_dual": SUSTAIN_DUAL,
        "sustain_single": SUSTAIN_SINGLE,
        "sustain_alpha_pos": SUSTAIN_ALPHA_POS,
        "sustain_alpha_neg": SUSTAIN_ALPHA_NEG,
        "sustain_alpha_flat": SUSTAIN_ALPHA_FLAT,
        "outlook_strong_alpha_neg": OUTLOOK_STRONG_ALPHA_NEG,
        "outlook_strong": OUTLOOK_STRONG,
        "outlook_medium": OUTLOOK_MEDIUM,
        "outlook_weak": OUTLOOK_WEAK,
        "outlook_alpha_neg_reminder": OUTLOOK_ALPHA_NEG_REMINDER,
        "outlook_alpha_pos_note": OUTLOOK_ALPHA_POS_NOTE,
        "cycle_buy_profit": CYCLE_BUY_PROFIT,
        "cycle_buy_loss": CYCLE_BUY_LOSS,
        "cycle_buy_neutral": CYCLE_BUY_NEUTRAL,
        "cycle_sell_profit": CYCLE_SELL_PROFIT,
        "cycle_sell_loss": CYCLE_SELL_LOSS,
        "cycle_sell_neutral": CYCLE_SELL_NEUTRAL,
        "cycle_mech_profit_sell": CYCLE_MECH_PROFIT_SELL,
        "cycle_mech_reentry": CYCLE_MECH_REENTRY,
        "cycle_mech_buy_generic": CYCLE_MECH_BUY_GENERIC,
        "cycle_mech_sell_generic": CYCLE_MECH_SELL_GENERIC,
        "cycle_dur_short": CYCLE_DUR_SHORT,
        "cycle_dur_long": CYCLE_DUR_LONG,
    }
)


class _SafeDict(dict):
    """str.format_map helper: missing placeholders render as '' instead of raising."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return ""


def _stable_index(seed: str, n: int) -> int:
    """Deterministic index in [0, n). Same seed → same pick (stable report)."""
    if n <= 0:
        return 0
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return int(digest, 16) % n


def pick(category: str, seed: str, inputs: Dict[str, Any]) -> str:
    """Select one filled template from `category`, deterministically by `seed`."""
    pool = TEMPLATES.get(category) or []
    if not pool:
        return ""
    idx = _stable_index(f"{seed}|{category}", len(pool))
    try:
        return pool[idx].format_map(_SafeDict(inputs or {}))
    except Exception:
        return pool[idx]


def pool_size() -> int:
    """Total number of templates in the permanent pool."""
    return sum(len(v) for v in TEMPLATES.values())
