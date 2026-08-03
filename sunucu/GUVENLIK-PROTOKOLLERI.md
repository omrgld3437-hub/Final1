# Final1 Sunucu Güvenlik Protokolleri

Bu belge Final1 projesini tek sunucuda, Aysegul projesiyle birlikte çalıştırırken uygulanacak güvenlik mimarisini ve kontrol listesini açıklar.

## En Önemli Gerçeklik Sınırı

Klasik VPS veya kiralık sunucuda root yetkisi olan sunucu sahibi veya hosting operatörü şu verilere teknik olarak erişebilir:

- Çalışan proses belleği.
- Diskteki veritabanı, yedekler ve loglar.
- systemd environment dosyaları.
- Uygulama başlatılırken çözülen secret değerleri.
- Ağ trafiğinin sunucuya ulaştıktan sonraki açık hali.

Bu nedenle “sunucu sahibi hiçbir önemli bilgiyi göremesin” hedefi, sıradan VPS üzerinde mutlak olarak sağlanamaz. Profesyonel hedef şudur: erişim yüzeyini küçültmek, gizli bilgileri en az tutmak, secret değerleri döndürülebilir yapmak, root dışı çalışma ve dış servislerle kritik anahtarları ayrıştırmak.

## Kaynak Standartlar

Bu protokol aşağıdaki güncel ve güvenilir kaynakların ilkeleriyle hizalanmıştır:

- OWASP Transport Layer Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html
- OWASP Web Service Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Web_Service_Security_Cheat_Sheet.html
- OWASP Secrets Management Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
- NIST Cybersecurity Framework: Identify, Protect, Detect, Respond, Recover: https://www.nist.gov/cyberframework/csf-11-five-functions
- Cloudflare Tunnel dokümantasyonu: https://developers.cloudflare.com/tunnel/
- OpenSSH `ssh` kılavuzu, yerel port yönlendirme ve agent forwarding uyarıları: https://man.openbsd.org/ssh

## Mevcut Uygulanan Tedbirler

- Final1 ayrı systemd servisleriyle çalışıyor: `final1-web`, `final1-worker`, `final1-manager`.
- Aysegul ayrı servis olarak aktif kalıyor.
- Final1 servisleri root yerine `final1` kullanıcısıyla çalışacak şekilde kuruldu.
- Uygulama verileri `/var/lib/final1` altında tutuluyor.
- Gizli ortam değişkenleri `/etc/final1/final1.env` altında tutuluyor.
- Loglar `/var/log/final1` altında ayrıldı.
- systemd tarafında servis izolasyonu kullanılıyor: `NoNewPrivileges`, `PrivateTmp`, `ProtectHome`, `ProtectSystem`, `ReadWritePaths`.
- Nginx üzerinden iki proje aynı sunucuda ayrı portlarla çalışıyor.
- Yerel erişim için SSH tüneli hazırlanıyor; bu model yayın açılmadan güvenli erişim sağlar.
- Sunucu durum paneli sadece `127.0.0.1` üzerinde çalışır ve gizli bilgi göstermez.

## Ek Sertleştirme Hedefleri

### 1. Root Yerine Sınırlı Deploy Kullanıcısı

Mevcut bağlantı root anahtarıyla yapılabiliyor. Uzun vadede şu model daha güvenlidir:

- `deploy-final1` adında ayrı kullanıcı.
- Sadece `/opt/final1`, `/var/lib/final1` ve `final1-*` servisleri için sınırlı sudo.
- `PermitRootLogin no`.
- `PasswordAuthentication no`.
- SSH sadece anahtar ile.
- Anahtarlar cihaz bazlı ve parolalı.

Root SSH kapatma işlemi kilitlenme riski doğurduğu için otomatik uygulanmamalıdır. Önce ikinci bir yönetici erişimi doğrulanmalı, sonra değişiklik yapılmalıdır.

### 2. Cloudflare Tunnel Tercihi

En iyi dış yayın modeli Cloudflare Tunnel’dır:

- Sunucuda public inbound uygulama portu açılmaz.
- `cloudflared` sunucudan Cloudflare’a outbound bağlantı kurar.
- Alan adı Cloudflare üzerinden uygulamaya yönlenir.
- Cloudflare Access ile ek kimlik doğrulama katmanı eklenebilir.

Bu model sunucu sahibini tamamen engellemez; fakat dış dünyadan saldırı yüzeyini belirgin biçimde azaltır.

### 3. TLS ve Tarayıcı Güvenliği

- Dış erişim HTTPS olmalı.
- TLS 1.2 ve TLS 1.3 dışındaki protokoller kapalı olmalı.
- HTTPS kalıcı hale geldikten sonra HSTS açılmalı.
- Cookie değerlerinde `Secure`, `HttpOnly`, `SameSite=Lax` veya ihtiyaca göre `Strict` kullanılmalı.
- Mixed content olmamalı.
- Cloudflare SSL modu `Full (strict)` hedeflenmeli.

### 4. Secret ve Anahtar Yönetimi

- Secret değerleri repoya girmemeli.
- `.env`, veritabanı ve yedekler transfer dışı tutulmalı.
- `BINANCE_MASTER_KEY` gibi anahtarlar periyodik döndürülmeli.
- Binance API anahtarlarında para çekme yetkisi olmamalı.
- Binance API anahtarları IP kısıtlamalı olmalı.
- API secret değerleri loglanmamalı.
- Yedekler şifrelenmeden sunucu dışına çıkarılmamalı.
- Sunucu sahibi riskine karşı en güçlü model: canlı API secret değerlerini bu sunucuda tutmamak, işlemleri ayrı güvenli imzalama servisi veya dış KMS/HSM üzerinden yaptırmak.

