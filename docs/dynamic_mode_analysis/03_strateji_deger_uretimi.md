# 03 — Strateji Değer Üretimi & Agresiflik/Pasiflik (S171–S255)

> Kaynak: `app/botengine/dynamic/strategy_engine.py`. İşaretler: ✅ doğru · ⚠️ orta · 🔴 önemli.
>
> **Temel formüller:** `atr_c = clamp(atr_pct_5m, 0.15, 6.0)` · `base_step = 0.7×atr_c` · `step = max(0.05, base_step×step_mult)` · `grid_i trigger = step×(i+1)` · `trail = max(0.15, 1.0×atr_c×trail_mult)` · `tp_rise = max(0.5, 2.5×atr_c×tp_rise_mult)` · `tp_drop = max(0.15, 0.4×atr_c)` · `re_drop = max(0.5, 2.0×atr_c)` · `re_rise = max(0.15, 0.4×atr_c)`.

## A. Grid step üretimi (S171–S187)

**S171. Grid step neye bağlı?** Yalnız 5m ATR'ye (`0.7×atr_c`) ve rejim `step_mult`'ına. ✅ Vol-ölçekli (doğru fikir).

**S172. K_ATR_GRID_STEP=0.7 katsayısı nereden?** Sezgisel sabit (gerekçe yok). ⚠️ Kalibrasyon/backtest dayanağı belgelenmemiş.

**S173. Grid trigger'ları geometrik mi liner mi?** Liner: `step×(i+1)` (1,2,3,4×step). ✅ Kod yorumu "geometrik trigger patlar" diyerek liner seçmiş — vol-ağır coin için güvenli.

**S174. Manuel grid yüzdeleri korunuyor mu?** 🔴 Hayır — manuel trigger %'leri **tamamen atılır**, yalnız **adet** korunur. Kullanıcının -%20 gridi dinamik modda yok olur.

**S175. Düşük ATR'de gridler ne kadar dar olur?** ATR 0.3, LOW_VOL (0.8): step=0.168% → gridler 0.17/0.34/0.50/0.67%. 🔴 **Fee'nin altında** (round-trip ~0.2%) — kâr etmeyen tetikler riski.

**S176. Bu çok-dar grid sorun mu?** 🔴 Evet — 4 grid yalnız %0.67 derinlik kaplar (DCA değil, scalping); ve step < fee. Min-net-profit guard kısmen korur ama gridler boşuna armlanır.

**S177. Yüksek ATR'de gridler ne olur?** ATR 6 (ceil), DUMP (2.0): step=8.4 → her seviye 8%'e clamp'lenir → **tüm gridler 8%** (degenerate, tek seviye). 🔴

**S178. Degenerate grid (hepsi 8%) zararı?** 4 ayrı emir aynı tetik fiyatında → eş-zamanlı, gereksiz parçalanma; DCA derinliği yok. 🔴 Yüksek-vol coin'de DCA çökmüş olur.

**S179. ATR_CEIL=6 yeterli mi?** ⚠️ 20%+ ATR'li coin 6 sayılır → grid alt-boyutlu. Aşırı-vol coin için yetersiz tavan.

**S180. Dinamik grid maksimum derinliği nedir?** Risk `BOUNDS["grid_step_pct"]` max=8 → **hiçbir dinamik grid 8%'i geçemez**. 🔴 Dinamik modda DCA derinliği yapısal olarak ≤%8.

**S181. Kullanıcı -%20 DCA istiyorsa dinamik modda olur mu?** 🔴 Hayır — gridler 8%'e clamp'lenir. Kullanıcının derin DCA niyeti dinamik modda gerçekleşmez.

**S182. Bu, önceki turda eklenen derinlik koruması ile çelişir mi?** Hayır ama bağlamı değiştirir: derinlik koruması **efektif** (≤8%) gridi kullanır; yani dinamik modda guard ≈ 8%+5%=13% fiyat düşüşü. Manuel-derin-grid senaryosu dinamik modda zaten oluşmaz. ⚠️ İkisi tutarlı ama 8% cap asıl kısıtlayıcı.

