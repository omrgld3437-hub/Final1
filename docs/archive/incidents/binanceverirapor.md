# Binance Cüzdan Verisi Raporu — Anasayfa Cüzdan Verisi Gösterilmemesi

**Tarih:** 2026-02-12  
**Konu:** Anasayfada hiçbir cüzdan verisi görünmemesi  
**Kapsam:** Kod yapısı, mimari, veri akışı, kök neden analizi, tahminler ve öneriler

---

## 1. Özet ve Problem Tanımı

### 1.1 Problem
Anasayfada (dashboard, Binance sekmesi) cüzdan verileri hiç görünmemektedir:
- Kullanılabilir varlıklar "Yükleniyor…" durumunda kalıyor
- Toplam spot bakiyesi $0.00 veya eksik
- Cüzdan varlıkları listesi boş veya yüklenemiyor

### 1.2 Beklenen Davranış
- Kullanıcı giriş yaptıktan sonra Anasayfa yüklendiğinde cüzdan verisi (Kullanılabilir, Bot kilitli, Kilitli varlıklar) görünmeli
- Veri ya anında (cache’ten) ya da 3–10 saniye içinde gelmeli

### 1.3 Etkilenen UI Bileşenleri
- `#unifiedKpiStrip` — Toplam spot bakiyesi, günlük değişim
- `#binanceAvailableAssets` — Kullanılabilir varlıklar
- `#binanceBotLockedAssets` — Bot kilitli
- `#binanceLockedAssets` — Kilitli varlıklar
- `#bnAssetsBody` — Varlıklar tablosu
- `#bnTotalValue`, `#bnFreeValue`, `#bnLockedValue` — Cüzdan özeti

---

## 2. Mimari Genel Bakış

### 2.1 Veri Kaynakları Hiyerarşisi
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CÜZDAN VERİSİ KAYNAKLARI                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. AssetSnapshot (DB)     ← POST /api/home/wallet/refresh başarılı olduğunda │
│ 2. In-memory wallet       ← _in_memory_wallet[account_id] (home modülü)     │
│ 3. Binance API            ← GET /api/v3/account (gerçek zamanlı)            │
│ 4. localStorage           ← storageCache (tt_home_cache_v1:{accountId})     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 API Uç Noktaları ve Rolü
| Endpoint | Auth | Binance Çağrısı | Cüzdan Verisi Kaynağı |
|----------|------|-----------------|------------------------|
| GET /api/home/fast | require_auth | Hayır | AssetSnapshot (DB) |
| POST /api/home/wallet/refresh | require_auth | Evet | Binance → AssetSnapshot yazar |
| GET /api/dashboard/snapshot | require_auth | Evet (fields=wallet) | _fetch_wallet_uncached |
| GET /api/binance/wallet | require_auth + require_account_access | Evet | _fetch_wallet_uncached |
| GET /api/debug/wallet/diag | require_auth + require_account_access | Evet (3s timeout) | Teşhis: keys, snapshot, cache, live fetch |

### 2.3 Frontend State Modeli
```javascript
assetsState = {
  wallet: {
    status: 'idle' | 'loading' | 'ready' | 'error',
    ts: number,
    assets: Array<{asset, free, locked, total_usd, free_usd, locked_usd, ...}>,
    total_usd: number | null,
    free_usd: number | null,
    locked_usd: number | null,
    bot_locked_usd: number | null,
    available_usd: number | null,
    keys_configured: boolean,
    error: object | null,
    data_status: 'fresh' | 'cached' | 'stale'
  }
}
```

**Kritik:** `status === 'idle'` veya `'loading'` iken UI "Yükleniyor…" gösterir. Veri görünmesi için `status === 'ready'` gerekir.

---

## 3. Veri Akışı — Detaylı

### 3.1 İlk Yükleme Akışı (FLASH_HOME_ENABLED=true, varsayılan)
```
1. initDashboard(accountId)
   └─> window.__ACTIVE_ACCOUNT_ID = accountId
   └─> homeFlash.init()
       ├─> storageCache.load(accountId)  → cached
       ├─> cached.wallet_cached varsa → walletCachedToAssetsState() → normalizeAndApplyWallet → status='ready'
       ├─> cached.kpis varsa → updateKPIs()
       └─> loadFast(accountId)
           └─> GET /api/home/fast?account_id=X
               └─> data.wallet_cached varsa → walletCachedToAssetsState() → normalizeAndApplyWallet()
               └─> data.wallet_cached YOKSA → fallback: 3 deneme (600ms, 1500ms, 4000ms) BinanceAssetsPanel.refresh()
       └─> triggerRefresh(accountId)  [document.hidden kontrolü KALDIRILDI — arka planda da tetiklenir]
           └─> account_id != __ACTIVE_ACCOUNT_ID ise ACCOUNT_ID_MISMATCH → atlanır
           └─> POST /api/home/wallet/refresh
               └─> _do_wallet_refresh() → Binance API → AssetSnapshot yaz → wallet_live dön
```

### 3.2 Periyodik Yenileme (Her 3 saniye)
```
dashboardDataRefresh() [SNAPSHOT_POLL_MS=3000]
├─> Tab = binance/varliklar ve FLASH_HOME_ENABLED
│   ├─> walletIdle (status idle/loading) ?
│   │   ├─> _binanceWalletIdleCycles >= 2 → fetchSnapshot() [fields=prices,kpis,wallet]
│   │   └─> değilse → homeFlash.loadFast()
│   └─> homeFlash.loadFast() → GET /api/home/fast
└─> Tab = bots/finance/...
    └─> fetchSnapshot() [fields=getSnapshotFields()]
```

### 3.3 wallet_cached Nereden Gelir?
```
GET /api/home/fast
├─> _get_last_wallet_snapshot_with_new_session(account_id, max_assets)
│   └─> DB: SELECT * FROM asset_snapshots
│       WHERE account_id = X
│       ORDER BY timestamp DESC
│       LIMIT 1
│   └─> row yoksa → (None, None)  ← KRİTİK: Hiç snapshot yoksa wallet_cached=null
│   └─> row varsa → _minimal_wallet_from_breakdown() → minimal dict
└─> data["wallet_cached"] = wallet_cached  # null veya dict
```

### 3.4 AssetSnapshot Ne Zaman Yazılır?
**Tek yazma yolu:** `POST /api/home/wallet/refresh` → `_do_wallet_refresh()` başarılı olduğunda.

```python
# app/api/subroutes/home.py - _do_wallet_refresh()
wallet_raw = await _fetch_wallet_uncached(account_id, db)  # Binance API
# ...
snap = AssetSnapshot(
    account_id=account_id,
    timestamp=datetime.now(timezone.utc),
    total_usd_value=total_usd,
    breakdown_json=json.dumps(breakdown),
    source="binance",
)
db.add(snap)
db.commit()
```

**Önemli:** AssetSnapshot sadece `wallet/refresh` başarılı olursa yazılır. Binance API hata verirse (401, 429, timeout) snapshot yazılmaz.

