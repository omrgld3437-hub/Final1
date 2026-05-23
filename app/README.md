# app — Backend (Python paketi)

**Konum:** `app/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Tüm sunucu tarafı mantık burada. FastAPI uygulaması (`main.py`), REST/WebSocket API, veritabanı modelleri, Binance entegrasyonu ve Bot Engine paketi `app` adıyla import edilir.

## Bu klasörde ne bulursunuz?

Web süreci: `uvicorn app.main:app`. Worker süreci: `python -m app.botengine.worker_main`. Bu paket adı değiştirilmez — deploy ve import yolları buna bağlıdır.

## Önemli dosyalar

`main.py` FastAPI giriş · `boot_id.py` sunucu örneği kimliği · `server_state.py` runtime bayrakları

## İçerik özeti

```
api/
boot_id.py
bot/
botengine/
core/
db/
error_logging.py
main.py
middleware/
observability/
server_state.py
services/
utils/
```

## İlgili dokümanlar

app/_meta/MODULE.md · TRADE_TRAILING_MASTER_SPEC.md

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
