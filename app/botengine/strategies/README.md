# app/botengine/strategies — Bot stratejileri

**Konum:** `app/botengine/strategies/`  
**Güncelleme:** 2026-05-23 (otomatik: `python3 scripts/devops/generate_folder_readmes.py`)

## Ne işe yarar?

Her bot tipinin tick mantığı: DCA grid trailing, TRDCA, multi-asset rebalance vb.

## Bu klasörde ne bulursunuz?

Yeni strateji eklerken buraya modül + registry kaydı. Worker tick başına strateji `run()` çağrılır.

## Önemli dosyalar

dca_grid_trailing.py · trdca_pro.py · registry.py · base.py

## İçerik özeti

```
__init__.py
base.py
dca_grid_trailing.py
multi_asset_rebalance.py
registry.py
trdca_pro.py
```

## İlgili dokümanlar

TRADE_TRAILING_MASTER_SPEC.md strateji bölümleri

---

Üst rehber: [docs/STRUCTURE.md](../docs/STRUCTURE.md)