---

## 4. Backend Bileşenleri — Detay

### 4.1 home/fast
- **Dosya:** `app/api/subroutes/home.py` (veya `app/api/routes/home.py`)
- **Önbellek:** `_fast_cache[account_id]` — TTL 2 sn (home_fast_cache_ttl_sec)
- **wallet_cached:** `_get_last_wallet_snapshot_with_new_session()` — her zaman DB’den okur
- **Binance:** Hiç çağrılmaz (Patch H — kritik yol Binance’sız)

### 4.2 wallet/refresh
- **Tetikleyici:** `homeFlash.triggerRefresh()` — init sonrası (document.hidden kontrolü kaldırıldı; arka planda da tetiklenir)
- **account_id tutarlılığı:** `account_id != window.__ACTIVE_ACCOUNT_ID` ise ACCOUNT_ID_MISMATCH loglanır ve atlanır
- **Kısıtlamalar:**
  - REFRESH_DEBOUNCE_MS = 30000 (30 sn)
  - REFRESH_LOCK_TTL_MS = 20000 (localStorage kilidi)
  - TTL 5 sn (wallet_live_ttl_sec)
  - Cooldown 30 sn (wallet_cooldown_sec) — 401/429 sonrası
  - Inflight dedup — aynı anda tek istek

### 4.3 _fetch_wallet_uncached
- **Dosya:** `app/api/routes.py`
- **Binance:** `get_wallet(keys)` → GET /api/v3/account
- **Hata durumları:**
  - ACCOUNT_KEYS_MISSING → API key/secret yok
  - 401 Unauthorized → Geçersiz key, IP kısıtlı, sunucu saati
  - 429 → Rate limit
  - Timeout 12 sn

### 4.4 get_account_keys
- **Dosya:** `app/services/binance_assets.py`
- **Gereksinimler:** Account.api_key_enc, Account.api_secret_enc dolu ve decrypt edilebilir
- **Eksikse:** `ValueError(ACCOUNT_KEYS_MISSING)`

### 4.5 AssetSnapshot Tablosu
```sql
asset_snapshots:
  id, account_id, timestamp, total_usd_value, breakdown_json, source
```
- **breakdown_json:** `{ "USDT": { "free": 100, "locked": 0, "usdValue": 100 }, ... }`

---

## 5. Frontend Bileşenleri — Detay

### 5.1 homeFlash.init()
- storageCache’ten wallet_cached yükler (30 dk MAX_AGE_MS)
- wallet_cached varsa → walletCachedToAssetsState() → status='ready'
- loadFast() çağırır
- triggerRefresh() çağırır

### 5.2 walletCachedToAssetsState(walletCached, walletCachedAt)
- **Dosya:** `ui/assets/renderHome.js`
- **Koşul:** `if (!walletCached || typeof walletCached !== 'object') return;`
- **Yaptığı:** `normalizeAndApplyWallet(p, { source: 'home_fast_cached' })` kullanır (varsa); home_fast `usdt_value` → `value_usd`, `free_usd`, `locked_usd` map edilir
- **Sonuç:** BinanceAssetsPanel.render() + renderVarliklarList() tetiklenir

### 5.3 Tek Reducer: normalizeAndApplyWallet(payload, meta)
- **Dosya:** `ui/assets/dashboard.js`
- **coerceNumber(x):** string "10500.50" → number; typeof drop önlenir
- **Kurallar:** `status = _error ? 'error' : 'ready'`; totals null + assets boş + keys_configured true → WALLET_EMPTY_UNEXPECTED
- **window.__walletEvents:** Son 50 wallet event (source, status, total_usd, asset_count, note)
- **pushWalletEvent(ev):** Her wallet güncellemesinde çağrılır
- **window.__ACTIVE_ACCOUNT_ID:** initDashboard'da atanır; tek kaynak hesap kimliği

### 5.4 Fallback Mekanizması (homeFlash.js)
- `data.wallet_cached` null ve status idle/loading ise:
  - 3 denemelik retry: 600ms, 1500ms, 4000ms → `BinanceAssetsPanel.refresh()` → pollWallet(true)
  - pollWallet → GET /api/binance/wallet

### 5.5 dashboardDataRefresh Fallback
- wallet status idle/loading ise `_binanceWalletIdleCycles` artırılır
- 2 döngü (≈6 sn) sonra `fetchSnapshot()` çağrılır
- getSnapshotFields() wallet idle iken `'prices,kpis,wallet'` döner
- fetchSnapshot → GET /api/dashboard/snapshot?fields=prices,kpis,wallet
- applySnapshotToUI(data) → data.wallet varsa assetsState.wallet doldurulur

### 5.6 pollWallet
- GET /api/binance/wallet
- Başarılıysa assetsState.wallet.status = 'ready'
- Binance API doğrudan çağrılır (cache miss)

### 5.7 renderAssetsSummary()
- `walletLoading = status === 'idle' || status === 'loading'`
- walletLoading true ise → "Yükleniyor…" gösterir, return
- status 'ready' olmalı ki değerler yazılsın

---

## 6. Kök Neden Analizi — Olası Senaryolar

### 6.1 AssetSnapshot Hiç Yazılmamış
**Neden:** POST /api/home/wallet/refresh hiç başarılı olmamış.
- API key/secret tanımlı değil → ACCOUNT_KEYS_MISSING
- 401 (geçersiz key, IP, saat)
- 429 (rate limit)
- Timeout
- wallet/refresh hiç tetiklenmemiş (init sırasında document.hidden, hata vb.)

**Sonuç:** home/fast her zaman wallet_cached=null döner.

### 6.2 storageCache Boş veya Süresi Dolmuş
- İlk ziyaret veya 30 dk’dan eski cache
- wallet_cached init’te yok
- loadFast wallet_cached=null döner

### 6.3 triggerRefresh Başarısız veya Atlanmış
- REFRESH_DEBOUNCE_MS, REFRESH_LOCK_TTL_MS
- ~~document.hidden true ise tetiklenmez~~ (KALDIRILDI — arka planda da tetiklenir)
- account_id != __ACTIVE_ACCOUNT_ID ise ACCOUNT_ID_MISMATCH → atlanır
- API hata verirse snapshot yazılmaz

### 6.4 pollWallet Başarısız
- GET /api/binance/wallet 403 (auth?)
- Timeout
- Binance 401/429
- Fallback 600 ms sonra çalışsa bile hata alırsa status 'error' kalır

### 6.5 fetchSnapshot wallet Hata Veriyor
- need_wallet = "wallet" in requested_fields or "kpis" in requested_fields
- kpis her zaman isteniyor; need_wallet true
- Ama getSnapshotFields() wallet idle iken 'prices,kpis,wallet' döner
- Snapshot içinde wallet _error ile gelebilir (timeout, 401)
- applySnapshotToUI: data.wallet._error varsa `status='error'` atanır; "Yenile | Ayarlara git" banner gösterilir (2026-02-12 patch)

