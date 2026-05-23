# manager_server — Ops paneli (:7999)

**Konum:** `manager_server/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Sunucu operasyon paneli: process start/stop, log tail, metrik, servis durumu.

## Bu klasörde ne bulursunuz?

Ayrı FastAPI uygulaması. Web/worker/helper script'leri buradan tetiklenebilir. Sadece localhost.

## Önemli dosyalar

app.py · state.py · reason_engine.py · ui/

## İçerik özeti

```
__init__.py
__main__.py
app.py
reason_engine.py
state.py
ui/
```

## İlgili dokümanlar

manager_server/_meta/MODULE.md · docs/runtime.md

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
