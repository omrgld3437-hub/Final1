# Git — Final1

> HEAD `e8033a3` · Toplam **107** commit · branch `main`

## GitHub

| Alan | Değer |
|------|-------|
| Repository | [omrgld3437-hub/Final1](https://github.com/omrgld3437-hub/Final1) |
| Web | https://github.com/omrgld3437-hub/Final1 |
| SSH (origin) | `git@github.com:omrgld3437-hub/Final1.git` |
| HTTPS | `https://github.com/omrgld3437-hub/Final1.git` |
| Aktif branch | `main` |
| HEAD (kısa) | `e8033a3` |
| HEAD (tam) | `e8033a36a99f914d0f026afc271f6e82b166d086` |
| Remote durumu | `origin/main`'den **1** commit önde |

## Submodule: marketing

| Alan | Değer |
|------|-------|
| Gitlink (HEAD) | `9a2d089` (`9a2d089773bb583e393b204813bc47eeb1287279`) |
| Klasör | `marketing/` (ayrı git repo) |

## Commit geçmişi (`git log`)

En yeni commit üstte.

### 1. `e8033a3` — Fix: sell-grid outage recovery firing on a fabricated, unverified peak

- **Commit no (tam):** `e8033a36a99f914d0f026afc271f6e82b166d086`
- **Commit no (kısa):** `e8033a3`
- **Tarih:** 2026-06-23 12:26:09 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - _recover_sell_grid had the same class of bug as the buy-side fix in
  - c5e0879, but inverted: when no real intra-cycle peak had been tracked
  - yet (peaks[idx] is None), the fallback peak = max(trigger, P) fabricates
  - a peak at the trigger level. If price had already fallen well below that
  - fabricated peak by recovery time, P <= exec_thr was trivially satisfied
  - and the grid fired an immediate sell against a peak that was never
  - actually observed — a premature/exaggerated sell rather than a genuine
  - trailing pullback.
  - Same remedy as the buy side: the immediate-fire shortcut now only
  - applies when a real, previously tracked peak exists (legitimate outage
  - catch-up). Without prior peak history the grid keeps trailing normally
  - and only fires once price truly pulls back by the configured
  - sell_trigger_trailing_pct, matching live-tick behavior.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 2. `b3c54a8` — docs: sync GIT.md (git log)

- **Commit no (tam):** `b3c54a859531c582a396abe65844a74b3dc3e298`
- **Commit no (kısa):** `b3c54a8`
- **Tarih:** 2026-06-23 11:49:24 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 3. `c5e0879` — Fix: buy-grid outage recovery firing with near-zero trailing margin

- **Commit no (tam):** `c5e08792c8b6d33278ab6d4132850ad44eb5201e`
- **Commit no (kısa):** `c5e0879`
- **Tarih:** 2026-06-23 11:49:24 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - After a connectivity gap, _recover_buy_grid derived an unobserved trough
  - straight from the current price P when no real intra-cycle low had been
  - tracked yet, then immediately marked it "favorable" (instant fire) even
  - though P never bounced buy_trigger_trailing_pct% above that trough. This
  - collapsed the configured trailing margin to ~0, so the grid detail modal
  - showed "Dip fiyat" and "Gerçekleşme fiyatı" almost identical regardless
  - of the configured trailing percentage (e.g. 0.5%).
  - Now the immediate-fire shortcut only applies when a real, previously
  - tracked trough exists (legitimate outage catch-up); without prior trough
  - history the grid keeps trailing normally and only fires once price truly
  - recovers by the configured percentage, matching live-tick behavior.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 4. `d6995b2` — docs: sync GIT.md (git log)

- **Commit no (tam):** `d6995b2d4f30667f976bc06764fdf89010859e85`
- **Commit no (kısa):** `d6995b2`
- **Tarih:** 2026-06-23 11:49:01 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 5. `7c0a013` — WIP: dynamic mode, param assistant, dashboard/UI updates (pre dip-fiyat fix)

- **Commit no (tam):** `7c0a013d3a61760e241b4af72cd662bcb2bac7f1`
- **Commit no (kısa):** `7c0a013`
- **Tarih:** 2026-06-23 11:49:01 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Snapshot of in-progress work across botengine, API, manager_server and UI
  - prior to the buy-grid outage-recovery trailing fix.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 6. `6692270` — docs: sync GIT.md (git log)

- **Commit no (tam):** `669227046f284b71b3595f8b91ac7883983af679`
- **Commit no (kısa):** `6692270`
- **Tarih:** 2026-06-18 17:04:24 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 7. `1791a18` — Fix Binance whitelist connectivity alerts

- **Commit no (tam):** `1791a187e1ef9315a692d6cee621fd2a35406a82`
- **Commit no (kısa):** `1791a18`
- **Tarih:** 2026-06-18 17:04:24 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 8. `958c3b8` — docs: sync GIT.md (git log)

- **Commit no (tam):** `958c3b8d98ae056a4afbdebe41627d5f120f64e9`
- **Commit no (kısa):** `958c3b8`
- **Tarih:** 2026-06-18 16:47:30 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 9. `af1ba2e` — Update dashboard assistant and bot safety handling

- **Commit no (tam):** `af1ba2e769059f32e6669601f7df6367d1fcaf47`
- **Commit no (kısa):** `af1ba2e`
- **Tarih:** 2026-06-18 16:47:30 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 10. `0628f1a` — docs: sync GIT.md (git log)

- **Commit no (tam):** `0628f1a380375300cb32dbad04a314514b88fa29`
- **Commit no (kısa):** `0628f1a`
- **Tarih:** 2026-06-16 04:27:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.33>

---

### 11. `f8e66f4` — Fix CI by applying ruff format to changed Python files.

- **Commit no (tam):** `f8e66f4b133d78df819cbc8750487782578a0c79`
- **Commit no (kısa):** `f8e66f4`
- **Tarih:** 2026-06-16 04:27:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.33>

---

### 12. `cf13584` — docs: sync GIT.md (git log)

- **Commit no (tam):** `cf13584254d4a6027a97345f4e88b1cd44fbe10e`
- **Commit no (kısa):** `cf13584`
- **Tarih:** 2026-06-16 04:24:29 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.33>

---

### 13. `bca4d29` — Add dynamic mode, bot alpha performance, and dashboard UX improvements.

- **Commit no (tam):** `bca4d295f6d82726fd084f317232709cff888f49`
- **Commit no (kısa):** `bca4d29`
- **Tarih:** 2026-06-16 04:24:29 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.33>
- **Detay:**
  - Run-start baseline drives bot performans % (balance minus coin) on detail/performance APIs; leaderboard dynamic badges and Parametreler flows; session-scoped engine logs and related tests/spec updates.

---

### 14. `4a6ab47` — test: use portable pytest database path

- **Commit no (tam):** `4a6ab4757d8e69a5a3cdbc75c3a616b705761104`
- **Commit no (kısa):** `4a6ab47`
- **Tarih:** 2026-06-06 11:40:08 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 15. `1ab5047` — ci: expose pytest failure details

- **Commit no (tam):** `1ab50472d413f6718c79cd106ee5edcc69ec2cbc`
- **Commit no (kısa):** `1ab5047`
- **Tarih:** 2026-06-06 11:38:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 16. `5864bcc` — ci: pin pytest for stable actions run

- **Commit no (tam):** `5864bcce167b1442c890bfb33a461e94d5179841`
- **Commit no (kısa):** `5864bcc`
- **Tarih:** 2026-06-06 11:36:20 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 17. `b15e563` — docs: sync GIT.md (git log)

- **Commit no (tam):** `b15e5637aeadfd1eefe3d854a15ae9e78b43eca1`
- **Commit no (kısa):** `b15e563`
- **Tarih:** 2026-06-06 11:33:05 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 18. `796a807` — ci: stabilize github actions quality job

- **Commit no (tam):** `796a807dead6b08e494e21b010f80ae698ec043d`
- **Commit no (kısa):** `796a807`
- **Tarih:** 2026-06-06 11:33:05 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 19. `e4bbdda` — docs: sync GIT.md (git log)

- **Commit no (tam):** `e4bbddacc9d7e0def80fb8ee1fa37a8c162156fe`
- **Commit no (kısa):** `e4bbdda`
- **Tarih:** 2026-06-06 04:52:46 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 20. `d7e5bfa` — fix(test): test_parallel_grids max_buy_levels=2 eksikti

- **Commit no (tam):** `d7e5bfa8b53bac1a862aae0e428554c2203ab4de`
- **Commit no (kısa):** `d7e5bfa`
- **Tarih:** 2026-06-06 04:52:46 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - _cfg_two_buy() fixture'ında max_buy_levels belirtilmemişti; default 1
  - olduğu için ikinci buy grid BOT_BUY_LEVEL_BLOCKED ile bloklanıyor ve
  - test assert len(buys)==2 başarısız oluyordu.
  - Test 2 paralel alış grid'ini doğruladığından max_buy_levels=2 zorunlu.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 21. `a8543b2` — docs: sync GIT.md (git log)

- **Commit no (tam):** `a8543b2649acc3b5abd766e41d27db4081d6a1c6`
- **Commit no (kısa):** `a8543b2`
- **Tarih:** 2026-06-06 04:47:55 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 22. `cf12ad3` — ci: ruff lint+format hatalarını düzelt, ruff.toml ekle

- **Commit no (tam):** `cf12ad3bf93aade3f187cd940f79e583a2f90b70`
- **Commit no (kısa):** `cf12ad3`
- **Tarih:** 2026-06-06 04:47:55 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - - ruff.toml: kasıtlı E402/E712/E741/E722/F821 kuralları muaf tutuldu
  - - 153 unused import ve unused variable otomatik düzeltildi (ruff --fix)
  - - 230 dosya ruff format ile yeniden formatlandı
  - - psutil lazy-import'lar noqa:F401 ile işaretlendi
  - - tests/test_grid_outage_recovery.py: duplicate test fonksiyon adı düzeltildi
  - CI artık lint-format-import-test aşamasını geçiyor.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 23. `c6d5f3a` — docs: sync GIT.md (git log)

- **Commit no (tam):** `c6d5f3a3fc7cdc944d108297a1449a6116717039`
- **Commit no (kısa):** `c6d5f3a`
- **Tarih:** 2026-06-06 03:49:29 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 24. `cfdec7a` — fix: bot detay start logları gizlenme hatası düzeltildi

- **Commit no (tam):** `cfdec7a8e894d31a4b064a3310a436f40326d8cc`
- **Commit no (kısa):** `cfdec7a`
- **Tarih:** 2026-06-06 03:49:29 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - shouldHideDuplicateBotStart fonksiyonu initial_allocation_done=true
  - olduğunda (bot daha önce çalışmışsa) tüm yeni başlatma loglarını
  - yanlışlıkla gizliyordu.
  - Yeni mantık:
  - - En son (en yüksek id'li) gerçek start logu asla gizlenmez
  - - Daha sonra gelen başka bir gerçek start varsa eski log gizlenebilir
  - - Yalnızca bağlantı kesintisi recovery sonrası gelen eski start'lar gizlenir
  - - connectivity_resume=true olan başlatmalar eskisi gibi her zaman gizlenir
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 25. `c008064` — docs: sync GIT.md (git log)

- **Commit no (tam):** `c0080641b40e9e594db4c1305e4a7759d965ae74`
- **Commit no (kısa):** `c008064`
- **Tarih:** 2026-06-05 20:00:48 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 26. `e7c4678` — fix: user stream yeniden başlatma sonrası hatalı ERROR seviyesi giderildi

- **Commit no (tam):** `e7c4678f8b3ecd054970abec094f7a9eca2ad2b8`
- **Commit no (kısa):** `e7c4678`
- **Tarih:** 2026-06-05 20:00:48 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - Servis yeniden başlatıldıktan sonraki ilk 120 saniye "başlangıç dönemi"
  - sayılıyor. Bu süre içindeki ardışık bağlantı başarısızlıkları (consecutive=3)
  - ERROR yerine WARNING olarak loglanıyor — yeniden başlatma kaynaklı geçici
  - durum "Hatalar" listesine düşmüyor. 120s sonraki kalıcı hatalar eskisi gibi
  - ERROR seviyesinde kalır.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 27. `63078d8` — docs: sync GIT.md (git log)

- **Commit no (tam):** `63078d8d404c7cd2d50c4b9a22263dfcd5ce21aa`
- **Commit no (kısa):** `63078d8`
- **Tarih:** 2026-06-05 19:50:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 28. `409c88a` — fix: user stream HTML yanıt tespiti — ağ engeli ile API hatası ayırt edildi

- **Commit no (tam):** `409c88aeb1b2f6ef832b100346b329081bce86b1`
- **Commit no (kısa):** `409c88a`
- **Tarih:** 2026-06-05 19:50:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - Binance API'ye ulaşılamadığında (proxy/ISP engeli) JSON yerine HTML
  - yanıt geliyor. Bu durum USER_STREAM_CREATE_410 olarak yanlış sınıflandırılıyordu.
  - - _create_listen_key: yanıt HTML ise USER_STREAM_NETWORK_BLOCK logluyor
  - (kod=None msg=<html> artık net teşhis veriyor)
  - - JSON yanıt hatalarında eski 410 yolu korunuyor
  - - logHumanize: NETWORK_BLOCK için ayrı şablon: "ağ engeli, DNS/VPN kontrol et"
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 29. `da9761f` — docs: sync GIT.md (git log)

- **Commit no (tam):** `da9761feb3759f59ac1e108cbcd0281e1a82e676`
- **Commit no (kısa):** `da9761f`
- **Tarih:** 2026-06-04 23:13:56 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 30. `ad0df7d` — feat: kapsamlı UI/UX ve backend iyileştirmeleri

- **Commit no (tam):** `ad0df7dc3d1d7d92d4c2d94fdae3be661a1dbf68`
- **Commit no (kısa):** `ad0df7d`
- **Tarih:** 2026-06-04 23:13:56 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - Bot & Performans:
  - - Bot detay tur süresi formatı: <24sa=sa:dk, <1ay=gün:sa, <1yıl=ay:gün
  - - Mevcut çalışma öncesi tur verileri performans bölümünde görünmüyor (bot.started_at filtresi)
  - - Sıfır tamamlanmış tur durumunda "henüz tur yok" mesajı gösteriliyor
  - İşlem Geçmişi:
  - - Kullanıcı stream (ORDER_FILLED) anında tx_history dosyasına yazılıyor — sayfa yenilemeden güncellenir
  - - Test hesabı işlem geçmişi Trade tablosundan paper bot emirleri gösteriyor (SİMÜLE rozeti)
  - - Test işlem detayı eksik alanlar düzeltildi (qty/price/commission_usdt)
  - - Revision değişince panel kapalıyken fark edilip tab açılınca anında yükleniyor
  - Admin Paneli:
  - - Giriş/çıkış zamanları last_activity_at (60s ping) ile güncelleniyor, eski login_at eski kalıyor
  - - İnternet hızı: network_mbps_down ↓ / network_mbps_up ↑ doğru alanlardan okunuyor
  - - Ayarlar butonları tasarım sistemine uygun (btn-danger, btn-warning, btn-secondary)
  - Bot Oluşturma:
  - - Grid sayısı max 15, scroll ile 0.5 adım artış, miktar toplamı canlı göstergesi
  - - Yüzde toplamı %100 değilse bot başlamadan uyarı
  - User Stream / Loglama:
  - - 410 ardışık hata: 3+ sonra ERROR+5dk backoff, spam önlendi
  - - logHumanize: USER_STREAM_PERSISTENT_FAILURE ve CREATE_410 için açıklayıcı şablonlar
  - - Wallet stale eşiği stream down iken 2x artıyor
  - Genel:
  - - 404 NOT_FOUND logları WARNING→DEBUG indirildi
  - - fetchBotHealth _botDetailMissing kontrolü eklendi
  - - visibilitychange handler bot bulunamadıysa interval yeniden başlatmıyor
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 31. `a6d07e3` — docs: sync GIT.md (git log)

- **Commit no (tam):** `a6d07e30e8bf9575ac02e091864ea22b38b44710`
- **Commit no (kısa):** `a6d07e3`
- **Tarih:** 2026-06-04 11:56:54 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 32. `11173e6` — Display enriched CYCLE_END/START fields in bot engine log UI

- **Commit no (tam):** `11173e63fba8f62767184dc6ae7e1b5434df1313`
- **Commit no (kısa):** `11173e6`
- **Tarih:** 2026-06-04 11:56:54 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - engineLogFormat.js — formatCycleStart güncellendi:
  - - Base %50.1 / Quote %49.9: anlık rebalance oranı (hedeften >2% sapma ⚠ uyarısı)
  - - başabaş ~$2041.93: fee dahil tahmini başa baş fiyatı
  - - grid tetik: A1: $1982.90 · A2: $1962.87 · Y1: $2022.95 · Y2: $2042.99
  - engineLogFormat.js — formatCycleEnd güncellendi:
  - - süre 57dk: tur kaç dakika/saat sürdü
  - - grid: 2/2 satış · 0/2 alış: tetiklenen grid sayısı
  - - fiyat: $0.2491–$0.2524: tur boyunca min–max fiyat
  - - kümülatif: +$35.85 nakit · +149.14 XLM envanter (X tur)
  - Yeni event tipleri:
  - - GRID_SUMMARY → 'Özet' tipiyle görünür (her 10 turda backend yazıyor)
  - - WARN/BALANCE_DRIFT_WARN → 'Uyarı' tipiyle bakiye sapma uyarısı
  - - INFO/BALANCE_SYNC_OK → hidden (gürültü olmadan sessiz doğrulama)
  - - ORDER_UPDATE → 'Emir' etiketiyle (user stream fills)
  - TYPE_TR ve META_SKIP_KEYS zenginleştirilmiş alanlarla güncellendi.
  - fmtDuration() yardımcısı eklendi (sn/dk/s formatı).
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 33. `223cfb3` — docs: sync GIT.md (git log)

- **Commit no (tam):** `223cfb3c54315a3e2bf6c6641289a74e5f133fb8`
- **Commit no (kısa):** `223cfb3`
- **Tarih:** 2026-06-04 11:48:07 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 34. `abca2df` — Enrich CYCLE_END/START events: duration, grid utilization, price range, breakeven, cumulative PnL

- **Commit no (tam):** `abca2df08bf227bbae7dfea58403a2673205fd8b`
- **Commit no (kısa):** `abca2df`
- **Tarih:** 2026-06-04 11:48:07 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - CYCLE_END meta zenginleştirme (app/botengine/execution.py):
  - - duration_sec: tur süresi saniye cinsinden (ledger.started_at → kapanış)
  - - sell_grids_fired / buy_grids_fired / *_total: hangi gridler tetiklendi
  - - avg_buy_price / avg_sell_price: ledger'dan ağırlıklı ortalama
  - - price_high / price_low: tur boyunca fiyat aralığı
  - - cum_cash_pnl_usdt / cum_inventory_qty / cum_cycles: Tur 1'den itibaren kümülatif K/Z
  - CYCLE_START meta zenginleştirme:
  - - sell_trigger_prices (Y1, Y2…): her satış grid'inin tetikleme fiyatı
  - - buy_trigger_prices (A1, A2…): her alış grid'inin tetikleme fiyatı
  - - estimated_breakeven: yaklaşık başa baş fiyatı (fee dahil)
  - - estimated_profit_target: kar satışı hedef fiyatı
  - - base_usd / quote_usd / base_ratio_pct / quote_ratio_pct: anlık rebalance oranı
  - - target_base_alloc_pct / target_quote_alloc_pct: hedef tahsis
  - Grid özet olayı (GRID_SUMMARY):
  - - Her 10 turda bir otomatik yayınlanır
  - - Dönem: nakit tur sayısı, envanter tur sayısı, dönem K/Z
  - - Kümülatif toplamlar dahil
  - Sanal vs Gerçek bakiye senkronizasyonu:
  - - Her 50 tick'te bir (live botlar, ilk alım sonrası)
  - - Sapma >%5 base veya >$5 USDT → WARN event + logger.warning
  - - Normal → INFO event (sessiz doğrulama)
  - Fiyat aralığı takibi (app/botengine/orchestrator.py):
  - - Her tick'te _cycle_price_high / _cycle_price_low güncellenir
  - - cycle_reset_after_fill'den ÖNCE CYCLE_END meta'ya eklenir
  - - Yeni tur açılışında sıfırlanır
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 35. `637e93f` — docs: sync GIT.md (git log)

- **Commit no (tam):** `637e93f6178c29872e3b2881fd0b8fa166763aec`
- **Commit no (kısa):** `637e93f`
- **Tarih:** 2026-06-04 11:31:04 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 36. `b6cd00c` — Production hardening and bot health fixes

- **Commit no (tam):** `b6cd00cdc8223edd337767d60236b3a311b8ee60`
- **Commit no (kısa):** `b6cd00c`
- **Tarih:** 2026-06-04 11:31:04 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 37. `59fbd9a` — docs: sync GIT.md (git log)

- **Commit no (tam):** `59fbd9a6bfc0a43e816ca2e11a522b73c346fbea`
- **Commit no (kısa):** `59fbd9a`
- **Tarih:** 2026-06-04 11:13:11 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 38. `95a498b` — Fix USER_STREAM 410 Gone: auto-reconnect + account label in logs

- **Commit no (tam):** `95a498b320b557c546f1db6ed0d9f9664a29d857`
- **Commit no (kısa):** `95a498b`
- **Tarih:** 2026-06-04 11:13:11 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - 410 Gone root cause:
  - Binance listenKey süresi 60 dk'da doluyor. _keepalive_loop 30 dk'da bir
  - PUT ile yeniliyor ama 410 alınca sadece log atıp devam ediyordu; WebSocket
  - sonunda kopunca run() yeni listenKey alarak yeniden bağlanıyordu. Bu süreçte
  - art arda 410 uyarısı çıkıyor ve yanlış hata kategorisiyle gösteriliyordu.
  - Düzeltmeler (app/botengine/user_stream.py):
  - - _keepalive_loop: 410 HTTPStatusError ayrı yakalanır, _force_reconnect=True
  - ve listen_key=None set edilir; keepalive loop'u kırılır
  - - run(): ws.recv() asyncio.wait_for(timeout=5s) ile sarar; _force_reconnect
  - bayrağını döngüde kontrol eder, set edilince WebSocket kapatılıp hemen
  - yeni listenKey POST ile yeniden bağlanır (backoff yok)
  - - _delete_listen_key(): temiz kapanışta Binance'e DELETE gönderilir
  - - account_label parametresi: log'larda "AdSoyad #KOD (id=3)" formatı
  - - _build_account_label(): DB'den Account.name + account_code lookup
  - app/botengine/worker_main.py:
  - - start_user_stream_for_account'a db= geçirilir (hesap adı/kodu okusun)
  - - USER_STREAM_STARTED log'u hesap etiketiyle yazdırılır
  - manager_server/ui/assets/logHumanize.js:
  - - USER_STREAM handler genel Binance handler'ından ÖNCE eklendi
  - - USER_STREAM_CONNECTED, KEY_EXPIRED, 410 durumları ayrı mesajlarla
  - - Genel Binance regex artık user_stream mesajlarını yakalamıyor
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 39. `d140169` — docs: sync GIT.md (git log)

- **Commit no (tam):** `d1401691e4b95e007c255fc4647a9c3329774520`
- **Commit no (kısa):** `d140169`
- **Tarih:** 2026-06-04 03:04:02 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 40. `350bbdb` — Modularize dashboard.js phase 3: bot-perf, tx-history, bots, create-modal, tabs

- **Commit no (tam):** `350bbdbd4ee2bb5fffa4aa6ad7f686dd069f2db1`
- **Commit no (kısa):** `350bbdb`
- **Tarih:** 2026-06-04 03:04:02 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - dashboard.js: 17,939 → 4,574 satır (−13,365 satır, %74 küçülme toplamda)
  - 12 modül dosyası oluşturuldu → ui/assets/modules/
  - Çıkarılan modüller (dashboard.js'ten SONRA yüklenir):
  - dashboard-bot-perf.js (478 satır)
  - - Bot perf cache: _readBotPerfCache, _persistBotPerfCache, hydrateBotPerformanceFromCache
  - - renderBotPerformancePanel, loadBotPerformance
  - - Leaderboard yardımcıları: normalizeRunningSinceIso, formatLeaderboardRunningDuration,
  - formatLeaderboardTotalPnl, renderBotParamsConfig, applyTrailingDcaConfigToForm
  - dashboard-tx-history.js (547 satır)
  - - İşlem geçmişi değişkenleri (_txHistoryRevision, _txHistoryLoaded vb.)
  - - loadTransactionHistory, pollTransactionHistoryRevision
  - - openTxDetailModal, closeTxDetailModal, spotOrderResultToTxItem
  - dashboard-bots.js (423 satır)
  - - Botlar sekmesi cache: _botsTabCache, activateBotsTab, loadBotsListFast
  - - Bot sıralama: financeBotsSortPnlUsd, renderBotsList, updateFinanceBotsSortButtonUi
  - dashboard-bot-create.js (855 satır)
  - - Bot yapıları + seçim: BOT_STRUCTURES, renderBotStructures, selectBotStructure
  - - Oluşturma sekmesi: createAndStartBot, startBotFromCreateTab, openBotParameterModal
  - - dashboardValidatePassword
  - dashboard-tabs.js (929 satır)
  - - Sekme bağlama: bindTabs, desktopTabToMobileTab, initMobileBottomNav
  - - Mobil alt nav, mobil trade arama, mobil favori coin listesi
  - - bindMustChangePasswordModal
  - dashboard-create-modal.js (1513 satır)
  - - DM modal: openCreateBotModal, closeCreateBotModal, bindCreateBotModal
  - - Sembol arama: showCreateModalSymbolDropdown, filterCoinListForSearch
  - - Form: collectForm, validateForm, validateDcaGridNotionals, createBot
  - Kalan dashboard.js çekirdeği (4574 satır):
  - State, DataHub, SpotCache, hata banner, hesap çözümleme, SSE/snapshot,
  - assetsState, normalizeAndApplyWallet, renderAssetsList, BinanceAssetsPanel,
  - test hesabı yardımcıları, Binance coin listesi, bindBinanceTab, initDashboard
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 41. `791ca71` — docs: sync GIT.md (git log)

- **Commit no (tam):** `791ca71f144f389856ce61c5e656159f210afee4`
- **Commit no (kısa):** `791ca71`
- **Tarih:** 2026-06-04 02:49:01 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 42. `ccad8be` — Modularize dashboard.js phase 2: appbar, wallet-state, spot-trade, finance

- **Commit no (tam):** `ccad8be278c4e12920e0048b49af8f588d5d0953`
- **Commit no (kısa):** `ccad8be`
- **Tarih:** 2026-06-04 02:49:01 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - dashboard.js: 17,939 → 9,296 satır (−8,643 satır, %48 küçülme toplamda)
  - Çıkarılan modüller (dashboard.js'ten SONRA yüklenir):
  - dashboard-appbar.js (309 satır)
  - - Appbar display name yönetimi: updateAccountName, lockAppbarDisplayName,
  - getLockedAppbarDisplayName, applyAppbarSnapshot, restoreAppbarFromSessionCache
  - dashboard-wallet-state.js (958 satır)
  - - Wallet live/stale durum değişkenleri ve tüm rozet mantığı
  - - isWalletDataLive, syncWalletPanelStatusBadges, applyWalletStaleWarningEl
  - - markWalletLiveFetchOk/Failed/Stale, walletStaleStatusText
  - - KPI cüzdan: updateCuzdanPnlKpi, applyKpiCuzdanSnapshot, updateKPIs
  - - Connectivity toast: debouncedWalletConnectivityToast, recoverDashboardAfterConnectivity
  - dashboard-spot-trade.js (3111 satır)
  - - Spot trade modal: openSpotTradeModal, submitSpotTrade, setTradeSide
  - - Aktif emirler: loadActiveOrders, renderActiveOrders, cancelOrder
  - - Coin listesi: loadCoinList, renderCoinList, filterCoinList, bindCoinList
  - - checkFullscreenBlockers
  - dashboard-finance.js (3282 satır)
  - - Finans sekmesi: initFinanceTab, saveFinanceReference, calculateFinanceRebalance
  - - Raporlar: initReportsTab, loadEquityCurve, loadFinanceReport, loadFinanceTrades
  - - Dönem seçimi: setFinancePeriod, setTradesPeriod, exportReportCSV
  - - Popup: fetchAndShowUserPopup, dismissUserPopup
  - Yükleme sırası (dashboard.html):
  - [1] dashboard-format.js (State bağımsız, ÖNCE)
  - [2] dashboard.js (State + assetsState + normalizeAndApplyWallet tanımlar)
  - [3] appbar → wallet-state → leaderboard → spot-trade → finance (SONRA)
  - DOMContentLoaded tüm modüller yüklendikten sonra initDashboard() çağırır ✓
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 43. `5c8dcee` — docs: sync GIT.md (git log)

- **Commit no (tam):** `5c8dcee4f6f353fa39340b2335033ae3cf01abca`
- **Commit no (kısa):** `5c8dcee`
- **Tarih:** 2026-06-04 02:37:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 44. `b9a042f` — Modularize dashboard.js: extract format utils + leaderboard (phase 1)

- **Commit no (tam):** `b9a042fcd03ca42149afb8df99504e7b443cc6cf`
- **Commit no (kısa):** `b9a042f`
- **Tarih:** 2026-06-04 02:37:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - dashboard.js: 17,939 → 16,932 satır (1,007 satır kaldırıldı, ~5.6% azalma)
  - dashboard-format.js (426 satır) — dashboard.js'ten ÖNCE yüklenir:
  - - isMobileView, throttle (utility)
  - - usdFmt, fmtUsd, fmtCoinPrice, fmtSignedUsd, fmtNum (format)
  - - parseDecimal, parseApiErrorDetail, relativeTime, translateErrorToTurkish
  - - _fmtPerfUsdt, _fmtPerfCoin, _fmtPerfDateOnly, _perfPeriodPrefix ve diğer
  - bot performance format yardımcıları
  - - fmtSignedUsdOrDash, fmtSignedPct
  - Bunların tamamı saf (pure) fonksiyon — State/DOM bağımlılığı yok.
  - dashboard-leaderboard.js (602 satır) — dashboard.js'ten SONRA yüklenir:
  - - LEADERBOARD_* sabitler ve state değişkenleri
  - - leaderboardItemKey, sortLeaderboardItemsByProfit, stabilizeLeaderboardOrder
  - - buildGlobalLeaderboardItemHtml, buildGlobalLeaderboardOrderSignature ve diğerleri
  - - formatLeaderboard*, filterLeaderboardItemsForDisplay
  - - openLeaderboardParamsModal, resolveLeaderboardItemForModal
  - - loadGlobalLeaderboard (async)
  - State'e runtime'da erişir → dashboard.js'ten sonra yüklenince global scope üzerinden ulaşır.
  - dashboard.html: yükleme sırası güncellendi.
  - Yöntem: Build tool gerektirmez — top-level fonksiyon tanımları global scope'ta otomatik,
  - runtime çağrıları için sıra önemli değil.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 45. `e2d8fba` — docs: sync GIT.md (git log)

- **Commit no (tam):** `e2d8fba8894e8c4a42e1dca1bbfa8f74485c0855`
- **Commit no (kısa):** `e2d8fba`
- **Tarih:** 2026-06-03 21:36:06 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 46. `2c6479f` — Implement CTO report items: CORS, admin security, daily loss limit, health endpoints

- **Commit no (tam):** `2c6479fc394ed1bc06311055880e7a1ba53e3317`
- **Commit no (kısa):** `2c6479f`
- **Tarih:** 2026-06-03 21:36:06 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - CORS (app/main.py):
  - - allow_origins=["*"] → ALLOWED_ORIGINS env var ile konfigüre edilebilir
  - - Ortam değişkeni belirtilmezse ["*"] + credentials=False (geçerli CORS spec)
  - - Belirtilirse specific origin listesi + credentials=True
  - - allow_methods/headers explicit whitelist'e alındı
  - Admin güvenliği (app/api/admin.py):
  - - /admin/server/restart artık şifre doğrulaması gerektiriyor (exit ile aynı koruma)
  - - ServerRestartRequest model eklendi; yanlış şifrede 400 döner, log yazılır
  - Günlük kayıp limiti (app/botengine/):
  - - DcaGridTrailingConfig: daily_loss_limit_usd alanı eklendi
  - - tick_dca_grid_trailing: günlük referans equity takibi (_dll_ref_usd/_dll_ref_date)
  - her TR günü başında sıfırlanır; limit aşılırsa bot tick durdurulur + HEALTH_WARN event
  - - orchestrator.py: _daily_loss_limit_hit flag → bot status=paused_error + log
  - BNB fee uyarısı (app/botengine/cycle_ledger.py + orchestrator.py):
  - - BNB fee USDT'ye çevrilemezse ledger içinde _fee_conversion_warn listesi oluşur
  - - Orchestrator her tick sonunda bu uyarıları kalıcı bot event'e dönüştürür
  - Health/ready endpoint'leri (app/main.py):
  - - /api/health: DB ping, worker durumu, DataHub fiyat sayısı, Binance failure state
  - - /api/ready: load balancer probe → DB hazır değilse 503 döner
  - Kod kalitesi (app/bot/):
  - - engine.py, engine_v2.py, trailing_engine.py: print() → logger.error()
  - - engine_v2.py ve trailing_engine.py'ye logging import eklendi
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 47. `98e58e9` — docs: sync GIT.md (git log)

- **Commit no (tam):** `98e58e9fca4734490498e93478442f6d5c0e9885`
- **Commit no (kısa):** `98e58e9`
- **Tarih:** 2026-06-03 10:05:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 48. `c05cad8` — Fix BINANCE_UNREACHABLE false-positive: suppress transient outage alerts & faster recovery

- **Commit no (tam):** `c05cad8053e105e0c9bdb7b94e2814943821d748`
- **Commit no (kısa):** `c05cad8`
- **Tarih:** 2026-06-03 10:05:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - Problem: Binance geçici erişilemez olduğunda (30-60 sn) anında kalıcı "Hata" log satırı
  - yazılıyor, bot CRITICAL alert gösteriyor, kullanıcı sistemi durdu sanıyordu.
  - Değişiklikler:
  - - binance_connectivity.py: _TRANSIENT_OUTAGE_LOG_DELAY_SEC=90 — hata 90s'den kısa süre
  - devam ederse bot log'una "Hata" event yazılmıyor; _first_fail_ts_by_account ile izleniyor
  - - binance_connectivity.py: _FAST_PROBE_SEC=12 — aktif hata varken probe sıklığı
  - 30s → 12s (daha hızlı toparlanma tespiti)
  - - binance_connectivity.py: note_binance_failure/success _first_fail_ts kaydı/temizliği
  - - binance_connectivity.py: sync_bot_connectivity_on_view hata varken hızlı probe
  - - health_watch.py: evaluate_bot_health ve evaluate_bot_health_for_list geçici kesintilerde
  - (<90s) BINANCE_UNREACHABLE CRITICAL alert göstermiyor
  - - worker_main.py: auto-resume döngüsü aktif hata varken 60s → 15s (hızlı toparlanma)
  - - home.py: wallet refresh BINANCE_TIMEOUT cooldown 30s → 10s (geçici kesinti sonrası
  - cüzdan daha hızlı güncellenir)
  - Sonuç: 30-60 saniyelik Binance kesintilerinde UI temiz kalır, log kirlenmez. 90s+ süren
  - gerçek kesintilerde uyarı gösterilir. Toparlanma öncekine göre 3-5x daha hızlı.
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 49. `c4aecf7` — docs: sync GIT.md (git log)

- **Commit no (tam):** `c4aecf7be2717610af45debf85497a57ea0e0de8`
- **Commit no (kısa):** `c4aecf7`
- **Tarih:** 2026-06-03 02:33:41 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 50. `f0b7446` — Fix wallet stale flicker, bot yellow mislead, ETH synthetic balance & cycle ledger fee bug

- **Commit no (tam):** `f0b7446ef4b7d2aa011be6269b12e98ce2635676`
- **Commit no (kısa):** `f0b7446`
- **Tarih:** 2026-06-03 02:33:41 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - UI / Dashboard:
  - - Wallet ts fallback: payload.ts yokken Date.now() yerine mevcut ts korunur (sayfa yenileme flickerı)
  - - 3 s grace period: shouldShowWalletStaleWarning ilk 3 s stale gösterimi engeller
  - - toLocaleTimeString: Istanbul timezone eklendi
  - - Bot satır yellowing: walletSnapshotStale nedeniyle bireysel bot satırları sarı yapılmıyor;
  - panel üstünde wallet-stale-bot-notice gösteriliyor
  - - Botlar sekmesi sarı devam ediyor; tooltip açıklayıcı hale getirildi
  - - Bot detay sayfası: localStorage köprüsü ile wallet stale notice (walletStaleBotDetailNotice)
  - - dashboard.js → localStorage wallet_stale_for_botdetail_v1 yazma/silme
  - - bot.html: _syncWalletStaleBotDetailBadge, walletStaleBotDetailNotice
  - - dashboard.html: walletStaleBotNotice / walletStaleBotNoticeBotsTab eklendi
  - - dashboard.css: .wallet-stale-bot-notice stili
  - Backend:
  - - home.py _enrich_minimal_wallet_with_bot_locked: bot_locked'da snapshot'ta olmayan varlıkları
  - (ETH gibi) DataHub fiyatı ile synthetic satır olarak ekler; total_usd güncellenir
  - - cycle_ledger.py cycle_ledger_with_basis: basis_mode=total'de initial_alloc_fee_quote
  - eklenmiyordu → breakeven ~133 USDT/ETH eksik çıkıyordu; düzeltildi
  - - execution.py: initial_allocation fill'de initial_alloc_fee_quote state'e kaydediliyor;
  - _sync_initial_done_from_db restart sonrası kopyalıyor
  - - test_cycle_ledger.py: test_cycle_ledger_with_total_basis_includes_initial_alloc_fee eklendi
  - - test_bot_performance_inventory_pnl.py: inventory cycle PnL live fiyat kullanmamalı
  - - test_compound_reentry_lot_boost.py: reentry lot boost testleri
  - Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---

### 51. `ec8e100` — docs: sync GIT.md (git log)

- **Commit no (tam):** `ec8e100add7e7f5aa7ea774bb69102d62d0cbfd2`
- **Commit no (kısa):** `ec8e100`
- **Tarih:** 2026-06-01 14:39:36 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 52. `dabab68` — Speed up finance history first paint

- **Commit no (tam):** `dabab68b675faefb6b485a0169d8510f441722ba`
- **Commit no (kısa):** `dabab68`
- **Tarih:** 2026-06-01 14:39:36 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 53. `310fb3c` — docs: sync GIT.md (git log)

- **Commit no (tam):** `310fb3c095fe57a81a7060a0734b86afd1d994d6`
- **Commit no (kısa):** `310fb3c`
- **Tarih:** 2026-06-01 14:25:59 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 54. `1b1dc05` — Add bounded log maintenance and reduce runtime noise

- **Commit no (tam):** `1b1dc0597a0e699652fbaa139b7cb9a5850064b5`
- **Commit no (kısa):** `1b1dc05`
- **Tarih:** 2026-06-01 14:25:59 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 55. `285d08e` — docs: sync GIT.md (git log)

- **Commit no (tam):** `285d08ed236101ca10690869ded9397764bcf58f`
- **Commit no (kısa):** `285d08e`
- **Tarih:** 2026-06-01 04:28:30 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 56. `40264fc` — Stabilize dashboard runtime and UI state

- **Commit no (tam):** `40264fc7d7194184b243e8fb559ff2d592dfc3f5`
- **Commit no (kısa):** `40264fc`
- **Tarih:** 2026-06-01 04:28:30 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 57. `53479f6` — docs: sync GIT.md (git log)

- **Commit no (tam):** `53479f6121e2d9505684d544e2952f65c02664d0`
- **Commit no (kısa):** `53479f6`
- **Tarih:** 2026-06-01 02:49:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---

### 58. `e060cae` — Improve admin, dashboard, and bot detail UX with perf and scroll fixes.

- **Commit no (tam):** `e060cae4ef9d0eeccc1f264d105b52804cad0acd`
- **Commit no (kısa):** `e060cae`
- **Tarih:** 2026-06-01 02:49:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>
- **Detay:**
  - Admin accounts load via lite-first client flow and parallel full refresh on the server; bot trades panel gets TR timezone and layout fixes without page auto-scroll; dashboard wallet status, scroll restore utilities, manager log humanization, and production hardening updates ship together with dashboard-react scaffold.

---

### 59. `f0519b1` — docs: sync GIT.md (git log)

- **Commit no (tam):** `f0519b125ef97e8c19b57be4baec138c2138c8a4`
- **Commit no (kısa):** `f0519b1`
- **Tarih:** 2026-05-31 16:21:27 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 60. `dfd42cc` — Expand login page with zip welcome layout and market dock.

- **Commit no (tam):** `dfd42cc04305699d9bc1e8eb9b1fa445fb849a8c`
- **Commit no (kısa):** `dfd42cc`
- **Tarih:** 2026-05-31 16:21:27 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Add full-screen karşılama, live ticker, borsa saatleri/makro dock, and nebula background assets while keeping existing auth flows.

---

### 61. `3f93c07` — docs: sync GIT.md (git log)

- **Commit no (tam):** `3f93c077ae45d54fff5b996e0602bef8abb566be`
- **Commit no (kısa):** `3f93c07`
- **Tarih:** 2026-05-31 14:31:34 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 62. `44f08d8` — Redesign login page with zip AuthCard glass theme.

- **Commit no (tam):** `44f08d8f78a84c102c7232e161aa32d874db4c2a`
- **Commit no (kısa):** `44f08d8`
- **Tarih:** 2026-05-31 14:31:34 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Apply tradertrailing.zip visual language (gold accent, header tabs, hero badge) while keeping existing auth forms and API wiring.

---

### 63. `c69193c` — docs: sync GIT.md (git log)

- **Commit no (tam):** `c69193c2cd55a4e4e828f0eed32c21d839f9dac8`
- **Commit no (kısa):** `c69193c`
- **Tarih:** 2026-05-31 14:30:10 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 64. `5a99e35` — Fix Binance wallet errors, dashboard UX, and engine log stability.

- **Commit no (tam):** `5a99e35362df096d18449012339cc29ba53622c5`
- **Commit no (kısa):** `5a99e35`
- **Tarih:** 2026-05-31 14:30:10 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Correct API_UNAUTHORIZED vs CLOCK_DRIFT classification when signed URLs contain recvWindow, harden -1021 retries and timestamp handling, and improve admin/dashboard connectivity feedback.

---

### 65. `95318b1` — docs: sync GIT.md (git log)

- **Commit no (tam):** `95318b1707c62e5968751185024e432c556c87c0`
- **Commit no (kısa):** `95318b1`
- **Tarih:** 2026-05-31 03:01:36 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 66. `1e03319` — Fix dashboard connectivity, rate-limit toasts, and bot UX regressions.

- **Commit no (tam):** `1e03319ab536f6a82b8e568a04b7364245d65ed4`
- **Commit no (kısa):** `1e03319`
- **Tarih:** 2026-05-31 03:01:36 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Add home connectivity-check and CLOCK_DRIFT classification; debounce 429 toasts and tx-history backoff; recover wallet on focus/online; leaderboard/symbol-dropdown/KPI fixes; bot Parametreler modal and virtual budget cap; engine log dedupe; manager log humanization; admin retry on 499; spec and module docs.

---

### 67. `99aeb83` — docs: sync GIT.md (git log)

- **Commit no (tam):** `99aeb835fbad9f546efb843fbfa4db8791e4a634`
- **Commit no (kısa):** `99aeb83`
- **Tarih:** 2026-05-30 04:41:55 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 68. `e17f1da` — UI: redesign admin header/KPI/tabs and improve dashboard Bots persistence.

- **Commit no (tam):** `e17f1dae027230fb7319742baf6fce22023dc97d`
- **Commit no (kısa):** `e17f1da`
- **Tarih:** 2026-05-30 04:41:55 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Admin gets a centered appbar with animated logo, compact KPI strip, fixed tab slider positioning, and yellow-bordered Admin badge. Dashboard tabs are centered; Bots tab and bot detail pages cache DOM to avoid redraw on return.

---

### 69. `4b8b710` — docs: sync GIT.md with Bots tab and wallet UX commit details.

- **Commit no (tam):** `4b8b71092d20fb0439f90dfba8adc1a961c6e3c7`
- **Commit no (kısa):** `4b8b710`
- **Tarih:** 2026-05-30 04:03:14 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 70. `3f64a0a` — docs: sync GIT.md (git log)

- **Commit no (tam):** `3f64a0a781d036b147b98ecbcd4936850d4936fa`
- **Commit no (kısa):** `3f64a0a`
- **Tarih:** 2026-05-30 04:02:43 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 71. `a8280fd` — Restore dashboard Bots tab and improve wallet/manager spot UX.

- **Commit no (tam):** `a8280fd9ed851ed0397e939cd6677af04ca0980b`
- **Commit no (kısa):** `a8280fd`
- **Tarih:** 2026-05-30 04:02:43 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Bring back Botlar tab content (bot list, performance, leaderboard), sync dual bot tables, wallet live badges and price blink; add manager logHumanize spot_routes templates and transient quick_data logging.

---

### 72. `a30acfa` — docs: sync GIT.md (git log)

- **Commit no (tam):** `a30acfa3506f5a80c21e1d1a1052808b2920207a`
- **Commit no (kısa):** `a30acfa`
- **Tarih:** 2026-05-30 03:12:50 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 73. `42444b9` — Perf: batch live API, bulk state loads, and calmer UI polling.

- **Commit no (tam):** `42444b9176ead5ceb2b896177c144ec52f0dc548`
- **Commit no (kısa):** `42444b9`
- **Tarih:** 2026-05-30 03:12:50 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Dashboard uses GET /api/bots-engine/batch/live (max 50 bots); bots list
  - avoids N+1 load_state; live cache 3s with invalidate on save_state; bot
  - detail drops redundant strip-price poll and aligns polls to 3s/10s.

---

### 74. `5dc6e2c` — docs: sync GIT.md (git log)

- **Commit no (tam):** `5dc6e2c8e1940c0681373c8e055cb0958099f298`
- **Commit no (kısa):** `5dc6e2c`
- **Tarih:** 2026-05-30 03:10:02 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 75. `4857932` — UI stability, manager metrics, and test-account worker hardening.

- **Commit no (tam):** `48579320380a13930c10b4cc6e847474e734dc83`
- **Commit no (kısa):** `4857932`
- **Tarih:** 2026-05-30 03:10:02 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Bot detail hydration/cache fixes, perf label corrections, manager hourly
  - request counting and log scroll; dashboard/home updates; paper test ticks
  - and orchestrator noise reduction for test accounts.

---

### 76. `71e8888` — docs: sync GIT.md (git log)

- **Commit no (tam):** `71e8888a9f2808db8762e909a17e70faff27ebe4`
- **Commit no (kısa):** `71e8888`
- **Tarih:** 2026-05-30 02:33:45 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 77. `13b5770` — Improve test paper trading realism and align test KPIs across admin and dashboard.

- **Commit no (tam):** `13b577044972ef0a7420114557ee449c41d22916`
- **Commit no (kısa):** `13b5770`
- **Tarih:** 2026-05-30 02:33:45 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Add shared simulation helpers (fees, slippage, latency), sync admin spot/daily PnL with dashboard bot equity, refresh bot performance labels, remove debug error strips, and style bot back links.

---

### 78. `b2ab64c` — docs: sync GIT.md (git log)

- **Commit no (tam):** `b2ab64c6ed1b5c46d45b7a996cb02d5c14e4a46a`
- **Commit no (kısa):** `b2ab64c`
- **Tarih:** 2026-05-30 02:13:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 79. `329f600` — Align admin active bot count and reduce Binance/asyncio log noise.

- **Commit no (tam):** `329f600706905921ff79df6a8efb314602266e86`
- **Commit no (kısa):** `329f600`
- **Tarih:** 2026-05-30 02:13:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Admin AKTİF BOT uses running+paused (case-insensitive) via bot_status_utils; klines normalize BTC→BTCUSDT; transient Binance/asyncio errors log at DEBUG.

---

### 80. `385d3e9` — docs: sync GIT.md (git log)

- **Commit no (tam):** `385d3e9a8cc94299ac5f3dad5cfd37d973aa96ad`
- **Commit no (kısa):** `385d3e9`
- **Tarih:** 2026-05-30 01:39:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 81. `2a7894d` — Fix test account wallet KPI/strip and harden upstream error handling.

- **Commit no (tam):** `2a7894d66cf23956afc8c23effa20e16e43d2d0f`
- **Commit no (kısa):** `2a7894d`
- **Tarih:** 2026-05-30 01:39:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Unify test paper wallet via build_test_account_wallet; align dashboard strip with running bot equity and stop varlıklar price flicker. Reduce manager log spam on transient Binance/deposit failures; reconcile stale bot perf cycle files on read/start.

---

### 82. `7271b17` — docs: sync GIT.md (git log)

- **Commit no (tam):** `7271b175296ba4871daea4a2462804918c65cb17`
- **Commit no (kısa):** `7271b17`
- **Tarih:** 2026-05-29 23:51:06 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 83. `dc69f29` — docs: sync GIT.md (git log)

- **Commit no (tam):** `dc69f29cb946b242b0e49df13fb3cd69c41c012c`
- **Commit no (kısa):** `dc69f29`
- **Tarih:** 2026-05-29 23:51:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 84. `9ec9b4f` — Fix bot state hero panel live updates and duration ticker.

- **Commit no (tam):** `9ec9b4fff40b1bd7614b9cc1d69f11e370246598`
- **Commit no (kısa):** `9ec9b4f`
- **Tarih:** 2026-05-29 23:51:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Keep süre/bakiye/K/Z fresh via dedicated duration poll and /live-only hero updates while running; avoid stale detail patches overwriting the panel.

---

### 85. `eda020a` — docs: sync GIT.md (git log)

- **Commit no (tam):** `eda020a6c43a0925dd04761b83f62995c201849b`
- **Commit no (kısa):** `eda020a`
- **Tarih:** 2026-05-29 23:45:36 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 86. `419defa` — docs: sync GIT.md (git log)

- **Commit no (tam):** `419defa4bebc1a450e096704125514d83beff688`
- **Commit no (kısa):** `419defa`
- **Tarih:** 2026-05-29 23:45:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 87. `a09249b` — Fix manager global restart UnboundLocalError causing HTTP 500.

- **Commit no (tam):** `a09249bba6ecb4c1564c7d5ca9427ecf6313d26f`
- **Commit no (kısa):** `a09249b`
- **Tarih:** 2026-05-29 23:45:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Declare global _global_action_running in schedule_global_action so POST /api/global/restart works; add clearer logHumanize text for global action 500 responses.

---

### 88. `19eea96` — docs: sync GIT.md (git log)

- **Commit no (tam):** `19eea9641518474f96dbdf5d77fbcfd36a9a4397`
- **Commit no (kısa):** `19eea96`
- **Tarih:** 2026-05-29 23:43:27 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 89. `1a87f0f` — docs: sync GIT.md (git log)

- **Commit no (tam):** `1a87f0f15a30f1fdd29f9ca65e301596a6fabc12`
- **Commit no (kısa):** `1a87f0f`
- **Tarih:** 2026-05-29 23:43:17 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 90. `5f6c321` — docs: sync GIT.md (git log)

- **Commit no (tam):** `5f6c32166a325569102ca9edf3b7c5b992eb4ff1`
- **Commit no (kısa):** `5f6c321`
- **Tarih:** 2026-05-29 23:43:10 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 91. `80e39e9` — Bot UI/engine reliability: daily K/Z, cycle timer, logs, and manager global actions.

- **Commit no (tam):** `80e39e95f5a748ce69d0226ab07bf0e34efc2ffd`
- **Commit no (kısa):** `80e39e9`
- **Tarih:** 2026-05-29 23:43:10 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Fix slow bot warm-up, 15s order timeout, health log noise, engine log flicker, and daily PnL from equity; improve cycle-start log labels (Quote), commission display, and manager global restart busy handling without false WARN spam.

---

### 92. `4245e01` — docs: sync GIT.md (git log)

- **Commit no (tam):** `4245e0136ec7eb389893587970b5c58b29b1deb7`
- **Commit no (kısa):** `4245e01`
- **Tarih:** 2026-05-29 22:01:45 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 93. `1db1ee5` — docs: sync GIT.md (git log)

- **Commit no (tam):** `1db1ee532490656f75dd5569ce0a828f050353d1`
- **Commit no (kısa):** `1db1ee5`
- **Tarih:** 2026-05-29 22:01:41 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 94. `c2c6cae` — docs: sync GIT.md (git log)

- **Commit no (tam):** `c2c6caea7f337e796cc42a06e5ea8b5a4d31f803`
- **Commit no (kısa):** `c2c6cae`
- **Tarih:** 2026-05-29 22:01:28 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 95. `9987ecb` — docs: sync GIT.md (git log)

- **Commit no (tam):** `9987ecb1ec1b7c75a7f9f9314a14f3560b66920d`
- **Commit no (kısa):** `9987ecb`
- **Tarih:** 2026-05-29 22:01:19 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 96. `379bb3c` — Bot session tenure, connectivity restore, synthetic cycle logs, and wallet KPI alignment.

- **Commit no (tam):** `379bb3c7985a0eb0171935e072cdf72b6c2a7462`
- **Commit no (kısa):** `379bb3c`
- **Tarih:** 2026-05-29 22:01:19 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Add bot_session and wallet_display modules; fix execution timedelta bug; expand engine log synthesis, connectivity stable flush, and admin/dashboard wallet strip parity.

---

### 97. `2498bb1` — Dashboard, manager, and engine hardening across bot perf, leaderboard, and ops.

- **Commit no (tam):** `2498bb1472406a809a10701ac9d28265f4905581`
- **Commit no (kısa):** `2498bb1`
- **Tarih:** 2026-05-29 15:10:26 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Align Mevcut Botlar with live bot K/Z and centered table layout; fix leaderboard equity metrics and bot performance rounds; add full stack manager reboot, log humanization, RAM capture tooling, rate limiting, and state trim; update master spec and module docs.

---

### 98. `7756f7c` — docs: sync GIT.md (git log)

- **Commit no (tam):** `7756f7c2c37b81d2b9fdce38cb0652adc5afa94f`
- **Commit no (kısa):** `7756f7c`
- **Tarih:** 2026-05-29 02:42:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 99. `5a163ba` — Bot health resilience, grid/profit UI polish, and engine hardening.

- **Commit no (tam):** `5a163bad0b2e2b69d3af469b6e840434752e60a1`
- **Commit no (kısa):** `5a163ba`
- **Tarih:** 2026-05-29 02:42:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Expand health_watch with recoverable tick errors, auto loop restart logging,
  - and deduped engine-log alerts; refresh bot detail health UX (no banner, border
  - badges, registry rows). Fix LOT_SIZE preflight, cycle_opened_at, trade counts,
  - and grid tepe/dip % vs reference or avg cost with stable table columns. Add
  - perf/transaction file stores, order_qty helper, dashboard and manager updates.

---

### 100. `9634309` — docs: sync GIT.md (git log)

- **Commit no (tam):** `9634309f7ab5f16c16d459f9d0f402201b075d9f`
- **Commit no (kısa):** `9634309`
- **Tarih:** 2026-05-28 14:25:09 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 101. `3531540` — Grid trailing, Binance connectivity, and dashboard KPI hardening.

- **Commit no (tam):** `35315408f3bd82aded9d3df80cf6b027e6b76573`
- **Commit no (kısa):** `3531540`
- **Tarih:** 2026-05-28 14:25:09 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Lock dip/tepe to min/max anchors in engine and UI envelope, improve health/log UX with export and connectivity alerts, and stop dashboard wallet KPIs from showing false Canlı state or PnL flicker when Binance is unreachable.

---

### 102. `5481c74` — docs: sync GIT.md (git log)

- **Commit no (tam):** `5481c74e66082622c262039d66ec4cac9b573dd1`
- **Commit no (kısa):** `5481c74`
- **Tarih:** 2026-05-25 04:12:08 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>

---

### 103. `1974512` — Add grid trade modal, manager log UX, and bot detail sync fixes.

- **Commit no (tam):** `1974512fc9fe7d150259efa996c9b896f1539378`
- **Commit no (kısa):** `1974512`
- **Tarih:** 2026-05-25 04:12:08 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>
- **Detay:**
  - Grid tur işlemlerine tıklanınca detay modalı (tetik, tepe/dip, gerçekleşme); trades API grid_detail ve tur arşivi. Manager logları Türkçeleştirme ve kaydırma düzeltmeleri. Bot tur UI senkronu, dashboard ve ilgili hardening.

---

### 104. `1cd3a5e` — Update marketing submodule to latest landing and deploy changes.

- **Commit no (tam):** `1cd3a5e224209e06c5c011eb6141344835a084af`
- **Commit no (kısa):** `1cd3a5e`
- **Tarih:** 2026-05-24 04:50:41 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>

---

### 105. `805594b` — Engine log UX, health alerts, grid trailing hardening, and tur trade fixes.

- **Commit no (tam):** `805594bc839e196b860244c6371b7274e6461657`
- **Commit no (kısa):** `805594b`
- **Tarih:** 2026-05-24 04:49:54 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>
- **Detay:**
  - Improve bot detail logs (Tur labels, besmele, bakiye enrichment), add worker health_watch + UI alerts, parallel grid trailing and profit-exit trigger updates, config grid preflight validation, and correct initial-allocation trade display without meaningless gerçekleşme %.

---

### 106. `4ba8f8c` — Checkpoint: pre profit-exit trigger fix (REST SSOT, UI, ops reorg).

- **Commit no (tam):** `4ba8f8cfcfc455dcbc77824fad6ac13308da29b6`
- **Commit no (kısa):** `4ba8f8c`
- **Tarih:** 2026-05-23 20:42:05 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>
- **Detay:**
  - Save working tree before fixing DCA grid trailing profit sell arming below configured rise threshold.

---

### 107. `8c5aa65` — chore: history — 2026-05-06 öncesi tüm commitler squash edildi

- **Commit no (tam):** `8c5aa654d9814442341b28a89bdc694fa54f775b`
- **Commit no (kısa):** `8c5aa65`
- **Tarih:** 2026-06-06 04:58:48 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.25>

---


## Yenileme

Her commit sonrası `post-commit` hook otomatik çalışır.

Elle güncellemek için:

```bash
python3 scripts/devops/sync_git_log.py
make hooks   # hook kurulumu (ilk sefer)
```

