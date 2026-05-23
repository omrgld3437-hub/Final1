# Dokümantasyon indeksi

## Yapı

| Dosya | Konu |
|-------|------|
| [STRUCTURE.md](STRUCTURE.md) | **Proje yapısı — tek sayfa rehber** |
| **Her klasörde `README.md`** | Klasör işlevi + dosya listesi (48 klasör) |
| [ANA_BASLIKLAR.md](ANA_BASLIKLAR.md) | Tüm dosyalar — kategoriler |
| [CODE_TREE.md](CODE_TREE.md) | Klasör ağacı |
| [runtime.md](runtime.md) | Başlatma, portlar |
| [security_hardening.md](security_hardening.md) | Auth, güvenlik |
| [engine/BOTENGINE_RUNBOOK.md](engine/BOTENGINE_RUNBOOK.md) | Engine operasyon |
| [engine/BOTENGINE_STATE_MODEL.md](engine/BOTENGINE_STATE_MODEL.md) | Durum modeli |
| [api/](api/) | API sözleşmeleri |

**Spec (kök):** [TRADE_TRAILING_MASTER_SPEC.md](../TRADE_TRAILING_MASTER_SPEC.md)

---

## Modül (_meta)

| Modül | Dosya |
|-------|--------|
| Backend | [../app/_meta/MODULE.md](../app/_meta/MODULE.md) |
| Bot Engine | [../app/botengine/_meta/MODULE.md](../app/botengine/_meta/MODULE.md) |
| API | [../app/api/_meta/MODULE.md](../app/api/_meta/MODULE.md) |
| Servisler | [../app/services/_meta/MODULE.md](../app/services/_meta/MODULE.md) |
| Web paneli | [../ui/_meta/MODULE.md](../ui/_meta/MODULE.md) |
| Manager | [../manager_server/_meta/MODULE.md](../manager_server/_meta/MODULE.md) |
| Calistirma | [../ops/_meta/MODULE.md](../ops/_meta/MODULE.md) |
| Scriptler | [../scripts/_meta/MODULE.md](../scripts/_meta/MODULE.md) + [../scripts/README.md](../scripts/README.md) |
| Testler | [../tests/_meta/MODULE.md](../tests/_meta/MODULE.md) |
| Deploy | [../deploy/_meta/MODULE.md](../deploy/_meta/MODULE.md) |
| Marketing | [../marketing/README.md](../marketing/README.md) |

---

## Arşiv

[archive/](archive/) — eski raporlar, birleştirilmiş dokümanlar

Güncelleme: `make meta` (README + envanter + ana başlıklar)

Üretim script'i: `scripts/devops/generate_folder_readmes.py`
