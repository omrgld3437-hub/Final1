# TraderTrailing – Proje

> **Güncel giriş:** Proje kökündeki [README.md](../README.md) ve kod ağacı [docs/CODE_TREE.md](CODE_TREE.md).

Bu klasör TraderTrailing (DCA Bot Manager) projesidir.

- **Kaynak proje:** `~/Desktop/güncel2` (varsa)
- **Proje klasörü:** `~/Desktop/trader` veya kurulum yaptığınız dizin

## Çalıştırma

```bash
cd ~/Desktop/trader
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

veya proje kökündeki **`start.command`** (macOS) / **`start.bat`** (Windows) kullanın. Alternatif: `scripts/run.sh` (Mac, tek proses).

**Manager Panel (yerel yönetim):** Web + Bot Engine’i tek ekrandan başlatıp log/hata izlemek için:
- **Windows:** Proje kökünden `start.bat` — Manager + Web + Engine.
- **macOS:** Proje kökünden `./start.command` — Aynı davranış.
- **Panel:** http://127.0.0.1:7999/ui (yerel).
- **Durdurma:** `stop.bat` / `stop.command`. Yeniden başlatma: `restart.bat` / `restart.command`.
- **Loglar:** `logs/manager.log`, `logs/web.log`, `logs/worker.log`

### Windows: Kurulum ve çalıştırma

Sunucuyu Windows’ta hatasız çalıştırmak için:

1. **İlk kurulum:** **`scripts/Kurulum.bat`** çift tıklayın (Python 3.12/3.13 bulur, .venv oluşturur, paketleri yükler).
2. **Başlatma:** Proje kökünden **`start.bat`** ile sunucuyu başlatın.
3. **Durdurma:** **`stop.bat`**. Yeniden başlatma: **`restart.bat`**.
4. Ayrıntılar: **docs/README_WINDOWS.md**.

### Windows: .bat dosyaları bozuksa (Mac'ten kopya sonrası)

Mac'te kaydedilen proje Windows'ta açıldığında satır sonları (LF/CRLF) yüzünden .bat dosyaları hata verebilir. Çözüm:

1. **Tek seferlik düzeltme:** Proje klasöründe **`scripts/run_fix_crlf.bat`** çift tıklayın; veya PowerShell açıp `.\scripts\fix_bat_crlf.ps1` çalıştırın. Tüm .bat dosyaları Windows uyumlu (CRLF) yapılır.
2. **Git kullananlar:** Projede `.gitattributes` var; `git add --renormalize .` ve commit sonrası clone/pull yapan herkes doğru satır sonunu alır.

## Hangi proje çalışıyor?

Aynı bilgisayarda **güncel2**, **proje** gibi birden fazla kopya varsa, hangi klasörün sunucusunun çalıştığını kontrol için:

1. **Başlatırken:** `start.command` veya `scripts/run.sh` çalıştırdığınızda terminalde **"Proje klasörü: ..."** satırı bu dosyanın bulunduğu klasörü gösterir. Projenin **proje** içinde olduğundan emin olun (örn. `Desktop/trader`).
2. **Çalışan sunucuyu doğrulama:** `curl -s http://127.0.0.1:8000/api/health` — Yanıttaki **`project_path`** alanı, o anda çalışan kodun klasörünü gösterir. Örn. `/Users/.../Desktop/trader` olmalı.
3. **Port 8000:** Aynı anda yalnızca bir sunucu 8000’i kullanır. Sunucuyu **proje** içinden başlatırsanız projenin kodu çalışır.

**Özet:** Çalıştırmak için sunucuyu **proje** klasöründen başlatın.

## Cursor / IDE

Proje üzerinde çalışmak için Cursor’da klasörü açın:

**File → Open Folder → `Desktop/trader`** (veya proje klasörünüz)

## Veritabanı (hesaplar, botlar – güncellemede korunur)

Veritabanı varsayılan olarak **`~/.trader/dca.db`** konumunda tutulur. Projeyi silip yeniden kursanız bile hesaplar, botlar ve veriler korunur. Konum: `~/.trader/` (Mac/Linux) veya `%USERPROFILE%\.trader\` (Windows).

## İçerik

- Projenin tam kopyası (app, ui, docs, .venv, vb.)
- Tüm yollar script içinde `dirname` ile çözüldüğü için projeden bağımsız çalışır.
