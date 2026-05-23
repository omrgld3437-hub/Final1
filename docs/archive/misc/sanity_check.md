# SANITY CHECK - DCA Bot Manager Clean Version

**Date:** 2026-01-24  
**Project:** DCA_Bot_Manager_Clean

## ÇALIŞTIRMA ADIMLARI

### 1. İlk Kurulum

```bash
cd ~/Desktop/DCA_Bot_Manager_Clean

# Run script'i çalıştır (otomatik venv kurulum + server başlatma)
./run.sh
```

Veya manuel:

```bash
cd ~/Desktop/DCA_Bot_Manager_Clean

# Virtual environment oluştur
python3 -m venv .venv

# Aktif et
source .venv/bin/activate

# Paketleri yükle
pip install -r requirements.txt

# Server'ı başlat
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Environment Variables

`.env` dosyası oluştur (`.env.example`'dan kopyala):

```bash
cp .env.example .env
```

`.env` dosyasını düzenle:
- `BINANCE_MASTER_KEY`: 32 karakterlik encryption key (Fernet.generate_key() ile oluştur)
- `DATABASE_URL`: SQLite için `sqlite:///./dca.db` (default)

### 3. Server Durumu Kontrol

```bash
# Server çalışıyor mu?
curl http://127.0.0.1:8000/docs

# Logları kontrol et
tail -f .run/server.log

# Veya app logları
tail -f logs/app.log
```

## TEST URL'LERİ

### Admin Sayfası
- **URL:** http://127.0.0.1:8000/ui/admin.html
- **Beklenen:** Admin sayfası açılmalı, hesap listesi görünmeli
- **Test:** Yeni hesap oluşturma çalışmalı

### Dashboard
- **URL:** http://127.0.0.1:8000/ui/dashboard.html
- **Beklenen:** Dashboard açılmalı, account_id parametresi ile hesap seçilmeli
- **Test:** Botlar sekmesi çalışmalı

### Index (Redirect)
- **URL:** http://127.0.0.1:8000/
- **Beklenen:** Dashboard'a yönlendirme

### API Docs
- **URL:** http://127.0.0.1:8000/docs
- **Beklenen:** FastAPI Swagger UI açılmalı

### Üst Ticker Canlı Fiyat
- **Endpoint:** `GET /api/pricing/summary`
- **Beklenen:** JSON ile `usdtry`, `eurtry`, `gbptry`, `btcusd`, `ethusd`, `gram_altin_tl`, `ons_altin_usd` (0 değil, makul sayılar); `source_status.fx`, `.metals`, `.crypto` (live|stale|error).
- **Frontend:** Dashboard üst bar (USD/TRY, EUR/TRY, GBP/TRY, BTC/USD, ETH/USD, Gram Altın TL, Ons Altın USD) 0 göstermemeli; 10–20 sn içinde BTC/ETH değişmeli. Network’te `/api/pricing/summary` ~2 sn’de bir çağrılır, backend cache ile dış API spam’i olmaz.

### Cüzdan / 429 fix – Wallet ve Open-Orders (2026-01-25)
- **Root cause:** 429’u backend dönüyordu (Binance veya internal limiter); UI kırılıyordu.
- **Backend – Zorunlu kural:** Cache varsa → **her zaman HTTP 200** (stale olabilir). Upstream 429/timeout olsa bile UI’a **429 gönderilmez** (serve stale). 429 **sadece cache boşken** (ilk çağrı) döner.
- **Backend – Wallet:** TTL **2.0 sn**; in-flight dedupe. Log: `wallet cache_hit=true/false upstream_call=true/false`; 429 dönüleceği an: `wallet 429 source=upstream cache_empty=true` (bu satırı logda ararsan 429’u kimin tetiklediği net olur).
- **Backend – Open-orders:** 2 sn TTL + in-flight dedupe; aynı serve-stale. Log: `open_orders cache_hit=...`; 429 anı: `open_orders 429 source=upstream cache_empty=true`.
- **Frontend – Tek owner:** Tüm Binance polling `binanceTab` owner’ında. `wallet:poll`, `tab.binance.prices`, `activeOrders.load`, `activeOrders.prices` → tab değişince / çıkışta tek `stopByOwner('binanceTab')` ile hepsi durur (duplicate polling yok).
- **Frontend – pollWallet:** WALLET_POLL_MS **4 sn**. 429’da interval durur, `retry_after` sonrası tekrar başlar; UI’da son değer kalır.
- **Frontend – loadActiveOrders:** 429’da liste korunur; interval durur, `retry_after` sonrası hem tek çağrı hem interval yeniden başlar.