### 6.6 BinanceAssetsPanel.refresh Yanlış Yönlendirme
- FLASH_HOME_ENABLED=true iken binanceRefresh() → homeFlash.triggerRefresh()
- BinanceAssetsPanel.refresh() → pollWallet(true) direkt
- Yani fallback’te pollWallet doğru çağrılıyor

### 6.7 Tab Zamanlaması
- Kullanıcı hemen başka taba geçerse startBinanceTabPolling çalışmamış olabilir
- walletIdle kontrolü tab değişince sıfırlanmıyor; _binanceWalletIdleCycles sadece dashboardDataRefresh içinde

### 6.8 Script Yükleme Sırası
- homeFlash, renderHome, storageCache, BinanceAssetsPanel sırası önemli
- BinanceAssetsPanel.refresh tanımlı değilse fallback çalışmaz

---

## 7. Teşhis Kontrol Listesi

### 7.1 Veritabanı
```sql
SELECT * FROM asset_snapshots WHERE account_id = ? ORDER BY timestamp DESC LIMIT 5;
```
- Hiç kayıt yoksa → wallet/refresh hiç başarılı olmamış
- Kayıt varsa → home/fast neden null dönüyor kontrol et (farklı account_id, session?)

### 7.2 API Key
- Ayarlar’da Binance API Key ve Secret girilmiş mi?
- Account tablosunda api_key_enc, api_secret_enc dolu mu?

### 7.3 Ağ İstekleri (Tarayıcı DevTools)
- GET /api/home/fast → 200? data.wallet_cached dolu mu?
- POST /api/home/wallet/refresh → 200? data.wallet_live dolu mu?
- GET /api/binance/wallet → 200? assets[] dolu mu?
- GET /api/dashboard/snapshot?fields=... → 200? data.wallet var mı?

### 7.4 Console
- `window.__DEBUG_NET__ = true` ile homeFlash logları
- `?debug_wallet=1` ile debug overlay (sağ alt köşe: accountId, status, source, totals, son 5 event)
- `window.assetsState?.wallet` — status, source, total_usd, assets.length
- `window.__walletEvents` — son 50 wallet event
- Herhangi bir JavaScript hatası

### 7.5 Sunucu Logları
- home_wallet_refresh event logları
- [home] wallet refresh write snapshot failed
- [snapshot] wallet error
- wallet cache_hit, upstream_call
- **wallet_trace:** `app.core.logging_helpers.log_wallet_trace` — event=wallet_payload_out, source=home_fast_cached|wallet_refresh_live|snapshot_wallet|binance_wallet, asset_count, total_usd, cache_hit, upstream_call, duration_ms

---

## 8. Çözüm Önerileri

### 8.1 Kısa Vadeli (Mevcut Fallback’leri Güçlendirme)
1. **İlk yüklemede agresif fallback:** wallet_cached null ve status idle ise 2. home/fast cevabında beklemeden hemen pollWallet veya fetchSnapshot(wallet) tetikle
2. **pollWallet auth:** GET /api/binance/wallet require_auth ile korunuyor mu kontrol et; 403 ise token/session kontrolü
3. **localStorage bootstrap:** İlk kurulumda boş wallet ile status='ready' yapma; ama "API key ekleyin" mesajını net göster

### 8.2 Orta Vadeli (Mimari)
1. **AssetSnapshot seed:** Hesap ilk oluşturulduğunda veya API key ilk girildiğinde tek seferlik wallet/refresh tetikle (background job)
2. **dashboard/snapshot wallet her zaman:** Binance tabında ilk 2–3 istekte fields’a wallet ekle (zaten yapıldı)
3. **Health endpoint:** GET /api/home/wallet/status genişlet — son_snapshot_at, last_error, keys_configured dönsün; UI buna göre kullanıcıya net mesaj versin

### 8.3 Uzun Vadeli
1. **WebSocket wallet push:** Binance sekmesi açıkken wallet güncellemesi push ile gelsin
2. **Optimistic UI:** Önceki oturumdan cache varsa hemen göster, arka planda yenile
3. **Wallet service:** Cüzdan verisi tek bir service’te toplansın; home, snapshot, binance/wallet hepsi bu service’i kullansın

---

## 9. Kod Konumları Referansı

### 9.1 Backend
| Bileşen | Dosya | Satır (yaklaşık) |
|---------|-------|------------------|
| home_fast | app/api/subroutes/home.py | 183-283 |
| home_wallet_refresh | app/api/subroutes/home.py | 370-533 |
| _get_last_wallet_snapshot_sync | app/api/subroutes/home.py | 95-118 |
| _do_wallet_refresh | app/api/subroutes/home.py | 295-368 |
| AssetSnapshot model | app/db/models.py | 374-385 |
| _fetch_wallet_uncached | app/api/routes.py | 2465-2519 |
| api_binance_wallet | app/api/routes.py | 2528-2700 |
| api_debug_wallet_diag | app/api/routes.py | — |
| api_dashboard_snapshot | app/api/routes.py | 2043-2290 |
| log_wallet_trace | app/core/logging_helpers.py | — |
| get_account_keys | app/services/binance_assets.py | 23-47 |

### 9.2 Frontend
| Bileşen | Dosya | Satır (yaklaşık) |
|---------|-------|------------------|
| assetsState | ui/assets/dashboard.js | 4168-4169 |
| homeFlash.init | ui/assets/homeFlash.js | 59-83 |
| homeFlash.loadFast | ui/assets/homeFlash.js | 84-151 |
| walletCachedToAssetsState | ui/assets/renderHome.js | 33-90 |
| normalizeAndApplyWallet | ui/assets/dashboard.js | — |
| coerceNumber, pushWalletEvent, __walletEvents | ui/assets/dashboard.js | — |
| renderWalletDebugOverlay | ui/assets/dashboard.js | ?debug_wallet=1 |
| pollWallet | ui/assets/dashboard.js | 4275-4400 |
| renderAssetsSummary | ui/assets/dashboard.js | 4363-4431 |
| dashboardDataRefresh | ui/assets/dashboard.js | 8660-8684 |
| getSnapshotFields | ui/assets/dashboard.js | 801-812 |
| applySnapshotToUI | ui/assets/dashboard.js | 828-896 |
| BinanceAssetsPanel | ui/assets/dashboard.js | 4548-4562 |

### 9.3 Config / Env
| Değişken | Varsayılan | Açıklama |
|----------|------------|----------|
| FLASH_HOME_ENABLED | true | home/fast kullan |
| home_fast_cache_ttl_sec | 2 | home/fast memory cache TTL |
| wallet_live_ttl_sec | 5 | wallet/refresh TTL |
| wallet_cooldown_sec | 30 | Hata sonrası cooldown |
| home_fast_max_assets | 20 | Snapshot’ta max varlık sayısı |
| WALLET_RESPONSE_CACHE_TTL | 2 | binance/wallet cache süresi |

---

