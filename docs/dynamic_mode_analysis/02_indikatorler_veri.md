# 02 — İndikatörler & Veri (S86–S170)

> Kaynak: `app/botengine/dynamic/indicators.py`, `features.py`. İşaretler: ✅ doğru · ⚠️ orta · 🔴 önemli.

## A. ATR (S86–S95)

**S86. ATR formülü doğru mu?** Evet — `true_ranges` = max(H−L, |H−Cprev|, |L−Cprev|); Wilder yumuşatma (ilk `period` ortalama, sonra `(atr*(p−1)+tr)/p`). ✅ Standart Wilder ATR.

**S87. ATR periyodu?** 14 (varsayılan). ✅ Endüstri standardı.

**S88. ATR yarı-oluşmuş son mumu içeriyor mu?** 🔴 Evet. `_fetch_klines` Binance klines döndürür; son eleman henüz kapanmamış mumdur. ATR onu TR'ye dahil eder → tur başındaki anlık fiyat sıçraması ATR'yi şişirebilir.

**S89. ATR% nasıl hesaplanıyor?** `atr/last_close*100`. ✅ Doğru normalizasyon (fiyat-bağımsız yüzde).

**S90. ATR negatif/None olabilir mi?** `atr_val>=0` kontrolü var; yetersiz veride None. ✅ None-safe.

**S91. ATR hangi zaman diliminde?** Grid step için **5m** (`atr_pct_5m`), rejim için ayrıca **1h** (`atr_pct_1h` — ama 1h ATR aslında kullanılmıyor, bkz. S151). ✅/⚠️.

**S92. 5m ATR grid spacing için doğru seçim mi?** Evet — kısa vadeli volatilite grid aralığını belirlemeli. ✅ Mantıklı.

**S93. ATR ani bir wick'ten etkilenir mi?** Evet — tek büyük TR ATR'yi yukarı çeker (Wilder yumuşatma sınırlı). ⚠️ Forming mum + wick birleşince tur başında geçici yüksek ATR → geçici geniş grid.

**S94. ATR'nin alt/üst sınırı var mı?** İndikatörde yok; strateji `_atr_clamped` ile [0.15, 6.0]'a sıkıştırır. ✅ Aşırı değer koruması strateji katmanında.

**S95. `atr_pct_1h` hesaplanıyor mu, kullanılıyor mu?** Hesaplanıyor (features) ama 🔴 ne rejimde ne strateji'de kullanılıyor — atıl feature.

## B. ADX (S96–S106)

**S96. ADX formülü doğru mu?** Evet — +DM/−DM, TR Wilder toplamı, DX = 100×|+DI−−DI|/(+DI+−DI), ADX = DX'in Wilder ortalaması. ✅ Standart.

**S97. ADX periyodu?** 14. ✅

**S98. ADX kaç mum gerektirir?** `n < period*2+1` → None; yani **29** mum minimum. ✅ Doğru (ADX çift-yumuşatma gerektirir).

**S99. 1h ADX için kaç mum çekiliyor?** 100 (`_fetch_klines(sym,"1h",100)`), ama strateji 1h indikatörlerini yalnız `len>=40` ise hesaplar. ✅ 40 > 29, yeterli.

**S100. ADX < 40 mumlu yeni coin'de None mu?** features 1h bloğunu `len(k1h)>=40` ile koşullar; <40 ise `adx_1h=None`. ⚠️ Sonuç: yeni coin'de trend rejimi hiç açılmaz (S120).

**S101. ADX sıfıra bölme koruması var mı?** Evet — `atr_s<=0` ve `denom<=0` atlanır. ✅ None-safe.

**S102. ADX yön veriyor mu?** Hayır — ADX yalnız trend **gücü**. Yön `ema_slope_1h_pct` ile belirleniyor. ✅ Doğru ayrım (+DI/−DI yön için kullanılmıyor ama slope yeterli).

**S103. +DI/−DI ayrıca yön için kullanılabilir miydi?** Evet — ADX zaten +DI/−DI hesaplıyor; ⚠️ yön için slope yerine (veya ek olarak) +DI/−DI kullanılabilirdi (daha az gecikmeli). Şu an atılıyor.

