# app/middleware — HTTP middleware

**Konum:** `app/middleware/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

FastAPI middleware zinciri: CSRF, güvenlik başlıkları, istek metrikleri.

## Bu klasörde ne bulursunuz?

Her HTTP isteğinden önce/sonra çalışır; main.py'de kayıtlıdır.

## Önemli dosyalar

csrf.py · security_headers.py · request_metrics.py

## İçerik özeti

```
__init__.py
csrf.py
request_metrics.py
security_headers.py
```

## İlgili dokümanlar

app/main.py

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
