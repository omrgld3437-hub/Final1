# Deployment Kılavuzu – Sabit ve Değişken Dosyalar

Bu proje **sabit** ve **değişken** dosyalar olarak ayrılmıştır. Sunucuya her seferinde sıfırdan taşımak yerine, sadece değişen dosyaları güncelleyebilirsiniz.

---

## İçindekiler

1. [Genel Bakış](#genel-bakış)
2. [SABİT Dosyalar](#sabit-dosyalar-asla-değiştirilmemeli)
3. [DEĞİŞKEN Dosyalar](#değişken-dosyalar-güncellenir)
4. [İlk Kurulum (Sıfırdan)](#ilk-kurulum-sıfırdan)
5. [Güncelleme Deploy (Sonraki Seferler)](#güncelleme-deploy-sonraki-seferler)
6. [Deploy Yöntemleri](#deploy-yöntemleri)
7. [Windows Kullanıcıları](#windows-kullanıcıları)
8. [Manuel Kopyalama](#manuel-kopyalama-ftp-scp-filezilla)
9. [Sorun Giderme](#sorun-giderme)

---

## Genel Bakış

| Durum | Ne yapılır |
|-------|------------|
| **İlk kez sunucuya kuruyorsunuz** | Tüm projeyi kopyalayın, `.env` oluşturun, venv kurun |
| **Kod güncellemesi yapıyorsunuz** | Sadece değişken dosyaları kopyalayın (`.env`, veritabanı, loglar korunur) |

Deploy script ve rsync bu ayrımı otomatik yapar: **SABİT** dosyalar atlanır, **DEĞİŞKEN** dosyalar kopyalanır.

---

## SABİT Dosyalar (ASLA Değiştirilmemeli)

Sunucuda **mevcut hali korunmalı**dır. Deploy sırasında bu dosyalar **üzerine yazılmaz**.

| Dosya/Klasör | Açıklama |
|--------------|----------|
| `.env` | API anahtarları, şifreler, veritabanı URL, sunucuya özel ayarlar |
| `*.db`, `*.sqlite` | Veritabanı dosyaları (işlem geçmişi, hesaplar, bot durumları) |
| `logs/` | Log dosyaları |
| `venv/`, `.venv/` | Python sanal ortamı (pip paketleri) |
| `__pycache__/` | Python önbellek |
| `.git/` | Git geçmişi |
| `Omeraltinhtml/visits.json` | Ziyaretçi istatistikleri |

**Önemli:** `.env` dosyasını sunucuda **bir kez** oluşturun. Proje kök dizinine `.env.example` dosyasından kopyalayıp, API anahtarlarını ve ayarları güncelleyin.

---

## DEĞİŞKEN Dosyalar (Güncellenir)

Bu dosyalar geliştirme sırasında değişir. Deploy sırasında sunucuya kopyalanır ve **sunucudaki eski sürümlerin üzerine yazılır**.

| Klasör/Dosya | İçerik |
|--------------|--------|
| `app/` | Python backend kodu |
| `manager_server/` | Manager sunucu kodu |
| `ui/` | Arayüz (HTML, JS, CSS, görseller) |
| `scripts/` | Yardımcı ve migration scriptleri |
| `tests/` | Test dosyaları |
| `docs/` | Dokümantasyon |
| `requirements.txt` | Python bağımlılıkları |
| `start.*`, `stop.*`, `restart.*` | Başlatma/durdurma betikleri |
| `.env.example` | Ortam değişkeni şablonu |
| `Omeraltinhtml/` | Statik site (visits.json hariç) |
| `deploy/` | Deployment script ve listeler |

---

## İlk Kurulum (Sıfırdan)

Sunucuya projeyi **ilk kez** kuruyorsanız:

### 1. Projeyi sunucuya kopyalayın

**Yerel makineden (Geliştirme):**
```bash
# rsync ile tam kopya (veya scp, FTP, Git clone)
rsync -avz /Users/omeraltin/Desktop/final1/ user@sunucu.com:/var/www/final1/
```

**Veya sunucuda Git kullanıyorsanız:**
```bash
cd /var/www
git clone <repo-url> final1
cd final1
```

### 2. .env dosyasını oluşturun

**Sunucuda:**
```bash
cd /var/www/final1
cp .env.example .env
nano .env   # veya vim, vi
```

**.env içinde düzenleyin:**
- `BINANCE_MASTER_KEY` – Şifreleme anahtarı (`.env.example` içindeki talimatla oluşturun)
- `DATABASE_URL` – Örn: `sqlite:////var/www/final1/data/dca.db` veya PostgreSQL bağlantı bilgisi

### 3. Sanal ortam ve bağımlılıklar

**Sunucuda (Linux/Mac):**
```bash
cd /var/www/final1
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows sunucuda:**
```cmd
cd C:\inetpub\final1
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Veritabanı (gerekirse)

SQLite kullanıyorsanız, veritabanı dizini oluşturulabilir:
```bash
mkdir -p /var/www/final1/data
# DATABASE_URL=sqlite:////var/www/final1/data/dca.db
```

### 5. Uygulamayı başlatın

```bash
./start.command    # Mac/Linux
# veya
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --loop uvloop --http httptools
```

---

## Güncelleme Deploy (Sonraki Seferler)

Kodda değişiklik yaptıktan sonra sunucuyu güncellemek için:

### Yöntem 1: Deploy script (önerilen)

**Yerel makineden (Geliştirme):**
```bash
cd /Users/omeraltin/Desktop/final1
./deploy/deploy.sh user@sunucu.com:/var/www/final1
```

Bu komut:
- `app/`, `ui/`, `manager_server/`, `scripts/` vb. kopyalar
- `.env`, `*.db`, `venv/`, `logs/` **atlar** (sunucudaki mevcut hali korunur)
- `--delete` ile sunucuda artık olmayan dosyaları siler

### Yöntem 2: Ortam değişkeni ile

```bash
export RSYNC_DEST="user@sunucu.com:/var/www/final1"
./deploy/deploy.sh
```

### Yöntem 3: Doğrudan rsync

```bash
rsync -avz --delete \
  --exclude-from=deploy/SABIT_DOSYALAR.txt \
  /Users/omeraltin/Desktop/final1/ user@sunucu.com:/var/www/final1/
```

### Deploy sonrası

Sunucuda uygulama çalışıyorsa, yeniden başlatmanız gerekebilir:
```bash
# Sunucuda
cd /var/www/final1
./restart.command
```

---

## Deploy Yöntemleri

### rsync parametreleri

| Parametre | Açıklama |
|-----------|----------|
| `-a` | Arşiv modu (izinler, tarihler korunur) |
| `-v` | Detaylı çıktı |
| `-z` | Sıkıştırma (daha hızlı ağ transferi) |
| `--delete` | Sunucuda kaynakta olmayan dosyaları siler |
| `--exclude-from=...` | Atlanacak dosyaların listesi |

### Örnek sunucu adresleri

```bash
# SSH ile
user@192.168.1.100:/var/www/final1
user@myserver.com:/home/user/apps/final1

# Farklı port
ssh -p 2222 user@sunucu.com
# rsync için:
rsync -avz -e "ssh -p 2222" ... user@sunucu.com:/var/www/final1/
```

---

## Windows Kullanıcıları

### Git Bash veya WSL ile rsync

1. Git for Windows kurun (Git Bash ile gelir)
2. veya WSL (Windows Subsystem for Linux) kurun

```bash
# Git Bash'te
cd /c/Users/KULLANICI/Desktop/final1
./deploy/deploy.sh user@sunucu.com:/var/www/final1
```

### deploy.bat (rsync gerekli)

```cmd
deploy\deploy.bat user@sunucu.com:/var/www/final1
```

`rsync` Windows'ta yüklü değilse, [manuel kopyalama](#manuel-kopyalama-ftp-scp-filezilla) bölümüne bakın.

---

## Manuel Kopyalama (FTP, SCP, FileZilla)

`rsync` veya script kullanamıyorsanız, **SABIT_DOSYALAR.txt** listesine bakarak manuel kopyalayın.

### Kopyalanacaklar (DEĞİŞKEN)

- `app/` klasörünün tamamı
- `manager_server/` klasörünün tamamı
- `ui/` klasörünün tamamı
- `scripts/` klasörünün tamamı
- `docs/` klasörünün tamamı
- `tests/` klasörünün tamamı
- `deploy/` klasörünün tamamı
- `requirements.txt`
- `start.bat`, `start.command`, `stop.bat`, `stop.command`, `restart.bat`, `restart.command`
- `Kurulum.bat`
- `.env.example`
- `Omeraltinhtml/` içindeki her şey **ama** `visits.json` hariç

### Kopyalanmayacaklar (SABİT – sunucudakini koruyun)

- `.env`
- `*.db`, `*.sqlite`
- `logs/`
- `venv/`, `.venv/`
- `__pycache__/`
- `.git/`
- `Omeraltinhtml/visits.json`

### FileZilla / WinSCP ile

1. Sol tarafta (yerel) proje klasörünü açın
2. Sağ tarafta (sunucu) hedef klasörü açın
3. Yukarıdaki “Kopyalanacaklar” listesindeki klasörleri sürükleyip bırakın
4. `.env` varsa **üzerine yazma** uyarısı gelirse “Hayır” deyin

---

## Sorun Giderme

### Değişiklikler yansımıyor (sunucuyu yeniden başlattım ama güncel kod görünmüyor)

Sırayla kontrol edin:

1. **Sunucuda `git pull` yaptınız mı?**  
   Yeniden başlatmak sadece **zaten diskte olan** kodu çalıştırır. Önce repodan güncel kodu almalısınız:
   ```bash
   cd /var/www/final1   # veya sunucudaki proje yolu
   git pull origin main
   ```
   Sonra servisi yeniden başlatın.

2. **Doğru dizinde mi çalışıyorsunuz?**  
   `git pull` yaptığınız klasör ile uygulamanın çalıştığı klasör **aynı** olmalı. Örneğin `~/final1` içinde pull yapıp servisi `/var/www/final1` üzerinden başlattıysanız eski kod çalışır. Servisi hangi dizinden başlatıyorsanız (systemd, `run.sh`, `start.command`), `git pull`’u da o dizinde yapın.

3. **Tarayıcı / proxy önbelleği**  
   Uygulama tüm `/ui/*` ve `/api/debug/build-info` yanıtlarına `Cache-Control: no-store` ekler; commit sonrası değişiklikler anında yansır. Proxy cache kullanıyorsanız bu path’lerde cache kapatın. Eski sekme açıksa **Ctrl+Shift+R** veya **Cmd+Shift+R** ile zorla yenileyin.

4. **Eski process hâlâ çalışıyor olabilir**  
   “Yeniden başlat” dediğinizde gerçekten yeni process başlıyor mu kontrol edin:
   ```bash
   # Linux/Mac: 8000 portunu kullanan process
   lsof -i :8000
   # veya
   ps aux | grep uvicorn
   ```
   Eski PID’leri kapatıp servisi tekrar başlatın (örn. `./scripts/restart_server.py` veya `restart.command`).

5. **Özet sıra (Git kullanıyorsanız)**  
   Sunucuda: **git pull** → **servisi yeniden başlat**. UI artık no-cache ile verildiği için sayfa yenilendiğinde güncel sürüm gelir.

6. **`/api/debug/build-info` adresi login sayfasına atıyorsa**  
   Bu path uygulama tarafında giriş istemeden açılır. Login’e düşüyorsa büyük ihtimalle **Nginx (veya başka proxy)** tüm `/api/*` isteklerini giriş yoksa login’e yönlendiriyordur. Nginx config’te bu path’i istisna yapın; örneğin `location = /api/debug/build-info { proxy_pass http://127.0.0.1:8000; ... }` ile doğrudan uygulamaya iletin (auth uygulamayın).

7. **Domain’den eski görünüm, sunucuda 127.0.0.1:8000 güncel**  
   Domain trafiği **Nginx (veya öndeki proxy)** üzerinden geçiyor; eski sayfa Nginx’in **önbelleği** veya **statik dosya root’u** yüzünden geliyor. Güncel görünümün yansıması için:

   - **Tüm istekleri 8000’e proxy edin:** `/` ve `/ui` için ayrı `root`/`alias` ile statik dosya sunmayın; her şeyi `proxy_pass http://127.0.0.1:8000` ile uygulamaya iletin.
   - **Proxy cache’i kapatın:** Bu site için ilgili `location` bloklarında `proxy_cache off;` kullanın (ve varsa `proxy_no_cache 1;`). Daha önce cache kullanıldıysa **cache’i temizleyin** veya Nginx’i yeniden başlatın (cache dizinini boşaltın).
   - **Cloudflare kullanıyorsanız:** Aşağıdaki “Cloudflare cache” bölümüne bakın.

   Yapılan her `git pull` + uygulama yeniden başlatma sonrası domain’den de güncel görünüm gelir (Nginx sadece proxy yapıyorsa ve öndeki Cloudflare cache temizlenmiş/kapalıysa).

8. **Cloudflare cache (domain eski, local güncel)**  
   Trafik **Cloudflare → Nginx → 8000** şeklindeyse eski sayfa büyük ihtimalle **Cloudflare önbelleği**nden geliyor. Yapılacaklar:

   - **Hızlı test:** Cloudflare Dashboard → **Caching** → **Configuration** → **Development Mode**’u 3 saat için açın. Siteyi tekrar açın; güncel görünüyorsa sebep Cloudflare cache.
   - **Kalıcı çözüm (seçeneklerden biri):**
     - **Purge:** **Caching** → **Configuration** → **Purge Everything** ile tüm cache’i temizleyin. Her deploy sonrası tekrar purge gerekebilir.
     - **Bypass:** **Caching** → **Cache Rules** (veya **Page Rules**) ile `tradertrailing.com/*` için **Cache Level: Bypass** kuralı ekleyin; böylece Cloudflare hiç önbelleğe almaz, her istek sunucuya gider (güncel görünüm garanti, CDN hızı bu domain’de olmaz).
     - **Sadece HTML’i bypass:** Sadece sayfa (HTML) güncel olsun istiyorsanız, `*tradertrailing.com/ui/*.html` veya `*tradertrailing.com/` için “Bypass cache” kuralı yazabilirsiniz; statik asset’ler (JS/CSS) isteğe bağlı cache’te kalabilir.
   - **SSL:** Cloudflare’da **SSL/TLS** → **Overview** → mode **Full** veya **Full (strict)** olsun; Nginx’te `X-Forwarded-Proto` zaten iletiliyorsa uygulama doğru scheme’i görür.

### "CRASH_LOOP" / Web servisi sürekli çöküyor

Servis kısa sürede tekrar tekrar yeniden başlıyorsa:

1. **Gerçek hatayı bulun** – log dosyasının son satırlarına bakın:
   - **Windows:** `C:\Users\Administrator\Desktop\Final1\logs\web.log`
   - **Linux/Mac:** `logs/web.log` veya `./logs/web.log`  
   Son 30–50 satırda genelde `ModuleNotFoundError` veya `Traceback` görünür.

2. **Sık nedenler:**
   - **`No module named 'app.core'`**, **`'app.api.utils'`**, **`'app.services.dashboard_snapshot'`** veya **`'app.botengine.intent_ledger'`** → Sunucuda kod güncel değil. Proje kökünde `git pull` yapıp Web ve Worker’ı yeniden başlatın (bkz. [Sunucuda "ModuleNotFoundError"](#suncuda-modulenotfounderror)).
   - **`No module named 'uvloop'`** → Windows’ta uvloop yok. `start.bat` ile başlatın (güncel start.bat uvloop kullanmaz); komut satırında `--loop uvloop` kullanmayın.

3. **Yeniden başlatmayı durdurun** – hatayı düzeltene kadar panelden “Yeniden başlat” yapmayın; önce `logs/web.log` ile nedeni tespit edin.

### stop.bat: "´╗┐@echo" / BOM hatası veya site kapanmıyor

- **BOM hatası:** Dosya UTF-8 BOM ile kaydedilmişse ilk satır bozulur. **Çözüm:** Sunucuda `stop.bat`'ı **Notepad** ile açıp "Farklı Kaydet" → **"ANSI"** veya **"UTF-8"** (BOM’suz) seçip kaydedin. Ya da proje kökünde `git pull` yapıp güncel `stop.bat`’ı alın (tercih edilen).
- **PID 0 / taskkill seli:** Güncel script sadece `PID > 0` olanları kapatır; port 80/443 da eklenmiştir.
- **tradertrailing.com hâlâ açıksa:** Site port 80/443’ten servis veriyorsa `stop.bat` artık bu portları da kapatıyor. Script’i **Yönetici olarak çalıştır**ın; yine kapanmıyorsa IIS veya başka bir servisin 80’i kullandığını kontrol edin.

### "Permission denied" hatası

```bash
# SSH anahtarınızı kontrol edin
ssh user@sunucu.com
# veya hedef klasör yazma izni
chmod 755 /var/www/final1
```

### ".env üzerine yazıldı" endişesi

Deploy script `--exclude-from=deploy/SABIT_DOSYALAR.txt` kullanır; `.env` bu listede olduğu için kopyalanmaz. Yine de ilk deploydan önce yedek alın:
```bash
cp .env .env.backup
```

### rsync bulunamadı

**Mac:** Genellikle kurulu.  
**Linux:** `sudo apt install rsync` (Debian/Ubuntu) veya `sudo yum install rsync` (CentOS)  
**Windows:** Git Bash veya WSL kullanın; ya da manuel kopyalama yapın.

### Deploy çok yavaş

`-z` sıkıştırma zaten kullanılıyor. Ağ yavaşsa sadece değişen dosyaları kopyalamak için `rsync` yeterli; büyük `venv` ve `node_modules` zaten atlanıyor.

### Sunucuda "ModuleNotFoundError"

**A) Eksik Python paketi** (örn. `No module named 'uvloop'`):  
`venv` atlandığı için sunucuda yeniden kurulmaz. `requirements.txt` değiştiyse sunucuda:
```bash
# Linux/Mac
source venv/bin/activate   # veya .venv/bin/activate
pip install -r requirements.txt

# Windows (CMD, proje kökünde)
.venv\Scripts\activate
pip install -r requirements.txt
```

**B) Eksik uygulama modülü** (`No module named 'app.core'`, `'app.api.utils'`, `'app.services.dashboard_snapshot'` veya `'app.botengine.intent_ledger'`):  
Bu modüller repoda var; sunucuda **güncel kod yok**. Proje Git ile yönetiliyorsa sunucuda proje kökünde:
```bash
# Windows (CMD)
cd C:\Users\Administrator\Desktop\Final1
git pull
```
Ardından Web ve Worker servislerini **Yeniden başlat** (panelden veya `start.bat`).  
Manuel kopya kullanıyorsanız yerelden şu klasör/dosyaları sunucuya kopyalayın: `app/core/` (tüm dizin), `app/botengine/intent_ledger.py`, `app/botengine/kill_switch.py`, `app/botengine/errors.py`, `app/botengine/reconcile.py`, `app/botengine/scheduler.py`, `app/botengine/bot_run.py`, `app/botengine/user_stream.py`.

---

## Özet Tablo

| İşlem | Komut / Yöntem |
|-------|----------------|
| İlk kurulum | Tam kopya + `.env` + venv |
| Güncelleme | `./deploy/deploy.sh user@host:/path` |
| Manuel | SABIT_DOSYALAR.txt’e göre hariç tut, geri kalanı kopyala |
| Windows | Git Bash + deploy.sh veya manuel |
