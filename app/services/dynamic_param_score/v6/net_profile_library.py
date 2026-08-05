# ROLE: V6 net profile library — fixed 4+4 weekly / ≤10% operator contract
"""Operator-authored 35-profile library used by Param Assistant and Dynamic Mode.

Contract (Parametre Asistanı — Sabit 4+4 Grid, Haftalık Çalışma, %10 Odaklı):
- Every profile has exactly 4 buy + 4 sell grids (reference plan when Kapalı).
- Optimized for ~7-day cycle; unrealized grids reposition at cycle close.
- Normal profiles: farthest grid ≤ 10%. Extreme / low-liq / pump / crash may use 12–15%.
- Each level amount ≥ 10%; each side sums to 100%.
- Kapalı profiles keep 4+4 as reference only (automatic_apply=False).

This is intentionally the only recommendation library consulted by the V6 live
resolver. Profiles are sealed after the adjuster/opportunity pipeline so the
operator ladders are not overwritten by regime_behavior_spec templates.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.dynamic_param_score.v6.domain.types import (
    GridLevel,
    ScenarioIdentity,
    V6CatalogProfile,
    V6InputContract,
)
from app.services.dynamic_param_score.v6.v6_quantizer import (
    profit_code_from_pct,
    trailing_code_from_pct,
)

logger = logging.getLogger(__name__)

LIBRARY_VERSION = "v6_net_profile_library_weekly_4x4_v1"

# (base_pct, sells[(d,amt)...], sell_trail, buys[(d,amt)...], buy_trail,
#  profit_sell(trigger,trail)|None, profit_buy(trigger,trail)|None, apply_policy)
PROFILE_VALUES: Dict[str, tuple] = {
    "R1_STRONG_UPTREND": (
        70,
        [(2, 20), (4, 30), (7, 30), (10, 20)],
        1.0,
        [(2, 40), (4, 30), (6, 20), (9, 10)],
        0.75,
        (5.0, 1.0),
        (3.0, 0.75),
        "Açık",
    ),
    "R1_PULLBACK": (
        60,
        [(2, 30), (4, 30), (6, 20), (9, 20)],
        0.75,
        [(1, 30), (3, 30), (5, 20), (8, 20)],
        0.5,
        (4.0, 0.75),
        (3.0, 0.5),
        "Açık",
    ),
    "R1_TREND_COOLDOWN": (
        50,
        [(1, 30), (3, 30), (5, 20), (8, 20)],
        0.75,
        [(2, 30), (4, 30), (7, 20), (10, 20)],
        0.75,
        (3.0, 0.75),
        (4.0, 0.75),
        "Açık",
    ),
    "R2_BALANCED_RANGE": (
        50,
        [(1, 30), (3, 30), (5, 20), (7, 20)],
        0.5,
        [(1, 30), (3, 30), (5, 20), (7, 20)],
        0.5,
        (3.0, 0.75),
        (3.0, 0.75),
        "Açık",
    ),
    "R2_CALM_RANGE": (
        50,
        [(1, 30), (2, 30), (3, 20), (4, 20)],
        0.5,
        [(1, 30), (2, 30), (3, 20), (4, 20)],
        0.5,
        (2.0, 0.5),
        (2.0, 0.5),
        "Açık — net kâr filtresi sağlanırsa",
    ),
    "R3_NOISY_RANGE": (
        40,
        [(2, 30), (4, 30), (7, 20), (10, 20)],
        0.75,
        [(2, 30), (4, 30), (7, 20), (10, 20)],
        0.75,
        (3.0, 0.75),
        (3.0, 0.75),
        "Açık — kontrollü",
    ),
    "R3_DIRECTIONLESS_COMPRESSION": (
        40,
        [(1, 30), (2, 30), (4, 20), (6, 20)],
        0.5,
        [(1, 30), (2, 30), (4, 20), (6, 20)],
        0.5,
        (2.0, 0.5),
        (2.0, 0.5),
        "Açık — kırılım filtresiyle",
    ),
    "R3_CONTROLLED_COMPRESSION": (
        50,
        [(1, 30), (2, 30), (3, 20), (5, 20)],
        0.5,
        [(1, 30), (2, 30), (3, 20), (5, 20)],
        0.5,
        (2.0, 0.5),
        (2.0, 0.5),
        "Açık",
    ),
    "R3_UPTREND_COMPRESSION": (
        70,
        [(2, 20), (4, 30), (7, 30), (10, 20)],
        0.75,
        [(2, 40), (4, 30), (6, 20), (9, 10)],
        0.75,
        (4.0, 0.75),
        (3.0, 0.75),
        "Açık",
    ),
    "R3_UPTREND_OVERHEAT": (
        50,
        [(1, 40), (2, 30), (4, 20), (7, 10)],
        0.75,
        [(3, 20), (5, 20), (8, 30), (10, 30)],
        1.0,
        (2.0, 0.75),
        (4.0, 1.0),
        "Açık — alışlar derin",
    ),
    "R3_UPPER_BAND_PROFIT_LOCK": (
        40,
        [(1, 40), (2, 30), (3, 20), (5, 10)],
        0.5,
        [(2, 20), (4, 20), (6, 30), (9, 30)],
        0.75,
        (2.0, 0.5),
        (3.0, 0.75),
        "Açık",
    ),
    "R4_LIQUID_VOLATILE_RANGE": (
        50,
        [(2, 30), (5, 30), (8, 20), (10, 20)],
        1.25,
        [(2, 30), (5, 30), (8, 20), (10, 20)],
        1.25,
        (5.0, 1.25),
        (5.0, 1.25),
        "Açık",
    ),
    "R4_MEDIUM_VOLATILE_RANGE": (
        50,
        [(2, 30), (4, 30), (7, 20), (10, 20)],
        1.0,
        [(2, 30), (4, 30), (7, 20), (10, 20)],
        1.0,
        (4.0, 1.0),
        (4.0, 1.0),
        "Açık",
    ),
    "R4_CHOPPY_RANGE": (
        50,
        [(3, 30), (6, 20), (8, 20), (10, 30)],
        1.25,
        [(3, 30), (6, 20), (8, 20), (10, 30)],
        1.25,
        (5.0, 1.25),
        (5.0, 1.25),
        "Açık",
    ),
    "R4_LOWER_BAND_BOUNCE": (
        60,
        [(2, 30), (4, 30), (7, 20), (10, 20)],
        1.0,
        [(2, 20), (4, 20), (7, 30), (10, 30)],
        0.75,
        (4.0, 1.0),
        (4.0, 0.75),
        "Açık",
    ),
    "R4_OVERHEATED": (
        40,
        [(1, 40), (3, 30), (5, 20), (8, 10)],
        1.0,
        [(4, 20), (6, 20), (8, 30), (10, 30)],
        1.25,
        (3.0, 1.0),
        (5.0, 1.25),
        "Açık",
    ),
    "R4_FRAGILE_LIQUID": (
        40,
        [(2, 30), (5, 30), (8, 20), (10, 20)],
        1.25,
        [(3, 20), (6, 20), (8, 30), (10, 30)],
        1.5,
        (4.0, 1.25),
        (6.0, 1.5),
        "Açık — savunmacı",
    ),
    "R4_LOW_LIQUIDITY": (
        30,
        [(3, 30), (6, 30), (9, 20), (12, 20)],
        1.5,
        [(4, 20), (7, 20), (10, 30), (13, 30)],
        1.5,
        (5.0, 1.5),
        (7.0, 1.5),
        "Açık — koşullu risk",
    ),
    "R4_RESTRICTED_UNSTABLE": (
        20,
        [(3, 40), (6, 30), (9, 20), (12, 10)],
        1.5,
        [(6, 20), (9, 20), (12, 30), (15, 30)],
        1.5,
        (4.0, 1.5),
        (7.0, 1.5),
        "Kapalı",
    ),
    "R5_CLEAN_BREAKOUT": (
        70,
        [(2, 20), (5, 30), (8, 30), (10, 20)],
        1.25,
        [(2, 40), (4, 30), (6, 20), (9, 10)],
        1.0,
        (6.0, 1.25),
        (4.0, 1.0),
        "Açık",
    ),
    "R5_POST_BREAKOUT_COOLDOWN": (
        50,
        [(2, 30), (4, 30), (7, 20), (10, 20)],
        0.75,
        [(3, 20), (5, 20), (8, 30), (10, 30)],
        1.0,
        (4.0, 1.0),
        (4.0, 1.0),
        "Açık",
    ),
    "R5_OVEREXTENDED": (
        40,
        [(1, 40), (2, 30), (4, 20), (7, 10)],
        1.0,
        [(4, 20), (6, 20), (8, 30), (10, 30)],
        1.25,
        (3.0, 1.0),
        (6.0, 1.25),
        "Açık — savunmacı",
    ),
    "R5_HIGH_VOL_OVEREXTENDED": (
        30,
        [(1, 40), (3, 30), (5, 20), (8, 10)],
        1.5,
        [(6, 20), (9, 20), (12, 30), (15, 30)],
        1.75,
        (4.0, 1.5),
        (8.0, 1.75),
        "Açık — alışlar güvenlik filtresiyle",
    ),
    "R5_HIGH_VOL_CLEAN_MOMENTUM": (
        70,
        [(3, 20), (6, 30), (9, 30), (12, 20)],
        1.5,
        [(3, 40), (6, 30), (9, 20), (12, 10)],
        1.25,
        (7.0, 1.5),
        (5.0, 1.25),
        "Açık",
    ),
    "R5_PARABOLIC_PUMP": (
        20,
        [(1, 40), (2, 30), (4, 20), (7, 10)],
        1.75,
        [(7, 20), (10, 20), (12, 30), (15, 30)],
        2.0,
        (3.0, 1.75),
        (10.0, 2.0),
        "Açık — satış aktif, alışlar soğuma teyidiyle",
    ),
    "R5_RECOVERY_GENERIC": (
        50,
        [(2, 30), (4, 30), (6, 20), (9, 20)],
        0.75,
        [(2, 30), (4, 30), (6, 20), (9, 20)],
        0.75,
        (4.0, 1.0),
        (3.0, 0.75),
        "Açık — kontrollü",
    ),
    "R6_CONTROLLED_RECOVERY": (
        60,
        [(2, 20), (4, 30), (7, 30), (10, 20)],
        1.0,
        [(2, 30), (4, 30), (6, 20), (9, 20)],
        0.75,
        (5.0, 1.0),
        (4.0, 0.75),
        "Açık",
    ),
    "R6_RECOVERY_BREAKOUT": (
        70,
        [(2, 20), (5, 30), (8, 30), (10, 20)],
        1.25,
        [(2, 40), (4, 30), (6, 20), (9, 10)],
        1.0,
        (6.0, 1.25),
        (4.0, 1.0),
        "Açık",
    ),
    "R7_DOWNTREND": (
        20,
        [(1, 40), (3, 30), (5, 20), (8, 10)],
        1.0,
        [(5, 20), (7, 20), (9, 30), (10, 30)],
        1.25,
        (3.0, 1.0),
        (7.0, 1.25),
        "Açık — koşullu risk",
    ),
    "R7_UNSTABLE_DOWNSIDE": (
        10,
        [(2, 40), (4, 30), (7, 20), (10, 10)],
        1.25,
        [(7, 20), (10, 20), (12, 30), (15, 30)],
        1.5,
        (3.0, 1.25),
        (9.0, 1.5),
        "Kapalı",
    ),
    "R8_CRASH_PANIC": (
        10,
        [(3, 40), (6, 30), (10, 20), (15, 10)],
        1.75,
        [(8, 20), (11, 20), (13, 30), (15, 30)],
        2.0,
        (5.0, 1.75),
        (10.0, 2.0),
        "Kapalı",
    ),
    "R8_RECOVERY_RESTRICTED": (
        20,
        [(2, 40), (5, 30), (8, 20), (12, 10)],
        1.5,
        [(7, 20), (10, 20), (13, 30), (15, 30)],
        1.5,
        (4.0, 1.5),
        (8.0, 1.5),
        "Kapalı — yeniden teyit beklenir",
    ),
    "R8_CAPITULATION_PROBE": (
        10,
        [(3, 40), (6, 30), (10, 20), (15, 10)],
        2.0,
        [(8, 20), (11, 20), (13, 30), (15, 30)],
        2.0,
        (6.0, 2.0),
        (10.0, 2.0),
        "Kapalı",
    ),
    "R8_HARD_BLOCK": (
        0,
        [(4, 40), (7, 30), (10, 20), (15, 10)],
        2.0,
        [(8, 20), (11, 20), (13, 30), (15, 30)],
        2.0,
        None,
        None,
        "Kapalı",
    ),
    "R8_LOW_LIQUIDITY_RESTRICTED": (
        0,
        [(4, 40), (7, 30), (10, 20), (15, 10)],
        2.0,
        [(8, 20), (11, 20), (13, 30), (15, 30)],
        2.0,
        None,
        None,
        "Kapalı",
    ),
}

PROFILE_COPY: Dict[str, Tuple[str, str]] = {
    "R1_STRONG_UPTREND": (
        "Sistem Güçlü Yükseliş Trendi Algıladı",
        "Trend güçlü ve devam ediyor. Fiyat EMA200 üzerinde, yüksek tepeler korunuyor ve yükseliş momentumu güçlü. Base ağırlığı korunurken satışlar yükselişin sık çalışabilecek bölümüne yayılır.",
    ),
    "R1_PULLBACK": (
        "Sistem Güçlü Yükseliş İçinde Geri Çekilme Algıladı",
        "Ana trend yukarı, fiyat kısa vadeli düzeltme yapıyor. Yükseliş yapısı bozulmadı ancak fiyat desteklere doğru geri çekiliyor. Yakın alışlar düzeltmeyi değerlendirir; satışlar toparlanmanın erişilebilir seviyelerine yerleştirilir.",
    ),
    "R1_TREND_COOLDOWN": (
        "Sistem Yükseliş Trendinde Kontrollü Soğuma Algıladı",
        "Yükseliş sürüyor fakat momentum zayıfladı. Ana yapı pozitif kalırken fiyatı kovalamamak gerekir. Dağılım dengelenir; alışlar biraz derinleştirilir, satışlar ise ulaşılabilir seviyelerde tutulur.",
    ),
    "R2_BALANCED_RANGE": (
        "Sistem Dengeli Aralık Algıladı",
        "Piyasa iki yönlü ve dengeli hareket ediyor. Belirgin trend yok; fiyat destek ve direnç arasında düzenli gidip geliyor. Simetrik ve orta genişlikte gridler işlem sıklığı ile güvenliği dengeler.",
    ),
    "R2_CALM_RANGE": (
        "Sistem Sakin Yatay Bölge Algıladı",
        "Yatay yapı kararlı, volatilite çok düşük. Fiyat dar bir bantta hareket ediyor. Yakın gridler sık çalışma sağlar; ilk iki gride daha fazla miktar verilerek sermayenin erişilemeyen uzak seviyelerde beklemesi önlenir.",
    ),
    "R3_NOISY_RANGE": (
        "Sistem Zayıf ve Gürültülü Aralık Algıladı",
        "Yön yok fakat yatay yapı temiz değil. Sık yön değişimi ve sahte hareket riski bulunuyor. Gridler sakin piyasaya göre biraz genişletilir; yakın iki grid işlem üretirken uzak gridler riski sınırlar.",
    ),
    "R3_DIRECTIONLESS_COMPRESSION": (
        "Sistem Yönsüz Sıkışma Algıladı",
        "Fiyat daralıyor, kırılım yönü henüz belli değil. Yön teyidi bulunmadığı için USDT rezervi yüksek tutulur. Yakın gridler dar hareketi değerlendirir; dördüncü grid olası bant genişlemesine karşı koruma sağlar.",
    ),
    "R3_CONTROLLED_COMPRESSION": (
        "Sistem Düşük Volatiliteli Kontrollü Sıkışma Algıladı",
        "Daralma düzenli ve sert düşüş sinyali yok. Yapı kararlı olduğu için yakın iki yönlü grid kullanılabilir. Seviyeler dar tutulur fakat tek bir küçük harekette tüm sermayenin işlem görmesi engellenir.",
    ),
    "R3_UPTREND_COMPRESSION": (
        "Sistem Yukarı Eğilimli Sıkışma Algıladı",
        "Ana yön yukarı, kısa vadeli hareket daralıyor. Yukarı kırılım ihtimali korunurken fiyat henüz geniş hareket etmiyor. Base yüksek tutulur; satışlar orta mesafeye, alışlar kontrollü geri çekilmelere yayılır.",
    ),
    "R3_UPTREND_OVERHEAT": (
        "Sistem Yukarı Trendde Aşırı Isınma Algıladı",
        "Trend pozitif fakat kısa vadede aşırı alım var. Mevcut base korunarak yakın seviyelerde kademeli kâr alınır. Yeni alışlar, normal dalgalanmaya değil daha anlamlı bir geri çekilmeye yerleştirilir.",
    ),
    "R3_UPPER_BAND_PROFIT_LOCK": (
        "Sistem Üst Banda Yakın Kontrollü Kâr Alma Algıladı",
        "Fiyat sakin piyasada üst banda yaklaştı. Güçlü trend teyidi olmadığı için yakın satışlarla kâr korunur. Geri alışlar, küçük gürültü yerine bant içine gerçek dönüşü bekleyecek şekilde aşağıda tutulur.",
    ),
    "R4_LIQUID_VOLATILE_RANGE": (
        "Sistem Likit ve Volatil Aralık Algıladı",
        "Oynaklık yüksek fakat piyasa likit ve iki yönlü. Geniş hareketler sık gerçekleşebilse de haftalık turda sermayenin erişilemeyen seviyelerde beklememesi için gridler normalde %10 içinde tutulur. İlk iki grid yüksek işlem olasılığını, son iki grid büyük salınımları değerlendirir.",
    ),
    "R4_MEDIUM_VOLATILE_RANGE": (
        "Sistem Orta Volatiliteli Aralık Algıladı",
        "Piyasa iki yönlü, volatilite orta seviyede. Gridler sakin piyasadan geniş, yüksek volatilite profilinden dardır. Bu dağılım yaklaşık bir haftalık turda hem yakın hareketleri hem orta büyüklükte salınımları hedefler.",
    ),
    "R4_CHOPPY_RANGE": (
        "Sistem Dalgalı Aralık Algıladı",
        "Fiyat iki yönde sert ve düzensiz dalgalanıyor. Gürültülü tetiklenmeyi azaltmak için seviyeler geniş tutulur. İlk iki grid kullanılabilir aralığı korurken son iki grid sert salınımları karşılar.",
    ),
    "R4_LOWER_BAND_BOUNCE": (
        "Sistem Alt Banttan Tepki Fırsatı Algıladı",
        "Fiyat volatil aralığın alt bölümünde. Yukarı tepki ihtimali nedeniyle base hafif artırılır. Yakın satışlar beklenen tepkiyi paraya çevirir; alışlar olası ikinci düşüşe kademeli yayılır.",
    ),
    "R4_OVERHEATED": (
        "Sistem Üst Bantta Kontrollü Volatil Aralık Algıladı",
        "Fiyat üst bantta ve aşırı alım riski yüksek. Trend teyidi yetersiz olduğu için base azaltılır. Satışlar erişilebilir yakın seviyelere, alışlar ise anlamlı düzeltme bölgelerine yerleştirilir.",
    ),
    "R4_FRAGILE_LIQUID": (
        "Sistem Kırılgan Fakat Likit Volatil Aralık Algıladı",
        "Likidite yeterli, coin yapısı kırılgan. Ani hareket riski nedeniyle USDT ağırlığı artırılır ve gridler genişletilir. İlk iki grid yine yeterli miktarda çalışırken derin seviyelerde ek koruma tutulur.",
    ),
    "R4_LOW_LIQUIDITY": (
        "Sistem Düşük Likiditeli Savunmacı Volatil Aralık Algıladı",
        "Spread veya hacim kalitesi zayıfladı. Emir gerçekleşme riski nedeniyle base azaltılır, seviyeler geniş ve miktarlar kontrollü tutulur. Uygulama yalnız spread ve minimum tutar kontrolleri sağlanırsa açılır.",
    ),
    "R4_RESTRICTED_UNSTABLE": (
        "Sistem Düşük Likiditeli ve Dengesiz Aralık Algıladı",
        "Fiyat yapısı ve emir gerçekleşme kalitesi güvenli değil. Profil yalnız referans planı üretir. Dört alış ve dört satış seviyesi korunur ancak güvenlik koşulları düzelmeden borsaya emir gönderilmez.",
    ),
    "R5_CLEAN_BREAKOUT": (
        "Sistem Temiz Breakout ve Trend Devamı Algıladı",
        "Kırılım güçlü ve birden fazla sinyalle teyitli. Base yüksek tutulur fakat ilk satış tamamen ötelenmez. Dört satış seviyesi haftalık dönemde erişilebilir yükseliş alanına yayılır; alışlar sağlıklı retest bölgelerine yerleştirilir.",
    ),
    "R5_POST_BREAKOUT_COOLDOWN": (
        "Sistem Breakout Sonrası Kontrollü Soğuma Algıladı",
        "Kırılım korunuyor fakat momentum yavaşlıyor. Dağılım yeniden dengelenir. Satışlar yakın ve orta seviyelerde tutulurken alışlar yalnız gerçek geri çekilmede çalışacak şekilde aşağıya yayılır.",
    ),
    "R5_OVEREXTENDED": (
        "Sistem Yukarı Breakoutta Aşırı Isınmış Momentum Algıladı",
        "Fiyat denge bölgesinden fazla uzaklaştı. USDT rezervi artırılır ve yakın satışlarla kâr korunur. Alış gridleri küçük geri çekilmelere değil, aşırı uzamanın çözülmesine yerleştirilir.",
    ),
    "R5_HIGH_VOL_OVEREXTENDED": (
        "Sistem Yüksek Volatilite ve Aşırı Momentum Algıladı",
        "Tepe riski ile yüksek oynaklık birlikte bulunuyor. Base düşük tutulur; satışlar yükseliş devam ederse çalışır, alışlar yalnız derin düzeltmeye yerleştirilir. Yüksek trailing küçük salınımlarda erken tetiklenmeyi azaltır.",
    ),
    "R5_HIGH_VOL_CLEAN_MOMENTUM": (
        "Sistem Yüksek Volatilitede Temiz Momentum Algıladı",
        "Yükseliş sağlıklı fakat fiyat hareketi geniş. Base yüksek tutulur; yüksek volatilite nedeniyle yalnız son grid gerekçeli biçimde %12’ye kadar uzatılır. İlk satış ihmal edilmez, ancak coinlerin çoğu orta yükseliş seviyelerinde değerlendirilir.",
    ),
    "R5_PARABOLIC_PUMP": (
        "Sistem Parabolik Pump Algıladı",
        "Fiyat çok kısa sürede olağan dışı yükseldi. Base en düşük seviyelerden birine indirilir ve yakın satışlarla kâr korunur. Dört alış seviyesi yalnız derin soğuma alanına yerleştirilir; teyit gelmeden etkinleştirilmez.",
    ),
    "R5_RECOVERY_GENERIC": (
        "Sistem Genel Toparlanma Algıladı",
        "Fiyat düşüşten sonra pozitife döndü, teyit henüz sınırlı. Yön iyileşse de güçlü toparlanma teyidi tamamlanmadı. Simetrik orta aralık gridler, yanlış toparlanma riskini artırmadan hareketi değerlendirmeyi hedefler.",
    ),
    "R6_CONTROLLED_RECOVERY": (
        "Sistem Kontrollü Toparlanma Algıladı",
        "Düşüş sonrası yapı belirgin biçimde iyileşiyor. Base kontrollü artırılır. Yakın alışlar iyileşen yapıyı değerlendirirken satışlar toparlanmanın devam edebileceği orta ve üst seviyelere yayılır.",
    ),
    "R6_RECOVERY_BREAKOUT": (
        "Sistem Düşüş Sonrası Recovery Breakout Algıladı",
        "Toparlanma güçlü kırılımla teyit edildi. Base yükseltilir ve satışlar trend devamını değerlendirecek şekilde yayılır. Alışlar kırılım sonrası normal retest bölgelerinde tutulur.",
    ),
    "R7_DOWNTREND": (
        "Sistem Düşüş Trendi Algıladı",
        "Aşağı yönlü piyasa yapısı güçlü. USDT ağırlığı yüksek tutulur. Satışlar tepki yükselişlerinde base azaltır; alışlar yalnız daha derin ve anlamlı geri çekilmelerde kademeli çalışır.",
    ),
    "R7_UNSTABLE_DOWNSIDE": (
        "Sistem Dengesiz Volatilite ve Düşüş Riski Algıladı",
        "Aşağı yön riski yüksek ve piyasa yapısı düzensiz. Profil dört yönlü referans gridini korur fakat otomatik emir açmaz. Base çok düşük, alış seviyeleri çok derin tutulur ve yeniden açılış için yapı teyidi beklenir.",
    ),
    "R8_CRASH_PANIC": (
        "Sistem Crash ve Sert Düşüş Algıladı",
        "Hızlı düşüş ve derin drawdown birlikte oluştu. Dört alış ve dört satış seviyesi yalnız referans olarak hesaplanır. Otomatik uygulama kapalıdır; düşük likiditede zorunlu satış veya yeni alım yapılmaz.",
    ),
    "R8_RECOVERY_RESTRICTED": (
        "Sistem Crash Sonrası Kontrollü Toparlanma Algıladı",
        "Kısa vadeli tepki var fakat crash riski sürüyor. Satış planı tepki hareketini değerlendirecek şekilde yakınlaştırılır. Alış gridleri derinde kalır ve otomatik uygulama yalnız crash koşulları tamamen sona erdiğinde açılır.",
    ),
    "R8_CAPITULATION_PROBE": (
        "Sistem Kapitülasyon Crash ve Koşullu Probe Algıladı",
        "Çok derin düşüşten sonra sınırlı tepki oluştu. Profil aşırı riskli olduğu için dört grid yalnız referans planıdır. Otomatik probe yapılmaz; yeniden açılış için likidite, hacim ve piyasa yapısı teyidi gerekir.",
    ),
    "R8_HARD_BLOCK": (
        "Sistem Hard Block ve İşlem Yasağı Algıladı",
        "Birden fazla ağır risk sinyali işlem güvenliğini kaldırdı. Sistem yalnız dört alış ve dört satış referans seviyesi üretir. Hiçbir emir borsaya gönderilmez; yeni sermaye USDT’de tutulur ve mevcut coin zorla satılmaz.",
    ),
    "R8_LOW_LIQUIDITY_RESTRICTED": (
        "Sistem Crash ile Birlikte Likidite Kısıtı Algıladı",
        "Crash koşullarına ciddi likidite sorunu eşlik ediyor. Dört alış ve dört satış seviyesi yalnız teknik referanstır. Spread ve hacim güvenli sınıra dönmeden hiçbir grid, kâr satışı veya geri alış emri açılmaz.",
    ),
}

_HINT_MAP = {
    "R1_STD_PULLBACK": "R1_PULLBACK",
    "R1_STD_TREND_COOLDOWN": "R1_TREND_COOLDOWN",
    "R3_STD_UPPER_BAND_PROFIT_LOCK": "R3_UPPER_BAND_PROFIT_LOCK",
    "R3_STD_UPTREND_OVERHEAT_COOLDOWN": "R3_UPTREND_OVERHEAT",
    "R3_STD_UPTREND_COMPRESSION": "R3_UPTREND_COMPRESSION",
    "R3_STD_CONTROLLED_COMPRESSION": "R3_CONTROLLED_COMPRESSION",
    "R4_DEF_OVERHEATED": "R4_OVERHEATED",
    "R4_RESTRICTED_UNSTABLE": "R4_RESTRICTED_UNSTABLE",
    "R4_DEF_LOW_LIQUIDITY": "R4_LOW_LIQUIDITY",
    "R4_ACT_LOWER_BAND_BOUNCE": "R4_LOWER_BAND_BOUNCE",
    "R4_STD_LIQUID": "R4_LIQUID_VOLATILE_RANGE",
    "R5_ACT_CLEAN_BREAKOUT": "R5_CLEAN_BREAKOUT",
    "R5_STD_POST_BREAKOUT_COOLDOWN": "R5_POST_BREAKOUT_COOLDOWN",
    "R5_DEF_OVEREXTENDED": "R5_OVEREXTENDED",
    "R5_DEF_PARABOLIC_OVEREXTENDED": "R5_PARABOLIC_PUMP",
    "R6_RECOVERY_ACT": "R6_CONTROLLED_RECOVERY",
    "R6_RECOVERY_BREAKOUT": "R6_RECOVERY_BREAKOUT",
    "R8_DEF_PANIC": "R8_CRASH_PANIC",
    "R8_RECOVERY_RESTRICTED": "R8_RECOVERY_RESTRICTED",
    "R8_CAPITULATION_CONDITIONAL_PROBE": "R8_CAPITULATION_PROBE",
    "R8_HARD_BLOCK": "R8_HARD_BLOCK",
}

# Reached only via regime/vol/liquidity heuristics (not a classifier hint).
HEURISTIC_ONLY_PROFILE_KEYS = frozenset(
    {
        "R1_STRONG_UPTREND",
        "R2_BALANCED_RANGE",
        "R2_CALM_RANGE",
        "R3_NOISY_RANGE",
        "R3_DIRECTIONLESS_COMPRESSION",
        "R4_MEDIUM_VOLATILE_RANGE",
        "R4_CHOPPY_RANGE",
        "R4_FRAGILE_LIQUID",
        "R5_HIGH_VOL_OVEREXTENDED",
        "R5_HIGH_VOL_CLEAN_MOMENTUM",
        "R5_RECOVERY_GENERIC",
        "R7_DOWNTREND",
        "R7_UNSTABLE_DOWNSIDE",
        "R8_LOW_LIQUIDITY_RESTRICTED",
    }
)

_NORMAL_MAX_DIST_KEYS = frozenset(
    {
        "R1_STRONG_UPTREND",
        "R1_PULLBACK",
        "R1_TREND_COOLDOWN",
        "R2_BALANCED_RANGE",
        "R2_CALM_RANGE",
        "R3_NOISY_RANGE",
        "R3_DIRECTIONLESS_COMPRESSION",
        "R3_CONTROLLED_COMPRESSION",
        "R3_UPTREND_COMPRESSION",
        "R3_UPTREND_OVERHEAT",
        "R3_UPPER_BAND_PROFIT_LOCK",
        "R4_LIQUID_VOLATILE_RANGE",
        "R4_MEDIUM_VOLATILE_RANGE",
        "R4_CHOPPY_RANGE",
        "R4_LOWER_BAND_BOUNCE",
        "R4_OVERHEATED",
        "R4_FRAGILE_LIQUID",
        "R5_CLEAN_BREAKOUT",
        "R5_POST_BREAKOUT_COOLDOWN",
        "R5_OVEREXTENDED",
        "R5_RECOVERY_GENERIC",
        "R6_CONTROLLED_RECOVERY",
        "R6_RECOVERY_BREAKOUT",
        "R7_DOWNTREND",
    }
)


def canonical_headline_for_key(key: str) -> str:
    title, _why = PROFILE_COPY.get(key, ("", ""))
    return str(title or key)


def _liquidity_weak(inp: V6InputContract) -> bool:
    spread = float(inp.spread_pct or 0.0)
    vol_consistency = float(inp.volume_consistency if inp.volume_consistency is not None else 0.5)
    return spread >= 0.10 or vol_consistency < 0.35


def select_profile_key(classified: Any, inp: V6InputContract) -> str:
    """Choose one of the 35 operator profiles from current engine signals."""
    hint = str(getattr(classified, "sub_profile_hint", "") or "")
    regime = str(getattr(classified, "regime_id", "R3") or "R3").upper()
    hard_block = bool(getattr(classified, "hard_block", False)) or hint == "R8_HARD_BLOCK"
    # Hard-block must beat liquidity override (R8_LOW_LIQUIDITY_RESTRICTED).
    if hard_block:
        return "R8_HARD_BLOCK"

    key = _HINT_MAP.get(hint)
    if hint and key is None:
        logger.warning(
            "Unknown sub_profile_hint=%s regime=%s — falling back to regime heuristic",
            hint,
            regime,
        )

    vol = float(inp.volatility_percentile or 0.0)
    liquidity_weak = _liquidity_weak(inp)

    if regime == "R1":
        return key or "R1_STRONG_UPTREND"
    if regime == "R2":
        return "R2_CALM_RANGE" if vol < 25 else "R2_BALANCED_RANGE"
    if regime == "R3":
        return key or (
            "R3_NOISY_RANGE"
            if float(inp.range_stability or 0.0) < 0.45
            else "R3_DIRECTIONLESS_COMPRESSION"
        )
    if regime == "R4":
        if key:
            return key
        if str(inp.asset_fragility_class or "F1").upper() in ("F2", "F3"):
            return "R4_FRAGILE_LIQUID" if not liquidity_weak else "R4_LOW_LIQUIDITY"
        if vol < 60:
            return "R4_MEDIUM_VOLATILE_RANGE"
        if float(inp.range_stability or 0.0) < 0.40:
            return "R4_CHOPPY_RANGE"
        return "R4_LIQUID_VOLATILE_RANGE"
    if regime == "R5":
        if key == "R5_CLEAN_BREAKOUT" and vol >= 75:
            return "R5_HIGH_VOL_CLEAN_MOMENTUM"
        if key == "R5_OVEREXTENDED" and vol >= 75:
            return "R5_HIGH_VOL_OVEREXTENDED"
        return key or "R5_RECOVERY_GENERIC"
    if regime == "R6":
        return key or "R6_CONTROLLED_RECOVERY"
    if regime == "R7":
        return "R7_UNSTABLE_DOWNSIDE" if liquidity_weak or vol >= 80 else "R7_DOWNTREND"
    if regime == "R8":
        if liquidity_weak:
            return "R8_LOW_LIQUIDITY_RESTRICTED"
        return key or "R8_CRASH_PANIC"
    return "R3_DIRECTIONLESS_COMPRESSION"


def build_classification_trace(
    classified: Any,
    inp: V6InputContract,
    *,
    selected_profile_key: str,
) -> Dict[str, Any]:
    missing: List[str] = []
    for field in ("roc_5m", "return_1h_pct", "pump_score", "dump_score", "fake_breakout_score"):
        if getattr(inp, field, None) is None:
            missing.append(field)
    liquidity_weak = _liquidity_weak(inp)
    hard_block = bool(getattr(classified, "hard_block", False))
    reasons = tuple(getattr(classified, "hard_block_reasons", ()) or ())
    gates = tuple(getattr(classified, "matched_gates", ()) or ())
    hint = str(getattr(classified, "sub_profile_hint", "") or "")
    regime = str(getattr(classified, "regime_id", "") or "")
    quality = "ok"
    if not getattr(inp, "price_valid", True):
        quality = "price_invalid"
    elif int(getattr(inp, "candles_5m", 0) or 0) < 50:
        quality = "thin_candles"
    elif missing:
        quality = "partial_scores"
    fallback_used = bool(hint and hint not in _HINT_MAP and not hard_block)
    confidence = 0.9
    if hard_block:
        confidence = 0.95
    elif fallback_used or quality != "ok":
        confidence = 0.55
    elif missing:
        confidence = 0.7
    return {
        "input_data_quality": quality,
        "roc_5m": getattr(inp, "roc_5m", None),
        "return_1h_pct": getattr(inp, "return_1h_pct", None),
        "pump_score": getattr(inp, "pump_score", None),
        "dump_score": getattr(inp, "dump_score", None),
        "fake_breakout_score": getattr(inp, "fake_breakout_score", None),
        "hard_block": hard_block,
        "hard_block_reason": list(reasons),
        "liquidity_weak": liquidity_weak,
        "matched_gates": list(gates),
        "selected_regime": regime,
        "selected_hint": hint,
        "selected_profile_key": selected_profile_key,
        "canonical_headline": canonical_headline_for_key(selected_profile_key),
        "fallback_used": fallback_used,
        "confidence": confidence,
        "missing_fields": missing,
        "library_version": LIBRARY_VERSION,
    }


def build_profile(key: str, classified: Any, severity: str) -> V6CatalogProfile:
    if key not in PROFILE_VALUES:
        raise KeyError(f"unknown_net_profile:{key}")
    base, sells, sell_trail, buys, buy_trail, profit_sell, profit_buy, apply_policy = PROFILE_VALUES[key]
    title, reason = PROFILE_COPY[key]
    auto_apply = not str(apply_policy).startswith("Kapalı")
    # Kapalı: keep 4+4 as reference ladders, but do not enable live buy placement.
    # Deployable is also gated by automatic_apply=False.
    normal_buy_enabled = bool(buys) and auto_apply
    scenario = ScenarioIdentity(
        regime_id=key.split("_", 1)[0],
        sub_id=str(getattr(classified, "sub_id", "01")),
        micro_id=str(getattr(classified, "micro_id", "001")),
        behavior_id=str(getattr(classified, "behavior_id", "PB01")),
        severity=severity,  # type: ignore[arg-type]
        name=title,
    )
    buy_grids = [GridLevel(int(-abs(int(d))), int(a)) for d, a in buys]
    sell_grids = [GridLevel(int(abs(int(d))), int(a)) for d, a in sells]
    return V6CatalogProfile(
        profile_id=key,
        scenario=scenario,
        base_allocation_pct=int(base),
        quote_allocation_pct=100 - int(base),
        initial_base_allocation=base > 0,
        normal_buy_enabled=normal_buy_enabled,
        buy_grids=buy_grids,
        sell_grids=sell_grids,
        sell_trailing_code=trailing_code_from_pct(float(sell_trail or 0.5)),
        buy_trailing_code=trailing_code_from_pct(float(buy_trail or 0.5)),
        buyback_after_sell_enabled=profit_buy is not None,
        buyback_trigger_code=profit_code_from_pct(float(profit_buy[0] if profit_buy else 5.0)),
        buyback_trailing_code=trailing_code_from_pct(float(profit_buy[1] if profit_buy else 0.5)),
        profit_sell_after_buyback_enabled=profit_buy is not None and profit_sell is not None,
        profit_sell_trigger_code=profit_code_from_pct(float(profit_sell[0] if profit_sell else 5.0)),
        profit_sell_trailing_code=trailing_code_from_pct(float(profit_sell[1] if profit_sell else 0.5)),
        modules={
            "net_profile_library": True,
            "library_version": LIBRARY_VERSION,
            "selected_profile_key": key,
            "profile_key": key,
            "headline": title,
            "canonical_headline": title,
            "why": reason,
            "why_this_profile": reason,
            "automatic_apply": auto_apply,
            "automatic_apply_label": apply_policy,
            "apply_policy": apply_policy,
            "reference_plan_only": not auto_apply,
            "weekly_cycle_days": 7,
            "grid_contract": "fixed_4x4",
            "max_normal_grid_pct": 10.0,
            "max_extreme_grid_pct": 15.0,
            "operator_authored": True,
            "sealed_shape": True,
            # Bypass rigid QTY_TEMPLATES; operator 4+4 amounts are contractual.
            "regime_behavior_spec": True,
        },
    )


def resolve_net_profile(classified: Any, inp: V6InputContract, severity: str) -> V6CatalogProfile:
    return build_profile(select_profile_key(classified, inp), classified, severity)


def seal_net_profile_shape(
    adjusted: V6CatalogProfile,
    library_profile: V6CatalogProfile,
) -> V6CatalogProfile:
    """Re-apply operator 4+4 contract after adjusters / opportunity postprocess."""
    if not (library_profile.modules or {}).get("net_profile_library"):
        return adjusted
    adjusted.base_allocation_pct = int(library_profile.base_allocation_pct)
    adjusted.quote_allocation_pct = int(library_profile.quote_allocation_pct)
    adjusted.initial_base_allocation = library_profile.initial_base_allocation
    adjusted.buy_grids = [
        GridLevel(g.distance_pct, g.amount_pct) for g in library_profile.buy_grids
    ]
    adjusted.sell_grids = [
        GridLevel(g.distance_pct, g.amount_pct) for g in library_profile.sell_grids
    ]
    adjusted.buy_trailing_code = library_profile.buy_trailing_code
    adjusted.sell_trailing_code = library_profile.sell_trailing_code
    adjusted.profit_sell_trigger_code = library_profile.profit_sell_trigger_code
    adjusted.profit_sell_trailing_code = library_profile.profit_sell_trailing_code
    adjusted.buyback_after_sell_enabled = library_profile.buyback_after_sell_enabled
    adjusted.buyback_trigger_code = library_profile.buyback_trigger_code
    adjusted.buyback_trailing_code = library_profile.buyback_trailing_code
    adjusted.profit_sell_after_buyback_enabled = (
        library_profile.profit_sell_after_buyback_enabled
    )
    adjusted.normal_buy_enabled = library_profile.normal_buy_enabled
    mods = dict(adjusted.modules or {})
    src = dict(library_profile.modules or {})
    for k in (
        "net_profile_library",
        "library_version",
        "selected_profile_key",
        "profile_key",
        "headline",
        "canonical_headline",
        "why",
        "why_this_profile",
        "automatic_apply",
        "automatic_apply_label",
        "apply_policy",
        "reference_plan_only",
        "weekly_cycle_days",
        "grid_contract",
        "max_normal_grid_pct",
        "max_extreme_grid_pct",
        "operator_authored",
        "sealed_shape",
        "regime_behavior_spec",
    ):
        if k in src:
            mods[k] = src[k]
    adjusted.modules = mods
    adjusted.scenario.name = str(src.get("headline") or adjusted.scenario.name)
    return adjusted


def validate_library_invariants() -> List[str]:
    """Return human-readable invariant violations (empty = ok)."""
    errors: List[str] = []
    for key, vals in PROFILE_VALUES.items():
        base, sells, _st, buys, _bt, _ps, _pb, _pol = vals
        if len(sells) != 4 or len(buys) != 4:
            errors.append(f"{key}: expected 4+4 grids")
        sell_amt = [a for _, a in sells]
        buy_amt = [a for _, a in buys]
        if abs(sum(sell_amt) - 100.0) > 1e-9:
            errors.append(f"{key}: sell amounts != 100")
        if abs(sum(buy_amt) - 100.0) > 1e-9:
            errors.append(f"{key}: buy amounts != 100")
        if any(a < 10.0 for a in sell_amt + buy_amt):
            errors.append(f"{key}: amount < 10%")
        max_d = max([d for d, _ in sells] + [d for d, _ in buys])
        if key in _NORMAL_MAX_DIST_KEYS and max_d > 10.0 + 1e-9:
            errors.append(f"{key}: normal profile grid > 10% ({max_d})")
        if max_d > 15.0 + 1e-9:
            errors.append(f"{key}: grid > 15% ({max_d})")
        if not (0.0 <= float(base) <= 100.0):
            errors.append(f"{key}: invalid base {base}")
        if key not in PROFILE_COPY:
            errors.append(f"{key}: missing copy")
    return errors
