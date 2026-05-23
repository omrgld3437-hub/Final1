# app/observability — Gözlemlenebilirlik

**Konum:** `app/observability/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

RAM probe, metrik stub'ları — prod debug ve kapasite izleme.

## Bu klasörde ne bulursunuz?

RAM_PROBE=1 ile snapshot loglama; manager panelinde izlenebilir.

## Önemli dosyalar

ram_probe.py · metrics_stubs.py

## İçerik özeti

```
__init__.py
metrics_stubs.py
ram_probe.py
```

## İlgili dokümanlar

scripts/perf/ram_analyze.py

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
