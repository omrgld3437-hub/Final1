"""Operator supplied 35-profile library used by Param Assistant and Dynamic Mode.

This is intentionally the only recommendation library consulted by the V6 live
resolver.  Profiles are still passed through the existing adjuster, exchange and
safety pipeline before they can be shown or deployed.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

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


# base, sell grids, sell trailing, buy grids, buy trailing,
# bought-coin profit sell (trigger/trailing), sold-coin profit buy (trigger/trailing),
# automatic apply policy
PROFILE_VALUES: Dict[str, Tuple[Any, ...]] = {
    "R1_STRONG_UPTREND": (70, [(4, 20), (8, 30), (13, 50)], 1, [(3, 40), (6, 60)], .7, (5, 1), (3, .7), "Açık"),
    "R1_PULLBACK": (60, [(4, 20), (8, 30), (13, 50)], 1, [(2, 15), (4, 25), (6.5, 30), (10, 30)], .6, (4.5, .9), (3.5, .6), "Açık"),
    "R1_TREND_COOLDOWN": (55, [(3, 25), (6.5, 35), (11, 40)], .8, [(4, 25), (7.5, 35), (12, 40)], .7, (4, .8), (4, .7), "Açık"),
    "R2_BALANCED_RANGE": (50, [(2, 20), (4, 25), (6.5, 25), (9.5, 30)], .5, [(2, 20), (4, 25), (6.5, 25), (9.5, 30)], .5, (3, .6), (3, .6), "Açık"),
    "R2_CALM_RANGE": (50, [(1.4, 20), (2.8, 25), (4.2, 25), (5.8, 30)], .35, [(1.4, 20), (2.8, 25), (4.2, 25), (5.8, 30)], .35, (2.2, .45), (2.2, .45), "Açık — net kâr filtresi sağlanırsa"),
    "R3_NOISY_RANGE": (45, [(3.5, 40), (7.5, 60)], .65, [(3.5, 40), (7.5, 60)], .65, (3.5, .7), (3.5, .7), "Açık — düşük işlem sıklığıyla"),
    "R3_DIRECTIONLESS_COMPRESSION": (45, [(2.5, 40), (5.5, 60)], .45, [(2.5, 40), (5.5, 60)], .45, (3, .55), (3, .55), "Açık — kırılım teyidine kadar kontrollü"),
    "R3_CONTROLLED_COMPRESSION": (50, [(1.8, 25), (3.6, 35), (5.8, 40)], .4, [(1.8, 25), (3.6, 35), (5.8, 40)], .4, (2.8, .5), (2.8, .5), "Açık"),
    "R3_UPTREND_COMPRESSION": (65, [(3, 10), (6, 20), (10, 30), (15, 40)], .8, [(3, 40), (6.5, 60)], .55, (4.5, .9), (3, .55), "Açık"),
    "R3_UPTREND_OVERHEAT": (50, [(1.8, 35), (3.8, 30), (6.5, 20), (10, 15)], .75, [(6, 35), (11, 65)], .9, (3.2, .75), (5, .9), "Açık — yeni alışlar yalnız derin seviyelerde"),
    "R3_UPPER_BAND_PROFIT_LOCK": (45, [(1.3, 35), (2.7, 30), (4.8, 20), (7.5, 15)], .55, [(4.5, 40), (8.5, 60)], .75, (2.4, .55), (4, .75), "Açık"),
    "R4_LIQUID_VOLATILE_RANGE": (50, [(4, 20), (8, 25), (13, 25), (20, 30)], 1, [(4, 20), (8, 25), (13, 25), (20, 30)], 1, (5, 1.1), (5, 1.1), "Açık"),
    "R4_MEDIUM_VOLATILE_RANGE": (50, [(3, 20), (6, 25), (9.5, 25), (14, 30)], .75, [(3, 20), (6, 25), (9.5, 25), (14, 30)], .75, (4, .85), (4, .85), "Açık"),
    "R4_CHOPPY_RANGE": (50, [(5, 25), (11, 35), (18, 40)], 1.2, [(5, 25), (11, 35), (18, 40)], 1.2, (6, 1.3), (6, 1.3), "Açık"),
    "R4_LOWER_BAND_BOUNCE": (60, [(3.5, 15), (7, 20), (12, 25), (18, 40)], 1, [(2, 20), (5, 35), (9, 45)], .8, (4.5, .95), (4, .85), "Açık"),
    "R4_OVERHEATED": (40, [(2, 35), (4.5, 30), (8, 20), (13, 15)], .9, [(6, 35), (12, 65)], 1, (3, .85), (5.5, 1), "Açık"),
    "R4_FRAGILE_LIQUID": (40, [(4, 30), (9, 35), (16, 35)], 1.2, [(7, 35), (14, 65)], 1.25, (4, 1.1), (6.5, 1.25), "Açık — savunmacı sınırlarla"),
    "R4_LOW_LIQUIDITY": (30, [(6, 40), (14, 60)], 1.5, [(16, 100)], 1.6, (4.5, 1.3), (8, 1.6), "Koşullu — likidite alt sınırları sağlanırsa"),
    "R4_RESTRICTED_UNSTABLE": (20, [(6, 40), (14, 60)], 1.6, [], None, (4, 1.4), None, "Kapalı"),
    "R5_CLEAN_BREAKOUT": (70, [(5, 10), (10, 20), (17, 30), (26, 40)], 1.2, [(4, 40), (8.5, 60)], .8, (6, 1.2), (3.5, .8), "Açık"),
    "R5_POST_BREAKOUT_COOLDOWN": (55, [(3, 20), (7, 25), (12, 25), (18, 30)], .95, [(4, 25), (8, 35), (13, 40)], .8, (4.5, .95), (4, .8), "Açık"),
    "R5_OVEREXTENDED": (40, [(1.5, 35), (3.5, 30), (6.5, 20), (10, 15)], 1, [(8, 35), (14, 65)], 1.05, (3, 1), (6, 1.05), "Açık — savunmacı"),
    "R5_HIGH_VOL_OVEREXTENDED": (30, [(3, 35), (7, 30), (13, 20), (21, 15)], 1.7, [], None, (3.5, 1.5), (9, 1.4), "Açık — yalnız satış ve kontrollü kâr alışı"),
    "R5_HIGH_VOL_CLEAN_MOMENTUM": (65, [(6, 10), (12, 20), (20, 30), (30, 40)], 1.5, [(5.5, 40), (11, 60)], 1, (7, 1.5), (5, 1), "Açık"),
    "R5_PARABOLIC_PUMP": (25, [(2, 35), (5, 30), (9, 20), (15, 15)], 1.8, [], None, (3, 1.6), (10, 1.5), "Açık — yalnız satış ve koşullu kâr alışı"),
    "R5_RECOVERY_GENERIC": (50, [(3, 25), (7, 35), (12, 40)], .85, [(3.5, 25), (7, 35), (11, 40)], .8, (4, .85), (3.5, .8), "Açık — kontrollü"),
    "R6_CONTROLLED_RECOVERY": (55, [(4, 15), (8, 20), (13, 25), (20, 40)], .9, [(3, 25), (6.5, 35), (10.5, 40)], .75, (4.5, .9), (3.5, .75), "Açık"),
    "R6_RECOVERY_BREAKOUT": (70, [(5, 10), (11, 20), (18, 30), (28, 40)], 1.2, [(4.5, 40), (9.5, 60)], .85, (6, 1.2), (4, .85), "Açık"),
    "R7_DOWNTREND": (25, [(2.5, 40), (6, 35), (11, 25)], .9, [(9, 30), (17, 70)], 1.1, (2.8, .9), (7, 1.1), "Koşullu — yalnız likidite ve veri güvenliyse"),
    "R7_UNSTABLE_DOWNSIDE": (15, [(4, 40), (10, 60)], 1.3, [], None, (2.5, 1.1), None, "Kapalı"),
    "R8_CRASH_PANIC": (10, [(7, 40), (14, 35), (24, 25)], 2, [], None, (5, 1.8), None, "Kapalı"),
    "R8_RECOVERY_RESTRICTED": (20, [(5, 30), (11, 35), (19, 35)], 1.7, [], None, (4, 1.5), None, "Kapalı"),
    "R8_CAPITULATION_PROBE": (10, [(10, 45), (20, 55)], 2, [], None, (6, 1.8), None, "Kapalı"),
    "R8_HARD_BLOCK": (0, [], None, [], None, None, None, "Kapalı"),
    "R8_LOW_LIQUIDITY_RESTRICTED": (0, [], None, [], None, None, None, "Kapalı"),
}


PROFILE_COPY: Dict[str, Tuple[str, str]] = {
    "R1_STRONG_UPTREND": ("Sistem Güçlü Yükseliş Trendi Algıladı", "Trend güçlü ve devam ediyor. Fiyat EMA200 üzerinde, yüksek tepeler korunuyor ve yükseliş momentumu güçlü."),
    "R1_PULLBACK": ("Sistem Güçlü Yükseliş İçinde Geri Çekilme Algıladı", "Ana trend yukarı, kısa vade düzeltme yapıyor. Yükseliş yapısı bozulmadı ancak fiyat kısa vadeli desteklere doğru geri çekiliyor."),
    "R1_TREND_COOLDOWN": ("Sistem Yükseliş Trendinde Kontrollü Soğuma Algıladı", "Yükseliş sürüyor fakat momentum zayıfladı. Ana yapı pozitif kalırken fiyatı kovalamamak ve USDT rezervini artırmak gerekiyor."),
    "R2_BALANCED_RANGE": ("Sistem Dengeli Aralık Algıladı", "Piyasa iki yönlü ve dengeli hareket ediyor. Belirgin trend yok; fiyat kararlı bir bant içinde destek ve direnç arasında gidip geliyor."),
    "R2_CALM_RANGE": ("Sistem Sakin Yatay Bölge Algıladı", "Yatay yapı kararlı, volatilite çok düşük. Fiyat dar bir bantta hareket ettiği için yakın ve simetrik gridler daha uygundur."),
    "R3_NOISY_RANGE": ("Sistem Zayıf ve Gürültülü Aralık Algıladı", "Yön yok fakat yapı temiz değil. Düşük volatiliteye rağmen sık yön değişimi bulunduğu için grid sayısı azaltılmalıdır."),
    "R3_DIRECTIONLESS_COMPRESSION": ("Sistem Yönsüz Sıkışma Algıladı", "Fiyat daralıyor, kırılım yönü henüz belli değil. Spot piyasada aşağı kırılım riski daha maliyetli olduğu için USDT rezervi hafif yüksek tutulur."),
    "R3_CONTROLLED_COMPRESSION": ("Sistem Düşük Volatiliteli Kontrollü Sıkışma Algıladı", "Daralma düzenli ve sert düşüş sinyali yok. Yapı kararlı olduğu için yakın fakat sınırlı sayıda iki yönlü grid kullanılabilir."),
    "R3_UPTREND_COMPRESSION": ("Sistem Yukarı Eğilimli Sıkışma Algıladı", "Ana yön yukarı, kısa vadeli hareket daralıyor. Yukarı kırılım ihtimali korunurken olası geri çekilme için sınırlı USDT rezervi bırakılır."),
    "R3_UPTREND_OVERHEAT": ("Sistem Yukarı Trendde Aşırı Isınma Algıladı", "Trend pozitif fakat kısa vadede aşırı alım var. Yeni alışlar derinleştirilir; mevcut coinlerde yakın seviyelerden kâr koruma öne çıkar."),
    "R3_UPPER_BAND_PROFIT_LOCK": ("Sistem Üst Banda Yakın Kontrollü Kâr Alma Algıladı", "Fiyat sakin piyasada üst banda yaklaştı. Trend teyidi zayıf olduğu için base azaltılır ve kârın bir bölümü erken korunur."),
    "R4_LIQUID_VOLATILE_RANGE": ("Sistem Likit ve Volatil Aralık Algıladı", "Oynaklık yüksek fakat piyasa likit ve iki yönlü. Geniş fiyat hareketlerini yakalamak için iki yönde geniş ve dengeli gridler gerekir."),
    "R4_MEDIUM_VOLATILE_RANGE": ("Sistem Orta Volatiliteli Aralık Algıladı", "Piyasa iki yönlü, volatilite orta seviyede. Gridler sakin piyasadan geniş; yüksek volatilite profilinden daha dar tutulur."),
    "R4_CHOPPY_RANGE": ("Sistem Dalgalı Aralık Algıladı", "Fiyat iki yönde sert ve düzensiz dalgalanıyor. Gereksiz işlem sayısını azaltmak için grid sayısı düşürülür ve aralıklar genişletilir."),
    "R4_LOWER_BAND_BOUNCE": ("Sistem Alt Banttan Tepki Fırsatı Algıladı", "Fiyat volatil aralığın alt bölümünde. Yukarı tepki ihtimali nedeniyle base hafif artırılır; ek alışlar daha derin seviyelere dağıtılır."),
    "R4_OVERHEATED": ("Sistem Üst Bantta Kontrollü Volatil Aralık Algıladı", "Fiyat üst bantta ve aşırı alım riski yüksek. Güçlü trend teyidi olmadığı için base azaltılır, satışlar yakın seviyelere ağırlıklandırılır."),
    "R4_FRAGILE_LIQUID": ("Sistem Kırılgan Fakat Likit Volatil Aralık Algıladı", "Likidite yeterli, coin yapısı kırılgan. Ani hareket riski nedeniyle base ve alış iştahı azaltılır; gridler geniş tutulur."),
    "R4_LOW_LIQUIDITY": ("Sistem Düşük Likiditeli Savunmacı Volatil Aralık Algıladı", "Spread veya hacim kalitesi zayıfladı. Emir sayısı azaltılır; yalnız küçük, geniş ve limit emir yapısı kullanılabilir."),
    "R4_RESTRICTED_UNSTABLE": ("Sistem Düşük Likiditeli ve Dengesiz Aralık Algıladı", "Fiyat yapısı ve emir gerçekleşme kalitesi güvenli değil. Yeni alış yapılmaz; mevcut base için yalnız referans satış planı tutulur."),
    "R5_CLEAN_BREAKOUT": ("Sistem Temiz Breakout ve Trend Devamı Algıladı", "Kırılım güçlü ve birden fazla sinyalle teyitli. Coin erken tüketilmez; satışlar yükselişin devamını izleyecek şekilde yukarı yayılır."),
    "R5_POST_BREAKOUT_COOLDOWN": ("Sistem Breakout Sonrası Kontrollü Soğuma Algıladı", "Kırılım korunuyor fakat momentum yavaşlıyor. USDT rezervi artırılır; yeni alımlar yalnız kontrollü geri çekilmelerde yapılır."),
    "R5_OVEREXTENDED": ("Sistem Yukarı Breakoutta Aşırı Isınmış Momentum Algıladı", "Fiyat denge bölgesinden fazla uzaklaştı. Yakın alışlar kapatılır; kâr koruma ve derin geri çekilmede yeniden alım öncelik kazanır."),
    "R5_HIGH_VOL_OVEREXTENDED": ("Sistem Yüksek Volatilite ve Aşırı Momentum Algıladı", "Tepe riski ile yüksek oynaklık birlikte bulunuyor. Normal alış tamamen kapatılır; sistem yalnız mevcut base satışını ve derin geri alışı yönetir."),
    "R5_HIGH_VOL_CLEAN_MOMENTUM": ("Sistem Yüksek Volatilitede Temiz Momentum Algıladı", "Yükseliş sağlıklı fakat fiyat hareketi geniş. Yüksek volatilite nedeniyle grid ve trailing aralıkları geniş; satışlar üst seviyelere ağırlıklıdır."),
    "R5_PARABOLIC_PUMP": ("Sistem Parabolik Pump Algıladı", "Fiyat çok kısa sürede olağan dışı yükseldi. Yeni alış kesin olarak kapatılır; mevcut base kademeli satılır ve geri alış yalnız derin düzeltmede yapılır."),
    "R5_RECOVERY_GENERIC": ("Sistem Genel Toparlanma Algıladı", "Fiyat düşüşten sonra pozitife döndü, teyit henüz sınırlı. Yön iyileşse de güçlü toparlanma oluşmadığı için dağılım dengeli tutulur."),
    "R6_CONTROLLED_RECOVERY": ("Sistem Kontrollü Toparlanma Algıladı", "Düşüş sonrası yapı belirgin biçimde iyileşiyor. Base dengeli biçimde artırılır; ancak güçlü breakout teyidi gelmeden agresifleşilmez."),
    "R6_RECOVERY_BREAKOUT": ("Sistem Düşüş Sonrası Recovery Breakout Algıladı", "Toparlanma güçlü kırılımla teyit edildi. Yükselişin devamından yararlanmak için base artırılır ve satışlar üst seviyelere yayılır."),
    "R7_DOWNTREND": ("Sistem Düşüş Trendi Algıladı", "Aşağı yönlü piyasa yapısı güçlü. Base düşük tutulur; alışlar derine, satışlar olası tepki yükselişlerine yerleştirilir."),
    "R7_UNSTABLE_DOWNSIDE": ("Sistem Dengesiz Volatilite ve Düşüş Riski Algıladı", "Aşağı yön riski yüksek ve piyasa yapısı düzensiz. Yeni alış yapılmaz; yalnız mevcut base için referans tepki satışları korunur."),
    "R8_CRASH_PANIC": ("Sistem Crash ve Sert Düşüş Algıladı", "Hızlı düşüş ve derin drawdown birlikte oluştu. Yeni alış ve kâr alışı kapatılır; mevcut base için yalnız referans tepki satış planı tutulur."),
    "R8_RECOVERY_RESTRICTED": ("Sistem Crash Sonrası Kontrollü Toparlanma Algıladı", "Kısa vadeli tepki var fakat crash riski sürüyor. Toparlanma tam teyit edilmediği için alış açılmaz; mevcut base tepki yükselişlerinde azaltılır."),
    "R8_CAPITULATION_PROBE": ("Sistem Kapitülasyon Crash ve Koşullu Probe Algıladı", "Çok derin düşüşten sonra sınırlı tepki oluştu. Otomatik probe yapılmaz; yalnız mevcut base için geniş referans satış seviyeleri tutulur."),
    "R8_HARD_BLOCK": ("Sistem Hard Block ve İşlem Yasağı Algıladı", "Birden fazla ağır risk sinyali işlem güvenliğini kaldırdı. Hiçbir yeni emir açılmaz; yeni sermaye USDT’de tutulur ve mevcut coin zorla satılmaz."),
    "R8_LOW_LIQUIDITY_RESTRICTED": ("Sistem Crash ile Birlikte Likidite Kısıtı Algıladı", "Crash koşullarına ciddi likidite sorunu eşlik ediyor. Alış, satış ve kâr döngüsü tamamen kapatılır; mevcut coin düşük likiditede zorla satılmaz."),
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


def select_profile_key(classified: Any, inp: V6InputContract) -> str:
    """Choose one of the 35 operator profiles from current engine signals."""
    hint = str(getattr(classified, "sub_profile_hint", "") or "")
    regime = str(getattr(classified, "regime_id", "R3") or "R3").upper()
    key = _HINT_MAP.get(hint)
    vol = float(inp.volatility_percentile or 0)
    spread = float(inp.spread_pct or 0)
    liquidity_weak = spread >= .10 or float(inp.volume_consistency or .5) < .35
    if regime == "R1":
        return key or "R1_STRONG_UPTREND"
    if regime == "R2":
        return "R2_CALM_RANGE" if vol < 25 else "R2_BALANCED_RANGE"
    if regime == "R3":
        return key or ("R3_NOISY_RANGE" if float(inp.range_stability or 0) < .45 else "R3_DIRECTIONLESS_COMPRESSION")
    if regime == "R4":
        if key:
            return key
        if str(inp.asset_fragility_class or "F1").upper() in ("F2", "F3"):
            return "R4_FRAGILE_LIQUID" if not liquidity_weak else "R4_LOW_LIQUIDITY"
        if vol < 60:
            return "R4_MEDIUM_VOLATILE_RANGE"
        if float(inp.range_stability or 0) < .40:
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


def build_profile(key: str, classified: Any, severity: str) -> V6CatalogProfile:
    values = PROFILE_VALUES[key]
    base, sells, sell_trail, buys, buy_trail, profit_sell, profit_buy, apply_policy = values
    title, reason = PROFILE_COPY[key]
    auto_apply = not str(apply_policy).startswith("Kapalı")
    scenario = ScenarioIdentity(
        regime_id=key.split("_", 1)[0],
        sub_id=str(getattr(classified, "sub_id", "01")),
        micro_id=str(getattr(classified, "micro_id", "001")),
        behavior_id=str(getattr(classified, "behavior_id", "PB01")),
        severity=severity,
        name=title,
    )
    return V6CatalogProfile(
        profile_id=key,
        scenario=scenario,
        base_allocation_pct=int(base),
        quote_allocation_pct=100 - int(base),
        initial_base_allocation=base > 0,
        normal_buy_enabled=bool(buys),
        buy_grids=[GridLevel(-float(d), int(a)) for d, a in buys],
        sell_grids=[GridLevel(float(d), int(a)) for d, a in sells],
        sell_trailing_code=trailing_code_from_pct(float(sell_trail or .5)),
        buy_trailing_code=trailing_code_from_pct(float(buy_trail or .5)),
        buyback_after_sell_enabled=profit_buy is not None,
        buyback_trigger_code=profit_code_from_pct(float(profit_buy[0] if profit_buy else 5)),
        buyback_trailing_code=trailing_code_from_pct(float(profit_buy[1] if profit_buy else .5)),
        profit_sell_after_buyback_enabled=profit_buy is not None and profit_sell is not None,
        profit_sell_trigger_code=profit_code_from_pct(float(profit_sell[0] if profit_sell else 5)),
        profit_sell_trailing_code=trailing_code_from_pct(float(profit_sell[1] if profit_sell else .5)),
        modules={
            "net_profile_library": True,
            "profile_key": key,
            "headline": title,
            "why": reason,
            "automatic_apply": auto_apply,
            "automatic_apply_label": apply_policy,
            "regime_behavior_spec": True,
        },
    )


def resolve_net_profile(classified: Any, inp: V6InputContract, severity: str) -> V6CatalogProfile:
    return build_profile(select_profile_key(classified, inp), classified, severity)