### 5. Veri Şifreleme

Diskte şifreleme yararlıdır fakat çalışan sunucuda root sahibi için tam koruma sağlamaz. Yine de uygulanacaklar:

- Veritabanı yedekleri şifreli alınmalı.
- Hassas alanlar uygulama seviyesinde şifrelenmeli.
- Master key sunucu dışında yönetilebiliyorsa dış KMS kullanılmalı.
- Geri dönüş testi yapılmadan yedek güvenilir sayılmamalı.

### 6. Uygulama İzolasyonu

systemd servislerinde hedeflenen ayarlar:

- `User=final1app`
- `Group=final1app`
- `UMask=0077`
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectHome=true`
- `ProtectSystem=full`
- `ProtectKernelTunables=true`
- `ProtectKernelModules=true`
- `ProtectControlGroups=true`
- `PrivateDevices=true`
- `RestrictSUIDSGID=true`
- `LockPersonality=true`
- `CapabilityBoundingSet=`
- `ReadWritePaths=/var/lib/final1 /var/log/final1 /opt/final1/current /opt/final1/.trader`

Bu ayarlar uygulamanın çalışması için gereken yazma alanlarını korurken, sistemin geri kalanına yazmayı azaltır.

### 7. Ağ ve Firewall

- Gerekli portlar dışında dinleme olmamalı.
- SSH portu sadece yönetim için açık kalmalı.
- Yayın Cloudflare Tunnel ile yapılırsa uygulama portları internete kapatılmalı.
- Geçici test portu `8081` yalnız test süresince açık tutulmalı.
- Nginx güvenlik başlıkları aktif olmalı.
- Rate limit ve WAF Cloudflare tarafında uygulanmalı.

### 8. Loglama ve Maskeleme

- Secret, token, API secret, cookie ve master key loglanmamalı.
- Hata loglarında stack trace dış dünyaya gösterilmemeli.
- Log rotasyonu aktif olmalı.
- Log erişimi `root`, `final1` ve sınırlı yönetici kullanıcılarıyla kalmalı.

### 9. Kimlik Doğrulama

- Yönetici şifreleri güçlü ve benzersiz olmalı.
- Uygulama oturumları kısa ve kontrollü yaşamalı.
- Kritik işlemler için tekrar doğrulama düşünülmeli.
- Brute-force koruması ve rate limit uygulanmalı.

### 10. İzleme

Minimum izlenecekler:

- `final1-web`, `final1-worker`, `final1-manager`, `aysegul`, `nginx` aktiflik durumu.
- CPU, RAM, disk doluluk.
- HTTP sağlık yanıtı.
- SSH başarısız girişleri.
- `/etc/final1/final1.env` değişiklikleri.
- systemd unit değişiklikleri.
- Beklenmeyen yeni dinleme portları.

Bu klasördeki `sunucu-durumu.command` ve `sunucu-guvenlik-kontrol.command` bu kontrollerin pratik başlangıç noktasıdır.

## NIST CSF Eşlemesi

### Identify

- [ ] Hangi veriler hassas: API keys, kullanıcı bilgileri, DB, işlem geçmişi.
- [ ] Sunucudaki tüm servisler listeli.
- [ ] Domain, DNS, Cloudflare ve SSH yetkileri sahiplik bazında biliniyor.

### Protect

- [ ] Root dışı uygulama kullanıcısı.
- [ ] Sıkı dosya izinleri.
- [ ] TLS/HTTPS.
- [ ] Cloudflare WAF veya Tunnel.
- [ ] Secret rotasyonu.
- [ ] En az yetki prensibi.

### Detect

- [ ] Servis durumu izleniyor.
- [ ] Loglar kontrol ediliyor.
- [ ] Yetkisiz SSH denemeleri izleniyor.
- [ ] Dosya bütünlüğü değişiklikleri kontrol ediliyor.

### Respond

- [ ] Şüpheli olayda API keys hemen iptal/döndür.
- [ ] Uygulama geçici olarak durdur.
- [ ] Cloudflare üzerinden erişimi kapat veya Access zorunlu yap.
- [ ] Log ve yedekleri koru.

### Recover

- [ ] Şifreli yedekten geri dönüş testi yap.
- [ ] Temiz sunucuya tekrar kurulum adımları hazır.
- [ ] Yeni anahtarlarla hizmete dön.

## Sunucu Sahibi Riskine Karşı En Güçlü Mimari

En yüksek güvenlik gerekiyorsa aşağıdaki modele geçilmelidir:

1. Sunucuda canlı Binance secret tutulmaz.
2. Uygulama işlem isteğini hazırlar.
3. İmza ayrı, güvenilir, sizin kontrolünüzdeki cihazda veya KMS/HSM/proxy serviste atılır.
4. Sunucuda yalnız sınırlı token veya kısa ömürlü erişim olur.
5. Kritik veriler istemci tarafında şifrelenmiş saklanır.

Bu model daha karmaşıktır fakat sunucu sahibine karşı gerçek koruma seviyesi sağlar.

## Yayın Kararı

Yayın için güvenli minimum:

- HTTPS veya Cloudflare Tunnel.
- Root dışı servis.
- Gizli dosya izinleri doğru.
- API keys IP kısıtlı ve para çekme kapalı.
- Veritabanı ve yedekler şifreli.
- Loglarda secret yok.
- Geri dönüş planı hazır.

Bu maddeler tamamlanmadan canlı müşteri/veri trafiği açılmamalıdır.