**S104. ADX gecikmeli mi?** Evet — çift Wilder yumuşatma ADX'i doğası gereği gecikmeli yapar. ⚠️ Trend rejimine geç girilir (kabul edilebilir; trend kalıcıdır).

**S105. ADX + slope kombinasyonu sağlam mı?** ADX (güç) + slope (yön) klasik ve sağlam. ✅ Ama slope eşiği (±0.4%) çok hassas (S109).

**S106. ADX forming 1h mumu içeriyor mu?** Evet (son 1h mum oluşum halinde). ⚠️ 1h mum 1 saat sürdüğünden forming etkisi 5m'ye göre daha az oransal ama mevcut.

## C. EMA & slope (S107–S114)

**S107. EMA formülü doğru mu?** Evet — SMA seed + `out[-1]+k*(v−out[-1])`, k=2/(p+1). ✅ Klasik EMA.

**S108. EMA slope nasıl?** `(EMA_now − EMA_{lookback önce})/EMA_{lookback önce}*100`, period 20, lookback 5. ✅ Normalize yüzde eğim.

**S109. Slope eşiği ±0.4% uygun mu?** ⚠️ 1h EMA(20)'nin 5 bar (5 saat) değişimi; %0.4 çok küçük — sakin piyasada bile aşılabilir → zayıf trend yön ataması.

**S110. Slope lookback=5 bar (5 saat) yeterli mi?** Kısa — 5 saatlik EMA değişimi orta-vadeli trendi temsil eder. ✅ Makul; daha uzun lookback daha kararlı ama daha gecikmeli olurdu.

**S111. EMA period 20 (1h) ne kadar geçmişi kapsar?** ~20 saat. ✅ Orta vadeli.

**S112. Slope, EMA serisi <lookback+1 ise None mu?** Evet. ✅ None-safe.

**S113. Slope b<=0'da None mu (bölme koruması)?** Evet (`if b<=0: return None`). ✅

**S114. EMA hangi seriye uygulanıyor?** 1h kapanışları (`closes_1h`). ✅ Trend için doğru zaman dilimi.

## D. BBW (Bollinger Band Width) (S115–S122)

**S115. BBW formülü?** `(upper−lower)/mid*100` = `4*sd/mid*100`, period 20, mult 2.0. ✅ Standart BBW yüzdesi.

**S116. BBW sabit seride 0 mu?** Evet — sd=0 → 0 (veya stdev None). ✅ Test bunu doğruluyor (`test_bbw_constant_series_is_zero_or_none`).

**S117. BBW hangi zaman dilimi?** Hem 5m hem 1h hesaplanır; SQUEEZE 1h-only, BREAKOUT 1h-or-5m. ⚠️ Asimetri (S30/S31).

**S118. BBW mid<=0 koruması?** Evet (`mid<=0 → None`). ✅

**S119. BBW periyodu 20 (5m) ne kadar?** ~100 dk. 1h'te ~20 saat. ✅ Standart.

**S120. 1h verisi <40 mum → bbw_1h None → SQUEEZE imkânsız mı?** 🔴 Evet. Yeni coin'de SQUEEZE hiç açılamaz; BREAKOUT 5m ile açılabilir (asimetri).

**S121. BBW birimi ATR ile karşılaştırılabilir mi (S29)?** 🔴 Hayır — BREAKOUT eşiği `ATR_HIGH_PCT*4` BBW'yi ATR sabitiyle kıyaslar; birim/ölçek tutarsız.

**S122. BBW forming mum etkisi?** Evet, son mum dahil. ⚠️ Özellikle 5m BBW'de gürültü.

## E. RSI (S123–S130)

**S123. RSI formülü doğru mu?** Evet — ilk `period` ortalama kazanç/kayıp, sonra Wilder yumuşatma; `avg_loss==0 → 100`. ✅ Standart Wilder RSI.

**S124. RSI periyodu?** 14, `period+1` mum gerekir. ✅

**S125. RSI uptrend'de >70, downtrend'de <30 mu?** Evet — testler doğruluyor (`test_rsi_uptrend_high/downtrend_low`). ✅ Yön doğru.