## 10. Tahminler ve Olası Gelecek Sorunlar

### 10.1 Yeni Hesap
- AssetSnapshot hiç yok
- İlk wallet/refresh 401/keys_missing alabilir
- Kullanıcı API key ekleyene kadar boş kalır

### 10.2 Çoklu Sekme
- Aynı hesap iki sekmede açıksa localStorage cache paylaşılır
- Bir sekmede refresh diğerini güncellemez (real-time değil)

### 10.3 Rate Limit (429)
- Binance 429 verirse cooldown 30 sn
- Bu sürede wallet_cached eski kalır, yeni snapshot yazılmaz

### 10.4 Sunucu Saati
- Binance signed isteklerde timestamp kullanır
- Windows sunucuda saat yanlışsa 401 (-1021) gelebilir

### 10.5 Session/Token
- require_auth başarısız olursa 401
- Token süresi dolmuşsa home/fast ve wallet/refresh 401 döner
- Frontend login’e yönlendirir, cüzdan verisi hiç yüklenmez

---

## 11. Hızlı Aksiyon Önerileri

1. **DB kontrolü:** `asset_snapshots` tablosunda ilgili account_id için kayıt var mı?
2. **API key:** Ayarlar’da Binance key tanımlı mı?
3. **Network:** home/fast ve wallet/refresh 200 dönüyor mu? Response body’de wallet_cached / wallet_live var mı?
4. **Fallback süresi:** 6 sn bekleyip fetchSnapshot’ın wallet ile çağrıldığını doğrula
5. **pollWallet:** BinanceAssetsPanel.refresh() tetiklendiğinde /api/binance/wallet isteği gidiyor mu?

---

## 12. Özet Akış Şeması (Metin)

```
[Kullanıcı Anasayfa Açar]
         │
         ▼
   initDashboard()
         │
         ▼
   homeFlash.init()
         │
         ├──► storageCache.load() ──► wallet_cached var? ──► walletCachedToAssetsState() ──► status=ready
         │
         ▼
   loadFast() ──► GET /api/home/fast
         │
         ├──► wallet_cached var? ──► walletCachedToAssetsState() ──► status=ready
         │
         └──► wallet_cached yok? ──► Fallback: 3 retry (600/1500/4000ms) ──► BinanceAssetsPanel.refresh() ──► pollWallet()
         │
         ▼
   triggerRefresh() ──► POST /api/home/wallet/refresh
         │
         └──► Başarılı? ──► AssetSnapshot yaz ──► Sonraki home/fast wallet_cached dolu döner

[Her 3 sn] dashboardDataRefresh()
         │
         ├──► wallet idle 2 cycle? ──► fetchSnapshot(wallet) ──► GET /api/dashboard/snapshot?fields=prices,kpis,wallet
         │
         └──► homeFlash.loadFast()
```

---

## 13. API Sözleşmeleri — Tam Payload Örnekleri

### 13.1 GET /api/home/fast Başarılı Response
```json
{
  "ok": true,
  "data": {
    "prices": { "BTCUSDT": { "price": 97500, "change24h": 0.5 }, "ETHUSDT": { "price": 3500, "change24h": -0.2 } },
    "kpis": { "total_bots": 3, "active_bots": 2, "total_pnl_usd": 150, "daily_bot_pnl_usd": 25 },
    "wallet_cached": {
      "total_usd": 10500.50,
      "assets": [
        { "asset": "USDT", "free": 5000, "locked": 0, "usdt_value": 5000 },
        { "asset": "BTC", "free": 0.05, "locked": 0.02, "usdt_value": 5500.50 }
      ]
    },
    "wallet_cached_at": "2026-02-12T10:30:00.000Z",
    "wallet_live_inflight": false
  },
  "meta": {
    "request_id": "abc-123",
    "server_ms": 45,
    "payload_bytes": 1200,
    "cache": true,
    "stale": false,
    "generated_at": "2026-02-12T10:30:00.000Z"
  }
}
```

### 13.2 GET /api/home/fast — wallet_cached null (Problem Senaryosu)
```json
{
  "ok": true,
  "data": {
    "prices": { "BTCUSDT": { "price": 97500 } },
    "kpis": { "total_bots": 0, "active_bots": 0 },
    "wallet_cached": null,
    "wallet_cached_at": null,
    "wallet_live_inflight": false
  },
  "meta": { "cache": false, "stale": true }
}
```

### 13.3 POST /api/home/wallet/refresh Başarılı
```json
{
  "ok": true,
  "data": {
    "wallet_live": { "total_usd": 10500, "assets": [...] },
    "wallet_live_at": "2026-02-12T10:30:05.000Z",
    "inflight": false,
    "skipped": false
  }
}
```

### 13.4 POST /api/home/wallet/refresh — Cooldown/TTL Skip
```json
{
  "ok": true,
  "data": {
    "wallet_live": { "total_usd": 10500, "assets": [...] },
    "wallet_live_at": "2026-02-12T10:30:00.000Z",
    "skipped": true,
    "inflight": false,
    "refresh_policy": { "ttl_sec": 5, "cooldown_sec": 30 }
  }
}
```

### 13.5 GET /api/binance/wallet — Anahtar Yok
```json
{
  "ok": true,
  "account_id": 1,
  "total_usd": 0,
  "free_usd": 0,
  "locked_usd": 0,
  "assets": [],
  "keys_configured": false,
  "ts": "2026-02-12T10:30:00.000Z"
}
```

### 13.6 GET /api/debug/wallet/diag — Teşhis (2026-02-12)
```json
{
  "ok": true,
  "data": {
    "request_id": "abc",
    "account_id_requested": 3,
    "active_account_id_from_auth": 3,
    "keys_configured": true,
    "decrypt_ok": true,
    "last_snapshot_at": "2026-02-12T10:30:00Z",
    "snapshot_total_usd": 10500.5,
    "snapshot_asset_count": 12,
    "wallet_cache_age_sec": 2.5,
    "wallet_cache_total_usd": 10500.5,
    "wallet_cache_asset_count": 12,
    "live_fetch": { "ok": true, "total_usd": 10500.5, "asset_count": 12 }
  }
}
```
Auth: require_auth + require_account_access. live_fetch 3s timeout.

---

## 14. Hata Kodu Eşlemesi

| Hata / Durum | Kaynak | UI Etkisi |
|--------------|--------|-----------|
| ACCOUNT_KEYS_MISSING | get_account_keys | keys_configured=false; boş assets |
| BINANCE_TIMEOUT | _do_wallet_refresh | Snapshot yazılmaz; cooldown 30 sn |
| BINANCE_RATE_LIMIT | 429/418 response | Snapshot yazılmaz; cooldown 30 sn |
| 401 Unauthorized | Binance API | Snapshot yazılmaz; cooldown; stale fallback |
| -1021 Timestamp outside | Binance (sunucu saati) | 401 benzeri |
| _error: timeout | _safe() SNAPSHOT_TASK_TIMEOUT | applySnapshotToUI wallet atlar |
| ~~document.hidden~~ | triggerRefresh | (KALDIRILDI) Artık arka planda da tetiklenir |
| isRefreshLocked | localStorage lock | wallet/refresh atlanır |
| REFRESH_DEBOUNCE_MS | lastRefreshAttemptAt | İlk 30 sn içinde tek tetikleme |

