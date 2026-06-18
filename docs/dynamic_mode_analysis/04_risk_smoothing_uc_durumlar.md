# 04 — Risk Motoru, Smoothing, Snapshot & Uç Durumlar (S256–S320)

> Kaynak: `risk_engine.py`, `strategy_engine.smooth_against_prev`, `cycle_manager.py`, `safety_gate.py`. İşaretler: ✅ doğru · ⚠️ orta · 🔴 önemli.

## A. Risk motoru — clamp & fallback (S256–S270)

**S256. Risk motoru son söz sahibi mi?** Evet — `apply_safety` her öneriyi clamp/fallback/rate-limit'ten geçirir; hiçbir öneri ham uygulanmaz. ✅ Çekirdek güvenlik ilkesi.

**S257. Hard bound'lar neler?** base_alloc [10,80], quote [20,90], grid_step [0.10,8], grid_qty [1,100], trailing [0.15,5], tp_rise [0.30,15], tp_drop [0.10,5], re_drop [0.30,15], re_rise [0.10,5]. ✅ Makul aralıklar.

**S258. NaN/Inf önerisi ne olur?** `_finite` false veya ≤0 → ilgili alan **manuel config fallback**'ine düşer + `fallbacks[]` log. ✅ "Dinamik kapalıymış gibi" güvenli düşüş.

**S259. Clamp sessiz mi?** Hayır — her clamp `clamps[]`'e yazılır (operatör görür). ✅ Şeffaf.

**S260. grid_step üst sınırı 8 — bu dinamik DCA derinliğini kısıtlıyor (S180), risk mi tasarım mı?** Hem hem: 8% tek-grid tavanı aşırı-derin tek sıçramayı önler (risk) ama çok-gridli derin DCA'i de imkânsız kılar (tasarım yan etkisi). 🔴 Bilinçli gözden geçirilmeli.

**S261. grid_qty alt sınırı 1 — çok-gridli dağılımda toplam bozulur mu?** Bireysel qty <1 ise 1'e çıkar; bu manuel toplamı hafif aşabilir. ⚠️ Çok sayıda küçük grid'de toplam sapması (nadir).

**S262. Monotonluk nasıl sağlanıyor?** `out[i].pct < out[i-1].pct` ise öncekine eşitlenir. ✅ Tetikler azalmaz. (Yüksek ATR'de hepsi 8'e eşitlenir → degenerate, S177.)

**S263. Anti-martingale nasıl?** Ardışık qty oranı >1.5 ise `prev×1.5`'e kesilir. ✅ Martingale (katlama) engellenir.

**S264. Anti-martingale yön doğru mu (yalnız artış)?** Evet — yalnız yukarı oranı kısar; azalan dağılıma dokunmaz. ✅

**S265. allocation pair normalize ediliyor mu?** Evet — base clamp + rate-limit + `quote=100−base`, quote<20 ise düzeltme. ✅ Toplam 100 garanti.

**S266. quote_alloc bound'u (20–90) base bound'u (10–80) ile tutarlı mı?** base∈[10,80] → quote∈[20,90]. ✅ Tutarlı.

**S267. Fallback değeri prev_applied mı base_cfg mi?** NaN/invalid → **base_cfg** (manuel). Rate-limit ayrı olarak prev_applied'e bakar. ✅ Doğru ayrım (fallback manuele, hız limiti önceki uygulanmışa).

**S268. Grid boşsa ne olur?** `fallbacks` + manuel grid kopyası. ✅ Asla boş grid uygulanmaz.

**S269. Risk motoru rejimi/feature'ı biliyor mu?** Hayır — yalnız öneri + base_cfg + prev. ✅ Temiz katman ayrımı (saf clamp).

**S270. Risk clamp'leri "olması gerekenden" değer üretir mi?** Clamp yalnız sınıra çeker (değer üretmez); fallback manuel değeri kullanır. ✅ Güvenli.

## B. Rate-limit (turlar arası) (S271–S280)

**S271. Rate-limit neye uygulanıyor?** Skalerlere: base_alloc, sell/buy_trailing, tüm profit_* (4 alan). ✅

**S272. Rate-limit gridlere uygulanıyor mu?** 🔴 Hayır — grid step/qty rate-limit'siz (tasarım: gridler ATR'yi anında takip etmeli). ⚠️ Doküman bunu netleştirdi (önceki tur).

**S273. Maksimum göreli değişim?** %60 (`MAX_RELATIVE_CHANGE=0.6`). ✅ Sert sıçramayı sınırlar.

**S274. Rate-limit prev ≤0/None ise?** Uygulanmaz (ilk tur). ✅ Doğru — referans yokken sınırlama yok.

**S275. Rate-limit smoothing'den sonra mı önce mi?** Smoothing (suggest sonrası) → sonra risk clamp+rate-limit. İkisi de prev_applied'e bakar → çift tampon. ✅

