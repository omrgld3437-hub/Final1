# Sunucuyu İnternete Açma

Uygulama varsayılan olarak sadece **localhost** (127.0.0.1) üzerinden erişime açıktır. İnternetten erişim için aşağıdaki adımları uygulayın.

---

## 1. Sunucuyu tüm ağ arayüzlerinde dinletmek

Uygulamanın **0.0.0.0** üzerinde dinlemesi gerekir (yani sadece localhost değil, tüm IP’ler).

### macOS / Linux (run.sh)

```bash
export WEB_HOST=0.0.0.0
./run.sh
```

Veya tek satırda:

```bash
WEB_HOST=0.0.0.0 ./run.sh
```

### Windows (calistir.bat / Server Start)

`winfinal` veya proje klasöründe **ortam değişkeni** tanımlayın:

- **Yöntem A:** CMD’de sunucuyu başlatmadan önce:
  ```cmd
  set WEB_HOST=0.0.0.0
  calistir.bat
  ```
- **Yöntem B:** Sistem ortam değişkeni olarak ekleyin:  
  Bilgisayar → Gelişmiş sistem ayarları → Ortam değişkenleri → Yeni → `WEB_HOST` = `0.0.0.0`

`local_web_worker_helper` kullanıldığında **WEB_HOST** zaten varsayılan **0.0.0.0**; yani Windows’ta calistir.bat ile başlatıyorsanız Web (8000) genelde ağdan erişilebilir olur. Emin olmak için yukarıdaki gibi `WEB_HOST=0.0.0.0` kullanın.

### Manager (7999) paneli

Manager varsayılan olarak **0.0.0.0:7999** dinler (`MANAGER_HOST` verilmezse). Sadece yerelde kalsın isterseniz:

```bash
export MANAGER_HOST=127.0.0.1
```

---

## 2. Güvenlik duvarı (firewall)

Sunucu çalışan makinede **8000** (ve isteğe bağlı 7999) portlarına gelen trafiğe izin verin.

- **Windows:** Windows Güvenlik Duvarı → Gelişmiş ayarlar → Gelen kuralları → Yeni kural → Bağlantı noktası → TCP 8000 (ve 7999) → İzin ver.
- **macOS:** Sistem Ayarları → Ağ → Güvenlik Duvarı → Seçenekler → uvicorn/python için gelen bağlantılara izin ver veya “python” için izin ekleyin.
- **Linux:** `ufw allow 8000/tcp` (ve gerekirse `ufw allow 7999/tcp`), sonra `ufw reload`.

---

## 3. Modem / router (port yönlendirme)

Sunucu ev/ofis ağında ve **NAT** arkasındaysa, dışarıdan erişim için **port yönlendirme** gerekir:

1. Modem/router yönetim paneline girin (örn. 192.168.1.1).
2. Port yönlendirme (Port Forwarding / Sanal sunucu) bölümüne girin.
3. **Dış port:** 8000 (ve isteğe bağlı 7999)  
   **İç IP:** Sunucunun yerel IP’si (örn. 192.168.1.100)  
   **İç port:** 8000 (ve 7999)  
   **Protokol:** TCP  
   Kaydedin.

Sunucunun yerel IP’sini öğrenmek:

- Windows: `ipconfig`
- macOS/Linux: `ifconfig` veya `ip addr`

---

## 4. Erişim adresi

- **Yerel ağdan:** `http://<sunucu-ip>:8000` (örn. http://192.168.1.100:8000)
- **İnternetten:** Genelde **sabit IP** veya **DDNS** gerekir. İnternet sağlayıcınızın verdiği dış IP ile: `http://<dis-ip>:8000`. IP değişiyorsa No-IP, DuckDNS vb. ile DDNS kullanabilirsiniz.

---

## 5. Güvenlik önerileri

1. **HTTPS:** İnternete açarken mutlaka HTTPS kullanın. Örneğin:
   - **Caddy** veya **nginx** ters proxy + Let’s Encrypt (ücretsiz SSL).
   - Uygulama 127.0.0.1:8000’de çalışır; Caddy/nginx dışarıda 443’te SSL ile dinleyip 8000’e proxy eder.
2. **Güçlü şifre:** Admin ve kullanıcı hesaplarında güçlü parola kullanın.
3. **Manager (7999):** Log/sunucu yönetim paneli. İnternete açmak zorundan değilseniz açmayın; sadece yerelde (MANAGER_HOST=127.0.0.1) kullanın veya firewall’da 7999’u dışarıya kapatın.
4. **Güncellemeler:** Sistemi ve uygulamayı düzenli güncelleyin.

---

## Özet

| Adım | Ne yapılır |
|------|------------|
| 1 | `WEB_HOST=0.0.0.0` ile sunucuyu başlat (run.sh veya Windows’ta ortam değişkeni). |
| 2 | Makinede firewall’da 8000 (ve isteğe bağlı 7999) portunu aç. |
| 3 | Modem/router’da 8000 → sunucu yerel IP:8000 port yönlendirmesi yap. |
| 4 | Erişim: `http://<ip>:8000/ui/login.html`; mümkünse önüne Caddy/nginx ile HTTPS ekle. |