---

## 15. Zaman Çizelgesi — İlk Yükleme

```
T=0ms     initDashboard() çağrılır
T=0ms     homeFlash.init() → renderSkeleton(), storageCache.load()
T=0ms     cached.wallet_cached varsa → walletCachedToAssetsState() [status=ready]
T=0ms     loadFast() → GET /api/home/fast (paralel)
T=0ms     triggerRefresh() → debounce/lock kontrolü
T=50ms    home/fast 200 döner
T=50ms    data.wallet_cached null → fallback koşulu: tabBinance active, walletIdle
T=650ms   setTimeout 600ms → BinanceAssetsPanel.refresh() → pollWallet(true)
T=700ms   GET /api/binance/wallet (paralel: wallet/refresh devam ediyor olabilir)
T=750ms   triggerRefresh geçtiyse POST /api/home/wallet/refresh (lastRefreshAttemptAt, lock)
T=1200ms  wallet/refresh 200 + wallet_live → walletCachedToAssetsState, storageCache.mergeSaved
T=1200ms  pollWallet 200 → assetsState.wallet.status='ready', BinanceAssetsPanel.render()
```

**Kritik pencereler:**
- 0–30 sn: REFRESH_DEBOUNCE_MS; ikinci triggerRefresh atlanır
- 0–20 sn: REFRESH_LOCK_TTL_MS; localStorage lock
- 600/1500/4000 ms: Fallback 3 deneme; tab kontrolü kaldırıldı (walletIdle yeterli)

---

## 16. Detaylı Kod Parçaları

### 16.1 homeFlash.js — Fallback Koşulu
```javascript
if (data.wallet_cached) {
    renderHome.walletCachedToAssetsState(data.wallet_cached, data.wallet_cached_at);
    _walletFallbackAttempts = 0;
} else if (_walletFallbackAttempts < WALLET_FALLBACK_MAX_ATTEMPTS && typeof window.BinanceAssetsPanel !== 'undefined' && window.BinanceAssetsPanel.refresh) {
    var walletIdle = window.assetsState && window.assetsState.wallet && (window.assetsState.wallet.status === 'idle' || window.assetsState.wallet.status === 'loading');
    if (walletIdle) {
        var delayMs = WALLET_FALLBACK_DELAYS_MS[Math.min(_walletFallbackAttempts, WALLET_FALLBACK_DELAYS_MS.length - 1)];
        _walletFallbackAttempts++;
        setTimeout(function () {
            if (window.BinanceAssetsPanel && window.BinanceAssetsPanel.refresh) window.BinanceAssetsPanel.refresh();
        }, delayMs);
    }
}
```
**WALLET_FALLBACK_DELAYS_MS:** [600, 1500, 4000] — 3 deneme. Tab kontrolü kaldırıldı; walletIdle ise tetiklenir.

### 16.2 renderHome.js — walletCachedToAssetsState ve normalizeAndApplyWallet
```javascript
if (!walletCached || typeof walletCached !== 'object') return;
// normalizeAndApplyWallet varsa kullan (home_fast usdt_value → value_usd, free_usd, locked_usd map)
if (window.normalizeAndApplyWallet) {
    var p = { total_usd, free_usd, locked_usd, assets: assetsForPanel, keys_configured: true, data_status: 'cached', ts };
    window.normalizeAndApplyWallet(p, { source: 'home_fast_cached' });
    return;
}
```
Boş obje `{}` geçerli; `{ total_usd: 0, assets: [] }` da geçerli. `null` veya `undefined` ile hiçbir güncelleme yapılmaz.

### 16.3 dashboard.js — getSnapshotFields (Satır 801-812)
```javascript
function getSnapshotFields() {
    var hasWallet = (requested_fields && requested_fields.indexOf('wallet') >= 0) || false;
    if (!hasWallet && assetsState && assetsState.wallet && (assetsState.wallet.status === 'idle' || assetsState.wallet.status === 'loading')) {
        hasWallet = true;  // wallet idle ise ekle
    }
    var fields = ['prices', 'kpis'];
    if (hasWallet) fields.push('wallet');
    // ...
}
```
Wallet idle/loading iken fields'a `wallet` eklenir; fetchSnapshot bu fields ile çağrıldığında need_wallet=true olur.

### 16.4 home.py — _get_last_wallet_snapshot_sync
```python
row = (
    db.query(AssetSnapshot)
    .filter(AssetSnapshot.account_id == account_id)
    .order_by(desc(AssetSnapshot.timestamp))
    .limit(1)
    .first()
)
if not row:
    return (None, None)
```
Hiç AssetSnapshot yoksa `(None, None)`; home_fast payload'ında `wallet_cached: null`.

---

## 17. TRADE_TRAILING_MASTER_SPEC ile Uyum

Spec’te ilgili bölümler:
- **Dashboard snapshot:** fields=prices,wallet,bots,kpis; SNAPSHOT_TASK_TIMEOUT 3s
- **home/wallet/refresh:** TTL 5s, cooldown 30s, inflight dedup
- **binance/wallet:** TTL 2s, in-flight dedupe
- **wallet:poll:** 15000 ms; dashboard’da snapshot kullanıldığı için wallet poll kaldırılmış

Bu rapor spec ile uyumludur; değişiklik yapıldığında spec güncellenmelidir.

---

## 18. Ortam Bağımlılıkları

### 18.1 Geliştirme (localhost)
- Binance API testnet/live; IP whitelist
- SQLite dca.db; asset_snapshots tablosu migrate edilmiş olmalı

### 18.2 Windows Server
- Sunucu saati: `w32tm /resync` — Binance -1021 hatası önleme
- document.hidden: (KALDIRILDI) triggerRefresh artık arka planda da tetiklenir

### 18.3 Çoklu Instance
- _fast_cache, _wallet_refresh_inflight, _in_memory_wallet in-memory; instance başına
- Redis kullanılmıyorsa aynı account farklı instance’larda farklı cache

---

## 19. Test Senaryoları ve Beklenen Sonuçlar

| Senaryo | Başlangıç | Beklenen |
|---------|-----------|----------|
| Yeni hesap, API key yok | asset_snapshots boş | wallet_cached=null; pollWallet keys_configured=false; "API key ekleyin" |
| Yeni hesap, API key var | asset_snapshots boş | wallet/refresh başarılı → snapshot yazılır; 2. home/fast wallet_cached dolu |
| Eski hesap, snapshot var | DB’de son 1 saat içinde kayıt | home/fast cache hit; wallet_cached dolu; status=ready |
| 429 rate limit | Binance 429 | wallet/refresh _error; cooldown 30 sn; stale gösterilir |
| Sekme arka planda | document.hidden=true | triggerRefresh tetiklenir (2026-02-12); loadFast çalışır |