**S276. Çift tampon (smoothing+rate-limit) aşırı atalet yaratır mı?** Düşük taban değerlerde (örn. trailing 0.15) %60 = 0.09/tur, smoothing 0.5 ile birleşince yavaş uyum. ⚠️ Hızlı vol değişiminde param geç yetişir (gridler hariç).

**S277. Rate-limit yön-asimetrik mi?** Hayır — yukarı/aşağı simetrik (`±max_delta`). ✅

**S278. Rate-limit clamp'ten önce mi sonra mı?** Önce clamp (bound), sonra rate-limit; sonra base için tekrar bound. ✅ Sıra mantıklı.

**S279. Rate-limit'li değer tekrar bound dışına çıkabilir mi?** base için sonradan `max(lo,min(hi,...))` var; diğerlerinde rate-limit bound içinden başladığı için güvenli. ✅

**S280. Rate-limit aşırı vol-spike'ı engelliyor mu (test)?** Evet — `test_rate_limiter_prevents_violent_jumps_across_cycles` doğruluyor. ✅

## C. Smoothing (S281–S290)

**S281. Smoothing ne yapıyor?** Skaler alanları prev_applied ile EMA harmanlar (alpha 0.5). ✅ Turlar arası yumuşatma.

**S282. Gridler smooth'lanıyor mu?** Hayır — "shape aynı, sadece sayılar değişir, yeni değerleri al". ⚠️ Gridler ne smooth ne rate-limit (ATR'yi tam takip).

**S283. Alpha 0.5 sabit mi?** Evet. ⚠️ Confidence'a göre uyarlanmıyor (düşük güvende daha çok prev'e yaslanmak mantıklı olurdu — S77).

**S284. Smoothing prev yoksa?** Ham yeni değerleri kullanır + reason. ✅ İlk tur doğru.

**S285. Smoothing quote'u tutarlı tutuyor mu?** `quote=100−base` smoothing sonrası yeniden hesaplanıyor. ✅

**S286. Smoothing invalid prev'de?** `_b` float dönüşümü başarısızsa `cur` (ham) döner. ✅ None-safe.

**S287. Smoothing tp_drop/re_* dahil mi?** Evet — tüm 6 skaler profit/trailing harmanlanıyor. ✅ (Üretimde rejim-kör olsalar da smoothing kapsıyor.)

**S288. Smoothing + rate-limit birlikte mantıklı mı?** Evet — smoothing yön/yumuşaklık, rate-limit sert tavan. ✅ Tamamlayıcı.

**S289. Smoothing rejim değişiminde "yapışkanlık" yaratır mı?** Evet — yeni rejim değerleri prev ile harmanlanır → 1 turda tam geçmez. ✅ İstenen (anti-spam).

**S290. Smoothing gridleri kapsamadığından grid-param uyumsuzluğu olur mu?** Gridler hemen yeni, skalerler yavaş → bir tur boyunca grid (yeni ATR) ile trailing (yarı-eski) hafif uyumsuz olabilir. ⚠️ Küçük etki.

## D. Snapshot yaşam döngüsü (S291–S305)

**S291. Snapshot ne zaman kurulur?** `need_recompute` true: flag (tur kapanışı), snapshot yok, veya cycle_id değişti. ✅

**S292. Tur içinde snapshot değişmez mi?** Evet — immutable; tur boyu aynı `applied`. ✅ Anti-spam.

**S293. Tur içi her tick overlay yeniden uygulanıyor mu?** Evet — cfg raw'dan rebuild edilebildiği için her tick `apply_overlay`. ✅ Tutarlılık.

**S294. Manuel taban her tur temiz mi (H0)?** Evet — orchestrator `DcaGridTrailingConfig(raw).to_dict()` ile overlay'siz manuel taban geçiriyor. ✅ Base-drift düzeltildi.

**S295. Stale veride snapshot ne yapar?** Önceki `applied`'i kopyalar (yoksa manuel mirror), `data_fresh=False`, rejim korunur. ✅ Çökmez.

**S296. History ring buffer kaç tur?** 20 (`HISTORY_MAX`). ✅ Salınım/drift izlemeye yeter.

**S297. History stale turu işaretliyor mu?** Evet — `stale:True` girdisi. ✅

**S298. Snapshot disk/DB'ye yazılıyor mu?** State içinde (`save_state`); cycle_manager yan etkisiz, orchestrator persist eder. ✅ Temiz ayrım.

**S299. Snapshot overlay yalnız izinli alanları mı değiştiriyor?** Evet — `_OVERLAY_FIELDS` (10 alan); max_buy_levels/daily_loss/symbol/fee vb. asla. ✅

**S300. Dinamik kapanınca snapshot temizleniyor mu?** Evet — `is_dynamic_mode_active` false → `state.pop("dynamic_snapshot")`. ✅ UI eski veri göstermez.

**S301. recompute flag güvenli tüketiliyor mu?** `need_recompute` içinde `state.pop(...)` — predicate yan etkili ama tek çağrı/tick. ⚠️ İsim yanıltıcı, davranış güvenli.

