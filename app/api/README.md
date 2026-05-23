# app/api — HTTP ve WebSocket API

**Konum:** `app/api/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Tarayıcı ve dış istemcilerin konuştuğu REST endpoint'leri ve WS kanalları.

## Bu klasörde ne bulursunuz?

Dashboard verisi (`routes.py`), bot start/stop (`bots_engine.py`), kimlik doğrulama (`auth.py`), admin, finans, spot, fiyat ve piyasa verisi route'ları. Alt router'lar `routes/` altında.

## Önemli dosyalar

bots_engine.py · auth.py · routes.py · admin.py · ws.py

## İçerik özeti

```
__init__.py
admin.py
auth.py
bots_engine.py
bots_v2.py
data_hub_routes.py
finance.py
finance_reports.py
leaderboard.py
market_data_routes.py
pricing_routes.py
routes/
routes.py
spot_routes.py
utils/
ws.py
```

## İlgili dokümanlar

app/api/_meta/MODULE.md · docs/api/

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