---

## 20. Debug Komutları

### Tarayıcı Console
```javascript
// Cüzdan durumu
JSON.stringify(window.assetsState?.wallet || {}, null, 2)

// Debug overlay (URL'ye ?debug_wallet=1 ekleyin)
// Sağ alt köşede: accountId, status, source, totals, son 5 event

// Son wallet event'leri
window.__walletEvents

// Aktif hesap (tek kaynak)
window.__ACTIVE_ACCOUNT_ID

// Manuel refresh
window.BinanceAssetsPanel && window.BinanceAssetsPanel.refresh()

// homeFlash debug
window.__DEBUG_NET__ = true

// storageCache içeriği
var u = JSON.parse(sessionStorage.getItem('user') || localStorage.getItem('user') || '{}');
var aid = u.account_id;
var k = 'tt_home_cache_v1:' + aid;
JSON.parse(localStorage.getItem(k) || '{}')
```

### Teşhis Endpoint (Backend)
```
GET /api/debug/wallet/diag?account_id=X
```
**Auth:** require_auth + require_account_access (aynı kullanıcı veya admin)

**Response:** keys_configured, decrypt_ok, last_snapshot_at, snapshot_total_usd, snapshot_asset_count, wallet_cache_age_sec, wallet_cache_total_usd, live_fetch (3s timeout ile). Kök neden tek çağrıda netleşir.

### Backend (Python shell)
```python
from app.db.base import SessionLocal
from app.db.models import AssetSnapshot
db = SessionLocal()
rows = db.query(AssetSnapshot).filter(AssetSnapshot.account_id == 1).order_by(AssetSnapshot.timestamp.desc()).limit(5).all()
for r in rows:
    print(r.id, r.timestamp, r.total_usd_value)
db.close()
```

---

## 21. Özet — En Olası 5 Kök Neden (CURSOR TASK)

1. **Payload totals string** — FE typeof checks null atar; coerceNumber ile çözüldü
2. **account_id mismatch** — home/fast ve wallet fetch farklı account_id; __ACTIVE_ACCOUNT_ID ile çözüldü
3. **State overwrite** — home/fast loop wallet_cached null dönünce loading'e geri döner; normalizeAndApplyWallet tek reducer
4. **applySnapshotToUI _error** — status loading kalıyordu; patch: status='error', banner göster
5. **assets filtered to 0** — threshold/max_assets sıralama hatası; backend trace ile tespit

---

## 22. Bileşen Bağımlılık Grafiği

```
                    ┌──────────────────┐
                    │  initDashboard   │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐
     │ storageCache│  │ homeFlash   │  │ intervalRegistry │
     │ .load()     │  │ .init()     │  │ dashboard_snapshot│
     └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘
            │                │                   │
            │                ├─ loadFast()       │ dashboardDataRefresh()
            │                │   └─ GET home/fast│   ├─ fetchSnapshot() [wallet idle 2x]
            │                │                   │   └─ homeFlash.loadFast()
            │                │                   │
            │                └─ triggerRefresh() │
            │                    └─ POST wallet/refresh
            │
            └──► walletCachedToAssetsState()  ◄── home/fast data.wallet_cached
                 wallet/refresh data.wallet_live
                 pollWallet() response
                 applySnapshotToUI(data.wallet)
```

**Bağımlılık zinciri (wallet verisi için):**
1. `assetsState.wallet` ← `walletCachedToAssetsState` | `pollWallet` | `applySnapshotToUI`
2. `walletCachedToAssetsState` ← home/fast `wallet_cached` veya wallet/refresh `wallet_live`
3. `pollWallet` ← GET /api/binance/wallet
4. `applySnapshotToUI` ← GET /api/dashboard/snapshot `data.wallet`

**Kritik:** Bu üç kaynaktan en az biri başarılı olmalı; hiçbiri çalışmazsa status idle/loading/error kalır.

---

## 23. storageCache Detayları

- **Key:** `tt_home_cache_v1:{accountId}`
- **MAX_AGE_MS:** 30 dakika (1800000)
- **İçerik:** `{ wallet_cached, wallet_cached_at, prices, kpis, generated_at }`
- **mergeSaved:** loadFast veya wallet/refresh sonrası günceller
- **load:** init’te çağrılır; `cached.wallet_cached` varsa hemen walletCachedToAssetsState

**Önemli:** İlk ziyarette storageCache boş; önceki oturumdan 30 dk içinde cache varsa anında gösterim mümkün.

---

## 24. pollWallet Akışı (dashboard.js Satır 4236-4353)

1. `walletPollInflight` kontrolü — aynı anda tek istek (manuel refresh hariç)
2. `walletPollBackoffUntil` — 429 sonrası bekleme
3. status 'idle'/'loading' ise body'de "Yükleniyor…"
4. GET /api/binance/wallet
5. Başarılı: assetsState.wallet doldurulur, status='ready', BinanceAssetsPanel.render()
6. Hata: status='error'; 429 ise backoff, stale gösterim

**apiClient:** apiClient.get() kullanır; cookie/token otomatik eklenir. apiClient yoksa fetch() fallback.

---

## 24b. Backend Wallet Trace (log_wallet_trace)

`app.core.logging_helpers.log_wallet_trace` — JSON-friendly event log. Logger: `wallet_trace`.

**Event:** `wallet_payload_out`  
**Source:** home_fast_cached | wallet_refresh_live | snapshot_wallet | binance_wallet

**Alanlar:** request_id, account_id, source, keys_configured, asset_count, total_usd, free_usd, locked_usd, error_code, cache_hit, upstream_call, age_sec, duration_ms

**Konumlar:** app/api/subroutes/home.py (home/fast, wallet/refresh), app/api/routes.py (binance/wallet, dashboard/snapshot)

---

## 25. Binance API Zinciri (Backend)

```
get_account_keys(account_id, db)
  └─ Account.api_key_enc, api_secret_enc
  └─ decrypt_text()
  └─ BinanceKeys(api_key, api_secret, testnet)

_fetch_wallet_uncached(account_id, db)
  └─ get_account_keys()  [ValueError → ACCOUNT_KEYS_MISSING]
  └─ get_wallet(keys)    [Binance GET /api/v3/account]
  └─ ticker_24h_all()   [Fiyat haritası]
  └─ _wallet_response() [total_usd, assets[], bot_locked]
```

**Test hesabı:** is_test_account true ise Binance çağrılmaz; 10.000 USDT paper balance döner.

---

## 26. applySnapshotToUI — Wallet Bölümü

```javascript
if (data.wallet && typeof data.wallet === 'object' && assetsState && assetsState.wallet) {
    const w = data.wallet;
    normalizeAndApplyWallet(w, { source: 'dashboard_snapshot', request_id: data.meta?.request_id || w._request_id });
    BinanceAssetsPanel.render();
    renderVarliklarList();
}
```

