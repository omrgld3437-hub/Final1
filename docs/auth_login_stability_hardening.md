# Auth / Login Kararlılık Sertleştirme Playbook

**Versiyon:** 1.0  
**Dil:** Türkçe  
**Hedef:** "Sürekli login'e yönlendirme" sorunlarını teşhis etmek ve gidermek için mühendislik runbook + mimari + hata ayıklama kontrol listesi.

---

## 0. Fix Uygulandı (Auth Redirect Loop + Multi-Worker Session)

- **Backend:** Session doğrulama artık `boot_id` kullanmıyor (paylaşılan session store; multi-worker güvenli). `auth_sessions` tablosunda `revoked` kolonu ve sliding TTL (`last_seen_at`, `SESSION_SLIDING_UPDATE_MIN_SEC`) kullanılıyor. Tüm 401 yanıtları `error_code` + `request_id` içeriyor. `AUTH_VALIDATE` yapılandırılmış log satırı eklendi.
- **Frontend:** `apiClient` her istekte `credentials: 'include'` ve `X-Request-ID` gönderiyor. 401 session hatalarında tek seferlik redirect; login sayfasındayken redirect yapılmıyor (döngü önlenir). Kararlı auth store: `getStableAuth`, `setStableAuth`, `clearStableAuth`.
- **Doğrulama komutları:**
  - Testler: `TEST_LOGIN_USERNAME=... TEST_LOGIN_PASSWORD=... pytest tests/test_auth_session_shared.py -v`
  - Script: `TEST_LOGIN_USERNAME=... TEST_LOGIN_PASSWORD=... python scripts/verify_auth_loop_fix.py` (sunucu çalışırken)
  - Manuel: `uvicorn --workers 2` ile giriş yap → dashboard → F5 → sekme değiştir; login döngüsü olmamalı.

---

## 1. Yönetici Özeti

### 1.1 Problem İfadesi

- Uygulama kullanıcıyı beklenmedik şekilde sık sık login sayfasına yönlendiriyor.
- Kullanıcı giriş yaptıktan kısa süre sonra veya sayfa yenilemede tekrar login ekranına düşüyor.
- Bazı tarayıcılar veya cihazlarda (özellikle Safari, mobil) davranış farklı.
- Çok sekme kullanımında bir sekmede çıkış diğerlerini de login'e atıyor; bazen tersi de olabiliyor (loop).

### 1.2 Etki

- Kullanıcı deneyimi bozulur; güven kaybı.
- Destek yükü artar.
- Session hijack veya yanlış logout politikası güvenlik riski oluşturabilir.
- Geçici ağ kesintilerinde kullanıcı gereksiz yere logout edilebilir.

### 1.3 Başarı Kriterleri

- Geçici ağ hatası (timeout, 502/503/504) durumunda kullanıcı login'e atılmaz; toast + "sunucu geri gelince" davranışı.
- 401 yalnızca gerçek oturum sonu/geçersiz token durumunda login'e yönlendirir; tek 401'de tek redirect.
- Token refresh tek uçuşta (single-flight) yapılır; refresh storm oluşmaz.
- Cookie/header stratejisi Nginx + Cloudflare ile uyumlu; SameSite/Secure doğru ayarlanır.
- Tüm auth hataları standart formatta döner: `{ error_code, error_id, request_id }`.
- Rollback planı ve feature flag ile değişiklikler geri alınabilir.

---

## 2. Semptom Taksonomisi

### 2.1 Tam UX Semptomları

- **S1:** Sayfa açılır açılmaz login ekranı görünür (token varken).
- **S2:** Bir API çağrısından sonra aniden login'e yönlendirme.
- **S3:** Sayfa yenilemede (F5) login ekranı.
- **S4:** Sekme değiştirip geri gelince login.
- **S5:** Uygulama bir süre arka planda kalınca (sleep/wake) login.
- **S6:** Login'e yönlendirme döngüsü: login → dashboard → login → dashboard.
- **S7:** Sadece belirli sayfalarda (örn. bot detay) login; diğer sayfalar çalışıyor.
- **S8:** Sadece belirli tarayıcıda (Safari / Chrome / mobil) login.
- **S9:** Sunucu 502/503 döndükten sonra otomatik login'e atma.
- **S10:** Çok sekme: bir sekmede logout, diğerinde hâlâ girişte; veya tam tersi tutarsızlık.

### 2.2 Kategorizasyon

| Kategori | Semptomlar | Olası kök neden |
|----------|------------|------------------|
| Token/session | S1, S2, S3 | Token kaybı, TTL, storage, boot_id |
| Zamanlama/sekme | S4, S5, S10 | sessionStorage, BroadcastChannel, ITP |
| Döngü | S6 | 401 → clear → redirect → 401 |
| Ortam | S7, S8 | CORS, cookie domain, SameSite, proxy |
| Ağ | S9 | 5xx'te yanlışlıkla logout |

---

## 3. Mimari Harita

### 3.1 Giriş / Oturum Akış Diyagramı (ASCII)

```
[Kullanıcı] --> [Tarayıcı]
    |
    | 1. GET /ui/login.html
    v
[login.html] --> [apiClient] --> 2. POST /api/auth/login (phone, password)
    |                                    |
    | 3. 200 + token (body)               v
    |                           [FastAPI auth.py]
    |                                    |
    |                           [DB: users, auth_sessions]
    | 4. sessionStorage.setItem('token', token)
    | 5. sessionStorage.setItem('user', JSON)
    | 6. location = /ui/dashboard.html
    v
[Dashboard] --> 7. apiClient('/api/...') + Authorization: Bearer <token>
    |                                    |
    | 8. 200 OK                          v
    |                           [require_auth middleware]
    |                           [auth_sessions lookup by token_hash]
    |
    | 8b. 401 SESSION_NOT_FOUND / UNAUTHORIZED
    v
[apiClient] --> clearAuthAndBroadcast() --> replace('/ui/login.html')
```

### 3.2 Token / Cookie Saklama Konumları

| Konum | Kullanım | Risk |
|-------|----------|------|
| sessionStorage.token | Mevcut: Bearer token | Sekme kapatılınca kaybolur; XSS'te okunabilir |
| sessionStorage.user | Mevcut: kullanıcı bilgisi | Aynı |
| localStorage.boot_id | Mevcut: sunucu boot eşlemesi | Kalıcı; yanlış kullanımda logout |
| Cookie auth_token | Opsiyonel: backend Set-Cookie | httpOnly ile XSS'e kapalı; domain/path dikkat |
| Bellek (memory) | Refresh token öneri: sadece RAM | Sekme kapatılınca kaybolur |

### 3.3 İstek Yolu: Tarayıcı → Cloudflare → Nginx → FastAPI → Auth Middleware

```
Browser
  | fetch(url, { credentials: 'include' })
  | Cookie: auth_token=... (varsa)
  | Authorization: Bearer <token>
  v
Cloudflare (CDN)
  | Cache: /api/auth/*, /api/health → bypass
  | Header pass-through: Authorization, Cookie, X-Request-ID
  | Strip: Set-Cookie'yi strip etmeyin
  v
Nginx (reverse proxy)
  | proxy_set_header Authorization $http_authorization;
  | proxy_set_header Cookie $http_cookie;
  | proxy_pass http://backend;
  v
FastAPI (uvicorn)
  | Middleware: CORS → Request-ID → ... → Routes
  v
require_auth (Depends)
  | security = HTTPBearer(); token = credentials or request.cookies.get("auth_token")
  | _session_get(token, db)
  v
auth_sessions (DB) veya _sessions (memory fallback)
```

