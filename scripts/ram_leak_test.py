#!/usr/bin/env python3
"""
RAM LEAK TEST — GC + asyncio Task sayımı.
Periyodik gc.collect() sonrası obje sayıları; stop sonrası task sayısı azalıyor mu?
Çalıştırma: RAM_PROBE_ENABLED=1 ile worker veya web başlatıldıktan sonra
  python scripts/ram_leak_test.py
veya uygulama içinden GET /api/debug/ram-snapshot (RAM_PROBE_ENABLED=1).
"""
import gc
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def main():
    os.chdir(_PROJECT_ROOT)
    # tracemalloc başlat (probe modülü yapar)
    from app.observability.ram_probe import (
        gc_collect_and_count,
        take_snapshot,
        get_ram_snapshot_log_path,
        _get_asyncio_task_count,
    )
    gc.collect()
    leak_result = gc_collect_and_count()
    snapshot = take_snapshot(label="leak_test")
    snapshot["gc_after_collect"] = leak_result.get("top_types", {})
    snapshot["asyncio_task_count"] = _get_asyncio_task_count()
    log_path = get_ram_snapshot_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"\nAppended to {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