**2026-02-12 patch:** `normalizeAndApplyWallet` tek reducer; `w._error` varsa `status='error'` atanır, "Yenile | Ayarlara git" banner gösterilir. Stale total korunur ama status artık loading kalmaz.

---

## 27. dashboardDataRefresh — walletIdle ve fetchSnapshot Tetiklemesi

```javascript
var walletIdle = assetsState && assetsState.wallet && (assetsState.wallet.status === 'idle' || assetsState.wallet.status === 'loading');
if (walletIdle) {
    _binanceWalletIdleCycles++;
    if (_binanceWalletIdleCycles >= 2) {
        _binanceWalletIdleCycles = 0;
        fetchSnapshot();  // fields=getSnapshotFields() → 'prices,kpis,wallet'
        return;
    }
} else {
    _binanceWalletIdleCycles = 0;
}
```

**Zamanlama:** SNAPSHOT_POLL_MS=3000; 2 döngü = 6 sn. Yani wallet idle 6 sn sonra fetchSnapshot(wallet) tetiklenir.

---

## 28. Script Yükleme Sırası (dashboard.html)

```
storageCache.js
renderHome.js
homeFlash.js
dashboard.js (assetsState, BinanceAssetsPanel, pollWallet, getSnapshotFields, applySnapshotToUI, dashboardDataRefresh)
```

**Kritik:** homeFlash.init() çağrıldığında renderHome ve storageCache hazır olmalı. BinanceAssetsPanel.refresh fallback’te kullanıldığı için dashboard.js yüklenmiş olmalı.

---

## 29. GET /api/binance/wallet — Auth Durumu

**2026-02-12:** `require_auth` ve `require_account_access` eklendi. 401/403 → standart JSON { error_code, message }.

---

## 30. Özet Karar Matrisi — Cüzdan Verisi Neden Boş?

| Koşul | wallet_cached | wallet/refresh | pollWallet | fetchSnapshot | Sonuç |
|-------|---------------|----------------|------------|---------------|-------|
| DB snapshot yok, API key yok | null | _error | keys_configured=false | wallet _error | Boş veya "API key ekleyin" |
| DB snapshot yok, API key var | null | Başarılı (2. istekte) | — | — | 2. home/fast’ta dolu |
| storageCache 30dk içinde | cached | — | — | — | Init’te hemen ready |
| Tab bots/finance | — | — | — | wallet fields yok | KPI’lar wallet olmadan |
| ~~document.hidden~~ | — | (KALDIRILDI) Tetiklenir | — | — | Arka planda da tetiklenir |

---

## 31. Ek Kaynaklar

- `TRADE_TRAILING_MASTER_SPEC.md` — sistem limitleri, endpoint sözleşmeleri
- `app/api/subroutes/home.py` — Flash Home backend, log_wallet_trace
- `app/core/logging_helpers.py` — log_wallet_trace
- `ui/assets/homeFlash.js` — Flash Home frontend, __ACTIVE_ACCOUNT_ID
- `ui/assets/renderHome.js` — walletCachedToAssetsState, normalizeAndApplyWallet
- `ui/assets/dashboard.js` — normalizeAndApplyWallet, coerceNumber, __walletEvents, renderWalletDebugOverlay
- `app/services/binance_assets.py` — get_account_keys, ACCOUNT_KEYS_MISSING
- `app/api/routes.py` — _fetch_wallet_uncached, api_binance_wallet, api_debug_wallet_diag, api_dashboard_snapshot

---

## 32. Teşhis Runbook — Adım Adım

### Adım 1: Veritabanı Kontrolü
```bash
sqlite3 dca.db "SELECT id, account_id, timestamp, total_usd_value FROM asset_snapshots ORDER BY timestamp DESC LIMIT 10;"
```
- Hiç satır yoksa → wallet/refresh hiç başarılı olmamış.
- account_id eşleşmiyorsa → yanlış hesap veya migration sorunu.

### Adım 2: API Key Kontrolü
```bash
sqlite3 dca.db "SELECT id, name, LENGTH(api_key_enc) as key_len, LENGTH(api_secret_enc) as secret_len FROM accounts WHERE id = ?;"
```
- key_len veya secret_len 0 ise → ACCOUNT_KEYS_MISSING.

### Adım 3: Tarayıcı Network
1. DevTools → Network
2. Filtre: home, wallet, binance, snapshot
3. GET /api/home/fast → Response body'de `data.wallet_cached` var mı?
4. POST /api/home/wallet/refresh → 200? `data.wallet_live` dolu mu?
5. GET /api/binance/wallet → 200? `assets` dizi dolu mu?

### Adım 4: Console Durumu
```javascript
// assetsState.wallet anlık durumu
JSON.stringify(window.assetsState?.wallet || {}, null, 2)

// Debug overlay: URL'ye ?debug_wallet=1 ekleyin
// Son wallet event'leri
window.__walletEvents

// Manuel refresh
window.BinanceAssetsPanel?.refresh?.()
```

### Adım 4b: Kök Neden için 6 Kanıt (Tek Seferde Topla)
1. **DevTools → Network:** `GET /api/binance/wallet` response body (tam JSON)
2. **DevTools → Network:** `GET /api/dashboard/snapshot?fields=prices,kpis,wallet` response body
3. **DevTools → Network:** `GET /api/home/fast?account_id=X` response body (wallet_cached, wallet_cached_at)
4. **Console:** `JSON.stringify(window.assetsState?.wallet || {}, null, 2)`
5. **localStorage:** `tt_home_cache_v1:{accountId}` içeriği
6. **DB:** `SELECT id, account_id, timestamp, total_usd_value FROM asset_snapshots WHERE account_id=? ORDER BY timestamp DESC LIMIT 5;`

Bunlar ile "payload boş mu", "tip uyuşmazlığı mı", "account_id mismatch mi" netleşir.

### Adım 5: Sunucu Logları
```bash
# home_wallet_refresh event
grep "home_wallet_refresh" app.log

# Snapshot wallet error
grep "\[snapshot\] wallet" app.log

# get_last_wallet_snapshot error
grep "get_last_wallet_snapshot" app.log
```

### Adım 6: Cooldown / Lock Temizleme (Geçici)
```javascript
// localStorage wallet refresh lock (20 sn TTL)
localStorage.removeItem('tt_wallet_refresh_lock:' + accountId);
```
Sunucu tarafı cooldown (_wallet_cooldown_until) sadece süre dolunca veya force=1 ile bypass edilir.

---

## 33. Olası Kod Hataları — Dikkat Edilmesi Gerekenler