**S183. Grid adımı sembolün tick/lot adımına göre yuvarlanıyor mu?** Hayır — strateji katmanında yüzde; emir anında `validate_*_qty` yuvarlar. ✅ Ayrım doğru.

**S184. step alt sınırı 0.05% mantıklı mı?** `max(0.05, ...)` — çok düşük ATR'de bile minimum 0.05% adım. ✅ Sıfır-adım koruması; ama yine fee altı.

**S185. Buy ve sell grid adımı farklı mı?** 🔴 Hayır — ikisi de aynı `base_step×step_mult`. Aynı tetik %'leri. Asimetri yok.

**S186. Trend yukarıda sell daha dar, buy daha geniş olmalı değil mi?** Evet (kâr-al hızlı, dip-yakalama yavaş) — ⚠️ ama uygulanmıyor; simetrik.

**S187. Grid step rejimle yeterince ayrışıyor mu?** step_mult: LVR 0.8, SQ 0.9, TU 1.2, HVR 1.4, TD 1.5, BO 1.6, DUMP 2.0. ✅ Yön doğru (vol/risk arttıkça geniş); ⚠️ ama 8% cap üst rejimlerde farkı siler.

## B. Grid qty dağılımı (S188–S195)

**S188. `buy_levels_mult` qty'yi etkiliyor mu?** 🔴 **HAYIR — hiç kullanılmıyor.** REGIME_TUNING'de tanımlı (DUMP 0.3, TD 0.5...) ama `suggest()` referans vermiyor. Rejime özgü alım kısıtı ölü.

**S189. Qty dağılımı nasıl?** Geometrik ağırlık (`growth^i`) manuel toplama normalize. Sells growth 1.10, buys 1.20. ✅ (H6 sonrası manuel toplam korunur.)

**S190. Buy growth 1.20 > sell 1.10 — neden?** Alımda maliyet ortalaması için derine doğru artan miktar (cost averaging). ✅ Mantıklı; anti-martingale (≤1.5) ile sınırlı.

**S191. Growth değerleri rejime bağlı mı?** 🔴 Hayır — sabit (1.10/1.20). DUMP'ta da TU'da da aynı dağılım şekli. Rejim qty *şeklini* etkilemiyor.

**S192. DUMP_RISK'te alım miktarı kısılıyor mu?** 🔴 Hayır — yalnız `position_state` (kullanım≥0.7) yarıya iner; rejim qty'yi azaltmaz (buy_levels_mult ölü). DUMP'ta base %15 (az başlangıç base) var ama quote yine gridlere tam dağıtılır.

**S193. position_state savunması yeterli mi?** Kısmen — yalnız buy seviyelerinin %70'i dolduğunda devreye girer ve yalnız o tur. ⚠️ Rejim-bağımsız; DUMP'ın ilk alımlarını kısmaz.

**S194. Sell qty dağılımı base'i tüketir mi?** Manuel toplam kadar (örn. %45). ✅ H6 ile çekirdek pozisyon korunur.

**S195. Qty anti-martingale ile çelişir mi?** Hayır — growth 1.10/1.20 < cap 1.5; risk motoru gerekirse keser. ✅ Tutarlı.

## C. Trailing üretimi (S196–S204)

**S196. Buy ve sell trailing farklı mı?** 🔴 Hayır — `sell_trail = buy_trail = max(0.15, atr_c×trail_mult)`. Birebir aynı.

**S197. Trailing neye bağlı?** ATR × rejim `trail_mult`. ✅ Vol-ölçekli.

**S198. trail_mult ayrışması?** LVR 0.8, SQ 1.0, DUMP 1.0, TD 1.2, HVR 1.3, TU 1.4, BO 1.5. ✅ Vol/trend arttıkça geniş trailing — doğru (erken stop-out önler).

**S199. Trailing tabanı 0.15% uygun mu?** Spot'ta 0.15% altı gürültü sayılır. ✅ Makul taban.

**S200. Trailing üst sınırı?** Risk `BOUNDS["trailing_pct"]` max=5.0. ATR 6×1.5(BO)=9→clamp 5. ✅ Aşırı geniş trailing engellenir.

