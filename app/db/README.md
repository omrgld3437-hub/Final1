# app/db — Veritabanı katmanı

**Konum:** `app/db/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

SQLAlchemy modelleri, oturum fabrikası, şema koruma (schema_guard).

## Bu klasörde ne bulursunuz?

Varsayılan SQLite: `~/.trader/dca.db`. Web ve worker aynı DB'yi kullanmalı (.env DATABASE_URL).

## Önemli dosyalar

models.py · session.py · base.py · schema_guard.py

## İçerik özeti

```
__init__.py
base.py
models.py
schema_guard.py
session.py
```

## İlgili dokümanlar

docs/runtime.md · scripts/migrations/

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