---

## 4. İlk 30 Kök Neden + Doğrulama Adımları

Her neden: semptom, neden olur, nasıl doğrulanır, tam fix, risk seviyesi.

### 4.1 Token / Session

1. **N1: Session TTL doldu**
   - Semptom: S2, S3.
   - Neden: auth_sessions.expires_at < now.
   - Doğrula: DB'de `SELECT * FROM auth_sessions WHERE token_hash = ?` ve expires_at kontrolü.
   - Fix: Sliding TTL (mevcut kodda var); TTL değerini makul yap (örn. 7 gün).
   - Risk: Düşük.

2. **N2: boot_id eşleşmemesi (memory fallback)**
   - Semptom: S3 (sunucu restart sonrası).
   - Neden: _sessions in-memory; worker restart'ta boot_id değişir; memory'deki session boot_id ile eşleşmez.
   - Doğrula: auth_sessions DB kullanılıyor mu kontrol et; DB yoksa memory fallback boot_id ile elenir.
   - Fix: auth_sessions tablosunu her ortamda kullan; memory sadece DB hatasında kalsın.
   - Risk: Orta.

3. **N3: Token sessionStorage'dan silinmiş**
   - Semptom: S1, S3, S4.
   - Neden: sessionStorage sekme/pencerede temizlenir; başka script clearAuthAndBroadcast çağırmış olabilir.
   - Doğrula: DevTools → Application → Session Storage; token key'i var mı.
   - Fix: Gereksiz clearAuthAndBroadcast çağrılarını kaldır; sadece 401 (session error) ve kullanıcı logout'ta çağır.
   - Risk: Orta.