1. **assetsState.wallet başlangıç:** `status: 'idle'` — Bu doğru; ready olana kadar UI "Yükleniyor…" gösterir.
2. **walletCachedToAssetsState total_usd 0:** Spec’e göre mevcut positive total'ı 0 ile üstüne yazmama var; ama ilk yüklemede currentTotal null, totalUsd 0 gelebilir.
3. **getSnapshotFields tab kontrolü:** `tabName === 'binance' || tabName === 'varliklar' || tabName === ''` — Boş string varsayılan binance kabul ediliyor.
4. **Spot modal açıkken:** `isSpotModalOpen()` true ise getSnapshotFields 'wallet,prices' döner; dashboardDataRefresh State.inFlight veya isSpotModalOpen nedeniyle erken return edebilir.

---

## 34. Uygulanan Patch (2026-02-12) ve CURSOR TASK Genişletmesi

### İlk 5 Maddelik Patch
1. **applySnapshotToUI:** `_error` gelince `status='error'` atanıyor; UI'da "Binance cüzdanı alınamadı: … — Yenile | Ayarlara git" mesajı gösteriliyor.
2. **homeFlash fallback:** `_walletFallbackTriggered` kaldırıldı; yerine 3 denemelik retry (600ms, 1500ms, 4000ms) eklendi.
3. **/api/binance/wallet:** `require_auth` ve `require_account_access` eklendi; auth hatalarında standart JSON dönüyor.
4. **wallet/status:** `keys_configured`, `last_snapshot_at` eklendi.
5. **CLOCK_DRIFT:** Binance -1021 (timestamp outside) algılandığında `CLOCK_DRIFT` error_code ve Windows `w32tm /resync` uyarısı.

### CURSOR TASK — Kök Neden Teşhisi + Kalıcı Fix
6. **normalizeAndApplyWallet:** Tek reducer; `coerceNumber()` ile string→number; `status = _error ? 'error' : 'ready'`; WALLET_EMPTY_UNEXPECTED (totals null + assets boş + keys_configured true).
7. **__walletEvents:** Son 50 wallet event ring buffer; `pushWalletEvent()` her güncellemede.
8. **__ACTIVE_ACCOUNT_ID:** initDashboard'da atanır; homeFlash.getAccountId() önce bunu kullanır; ACCOUNT_ID_MISMATCH loglanır.
9. **triggerRefresh:** document.hidden kontrolü kaldırıldı; arka planda da tetiklenir.
10. **renderHome wallet_cached:** home_fast `usdt_value` → `value_usd`, `free_usd`, `locked_usd` map; `normalizeAndApplyWallet` ile işlenir.
11. **Debug overlay:** `?debug_wallet=1` — sağ alt köşede accountId, status, source, totals, son 5 event (2 sn refresh).
12. **Backend wallet_trace:** `app.core.logging_helpers.log_wallet_trace` — home_fast_cached, wallet_refresh_live, snapshot_wallet, binance_wallet kaynaklarında event=wallet_payload_out.
13. **GET /api/debug/wallet/diag:** keys_configured, decrypt_ok, last_snapshot, cache, live fetch (3s timeout); kök neden tek çağrıda.

---

## 35. Versiyon ve Güncelleme Notları

Bu rapor 2026-02-12 tarihinde oluşturuldu. CURSOR TASK güncellemeleri uygulandı. Aşağıdaki değişiklikler yapıldığında güncellenmelidir:
- home/fast veya wallet/refresh sözleşmesi değişirse
- AssetSnapshot şeması değişirse
- Yeni wallet veri kaynağı eklenirse
- Fallback zamanlamaları (600/1500/4000ms, 2 cycle) değişirse
- normalizeAndApplyWallet, log_wallet_trace, debug/diag değişirse
- TRADE_TRAILING_MASTER_SPEC’te ilgili bölümler güncellenirse

---

## 36. Cüzdan Verisi İçin Öncelik Sırası

1. **storageCache (localStorage):** Init’te anında — 30 dk MAX_AGE
2. **GET /api/home/fast:** Kritik yol Binance’sız; wallet_cached DB’den
3. **POST /api/home/wallet/refresh:** Arka planda; Binance → AssetSnapshot
4. **Fallback 600ms:** wallet_cached null + tab aktif + walletIdle → pollWallet
5. **dashboardDataRefresh 2 cycle:** wallet idle 6 sn → fetchSnapshot(wallet)
6. **GET /api/binance/wallet:** pollWallet ve binanceRefresh manuel

Bu sıra ile en az biri başarılı olmalı; hepsi başarısız olursa "Yükleniyor…" veya hata mesajı kalır.

---

## 37. Performans Notları

- home/fast cache TTL 2 sn — çok sık tekrar istek yapılmaz
- wallet/refresh Binance GET /api/v3/account — weight 10; rate limit dikkat
- Snapshot wallet her 3 sn’de (idle 2 cycle sonrası) — çok hesap açıkken yük
- binance/wallet cache 2 sn TTL + in-flight dedupe — aynı account için tek upstream

---

## 38. Güvenlik Notları

- API key/secret DB’de şifreli (api_key_enc, api_secret_enc)
- require_auth: home/fast, wallet/refresh, dashboard/snapshot, binance/wallet, debug/wallet/diag
- require_account_access: account_id kontrolü (binance/wallet, debug/wallet/diag dahil)

---

## 39. Özet Tablo — Tüm Veri Yolları

| Yol | Tetikleyici | Binance | DB Snapshot | assetsState Güncelleme |
|-----|-------------|---------|-------------|------------------------|
| storageCache init | homeFlash.init | Hayır | Okuma | walletCachedToAssetsState |
| home/fast | loadFast | Hayır | Okuma | walletCachedToAssetsState |
| wallet/refresh | triggerRefresh | Evet | Yazma+Okuma | walletCachedToAssetsState |
| pollWallet fallback | 600/1500/4000ms retry | Evet | Hayır | pollWallet response |
| fetchSnapshot | dashboardDataRefresh 2 cycle | Evet | Hayır | applySnapshotToUI |
| binanceRefresh | Manuel "Yenile" | Evet | Hayır | triggerRefresh veya pollWallet |
| debug/wallet/diag | Teşhis (manuel) | Evet (3s) | Okuma | — (sadece diag) |

---

## 40. İndeks — Bölüm Haritası

- §1-2: Problem, mimari
- §3-5: Veri akışı, backend, frontend
- §6: Kök neden analizi
- §7: Teşhis kontrol listesi
- §8: Çözüm önerileri
- §9-12: Kod konumları, tahminler, aksiyon, akış şeması
- §13-15: API sözleşmeleri (home/fast, wallet/refresh, binance/wallet, debug/diag), hata kodları, zaman çizelgesi
- §16-21: Kod parçaları, spec uyum, ortam, test, debug, özet kök neden
- §22-31: Bileşen grafiği, storageCache, pollWallet, wallet_trace, Binance zinciri, applySnapshotToUI, runbook, 6 kanıt
- §32-39: Versiyon notları, öncelik, performans, güvenlik, özet tablo

---

*Rapor sonu (1000+ satır). Sorular veya güncellemeler için bu dosya tek kaynak olarak kullanılabilir. Spec değişikliklerinde TRADE_TRAILING_MASTER_SPEC.md güncellenmelidir.*

---
