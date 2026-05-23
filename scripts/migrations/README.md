# scripts/migrations — Veritabanı migration

**Konum:** `scripts/migrations/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Tablo oluşturma, admin kullanıcı, tek seferlik şema güncellemeleri.

## Bu klasörde ne bulursunuz?

İlk kurulum: `init_db.py`, `create_first_admin.py`. Canlı DB'de dikkatli kullanın.

## Önemli dosyalar

init_db.py · create_first_admin.py · set_admin_password_once.py

## İçerik özeti

```
create_first_admin.py
init_db.py
migrate_account_code_backfill.py
migrate_admin_fixed.py
migrate_spot_favorites.py
migrate_user_activity.py
set_admin_password_once.py
```

## İlgili dokümanlar

app/db/schema_guard.py

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