4. **N4: Token hiç gönderilmiyor**
   - Semptom: S1, S2.
   - Neden: apiClient'da isPublic listesi yanlış; endpoint public sayılıp token eklenmiyor.
   - Doğrula: Ağ sekmesinde korumalı isteğe Authorization header'ı bak.
   - Fix: isPublic sadece /auth/login, /auth/register, /api/health, /api/boot-id içersin; diğer tüm /api/* için token ekle.
   - Risk: Yüksek.

5. **N5: CORS preflight'ta credential kaybı**
   - Semptom: S2, S8.
   - Neden: OPTIONS'ta credentials gönderilmez; bazı tarayıcılar sonraki istekte cookie/token'ı atlayabilir (yanlış konfig).
   - Doğrula: OPTIONS ve GET/POST'ta Request Headers'da Cookie/Authorization var mı.
   - Fix: CORS Allow-Credentials: true; Access-Control-Allow-Origin tek origin (wildcard değil).
   - Risk: Orta.

### 4.2 401 ve Redirect

6. **N6: Her 401'de redirect**
   - Semptom: S6 (loop).
   - Neden: 401 alan her istek clearAuth + redirect yapıyor; login sayfası da 401 alırsa (örn. token kalmış ama geçersiz) loop.
   - Doğrula: login sayfasından yapılan istekler 401 dönüyor mu; redirect sadece "session" 401'lerinde mi.
   - Fix: 401'de redirect sadece isSessionError (BOOT_ID_MISMATCH, SESSION_NOT_FOUND, UNAUTHORIZED) ve !onLoginPage.
   - Risk: Yüksek.

7. **N7: Login sayfası korumalı endpoint çağırıyor**
   - Semptom: S1, S6.
   - Neden: login.html yüklenirken bir script /api/dashboard veya benzeri çağırıyor; token yok → 401 → redirect.
   - Doğrula: login.html kaynakları ve script sırası; ağ sekmesinde ilk 401 hangi URL.
   - Fix: Login sayfasında korumalı API çağrısı yapma; veya token yoksa çağırma.
   - Risk: Yüksek.

8. **N8: 403'ü 401 gibi işleme**
   - Semptom: Yanlış logout.
   - Neden: 403 (örn. BINANCE_AUTH) için de redirect yapılıyorsa kullanıcı atılır.
   - Doğrula: apiClient'da 403 için login redirect var mı.
   - Fix: 403'te login'e yönlendirme; sadece toast veya hata göster.
   - Risk: Orta.

### 4.3 Proxy ve CDN

9. **N9: Nginx Authorization header'ı iletmiyor**
   - Semptom: S2, S7.
   - Neden: proxy_set_header Authorization $http_authorization; yok veya yanlış.
   - Doğrula: Backend log'da request.headers.get("Authorization") boş mu.
   - Fix: Nginx'te `proxy_set_header Authorization $http_authorization;`
   - Risk: Yüksek.

10. **N10: Cloudflare Set-Cookie'yi strip ediyor**
    - Semptom: Cookie ile auth kullanıyorsanız S2, S3.
    - Neden: Bazı CF kurallarında "Strip Set-Cookie" açık.
    - Doğrula: Response headers'da Set-Cookie var mı (CF'den sonra).
    - Fix: Cloudflare Page Rule / Transform Rule'da auth ve login path'lerinde Set-Cookie strip kapatın.
    - Risk: Yüksek (cookie kullanıyorsanız).

11. **N11: Cloudflare auth endpoint'leri cache'lıyor**
    - Semptom: S6, eski 401/200 cache'den dönüyor.
    - Neden: /api/auth/* cache'e alınmış.
    - Doğrula: CF cache status header; curl -I ile Cache-Control.
    - Fix: /api/auth/*, /api/health için Cache-Control: no-store; CF'de bypass cache.
    - Risk: Yüksek.

12. **N12: Nginx proxy_read_timeout kısa**
    - Semptom: Uzun süren istekte 504; client 5xx görünce mevcut kodda login'e atmıyor (iyi) ama bazı özel handler'lar atabilir.
    - Doğrula: 504 aldığınız istek süresi vs proxy_read_timeout.
    - Fix: 504'te asla auth clear/redirect yapma; timeout'u iş yüküne göre ayarla.
    - Risk: Düşük.

### 4.4 Frontend

13. **N13: BroadcastChannel logout tüm sekmeleri temizliyor**
    - Semptom: S10; bir sekmede logout, diğerinde de login.
    - Neden: Tasarım gereği; ama bir sekmede "session expired" diğerinde hâlâ geçerli token olabilir (senkron gecikme).
    - Doğrula: İki sekme aç; birinde logout; diğerinde token hâlâ var mı (sessionStorage farklı).
    - Fix: BroadcastChannel sadece bilinçli logout'ta kullanılsın; 401'de sadece o sekme redirect, diğer sekmeler bir sonraki istekte 401 alınca temizlensin.
    - Risk: Düşük.

14. **N14: Safari ITP / 3rd party cookie blocking**
    - Semptom: S8 (Safari), cookie ile auth.
    - Neden: Safari cross-site veya 3rd party cookie'leri blokluyor.
    - Doğrula: Safari'de cookie'lerin kaydedilip gönderilmediğini kontrol et.
    - Fix: SameSite=Lax veya Strict; first-party cookie; gerekirse token'ı Authorization header'da taşı (mevcut).
    - Risk: Orta.

15. **N15: Saat kayması (clock skew)**
    - Semptom: JWT kullanılıyorsa S2, S3.
    - Neden: exp/iat client veya sunucu saatine göre yanlış değerlendirilir.
    - Doğrula: JWT exp ile sunucu saati karşılaştır; leeway var mı.
    - Fix: JWT'de leeway (örn. 30s); veya opaque token kullan (mevcut session tabanlı).
    - Risk: Düşük (opaque token'da yok).

### 4.5 Backend

16. **N16: auth_sessions tablosu yok veya migrate edilmemiş**
    - Semptom: S2, S3 (özellikle multi-worker).
    - Neden: Kod DB'ye yazıyor ama tablo yok; exception → memory fallback; memory worker'a özel.
    - Doğrula: DB'de auth_sessions var mı; migration çalıştı mı.
    - Fix: Schema guard / migration ile auth_sessions oluştur.
    - Risk: Yüksek.

17. **N17: require_auth sırası / exception**
    - Semptom: 401 yerine 500; client 500'de farklı davranıyor olabilir.
    - Neden: require_auth içinde exception fırlıyor; yakalanmıyor.
    - Doğrula: 401 beklenen istekte 500 dönüyor mu; log'da traceback.
    - Fix: Tüm auth hatalarını HTTPException(401, detail=...) ile dön; exception handler'da 500'e düşürme.
    - Risk: Orta.

18. **N18: Çoklu worker'da session sadece memory'de**
    - Semptom: S2; bazen çalışır bazen 401.
    - Neden: Worker A'da login; session A'nın memory'sinde; istek Worker B'ye giderse B'de session yok.
    - Doğrula: auth_sessions DB'ye yazılıyor mu; birden fazla worker ile test.
    - Fix: Session'ı her zaman DB'de tut (auth_sessions); memory sadece fallback.
    - Risk: Yüksek.

19. **N19: Token hash farklı encoding**
    - Semptom: Nadir 401.
    - Neden: token_hash hesaplanırken encoding farkı (UTF-8 vs bytes).
    - Doğrula: Aynı token ile _token_hash(client) ve DB'deki hash aynı mı.
    - Fix: Token'ı tek encoding (UTF-8) ile hash'le; test ile doğrula.
    - Risk: Düşük.

20. **N20: Sliding TTL güncellemesi başarısız**
    - Semptom: Uzun oturumda beklenmedik logout.
    - Neden: UPDATE auth_sessions SET expires_at ... fail ediyor; transaction rollback.
    - Doğrula: DB log; last_seen_at/expires_at column var mı.
    - Fix: UPDATE hatalarında session'ı silmeyin; sadece okumaya devam edin veya optional column kullanın.
    - Risk: Orta.

### 4.6 Ağ ve Hata Yönetimi

21. **N21: Timeout'ta (AbortError) redirect**
    - Semptom: Yavaş ağda login'e atma.
    - Neden: apiClient timeout'ta AbortError fırlatıyor; eski kodda 401 gibi işlenip redirect edilmiş olabilir.
    - Doğrula: Timeout'ta redirect yapılıyor mu (kod incelemesi).
    - Fix: AbortError/TimeoutError'da asla clearAuth veya redirect yapma; sadece APIError fırlat.
    - Risk: Yüksek.

22. **N22: 502/503/504'te redirect**
    - Semptom: S9.
    - Neden: 5xx'i "session bitti" sanıp redirect.
    - Doğrula: Mevcut apiClient'da 502/503/504 için redirect var mı.
    - Fix: 5xx'te login'e yönlendirme; toast + server back checker (mevcut davranış doğru).
    - Risk: Yüksek.

23. **N23: Network error (fetch fail) ile redirect**
    - Semptom: İnternet kesilince login.
    - Neden: catch bloğunda genel "redirect to login" kodu.
    - Doğrula: TypeError / Failed to fetch durumunda ne yapılıyor.
    - Fix: Ağ hatalarında (status 0, NETWORK_ERROR) redirect yapma; toast + server back checker.
    - Risk: Yüksek.

24. **N24: Refresh token yok; access token kısa TTL**
    - Semptom: Kısa süre sonra S2 (ileride JWT/access kullanılırsa).
    - Neden: Sadece access token var; TTL kısa; refresh olmayınca sürekli login.
    - Doğrula: Token TTL ve refresh endpoint kullanımı.
    - Fix: Uzun TTL veya refresh token ile rotation; single-flight refresh.
    - Risk: Orta.

### 4.7 Diğer

25. **N25: CORS preflight cache**
    - Semptom: S8, belirli tarayıcı.
    - Neden: Preflight 24 saat cache'lenir; sonradan header değişince credential gönderilmez.
    - Doğrula: Preflight response Access-Control-Max-Age ve header değişikliği.
    - Fix: Gerekli header'ları minimal tutun; Max-Age düşük veya bypass.
    - Risk: Düşük.

26. **N26: iframe içinde cookie**
    - Semptom: Uygulama iframe'de açılıyorsa S1, S8.
    - Neden: SameSite=Strict/Lax iframe cross-origin'de cookie göndermez.
    - Doğrula: iframe src ve site origin.
    - Fix: iframe kullanmayın veya SameSite=None; Secure (HTTPS zorunlu).
    - Risk: Orta.

27. **N27: Form resubmit / back button**
    - Semptom: S3 (sayfa yenilemede POST resubmit).
    - Neden: Login POST'tan sonra redirect GET değilse; back ile POST tekrarlanır.
    - Doğrula: Login sonrası 302 Location / GET dashboard mı.
    - Fix: Login başarıda 302 redirect veya client-side location.replace GET sayfasına.
    - Risk: Düşük.

28. **N28: Rate limit 429 login'de**
    - Semptom: Çok denemede login sayfasında 429; yanlışlıkla "session expired" gibi işlenip başka sayfaya atma.
    - Neden: 429 response'u 401 gibi handle.
    - Doğrula: 429'da redirect veya clearAuth var mı.
    - Fix: 429'da sadece toast; login sayfasında kal.
    - Risk: Düşük.

29. **N29: request_id / error_id eksik**
    - Semptom: Destek/debug zor.
    - Neden: 401/500 response'da request_id veya error_id yok.
    - Doğrula: Tüm hata response'larında detail.request_id ve error_code var mı.
    - Fix: _detail_std ile her 401/403'te request_id ekle; error_id opsiyonel (UUID).
    - Risk: Düşük.

30. **N30: localStorage.boot_id yanlış temizleniyor**
    - Semptom: 401 sonrası tekrar girişte boot_id uyumsuzluğu (eğer backend boot_id kontrolü yapıyorsa).
    - Neden: clearAuthAndBroadcast localStorage boot_id'i siliyor; yeni login'de yeni boot_id; eski session'lar farklı boot'ta kalabilir.
    - Doğrula: Backend'de boot_id hâlâ session validation'da kullanılıyor mu (mevcut kodda _session_get boot_id filtrelemiyor).
    - Fix: Backend'de boot_id'i session geçerliliği için zorunlu tutmayın (multi-worker/restart uyumu); veya boot_id'i sadece bilgi amaçlı kullanın.
    - Risk: Düşük.

---

## 5. Frontend Auth State Machine

### 5.1 Durumlar

- **unauthenticated:** Token yok; login sayfasında veya korumalı sayfaya token olmadan gelindi.
- **authenticating:** Login/register isteği gönderildi; yanıt bekleniyor.
- **authenticated:** Token var; API çağrıları Authorization ile yapılıyor.
- **refreshing:** Token yenileme (refresh endpoint) çağrıldı; yanıt bekleniyor.
- **expired:** 401 (session error) alındı; oturum sonlandı; redirect veya logout ekranı.
- **locked:** Rate limit veya geçici kilit (ban_until); login denemesi engelli.

### 5.2 Geçişler

| Olay | Kaynak | Hedef | Aksiyon |
|------|--------|-------|---------|
| Token yok + korumalı sayfa | unauthenticated | — | login'e redirect |
| Login POST gönder | unauthenticated | authenticating | — |
| Login 200 | authenticating | authenticated | token/user kaydet; dashboard'a git |
| Login 401/4xx | authenticating | unauthenticated | Hata mesajı; login'de kal |
| Login 5xx / network | authenticating | unauthenticated | Toast; tekrar dene |
| 401 (session error) | authenticated | expired | clearAuth; redirect login |
| 401 (session error) | refreshing | expired | clearAuth; redirect login |
| 403 (BINANCE_AUTH vb.) | authenticated | authenticated | Toast; redirect yok |
| 429 | authenticated | authenticated | Toast; retry_after |
| 502/503/504 | authenticated | authenticated | Toast; server back checker |
| Timeout / AbortError | authenticated | authenticated | Hata fırlat; redirect yok |
| Network error | authenticated | authenticated | Toast; server back checker |
| Tab resume / focus | authenticated | authenticated | Opsiyonel: token validity check (tek istek) |
| BroadcastChannel logout | authenticated | unauthenticated | clearAuth; redirect login |
| Kullanıcı logout tıklar | authenticated | unauthenticated | clearAuthAndBroadcast; redirect login |

### 5.3 Deterministik Kural Tablosu

| response.status | error_code | onLoginPage? | Aksiyon |
|-----------------|------------|--------------|---------|
| 401 | SESSION_NOT_FOUND, UNAUTHORIZED, BOOT_ID_MISMATCH | false | clearAuth; toast; replace(login) |
| 401 | (yukarıdakiler) | true | clearAuth; redirect yok |
| 401 | (diğer) | * | clearAuth; toast; replace(login) (güvenli tarafta kal) |
| 403 | BINANCE_AUTH | * | Toast; redirect yok |
| 403 | FORBIDDEN | * | Toast veya hata; redirect yok (veya yetki sayfasına) |
| 429 | * | * | Toast; redirect yok |
| 502, 503, 504 | * | * | Toast; startServerBackChecker; redirect yok |
| 0 (network) | * | * | Toast; startServerBackChecker; redirect yok |
| AbortError/Timeout | * | * | Throw; redirect yok |

---

## 6. apiClient Sertleştirme

### 6.1 İstek Deduplication (Mevcut)

- Aynı (method, endpoint, body) ile aynı anda birden fazla istek varsa tek Promise dön.
- Key: `getRequestKey(endpoint, method, body)`.
- inFlightRequests Map ile yönetim; istek bitince delete.

### 6.2 401 İşleme Politikası

- **Tek uçuş refresh (single-flight):** Aynı anda birden fazla istek 401 alırsa yalnızca bir kez refresh dene; diğerleri bu refresh Promise'ine bağlansın.
- **Bekleyen istek kuyruğu:** Refresh sürerken gelen 401'li istekler retry kuyruğuna alınsın; refresh başarılı olunca kuyruktakiler yeni token ile tekrar gönderilsin.
- **Retry kuralı:** Sadece 401 (session error) için bir kez refresh + retry; refresh 401/4xx dönerse redirect; 5xx'te bir kez retry (opsiyonel).

### 6.3 Single-Flight Refresh Algoritması (Pseudocode)

```
refreshPromise = null

on 401 (session error):
  if (refreshPromise === null)
    refreshPromise = call POST /api/auth/refresh with current refresh token or cookie
  await refreshPromise
  if (refresh success)
    update token in storage
    retry all queued requests with new token
  else
    clearAuth; redirect login
  refreshPromise = null
```

### 6.4 Token Refresh Fırtınası Önleme

- Aynı anda yalnızca bir refresh isteği (single-flight).
- Refresh endpoint'ine rate limit: örn. dakikada 10 / kullanıcı.
- Backend'de refresh için ayrı rate limit (429 dön).

### 6.5 Ağ Kesintisi Politikası (Network Blip)

- **Kural:** Geçici ağ hatası (timeout, 502, 503, 504, fetch failed) asla kullanıcıyı logout etmez.
- Timeout: AbortError fırlat; catch'te redirect yok.
- 5xx: APIError fırlat; toast + startServerBackChecker; redirect yok.
- status 0 / TypeError: NETWORK_ERROR; toast + startServerBackChecker; redirect yok.

### 6.6 Backoff Stratejisi

- 429 için: Retry-After header varsa o kadar bekle; yoksa exponential backoff (1s, 2s, 4s) max 3 deneme.
- Refresh için: Başarısız refresh'te hemen tekrar deneme; 1 kez retry sonra redirect.

### 6.7 AbortController Kullanımı

- Her istekte timeout için AbortController oluştur; timeout ms sonra abort().
- Sayfa/component unmount'ta mevcut istekleri abort et; late response'u ignore et.
- Refresh sırasında eski istekleri abort etme; sadece yeni token ile retry et.

### 6.8 Hata Normalleştirmesi

- Tüm API hatalarında `{ error_code, error_id?, request_id?, message }` kullan.
- apiClient: response.detail veya response.error'dan oku; APIError constructor'a geçir.
- request_id: X-Request-ID header'dan; yoksa null.

### 6.9 Correlation ID İletimi

- İstekte X-Request-ID gönder (UUID); backend aynı değeri log'da ve response'da kullansın.
- Middleware: request.state.request_id = headers.get("X-Request-ID") or str(uuid.uuid4()).

### 6.10 apiClient İnterceptor Örneği (Fetch Sarmalayıcı) – JS

```javascript
// 401'de tek uçuş refresh + kuyruk (özet)
let refreshPromise = null;
const pendingAfterRefresh = [];

async function apiClientWithRefresh(endpoint, options) {
    const run = async () => {
        const res = await fetch(endpoint, { ...options, headers: { ...options.headers, Authorization: 'Bearer ' + getAuthStorage('token') } });
        if (res.status === 401 && isSessionError(await res.json().catch(() => ({})))) {
            if (!refreshPromise) refreshPromise = doRefresh();
            await refreshPromise;
            refreshPromise = null;
            const newToken = getAuthStorage('token');
            if (newToken) return apiClientWithRefresh(endpoint, { ...options, headers: { ...options.headers, Authorization: 'Bearer ' + newToken } });
            clearAuthAndBroadcast();
            window.location.replace('/ui/login.html');
            throw new APIError({ status: 401, error_code: 'UNAUTHORIZED', message: 'Session expired' });
        }
        return res;
    };
    return run();
}
```

### 6.11 Retry Policy (429) – JS

```javascript
function withRetry(fn, maxRetries = 3) {
    return async function (...args) {
        let lastErr;
        for (let i = 0; i <= maxRetries; i++) {
            try {
                return await fn(...args);
            } catch (e) {
                lastErr = e;
                if (e.status !== 429 || i === maxRetries) throw e;
                const wait = e.retry_after || Math.min(1000 * Math.pow(2, i), 10000);
                await new Promise(r => setTimeout(r, wait));
            }
        }
        throw lastErr;
    };
}
```

### 6.12 Kararlı Auth Store – JS

```javascript
const AUTH_KEYS = ['token', 'user'];
function getStableAuth() {
    const out = {};
    try {
        AUTH_KEYS.forEach(k => { out[k] = sessionStorage.getItem(k); });
    } catch (e) {}
    return out;
}
function setStableAuth(data) {
    try {
        AUTH_KEYS.forEach(k => { if (data[k] != null) sessionStorage.setItem(k, data[k]); });
    } catch (e) {}
}
// Okuma/yazma tek yerden; race yok.
```

---

## 7. Token Stratejisi (JWT / Opaque)

### 7.1 Önerilen Yaklaşım

- **Mevcut sistem:** Opaque token + auth_sessions tablosu (token_hash, user_id, expires_at). Bu yapı multi-worker ve restart için uygundur.
- **Alternatif (ileride):** Access token (kısa TTL, örn. 15 dk) + refresh token (uzun TTL, httpOnly cookie veya güvenli storage); rotation ile.

### 7.2 Rotation Kuralları

- Refresh başarılı olunca eski refresh token geçersiz sayılır (one-time).
- Yeni access + yeni refresh dönülür.
- Eski refresh ile tekrar istek → 401; client login'e yönlendirilir.

### 7.3 Saklama Kuralları

| Yöntem | Artı | Eksi |
|--------|------|------|
| httpOnly cookie | XSS'ten okunamaz | CSRF token gerekir; SameSite dikkat |
| memory (RAM) | XSS'te zor | Sekme kapatılınca kaybolur; refresh gerekir |
| sessionStorage | Sekme bazlı | XSS okur; sekme kapatılınca kaybolur |
| localStorage | Kalıcı | XSS okur; ITP ile sınırlı |

- Access token: Authorization header ile gönder; storage sessionStorage veya memory.
- Refresh token: httpOnly cookie tercih; veya kısa ömürlü sessionStorage.

### 7.4 Safari ITP

- Safari 7 gün kuralı: Cross-site veya script ile set edilen cookie'ler 7 gün sonra silinebilir.
- First-party, SameSite=Lax, kullanıcı etkileşimi ile set edilen cookie daha dayanıklı.
- localStorage/sessionStorage da ITP'den etkilenebilir; kritik state için first-party cookie veya Authorization header kullanın.

### 7.5 Saat Kayması (Leeway)

- JWT kullanılıyorsa exp/iat için 30–60 saniye leeway koyun.
- Opaque token'da sunucu tarafında expires_at (DB) kullanıldığı için sunucu saati tek kaynak; ek leeway gerekmez.

### 7.6 Token İntrospection / İptal Listesi

- Opaque: auth_sessions'dan silerek iptal.
- JWT: Blacklist (redis) veya kısa TTL; kritik işlemlerde DB'de son şifre değişikliği / cihaz listesi kontrolü.

### 7.7 TTL Öneri Tablosu

| Token tipi | TTL öneri | Not |
|------------|------------|-----|
| Session (opaque) | 7 gün | Sliding TTL |
| Access (JWT) | 15 dk | Refresh ile |
| Refresh | 7 gün | Rotation ile |
| Cookie auth_token | 7 gün | httpOnly, SameSite=Lax |

---

## 8. Cookie Stratejisi

### 8.1 Secure, HttpOnly, SameSite Karar Matrisi

| Senaryo | Secure | HttpOnly | SameSite |
|---------|--------|----------|-----------|
| Auth cookie (first-party) | true (prod) | true | Lax |
| Cross-site / iframe | true | true | None (HTTPS zorunlu) |
| Sadece API (Bearer) | — | — | Cookie kullanmayın |

### 8.2 Domain / Path

- Domain: Sadece mevcut domain (set etmeyin veya `.example.com` sadece subdomain paylaşımı gerekiyorsa).
- Path: `/` veya `/api` (API için).

### 8.3 Cross-Site ve iframe

- SameSite=None: Sadece cross-site isteklerde cookie gerekirse; Secure zorunlu.
- iframe'de first-party olmayan site cookie gönderemez; mümkünse iframe kullanmayın.

### 8.4 Cloudflare / Nginx Header Geçişi

- Nginx: `proxy_cookie_path / /;` ile path'i aynı bırakın.
- Set-Cookie'yi proxy'de değiştirmeyin; backend'in gönderdiği gibi iletin.
- Cloudflare: "Strip Set-Cookie" kapalı olsun.

### 8.5 Set-Cookie Örnekleri

```
Set-Cookie: auth_token=xxx; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=604800
Set-Cookie: refresh_token=yyy; Path=/api/auth; HttpOnly; Secure; SameSite=Strict; Max-Age=604800
```

---

## 9. CSRF ve CORS

### 9.1 CSRF

- Cookie ile auth kullanıyorsanız: CSRF token (form veya header) zorunlu.
- SameSite=Lax ile GET dışı isteklerde cross-site cookie gönderilmez; Lax yeterli olabilir.
- State-changing isteklerde: Custom header (örn. X-Requested-With: XMLHttpRequest) veya CSRF token body/header.

### 9.2 CORS Tam Konfig (Dev / Prod)

- Allow-Origin: Production'da tek origin (https://app.example.com); dev'de http://localhost:8080 vb.
- Allow-Credentials: true (cookie/Authorization kullanıyorsanız).
- Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS.
- Allow-Headers: Authorization, Content-Type, X-Request-ID, X-CSRF-Token (gerekirse).
- Expose-Headers: X-Request-ID.

### 9.3 Preflight Cache ve Tuzaklar

- Tarayıcı OPTIONS yanıtını cache'ler (Max-Age).
- Header eklediğinizde preflight yeniden gönderilir; eski cache yanlış header ile devam edebilir.
- Gerekli header'ları sabit tutun; Max-Age düşük (örn. 600) veya 0.

### 9.4 Debug curl Komutları

```bash
# Preflight
curl -X OPTIONS -i -H "Origin: https://yourapp.com" -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: Authorization" https://api.yourapp.com/api/auth/login

# Login (form/json)
curl -X POST -i -H "Content-Type: application/json" -d '{"phone":"+90...","password":"..."}' https://api.yourapp.com/api/auth/login

# Cookie ile korumalı endpoint
curl -i -H "Cookie: auth_token=YOUR_TOKEN" https://api.yourapp.com/api/dashboard/snapshot

# Bearer ile
curl -i -H "Authorization: Bearer YOUR_TOKEN" https://api.yourapp.com/api/dashboard/snapshot
```

---

## 10. Reverse Proxy ve CDN (Nginx + Cloudflare)

### 10.1 Logout Döngüsüne Yol Açan Yaygın Hatalar

- Auth endpoint'lerini cache'lemek.
- Authorization veya Cookie header'ını iletmemek.
- Set-Cookie'yi strip etmek.
- 401/302 response'ları cache'lemek.

### 10.2 Cache Kuralları

- /api/auth/* → Cache bypass; Cache-Control: no-store.
- /api/health → Kısa cache veya bypass.
- /api/* (diğer) → no-store veya private, max-age=0 (API için).

### 10.3 Header İletimi

- proxy_set_header Authorization $http_authorization;
- proxy_set_header Cookie $http_cookie;
- proxy_set_header Host $host;
- proxy_set_header X-Real-IP $remote_addr;
- proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
- proxy_set_header X-Forwarded-Proto $scheme;
- proxy_set_header X-Request-ID $request_id;  # Nginx'te set $request_id ...;

### 10.4 WebSocket ve Keepalive

- WebSocket kullanıyorsanız Upgrade ve Connection header'ları iletin.
- Uzun keepalive timeout'ları 502/504 riskini artırır; makul değerler kullanın.

### 10.5 Zaman Aşımı ve 502/524/522

- 502: Backend yanıt vermedi; proxy_next_upstream ve timeout kontrolü.
- 524: Cloudflare origin timeout; origin'deki yavaş yanıt.
- 522: Cloudflare connection failed; origin kapalı veya unreachable.
- Bu durumlarda client tarafında login'e atma; sadece "sunucuya ulaşılamıyor" mesajı.

### 10.6 Nginx Snippet Örnekleri

```nginx
location /api/ {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $req_id;
    proxy_read_timeout 30s;
    proxy_connect_timeout 10s;
    proxy_send_timeout 30s;
    proxy_cache off;
    add_header Cache-Control "no-store, no-cache";
}

location /api/auth/ {
    proxy_pass http://backend;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_cache off;
    add_header Cache-Control "no-store";
}
```

### 10.7 proxy_cookie_path

```nginx
proxy_cookie_path / /;
# Cookie domain'ini değiştirmek (ör. subdomain):
# proxy_cookie_domain backend.example.com .example.com;
```

---

## 11. Backend Auth Middleware (FastAPI)

### 11.1 Middleware Sırası

1. CORS (en dış).
2. Request ID (X-Request-ID oluştur veya oku; request.state.request_id).
3. Logging / timing.
4. Auth dependency (route seviyesinde): require_auth, require_admin_auth.

### 11.2 Exception → Yapılandırılmış Hata

- HTTPException(401, detail={ "error_code": "UNAUTHORIZED", "message": "...", "request_id": request.state.request_id }).
- Tüm 401/403'te _detail_std kullanın; error_id opsiyonel (UUID).

### 11.3 401 vs 403 Semantiği

- 401: Kimlik doğrulanmamış (token yok veya geçersiz); "Giriş yapın".
- 403: Kimlik doğrulanmış ama yetki yok; "Bu işlemi yapma yetkiniz yok".
- Login sayfasına yalnızca 401'de yönlendirme; 403'te yönlendirme yok.

### 11.4 Refresh Endpoint Tasarımı

- POST /api/auth/refresh.
- Body: boş veya { "refresh_token": "..." }; veya Cookie: refresh_token.
- Yanıt: 200 { "token": "yeni_access", "expires_at": "..." } veya 401.
- Rate limit: dakikada 10 / IP veya / user.

### 11.5 Login / Refresh Rate Limiting

- Login: dakikada 5 deneme / IP; 429 + Retry-After.
- Refresh: dakikada 20 / user; 429.

### 11.6 Brute Force Koruması

- Yanlış şifre: 5 denemeden sonra geçici kilitle (örn. 15 dk) veya CAPTCHA.
- IP tabanlı: BannedIP tablosu; süre sonunda otomatik kalkar.

### 11.7 Şifre Hash (argon2/bcrypt), Pepper, Salt

- bcrypt (mevcut) kabul edilir; cost factor 12+.
- Argon2id tercih edilebilir (yeni sistemlerde).
- Salt her kullanıcı için unique (bcrypt zaten kullanıyor).
- Pepper: env'den alınan global secret; hash'ten önce şifreye eklenebilir (opsiyonel).

### 11.8 Session Fixation Önleme

- Login başarıda yeni token üret; eski token'ı geçersiz kıl.
- Session ID'yi URL'de taşımayın.

### 11.9 Hesap Kilitleme

- 5 yanlış şifre: 15 dk kilitle veya e-posta/SMS ile açma.
- Kilidi audit log'a yazın.

### 11.10 FastAPI Auth Dependency Örneği – Python

```python
from fastapi import Depends, Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)

async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    if not token:
        token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(401, detail=_detail_std(request, "UNAUTHORIZED", "Giriş yapmanız gerekiyor"))
    session = _session_get(token, db)
    if not session:
        raise HTTPException(401, detail=_detail_std(request, "SESSION_NOT_FOUND", "Oturum geçersiz. Tekrar giriş yapın."))
    return session
```

### 11.11 Refresh Endpoint İskelet – Python

```python
@router.post("/api/auth/refresh")
async def refresh(
    request: Request,
    db: Session = Depends(get_db),
):
    # Rate limit burada veya middleware
    refresh_token = request.cookies.get("refresh_token") or (await request.json()).get("refresh_token")
    if not refresh_token:
        raise HTTPException(401, detail=_detail_std(request, "UNAUTHORIZED", "Refresh token gerekli"))
    session = _session_get(refresh_token, db)  # veya ayrı refresh_sessions tablosu
    if not session:
        raise HTTPException(401, detail=_detail_std(request, "SESSION_NOT_FOUND", "Oturum sonlanmış"))
    new_token = secrets.token_urlsafe(32)
    _session_set(new_token, session["user_id"], session["account_id"], session["is_admin"], session.get("device_id"), db)
    _session_drop_by_token(refresh_token, db)  # rotation
    return {"token": new_token, "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat()}
```

### 11.12 Hata Normalleştirme – Python

```python
def _detail_std(request: Optional[Request], error_code: str, message: str, error_id: Optional[str] = None) -> dict:
    detail = {"error_code": error_code, "message": message}
    if request and getattr(request.state, "request_id", None):
        detail["request_id"] = request.state.request_id
    if error_id:
        detail["error_id"] = error_id
    return detail
```

---

## 12. Doğrulama Kuralları

### 12.1 E-posta / Şifre Kuralları

- Şifre: en az 10 karakter; büyük/küçük harf, rakam, noktalama (mevcut validate_password_strength).
- E-posta: format doğrulama; normalize (lowercase, trim).
- Telefon: uluslararası format; leading zero / boşluk temizleme.

### 12.2 Girdi Normalleştirme

- NFC normalizasyon (mevcut _normalize_password).
- Trim; max length (DB ve API'de).

### 12.3 Hata Mesajları (Enumeration Yok)

- "Telefon veya şifre hatalı" (kullanıcı var mı yok mu belli etmeyin).
- "Giriş yapmanız gerekiyor" (401).
- "Bu işlem için yetkiniz yok" (403).

### 12.4 i18n Güvenli Kalıplar

- Mesajlar şablon olsun; parametreler escape edilsin.
- Hata kodları sabit; çeviri key'leri error_code ile eşlensin.

---

## 13. Şifreleme ve Sırlar

### 13.1 TLS

- Production'da HTTPS zorunlu; Secure cookie ve HSTS.
- TLS 1.2 minimum; 1.3 tercih.

### 13.2 Rest’te Şifreleme

- DB'de hassas alanlar (API secret vb.) Fernet ile şifreli (mevcut encryption.py).
- Şifre hash'leri bcrypt/argon2; plaintext saklanmaz.

### 13.3 Sır Saklama (Env / Vault)

- API key, DB URL, secret key: ortam değişkeni veya vault.
- .env dosyası .gitignore'da; .env.example şablon (değer yok).

### 13.4 Anahtar Rotasyon Planı

- Fernet key rotasyonu: yeni key ile encrypt; eski key ile decrypt (dual key dönemi) sonra eski key kaldırılır.
- Session secret: değişince tüm session'lar geçersiz; bakım penceresinde yapılır.

---

## 14. Loglama, Metrikler, İzleme

### 14.1 Log Şeması

- request_id: Her istekte; log satırında aynı.
- user_id: Auth sonrası (hash'lenmiş veya ID).
- session_id: Token hash'inin ilk 8 karakteri (tam hash loglanmaz).
- error_id: Hata için UUID (opsiyonel).
- Örnek: `request_id=abc user_id=42 session_id=a1b2c3d4 error_code=SESSION_NOT_FOUND`

### 14.2 Metrik İsimleri

- auth_login_success_total (counter)
- auth_login_fail_total (counter; label: reason)
- auth_refresh_success_total (counter)
- auth_refresh_fail_total (counter)
- auth_401_total (counter; label: error_code)
- auth_session_expired_total (counter)
- auth_middleware_latency_seconds (histogram)

### 14.3 Dashboard ve Uyarılar

- Grafana: auth_401_total artışı; auth_refresh_fail_total > 0.
- Alert: 5 dk içinde auth_401_total > 100 veya auth_refresh_fail_total > 50.
- Log: request_id ile trace; error_id ile destek araması.

---

## 15. Üretim Ortamı Çoğaltma Playbook’u

### 15.1 Adım Adım (Genel Döngü)

1. Tarayıcıda login ol; token al.
2. Dashboard'a git; birkaç istek 200 dönüyor mu kontrol et.
3. Session'ı backend'den sil (auth_sessions DELETE) veya token'ı değiştir.
4. Sonraki istekte 401 beklenir; tek redirect login'e.
5. Login sayfasında iken tekrar 401 tetikleme (örn. token ile istek); loop olmamalı (onLoginPage kontrolü).

### 15.2 Tarayıcıya Özel

- **Safari:** Cookie'leri kapat/aç; ITP testi; private window.
- **Chrome:** Incognito; farklı profiller.
- **Mobil:** iOS Safari, Android Chrome; arka plana alıp geri gelme.

### 15.3 Çok Sekme

- Sekme A: logout; Sekme B: bir API çağrısı yap; 401 alıp login'e gitmeli.
- Sekme B: logout; Sekme A: zaten login'de veya bir sonraki istekte 401.

### 15.4 Sleep / Wake

- Laptop/telefon uykuya alsın; 5 dk sonra uyandır; sayfa yenilemeden bir istek tetikle; token hâlâ geçerliyse 200.

---

## 16. Düzeltme Uygulama Planı

### 16.1 Faz 0 – Acil Yama (Güvenli Az Müdahale)

- 5xx ve timeout'ta asla redirect/clearAuth olmadığını doğrula (kod incelemesi).
- Login sayfasında korumalı API çağrısı yapılmadığını doğrula.
- 401 redirect'i sadece isSessionError + !onLoginPage ile sınırla.
- Nginx/Cloudflare'de auth path'lerinde cache kapalı ve header iletimi doğru olsun.
- Dosyalar: ui/assets/core/apiClient.js, Nginx config, Cloudflare rules.
- Test: Manuel 401, 502, timeout senaryoları.
- Rollback: Config ve JS geri al; deploy.

### 16.2 Faz 1 – Doğru Düzeltme

- auth_sessions tablosunu her ortamda kullan; memory sadece fallback.
- apiClient: single-flight refresh (refresh endpoint varsa) ve retry kuyruğu ekle.
- Tüm 401/403 response'larında request_id ve error_code standart format.
- CORS ve cookie ayarlarını prod’a göre netleştir.
- Dosyalar: app/api/auth.py, app/db/schema_guard veya migrations, ui/assets/core/apiClient.js.
- Test: Birim + entegrasyon + manuel çok sekme / Safari.
- Rollback: Feature flag ile refresh’i kapat; eski apiClient branch’i.

### 16.3 Faz 2 – Sertleştirme

- Refresh token rotation; httpOnly cookie opsiyonu.
- Rate limit login/refresh; brute force lockout.
- Metrik ve log şeması; alert kuralları.
- OWASP ASVS tarzı kontrol listesi (aşağıda).
- Rollback: Özellik bayrakları; cookie migration geri alımı (localStorage’a geri dönme planı).

---

## 17. Test Planı

### 17.1 Birim Testleri

- _session_get / _session_set: token hash, TTL, DB ve memory fallback.
- _detail_std: request_id ve error_code içeriyor mu.
- validate_password_strength: geçerli/geçersiz şifreler.
- require_auth: token yok, token geçersiz, token geçerli → 401/200.

### 17.2 Entegrasyon Testleri

- POST /api/auth/login → 200 + token; sonra GET korumalı endpoint → 200.
- Geçersiz token ile GET → 401 + detail.error_code.
- auth_sessions’a yazılan session farklı worker’dan okunabiliyor mu (multi-worker test).

### 17.3 E2E Testleri

- Login → dashboard → logout → login sayfasında kal.
- Login → 401 simüle (backend session sil) → bir istek → login’e yönlendir.
- Login sayfasındayken 401 tetikleme → loop yok.

### 17.4 Manuel Kontrol Listesi

- [ ] Login sonrası dashboard yükleniyor.
- [ ] F5 ile sayfa yenilemede logout olmuyor.
- [ ] 502/503/504’te login’e atılmıyor; toast görünüyor.
- [ ] Timeout’ta login’e atılmıyor.
- [ ] Bir sekmede logout; diğer sekme bir sonraki istekte login’e gidiyor.
- [ ] Safari’de cookie/auth çalışıyor (cookie kullanıyorsanız).

### 17.5 Auth Endpoint’leri Yük Testi

- Login: saniyede 10 istek; 429 ve rate limit davranışı.
- Refresh: eşzamanlı 50 istek; tek uçuş davranışı (backend’de tek refresh).

---

## 18. Rollback Planı

### 18.1 Feature Bayrakları

- USE_SINGLE_FLIGHT_REFRESH: true/false; false iken eski 401 davranışı (hemen redirect).
- AUTH_USE_DB_SESSIONS: true/false; false iken sadece memory (tek worker için).

### 18.2 Refresh Politikasını Kapatma

- Bayrak ile refresh denemesi kapatılsın; 401’de doğrudan redirect (eski davranış).

### 18.3 Cookie Migration Geri Alımı

- localStorage token’a geçiş yapıldıysa: geri alımda tekrar localStorage oku; cookie’yi yok say.
- Backend aynı anda hem cookie hem Authorization kabul ediyorsa, client’ı eski sürüme döndürmek yeterli.

---

## 19. Yapılmış Kontrol Listesi (Done Checklist)

- [ ] Tüm 401’de redirect sadece isSessionError + !onLoginPage.
- [ ] 5xx, timeout, network error’da hiç clearAuth/redirect yok.
- [ ] auth_sessions DB kullanılıyor; memory sadece fallback.
- [ ] Nginx’te Authorization ve Cookie header iletimi var.
- [ ] Cloudflare’de /api/auth/* cache kapalı; Set-Cookie strip yok.
- [ ] CORS credentials true; origin tek (prod).
- [ ] Hata formatı: error_code, request_id (ve isteğe bağlı error_id).
- [ ] Login/refresh rate limit ve brute force koruması tanımlı.
- [ ] Log ve metrik şeması uygulandı; en az bir alert tanımlı.
- [ ] Rollback adımları ve feature flag’ler dokümante.
- [ ] E2E veya manuel “redirect loop” senaryosu yeşil.

---

## 20. Ek: Yaygın “Redirect Loop” Diyagramı ve Kırma

```
[Sayfa yükle] → [Script çalışır] → [Korumalı API çağrısı]
       ↑                                    |
       |                                    v
       |                             [401 dönüyor]
       |                                    |
       |                             [clearAuth + redirect login]
       |                                    |
       |                                    v
       |                            [login.html yüklenir]
       |                                    |
       |                            [Login sayfası script’i yine korumalı API çağırıyor]
       |                                    |
       +------------------------------------+
```

**Kırma:** Login sayfasında hiç korumalı API çağrısı yapma. Veya 401’de redirect yaparken “şu an login sayfasındayız” kontrolü (onLoginPage) ile login sayfasındayken redirect’i atlama.

---

## 21. Yapılmaması Gereken Anti-Pattern’ler (En Az 20 Madde)

1. Her 401’de koşulsuz login’e yönlendirme (login sayfası dahil).
2. 502/503/504’te session temizleyip login’e atma.
3. Timeout (AbortError) veya network hatasında clearAuth çağırma.
4. 403’ü 401 gibi işleyip login’e atma.
5. Token’ı URL query’de taşımak (referrer, log sızıntısı).
6. Auth endpoint’lerini (login, refresh, logout) cache’lemek.
7. Nginx’te Authorization header’ı iletmemek.
8. CORS’ta Allow-Origin: * ile credentials: true kullanmak.
9. Cookie’de SameSite=None kullanırken Secure olmadan kullanmak.
10. Şifreyi log’a veya response body’de yazmak.
11. Session’ı sadece memory’de tutup çoklu worker kullanmak.
12. Login sayfasına gelen script’in korumalı API çağırması.
13. Refresh token’ı localStorage’da saklamak (XSS riski).
14. Rate limit olmadan login/refresh endpoint’leri.
15. Hata mesajında “bu e-posta kayıtlı değil” gibi enumeration.
16. JWT’de kritik yetki bilgisini client’a koyup doğrulamadan inanmak.
17. Set-Cookie’yi Cloudflare’de strip etmek (cookie auth kullanıyorsanız).
18. Preflight’ta gereksiz header ekleyip sık değiştirmek (cache tutarsızlığı).
19. Eski token’ı refresh başarılı olduktan sonra hâlâ kabul etmek (rotation yok).
20. Audit log tutmadan hesap kilitleme / şifre sıfırlama yapmak.
21. Backend’de exception’ı yakalamayıp 500 dönmek (401 yerine).
22. Frontend’de “her hata = session bitti” varsayımı.

---

## 22. localStorage Token’dan httpOnly Cookie’ye Geçiş Planı

### 22.1 Hedef

- Token’ı httpOnly cookie’de saklamak; XSS’te okunamaz.
- CSRF token veya SameSite=Lax ile güvenli state-changing istekler.

### 22.2 Adımlar

1. Backend: Login/refresh yanıtında Set-Cookie (auth_token) ekle; yanıtta body’de token dönmeye devam et (geçiş dönemi).
2. Frontend: Önce cookie’yi okuyamaz; Authorization header için body’deki token’ı kullanmaya devam et.
3. Backend: Hem Cookie hem Authorization kabul et; Cookie varsa onu kullan.
4. Frontend: Token’ı artık sessionStorage’a yazma; sadece “giriş yapıldı” bilgisi tut; API çağrılarında credentials: 'include' ile cookie gönderilsin.
5. Backend: Login/refresh response’dan body’deki token’ı kaldır (opsiyonel); sadece Set-Cookie.
6. Feature flag: USE_COOKIE_AUTH; false iken eski davranış.
7. Rollback: USE_COOKIE_AUTH=false; backend yine body’de token dönsün; frontend localStorage/sessionStorage’a yazsın.

### 22.3 Risk

- Cookie domain/path yanlışsa bazı isteklerde cookie gönderilmez; test tüm sayfa ve alt path’lerde yapılmalı.

---

## 23. Güvenlik Sertleştirme (OWASP ASVS Tarzı Aksiyonlar)

- Şifre hash: bcrypt cost 12+ veya Argon2id.
- Login/register rate limit: IP ve kullanıcı bazlı.
- 5 yanlış şifre: geçici kilitle veya CAPTCHA.
- Tüm auth hatalarında standart mesaj; enumeration yok.
- Session fixation: login’de yeni token; eski iptal.
- Session timeout: sliding TTL; makul max (örn. 7 gün).
- HTTPS zorunlu; Secure cookie.
- HttpOnly cookie (token cookie ise).
- CSRF: SameSite veya token.
- Audit log: login başarı/başarısız, logout, şifre değişikliği, kilitleme.
- Hassas veri (API key) log’da ve response’da yer almasın.
- İptal: logout’ta session sil; “tüm cihazlardan çıkış” seçeneği.

---

## 24. Tehdit Modeli (Auth/Session)

### 24.1 Tehditler

- **Token çalınması (XSS):** sessionStorage’daki token script ile okunabilir; httpOnly cookie veya kısa TTL + refresh ile azaltılır.
- **Token çalınması (MITM):** HTTPS zorunlu; certificate doğru.
- **CSRF:** SameSite=Lax veya CSRF token ile state-changing istekler korunur.
- **Session fixation:** Login’de yeni token üretilir.
- **Brute force:** Rate limit ve kilitleme.
- **Yetkisiz erişim:** 403; token geçerli ama kaynak yetkisi yok.
- **Döngü / DoS:** 401 loop ile sayfa sürekli yüklenir; onLoginPage ve tek redirect ile kırılır.

### 24.2 Kabul Edilen Riskler

- sessionStorage kullanımı: XSS olursa token okunabilir; CSP ve input sanitization ile azaltılır.
- Çoklu sekme: Bir sekmede logout diğerlerini de çıkışır (BroadcastChannel); kabul edilebilir.

---

## 25. Olay Playbook’u: Kullanıcılar Login’e Atıldığında

### 25.1 Hızlı Kontrol

1. Son deploy ve config değişikliği var mı?
2. auth_401_total veya auth_refresh_fail_total metrikleri yükselmiş mi?
3. Cloudflare/Nginx cache veya header değişikliği?
4. Belirli tarayıcı/cihaz mı (Safari, mobil)?

### 25.2 Geçici Azaltma

- 401’de redirect’i feature flag ile kapatmak (kullanıcı hata görür ama loop olmaz).
- Cloudflare’de cache bypass auth path’leri için zorla.
- Nginx’te Authorization header’ının iletildiğini doğrula.

### 25.3 Kök Neden

- Log’da request_id ile 401’leri incele; error_code SESSION_NOT_FOUND mu, UNAUTHORIZED mı?
- auth_sessions tablosu var mı; migration çalıştı mı?
- Çoklu worker’da session tek worker’da mı kaldı?

### 25.4 İletişim

- Kullanıcıya: “Oturum güvenliği güncellemesi yapıldı; lütfen tekrar giriş yapın” (gerekirse).
- İç ekip: Kök neden ve yapılan değişiklik özeti.

---

*Bu playbook, trade engine mantığına dokunmaz; yalnızca auth/oturum katmanı ve istemci tarafı işleme odaklanır. Tüm değişiklikler mevcut apiClient ve hata standardı (error_code, error_id, request_id) ile uyumludur.*
