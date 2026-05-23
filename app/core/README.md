# app/core — Çekirdek yapılandırma

**Konum:** `app/core/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Uygulama config, sabitler, hata sınıfları, auth token yardımcıları, rate limit.

## Bu klasörde ne bulursunuz?

Ortam değişkenleri, limitler, güvenlik eşikleri — spec ile uyumlu tutulur.

## Önemli dosyalar

config.py · constants.py · errors.py · anomaly_codes.py

## İçerik özeti

```
__init__.py
anomaly_codes.py
auth/
config.py
constants.py
errors.py
logging_helpers.py
security/
```

## İlgili dokümanlar

TRADE_TRAILING_MASTER_SPEC.md System limits

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