**S126. RSI rejimde kullanılıyor mu?** 🔴 Hayır. `rsi_5m` ve `rsi_1h` hesaplanıp snapshot'a yazılıyor ama **hiçbir karar** RSI kullanmıyor.

**S127. RSI'nin kullanılmaması neyi kaçırıyor?** 🔴 Aşırı alım (>70) bölgesine yeni alım, aşırı satım (<30) bölgesine satış engellenebilirdi; aşırı satımda re-entry fırsatı vurgulanabilirdi. Tümü kullanılmıyor.

**S128. RSI divergence kullanımı var mı?** Hayır. ⚠️ (Beklenmez ama not.)

**S129. RSI 5m mı 1h mı daha anlamlı olurdu?** İkisi de hesaplanıyor; aşırı alım/satım için 1h daha az gürültülü olurdu. — Kullanılmadığı için moot.

**S130. RSI None durumu?** Yetersiz veride None. ✅ None-safe.

## F. Realized vol, volume z-score, wick/body (S131–S140)

**S131. Realized vol formülü?** Log getirilerin std × 100, lookback 30. ✅ Doğru (anlık vol proxy).

**S132. Realized vol kullanılıyor mu?** 🔴 Hayır — `realized_vol_5m` hesaplanıp atılıyor (ATR zaten vol proxy olarak kullanılıyor).

**S133. Volume z-score forming mumu dışlıyor mu?** ✅ Evet — `window = vols[-lookback-1:-1]` son (oluşan) mumu hariç tutar, sonra `vols[-1]` ile kıyaslar. **İndikatörler içinde forming'i doğru ele alan tek yer** (ATR/RSI/BBW dışlamıyor — tutarsızlık).

**S134. Volume z-score lookback?** 20. ✅ Makul pencere.

**S135. Volume z-score sd<=0'da None mu?** Evet. ✅

**S136. Wick/body ratio kullanılıyor mu?** 🔴 Hayır — `wick_body_ratio_5m` hesaplanıp atılıyor (chop dedektörü olarak tasarlanmış ama bağlı değil).

**S137. Wick/body chop'u yakalayabilir miydi?** Evet — yüksek wick oranı HIGH_VOL_RANGING/chop teyidi için kullanılabilirdi. ⚠️ Atıl.

**S138. Volume z-score rejimde nerede kullanılıyor?** DUMP (≥2) ve BREAKOUT (≥2) tetikleyicilerinde. ✅ Kullanılan birkaç feature'dan biri.

**S139. Volume 24h kullanılıyor mu?** 🔴 Hayır — `volume_24h_usdt` toplanıyor ama likidite filtresi olarak kullanılmıyor.

**S140. Spread kullanılıyor mu?** 🔴 Hayır — `spread_pct` toplanıyor ama grid genişletme/coin atlama için kullanılmıyor.

## G. Kullanılan vs atıl feature envanteri (S141–S156)

**S141. Hangi feature'lar GERÇEKTEN karar etkiliyor?** Yalnız 5: `atr_pct_5m` (rejim+strateji), `bbw_1h/bbw_5m` (rejim), `adx_1h` (rejim), `ema_slope_1h_pct` (rejim), `volume_zscore_5m` (rejim). ✅

**S142. Strateji (`suggest`) kaç feature kullanıyor?** Yalnız **1**: `atr_pct_5m`. Tüm grid/trail/tp/alloc ondan + rejim tuning'inden türiyor. 🔴 Çok dar taban.

**S143. `atr_pct_1h` atıl mı?** Evet (S95). 🔴

**S144. `rsi_5m` atıl mı?** Evet (S126). 🔴

**S145. `rsi_1h` atıl mı?** Evet. 🔴

**S146. `realized_vol_5m` atıl mı?** Evet (S132). 🔴

**S147. `wick_body_ratio_5m` atıl mı?** Evet (S136). 🔴

**S148. `spread_pct` atıl mı?** Evet (S140). 🔴

**S149. `volume_24h_usdt` atıl mı?** Evet (S139). 🔴

**S150. Atıl feature'ların maliyeti?** Hesap ucuz (zaten klines var), ama 🔴 **karar zenginliği** kaybı: 13 feature'dan 8'i karara girmiyor. Sistem "5 sinyalli".