### Cüzdan 2–4 sn güncelleme (Wallet / Binance)
- **Endpoint:** `GET /api/binance/wallet?account_id=<id>`
- **Beklenen:** JSON ile `account_id`, `total_usd`, `free_usd`, `locked_usd`, `assets[]`, `ts`, `ts_ms`. Opsiyonel: `data_status: "stale"`, `retry_after` (serve-stale durumunda).
- **Backend:** TTL 2 sn; in-flight dedupe; 429/upstream hata → serve stale (200 + cache) veya 429 + retry_after.
- **Frontend:** `WALLET_POLL_MS` 4 sn; 429’da polling durur, retry_after sonrası devam eder.

## MANUEL TEST ADIMLARI

### 1. Backend Test

```bash
# Server ayakta mı?
curl http://127.0.0.1:8000/docs

# Health check (eğer varsa)
curl http://127.0.0.1:8000/api/health
```

### 2. Admin Sayfası Test

1. Tarayıcıda aç: http://127.0.0.1:8000/ui/admin.html
2. Sayfa yüklenmeli, hata olmamalı
3. "Yeni Hesap" butonu çalışmalı
4. Hesap oluşturma modal'ı açılmalı
5. Form doldurulup kaydedilebilmeli

**Beklenen:**
- ✅ Sayfa açılıyor
- ✅ Hesap listesi görünüyor (boş olabilir)
- ✅ Yeni hesap oluşturma çalışıyor
- ✅ Console'da hata yok

### 3. Dashboard Test

1. Tarayıcıda aç: http://127.0.0.1:8000/ui/dashboard.html?account_id=1
2. Sayfa yüklenmeli, hata olmamalı
3. Tabs görünmeli: Anasayfa, Botlar, Finansal Hesap, Ayarlar
4. **Binance tab OLMAMALI** ❌

**Beklenen:**
- ✅ Sayfa açılıyor
- ✅ Tabs görünüyor (Anasayfa, Botlar, Finansal Hesap, Ayarlar)
- ✅ Binance tab YOK
- ✅ Botlar sekmesi çalışıyor
- ✅ Console'da hata yok
- ✅ Network'te 404 yok (kritik asset'ler yükleniyor)

### 4. Botlar Sekmesi Test

1. Dashboard'da "Botlar" tab'ına tıkla
2. Bot listesi görünmeli (boş olabilir)
3. "Bot Oluştur" butonu çalışmalı

**Beklenen:**
- ✅ Botlar sekmesi açılıyor
- ✅ Bot listesi görünüyor
- ✅ Bot oluşturma çalışıyor

### 5. Binance Endpoint Test (Mega Prompt sonrası – ÇALIŞMALI)

```bash
# Auth token gerekebilir; account_id geçerli hesap olmalı
curl -H "Authorization: Bearer <TOKEN>" "http://127.0.0.1:8000/api/binance/wallet?account_id=1"
curl -H "Authorization: Bearer <TOKEN>" "http://127.0.0.1:8000/api/binance/open-orders?account_id=1"
```

**Beklenen:**
- ✅ 200: account_id, total_usd, free_usd, locked_usd, assets[], ts (wallet)
- ✅ 200: account_id, orders[], count (open-orders)
- ✅ 404/400: Hesap yok veya keys yok ise error_code (ACCOUNT_NOT_FOUND, ACCOUNT_KEYS_MISSING)
- ✅ Response header: X-Request-Id mevcut

### 6. Console Error Check

Tarayıcı Developer Tools'da:

1. Console sekmesini aç
2. Hata var mı kontrol et

**Beklenen:**
- ✅ Console'da kritik hata yok
- ✅ Binance ile ilgili hata yok
- ⚠️ Uyarılar olabilir (kritik değil)

### 7. Network 404 Check

Tarayıcı Developer Tools'da:

