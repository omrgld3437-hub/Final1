# Modül: ops

## Amaç

Calistirma scriptleri — Manager, Web, Worker, marketing sitesi baslat/durdur/deploy.

Kokteki `start.command`, `start.bat` vb. dosyalar **wrapper**; gercek mantik burada.

## Scriptler

| Dosya | Aciklama |
|-------|----------|
| `start.command` | Unix: Manager :7999 + Web :8000 + Worker + marketing :8080 |
| `stop.command` | Tum servisleri durdurur |
| `restart.command` | stop → start |
| `deploy.sh` | Sunucu: git pull + pip + start |
| `run.sh` | Dev: yalnizca Web + Worker (`scripts/run.sh`) |
| `start` | `start.command` kisa yolu |
| `start.bat` / `stop.bat` / `restart.bat` | Windows tam stack |
| `Kurulum.bat` | Windows venv + requirements |
| `guncelle.bat` | Windows git pull |

## Kullanim

```bash
# Proje kokunden (onerilen)
./start.command

# Dogrudan
./ops/start.command
```

## Ilgili

- [docs/runtime.md](../docs/runtime.md)
- [docs/CODE_TREE.md](../docs/CODE_TREE.md)

## Dosya envanteri

### `(kök)`

```
Kurulum.bat
deploy.sh
guncelle.bat
restart.bat
restart.command
run.sh
start
start.bat
start.command
stop.bat
stop.command
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
