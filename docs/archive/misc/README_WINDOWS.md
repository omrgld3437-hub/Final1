# Windows Kurulum ve Çalıştırma

Bu proje **Windows** üzerinde de çalışır. Sunucuya proje klasörünü kopyalayıp aşağıdaki adımlarla hatasız başlatabilirsiniz.

## Python 3.12 veya 3.13 gerekli

**Python 3.14** bu projede kullanılamaz (pydantic paketi henüz desteklemiyor).  
Mutlaka **Python 3.12** veya **3.13** kurun: https://www.python.org/downloads/

Kurarken **"Add python.exe to PATH"** kutusunu işaretleyin.

---

## İlk kurulum (tek seferlik)

1. Python 3.12 veya 3.13 kurulu olsun (yukarıdaki linkten).
2. **scripts/Kurulum.bat** dosyasına çift tıklayın. Bu dosya:
   - Python 3.12/3.13'ü bulur
   - Eski `.venv` varsa siler
   - Yeni sanal ortam oluşturur ve paketleri yükler
3. Kurulum bitince proje kökünden **start.bat** ile uygulamayı başlatın.

---

## Günlük kullanım

| Dosya | Açıklama |
|-------|----------|
| **start.bat** | Tüm sunucuları başlatır (Manager + Web + Engine). |
| **stop.bat** | Tüm sunucuları durdurur. |
| **restart.bat** | Sunucuları yeniden başlatır. |
| **scripts/Kurulum.bat** | Sadece ilk kurulumda veya .venv bozulduğunda çalıştırın. |
| **scripts/run_fix_crlf.bat** | Mac'ten kopya sonrası .bat satır sonlarını CRLF yapar. |

### Manager Panel

Proje kökünden **start.bat** çalıştırıldığında Manager + Web + Engine başlar. Panel: http://127.0.0.1:7999/ui  

---

## Adresler

- **Manager Panel v3:** http://127.0.0.1:7999/ui (yerel, 127.0.0.1)
- **Giriş:** http://127.0.0.1:8000/ui/login.html
- **Admin:** http://127.0.0.1:8000/ui/admin.html

---

## Sorun giderme

### "Python 3.12 veya 3.13 bulunamadi"
- Python 3.12'yi python.org'dan indirip kurun; kurulumda **"Add to PATH"** işaretli olsun.
- CMD'yi kapatıp açın, **scripts/Kurulum.bat**'ı tekrar çalıştırın.

### Hâlâ "cp314" veya "pydantic" hatası
- Klasördeki **`.venv`** klasörünü elle silin (sağ tık → Sil).
- **scripts/Kurulum.bat**'ı tekrar çalıştırın (Python 3.12 kurulu olmalı).

### "py" tanınmıyor
- Python'u "Add to PATH" ile yeniden kurun veya Python 3.12'yi varsayılan olacak şekilde kurun.

### .bat dosyaları çalışmıyor / satır sonu hatası
- **scripts/run_fix_crlf.bat** çalıştırın; tüm .bat dosyaları Windows CRLF formatına çevrilir.