**S201. Sell trailing buy'dan bağımsız ayarlanmalı mıydı?** Evet — örn. TU'da kâr-al trailing'i dar, dip-al trailing'i geniş olabilirdi. ⚠️ Simetri fırsat kaçırıyor (S186 ile aynı tema).

**S202. Düşük ATR'de trailing çok mu dar?** ATR 0.3×0.8=0.24% → dar ama ≥0.15 taban. ⚠️ Dar trailing erken tetikler (whipsaw), ama floor koruyor.

**S203. Yüksek ATR'de trailing yeterince geniş mi?** ATR 3×1.4(TU)=4.2% → geniş. ✅ Trendi takip eder. (6×... → 5 cap.)

**S204. Trailing ATR ile lineer — uygun mu?** Evet, trailing'in vol ile ölçeklenmesi standart pratik. ✅

## D. Kâr-alma & yeniden-giriş eşikleri (S205–S214)

**S205. tp_rise (kâr-al tetiği) neye bağlı?** `2.5×atr_c×tp_rise_mult`, taban 0.5. ✅ Vol + rejim ölçekli.

**S206. tp_rise_mult ayrışması?** LVR 0.9, SQ/DUMP/UNK 1.0, HVR 1.1, TD 1.3, BO 1.5, TU 1.6. ✅ TU'da geç kâr-al (trendi sür) — doğru.

**S207. tp_drop (kâr-al trailing) rejime bağlı mı?** 🔴 Hayır — saf `0.4×atr_c`, taban 0.15. Tüm rejimlerde aynı trailing sıkılığı.

**S208. re_drop (yeniden-giriş tetiği) rejime bağlı mı?** 🔴 Hayır — saf `2.0×atr_c`, taban 0.5. TD'de daha derin re-entry istenebilirdi; yapılmıyor.

**S209. re_rise (yeniden-giriş trailing) rejime bağlı mı?** 🔴 Hayır — saf `0.4×atr_c`, taban 0.15.

**S210. Kâr/giriş eşiklerinin yarısı rejim-kör — sorun mu?** ⚠️ Evet, kısmi tutarsızlık: tp_rise rejim-duyarlı ama tp_drop/re_drop/re_rise değil. Rejim mantığı eşiklerin yalnız birinde tam yansıyor.

**S211. tp_rise tabanı 0.5% fee-üstü mü?** Round-trip ~0.2% < 0.5% → ✅ kâr-al en az fee'yi karşılar.

**S212. re_drop 2.0×ATR mantıklı mı?** Kâr-sat sonrası ~2 ATR düşünce yeniden gir. ✅ Makul; ama rejim-kör (S208).

**S213. DUMP'ta re-entry agresif mi?** re_drop saf ATR → DUMP'ta da normal derinlik. ⚠️ DUMP'ta yeniden-girişin daha temkinli olması beklenirdi (buy_levels_mult ölü olduğundan yok).

**S214. Kâr-al tutarı (qty) ne kadar?** Sell gridleri zaten kâr-al ladder'ı; ayrıca cycle-close profit-exit var. Dinamik yalnız %'leri ayarlar, qty manuel-toplam korunur. ✅

## E. Allokasyon (base/quote) (S215–S225)

**S215. base_pct nereden?** Rejim `base_pct_target`, sonra [10,80] clamp. ✅

**S216. base_pct_target ayrışması?** DUMP 15, TD 25, HVR 40, SQ 45, LVR/BO/UNK 50, TU 60. ✅ Risk arttıkça az base (nakit). Mantıklı.

**S217. TU'da base %60 doğru mu?** Trendde daha çok base (yükselişe katıl). ✅ Ama `buy_levels_mult=0.8` (alımları kıs) ölü olduğundan, TU'da hem çok base hem tam alım → "runup'a ekleme yapma" niyeti yok (S188).

**S218. DUMP'ta base %15 yeterince defansif mi?** Başlangıç dağılımı olarak ✅ (çoğu nakit). Ama o nakit gridlere tam dağıtılır (S192). Yani "nakit tut" kısmen "nakdi dibe yatır"a dönüşebilir.

