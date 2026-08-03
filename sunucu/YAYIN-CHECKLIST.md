# Final1 Yayın Checklist

Bu liste, dış dünyaya açılmadan önce hızlı ama disiplinli doğrulama için hazırlanmıştır.

## 1. DNS ve Cloudflare

- [ ] `ayserose.com` A kaydı `178.210.168.102` değerine gidiyor.
- [ ] `www.ayserose.com` A/CNAME kaydı Final1 sunucusuna gidiyor.
- [ ] `omeraltin.com` A kaydı `178.210.168.102` değerine gidiyor ve Cloudflare proxy açık.
- [ ] `www.omeraltin.com` A/CNAME kaydı Final1 sunucusuna gidiyor ve Cloudflare proxy açık.
- [ ] `omeraltin.com` ana Final1 panelini değil `marketing/` küçük sitesini açıyor.
- [ ] Eski Cloudflare Pages/Worker/redirect/page rule ayarları `diyabetlistesi.com` yönlendirmesi yapmıyor.
- [ ] Cloudflare SSL/TLS modu yalnızca `Full (strict)`; `Flexible` kapalı.
- [ ] Cloudflare Origin Certificate veya Let’s Encrypt origin sertifikası bütün aktif alan adlarını kapsıyor.
- [ ] HTTPS adresleri yönlendirmesiz `200`; HTTP adresleri en fazla bir `301/308` ile HTTPS sonucuna ulaşıyor.
- [ ] Redirect Rule/Page Rule içinde aynı HTTPS adresine geri yönlendiren kural yok.
- [ ] Kalıcı HTTPS sonrası HSTS açılacak; önce test alanında doğrulanacak.
- [ ] Cloudflare WAF, rate limit ve bot koruması temel kuralları aktif.
- [ ] En güvenli model isteniyorsa Cloudflare Tunnel ile inbound port ihtiyacı azaltıldı.

## 2. Uygulama Sağlığı

- [ ] `final1-web`, `final1-worker`, `final1-manager` aktif.
- [ ] `aysegul` aktif kalıyor.
- [ ] `kpss` aktif ve `127.0.0.1:4002` sağlık isteğine yanıt veriyor.
- [ ] `nginx` aktif.
- [ ] `http://127.0.0.1:8000/api/health` sunucuda `ok:true` dönüyor.
- [ ] Dış test adresi `http://178.210.168.102:8081/api/health` beklenen yanıtı veriyor.
- [ ] Worker PID bilgisi doğru yazılıyor.

## 3. Veri ve Gizli Anahtarlar

- [ ] `.env`, `.env.*`, veritabanı ve yedekler repo/dış transfer dışında tutuluyor.
- [ ] `/etc/final1/final1.env` izinleri `640` veya daha sıkı.
- [ ] `/var/lib/final1/tradertrailing.db` izinleri `600` veya eşdeğer.
- [ ] Binance anahtarlarında para çekme yetkisi yok.
- [ ] Binance anahtarları IP kısıtlamalı.
- [ ] Yayın sonrası kritik anahtarlar döndürülüyor.
- [ ] Loglarda API secret, token, kullanıcı şifresi veya master key yok.

## 4. Sunucu Sertleştirme

- [ ] Uygulama root yerine `final1` kullanıcısıyla çalışıyor.
- [ ] systemd servislerinde `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`, `PrivateTmp`, `UMask` aktif.
- [ ] Gereksiz portlar kapalı.
- [ ] SSH sadece anahtar ile çalışıyor.
- [ ] Root SSH uzun vadede kapatılıp sınırlı deploy kullanıcısına geçilecek.
- [ ] Fail2ban veya eşdeğer brute-force koruması aktif.
- [ ] Sistem paketleri güncel.
- [ ] Kök bölüm fiziksel disk kapasitesinin tamamını kullanıyor ve disk kullanımı `%80` altında.
- [ ] `sunucu-bakim.timer` etkin.
- [ ] Journal, KPSS logrotate, swap ve servis kaynak sınırları etkin.

## 5. İzleme ve Müdahale

- [ ] `sunucu/sunucu-durumu.command` paneli çalışıyor.
- [ ] `sunucu/sunucu-guvenlik-kontrol.command` kritik kontrolleri temiz gösteriyor.
- [ ] Günlükler düzenli kontrol ediliyor.
- [ ] Yetkisiz giriş ve servis değişiklikleri için alarm planı var.
- [ ] Yedek geri dönüş testi yapıldı.

## 6. Yayın Sonrası

- [ ] İlk 24 saat servis sağlık, CPU, RAM ve disk izleniyor.
- [ ] Hata logları inceleniyor.
- [ ] Cloudflare analitikleri ve güvenlik olayları kontrol ediliyor.
- [ ] Veritabanı yedeği alınıp şifreli dış depoya konuyor.