1. Network sekmesini aç
2. Sayfayı yenile (F5)
3. 404 hatası var mı kontrol et

**Beklenen:**
- ✅ Kritik asset'ler yükleniyor (CSS, JS)
- ✅ 404 yok (kritik dosyalar için)
- ⚠️ binance.js için 404 olabilir (normal, kaldırıldı)

## BINANCE ENTEGRASYONU – SANITY CHECK (Mega Prompt sonrası)

- Coin list fiyatları canlı mı? → `/api/data/hub` → `data_status: "live"`, `ws_status: "rest"`, `prices`/`coin_list` dolu
- Wallet 1–4 sn içinde geliyor mu? → Binance sekmesi, cüzdan tablosu dolu (veya keys/hesap hatası anlamlı)
- Modal açılış gecikmesi var mı? → Al/Sat modal’da quick_data, commission, price/klines gerçek
- 429 simülasyonunda crash oluyor mu? → Backend **serve stale** (200 + cache) veya 429 + retry_after; frontend polling durur, retry_after sonrası devam eder; UI kırılmaz
- request_id frontend console’da görünüyor mu? → Network’te cevap header’ında `X-Request-Id` var
- Dashboard özetinde spot bakiye dolu mu? → `account.spot_balance_usd` > 0 (keys varsa)

## BAŞARILI TEST KRİTERLERİ

- ✅ Backend kalkıyor (server ayakta)
- ✅ Dashboard açılıyor
- ✅ Admin sayfası açılıyor ve hesap oluşturma çalışıyor
- ✅ Botlar sekmesi çalışıyor
- ✅ Binance sekmesi: wallet API çağrılıyor, veri veya anlamlı hata
- ✅ DataHub canlı fiyat/coin list dönüyor; ws_status connected veya rest
- ✅ Response header X-Request-Id mevcut
- ✅ Console’da kritik hata yok

### Prompt #2 – WebSocket + Ortak Katman
- Hub: `GET /api/data/hub` → `data_status=live`, `ws_status=connected` veya `rest`, prices/mini dolu
- WS kapalı simülasyonu → REST fallback ile fiyatlar gelmeye devam eder
- Spot modal: quick_data ve fiyat güncellemeleri hızlı
- Rate limit 429 → backend log’da retry/backoff görülür

### Wallet TRY bug fix (2026-01-25)
1. GET /api/binance/wallet → assets[] only Binance, total_usd sane.
2. UI: No TRY row from FX; total ~416 not 1620.
3. Wallet TTL cache 1.5s, no 429 spam.

### Binance Cancel Order (2026-01-26)
- **Endpoint:** DELETE /api/binance/order (query: account_id, symbol, order_id)
- **Kural:** Signature query string order == gönderilen query string order (imza ile gönderilen string birebir aynı).
- **Beklenen:** 200 + `success: true`, `status: "CANCELED"`; "Signature for this request is not valid" hatası olmamalı.
- **Test:** `curl -X DELETE -H "Authorization: Bearer <JWT>" "http://127.0.0.1:8000/api/binance/order?account_id=1&symbol=XRPUSDT&order_id=<ORDER_ID>"`

## RAM Probe Verification

RAM probe writes JSONL to `logs/ram_snapshots.log` when `RAM_PROBE=1`. Both web and worker processes write snapshots.

**Steps:**

1. `cd` proje klasörüne (örn. `cd ~/Desktop/trader`)
2. `RAM_PROBE=1 RAM_PROBE_INTERVAL=10 ./Server\ Start.command`
3. `ls -la logs/ram_snapshots.log` — file should exist and grow over time
4. `tail -n 5 logs/ram_snapshots.log` — each line is one JSON object
5. Confirm both components appear over time: `"component":"web"` and `"component":"worker"` in the JSON lines

**Troubleshooting:**

- If file is missing or empty: check `logs/web.log` and `logs/worker.log` for import errors (e.g. `app.observability.ram_probe`).
- Ensure `requirements.txt` includes `psutil`; probe still runs without psutil but writes `rss_mb: null`.
- To enable from shell: `export RAM_PROBE=1` and `export RAM_PROBE_INTERVAL=10` before running Server Start.command (or pass inline as in step 2).
