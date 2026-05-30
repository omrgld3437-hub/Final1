# Git — Final1

> HEAD `4a0c8c0` · Toplam **186** commit · branch `main`

## GitHub

| Alan | Değer |
|------|-------|
| Repository | [omrgld3437-hub/Final1](https://github.com/omrgld3437-hub/Final1) |
| Web | https://github.com/omrgld3437-hub/Final1 |
| SSH (origin) | `git@github.com:omrgld3437-hub/Final1.git` |
| HTTPS | `https://github.com/omrgld3437-hub/Final1.git` |
| Aktif branch | `main` |
| HEAD (kısa) | `4a0c8c0` |
| HEAD (tam) | `4a0c8c02af6fbd282d50d13de0b38307223cd3b2` |
| Remote durumu | `origin/main`'den **1** commit önde |

## Submodule: marketing

| Alan | Değer |
|------|-------|
| Gitlink (HEAD) | `9a2d089` (`9a2d089773bb583e393b204813bc47eeb1287279`) |
| Klasör | `marketing/` (ayrı git repo) |

## Commit geçmişi (`git log`)

En yeni commit üstte.

### 1. `4a0c8c0` — Restore dashboard Bots tab and improve wallet/manager spot UX.

- **Commit no (tam):** `4a0c8c02af6fbd282d50d13de0b38307223cd3b2`
- **Commit no (kısa):** `4a0c8c0`
- **Tarih:** 2026-05-30 04:02:43 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Bring back Botlar tab content (bot list, performance, leaderboard), sync dual bot tables, wallet live badges and price blink; add manager logHumanize spot_routes templates and transient quick_data logging.

---

### 2. `d1e1413` — docs: sync GIT.md (git log)

- **Commit no (tam):** `d1e14132a2b551fc310ebf29f80c70c24e8d6b45`
- **Commit no (kısa):** `d1e1413`
- **Tarih:** 2026-05-30 03:12:50 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 3. `6101503` — Perf: batch live API, bulk state loads, and calmer UI polling.

- **Commit no (tam):** `6101503cd6d0bc9f0c58137dbae77ed606baf847`
- **Commit no (kısa):** `6101503`
- **Tarih:** 2026-05-30 03:12:50 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Dashboard uses GET /api/bots-engine/batch/live (max 50 bots); bots list
  - avoids N+1 load_state; live cache 3s with invalidate on save_state; bot
  - detail drops redundant strip-price poll and aligns polls to 3s/10s.

---

### 4. `b222a55` — docs: sync GIT.md (git log)

- **Commit no (tam):** `b222a552ee0b1c6baa9ffe5b1107437a33644689`
- **Commit no (kısa):** `b222a55`
- **Tarih:** 2026-05-30 03:10:02 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 5. `c47d391` — UI stability, manager metrics, and test-account worker hardening.

- **Commit no (tam):** `c47d391ee4e7342e782be744f40828ac77c11eb1`
- **Commit no (kısa):** `c47d391`
- **Tarih:** 2026-05-30 03:10:02 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Bot detail hydration/cache fixes, perf label corrections, manager hourly
  - request counting and log scroll; dashboard/home updates; paper test ticks
  - and orchestrator noise reduction for test accounts.

---

### 6. `5ba06fe` — docs: sync GIT.md (git log)

- **Commit no (tam):** `5ba06fe4fac0cdb4094f9649829a097c7e5f17c2`
- **Commit no (kısa):** `5ba06fe`
- **Tarih:** 2026-05-30 02:33:45 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 7. `7b8d1d2` — Improve test paper trading realism and align test KPIs across admin and dashboard.

- **Commit no (tam):** `7b8d1d2632b1bcd4a810043c3fbee18549565d34`
- **Commit no (kısa):** `7b8d1d2`
- **Tarih:** 2026-05-30 02:33:45 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Add shared simulation helpers (fees, slippage, latency), sync admin spot/daily PnL with dashboard bot equity, refresh bot performance labels, remove debug error strips, and style bot back links.

---

### 8. `2b6259e` — docs: sync GIT.md (git log)

- **Commit no (tam):** `2b6259ec3974fb243fe171db3cbfa73feb775a1a`
- **Commit no (kısa):** `2b6259e`
- **Tarih:** 2026-05-30 02:13:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 9. `5c4268f` — Align admin active bot count and reduce Binance/asyncio log noise.

- **Commit no (tam):** `5c4268fcff0422d3f25c12896cb5446ed24c4dc7`
- **Commit no (kısa):** `5c4268f`
- **Tarih:** 2026-05-30 02:13:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Admin AKTİF BOT uses running+paused (case-insensitive) via bot_status_utils; klines normalize BTC→BTCUSDT; transient Binance/asyncio errors log at DEBUG.

---

### 10. `64e9548` — docs: sync GIT.md (git log)

- **Commit no (tam):** `64e9548ef9e4fd720ee921adc86c3cd4f2ca5cf0`
- **Commit no (kısa):** `64e9548`
- **Tarih:** 2026-05-30 01:39:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 11. `c9eb79d` — Fix test account wallet KPI/strip and harden upstream error handling.

- **Commit no (tam):** `c9eb79d56111fdd658a1e449043c98db8bccd3b2`
- **Commit no (kısa):** `c9eb79d`
- **Tarih:** 2026-05-30 01:39:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Unify test paper wallet via build_test_account_wallet; align dashboard strip with running bot equity and stop varlıklar price flicker. Reduce manager log spam on transient Binance/deposit failures; reconcile stale bot perf cycle files on read/start.

---

### 12. `d0e5d36` — docs: sync GIT.md (git log)

- **Commit no (tam):** `d0e5d361b56d8df7e724fe1d6951e99c23837bdc`
- **Commit no (kısa):** `d0e5d36`
- **Tarih:** 2026-05-29 23:51:06 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 13. `40f92bc` — docs: sync GIT.md (git log)

- **Commit no (tam):** `40f92bcbf92d3e29cb4b91c13494d8c0289b0a14`
- **Commit no (kısa):** `40f92bc`
- **Tarih:** 2026-05-29 23:51:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 14. `80d8055` — Fix bot state hero panel live updates and duration ticker.

- **Commit no (tam):** `80d80550c5ef2129aae13aace5675ba8bb2eae0c`
- **Commit no (kısa):** `80d8055`
- **Tarih:** 2026-05-29 23:51:03 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Keep süre/bakiye/K/Z fresh via dedicated duration poll and /live-only hero updates while running; avoid stale detail patches overwriting the panel.

---

### 15. `b58ec63` — docs: sync GIT.md (git log)

- **Commit no (tam):** `b58ec6376d18f5bfbfbfa3f6bbb2dce8929db790`
- **Commit no (kısa):** `b58ec63`
- **Tarih:** 2026-05-29 23:45:36 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 16. `130f23e` — docs: sync GIT.md (git log)

- **Commit no (tam):** `130f23e3efa1b4c4ea4f2753122ee17855ce4cdc`
- **Commit no (kısa):** `130f23e`
- **Tarih:** 2026-05-29 23:45:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 17. `26f244c` — Fix manager global restart UnboundLocalError causing HTTP 500.

- **Commit no (tam):** `26f244c44db15d772f867d847c8c03bd1392e9d7`
- **Commit no (kısa):** `26f244c`
- **Tarih:** 2026-05-29 23:45:34 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Declare global _global_action_running in schedule_global_action so POST /api/global/restart works; add clearer logHumanize text for global action 500 responses.

---

### 18. `45762b5` — docs: sync GIT.md (git log)

- **Commit no (tam):** `45762b542f097c10903d4924c78b05dc7a0f1535`
- **Commit no (kısa):** `45762b5`
- **Tarih:** 2026-05-29 23:43:27 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 19. `c9ed330` — docs: sync GIT.md (git log)

- **Commit no (tam):** `c9ed330ce2d63bbd17c769db970a7e685a65949d`
- **Commit no (kısa):** `c9ed330`
- **Tarih:** 2026-05-29 23:43:17 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 20. `5ce1931` — docs: sync GIT.md (git log)

- **Commit no (tam):** `5ce193135ab711efc67ead70593574a13b15604e`
- **Commit no (kısa):** `5ce1931`
- **Tarih:** 2026-05-29 23:43:10 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 21. `7731660` — Bot UI/engine reliability: daily K/Z, cycle timer, logs, and manager global actions.

- **Commit no (tam):** `77316606b4b6e33d8c0d91af807ae43ece1e0c4c`
- **Commit no (kısa):** `7731660`
- **Tarih:** 2026-05-29 23:43:10 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Fix slow bot warm-up, 15s order timeout, health log noise, engine log flicker, and daily PnL from equity; improve cycle-start log labels (Quote), commission display, and manager global restart busy handling without false WARN spam.

---

### 22. `6efd6f2` — docs: sync GIT.md (git log)

- **Commit no (tam):** `6efd6f2929d1eab162eb82ddcf49f57c239220a0`
- **Commit no (kısa):** `6efd6f2`
- **Tarih:** 2026-05-29 22:01:45 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 23. `e7ab403` — docs: sync GIT.md (git log)

- **Commit no (tam):** `e7ab403ad233b29fdd6f8b9b715bf7e4cf4d051e`
- **Commit no (kısa):** `e7ab403`
- **Tarih:** 2026-05-29 22:01:41 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 24. `8a32511` — docs: sync GIT.md (git log)

- **Commit no (tam):** `8a32511cd942e83e85fcae39c690d576a64c199c`
- **Commit no (kısa):** `8a32511`
- **Tarih:** 2026-05-29 22:01:28 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 25. `17c7138` — docs: sync GIT.md (git log)

- **Commit no (tam):** `17c71384f33f6c99241ff48018c4850149cd0b07`
- **Commit no (kısa):** `17c7138`
- **Tarih:** 2026-05-29 22:01:19 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>

---

### 26. `6efb1c5` — Bot session tenure, connectivity restore, synthetic cycle logs, and wallet KPI alignment.

- **Commit no (tam):** `6efb1c5d7c413450963c229b99ee61cb6763a58e`
- **Commit no (kısa):** `6efb1c5`
- **Tarih:** 2026-05-29 22:01:19 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.21>
- **Detay:**
  - Add bot_session and wallet_display modules; fix execution timedelta bug; expand engine log synthesis, connectivity stable flush, and admin/dashboard wallet strip parity.

---

### 27. `4af6274` — Dashboard, manager, and engine hardening across bot perf, leaderboard, and ops.

- **Commit no (tam):** `4af6274785dc0513c920f0a0d8b6a99ded099deb`
- **Commit no (kısa):** `4af6274`
- **Tarih:** 2026-05-29 15:10:26 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Align Mevcut Botlar with live bot K/Z and centered table layout; fix leaderboard equity metrics and bot performance rounds; add full stack manager reboot, log humanization, RAM capture tooling, rate limiting, and state trim; update master spec and module docs.

---

### 28. `d19ed58` — docs: sync GIT.md (git log)

- **Commit no (tam):** `d19ed58b33c8311bf8a7e8f1087eb639e9e13bd5`
- **Commit no (kısa):** `d19ed58`
- **Tarih:** 2026-05-29 02:42:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 29. `21db228` — Bot health resilience, grid/profit UI polish, and engine hardening.

- **Commit no (tam):** `21db22880c7bef30401e6d4c6607108d391b60d2`
- **Commit no (kısa):** `21db228`
- **Tarih:** 2026-05-29 02:42:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Expand health_watch with recoverable tick errors, auto loop restart logging,
  - and deduped engine-log alerts; refresh bot detail health UX (no banner, border
  - badges, registry rows). Fix LOT_SIZE preflight, cycle_opened_at, trade counts,
  - and grid tepe/dip % vs reference or avg cost with stable table columns. Add
  - perf/transaction file stores, order_qty helper, dashboard and manager updates.

---

### 30. `2a5dcd3` — docs: sync GIT.md (git log)

- **Commit no (tam):** `2a5dcd3749212819373c9ae75a46b5360aa929f9`
- **Commit no (kısa):** `2a5dcd3`
- **Tarih:** 2026-05-28 14:25:09 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 31. `6066d76` — Grid trailing, Binance connectivity, and dashboard KPI hardening.

- **Commit no (tam):** `6066d76754d8b4f9df0655288d286e5d050a13fc`
- **Commit no (kısa):** `6066d76`
- **Tarih:** 2026-05-28 14:25:09 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - Lock dip/tepe to min/max anchors in engine and UI envelope, improve health/log UX with export and connectivity alerts, and stop dashboard wallet KPIs from showing false Canlı state or PnL flicker when Binance is unreachable.

---

### 32. `06cef9a` — docs: sync GIT.md (git log)

- **Commit no (tam):** `06cef9a963df271c824cbbf0c5d0932c6a3209e8`
- **Commit no (kısa):** `06cef9a`
- **Tarih:** 2026-05-25 04:12:08 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>

---

### 33. `901f1a3` — Add grid trade modal, manager log UX, and bot detail sync fixes.

- **Commit no (tam):** `901f1a38ef259b1628b882b0c499c54c09009885`
- **Commit no (kısa):** `901f1a3`
- **Tarih:** 2026-05-25 04:12:08 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>
- **Detay:**
  - Grid tur işlemlerine tıklanınca detay modalı (tetik, tepe/dip, gerçekleşme); trades API grid_detail ve tur arşivi. Manager logları Türkçeleştirme ve kaydırma düzeltmeleri. Bot tur UI senkronu, dashboard ve ilgili hardening.

---

### 34. `9cd5850` — Update marketing submodule to latest landing and deploy changes.

- **Commit no (tam):** `9cd58508c8eb8f39db2e310d75c5812bc67a0468`
- **Commit no (kısa):** `9cd5850`
- **Tarih:** 2026-05-24 04:50:41 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>

---

### 35. `f2b5379` — Engine log UX, health alerts, grid trailing hardening, and tur trade fixes.

- **Commit no (tam):** `f2b5379965137f4740064252dcc16e194153cd08`
- **Commit no (kısa):** `f2b5379`
- **Tarih:** 2026-05-24 04:49:54 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>
- **Detay:**
  - Improve bot detail logs (Tur labels, besmele, bakiye enrichment), add worker health_watch + UI alerts, parallel grid trailing and profit-exit trigger updates, config grid preflight validation, and correct initial-allocation trade display without meaningless gerçekleşme %.

---

### 36. `a699226` — Checkpoint: pre profit-exit trigger fix (REST SSOT, UI, ops reorg).

- **Commit no (tam):** `a699226c773b7d0cb8ab5bfd3de660899a62f29f`
- **Commit no (kısa):** `a699226`
- **Tarih:** 2026-05-23 20:42:05 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.12>
- **Detay:**
  - Save working tree before fixing DCA grid trailing profit sell arming below configured rise threshold.

---

### 37. `f203968` — Sunucu deploy.sh: guncel commit ciktida, degisti ise belirtilir

- **Commit no (tam):** `f2039688c3cd0bcdbf5bd0838842a943ecf9291a`
- **Commit no (kısa):** `f203968`
- **Tarih:** 2026-02-25 06:09:36 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 38. `f9fcf9b` — Linux HTML başlatma, bakiye doğrulama, dual PNL (Cash/Inventory), perfPanel+tradesPanel, Aktif Emirler sadece Anasayfa

- **Commit no (tam):** `f9fcf9bcbd3d6837662549eca990a6045f92de35`
- **Commit no (kısa):** `f9fcf9b`
- **Tarih:** 2026-02-25 06:03:51 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 39. `2fea40c` — Admin: askı cache invalidation + çevrimiçi last_seen 2dk; sohbet flicker/typing düzeltmesi; coin logo cache 31 gün

- **Commit no (tam):** `2fea40ce1f4362ac9f1133d0c05c98a9fd03144c`
- **Commit no (kısa):** `2fea40c`
- **Tarih:** 2026-02-19 06:10:25 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 40. `da82dd3` — Sohbet: admin yazıyor göstergesi + kullanıcı çevrimiçi/çevrimdışı nokta (yeşil/kırmızı)

- **Commit no (tam):** `da82dd38212237c7b96597374b2ea93938b9bc39`
- **Commit no (kısa):** `da82dd3`
- **Tarih:** 2026-02-19 05:56:13 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 41. `8fa1d4a` — Sohbet: anında mesaj (admin poll 2.5s, kullanıcı poll 2.5s, gönderim sonrası yenileme, welcome 1.2s)

- **Commit no (tam):** `8fa1d4a4731c9d6c2e215c4ef283b47faf4a375b`
- **Commit no (kısa):** `8fa1d4a`
- **Tarih:** 2026-02-19 05:46:24 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 42. `4a93a08` — Login: kripto logo flicker onleme - liste bir kez render, sonra sadece fiyat/chg guncelle

- **Commit no (tam):** `4a93a08717a30602cdc8ba9a1f446ca58421d4e9`
- **Commit no (kısa):** `4a93a08`
- **Tarih:** 2026-02-19 05:31:41 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 43. `c82c2d7` — Aktif Emirler paneli: emir yokken her zaman İşlem Geçmişi altında (txPanel.after)

- **Commit no (tam):** `c82c2d797abed869efad750cfe111798cbf2e556`
- **Commit no (kısa):** `c82c2d7`
- **Tarih:** 2026-02-19 02:28:32 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 44. `37791ce` — Admin: sunucu paneli, audit, hata logları, API rehberi

- **Commit no (tam):** `37791ce96e060ac8741c48b09139ee7e0a35cb10`
- **Commit no (kısa):** `37791ce`
- **Tarih:** 2026-02-19 02:25:30 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Sunucu paneli: tasarım (masaüstü 3 sütun), Erişimi Kapat/Anlık indirme-yükleme kaldırıldı
  - - Sunucudan Çık: ana uvicorn sürecini kapat (gerçek kapanma)
  - - run.sh: proje köküne wrapper, scripts/run.sh fallback
  - - Hata logları: sıfırla = backend clear, Binance tile hatası raporlama kaldırıldı
  - - İşlem geçmişi: target_user_label (ad soyad), modal yeniden tasarım, mobil kart görünümü
  - - Admin audit API: ip_masked=false (admin panelinde IP görünsün)
  - - İlk giriş modalı: Binance API rehberi güncellendi, güvenlik (para çekme yok) metni
  - - Sekme: kayıtlı sekme ilk yüklemede animasyonsuz, server panel değerleri görünür

---

### 45. `a411a4b` — fix: logo flicker, price blink, bot performance period update; suppress ProactorBasePipeTransport log

- **Commit no (tam):** `a411a4b86b455e78b8d9364830945a3898d6d5fe`
- **Commit no (kısa):** `a411a4b`
- **Tarih:** 2026-02-19 00:39:19 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 46. `535a648` — omeraltin.com kapanma: HTML watchdog + auto_start + start.py sertlestirme

- **Commit no (tam):** `535a6480ff06ad8f1f74b44e846778de56c1a649`
- **Commit no (kısa):** `535a648`
- **Tarih:** 2026-02-19 00:00:17 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Manager: HTML (8080) auto_start_if_needed ile acilista baslatiliyor
  - - Manager: start_html_watchdog() her 60sn port kontrolu; kapaliysa yeniden baslat
  - - Omeraltinhtml/start.py: log_access ve print_stats_loop stdout BrokenPipe/IOError karsi korumali

---

### 47. `ae3d5d3` — Admin tabs: mobile Sekmeler fix + perf (store, preload, instant switch)

- **Commit no (tam):** `ae3d5d3cac2cd4e5404e08e9ede6326a614bd601`
- **Commit no (kısa):** `ae3d5d3`
- **Tarih:** 2026-02-18 23:56:28 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Mobile: portal for tabs menu, 250ms click-outside guard, event delegation, rAF+visualViewport positioning
  - - AdminStore with TTL, inflight coalescing, abort; loadTab + switchToken guard for no stale render
  - - switchTab: immediate panel + skeleton, loadTab() before animation; preload queue concurrency 2
  - - CSS: #adminTabsPortal, tab-indicator transition, touch-action on toggle
  - - Polling/breach only when visibilityState visible; __adminDump, __ADMIN_DEBUG
  - - Dossier + trailing DCA spec + tests; other app/dashboard changes

---

### 48. `801d68d` — Bot sayfası: Başlat kaldırıldı; 401'de Hata (API anahtarı) gösterimi; strip fiyat/24h/mini grafik layout kayması düzeltmesi

- **Commit no (tam):** `801d68d86b35e6c03286219f63998626eb3bdd43`
- **Commit no (kısa):** `801d68d`
- **Tarih:** 2026-02-17 17:33:06 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 49. `b2717f2` — Manager: GET / redirect, 401/ConnectionResetError log bastırma; Oluştur=anında başlat; Başlat butonu sadece stopped; Leaderboard parametreleri görüntüle + modal

- **Commit no (tam):** `b2717f28f2409a6b6037d5ca88b6520adc6a491c`
- **Commit no (kısa):** `b2717f2`
- **Tarih:** 2026-02-17 17:26:59 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 50. `ef90350` — Bot 401: pause bot on Binance Unauthorized, set API_UNAUTHORIZED and ERROR event for UI

- **Commit no (tam):** `ef903504d00ff9d7f9519af2b8d563468e89ae52`
- **Commit no (kısa):** `ef90350`
- **Tarih:** 2026-02-17 17:14:04 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 51. `9a1b6f8` — UI/UX: flicker fixes, mobile padding, admin tabs, leaderboard, chat; deploy nginx config

- **Commit no (tam):** `9a1b6f8506c86cbb64e5620823c7e4a78aa10075`
- **Commit no (kısa):** `9a1b6f8`
- **Tarih:** 2026-02-17 17:05:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 52. `d0c1f26` — Deploy: Nginx domain eski gorunum notu (DEPLOY.md) + show-nginx-config.bat (Windows)

- **Commit no (tam):** `d0c1f263a0cdf7b58c9283300b6854f0ddee001c`
- **Commit no (kısa):** `d0c1f26`
- **Tarih:** 2026-02-17 15:21:54 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 53. `89cf45b` — start.bat: teshis ciktisi - Dashboard (diskte) surum + build-info URL + eski gorunum notu

- **Commit no (tam):** `89cf45bc3548800e1176e1f8800a11808985e228`
- **Commit no (kısa):** `89cf45b`
- **Tarih:** 2026-02-17 15:07:57 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 54. `e81ea4f` — build-info login fix + no-cache UI: path normalize, route ilk sırada, no-cache middleware, DEPLOY notları

- **Commit no (tam):** `e81ea4f5d985d8293de523ae0a79aa3da1fb85f5`
- **Commit no (kısa):** `e81ea4f`
- **Tarih:** 2026-02-17 15:03:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 55. `e8cd6f8` — api/debug/build-info: lockdown whitelist'e ekle (giriş olmadan erişilebilsin)

- **Commit no (tam):** `e8cd6f8426b18e511246128a362d42146a38fa6f`
- **Commit no (kısa):** `e8cd6f8`
- **Tarih:** 2026-02-17 14:55:15 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 56. `61248cf` — Deploy: Değişiklikler yansımıyor rehberi + /api/debug/build-info endpoint

- **Commit no (tam):** `61248cfc2b061dcc7a7b5a5415bb1a7d9de8c66b`
- **Commit no (kısa):** `61248cf`
- **Tarih:** 2026-02-17 14:51:26 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 57. `f5fb145` — Bot engine, routes, cycle_ledger, dashboard snapshot, UI: tüm kalan değişiklikler

- **Commit no (tam):** `f5fb14584fd0b7e38a19dc154d37062ed2a7f2bf`
- **Commit no (kısa):** `f5fb145`
- **Tarih:** 2026-02-17 14:43:56 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 58. `a3b8688` — Leaderboard: sadece kârda botlar; Bulunamadı mesajı. Admin: sarı çerçeve, tab sarı+kayma, koyu tema, hover glow

- **Commit no (tam):** `a3b868868291d76a521b8408903f58783a408b05`
- **Commit no (kısa):** `a3b8688`
- **Tarih:** 2026-02-17 14:41:19 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 59. `9153e39` — Admin: tab slider indicator + içerik kayma animasyonu

- **Commit no (tam):** `9153e39dc693d32aa68b9dac00485036282fb2de`
- **Commit no (kısa):** `9153e39`
- **Tarih:** 2026-02-17 14:36:41 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - .admin-tabs-list içinde .tab-indicator; animasyonla seçili tab altına kayar
  - - initAdminTabsSlider(), positionIndicatorToButton(), resize’da yeniden konum
  - - switchTab: __adminTabAnimating guard, indicator kaydırma, animateAdminTabContentTransition
  - - İçerik: yön bilgili slide (enterX/exitX 22px), 220ms cubic-bezier
  - - .tab-btn.active: arka plan transparent, indicator görünsün; metin accent-bright
  - - admin-tab-panel + data-tab-panel; showAdminPanel/hideAdminPanel, runLoadForTab animasyon sonunda

---

### 60. `cd4e83d` — Copy Trading + Global Leaderboard; admin hesap kartları stil

- **Commit no (tam):** `cd4e83d70bd7c2c5285375383765b3cb071e7e23`
- **Commit no (kısa):** `cd4e83d`
- **Tarih:** 2026-02-17 14:31:31 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Leaderboard: bot_public_metrics tablosu, /api/leaderboard/structures/{id}/top ve /global/top
  - - copytrading_sanitize + leaderboard_service, 60s refresh loop (DB/PnlService, Binance yok)
  - - Create Bot modal: Copy Trading butonu + Top 5 drawer, Bu parametreleri uygula
  - - Anasayfa: Global En İyi Bot bölümü
  - - Admin: hesap kartları koyu arka plan, belirgin çerçeve, okunaklı metin
  - - Spec güncellendi

---

### 61. `4598ac0` — Spot modal: hemen açılma + yüzde flicker düzeltmesi; ilk giriş popup sırası + mobil X

- **Commit no (tam):** `4598ac0e8700d45c89848d3c4b6d0672778a04c4`
- **Commit no (kısa):** `4598ac0`
- **Tarih:** 2026-02-17 14:22:00 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Modal: ensureFeeRates beklenmeden modal hemen açılıyor; fee sonra güncelleniyor
  - - bnTradePriceChange: tek kaynak (ticker_24h), handleSpotEngineData/updateModalPriceChange yazmıyor
  - - İlk giriş: admin first_login popup önce, kapatılınca API key modalı
  - - firstLoginModal ve admin popup mobilde X ile kapatılabiliyor

---

### 62. `c170a91` — binance_spot: _binance_ip_ban global kaldırıldı – mutable state ile 'used prior to global declaration' hatası giderildi

- **Commit no (tam):** `c170a913c348fcc74c111cd4668a737f2f5233da`
- **Commit no (kısa):** `c170a91`
- **Tarih:** 2026-02-13 18:53:26 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>

---

### 63. `7a0817a` — Wallet: bot/emir kilitli strip+tablo; Trade favori: sembol/fiyat tam görünsün

- **Commit no (tam):** `7a0817a480f9cfcf3c7fc1ac0e62546ee78e38d6`
- **Commit no (kısa):** `7a0817a`
- **Tarih:** 2026-02-13 18:50:01 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>
- **Detay:**
  - - home: wallet refresh tam cüzdan dönsün (locked_usd, bot_locked_usd); cache cüzdan bot_locked ile zenginleştirilsin
  - - Trade sekmesi favori coinler: 2 satır layout, sembol ve fiyat kesilmeden tam okunur
  - - spec: wallet sözleşmesi (strip/tablo) güncellendi

---

### 64. `0698e05` — Dashboard, bot panel, popup, perf: İşlem geçmişi görünürlük, fiyat blink, live K/Z, popup etiket, SLOW_REQUEST optimizasyonu

- **Commit no (tam):** `0698e05da4402ef236c369d726a06e0308313ee0`
- **Commit no (kısa):** `0698e05`
- **Tarih:** 2026-02-13 18:35:46 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>
- **Detay:**
  - - Anasayfa İşlem Geçmişi: panel CSS/JS/HTML ile her zaman görünür (FİYAT sütunu, canlı bakiye)
  - - Varlıklar tablosu fiyat hücreleri: triggerValueBlink (blink-positive/blink-negative) eklendi
  - - Bot sayfası: /live endpoint daily_pnl_usd, daily_pnl_pct, initial_capital; applyLive ile Günlük/Toplam K/Z canlı güncelleme
  - - Mevcut Botlar: mobil kartta FİYAT = canlı sembol fiyatı; spec güncellendi
  - - Popup başlık: 'Başarı / Duyuru' -> 'Duyuru' (admin.html, dashboard.js)
  - - GET /api/finance/trades: type_filter=all için 90 gün varsayılan, 5000 fill cap (SLOW_REQUEST 30s+ önleme)
  - - TRADE_TRAILING_MASTER_SPEC.md: finance/trades, live endpoint, İşlem Geçmişi paneli notları

---

### 65. `e210bf5` — Dashboard & API: perf, UX, işlem geçmişi, yenilemede sekme koruma

- **Commit no (tam):** `e210bf55fddd31593482567ba7e66995d202a63e`
- **Commit no (kısa):** `e210bf5`
- **Tarih:** 2026-02-13 18:12:42 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>
- **Detay:**
  - - SLOW_REQUEST: finance/trades DB pagination (type_filter=buysell), dashboard summary 20s cache, trades_normalized index
  - - Günlük cüzdan değişimi: AssetSnapshot gün başı referansı (doğru günlük PnL)
  - - İşlem geçmişi: mobilde görünür, varsayılan Günlük+Alım/Satım, sayfa açılışta yükle; platform TradeTrailing/Binance; miktar/fiyat formatı
  - - Yenilemede aynı sekme: tab URL'de, savedTab düzeltmesi, mobil sekme eşlemesi
  - - KPI sembol/fiyat okunaklılık (CSS)
  - - İşlem geçmişi Yenile butonu kaldırıldı
  - - Spec: daily_wallet_pnl, cache/index sabitleri güncellendi

---

### 66. `64fb33e` — ui: dashboard trade view + wallet refresh + bot detail back link

- **Commit no (tam):** `64fb33e2c39f83d5a256ba2f8c8ae5d117d2b6e9`
- **Commit no (kısa):** `64fb33e`
- **Tarih:** 2026-02-13 17:51:33 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>
- **Detay:**
  - - Dashboard Mevcut Botlar: PORTFÖY→FİYAT, price cell = symbol live price; balance = bot balance
  - - Anasayfa: immediate wallet refresh on tab switch + 15s periodic refresh (LTC/cüzdan anında yansısın)
  - - Dashboard: restore tab from ?tab= URL; back from bot detail goes to Botlar tab
  - - Bot detail: engineLogPanel desktop only (hidden on mobile); backLink href includes &tab=bots
  - - Trade view (mobileTradeView): symbol as SOL/USDT, price/percent formatting, layout for mobile + desktop

---

### 67. `c1012b3` — fix: bot running but no real Binance trades — run_id, reconcile NOT_FOUND, verify-before-repair

- **Commit no (tam):** `c1012b3aa5f672522cbeaae5bef27959460c3d26`
- **Commit no (kısa):** `c1012b3`
- **Tarih:** 2026-02-13 17:32:23 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>
- **Detay:**
  - - BOT_RUN_ID: set run_id=cmd{command_id} on START; intent_id and client_order_id include run_id to avoid restart collision
  - - Binance reconcile: 200+code!=0 (-2013) => NOT_FOUND; valid order response check (orderId, status, symbol, clientOrderId)
  - - Verify-before-repair: only mark FILLED when GET myTrades confirms orderId; else proceed to place
  - - Forensic logs: RECONCILE_QUERY/RESPONSE_BODY/DECISION, EXEC_ORDER_ATTEMPT (run_id, coid), BINANCE_PLACE_ORDER, INITIAL_ALLOC_VERIFY
  - - BinanceSignedError for 200+error body; get_my_trades_for_order in adapter; Ledger.record_trade + ORDER_FILLED repaired on repair
  - - Tests: test_binance_reconcile.py, intent_id/coid run_id tests; script: scripts/binance_verify_order.py
  - - TRADE_TRAILING_MASTER_SPEC: run_id in S8, intent formula, Reconcile NOT_FOUND vs FOUND section

---

### 68. `3dfdd54` — feat: BOT_TICK_SUMMARY + BOT_TEŞHIS_DUMP on loop start; favori coin layout fix

- **Commit no (tam):** `3dfdd54af012f6a307a49f7adc7827508ae9cbf0`
- **Commit no (kısa):** `3dfdd54`
- **Tarih:** 2026-02-13 17:13:24 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>
- **Detay:**
  - - orchestrator: BOT_TICK_SUMMARY after strategy.tick (actions, next_wake, initial_allocation_done, quote/base, price)
  - - state_store: get_events_diagnostic_summary(); orchestrator logs BOT_TEŞHIS_DUMP + BOT_TEŞHIS_EVENT on loop start (last 80 events, by_type, skip_reasons)
  - - forensic doc: §3.1 order submit diagnostic, auto teşhis from logs
  - - dashboard.css: favori coinler grid 3-col, min-width symbol/price so coin name and prices visible

---

### 69. `7f879df` — fix: live/paper audit logs, Bot Performansı %, Favori Coinler, İşlem Geçmişi paneli, manager favicon/alerts

- **Commit no (tam):** `7f879dfc37576d1ae4159c6de5fb860eb418fe20`
- **Commit no (kısa):** `7f879df`
- **Tarih:** 2026-02-13 17:02:24 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.20>
- **Detay:**
  - - BOT_MODE_CHECK, EXEC_ORDER_ATTEMPT, BINANCE_PLACE_ORDER audit logs; paper_mode from DB only; live no-keys -> paused_error
  - - Bot Performansı panel: PnL yüzde bölümü her zaman (—% veya +X.XX%)
  - - Favori Coinler: mobil grid/layout restore (d2719ec style)
  - - İşlem Geçmişi: Anasayfa’da her zaman görünsün; Binance sekmesinde loadTransactionHistory tetikle
  - - Manager: /favicon.ico 204; alerts/ack id yoksa 200; server restart key strip

---

### 70. `218a086` — fix: avoid logout on 401 UNAUTHORIZED (missing_token); only SESSION_NOT_FOUND triggers session invalid; auth missing_token log at DEBUG

- **Commit no (tam):** `218a086567612b18e4922e0023239edaf94a05ef`
- **Commit no (kısa):** `218a086`
- **Tarih:** 2026-02-13 05:26:06 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 71. `ca855ba` — fix: force mainnet for non-test accounts; log BOT_ACCOUNT_CTX (paper_mode, testnet) at tick start

- **Commit no (tam):** `ca855bad7e878c1cf5aeadc84c900dcdeb7a195d`
- **Commit no (kısa):** `ca855ba`
- **Tarih:** 2026-02-13 05:21:10 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 72. `1cdf887` — fix: sync virtual_wallet from state when initial_allocation_done so balance not overwritten; repair log

- **Commit no (tam):** `1cdf88769e41e01ad7f84a5e4619008c32bcc921`
- **Commit no (kısa):** `1cdf887`
- **Tarih:** 2026-02-13 05:15:44 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - orchestrator: when state has initial_allocation_done and non-zero balances, sync virtual_wallet from state before get_virtual_wallet so next tick does not overwrite state with stale (0, 2800)
  - - execution: log initial_allocation_done=True and balances on repair for debugging

---

### 73. `113c237` — fix: real account never runs in paper mode (paper only when test user and no API keys)

- **Commit no (tam):** `113c2373b6d8370a4bf6f772555f9b0345cd64bd`
- **Commit no (kısa):** `113c237`
- **Tarih:** 2026-02-13 05:09:44 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - bot_run: paper_mode = test_user and is_test_account_username and not keys
  - - orchestrator: paper_mode = test_user and is_test_account_username and not has_keys
  - - Gerçek hesapta (API anahtarı varsa) asla paper modda bot çalışmaz

---

### 74. `d40a24e` — fix: repair set initial_allocation_done to stop repeat repair; data_hub get_all_prices snapshot

- **Commit no (tam):** `d40a24e4d340d13052e48bc8fb37c1616b5c204d`
- **Commit no (kısa):** `d40a24e`
- **Tarih:** 2026-02-13 05:02:10 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - execution: after repair apply_fill set initial_allocation_done=True and reference_price so next tick stops re-running repair and re-applying same fill (fixes negative quote / wrong UI state)
  - - data_hub: iterate list(prices.items()) in get_all_prices to avoid dictionary changed size during iteration when cache updated concurrently

---

### 75. `edb7864` — fix: initial allocation repair use intent client_order_id; dashboard bot performance range flicker

- **Commit no (tam):** `edb7864c3c9351e51bceb789bede2c6293a5d46d`
- **Commit no (kısa):** `edb7864`
- **Tarih:** 2026-02-13 04:56:18 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - execution: repair block uses intent_row.client_order_id for get_order_by_client_order_id (was fresh build with timestamp, so Binance order not found)
  - - dashboard.js: preserve last non-empty date range in bot performance panel when API returns empty range to prevent flicker

---

### 76. `7891d83` — feat: pre-fill bot create form with last used params (localStorage)

- **Commit no (tam):** `7891d83ac730c58cbd33e7b26d91138b2cf70e4f`
- **Commit no (kısa):** `7891d83`
- **Tarih:** 2026-02-13 04:47:38 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 77. `84ec6d2` — fix: initial allocation 1s retry; v5 use strategy next_wake; remove Performans raporu block; spec

- **Commit no (tam):** `84ec6d2ec1eeaf08f758e4c701f47907bc8fe6c8`
- **Commit no (kısa):** `84ec6d2`
- **Tarih:** 2026-02-13 04:43:53 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 78. `af57288` — fix: restore Favori Coinler layout to previous working state (inline list style, simpler mobile CSS)

- **Commit no (tam):** `af572881da05fa75f9161792e8c2fd05a8716e62`
- **Commit no (kısa):** `af57288`
- **Tarih:** 2026-02-13 04:39:55 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 79. `c6a7d68` — fix: bot detail live price + initial allocation state UX

- **Commit no (tam):** `c6a7d68e70ed155b213c8bc87289675d1d62adf5`
- **Commit no (kısa):** `c6a7d68`
- **Tarih:** 2026-02-13 04:34:27 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Backend: live snapshot last_price fallback to data_hub when price_hub empty
  - - Bot detail: strip price poll (1.5s) from /api/spot/price for #botPriceEl
  - - Bot detail: show 'İlk alım bekleniyor' when running with 0 base and quote > 0

---

### 80. `d2741b4` — fix: bots_delete skip convert on worker-only error, proceed with delete

- **Commit no (tam):** `d2741b4f1fabb737aae2321cb3a46fe788283665`
- **Commit no (kısa):** `d2741b4`
- **Tarih:** 2026-02-13 04:25:30 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 81. `1b0bb33` — fix: remove redundant local import of update_intent_filled to fix UnboundLocalError

- **Commit no (tam):** `1b0bb33c5bfd44727593384c7d352d5a286bbc51`
- **Commit no (kısa):** `1b0bb33`
- **Tarih:** 2026-02-13 04:22:57 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 82. `e3bb759` — fix: chart page mobile – flex layout, 44px touch targets, no horizontal overflow

- **Commit no (tam):** `e3bb7597fd5eae287e2b3ffbc2c3c62e1a1a5352`
- **Commit no (kısa):** `e3bb759`
- **Tarih:** 2026-02-13 04:17:14 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 83. `3b6989a` — fix: Bot Create modal mobile – viewport lock, body-only scroll, form spacing

- **Commit no (tam):** `3b6989a14b3d88d99522246f618e8375e1dc3ddf`
- **Commit no (kısa):** `3b6989a`
- **Tarih:** 2026-02-13 04:15:56 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 84. `d2719ec` — perf & UI: finance/trades 365d cap; snapshot 5s; bot perf flicker fix; tx history order grouping + Binance platform + layout; mobile trade favs & Bot Create modal

- **Commit no (tam):** `d2719ec785a22e6adcf9cec169e297a6b4dde1c3`
- **Commit no (kısa):** `d2719ec`
- **Tarih:** 2026-02-13 04:13:17 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 85. `6c5dd19` — fix: spot order HTTPException re-raise (no 500); mobile trade fav layout 30/50px from logo

- **Commit no (tam):** `6c5dd198b5cd2827bcb5343df325f1b78afe49fe`
- **Commit no (kısa):** `6c5dd19`
- **Tarih:** 2026-02-13 04:02:47 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 86. `2bfb377` — Trade favorileri: sembol logonun yanında, fiyat 30 boşluk, yüzde 50 boşluk hizalama

- **Commit no (tam):** `2bfb377eeb529314feee3c100412013a9cd36d15`
- **Commit no (kısa):** `2bfb377`
- **Tarih:** 2026-02-13 03:55:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 87. `7dc4458` — fix: Bot Performansı PnL flicker – sadece değer değişince DOM güncelle

- **Commit no (tam):** `7dc44585795b23bb685daff771e7f54b0cb8e140`
- **Commit no (kısa):** `7dc4458`
- **Tarih:** 2026-02-13 03:50:04 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 88. `e8cb0a2` — Dashboard: Trade favorileri mobil sığdırma, sembol/logo hizalama, 30 boşluk spacer

- **Commit no (tam):** `e8cb0a2753a70025fbc6581ec5f240e00e71517d`
- **Commit no (kısa):** `e8cb0a2`
- **Tarih:** 2026-02-13 03:19:25 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 89. `cf33970` — fix: bootstrap 404, mobile wallet, spot order from web, ticker desktop-only

- **Commit no (tam):** `cf339701bfccbd146494a0036d4dbc8b8060a40e`
- **Commit no (kısa):** `cf33970`
- **Tarih:** 2026-02-12 22:25:40 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - API: GET /api/dashboard/bootstrap in routes.py (delegate + fallback) so no 404
  - - Spot: allow_web=True for user-initiated spot orders from UI (place_spot_order)
  - - Mobile: syncBootWalletToAssetsState, usdt_value->total_usd for bootstrap wallet, setMobileTab(home) sync
  - - Ticker: 1024px breakpoint (JS+CSS), desktop only
  - - Add docs, scripts, tests, observability stubs, routes/home

---

### 90. `29335ec` — fix(mobile): wallet data on mobile — sync bootstrap wallet from dashboardStore to assetsState

- **Commit no (tam):** `29335ec6e84d64a4c30d15056a2d832028bcacfd`
- **Commit no (kısa):** `29335ec`
- **Tarih:** 2026-02-12 22:13:24 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - appBoot runs before dashboard.js so bootstrap wallet was never applied to assetsState on first paint
  - - Add syncBootWalletToAssetsState() in dashboard.js: reads store, applies to assetsState, triggers render
  - - Call sync from appBoot after bootstrap response so wallet shows when dashboard.js already loaded
  - - Call sync once when dashboard.js loads so wallet shows when bootstrap completed earlier (e.g. slow mobile)

---

### 91. `fd2b91d` — fix(mobile): hide top ticker strip; ensure Binance data loads on mobile

- **Commit no (tam):** `fd2b91defb15608bdc7caaea4b81c99aeb797a57`
- **Commit no (kısa):** `fd2b91d`
- **Tarih:** 2026-02-12 22:03:47 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - dashboard.css: hide #topTicker / .top-ticker on max-width 768px (no height, no visibility)
  - - dashboard.js: run Binance tab init (varliklar, orders, polling) when isMobileView() so strip/panel/orders get data
  - - setMobileTab('home'): call BinanceAssetsPanel.render + renderVarliklarList on switch so UI updates

---

### 92. `eee7bea` — fix: snapshot cache-only wallet + dashboard bootstrap + mobile ticker hide

- **Commit no (tam):** `eee7bea518240463ced9e681b1265dd27a339d48`
- **Commit no (kısa):** `eee7bea`
- **Tarih:** 2026-02-12 21:56:02 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Snapshot: wallet from DB/cache only, no live Binance (removes [snapshot] wallet timeout)
  - - POST /api/home/wallet/refresh: 6s timeout, wallet_refresh_attempt/success logs
  - - GET /api/dashboard/bootstrap: fast cache-only prices/kpis/wallet_cached/wallet_status
  - - appBoot.js + dashboardStore.js: single boot path for desktop + mobile, no tab gating
  - - apiClient: 401 on dashboard shows banner + Giriş (no immediate redirect), Accept/X-Requested-With
  - - dashboard: getSnapshotFields always includes wallet; no fetch fallback (apiClient only)
  - - Mobile: hide top currency ticker strip (max-width 768px)
  - - Spec: snapshot wallet cache-only, log examples updated

---

### 93. `51ba364` — mobile: root fix - tabs + prices visible

- **Commit no (tam):** `51ba3640cd678d714dc897b08e85b4574c72d0ea`
- **Commit no (kısa):** `51ba364`
- **Tarih:** 2026-02-12 21:26:52 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Move mobileBottomNav outside dashboardMainContainer (body child)
  - - Add MOBIL KÖK FIX CSS block: #mobileBottomNav display flex, dm-tabs hidden
  - - Remove ticker display:none on mobile (ticker.css) - show prices
  - - ticker.js: retry start() if hasToken false (800ms delay)
  - - Inline script: mobile-tab-home + KPI strip on load when mobile

---

### 94. `e11dfec` — fix: SyntaxError in api_debug_wallet_diag snapshot_asset_count

- **Commit no (tam):** `e11dfecad6b3b6b1dde354cc81c71320353ff1c1`
- **Commit no (kısa):** `e11dfec`
- **Tarih:** 2026-02-12 21:16:59 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 95. `6ef26df` — wallet: CURSOR TASK - normalizeAndApplyWallet, debug overlay, trace logs, diag endpoint

- **Commit no (tam):** `6ef26df2ac7164c7924587eac4a385bba58f9cc2`
- **Commit no (kısa):** `6ef26df`
- **Tarih:** 2026-02-12 21:08:39 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Frontend: coerceNumber, __walletEvents, normalizeAndApplyWallet reducer
  - - Frontend: ?debug_wallet=1 overlay, __ACTIVE_ACCOUNT_ID
  - - Frontend: homeFlash 3-retry fallback, document.hidden removed, ACCOUNT_ID_MISMATCH
  - - Frontend: renderHome wallet_cached -> normalizeAndApplyWallet (usdt_value map)
  - - Backend: log_wallet_trace in home/fast, wallet/refresh, binance/wallet, snapshot
  - - Backend: GET /api/debug/wallet/diag (keys, snapshot, cache, live fetch)
  - - docs/binanceverirapor.md: CURSOR TASK updates applied

---

### 96. `e6f75cc` — fix: Wallet loading / cüzdan hiç gelmiyor — 5 patch uygulandı

- **Commit no (tam):** `e6f75cc91c2d630b8e7ebe20dd9cc08da738527b`
- **Commit no (kısa):** `e6f75cc`
- **Tarih:** 2026-02-12 20:44:53 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - applySnapshotToUI: wallet _error → status=error; UI banner Yenile/Ayarlara git
  - - homeFlash: 3 denemelik retry (600ms, 1500ms, 4000ms)
  - - /api/binance/wallet: require_auth + require_account_access
  - - /api/home/wallet/status: keys_configured, last_snapshot_at eklendi
  - - CLOCK_DRIFT: Binance -1021 algılama; Windows w32tm uyarısı
  - - Mobil alt çubuk kaldırıldı; appbar çıkış butonu sadece solda
  - - docs/binanceverirapor.md eklendi
  - - TRADE_TRAILING_MASTER_SPEC.md güncellendi

---

### 97. `43b775a` — fix: dashboard flicker, wallet loading, appbar mobile, manager Windows Server

- **Commit no (tam):** `43b775a04900cf8172d26f977d24f5ff0eff3605`
- **Commit no (kısa):** `43b775a`
- **Tarih:** 2026-02-12 20:13:15 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - homeFlash: wallet fallback when wallet_cached null (pollWallet)
  - - dashboard: snapshot fetch with wallet when idle 2 cycles on Binance tab
  - - renderHome: skip empty price updates (prevent flicker)
  - - dashboard: mobile appbar - logout button in left, hide center
  - - manager: MANAGER_ALLOW_REMOTE for Windows Server remote access
  - - manager: Windows disk_usage(C:) fix, 403 error feedback in UI

---

### 98. `cb7fdc9` — fix: Flash Home fallback + mobile Trade favori/arama

- **Commit no (tam):** `cb7fdc90c6bdfd4e30c91b854840e4e5e090d904`
- **Commit no (kısa):** `cb7fdc9`
- **Tarih:** 2026-02-12 19:52:01 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - main: try app.api.routes.home then subroutes.home for /api/home/fast so server works when subroutes missing
  - - mobile Trade: load favorites from API when opening tab (if accountId); use coinListSearchAllSymbols for search dropdown with price+% preview; refresh mobile favorites list when toggling star in modal

---

### 99. `1b22c82` — fix(ui): preserve last good spot balance in Flash Home walletCachedToAssetsState

- **Commit no (tam):** `1b22c82cdc2d430edae8e0c1b1229c98a7765589`
- **Commit no (kısa):** `1b22c82`
- **Tarih:** 2026-02-12 19:42:26 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 100. `caab28d` — fix: Binance wallet flash to 0 + mobile appbar center width

- **Commit no (tam):** `caab28d8ed914dce11086f5f7017025b26c7da78`
- **Commit no (kısa):** `caab28d`
- **Tarih:** 2026-02-12 19:37:28 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Snapshot: on wallet error use last-known total_usd from cache (120s) so UI does not flash to 0
  - - Frontend: keep last good spot on wallet error/stale; show 'Güncel değil' when stale
  - - Mobile appbar: center block width fit-content so logout button does not stretch

---

### 101. `3976ba6` — fix(ui): mobile dashboard appbar single-row layout and alignment

- **Commit no (tam):** `3976ba6ade8b77866ae53d64c0baa82b8c360948`
- **Commit no (kısa):** `3976ba6`
- **Tarih:** 2026-02-12 19:24:56 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 102. `51c93ef` — Binance: 429 reduce myTrades to 40 symbols + delay + cooldown 10min; 401/timeout: 8s timeout, timestamp fallback, wallet_error in snapshot

- **Commit no (tam):** `51c93ef25921bb78950840bf04b0a60c0d8011aa`
- **Commit no (kısa):** `51c93ef`
- **Tarih:** 2026-02-12 19:15:28 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 103. `048c42f` — start.bat: checkout stop.bat before pull to avoid merge abort; note for file-in-use error

- **Commit no (tam):** `048c42fe8ba503f732d4b86970b025974c0fb76b`
- **Commit no (kısa):** `048c42f`
- **Tarih:** 2026-02-12 19:03:37 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 104. `3718194` — Manager: global actions include HTML, restart(html), loading state and feedback for all buttons; stop.bat and DEPLOY notes

- **Commit no (tam):** `3718194b7de37467741dc9dd913de51b1fc8ff79`
- **Commit no (kısa):** `3718194`
- **Tarih:** 2026-02-12 19:01:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 105. `08d71d1` — Add app.services.dashboard_snapshot to repo; 503 on snapshot when module missing

- **Commit no (tam):** `08d71d17d1840247c6c5fb437d09955b3b31c0c9`
- **Commit no (kısa):** `08d71d1`
- **Tarih:** 2026-02-12 18:56:57 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 106. `25fa288` — fix(stop.bat): port-based kill first, locale-safe netstat, run-as-admin hint

- **Commit no (tam):** `25fa288a7ada2d1b4b3be32f7215d63d8bbdbb49`
- **Commit no (kısa):** `25fa288`
- **Tarih:** 2026-02-12 18:46:56 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 107. `01a9542` — docs: add app.api.utils to ModuleNotFoundError section in DEPLOY.md

- **Commit no (tam):** `01a95425a15e640cb0efe84fd5cb1f1247380525`
- **Commit no (kısa):** `01a9542`
- **Tarih:** 2026-02-12 18:42:30 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 108. `4de2f98` — Add app.api.utils (fields) for snapshot; defensive import in routes (fallback if module missing)

- **Commit no (tam):** `4de2f9889261ab987049b26d644e0aacd91a4095`
- **Commit no (kısa):** `4de2f98`
- **Tarih:** 2026-02-12 18:41:23 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 109. `00e4eab` — Server: middleware optional (app.middleware yoksa baslar), middleware repoya, worker DataHub warmup, deploy CRASH_LOOP notu

- **Commit no (tam):** `00e4eaba3922feae063e09159ab45cb0e8d76cf3`
- **Commit no (kısa):** `00e4eab`
- **Tarih:** 2026-02-12 18:37:26 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 110. `b65acc8` — deploy: ModuleNotFoundError (app.core / intent_ledger) icin git pull ve manuel kopya notu

- **Commit no (tam):** `b65acc8e798f50ddfda520695d956eb49db93172`
- **Commit no (kısa):** `b65acc8`
- **Tarih:** 2026-02-12 18:31:58 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 111. `766165d` — Add app.core module (auth.token_utils, config, constants, errors, security) for server - fix ModuleNotFoundError: app.core

- **Commit no (tam):** `766165dd7dfd275cfb13764fffc2081bc6c21f74`
- **Commit no (kısa):** `766165d`
- **Tarih:** 2026-02-12 18:30:42 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 112. `bc08bf0` — Windows: uvloop/httptools atlama (ModuleNotFoundError on server)

- **Commit no (tam):** `bc08bf0e8ec59cb527f1b64aef09216b8d1cf268`
- **Commit no (kısa):** `bc08bf0`
- **Tarih:** 2026-02-12 18:29:03 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 113. `354b34d` — Add missing botengine modules (intent_ledger, kill_switch, reconcile, scheduler, bot_run, errors, user_stream) for server deploy

- **Commit no (tam):** `354b34dac91f6081b719aefd33837c76984c52f3`
- **Commit no (kısa):** `354b34d`
- **Tarih:** 2026-02-12 18:28:46 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 114. `d7a979c` — UI: popup 405 fix, Görüntüleyen+UTC+3, auth log, appbar sticky, login telefon label/placeholder, dm-tabs sola

- **Commit no (tam):** `d7a979c6bf5baab8f27e63f8715fd12a009f48d8`
- **Commit no (kısa):** `d7a979c`
- **Tarih:** 2026-02-12 18:23:18 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 115. `0a724da` — UI: çıkış butonu ortala/KPI hiza, popup detay+okuyanlar, Ayarlar sekmesi sağa

- **Commit no (tam):** `0a724da04ab6654fd853347dee19497adf974946`
- **Commit no (kısa):** `0a724da`
- **Tarih:** 2026-02-12 18:06:56 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 116. `1bcc836` — fix(auth): do not logout on boot_id change; validate via whoami

- **Commit no (tam):** `1bcc83643b16fb571ae96c2f2e216f7cd041f8f4`
- **Commit no (kısa):** `1bcc836`
- **Tarih:** 2026-02-12 16:42:23 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 117. `5bda1f6` — fix: perf chart modal crosshair guard (pt + try/catch), cache bust v=2

- **Commit no (tam):** `5bda1f6f582bf2cf0a87ee15fc1bfaf3c865e9c1`
- **Commit no (kısa):** `5bda1f6`
- **Tarih:** 2026-02-11 20:32:34 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 118. `46e3874` — Login-forex paralel; rebalancing USDT satiri; finance trades 90s timeout + cache bust; perf_chart crosshair param guard

- **Commit no (tam):** `46e38746c6885dad647a9d39d4bc392be9889681`
- **Commit no (kısa):** `46e3874`
- **Tarih:** 2026-02-11 20:29:05 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 119. `af74323` — Login-forex: altin yedek Binance PAXGUSDT; Manager: web durumu port 8000 ile

- **Commit no (tam):** `af7432300473c57cbd0bbbbe1cdd70360515c815`
- **Commit no (kısa):** `af74323`
- **Tarih:** 2026-02-11 20:07:23 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 120. `248d1a2` — Login: döviz/altin backend /api/login-forex proxy (CORS cozumu)

- **Commit no (tam):** `248d1a2b2d2a2c5f5378ead9f73e5614e06da148`
- **Commit no (kısa):** `248d1a2`
- **Tarih:** 2026-02-11 20:03:15 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 121. `8686cb2` — 503 hata mesaji: backend detail.message goster (BINANCE_MASTER_KEY uyarisi)

- **Commit no (tam):** `8686cb211da13b9f80e66c51e06458e8e95ef2fc`
- **Commit no (kısa):** `8686cb2`
- **Tarih:** 2026-02-11 20:01:47 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 122. `41ff1ef` — Login: kripto fiyatlari backend /api/login-crypto uzerinden (CORS cozumu)

- **Commit no (tam):** `41ff1ef0c471d9dbdf607e39d3b747f7307e2ced`
- **Commit no (kısa):** `41ff1ef`
- **Tarih:** 2026-02-11 19:55:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 123. `5da991d` — Admin panel: giris yapan adminin kendi hesabi tile listesinde gosterilmesin

- **Commit no (tam):** `5da991d0072908bee48b82044256c1b8b5650b2d`
- **Commit no (kısa):** `5da991d`
- **Tarih:** 2026-02-11 19:51:55 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 124. `9b8ee7e` — Login: ilk admin sentinel bcrypt kaldirildi (Invalid salt hatasi duzeltildi)

- **Commit no (tam):** `9b8ee7e875584d39f3b744b9368902270d599b89`
- **Commit no (kısa):** `9b8ee7e`
- **Tarih:** 2026-02-11 19:48:16 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 125. `b83fce6` — İlk admin otomatik, varsayılan şifre kaldırıldı; ilk girişte yazılan şifre kalıcı. Kullanıcı yoksa 'Kullanıcı bulunamadı' mesajı.

- **Commit no (tam):** `b83fce6c9aff9006e575cf83cd95ca601de3d27c`
- **Commit no (kısa):** `b83fce6`
- **Tarih:** 2026-02-11 19:41:32 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 126. `7c6c910` — create_first_admin.py: ilk admin yoksa olusturur (Admin / Omeromer01.)

- **Commit no (tam):** `7c6c91044188d5b6857d19f63b640ac1f2ff8722`
- **Commit no (kısa):** `7c6c910`
- **Tarih:** 2026-02-11 19:34:43 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 127. `1c595b3` — Login 401: localhostta debug_hint (user_not_found / invalid_password) ve arayuzde gosterim

- **Commit no (tam):** `1c595b3ceb2386381afcbce04d16e3322247c8b6`
- **Commit no (kısa):** `1c595b3`
- **Tarih:** 2026-02-11 19:32:10 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 128. `58e28a4` — Giris: sifre dogrulama NFC + NFD + raw strip ile tam uyumluluk

- **Commit no (tam):** `58e28a4f3a416f8dde93ead1e312cf4620bb8ef1`
- **Commit no (kısa):** `58e28a4`
- **Tarih:** 2026-02-11 19:29:28 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 129. `40174e9` — Silinen dosyalar: SEO_MASTER_*, calistir.bat

- **Commit no (tam):** `40174e90ef6e3b637dfdc23104bc959085f66667`
- **Commit no (kısa):** `40174e9`
- **Tarih:** 2026-02-11 19:27:20 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 130. `15efe04` — Admin varsayilan sifre Omeromer01., giris sonrasi yeni sifre zorunlu

- **Commit no (tam):** `15efe0446e916040283decf36beeae3c13a9a74e`
- **Commit no (kısa):** `15efe04`
- **Tarih:** 2026-02-11 19:26:49 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 131. `6b9b6c3` — guncelle.bat mesaji; deploy_windows.sh Windows sunucu deploy

- **Commit no (tam):** `6b9b6c33b0dc7dacd666cc6af5b60c6fb43e2ec5`
- **Commit no (kısa):** `6b9b6c3`
- **Tarih:** 2026-02-11 19:23:48 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 132. `0b57ef0` — Admin sifresi giris yapmadan sifirlama: ADMIN_PASSWORD_RESET_SECRET ile endpoint

- **Commit no (tam):** `0b57ef0dc68ab023a450df8382bbf22367dffac4`
- **Commit no (kısa):** `0b57ef0`
- **Tarih:** 2026-02-11 19:23:23 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 133. `584f60e` — Admin: telefon ile sifre atama endpointi (yayinda giris icin sifre senkron)

- **Commit no (tam):** `584f60ec6724ad75394538956fd0484f4d8b0aed`
- **Commit no (kısa):** `584f60e`
- **Tarih:** 2026-02-11 19:21:49 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 134. `efc00af` — Giris: sifre NFC/NFD normalizasyonu - local ve yayinda ayni sifre kabulu, invalid password log

- **Commit no (tam):** `efc00afb248947b09f865ebbf06e7ed3f9b02c0a`
- **Commit no (kısa):** `efc00af`
- **Tarih:** 2026-02-11 19:17:59 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 135. `1b99ed6` — guncelle.bat: sunucuda start.bat eski kaldiginda once calistirilacak proje guncelleme scripti

- **Commit no (tam):** `1b99ed66d8b310edc2d51ed6fae108ed945b4353`
- **Commit no (kısa):** `1b99ed6`
- **Tarih:** 2026-02-11 18:50:56 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 136. `8bf6d31` — Giris: sifre dogrulama guclendirildi, trim ve hash str/bytes destegi

- **Commit no (tam):** `8bf6d317cebc2e307cd53386e88c8090d7fa5761`
- **Commit no (kısa):** `8bf6d31`
- **Tarih:** 2026-02-11 18:48:26 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 137. `b05f62e` — start.bat: batch echo duzeltmeleri, calistir kelimesi stir hatasini onlemek icin baslat ile degistirildi

- **Commit no (tam):** `b05f62e5e993ca2f0013b82f42b3b91cd0a9120a`
- **Commit no (kısa):** `b05f62e`
- **Tarih:** 2026-02-11 18:36:31 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 138. `25e105e` — start.bat: git pull ciktisi goster; Omeraltinhtml yoksa yonlendirme mesaji

- **Commit no (tam):** `25e105efa66f6f13c5f4c47ca7bdc25fbe235e76`
- **Commit no (kısa):** `25e105e`
- **Tarih:** 2026-02-11 18:30:04 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 139. `044e331` — start.bat: guncel commit goster; Omeraltinhtml klasorunu adinda omeraltin gecen her varyanttan bul

- **Commit no (tam):** `044e331a42dafd6723530b2322d1e5ac3d0d5877`
- **Commit no (kısa):** `044e331`
- **Tarih:** 2026-02-11 18:25:09 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 140. `be4f246` — start/restart.bat: her calistirmada git pull; Omeraltinhtml klasor adi kontrolu

- **Commit no (tam):** `be4f2468f2e8a3f29086ea8cadf3a268ed0a0897`
- **Commit no (kısa):** `be4f246`
- **Tarih:** 2026-02-11 18:14:39 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 141. `a388351` — Login: şifre butonu yayında tutarlı, login.css v=2 cache-bust

- **Commit no (tam):** `a3883517daada091e923b3744f8753f7b8de1378`
- **Commit no (kısa):** `a388351`
- **Tarih:** 2026-02-11 17:45:56 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 142. `455adb7` — Şifre göster/gizle butonu: göz ikonu ve düzenli stil

- **Commit no (tam):** `455adb7714150d063188fcffa6fe349993bf8ae6`
- **Commit no (kısa):** `455adb7`
- **Tarih:** 2026-02-11 17:08:18 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 143. `fecf44b` — deploy test

- **Commit no (tam):** `fecf44bbe07e21d49b9ca441486e1e3dcb26117b`
- **Commit no (kısa):** `fecf44b`
- **Tarih:** 2026-02-11 16:36:03 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 144. `e529605` — init: project source

- **Commit no (tam):** `e529605152ee34a53d22d8b180350f0533ec7223`
- **Commit no (kısa):** `e529605`
- **Tarih:** 2026-02-11 03:01:10 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 145. `fe8c9cf` — chore: prepare repo for deploy (ignore runtime/data)

- **Commit no (tam):** `fe8c9cf32fb8b28f387e3fdb47b7005e18a85edd`
- **Commit no (kısa):** `fe8c9cf`
- **Tarih:** 2026-02-11 02:58:40 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 146. `358d5f8` — init: first push

- **Commit no (tam):** `358d5f85fd8ae326ebb4e56a63283e29e3fb4e16`
- **Commit no (kısa):** `358d5f8`
- **Tarih:** 2026-02-11 02:54:38 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 147. `3e6fcbc` — chore: prepare project for git-based deploy (no logic changes)

- **Commit no (tam):** `3e6fcbc8463add3d38efe7ba9e709fb053fc2b47`
- **Commit no (kısa):** `3e6fcbc`
- **Tarih:** 2026-02-11 02:28:07 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 148. `78acfea` — TRDCA bakiye düzeltmesi, login mobil scroll, favori coinler daraltma

- **Commit no (tam):** `78acfea0d76643f5469f0b32cd1055d5af823d55`
- **Commit no (kısa):** `78acfea`
- **Tarih:** 2026-02-10 17:48:37 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>
- **Detay:**
  - - orchestrator: Gerçek hesapta initial_capital ile bakiye sınırlama
  - - trdca_pro: target_weights normalizasyonu, base varlık dağılımı düzeltmesi
  - - login.css: Mobil scroll, logo parlama animasyonu
  - - dashboard.css: Favori coinler mobilde daha dar/kompakt

---

### 149. `23d2d4e` — Kurulum: ilk calistirmada otomatik Kurulum.bat. start.bat: 8080/Omeraltinhtml terminal mesajlari. Kadran: tek renk koyu yesil + kucuk sik balik sirti efekti

- **Commit no (tam):** `23d2d4e322640862e9ad92cae86acc001136eac8`
- **Commit no (kısa):** `23d2d4e`
- **Tarih:** 2026-02-10 04:17:41 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 150. `2a2cc3e` — Login: sözleşme onayları, modal scroll, Geri/Okudum anladım. stop/start/restart.bat düzeltmeleri, deploy ve command klasörleri

- **Commit no (tam):** `2a2cc3ea4380f34c9252291407872092f164e1e8`
- **Commit no (kısa):** `2a2cc3e`
- **Tarih:** 2026-02-10 04:11:35 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 151. `c871840` — Admin: tema, mobil sekmeler, sunucu paneli, ticker gizleme, sekme hatırlama

- **Commit no (tam):** `c871840341b5a75df02080ffc74767a74e807d5d`
- **Commit no (kısa):** `c871840`
- **Tarih:** 2026-02-10 03:19:27 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>
- **Detay:**
  - - admin-login-theme.css: koyu tema, altın vurgu, ince çerçeve/boşluklar
  - - Mobil: sekmeler dropdown body portal, opak arka plan, tam genişlik
  - - Masaüstü: sayfa normal kayar, sekmeler kendi içinde kaymaz
  - - Sunucu sekmesi mobil: tek sütun yatay satır KPI, yana kayma yok, serverStartedAt gizli
  - - #topTicker admin sayfasında gizlendi
  - - Sekme seçimi sessionStorage ile yenilemede korunuyor

---

### 152. `c2b240e` — Login: çıkış uyarısı kutu içinde kısa, Güvenli çıkış yapıldı, mobil Sekmeler dropdown sayfa içinde

- **Commit no (tam):** `c2b240e7ab06fd81478b050717099f48109b7066`
- **Commit no (kısa):** `c2b240e`
- **Tarih:** 2026-02-10 02:53:05 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 153. `2618660` — Login: topbar bayrak sağda/buton boyu, kayan yıldız düz, mobil tab 50/50, modal sekmeler ortala

- **Commit no (tam):** `2618660dbf1d6eddac151590c021ea56b7aeb44d`
- **Commit no (kısa):** `2618660`
- **Tarih:** 2026-02-10 02:49:11 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 154. `e7b6395` — Login: saatler koyu Rolex yeşili ve zengin görünüm, nebula sağda sabit ve görünür

- **Commit no (tam):** `e7b6395079ef78d8dfc850bf3525c577ed4b1637`
- **Commit no (kısa):** `e7b6395`
- **Tarih:** 2026-02-10 02:29:10 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 155. `b1dc19c` — Admin panel mobil: sekme dropdown hesapların üstünde görünsün (z-index düzeltmesi)

- **Commit no (tam):** `b1dc19cf1b594c306adc66a9c5fed1af79f90b12`
- **Commit no (kısa):** `b1dc19c`
- **Tarih:** 2026-02-10 01:26:50 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 156. `86882a5` — feat: MULTI bot Sonlandır ve Sil - tüm coinleri quote'a çevir, modal metni güncelle

- **Commit no (tam):** `86882a58ab67880df1b39be03de79c3060083aed`
- **Commit no (kısa):** `86882a5`
- **Tarih:** 2026-02-06 15:45:09 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>
- **Detay:**
  - - API: MULTI botlarda convert_base_to_quote ile tüm coinler piyasa emri ile satılır
  - - UI: Sonlandır ve Sil modalı MULTI için coin listesi gösterir
  - - windows/ ve winfinal/ klasörleri kaldırıldı, docs/ taşındı

---

### 157. `e8ccbd7` — Start/stop sadece final1 kokunde: start.bat, stop.bat, restart.bat + .command; diger tum start/stop dosyalari kaldirildi

- **Commit no (tam):** `e8ccbd731d9bf615a36339527a75ff9fb96993e6`
- **Commit no (kısa):** `e8ccbd7`
- **Tarih:** 2026-02-06 04:08:21 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 158. `e823e3c` — Manager panel: özet flicker düzeltmesi, WS errors_ring/warns_ring birleştirme, Hata/Uyarı panel etiketleri, 401 throttle özet satırı

- **Commit no (tam):** `e823e3c7385d9adf6e279374e6a4e07a2821aa1c`
- **Commit no (kısa):** `e823e3c`
- **Tarih:** 2026-02-06 03:17:02 +0300
- **Yazar:** Ömer Altın <omeraltin@192.168.1.15>

---

### 159. `501052e` — Hata logları sıfırlama: backend clear endpoint + frontend entegrasyonu (yenileyince kalıcı temiz)

- **Commit no (tam):** `501052eaad101920bae0bcf5eed22beb3bbcf8af`
- **Commit no (kısa):** `501052e`
- **Tarih:** 2026-02-05 16:12:18 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 160. `2bebb02` — TRDCA Pro+ parametre ekranı, test hesabı iyileştirmeleri, hata logları ve UI düzeltmeleri

- **Commit no (tam):** `2bebb026ccdfe6a5e4dc5b2eec5b7ce3ab775042`
- **Commit no (kısa):** `2bebb02`
- **Tarih:** 2026-02-05 16:09:02 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - TRDCA: Quote/bakiye, rebalancing (coin sayısı + dağılım + önizleme), DCA parametreleri, performans varsayılanları
  - - TrdcaProConfig: bot_budget_usdt/initial_capital_usdt, to_dict güncellendi
  - - Test hesabı: audit events son 24 saat; error-logs 403 düzeltmesi (session account_id)
  - - TRDCA strateji: batch_id determinism, UNKNOWN legs timeout, pending_* clamp debug uyarısı
  - - Orchestrator/execution: gerçek order status, fill varsayımı yok
  - - Binance sekmesi: viewport'a sığma (tab + paneller)
  - - Hata logları: MULTI.png 404 önleme (coinLogo MULTI fallback), sıfırla butonları anında listeyi temizliyor
  - - JS: modalTitle/quotePct çakışmaları giderildi, openCreateBotModal atanıyor
  - - splash.html eklendi

---

### 161. `041c4ff` — Test hesabı (test_local): sadece localhost giriş, paper mod, 10.000 USDT sanal bakiye

- **Commit no (tam):** `041c4ff003be802d97862d4f88a8ba32ad0f5322`
- **Commit no (kısa):** `041c4ff`
- **Tarih:** 2026-02-05 15:09:22 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 162. `3d4e9ee` — TRDCA Pro+ strateji entegrasyonu: backend (strategy_tick, apply_fills, DCA/TRB), orchestrator snapshot, execution batch, UI parametre ve detay sayfası

- **Commit no (tam):** `3d4e9eeec99612dc9b4f7cd45e4880943e695324`
- **Commit no (kısa):** `3d4e9ee`
- **Tarih:** 2026-02-05 15:00:35 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 163. `2dff087` — Mobil uyumluluk, admin/error-logs API, Windows launcher ve genel güncellemeler

- **Commit no (tam):** `2dff0872d582f89d5a8962976f5e55ff97362015`
- **Commit no (kısa):** `2dff087`
- **Tarih:** 2026-02-04 01:07:44 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 164. `4f745c1` — Manager panel (7999): hız, restart, log ve overview iyileştirmeleri

- **Commit no (tam):** `4f745c1ab4928d4f289a1c513d1988553a446d08`
- **Commit no (kısa):** `4f745c1`
- **Tarih:** 2026-02-03 03:48:17 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Manager Start/Stop scriptleri (Manager Start.command/bat, Manager Stop)
  - - Light status (?light=1): log parse ve system_profiler yok, sayfa jet hızında
  - - Full status: 80 satır parse, skip_slow, cache 8s; handler exception yakalama
  - - ThreadingMixIn: tail status'ü beklemez; status cache 2s (light) / 8s (full)
  - - Restart sonrası tarayıcı açılsın (NO_OPEN_BROWSER kaldırıldı); poll 80x1.5s, fallback link
  - - Toplam istek: Web + Bot Engine dahil; overview kartlarda hata/uyarı kutuları
  - - Bot engine: gereksiz loglar DEBUG; active_bots .run/worker_active_bots; orchestrator/registry DEBUG
  - - docs/MANAGER_KAPANMA_ANALIZI.md güncellendi

---

### 165. `dcb5cd9` — logs: .meta yeşil metin, #panelAnasistem dış çerçeve cırtlak pembe

- **Commit no (tam):** `dcb5cd90aaa378812a1104047299825311f66586`
- **Commit no (kısa):** `dcb5cd9`
- **Tarih:** 2026-02-03 02:33:39 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 166. `184d766` — Rebalancing entegrasyonu, UI/API düzeltmeleri, Binance saat senkronu

- **Commit no (tam):** `184d766eef30f6d12d756e0487e8238a923e7f7e`
- **Commit no (kısa):** `184d766`
- **Tarih:** 2026-02-03 01:00:47 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Rebalancing: parametre sayfası stratejiye ve sisteme entegre (model, strateji, orchestrator, execution)
  - - Rebalancing: multi-asset sembol/yüzde/önizleme ghost placeholder, özet tablosu kaldırıldı
  - - Rebalancing: varsayılan coin/yüzde kaldırıldı, step 1, parametre ekranı yenilemede korunuyor
  - - Binance: -1021 için sunucu saati önbelleği, recvWindow 60s; finance_reports endTime sınırı
  - - DCA modal: pair strip sembol seçilene kadar gizli
  - - Server Start.bat -> ServerStart.bat

---

### 167. `0951fa5` — Log sunucusu düzeltmeleri: Python 3.9 uyumu (Optional[int]), Server Start'ta terminalde log, Yeniden Başlat sonrası poll+Sayfayı yenile, Anasistem sunucu istekleri

- **Commit no (tam):** `0951fa5b1074c36341955e53b059caea65abee8e`
- **Commit no (kısa):** `0951fa5`
- **Tarih:** 2026-02-02 22:26:31 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 168. `907e638` — Worker sekmesi Toplam istek canlı güncelleme: worker_main sayacı, local_logs fallback, manager okuma sırası

- **Commit no (tam):** `907e638adfb36455486cb7d6f3764a4ae2bed799`
- **Commit no (kısa):** `907e638`
- **Tarih:** 2026-02-02 22:10:31 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 169. `eb3c400` — Değişiklikler kaydedildi: Server Start, local_logs, orchestrator, worker_main, local_web_worker_helper, manager_backend, logs

- **Commit no (tam):** `eb3c40062c544968471980ebc1b9c17e7f0b84c6`
- **Commit no (kısa):** `eb3c400`
- **Tarih:** 2026-02-02 22:03:47 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 170. `8fe922a` — Log sınıflandırma düzeltmesi: INFO/WARNING yanlış hata sayılması engellendi

- **Commit no (tam):** `8fe922a8f5fe908fcb521b95495c9b65f8016a40`
- **Commit no (kısa):** `8fe922a`
- **Tarih:** 2026-02-02 21:00:18 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - ui/logs.html: HTTP hata regex'i ondalık sayıları (0.476, 104.85) eşleştirmiyor; INFO satırları artık line-info
  - - app/api/local_logs.py, scripts/manager_backend.py: Aynı regex ile existing_loop=37709508 gibi sayılardaki 508 hata sayılmıyor; WARNING satırları Son uyarılar listesine düşüyor
  - - Server Restart, start_all, observability/ram_probe, ram dokümanları ve diğer güncellemeler eklendi

---

### 171. `e9d5f2a` — Proje güncellemesi: Server Start/Stop, loglar sayfası (7999), web/worker ayrı yönetim, Sıfırla/401/renklendirme düzeltmeleri

- **Commit no (tam):** `e9d5f2a5e2f2053013fcee680745d627b2ba16af`
- **Commit no (kısa):** `e9d5f2a`
- **Tarih:** 2026-02-02 18:11:32 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 172. `fb7a619` — feat: günlük PnL bot silindiğinde sıfırlanmasın — account_daily_realized_pnl cache

- **Commit no (tam):** `fb7a61950d4bb55ce1fc8d29078a8c703b18eee0`
- **Commit no (kısa):** `fb7a619`
- **Tarih:** 2026-02-02 16:11:23 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - schema_guard: account_daily_realized_pnl tablosu
  - - PnlService: _daily_realized_for_bot_trades, get/add cache, daily_realized cache dahil
  - - delete_bot_fully: silmeden önce bugünkü realized PnL cache'e yazılıyor
  - - Worker/strategy split + start/stop scripts (önceki işler dahil)

---

### 173. `fe407f5` — Clean cycle boundaries + compounding + perf chart + SELL balance guard

- **Commit no (tam):** `fe407f5e2a74417d14b03e0543b1c2752de49e97`
- **Commit no (kısa):** `fe407f5`
- **Tarih:** 2026-02-02 15:56:57 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - pnl_mode default: cycle_only_fee_aware_v1 (models)
  - - Cycle end: cycle_type (LONG_SCALP/INVENTORY_REBALANCE), base_delta, close_reason/side, cycle_pnls schema, target_budgets at cycle end
  - - Order sizing: _buy_qty_for_grid / _sell_qty_for_grid cap by target_budgets when present
  - - API: cycle_type_last, cycle_base_delta_last, cycle_pnl_last_net, target_budgets
  - - Perf chart: seed_perf_chart_state_on_bot_start (backend); refreshFromServer on Start (no clearForBot); GET range 1m/5m
  - - SELL pre-check: Binance free_base before place_market_sell to avoid INSUFFICIENT_BALANCE (virtual vs real drift)
  - - cycle_ledger: get_cycle_type_and_base_delta(); tests + docs/sanity_check.md

---

### 174. `f17a949` — Cycle PnL fix (fee-aware), perf chart, XRAY doc

- **Commit no (tam):** `f17a94989ae6ba7e88c8129404dbdcb3bf414a85`
- **Commit no (kısa):** `f17a949`
- **Tarih:** 2026-02-02 15:19:28 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Cycle ledger: cycle-only PnL, breakeven/trigger (fee-aware), pnl_mode legacy|cycle_only_fee_aware_v1
  - - Config: buy_fee_rate, sell_fee_rate, min_net_profit_rate, pnl_mode; fill snapshot free_quote/locked_quote
  - - Profit-exit: trigger_price = breakeven * (1+min_net_profit); SELL only if price >= trigger
  - - API: cycle_pnl_last, cycle_id_last, pnl_calculation_mode, realized_pnl_total, fees_total
  - - Perf chart: modal legend dynamic, tooltip hide on mouseleave, time grids & hover fix
  - - Docs: PROJECT_BOTENGINE_XRAY.md, SANITY_CHECK_CYCLE_PNL.md, CHANGELOG
  - - Tests: test_cycle_ledger.py (unit tests for ledger PnL, breakeven, trigger)

---

### 175. `0d41fe9` — Grafik 1m/5m penceresi, canlı uç setData, tur/trades canlı güncelleme, işlem satırına gerçekleşme %, reference_price düzeltmesi

- **Commit no (tam):** `0d41fe9553c38d06f8f75d6c1e71425fb6c2f5ee`
- **Commit no (kısa):** `0d41fe9`
- **Tarih:** 2026-02-02 14:25:11 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - perf_chart_tv: 5m için 7 gün / 1m için 24 saat pencere; canlı uç update yerine setData (çizgi uzamaz); buildChartDataWithLive; reference_price ledger için reset öncesi alınıyor
  - - bot.html: Tur değişince trades panel yenileme (refreshTradesPanel), cycle-pnl-item sonuna gerçekleşme yüzdesi
  - - Trade: reference_price kolonu; Ledger.record_trade/get_trades_dict reference_price; execution ref_price_for_ledger ile kayıt
  - - schema_guard: trades.reference_price kolonu

---

### 176. `206a309` — Güvenlik: breach shutdown + hesap askıya alma uyarısı; grid tamamlanınca tepe/dip/gerçekleşme dondurma; fill fiyatı 4 ondalık; fill fiyatı state ile grid UI

- **Commit no (tam):** `206a309ac05aa0896cb8cc095294cc5ecf0b64b2`
- **Commit no (kısa):** `206a309`
- **Tarih:** 2026-02-02 06:34:36 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 177. `b5a5e57` — Grafik: sunucuda state, yeni tarayıcıda yükleme, sekme kapalıyken kayıt

- **Commit no (tam):** `b5a5e57f5e38ca69147eccc8fab73657d9b72617`
- **Commit no (kısa):** `b5a5e57`
- **Tarih:** 2026-02-02 05:28:18 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - schema_guard: bot_perf_chart_state tablosu
  - - bots_engine: GET/PUT/DELETE perf-chart-state, append_perf_chart_sample (running botlar için)
  - - main: periyodik grafik örneklemesi (60sn) tarayıcı kapalıyken de kayıt
  - - perf_chart_tv: sunucudan yükleme/birleştirme, visibilitychange ile merge, clearForBot accountId

---

### 178. `287db18` — UI: Genel buton/perfGenelValue, işlemler yenileme, filtre-tablo boşlukları

- **Commit no (tam):** `287db18b0da2f2746397a104ee3d35252193305d`
- **Commit no (kısa):** `287db18`
- **Tarih:** 2026-02-02 05:11:54 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - bot.html: Genel butonuna tıklanınca perfGenelValue API ile güncellenmesin (sadece showDetail/polling)
  - - dashboard.js: İşlemler listesi 15sn polling, arka planda Yükleniyor gösterme (isBackgroundRefresh)
  - - dashboard.html: İşlemler filtre butonları tabloya yakın (margin 0.2rem), istatistik kutusu alt boşluk 1rem

---

### 179. `037f675` — UI: grafik yüzdeleri, grid/kar panelleri, cycle report, header/state sırası, bot tipi başlık, refD hatası

- **Commit no (tam):** `037f675695bd760a89e75fe6e2173d0dd9682e9b`
- **Commit no (kısa):** `037f675`
- **Tarih:** 2026-02-02 04:59:55 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - perf_chart_tv: parseUsdOrNumber iyileştirme, yüzde yedek kaynağı (Bakiye/Parite Değişim span), parseTrailingPct
  - - bot.html: renderGridPointsPanel/renderProfitPointsPanel, polling'de anlık güncelleme
  - - cycleReport sadece biten turlarda gösteriliyor
  - - headerPanel ile statePanel yer değişti (state üstte)
  - - bot tipi üst başlık (Trailing DCA Bot), etiket kaldırıldı, ortalandı
  - - lastRefPriceForPerf için refD yerine refPrice (refD is not defined düzeltmesi)

---

### 180. `aa21968` — Sonlandır/sil: base→quote seçilince Binance market satış; grafik bot bazlı clearForBot + başlatınca sıfırla

- **Commit no (tam):** `aa21968fca3b934f8fb8f539fa099a88755b92bf`
- **Commit no (kısa):** `aa21968`
- **Tarih:** 2026-02-02 04:43:53 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 181. `6f13e74` — Paper→live zorunlu, initial allocation sıfırlama, ortalama maliyet execution_price, grafik bot bazlı, form varsayılanları

- **Commit no (tam):** `6f13e745e4acb9bc911e6720522cda3aaa6f6852`
- **Commit no (kısa):** `6f13e74`
- **Tarih:** 2026-02-02 04:36:33 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 182. `73e411b` — Performans grafiği (Lightweight Charts), bot başlangıç/duration, cycle raporu, PNL/kar satışı, hata log API, grafik Sıfırla kaldırıldı

- **Commit no (tam):** `73e411b3382753c1474a96b1bcbb92f23bd5dc94`
- **Commit no (kısa):** `73e411b`
- **Tarih:** 2026-02-02 03:56:06 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>

---

### 183. `ef44e08` — UI: cycle trades labels, symbol chart modal back fix, perf chart debug doc

- **Commit no (tam):** `ef44e08de03202368b99989f645e6beca64e36fa`
- **Commit no (kısa):** `ef44e08`
- **Tarih:** 2026-02-02 03:02:27 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - bot.html: cycle trades list shows 'Miktar X · Fiyat @ Y' format
  - - chart.html: embed mode back link fixed with early inline script so Geri/Kapat never navigates iframe to dashboard (prevents page-in-page)
  - - perf_chart_rebuild.js: span refs by ID per sample, init when spans missing
  - - docs/debug/perf_chart_cursor_dump.md: technical evidence for perf chart fix

---

### 184. `0e1e645` — Dashboard & bot: KPI bot bakiyesi, günlük PnL (tur kârı), işlemler sync, Toplam K/Z, performans grafiği

- **Commit no (tam):** `0e1e645b36cf52ed1cdc8be8f80f5569c6333654`
- **Commit no (kısa):** `0e1e645`
- **Tarih:** 2026-02-02 02:48:00 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - Dashboard: kpiBotBakiye tek kaynak (bots_balance_usd), finance/summary bots_balance_usd + current_usd
  - - Günlük PnL: sadece o gün tamamlanan turların kârı (PnlService.daily_realized_from_cycles_completed_today)
  - - İşlemler paneli: TradeSyncService hesap bot sembollerini myTrades sync'e ekledi
  - - Bot detay: Toplam K/Z current_usd + initialCapital ile gösterim (state sell/buy_history şartı kaldırıldı)
  - - performans grafiği: perf_chart_rebuild.js (Lightweight Charts)
  - - renderFinanceBots: finance-bot-balance sınıfı, loadFinanceSummary State merge

---

### 185. `6fa4eae` — Dashboard & bot: KPI günlük ref, işlemler TR saati, grid qty_pct, PNL kartı, blink, buton stilleri

- **Commit no (tam):** `6fa4eae60b7289d659309fec08a8cdb47367a8a9`
- **Commit no (kısa):** `6fa4eae`
- **Tarih:** 2026-02-02 01:59:03 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - routes: Günlük KPI referansı (cüzdan/botlar) Türkiye günü, daily_wallet/bot_pnl_pct
  - - finance_reports: /finance/trades zaman alanları UTC (Z), _utc_iso
  - - dashboard.js: İşlemler dönem Türkiye saati, formatTurkeyDateTime, sync=1 ilk yükleme
  - - dashboard.js: KPI günlük değişim backend pct kullanımı
  - - dashboard.js: kpiCuzdanLive 30sn sonra son güncelleme tarihi
  - - dashboard.js: Varlıklar change-pct tick ile güncelleme
  - - dashboard.js: İşlemler Yenile/Önceki/Sonraki küçültme, dönem/filtre butonları sabit boyut
  - - dashboard.js: Mevcut Botlar fiyat hücresi blink (mevcut-botlar-price-cell)
  - - dashboard.css: trades-nav-btns, finance/trades period/filter min-height
  - - bots_engine: PNL kartı her zaman tüm CYCLE_END toplamı, dönemden bağımsız
  - - dca_grid_trailing: SyntaxError düzeltmeleri (if parantez)
  - - grid_view: grid_points qty_pct (satış base %, alım quote %)
  - - bot.html: Grid seviye hücresine %40/%60 dağılım gösterimi

---

### 186. `397ead6` — Performans raporu canlı veri, grid referans düzeltmesi, Bot Logları, bileşik tur

- **Commit no (tam):** `397ead6b9c0dcd7db6eac32bdb113b13a4f617f0`
- **Commit no (kısa):** `397ead6`
- **Tarih:** 2026-02-02 01:35:18 +0300
- **Yazar:** Ömer Altın <omeraltin@Omer-MacBook-Air.local>
- **Detay:**
  - - perfReport: Güncel bakiye/Bakiye Değişimi/Parite/Gerçek performans state grid ve botPriceEl ile canlı güncelleniyor
  - - perfGenelValue = Bakiye % − Parite % (canlı); perf-genel-hint metni kaldırıldı
  - - engineLogPanel başlığı: Bot engine logları → Bot Logları
  - - Dönem butonları (Günlük/Haftalık/Aylık/Genel) sadece PNL/Tur/Komisyon kartları ve grafiği değiştiriyor
  - - Satış gridleri: grid_reference_base ile her grid tur başı base'in aynı yüzdesini satıyor (kalan değil)
  - - Alım gridleri: grid_reference_quote zaten vardı; bileşik tur cycle_reset_after_fill ile korunuyor
  - - .gitignore: .run/ eklendi

---


## Yenileme

Her commit sonrası `post-commit` hook otomatik çalışır.

Elle güncellemek için:

```bash
python3 scripts/devops/sync_git_log.py
make hooks   # hook kurulumu (ilk sefer)
```

