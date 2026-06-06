# RAM Probe Runbook

## Nasıl açılır

Ortam değişkeni ile etkinleştir:

- **RAM_PROBE=1** (veya eski adıyla **RAM_PROBE_ENABLED=1**)

Örnek (macOS / Linux):

```bash
export RAM_PROBE=1
export RAM_PROBE_INTERVAL=30   # saniye (varsayılan 30)
./start.command
```

Veya tek satırda:

```bash
RAM_PROBE=1 RAM_PROBE_INTERVAL=10 ./start.command
```

Windows (CMD):

```cmd
set RAM_PROBE=1
set RAM_PROBE_INTERVAL=30
start.bat
```

## Log yeri

- **logs/ram_snapshots.log** — Her satır tek bir JSON (JSONL). Web ve worker ayrı satırlar yazar; `component` alanı "web" veya "worker".

## Alanlar (her snapshot satırı)

| Alan | Açıklama |
|------|----------|
| ts | ISO zaman (UTC) |
| component | "web" veya "worker" |
| pid | Süreç ID |
| reason | "periodic", "startup" veya stratejik nokta etiketi |
| rss_mb | RSS bellek (MB), psutil |
| vms_mb | Sanal bellek (MB), psutil |
| python_heap_estimate_mb | tracemalloc ile tahmini Python heap (MB) |
| gc | total_objects, dict, list, tuple, str, bytes, asyncio.Task sayıları |
| tracemalloc_top | En büyük 10 allocation: file, line, size_mb |
| hooks | Kayıtlı hook sonuçları (örn. active_bots, active_tasks, ws_connections, cache_sizes) |

## API (Web)

- **GET /api/health/ram** — Son alınan snapshot (RAM_PROBE=1 iken). Yoksa 404 veya `{"detail": "No snapshot yet"}`.

## Sorun giderme

- **Dosya oluşmuyor:** RAM_PROBE=1 ile hem web hem worker başlatıldığından emin olun; `logs/` dizininin yazılabilir olduğunu kontrol edin.
- **psutil yok:** `pip install psutil`. Yüklü değilse probe tek satırlık hata mesajı yazar, uygulama çalışmaya devam eder.
- **Sadece web veya sadece worker satırı:** İki proses de ayrı ayrı başlatılmalı (start.command hem web hem worker’ı başlatır).