**S302. cycle_id None/0 ise?** `int(state.get("cycle_id") or 1)` → 1. ✅ Güvenli varsayılan.

**S303. Snapshot reasons/clamps/fallbacks UI'ya taşınıyor mu?** Evet — engine event `DYN_SNAPSHOT` + detay API. ✅ Şeffaf.

**S304. İlk tur snapshot'ı olmadan grid banner boş mu?** Evet — `applied` boşsa banner görünmez; ilk tur bitince dolar. ✅ (Debug checklist'te not.)

**S305. Snapshot immutability rejim tepkiselliğini sınırlıyor mu?** Evet — uzun turda rejim donuk (S61). ⚠️ Bilinçli ödünleşme; tur-içi koruma emergency + depth guard.

## E. Uç durumlar & sayısal kararlılık (S306–S320)

**S306. price=0/None snapshot'ta?** features `data_fresh=False` (`price<=0`) → stale path. ✅

**S307. reference_price=0 derinlik korumasında?** Guard atlanır (fail-safe), equity stop devreye girer. ✅ (Önceki tur testi doğruluyor.)

**S308. Tüm indikatörler None (yeni coin)?** atr+adx None → UNKNOWN → nötr tuning; veya data_fresh=False → stale. ✅ Çökmez.

**S309. Bölme sıfıra karşı korumalar?** ATR/ADX/BBW/slope/vol_z hepsinde payda kontrolü var. ✅ Kapsamlı.

**S310. Çok büyük ATR (örn. 50%) taşma yapar mı?** `_atr_clamped` 6'ya, risk grid 8'e, trailing 5'e clamp. ✅ Taşma yok (ama alt-boyut, S179).

**S311. Negatif fiyat/qty mümkün mü?** Tüm üretimde `max(...)` pozitif taban + risk clamp. ✅ İmkânsız.

**S312. round(...,4) yeterli hassasiyet mi?** Yüzde değerler için ✅; emir anında ayrı tick/lot yuvarlama var.

**S313. Çok sayıda grid (örn. 20) performansı?** O(n) döngüler; n küçük (genelde ≤10). ✅ Önemsiz.

**S314. Cache 256 sınırı taşarsa veri kaybı?** En eski atılır, yeniden fetch'lenir. ✅ Doğruluk korunur (yalnız ek REST).

**S315. Eşzamanlılık: aynı sembolde çok bot cache yarışı?** Dict yazımı atomik; en kötü ihtimalle çifte fetch. ✅ Bozulma yok.

**S316. asyncio içinde features bloke eder mi?** `collect_features` async; klines await'li, ticker senkron (hafif). ⚠️ Ticker senkron çağrı tick'i çok kısa bloke edebilir (ihmal edilebilir, tur başı).

**S317. Exception rejimi/snapshot'ı çökertir mi?** Hayır — orchestrator hook `try/except` ile manuel cfg'ye düşer (`DYN_HOOK_EXCEPTION`). ✅ Bot çökmez.

**S318. Manuel mod (dynamic_mode=false) tamamen baypas mı?** Evet — gate false → hook hiç çalışmaz, snapshot temizlenir. ✅ Manuel mod byte-identik.

**S319. Dinamik mod hatası canlı pozisyonu riske atar mı?** Hayır — en kötü ihtimalle manuel config ile devam (overlay uygulanmaz). ✅ Güvenli düşüş zinciri sağlam.

**S320. Genel sayısal/uç-durum sağlamlığı?** ✅ Çok sağlam — None-safe, clamp'li, exception-tolerant, çökmez. Sistemin **güvenlik/sağlamlık** katmanı güçlü; zayıflık **karar zenginliği ve kalibrasyonda** (atıl feature'lar, ölü buy_levels_mult, rejim-kör eşikler, fee/likidite gözetmeme).

---

## Kapanış — en yüksek öncelikli 7 düzeltme adayı

1. 🔴 `buy_levels_mult`'ı `suggest()`'te kullan (rejime özgü alım kısıtı) — VEYA tablodan kaldır (ölü config). [S188]
2. 🔴 RSI'yi karara bağla (aşırı alım → alım kısıtı, aşırı satım → re-entry vurgusu). [S126/S152]
3. 🔴 Grid step'e fee-farkında min taban (`step ≥ k×fee`) ekle; düşük-ATR fee-altı gridleri önle. [S175/S234]
4. 🔴 Yüksek-ATR degenerate grid (hepsi 8%) durumunu ele al (geometrik dağıt veya adet azalt). [S177/S260]
5. 🟠 Likidite kapısı: `spread_pct`/`volume_24h` ile illiquid coin'de agresifliği kıs. [S140/S237]
6. 🟠 DUMP_RISK'i hızlandır (5m bazlı ani-düşüş sinyali ekle) ve OR mantığı (slope VEYA hacim). [S40/S42]
7. 🟠 `confidence`'ı kullan (alpha/agresiflik ölçekle) + kâr/giriş eşiklerini rejimle ölçekle (tp_drop/re_drop/re_rise). [S72/S207]