**S151. Bu atıl feature'lar neden duruyor?** Muhtemelen ileride kullanım için + snapshot'ta debug/şeffaflık. ✅ Şeffaflık iyi; ⚠️ ama tasarım niyeti (RSI/likidite) yarım kalmış.

**S152. En kritik atıl feature hangisi?** 🔴 **RSI** (aşırı alım/satım) — DCA için aşırı satımda alım, aşırı alımda temkin doğal sinyaller.

**S153. İkinci kritik atıl?** 🔴 **spread/volume_24h** — illiquid coin'de kötü dolum riski; likidite kapısı yok.

**S154. atr_pct_1h kullanılsa ne kazanırdık?** Çok-zaman-dilimli vol teyidi (5m gürültüsünü 1h ile filtreleme). ⚠️ Şu an yalnız 5m'ye güveniliyor.

**S155. wick/body kullanılsa?** Chop/tuzak teyidi → HIGH_VOL_RANGING güvenini artırır. ⚠️

**S156. Bu envanter "gereksiz hesap" mı yoksa "eksik kullanım" mı?** Eksik kullanım — feature'lar doğru hesaplanıyor, karar katmanı dar. 🔴 Asıl mantık boşluğu burada.

## H. Veri toplama, tazelik, zaman dilimi, cache (S157–S170)

**S157. Kaç mum çekiliyor?** 5m × 120, 1h × 100. ✅ ATR/RSI/BBW (5m) ve ADX/EMA (1h) için yeterli.

**S158. `data_fresh=False` ne zaman?** Sembol/fiyat yok, veya 5m yok / <30 mum. ✅ Çekirdek eksikse stale.

**S159. 30 mum tüm 5m indikatörlerine yeter mi?** ATR(14)✅, RSI(15)✅, BBW(20)✅, vol_z(21)✅, **realized_vol(31)❌** (30 < 31). ⚠️ Tam 30 mumda realized_vol None — ama zaten atıl (S132).

**S160. 1h bloğu ne zaman hesaplanır?** `k1h and len>=40`. <40 → tüm 1h feature None. ⚠️ Yeni coin'de trend/squeeze yok.

**S161. Cache TTL'leri?** 5m=60s, 1h=600s, 1m=20s, 15m=180s, 4h=1200s. ✅ Zaman dilimine oranlı.

**S162. Cache aynı sembolde çoklu botu birleştiriyor mu?** Evet — key `(sym,interval,limit)`. ✅ REST fan-out azaltır.

**S163. Tur başı seyrek olduğundan cache çoğu zaman soğuk mu?** Muhtemelen — turlar dakikalar/saatler sürebilir, TTL 60s/600s. ⚠️ Çoğu snapshot taze fetch yapar (kabul edilebilir, seyrek).

**S164. Cache eviction güvenli mi?** >256 girdide en eski atılır (`next(iter)`). ✅ Basit ama yeterli.

**S165. Klines hatası rejimi bozar mı?** Hayır — `_fetch_klines` exception'da cache veya None döner; features `data_fresh=False` → stale path. ✅ Asla raise etmez.

**S166. `testnet=False` sabit — paper bot etkilenir mi?** Paper bot da mainnet public klines çeker. ✅ Doğru (gerçek fiyat); ⚠️ mainnet'te olmayan sembolde stale.

**S167. Spread hesabı doğru mu?** `(ask−bid)/mid*100`, `ask>=bid` ve pozitiflik kontrollü. ✅ (Ama sonuç kullanılmıyor, S140.)

**S168. 24h ticker hatası rejimi bozar mı?** Hayır — `_fetch_ticker_24h` exception'da {} döner; spread/volume None kalır, çekirdek (5m) etkilenmez. ✅

**S169. Zaman dilimi karışıklığı riski var mı?** Feature isimleri (`_5m`, `_1h`) açık; ama rejim eşik sabitleri zaman dilimi etiketsiz (S39). ⚠️ Bakım riski.

**S170. Veri katmanı genel olarak sağlam mı?** ✅ Toplama/tazelik/cache/hata-yönetimi sağlam ve None-safe. Sorun veride değil, **toplanan verinin yarısının kullanılmamasında** (G bölümü).
