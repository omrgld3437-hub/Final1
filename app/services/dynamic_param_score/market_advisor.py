"""Risk-first Turkish market advice derived from the production DPS V6 result.

This adapter intentionally does not generate or apply bot parameters.  It turns
the already calculated V6 regime, sub-profile and safety signals into a compact,
deterministic explanation for the temporary recommendation-only assistant UI.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower_blob(*values: Any) -> str:
    return " ".join(_text(value).lower() for value in values if value)


_REGIME_ADVICE: Dict[str, Dict[str, str]] = {
    "R1": {
        "tone": "positive",
        "title": "GÜÇLÜ YÜKSELİŞ EĞİLİMİ",
        "summary": (
            "Seçilen coinden elde edilen verilere göre yükseliş eğilimi güçlü. "
            "Trend devam edebilir; ancak yükselen fiyatın peşinden kontrolsüz alım "
            "yapılmaması gerekir."
        ),
        "action": "İşlem yapılabilir; coin ağırlığı kontrollü biçimde orta-yüksek tutulabilir.",
        "allocation": "Coin/USDT dağılımında yalnız motorun bu analiz için ürettiği kesin oran kullanılmalıdır.",
        "sell_grid": (
            "Satış gridlerinin yakın seviyelerde coin tüketmemesi için orta-uzak "
            "mesafeden başlaması; küçük miktardan büyük miktara doğru ilerlemesi önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin geri çekilmeyi bekleyecek şekilde orta-uzak kurulması; "
            "yakında küçük, derinde daha büyük miktar kullanılması önerilir."
        ),
    },
    "R2": {
        "tone": "neutral",
        "title": "DENGELİ PİYASA",
        "summary": (
            "Seçilen coinden elde edilen verilere göre piyasa belirgin bir yöne "
            "ayrışmıyor ve dengeli bir bant içinde hareket ediyor."
        ),
        "action": "Dengeli grid işlemi uygulanabilir; tek yöne aşırı ağırlık verilmemelidir.",
        "allocation": "Coin/USDT dengesi motorun bu analiz için ürettiği kesin orana göre kurulmalıdır.",
        "sell_grid": (
            "Satış gridlerinin yakın-orta mesafede, miktarların dengeli veya dış "
            "seviyelere doğru kademeli artacağı biçimde kurulması önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin yakın-orta mesafede, küçük miktardan başlayıp derin "
            "seviyelerde daha büyük miktara çıkması önerilir."
        ),
    },
    "R3": {
        "tone": "caution",
        "title": "KARARSIZ / SIKIŞAN PİYASA",
        "summary": (
            "Seçilen coinden elde edilen verilere göre yön teyidi zayıf ve piyasa "
            "sıkışma ya da gürültülü yatay hareket üretiyor. Kırılmanın yönü net değildir."
        ),
        "action": (
            "Motorun hesapladığı coin üst sınırı aşılmamalı; yön teyidi gelmeden "
            "yakın kademelerde agresif yeni alım yapılmamalıdır."
        ),
        "allocation": "Motorun bu analiz için ürettiği coin üst sınırı artırılmamalıdır.",
        "sell_grid": (
            "Satış gridlerinin yakın-orta mesafede ve ilk seviyelerde kontrollü "
            "miktarla başlaması; tek seviyede büyük satış yapılmaması önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin kademeli biçimde uzaklaştırılması; yakında küçük, "
            "derinde daha büyük miktar kullanılması önerilir."
        ),
    },
    "R4": {
        "tone": "danger",
        "title": "YÜKSEK DALGALANMA RİSKİ",
        "summary": (
            "Seçilen coinden elde edilen verilere göre fiyat iki yönde sert hareket "
            "edebilir. Dar gridler sık ve kötü zamanlanmış işlemlere yol açabilir."
        ),
        "action": (
            "Motorun hesapladığı coin/USDT dağılımı üst sınır kabul edilmeli; "
            "dar grid veya bunun üzerinde coin maruziyeti kullanılmamalıdır."
        ),
        "allocation": "Motorun bu analiz için ürettiği nakit rezervi azaltılmamalıdır.",
        "sell_grid": (
            "Satış gridlerinin orta-geniş aralığa yayılması; risk azaltmak için ilk "
            "satışların daha büyük, sonraki satışların daha küçük tutulması önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin normalden uzak kurulması; küçük miktardan başlayıp en "
            "derin seviyede en büyük miktara ulaşması önerilir."
        ),
    },
    "R5": {
        "tone": "positive",
        "title": "BREAKOUT / YUKARI MOMENTUM",
        "summary": (
            "Seçilen coinden elde edilen verilere göre yukarı kırılma veya güçlenen "
            "momentum görülüyor. Fırsat olumlu olsa da tepe fiyattan kovalamak risklidir."
        ),
        "action": "İşlem yapılabilir; yeni alımlar geri çekilmelere bölünmelidir.",
        "allocation": "Coin/USDT dağılımında motorun bu analiz için ürettiği kesin oran aşılmamalıdır.",
        "sell_grid": (
            "Satış gridlerinin trendi erken tüketmemek için orta-uzak mesafeden "
            "başlaması; küçük miktardan büyük miktara doğru ilerlemesi önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin fiyatı kovalamadan geri çekilmeyi beklemesi; yakında "
            "küçük, derinde daha büyük miktar kullanması önerilir."
        ),
    },
    "R6": {
        "tone": "caution",
        "title": "YAVAŞ TOPARLANMA",
        "summary": (
            "Seçilen coinden elde edilen verilere göre toparlanma işaretleri var; "
            "ancak yükseliş henüz güçlü ve kalıcı biçimde teyit edilmiş değil."
        ),
        "action": "Kademeli ve kontrollü işlem yapılabilir; nakit rezervi korunmalıdır.",
        "allocation": "Toparlanma teyidi değişmedikçe motorun kesin coin üst sınırı artırılmamalıdır.",
        "sell_grid": (
            "Satış gridlerinin orta mesafede ve ilk kademelerde daha yüksek miktarla "
            "başlayıp sonraki kademelerde küçülmesi önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin yakın seviyelerde küçük miktarla başlayıp derin "
            "geri çekilmelerde daha büyük miktara çıkması önerilir."
        ),
    },
    "R7": {
        "tone": "danger",
        "title": "DÜŞÜŞ EĞİLİMİ",
        "summary": (
            "Seçilen coinden elde edilen verilere göre düşüş eğilimi belirgin. "
            "Erken ve büyük alımlar pozisyon riskini hızla artırabilir."
        ),
        "action": (
            "Yeni işlem mümkünse ertelenmeli; işlem yapılacaksa motorun kesin coin "
            "üst sınırı aşılmamalı ve yakın seviyede agresif alım yapılmamalıdır."
        ),
        "allocation": "Düşüş yapısı bozulmadıkça motorun kesin coin üst sınırı artırılmamalıdır.",
        "sell_grid": (
            "Satış gridlerinin yakın-orta mesafede, büyük miktardan başlayıp sonraki "
            "seviyelerde daha küçük miktara inmesi önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin uzak kurulması; küçük miktardan başlayıp yalnız daha "
            "derin seviyelerde büyük miktara çıkması önerilir."
        ),
    },
    "R8": {
        "tone": "critical",
        "title": "SERT DÜŞÜŞ RİSKİ ÇOK YÜKSEK",
        "summary": (
            "Seçilen coinden elde edilen verilere göre SERT DÜŞÜŞ riski çok yüksek. "
            "Bu piyasada işlem yapılmaması kuvvetle önerilir."
        ),
        "action": (
            "İşlem zorunluysa toplam sermayenin yalnız çok küçük bir bölümü "
            "kullanılmalı ve yeni alımlar sınırlandırılmalıdır."
        ),
        "allocation": "Yalnız motorun sert düşüş profili için ürettiği kesin koruma oranı kullanılmalıdır.",
        "sell_grid": (
            "Satış gridlerinin mümkün olduğunca yakına kurulması; büyük miktardan "
            "başlayıp son seviyeye doğru daha küçük miktarla ilerlemesi önerilir."
        ),
        "buy_grid": (
            "Alım gridlerinin mümkün olduğunca uzağa kurulması; küçük miktardan "
            "başlayıp yalnız en derin seviyede daha büyük miktara çıkması önerilir."
        ),
    },
}


_LOW_LIQUIDITY = {
    "tone": "critical",
    "title": "LİKİDİTE / SPREAD RİSKİ ÇOK YÜKSEK",
    "summary": (
        "Seçilen coinde emir derinliği zayıf veya alış-satış fiyat farkı yüksek. "
        "Doğru yön tahmin edilse bile emirlerin beklenenden kötü fiyattan gerçekleşme riski vardır."
    ),
    "action": "Bu koşulda yeni bot açılmaması ve piyasanın izlenmesi kuvvetle önerilir.",
    "allocation": "İşlem zorunluysa coin oranı ve toplam sermaye kullanımı çok düşük tutulmalıdır.",
    "sell_grid": "Mevcut coin satılacaksa küçük limit emirler kullanılmalı; tek seferde büyük emir verilmemelidir.",
    "buy_grid": "Yeni alımlar kapalı tutulmalı; likidite normale dönmeden uzak gridler dahi etkinleştirilmemelidir.",
}


_PARABOLIC = {
    "tone": "critical",
    "title": "AŞIRI YÜKSELİŞ / GERİ ÇEKİLME RİSKİ",
    "summary": (
        "Seçilen coinden elde edilen verilere göre fiyat kısa sürede aşırı uzamış. "
        "Yükseliş sürse bile sert kâr satışı ve hızlı geri çekilme riski çok yüksektir."
    ),
    "action": (
        "Normal yeni alım yapılmaması; mevcut pozisyonda kâr ve risk azaltma "
        "yönetiminin öne alınması önerilir."
    ),
    "allocation": "Yalnız motorun parabolik risk profili için ürettiği kesin koruma oranı kullanılmalıdır.",
    "sell_grid": "Satış gridlerinin yakından başlaması; büyük miktardan daha küçük miktara doğru ilerlemesi önerilir.",
    "buy_grid": (
        "Normal alım gridleri kapalı tutulmalıdır. Motor çok uzak bir koruma/probe "
        "kademesi üretirse bu, yükselişi kovalayan yeni alım olarak yorumlanmamalıdır."
    ),
}


_OVEREXTENDED = {
    "tone": "danger",
    "title": "AŞIRI UZAMIŞ YÜKSELİŞ / GERİ DÖNÜŞ RİSKİ",
    "summary": (
        "Yukarı momentum sürüyor; ancak fiyat sağlıklı geri çekilme alanından "
        "uzaklaşmış. Bu profil parabolik işlem yasağı değildir, fakat yeni alım "
        "koşulları motor tarafından kısıtlanmıştır."
    ),
    "action": (
        "Yeni alımlar tamamen kapalı değildir; ancak fiyat piyasa emriyle "
        "kovalanmamalı ve yalnız motorun ürettiği geri çekilme kademeleri ile "
        "kesin coin üst sınırı kullanılmalıdır."
    ),
    "allocation": "Motorun kesin coin/USDT dağılımı artırılmadan kullanılmalıdır.",
    "sell_grid": "Satışlar riski erken azaltacak biçimde öndeki kademelere ağırlık vermelidir.",
    "buy_grid": (
        "Yeni alımlar tamamen kapalı değildir; yakın alım yerine yalnız motorun "
        "kısıtlı ve geri çekilmeye bölünmüş alım kademeleri kullanılmalıdır."
    ),
}


_DATA_BLOCKED = {
    "tone": "critical",
    "title": "GÜVENİLİR ÖNERİ İÇİN VERİ YETERSİZ",
    "summary": (
        "Seçilen coin için güncel veya tutarlı piyasa verisi yeterli değil. "
        "Bu durumda yön tahmini üretmek güvenli değildir."
    ),
    "action": "İşlem yapılmaması ve veri akışı düzeldikten sonra analizin yenilenmesi önerilir.",
    "allocation": "Veri doğrulanana kadar yeni coin pozisyonu açılmamalıdır.",
    "sell_grid": "Yeni satış planı oluşturulmamalı; mevcut açık emirler ayrıca kontrol edilmelidir.",
    "buy_grid": "Yeni alım gridleri etkinleştirilmemelidir.",
}


_DATA_LIMITED = {
    "tone": "caution",
    "title": "VERİ KAPSAMASI SINIRLI",
    "summary": (
        "Motor piyasa yapısını sınıflandırdı; ancak veri kapsamı tam değil. "
        "Bu nedenle sonuç normalden daha korumacı okunmalıdır."
    ),
    "action": (
        "Agresif işlem açılmaması; mümkünse veri kapsamı tamamlandıktan sonra "
        "analizin yenilenmesi önerilir."
    ),
    "allocation": "Motorun ürettiği dağılım üst sınır kabul edilmeli, artırılmamalıdır.",
    "sell_grid": "Satış planı yalnız risk azaltma ve referans amacıyla kullanılmalıdır.",
    "buy_grid": "Yeni alımlar küçük tutulmalı; yakın ve yüksek miktarlı alım yapılmamalıdır.",
}


_COOLDOWN = {
    "tone": "caution",
    "title": "YÜKSELİŞ İÇİNDE SOĞUMA / GERİ ÇEKİLME",
    "summary": (
        "Ana eğilim yukarı olsa da kısa vadeli momentum soğuyor. "
        "Bu aşamada yükselişi kovalamak yerine geri çekilme teyidi beklenmelidir."
    ),
    "action": "İşlem yapılabilir; fakat yeni alımlar küçük tutulmalı ve nakit rezervi korunmalıdır.",
    "allocation": "Momentum yeniden güçlenmeden motorun kesin coin üst sınırı artırılmamalıdır.",
    "sell_grid": "Satış gridlerinin orta mesafede ve dengeli miktarlarda kurulması önerilir.",
    "buy_grid": (
        "Alım gridlerinin geri çekilmeyi bekleyecek kadar uzakta, küçük miktardan "
        "başlayıp derinde büyüyecek şekilde kurulması önerilir."
    ),
}


_REGIME_FOLLOW_UP: Dict[str, Dict[str, str]] = {
    "R1": {
        "interpretation": "Yükselişi kovalamak yerine trendi koruyup yeni alımı geri çekilmelere bölmek gerekir.",
        "risk_control": "Aşırı ısınma, zayıflayan hacim veya likidite bozulmasında yeni alımlar durdurulmalıdır.",
        "invalidation": "Fiyat ana trend yapısının altına iner veya motor R6/R7/R8'e geçerse bu plan geçersizdir.",
    },
    "R2": {
        "interpretation": "Amaç yön tahmini değil, bant içindeki iniş ve çıkışları dengeli iki yönlü gridle yönetmektir.",
        "risk_control": "Tek yöne yüksek ağırlık verilmemeli; bant dışı hacimli kırılmada yakın gridler korunmamalıdır.",
        "invalidation": "Volatilite veya trend gücü belirgin değişirse yeni rejim analizi yapılmalıdır.",
    },
    "R3": {
        "interpretation": "Sıkışma hem fırsat hem kırılma riski taşır; küçük pozisyon ve nakit rezervi birlikte korunmalıdır.",
        "risk_control": "Kırılma yönü teyit edilmeden büyük ilk alım veya tek seviyede yüksek miktar kullanılmamalıdır.",
        "invalidation": "Hacim ve trend birlikte güçlenip fiyat sıkışma bandından çıkarsa analiz yenilenmelidir.",
    },
    "R4": {
        "interpretation": "Trend zayıfken dalgalanma yüksek; amaç yön tahmini değil, geniş kademelerle sert fitilleri yönetmektir.",
        "risk_control": "Dar grid, yüksek coin oranı ve yakın seviyede büyük alım sermayeyi erken tüketebilir.",
        "invalidation": "Bant aşağı trende dönüşürse R7/R8, hacimli yukarı kırılırsa R1/R5 planı gerekir.",
    },
    "R5": {
        "interpretation": "Yukarı momentum fırsat yaratır; fiyatı kovalamadan geri çekilmeleri kullanmak gerekir.",
        "risk_control": "Parabolik uzama veya sahte kırılmada yeni alım kapatılıp kâr koruma öne alınmalıdır.",
        "invalidation": "Kırılma seviyesi korunamaz, hacim söner veya momentum tersine dönerse plan geçersizdir.",
    },
    "R6": {
        "interpretation": "Toparlanma ihtimali var ama güçlü trend teyidi yok; pozisyon ancak teyit geldikçe artırılmalıdır.",
        "risk_control": "İlk tepki kalıcı dönüş sanılmamalı ve derin alımlar için nakit saklanmalıdır.",
        "invalidation": "Yeni dipte R7/R8, güçlü yükselen tepe-dip yapısında R1/R5 için analiz yenilenmelidir.",
    },
    "R7": {
        "interpretation": "Öncelik dip bulmak değil, coin maruziyetini azaltıp daha derin düşüş için nakdi korumaktır.",
        "risk_control": "Yakın ve büyük alım yerine küçük ve uzak kademeler kullanılmalıdır.",
        "invalidation": "Düşen tepe-dip yapısı bozulup fiyat trend üzerinde kalıcı olursa yeniden analiz gerekir.",
    },
    "R8": {
        "interpretation": "Bu rejimde amaç fırsat aramak değil sermayeyi korumaktır; işlem açmamak temel karardır.",
        "risk_control": (
            "Normal ve yakın yeni alımlar kapalı tutulmalıdır. Motor yalnız çok uzak "
            "bir koruma/probe kademesi üretirse bu normal alım planı sayılmamalıdır."
        ),
        "invalidation": "Birden fazla zaman diliminde toparlanma teyidi gelmeden korumacı karar gevşetilmemelidir.",
    },
}


_SUB_SCENARIO_OVERRIDES: Dict[str, Dict[str, str]] = {
    "R1_STD_PULLBACK": {
        "title": "YÜKSELİŞ TRENDİNDE GERİ ÇEKİLME",
        "summary": "Ana trend yukarı; kısa vadeli geri çekilme başlamış. Alımlar aşağı kademelere bölünmelidir.",
    },
    "R1_STD_TREND_COOLDOWN": {
        "title": "YÜKSELİŞ TRENDİNDE MOMENTUM SOĞUMASI",
        "summary": "Ana yön yukarı kalırken momentum zayıflıyor. Coin payı korunabilir; yeni alım için soğuma beklenmelidir.",
    },
    "R3_STD_CONTROLLED_COMPRESSION": {
        "title": "DÜŞÜK VOLATİLİTE SIKIŞMASI",
        "summary": "Fiyat dar alanda sıkışıyor. Kırılma yönü belli olmadığı için küçük pozisyon gerekir.",
    },
    "R3_STD_UPTREND_COMPRESSION": {
        "title": "YUKARI EĞİLİMLİ SIKIŞMA",
        "summary": "Ana yapı yukarı eğilimli fakat fiyat sıkışıyor; geri çekilme için nakit ayrılmalıdır.",
    },
    "R3_STD_UPTREND_OVERHEAT_COOLDOWN": {
        "title": "YÜKSELİŞTE AŞIRI ISINMA VE SOĞUMA",
        "summary": "Ana eğilim güçlü olsa da kısa vadeli göstergeler ısınma sonrası soğuyor; yeni alım aceleye getirilmemelidir.",
    },
    "R3_STD_UPPER_BAND_PROFIT_LOCK": {
        "title": "ÜST BANTTA KÂR KORUMA",
        "summary": "Fiyat üst bantta ve geri çekilme riski artmış; yeni alım yerine kârı korumak önceliklidir.",
        "action": "Motorun kesin coin sınırı artırılmamalı; yeni alımdan önce geri çekilme beklenmelidir.",
    },
    "R4_STD_LIQUID": {
        "title": "YÜKSEK DALGALANMALI, LİKİT ARALIK",
        "summary": "Fiyat iki yönde sert hareket ediyor; spread ve likidite yeterli. Geniş ve nakit ağırlıklı grid uygundur.",
        "action": "İki yönlü kontrollü grid kullanılabilir; motorun ayırdığı USDT rezervi korunmalıdır.",
    },
    "R4_DEF_OVERHEATED": {
        "title": "DALGALI PİYASADA AŞIRI ISINMA",
        "summary": "Dalgalanma yüksek ve fiyat üst bölgede ısınmış; yeni alım azaltılıp risk yönetimi öne alınmalıdır.",
    },
    "R4_RESTRICTED_UNSTABLE": {
        "title": "KARARSIZ VE KIRILGAN DALGALANMA",
        "summary": "Dalgalanma uygulama riski yaratıyor; pozisyon çok küçük ve alımlar uzak tutulmalıdır.",
        "action": "Motor bu profilde yeni alımları kısıtlar; yeni bot yerine izleme tercih edilmelidir.",
    },
    "R4_DEF_LOW_LIQUIDITY": _LOW_LIQUIDITY,
    "R4_ACT_LOWER_BAND_BOUNCE": {
        "title": "ALT BANTTAN KONTROLLÜ TEPKİ",
        "summary": "Dalgalı aralığın altından tepki ihtimali var; alım tek noktada değil kademeli yapılmalıdır.",
        "action": "Kontrollü işlem yapılabilir; pozisyon yalnız alt bant tepkisi teyit edildikçe kademeli artırılmalıdır.",
    },
    "R4_FRAGILE_BUT_LIQUID": {
        "title": "LİKİT FAKAT KIRILGAN DALGALANMA",
        "summary": "Emir koşulları iyi fakat coin yapısı kırılgan; likidite tek başına yüksek coin oranını haklı çıkarmaz.",
    },
    "R5_ACT_CLEAN_BREAKOUT": {
        "title": "TEMİZ YUKARI KIRILMA",
        "summary": "Fiyat, momentum ve yapı yukarı kırılmayı destekliyor; alımlar yine geri çekilmelere bölünmelidir.",
        "action": "İşlem yapılabilir; motorun kesin coin üst sınırı aşılmadan alımlar geri çekilmelere bölünmelidir.",
    },
    "R5_STD_POST_BREAKOUT_COOLDOWN": {
        "title": "KIRILMA SONRASI KONTROLLÜ SOĞUMA",
        "summary": "Yukarı kırılma sonrası momentum soğuyor; kırılma seviyesi korunmadan nakit tüketilmemelidir.",
        "action": "Motor yeni alımları kısıtlar; kırılma seviyesi korunmadan yakın veya toplu alım yapılmamalıdır.",
    },
    "R5_DEF_OVEREXTENDED": _OVEREXTENDED,
    "R5_DEF_PARABOLIC_OVEREXTENDED": _PARABOLIC,
    "R6_RECOVERY_BREAKOUT": {
        "title": "TOPARLANMA KIRILMASI",
        "summary": "Düşüş sonrası toparlanma yukarı kırılmayla güçleniyor; pozisyon yine kademeli artırılmalıdır.",
        "action": "Motor yeni alımları kısıtlar; kırılma korundukça yalnız kesin kademelerle ilerlenmelidir.",
        "interpretation": "Toparlanma kırılmayla teyit kazanıyor; fırsat izlenebilir fakat eski düşüş riski nedeniyle alım bölünmelidir.",
        "invalidation": "Kırılma seviyesi korunamaz ve fiyat yeniden düşen dip yapısına dönerse toparlanma planı geçersizdir.",
    },
    "R6_RECOVERY_ACT": {
        "title": "GÜÇLENEN TOPARLANMA",
        "summary": "Toparlanma birden fazla göstergede güçleniyor; coin payı kontrollü artırılabilir.",
        "interpretation": "Toparlanma aktif teyit almış durumda; motorun kesin dağılımı aşılmadan trend kademeli takip edilebilir.",
        "risk_control": "Teyit güçlü olsa da bütün nakit tek noktada kullanılmamalı ve geri çekilme kademeleri korunmalıdır.",
    },
    "R8_HARD_BLOCK": {
        **_REGIME_ADVICE["R8"],
        "title": "SERT DÜŞÜŞ — YENİ İŞLEM KAPALI",
        "summary": "Düşüş ve risk kapıları teknik engel oluşturuyor; grid yerine yalnız izleme yapılmalıdır.",
        "action": "Motor alım ve satış gridlerini kapatmıştır; yeni pozisyon veya bot açılmamalıdır.",
    },
    "R8_CAPITULATION_CONDITIONAL_PROBE": {
        **_REGIME_ADVICE["R8"],
        "title": "KAPİTÜLASYON / ÇOK DERİN DÜŞÜŞ",
        "summary": "Panik satışına benzeyen derin düşüş var; tepki ihtimaline rağmen normal bot açmak güvenli değildir.",
        "action": "Normal alım yapılmamalı; motorun çok uzaktaki koşullu probe kademesi yalnız küçük risk referansıdır.",
    },
    "R8_RECOVERY_RESTRICTED": {
        **_REGIME_ADVICE["R8"],
        "title": "SERT DÜŞÜŞ SONRASI SINIRLI TOPARLANMA",
        "summary": "İlk toparlanma işaretleri var fakat yapı güvenli değil; coin oranı düşük ve alımlar uzak kalmalıdır.",
        "action": "Toparlanma teyidi yetersizdir; yalnız motorun kısıtlı coin üst sınırı ve uzak alım kademeleri kullanılmalıdır.",
    },
    "R8_DEF_PANIC": _REGIME_ADVICE["R8"],
}

ADVICE_LIBRARY_VERSION = "dps-v6-tr-audited-2026.07.29"
ADVICE_LIBRARY_SCENARIOS = tuple(
    sorted(
        set(_REGIME_ADVICE)
        | set(_SUB_SCENARIO_OVERRIDES)
        | {
            "DATA_BLOCKED",
            "DATA_LIMITED",
            "LOW_LIQUIDITY",
            "PARABOLIC",
            "R1_COOLDOWN",
            "R3_COOLDOWN",
            "R5_COOLDOWN",
        }
    )
)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tr_number(value: Any, digits: int = 1) -> str:
    numeric = _number(value)
    if numeric is None:
        return "—"
    return f"{numeric:.{digits}f}".replace(".", ",")


def _format_volume(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return "—"
    if numeric >= 1_000_000_000:
        return f"{numeric / 1_000_000_000:.1f} milyar".replace(".", ",")
    if numeric >= 1_000_000:
        return f"{numeric / 1_000_000:.1f} milyon".replace(".", ",")
    return f"{numeric:,.0f}".replace(",", ".")


def _grid_shape(grids: Sequence[Mapping[str, Any]], side: str) -> str:
    if not grids:
        return (
            "Yeni alım gridleri kapalı."
            if side == "buy"
            else "Yeni satış gridleri kapalı."
        )
    quantities = [_number(grid.get("qty_pct")) or 0 for grid in grids]
    triggers = [_number(grid.get("trigger_pct")) or 0 for grid in grids]
    sign = "-" if side == "buy" else "+"
    ladder = " / ".join(
        f"{sign}%{_tr_number(trigger)} seviyede miktar %{_tr_number(quantity)}"
        for trigger, quantity in zip(triggers, quantities)
    )
    ascending = all(
        left <= right for left, right in zip(quantities, quantities[1:])
    )
    descending = all(
        left >= right for left, right in zip(quantities, quantities[1:])
    )
    if ascending and quantities[0] < quantities[-1]:
        logic = (
            "İlk kademede sermayeyi az kullanır; fiyat düştükçe alım miktarını artırır."
            if side == "buy"
            else "Yakın yükselişte az satar; fiyat daha güçlü yükseldikçe satış miktarını artırır."
        )
    elif descending and quantities[0] > quantities[-1]:
        logic = (
            "Yakın düşüşte daha büyük alır, derin kademelerde miktarı azaltır."
            if side == "buy"
            else "Riski erken azaltmak için ilk satışı büyük tutar, sonraki satışları küçültür."
        )
    else:
        logic = "Miktarlar piyasa yapısına göre dengeli ve kademeli dağıtılır."
    return f"{ladder}. {logic}"


def _engine_plan(result: Mapping[str, Any]) -> Dict[str, str]:
    config = _mapping(
        result.get("ui_config") or result.get("recommendation_config")
    )
    telemetry = _mapping(result.get("telemetry"))
    v6_final = _mapping(telemetry.get("v6_final"))
    profile = _mapping(v6_final.get("profile"))
    if not config and not profile:
        return {
            "status": "Motor yeni işlem için uygulanabilir plan üretmedi.",
            "allocation": "Motor uygulanabilir yeni parametre planı üretmedi.",
            "buy_ladder": "Yeni alım planı kapalı.",
            "sell_ladder": "Yeni satış planı kapalı.",
            "trailing": "Trailing planı yok.",
            "profit_cycle": "Kâr döngüsü kapalı.",
        }
    up = _mapping(config.get("up"))
    down = _mapping(config.get("down"))
    profit = _mapping(config.get("profit"))
    if config:
        buy_grids = [
            _mapping(grid)
            for grid in (down.get("grids") or [])
            if isinstance(grid, Mapping)
        ]
        sell_grids = [
            _mapping(grid)
            for grid in (up.get("grids") or [])
            if isinstance(grid, Mapping)
        ]
        base = _number(config.get("base_alloc_pct"))
        quote = _number(config.get("quote_alloc_pct"))
        ladder_display = _mapping(config.get("ladder_display"))
        sell_ladder_state = _text(
            ladder_display.get("sell_ladder_mode")
        ) or "active"
        buy_ladder_state = (
            "disabled" if bool(config.get("buy_disabled")) else "active"
        )
    else:
        buy_grids = [
            {
                "trigger_pct": abs(_number(grid.get("distance_pct")) or 0),
                "qty_pct": grid.get("amount_pct"),
            }
            for grid in (profile.get("buy_grids") or [])
            if isinstance(grid, Mapping)
        ]
        sell_grids = [
            {
                "trigger_pct": abs(_number(grid.get("distance_pct")) or 0),
                "qty_pct": grid.get("amount_pct"),
            }
            for grid in (profile.get("sell_grids") or [])
            if isinstance(grid, Mapping)
        ]
        base = _number(profile.get("base_allocation_pct"))
        quote = _number(profile.get("quote_allocation_pct"))
        sell_ladder_state = "active" if sell_grids else "disabled"
        buy_ladder_state = (
            "active"
            if bool(profile.get("normal_buy_enabled")) and buy_grids
            else "disabled"
        )
    allocation = (
        f"Coin %{_tr_number(base)} · USDT %{_tr_number(quote)}"
        if base is not None and quote is not None
        else "Dağılım üretilemedi."
    )
    buy_ladder = _grid_shape(buy_grids, "buy")
    sell_ladder = _grid_shape(sell_grids, "sell")
    if sell_ladder_state == "planned_inactive" and sell_grids:
        sell_ladder = (
            "Mevcut satılabilir coin olmadığı için bu satış kademeleri henüz aktif "
            f"değildir; coin edinildiğinde kullanılacak plan: {sell_ladder}"
        )
    return {
        "status": (
            "Motor bu planı teknik olarak uygulanabilir buldu."
            if result.get("deployable")
            else (
                "Motorun güvenlik profili referans olarak gösteriliyor; otomatik uygulama kapalıdır."
                if profile and not config
                else "Bu plan yalnız korumacı referanstır; otomatik uygulama kapalıdır."
            )
        ),
        "allocation": allocation,
        "buy_ladder": buy_ladder,
        "sell_ladder": sell_ladder,
        "buy_ladder_state": buy_ladder_state,
        "sell_ladder_state": sell_ladder_state,
        "trailing": (
            (
                f"Alış trailing %{_tr_number(down.get('trail_pct'))} · "
                f"satış trailing %{_tr_number(up.get('trail_pct'))}"
            )
            if config
            else "Trailing değerleri motorun güvenlik profilinde korunuyor."
        ),
        "profit_cycle": (
            (
                f"Satış sonrası geri alım tetiği %{_tr_number(profit.get('rebuy_trigger_pct'))}, "
                f"trailing %{_tr_number(profit.get('rebuy_trail_pct'))}; geri alım sonrası "
                f"kâr satışı tetiği %{_tr_number(profit.get('resell_trigger_pct'))}, "
                f"trailing %{_tr_number(profit.get('resell_trail_pct'))}."
            )
            if config
            else "Kâr döngüsü motorun güvenlik profiline göre sınırlandırılıyor."
        ),
    }


def _market_evidence(result: Mapping[str, Any]) -> List[str]:
    telemetry = _mapping(result.get("telemetry"))
    indicators = _mapping(telemetry.get("indicators"))
    evidence: List[str] = []
    adx = _number(indicators.get("adx_1h"))
    price_ema = _number(indicators.get("price_vs_ema200_pct"))
    if adx is not None:
        if adx >= 25:
            if price_ema is None:
                evidence.append(
                    f"1 saatlik ADX {_tr_number(adx)}: trend gücü belirgin; "
                    "EMA200 yön verisi bulunmadığı için yön tek başına ADX'ten çıkarılmıyor."
                )
            else:
                direction = (
                    "yukarı"
                    if price_ema > 0
                    else "aşağı"
                    if price_ema < 0
                    else "EMA200 sınırında"
                )
                evidence.append(
                    f"1 saatlik ADX {_tr_number(adx)} ve EMA200 konumu: "
                    f"{direction} yönde belirgin trend yapısı."
                )
        else:
            evidence.append(
                f"1 saatlik ADX {_tr_number(adx)}: güçlü tek yönlü trend teyit edilmiyor."
            )
    volatility = _number(indicators.get("volatility_percentile"))
    if volatility is not None:
        level = (
            "çok yüksek"
            if volatility >= 85
            else "yüksek"
            if volatility >= 65
            else "orta"
            if volatility >= 35
            else "düşük"
        )
        evidence.append(
            f"Volatilite yüzdeliği %{_tr_number(volatility)}: dalgalanma {level}."
        )
    rsi_5m = _number(indicators.get("rsi14_5m"))
    rsi_1h = _number(indicators.get("rsi14_1h"))
    if rsi_5m is not None and rsi_1h is not None:
        if (rsi_5m >= 70 and rsi_1h <= 30) or (
            rsi_1h >= 70 and rsi_5m <= 30
        ):
            state = "zaman dilimleri sert biçimde ayrışıyor"
        elif rsi_5m >= 70 or rsi_1h >= 70:
            state = "aşırı alım / ısınma riski var"
        elif rsi_5m <= 30 or rsi_1h <= 30:
            state = "aşırı satış baskısı var"
        else:
            state = "momentum nötr bölgede"
        evidence.append(
            f"RSI 5dk {_tr_number(rsi_5m)} · 1s {_tr_number(rsi_1h)}: {state}."
        )
    return_24h = _number(indicators.get("return_24h_pct"))
    drawdown_7d = _number(indicators.get("drawdown_7d_pct"))
    if return_24h is not None:
        evidence.append(
            f"24 saatlik değişim %{_tr_number(return_24h)}"
            + (
                f", 7 günlük tepe gerilemesi %{_tr_number(drawdown_7d)}."
                if drawdown_7d is not None
                else "."
            )
        )
    spread = _number(indicators.get("orderbook_spread_pct"))
    if spread is not None:
        volume = _number(indicators.get("quote_volume_24h"))
        if volume is None:
            volume = _number(result.get("volume_24h"))
        consistency = _number(indicators.get("volume_consistency"))
        if consistency is None:
            consistency = _number(result.get("volume_consistency"))
        safety = _safety_context(result)
        restricted = "low_liquidity" in safety
        if restricted:
            quality = "motor tarafından kısıtlı"
        elif (
            spread <= 0.03
            and volume is not None
            and volume >= 1_000_000
            and consistency is not None
            and consistency >= 0.45
        ):
            quality = "motorun likit coin eşiğiyle uyumlu"
        elif (
            spread < 0.10
            and volume is not None
            and volume >= 1_000_000
            and (consistency is None or consistency >= 0.35)
        ):
            quality = (
                "spread ve hacim yeterli; hacim sürekliliği verisi bekleniyor"
                if consistency is None
                else "yeterli"
            )
        else:
            quality = "zayıf veya eksik"
        evidence.append(
            f"Spread %{_tr_number(spread, 3)} ve 24s hacim "
            f"{_format_volume(volume)} USDT: "
            f"emir koşulları {quality}."
        )
    data_quality = _text(result.get("data_quality_display"))
    if data_quality:
        evidence.append(data_quality + ".")
    return evidence[:6]


def _scenario_fields(result: Mapping[str, Any]) -> tuple[str, str, str]:
    selection = _mapping(result.get("selection_telemetry"))
    v6_display = _mapping(selection.get("v6_display"))
    scenario = _mapping(v6_display.get("scenario_identity"))
    telemetry = _mapping(result.get("telemetry"))
    v6_final = _mapping(telemetry.get("v6_final"))
    final_scenario = _mapping(v6_final.get("scenario"))
    opportunity = _mapping(v6_final.get("opportunity_notes"))
    final_regime = _text(final_scenario.get("regime_id")).upper()
    selection_regime = _text(scenario.get("regime_id")).upper()
    regime = final_regime or selection_regime or _text(
        result.get("regime_tag")
    ).upper()
    if final_regime:
        hint = _text(
            final_scenario.get("sub_profile_hint")
            or opportunity.get("sub_profile_hint")
            or opportunity.get("semantic_role")
        ).upper()
        name = _text(final_scenario.get("label"))
    else:
        hint = _text(
            scenario.get("sub_profile_hint")
            or v6_display.get("sub_profile_hint")
            or opportunity.get("sub_profile_hint")
            or opportunity.get("semantic_role")
        ).upper()
        name = _text(scenario.get("name"))
    return regime, hint, name


def _safety_context(result: Mapping[str, Any]) -> str:
    telemetry = _mapping(result.get("telemetry"))
    v6_final = _mapping(telemetry.get("v6_final"))
    opportunity = _mapping(v6_final.get("opportunity_notes"))
    return _lower_blob(
        opportunity.get("semantic_role"),
        opportunity.get("sub_profile_hint"),
        " ".join(str(code) for code in opportunity.get("reason_codes") or []),
        v6_final.get("deploy_block_reason"),
    )


def build_market_advice(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a compact recommendation-only response from a DPS result."""

    regime, hint, scenario_name = _scenario_fields(result)
    market_status = _text(
        result.get("market_status_plain")
        or result.get("display_regime_label")
    )
    data_quality = _text(result.get("data_quality_display"))
    final_action = _text(result.get("final_action")).upper()
    final_action_label = _text(result.get("final_action_label"))
    risk_label = _text(
        result.get("risk_display_label")
        or result.get("risk_tone_plain")
    )
    context = _lower_blob(
        hint,
        scenario_name,
        market_status,
        final_action,
        final_action_label,
        result.get("controlled_grid_note"),
        _safety_context(result),
    )

    data_blocked = (
        "veri kalitesi zayıf" in data_quality.lower()
        or "fiyat verisi geçersiz" in context
        or final_action == "DATA_STALE_SAFE_WAIT"
    )
    data_limited = (
        not data_blocked
        and "veri kapsaması" in data_quality.lower()
        and "sınırlı" in data_quality.lower()
    )
    low_liquidity = any(
        token in context
        for token in (
            "low_liquidity",
            "düşük likidite",
            "likidite/spread",
            "restricted_by_liquidity",
            "spread_unsafe",
        )
    )
    parabolic = (
        "parabolic" in context
        or "parabolik" in context
    )
    cooldown = (
        regime in {"R1", "R3", "R5"}
        and any(
            token in context
            for token in ("pullback", "cooldown", "soğuyor", "geri çekilme")
        )
    )

    scenario_code = regime if regime in _REGIME_ADVICE else "DATA_BLOCKED"
    if data_blocked:
        template = _DATA_BLOCKED
        scenario_code = "DATA_BLOCKED"
    elif low_liquidity:
        template = _LOW_LIQUIDITY
        scenario_code = "LOW_LIQUIDITY"
    elif regime == "R8":
        template = _REGIME_ADVICE["R8"]
        scenario_code = "R8"
    elif parabolic:
        template = _PARABOLIC
        scenario_code = "PARABOLIC"
    elif data_limited:
        template = _DATA_LIMITED
        scenario_code = "DATA_LIMITED"
    elif cooldown:
        template = _COOLDOWN
        scenario_code = f"{regime}_COOLDOWN"
    else:
        template = _REGIME_ADVICE.get(regime, _DATA_BLOCKED)

    if (
        hint in _SUB_SCENARIO_OVERRIDES
        and not data_blocked
        and not data_limited
        and not low_liquidity
    ):
        template = {**template, **_SUB_SCENARIO_OVERRIDES[hint]}
        scenario_code = hint

    follow_up = _REGIME_FOLLOW_UP.get(regime, _REGIME_FOLLOW_UP["R8"])
    engine_plan = _engine_plan(result)
    if data_blocked:
        engine_plan["status"] = (
            "Veri kapısı planı geçersiz kıldı; yeni işlem için kullanılmamalıdır."
        )
    elif low_liquidity:
        engine_plan["status"] = (
            "Bu yalnız restricted risk referansıdır; yeni bot açma önerisi değildir."
        )
    elif regime == "R8" or parabolic:
        engine_plan["status"] = (
            "Bu yalnız koruma/probe referansıdır; normal yeni alım planı değildir."
        )
    elif data_limited:
        engine_plan["status"] = (
            "Veri kapsamı sınırlı olduğu için plan üst sınır ve korumacı referanstır."
        )
    template = dict(template)
    if engine_plan["allocation"].startswith("Coin %"):
        template["allocation"] = (
            f"Motorun bu analiz için kesin referansı: {engine_plan['allocation']}."
        )
        template["buy_grid"] = engine_plan["buy_ladder"]
        template["sell_grid"] = engine_plan["sell_ladder"]
    if engine_plan.get("sell_ladder_state") == "planned_inactive":
        template["action"] = (
            f"{template['action']} Mevcut satılabilir coin olmadığı için satış "
            "kademeleri şu anda aktif değildir."
        )
    market_evidence = _market_evidence(result)
    reasons = []
    for reason in (
        market_status,
        scenario_name,
        f"Risk yaklaşımı: {risk_label}" if risk_label else "",
        data_quality,
    ):
        if reason and reason not in reasons:
            reasons.append(reason)

    confidence = result.get("confidence")
    risk_score = result.get("risk_score")
    return {
        "ok": True,
        "engine": "dynamic_param_score_v6",
        "mode": "recommendation_only",
        "comment_source": "prebuilt_scenario_library",
        "advice_library_version": ADVICE_LIBRARY_VERSION,
        "advice_library_scenario_count": len(ADVICE_LIBRARY_SCENARIOS),
        "legacy_parameter_application_disabled": True,
        "symbol": result.get("symbol"),
        "budget": result.get("budget"),
        "decision_id": result.get("decision_id"),
        "regime_tag": regime or None,
        "display_regime_label": market_status or template["title"],
        "market_status_plain": market_status or template["title"],
        "risk_display_label": risk_label or "Temkinli",
        "risk_score": risk_score,
        "confidence": confidence,
        "confidence_display_pct": result.get("confidence_display_pct"),
        "data_quality_display": data_quality or "Veri kalitesi kontrol edildi",
        "deployable": False,
        "can_apply_safe_overlay": False,
        "ui_config": None,
        "recommendation_config": None,
        "recommendation": {
            "scenario_code": scenario_code,
            **template,
            "reasons": reasons[:4],
            "interpretation": template.get(
                "interpretation", follow_up["interpretation"]
            ),
            "risk_control": template.get(
                "risk_control", follow_up["risk_control"]
            ),
            "invalidation": template.get(
                "invalidation", follow_up["invalidation"]
            ),
            "engine_plan": engine_plan,
            "market_evidence": market_evidence,
            "disclaimer": (
                "Bu sonuç kesin fiyat tahmini değildir. Piyasa yapısı değiştiğinde "
                "analizi yenileyin; yüksek riskli durumda işlem açmamak önceliklidir."
            ),
        },
    }
