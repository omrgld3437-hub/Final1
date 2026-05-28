# Modül: manager_server

## Amaç

Yerel ops paneli — süreç başlat/durdur, log, metrik (emir göndermez).

## Giriş

```
python -m manager_server
```

**Port:** 7999 · **UI:** `/ui`

## Dosyalar

| Dosya | Görev |
|-------|--------|
| `app.py` | FastAPI, API, WS |
| `state.py` | PID, log ring, helper spawn; olaylar → dosya |
| `issue_file_store.py` | Olay Merkezi dosya deposu (`.run/issues/`) |
| `reason_engine.py` | Durum açıklama |
| `ui/` | manager.js, logHumanize.js, index.html — canlı log paneli hata/uyarı ring’ini birleştirir |

## Güvenlik

`MANAGER_ALLOW_REMOTE=1` olmadan yalnızca localhost.

## Dosya envanteri

### `(kök)`

```
__init__.py
__main__.py
app.py
issue_file_store.py
reason_engine.py
state.py
```

### `ui/`

```
ui/assets/manager.css
ui/assets/manager.js
ui/index.html
```

*Envanter: 2026-05-23 — `python scripts/sync_module_meta.py`*