**S219. TRENDING_DOWN düşük confidence yumuşatması?** `TD & conf<0.6 → base=max(25,35)=35`. ✅ Belirsiz düşüşte aşırı defansiften kaçınır. (Confidence'ın tek gerçek kullanımı.)

**S220. base+quote=100 garanti mi?** Evet — `quote=100−base`, risk motoru da normalize eder. ✅

**S221. base [10,80] sınırları uygun mu?** ✅ Ne tam nakit ne tam base; grid için dengeli aralık.

**S222. Allokasyon turlar arası rate-limit'li mi?** Evet — `base_alloc_pct` skaler rate-limit'e (60%) tabi. ✅ Sert sıçrama önlenir.

**S223. Allokasyon smoothing'li mi?** Evet — `smooth_against_prev` base'i prev ile harmanlar (alpha 0.5). ✅ Çift tampon (smoothing + rate-limit).

**S224. Allokasyon değişimi mevcut pozisyonu nasıl etkiler?** Yeni tur başında hedef; strateji base/quote referansını tur başında belirler. ✅ Tur-içi sabit.

**S225. base hedefine ulaşmak için zorla al/sat olur mu?** Strateji `_quote_ref_for_buy_grid` vb. ile hedefi referans alır; ani rebalance yerine grid akışıyla. ✅ Şok rebalance yok.

## F. Agresiflik / pasiflik dengesi (S226–S245)

**S226. "Gereksiz agresif" değer üretilebilir mi?** Evet, birkaç durumda: (a) yüksek ATR + DUMP'ta gridler 8'e çöküp tüm quote tek seviyede dibe yatırılabilir (S178/S192); (b) buy_levels_mult ölü olduğundan riskli rejimlerde alım kısılmaz. 🔴

**S227. "Gereksiz pasif" değer üretilebilir mi?** Evet: düşük ATR'de gridler fee-altı/çok-dar → fazla işlem, küçük kâr; trailing 0.15 tabanında whipsaw. ⚠️

**S228. En agresif rejim hangisi?** Değerce DUMP (step 2.0) ama base %15. Net: geniş gridli, nakit-ağır → aslında defansif konumlanma. ✅ (Niyet doğru, ama qty kısıtı eksik.)

**S229. En pasif rejim hangisi?** LOW_VOL_RANGING (step 0.8, trail 0.8, dar her şey). ✅ Sakin piyasada dar grid mantıklı (daha çok dolum).

**S230. Agresiflik ATR ile lineer mi büyüyor?** Evet — step/trail/tp hepsi atr_c ile lineer. ✅ Tutarlı; ama clamp'ler uçları kesiyor.

**S231. Aşırı agresifliğe karşı kaç kat koruma var?** 3: ATR clamp [0.15,6] → rejim mult → risk BOUNDS clamp → rate-limit. ✅ Çok katmanlı.

**S232. Aşırı pasifliğe (atalet) karşı koruma?** Yalnız tabanlar (step 0.05, trail 0.15, tp 0.5). ⚠️ Fee-altı grid'i engelleyen açık bir "min ekonomik adım" yok.

**S233. Fee-farkındalık dinamik değerlerde var mı?** 🔴 Hayır — dinamik step/trailing fee'yi hesaba katmaz. Strateji'nin min_net_profit guard'ı ayrı katman; ama grid spacing fee-altı olabilir (S175).

**S234. Önerilen min grid step fee'ye bağlanmalı mıydı?** Evet — `step ≥ k×(buy_fee+sell_fee)` gibi bir taban mantıklı olurdu. ⚠️ Yok.

**S235. Yüksek ATR'de aşırı geniş trailing kâr kaçırır mı?** Trailing 5'e clamp'li; geniş trailing trendde iyi, range'de kâr kaçırabilir. ⚠️ Rejim trail_mult bunu kısmen yönetiyor (LVR 0.8).

**S236. Agresiflik confidence'a göre azalıyor mu?** 🔴 Hayır (S72) — düşük güvende bile tam agresif.

**S237. Düşük likiditede agresiflik kısılıyor mu?** 🔴 Hayır — spread/volume kullanılmıyor (S140/S139). İlliquid coin'de aynı agresiflik → kötü dolum.

**S238. Pozisyon derinleştikçe (çok buy fired) temkin artıyor mu?** Evet — `used_ratio≥0.7 → buy qty yarı`. ✅ Tek gerçek pozisyon-farkında savunma.

**S239. Bu 0.7 eşiği uygun mu?** Buy seviyelerinin %70'i dolunca. ⚠️ Sert eşik; kademeli azaltma (0.5→0.7→0.9) daha pürüzsüz olurdu.

**S240. Agresiflik/pasiflik genel dengesi?** Yön doğru (vol↑→geniş, risk↑→az base) ✅; ama (a) buy_levels_mult ölü, (b) confidence kullanılmıyor, (c) fee/likidite gözetilmiyor → denge **eksik kalibre**. 🔴/⚠️

**S241. Değerler "olması gerektiği gibi" hareket ediyor mu?** Büyük resimde ✅ (ATR↑→grid genişler, trend↑→base artar). Detayda ⚠️ (uçlarda degenerate/fee-altı; rejim niyetinin yarısı qty'de uygulanmıyor).

**S242. Bir rejim değişiminde değerler ne kadar zıplar?** Smoothing (0.5) + rate-limit (60%) skalerleri sınırlar; gridler sınırsız (ATR'yi takip eder, tasarım gereği). ✅/⚠️

**S243. Tek bir kötü ATR okuması tüm tur agresifliğini bozar mı?** Evet — snapshot tur boyu sabit; forming-mum şişmiş ATR tüm tur geniş grid verir. ⚠️ (Tur kısa ise düzelir.)

**S244. Değerler asla negatif/sıfır olabilir mi?** Hayır — tüm tabanlar pozitif (`max(...)`), risk motoru ek koruma. ✅

**S245. Değerler manuel config'ten "çok mu" uzaklaşır?** Gridler tamamen yeniden kurulur (manuel %'ler atılır), allokasyon rejim hedefine gider. ⚠️ Manuel-taban yalnız adet + fallback'te; değerler büyük ölçüde dinamik.

## G. Rejim ↔ değer tutarlılığı (S246–S255)

**S246. TD rejiminde değerler defansif mi?** base 25 ✅, geniş grid (1.5) ✅, ama alım qty kısılmaz (S192) 🔴. Yarı-defansif.

**S247. TU rejiminde değerler trend-takipçi mi?** base 60 ✅, geniş trailing (1.4) ✅, geç kâr-al (1.6) ✅; ama "runup'a ekleme yapma" yok (S217) ⚠️.

**S248. LVR'de değerler grid-dostu mu?** Dar grid/trailing, dengeli base ✅. Sakin piyasa için doğru. (Ama fee-altı riski S175.)

**S249. HVR'de chop koruması var mı?** Geniş grid (1.4), az base (40) ✅; whipsaw'a karşı geniş trailing (1.3) ✅. İyi.

**S250. SQUEEZE değerleri "patlama bekle" yansıtıyor mu?** ⚠️ Neredeyse nötr (0.9/1.0/45) — ayırt edici konumlanma zayıf (S48).

**S251. BREAKOUT değerleri yön-belirsizliğe uygun mu?** Geniş her şey (1.6/1.5/1.5) ✅; ama yön-kör (aşağı breakout'ta nötr base) 🔴 (S35).

**S252. DUMP değerleri panik-koruması mı?** base 15 ✅ geniş grid ✅, ama qty kısıtı yok 🔴. Kısmen.

**S253. UNKNOWN değerleri manuel-nötr mü?** Tüm mult 1.0, base 50 ✅. Doğru — bilinmeyende nötr.

**S254. Rejim tuning yönleri genel olarak doğru mu?** ✅ Evet — base/grid/trailing/tp yönleri ekonomik olarak mantıklı. Asıl boşluk **uygulanmayan** (buy_levels_mult) ve **kısmi** (kâr/giriş eşikleri rejim-kör) kısımlar.

**S255. Tuning tablosu backtest ile kalibre edilmiş mi?** ⚠️ Belirti yok — değerler sezgisel görünüyor; gerekçe/backtest belgesi yok. Kalibrasyon doğrulanmamış.
