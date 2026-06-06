# Veritabanı migrasyonları

**Proje kökünden** çalıştırın (cwd = proje klasörü):

```bash
# İlk kurulum: tabloları oluştur
python scripts/migrations/init_db.py

# Tek seferlik migrasyonlar (gerekirse)
python scripts/migrations/migrate_spot_favorites.py   # accounts.spot_favorites_json
python scripts/migrations/migrate_user_activity.py    # users: last_login_ip, last_activity_at, ...
python scripts/migrations/migrate_account_code_backfill.py  # accounts.account_code backfill
python scripts/migrations/migrate_admin_fixed.py      # Admin kullanıcı adı/şifre (admin zaten varsa)
python scripts/migrations/create_first_admin.py       # İlk admin yoksa oluşturur; ilk girişte yazılan şifre kalıcı olur
```

Windows’ta `.venv` kullanıyorsanız: `.venv\Scripts\python scripts\migrations\init_db.py`
