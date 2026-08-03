# Final1 Sunucu Yayını

Final1, Aysegul ile aynı sunucuda ayrı servisler olarak çalışır.

## Sunucu Bilgileri

- IP: `178.210.168.102`
- SSH portu: `22666`
- Sunucu yolu: `/opt/final1/current`
- Kalıcı veri: `/var/lib/final1`
- Loglar: `/var/log/final1`
- Env dosyası: `/etc/final1/final1.env`
- Web servis: `final1-web`
- Worker servis: `final1-worker`
- Manager servis: `final1-manager`
- Geçici test adresi: `http://178.210.168.102:8081`
- Yerel tünel adresi: `http://127.0.0.1:18081/ui/login.html`

## Kullanılacak Dosyalar

- `sunucu-local-erisim.command`: Yayın açılmasa bile sunucudaki çalışan projeyi bu bilgisayarda tarayıcıda açar.
- `sunucu-durumu.command`: Sunucu değerlerini basit web panelinde gösterir.
- `degisiklikleri-sunucuya-gonder.command`: Local değişiklikleri sunucuya gönderir.
- `sunucu-yayinini-durdur.command`: Sadece Final1 servislerini durdurur; Aysegul ve Nginx çalışmaya devam eder.
- `sunucu-yayinini-baslat.command`: Final1 servislerini başlatır.
- `sunucu-guvenlik-kontrol.command`: Yayın ve güvenlik durumunu okur.

Kökteki `.command` dosyaları aynı işlemler için kısa yol olarak bırakıldı; asıl dosyalar `sunucu/` içindedir.

## Cloudflare

Cloudflare DNS tarafında A kayıtları:

```text
ayserose.com         A  178.210.168.102
www.ayserose.com     A  178.210.168.102
omeraltin.com        A  178.210.168.102
www.omeraltin.com    A  178.210.168.102
```

`omeraltin.com` ve `www.omeraltin.com`, Final1 paneli yerine `marketing/` klasöründeki küçük statik siteyi açar.

Cloudflare proxy açıkken zorunlu SSL/TLS modu:

```text
Full (strict)
```

Origin sertifikası:

```text
Cloudflare Origin Certificate veya Let's Encrypt
```

`Flexible` kullanılmaz. Nginx HTTP isteklerini HTTPS'e yönlendirdiği için
`Flexible`, Cloudflare ile origin arasında sonsuz yönlendirme döngüsü oluşturur.
HTTPS adresleri doğrudan `200`, HTTP adresleri en fazla tek yönlendirmeyle HTTPS
sonucunu vermelidir.

En güvenli dış yayın modeli:

```text
Cloudflare Tunnel + Cloudflare Access + sunucuda public uygulama portlarını kapatma
```

## Farklı Domain

Farklı domain kullanılacaksa:

```bash
SERVER_NAMES="ornek-domain.com www.ornek-domain.com" ./sunucu/degisiklikleri-sunucuya-gonder.command
```

## Önemli Güvenlik Notu

Klasik VPS modelinde root yetkili sunucu sahibi canlı çalışan uygulamanın belleğini, diskini ve env değerlerini görebilir. Bu yüzden kritik API secret değerleri için en güçlü model, bu sunucuda canlı secret tutmayan dış KMS/HSM veya ayrı imzalama servisi mimarisidir. Detaylar için `GUVENLIK-PROTOKOLLERI.md` dosyasına bakın.
