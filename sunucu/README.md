# Final1 Sunucu Merkezi

Bu klasör, Final1 projesinin sunucu ve yerel erişim araçlarını tek yerde toplar.

## Tek Tık Dosyaları

- `sunucu-local-erisim.command`: Sunucudaki çalışan Final1 uygulamasına bu bilgisayardan güvenli yerel tünel açar ve tarayıcıda açar.
- `sunucu-local-erisim-kapat.command`: Yerel tüneli kapatır.
- `manager-server-erişim.command`: Sunucudaki Final1 Manager Server paneline bu bilgisayardan güvenli yerel tünel açar ve tarayıcıda açar.
- `sunucu-durumu.command`: Basit, düşük kaynak tüketimli web arayüzünde sunucu durumunu ve temel grafikleri gösterir.
- `sunucudaki-projeyi-baslat.command`: Sunucudaki Final1 projesini başlatır.
- `sunucudaki-projeyi-durdur.command`: Sunucudaki Final1 projesini durdurur; Aysegul ve Nginx çalışmaya devam eder.
- `sunucu-yayinini-baslat.command`: Final1 servislerini başlatır.
- `sunucu-yayinini-durdur.command`: Final1 servislerini durdurur.
- `degisiklikleri-sunucuya-gonder.command`: Bu bilgisayardaki değişiklikleri sunucuya gönderir.
- `ssl-sertifikalarini-guncelle.command`: DNS kayıtları sunucuya yöneldikten sonra tüm alan adlarını Let’s Encrypt sertifikasına ekler ve doğrular.
- `sunucu-guvenlik-kontrol.command`: Sunucuda yayın öncesi güvenlik ve durum kontrollerini okur.

## Varsayılan Erişim

- Sunucu IP: `178.210.168.102`
- SSH portu: `22666`
- SSH anahtarı: `$HOME/.ssh/aysegul_sunucu_ed25519`
- Sunucudaki Final1 iç portu: `8000`
- Bu bilgisayarda tünel portu: `18081`
- Sunucudaki Manager Server iç portu: `7999`
- Bu bilgisayarda Manager Server tünel portu: `17999`
- Sunucu durum paneli: `http://127.0.0.1:18082`

## Cloudflare DNS

Cloudflare tarafında alan adı için A kaydı:

- `ayserose.com` -> `178.210.168.102`
- `www.ayserose.com` -> `178.210.168.102`
- `omeraltin.com` -> `178.210.168.102`
- `www.omeraltin.com` -> `178.210.168.102`

`omeraltin.com` ve `www.omeraltin.com`, ana Final1 uygulamasına değil `marketing/` klasöründeki küçük statik siteye gider.

Cloudflare SSL/TLS modu `Full (strict)` olmalıdır. DNS kayıtları sunucuya yöneldikten sonra `ssl-sertifikalarini-guncelle.command` çalıştırılarak bütün alan adları Let’s Encrypt sertifikasına eklenir. `Flexible` modu HTTPS yönlendirme döngüsüne ve Cloudflare ile origin arasının şifresiz kalmasına neden olabileceği için kullanılmamalıdır.

## Artımlı Yayın

`degisiklikleri-sunucuya-gonder.command` yalnızca içeriği veya değiştirilme zamanı farklı olan dosyaları aktarır. Yerel dosya sahibi ve izin farkları aktarım nedeni sayılmaz. Python bağımlılıkları da yalnızca `requirements.txt` değiştiğinde yeniden kurulur. Testler, önbellekler, yerel loglar ve geliştirme çıktıları sunucuda tutulmaz; çalışma veritabanı ile kullanıcı verileri yayın sırasında korunur.

## Kalıcı Kaynak Bakımı

Sunucuda kök XFS bölümü fiziksel diskin tamamını kullanır. Haftalık `sunucu-bakim.timer`, yalnızca yeniden üretilebilir APT önbelleğini ve 14 günden eski systemd journal kayıtlarını temizler. Kullanıcı verileri, veritabanları, proje sürümleri ve yedekler bu bakımın kapsamı dışındadır.

- Journal üst sınırı: `256 MB`; bakım hedefi: `200 MB`.
- KPSS günlükleri: günlük çevrim, en fazla 7 arşiv ve dosya başına `5 MB`.
- Koruyucu swap: `2 GB`; `vm.swappiness=10`.
- Servislerde mevcut normal tüketimin üzerinde `MemoryHigh`, `MemoryMax` ve `TasksMax` kaçak-kaynak sınırları bulunur.
- Final1 karar telemetrisi, sonucu etkilemeyen yinelenmiş `filtered_out` aday listesini veritabanına yazmaz.
- `sunucu-durumu.command`, KPSS dahil servislerin anlık RAM değerini ve swap kullanımını gösterir.

Kurulu ayarların kaynakları `sunucu/config/`, bakım programı ise `sunucu/tools/sunucu-guvenli-bakim` altındadır.

## Güvenlik Belgeleri

- `GUVENLIK-PROTOKOLLERI.md`: Sunucu sahibi, dış dünya ve veri güvenliği için kapsamlı protokol.
- `YAYIN-CHECKLIST.md`: Yayın öncesi ve sonrası doğrulama listesi.
