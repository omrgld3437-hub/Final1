#!/usr/bin/env python3
"""
RAM STRESS SENARYOLARI — A/B/C/D.
Ölçüm sonuçları logs/ram_snapshots.log ve docs/ram_root_cause_report.md ile doldurulur.
Bu script sadece talimat verir; senaryoları manuel veya API ile çalıştırın.

Kullanım:
  RAM_PROBE_ENABLED=1 ile web/worker başlatın.
  A/B/C/D adımlarını sırayla uygulayın; her adımda ram_snapshots.log’a yazılır.
  En son: logs/ram_snapshots.log’u parse edip docs/ram_root_cause_report.md’yi doldurun.
"""
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOGS_DIR = _PROJECT_ROOT / "logs"
_RAM_LOG = _LOGS_DIR / "ram_snapshots.log"
_REPORT = _PROJECT_ROOT / "docs" / "ram_root_cause_report.md"


def print_instructions():
    print("=" * 60)
    print("RAM ROOT CAUSE — Stres senaryoları")
    print("=" * 60)
    print("1. RAM_PROBE_ENABLED=1 ile uygulamayı başlatın (web veya worker).")
    print("2. logs/ram_snapshots.log her 30 saniyede dolar + stratejik probe’lar yazar.")
    print("")
    print("Senaryo A — Idle: 0 bot, 10 dk bekle. RAM artıyor mu?")
    print("Senaryo B — 1 Bot: 1 bot start, 30 dk çalışsın. RAM sabit mi?")
    print("Senaryo C — 10 Bot: 10 bot start, 30 dk, sonra hepsini stop. RAM geri düşüyor mu?")
    print("Senaryo D — Web Down: Worker açık, web server kapat. RAM değişimi?")
    print("")
    print("3. Ölçüm sonrası docs/ram_root_cause_report.md’yi doldurun:")
    print("   - logs/ram_snapshots.log satırlarını parse edin (her satır bir JSON).")
    print("   - RSS/heap_mb zaman çizelgesi, top_allocations, top_types, asyncio_task_count.")
    print("   - Leak: stop sonrası task sayısı azalıyor mu? gc.collect() sonrası obje sayısı düşüyor mu?")
    print("")
    print("Snapshot log:", _RAM_LOG)
    print("Rapor şablonu:", _REPORT)
    print("=" * 60)


def parse_log_lines(limit: int = 100):
    """Son limit satırı parse et; tablo için kullanılabilir."""
    if not _RAM_LOG.exists():
        print("Log yok:", _RAM_LOG)
        return []
    lines = _RAM_LOG.read_text(encoding="utf-8", errors="replace").strip().split("\n")
    rows = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main():
    os.chdir(_PROJECT_ROOT)
    if len(sys.argv) > 1 and sys.argv[1] == "parse":
        rows = parse_log_lines(200)
        print(f"Parsed {len(rows)} lines from {_RAM_LOG}")
        for i, r in enumerate(rows[-10:]):
            ts = r.get("ts", "")
            label = r.get("label", "")
            rss = r.get("rss_mb", 0)
            task = r.get("asyncio_task_count", 0)
            print(f"  {ts} label={label} rss_mb={rss} task_count={task}")
        return 0
    print_instructions()
    return 0


if __name__ == "__main__":
    sys.exit(main())
